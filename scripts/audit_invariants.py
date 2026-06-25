#!/usr/bin/env python3
"""
Data-integrity audit harness for polymarket_tracker.db.

Runs invariant checks across Tier 1 (CRITICAL), Tier 2 (REGRESSION),
and Tier 3 (structural baseline) categories. Read-only against the four
core tables; only writes its JSON report.

Usage:
    python3 scripts/audit_invariants.py
    python3 scripts/audit_invariants.py --verbose   # print example violating rows
    python3 scripts/audit_invariants.py --alert     # Telegram alert on failures
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitoring.column_definitions as cd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DB_PATH    = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
OUTPUT_DIR = Path("/home/parison/trading-swarm/brain/agent-outputs/data-audit")

# ---------------------------------------------------------------------------
# FLOORS
# Update these constants as fixes land. Comment explains why the floor is
# that value: 0 = logically impossible state; N = current structural
# baseline to be driven down by a specific Teardown.
# ---------------------------------------------------------------------------

# ---- Tier 1 (floor = 0; CRITICAL if any row found) ----------------------
FLOOR_SUCC_GT_TOTAL     = 0  # impossible: won trades can't exceed total_trades
FLOOR_WINRATE_FRAC      = 0  # impossible: fraction-scale win_rate > 1.0 is nonsense
FLOOR_WINRATE_PCT       = 0  # impossible: percentage-scale win_rate > 100 is nonsense
FLOOR_SPEC_RATIO        = 0  # impossible: specialisation_ratio is a fraction [0..1]
FLOOR_GEO_ELO_RANGE     = 0  # impossible: geo_elo must be in [0, 5000] for pool members
FLOOR_GEO_POOL_SANITY   = 0  # impossible: pool member must satisfy the >= 500 sanity gate (commit af6fafb)
FLOOR_DUP_MARKET_ID     = 0  # impossible: market_id is PRIMARY KEY
FLOOR_CONDID_ORPHAN     = 0  # must stay 0 after condition_id → market_id JOIN fix (commit f9f748d)
FLOOR_GEO_RECON         = 0  # must stay 0 after reconcile_geo_resolved_counts.py fix (commit dac9b2b)

# ---- Tier 2 (floor = current value; REGRESSION if count grows) -----------
FLOOR_PENDING_FLAGGED   = 0       # stays 0 as long as daily evaluation keeps pace
FLOOR_PENDING_GEO       = 0       # stays 0 as long as daily evaluation keeps pace
FLOOR_UNKNOWN_CAT       = 122417  # denormalized-category-cache drift; deferred to Teardown 2
                                   # (drop-and-JOIN vs refresh decision, next session).
                                   # Known-growing baseline — alerts only on growth beyond this floor.
                                   # Expected until Teardown 2.

# Timestamp non-canonical counts per column.
# "Non-canonical" = the minority format for that column (i.e., the format
# that shouldn't be there).  Lower-bit floors are 0 because those columns
# are already uniform.
FLOOR_TS_TRADES         = 0      # trades.timestamp: all space-sep (YYYY-MM-DD HH:MM:SS)
FLOOR_TS_MARKET_END     = 946    # markets.end_date: 946 T-sep rows mixed in (minority)
FLOOR_TS_MARKET_RES     = 881    # markets.resolution_date: 881 T-sep rows (minority)
FLOOR_TS_TRADER_ELO     = 23163  # traders.elo_last_updated: 23,163 space-sep rows (T is dominant)
FLOOR_TS_POS_ENTRY      = 0      # positions.entry_timestamp: all T-sep
FLOOR_TS_POS_EXIT       = 0      # positions.exit_timestamp: all T-sep
FLOOR_TS_POS_CREATED    = 0      # positions.created_at: all space-sep
FLOOR_TS_POS_UPDATED    = 0      # positions.last_updated: all space-sep
# Deferred: mixed-format timestamp normalization planned for Teardown 3.
# Known-structural baseline — alerts only on growth beyond this floor.
# Set to last-observed total count (2026-06-18); expected until Teardown 3.
FLOOR_TS_TOTAL = 24996

FLOOR_DS_NULLS   = 0  # after backfill: any NULL is a new write-path omission
FLOOR_DS_INVALID = 0  # after backfill: any out-of-set value is a new write-path regression

# ---- Tier 3 (alert only on > 10% growth from floor) ---------------------
FLOOR_API_NO_LOCAL      = 114047  # traders with API total_trades but 0 local records — Teardown: discovery backfill
FLOOR_BUY_NO_POS        = 275254  # BUY trades with no position record — Teardown: position backfill
FLOOR_VOL_OUTLIERS      = 75      # traders with stored total_volume > $1B (accumulation bug candidates)
FLOOR_INVESTED_MISMATCH = 0       # total_invested vs SUM(entry_total_cost) divergence > 5%
FLOOR_SUCC_CONTRA       = 608     # traders where successful_trades > actual won trades + 5 — Teardown: recalculate_trader_stats.py

# Tier 3 regression threshold (grow by more than this fraction)
TIER3_THRESHOLD = 0.10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_examples(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> list:
    try:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        return [{"error": str(exc)}]


def _count(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> int:
    cur.execute(sql, params)
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Tier 1 invariants — CRITICAL if count > 0
# ---------------------------------------------------------------------------

def check_successful_gt_total(cur, verbose):
    count = _count(cur, "SELECT COUNT(*) FROM traders WHERE successful_trades > total_trades")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, total_trades, successful_trades "
            "FROM traders WHERE successful_trades > total_trades LIMIT 5")
    return ("successful_trades > total_trades", 1, FLOOR_SUCC_GT_TOTAL, count, examples)


def check_winrate_frac_scale(cur, verbose):
    """win_rate > 1.0 and <= 100 — stored as fraction but exceeds maximum of 1."""
    count = _count(cur,
        "SELECT COUNT(*) FROM traders WHERE win_rate > 1.0 AND win_rate <= 100")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, win_rate, total_trades, successful_trades FROM traders "
            "WHERE win_rate > 1.0 AND win_rate <= 100 LIMIT 5")
    return ("win_rate > 1.0 (fraction-scale violation)", 1, FLOOR_WINRATE_FRAC, count, examples)


def check_winrate_pct_scale(cur, verbose):
    """win_rate > 100 — percentage-scale data stored in a fraction field."""
    count = _count(cur, "SELECT COUNT(*) FROM traders WHERE win_rate > 100")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, win_rate, total_trades, successful_trades FROM traders "
            "WHERE win_rate > 100 LIMIT 5")
    return ("win_rate > 100 (percentage-scale corruption)", 1, FLOOR_WINRATE_PCT, count, examples)


def check_spec_ratio(cur, verbose):
    count = _count(cur,
        "SELECT COUNT(*) FROM traders WHERE specialisation_ratio > 1.0")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, specialisation_ratio, specialist_category FROM traders "
            "WHERE specialisation_ratio > 1.0 LIMIT 5")
    return ("specialisation_ratio > 1.0", 1, FLOOR_SPEC_RATIO, count, examples)


def check_geo_elo_range(cur, verbose):
    count = _count(cur,
        "SELECT COUNT(*) FROM traders "
        "WHERE geo_accuracy_pool = 1 AND (geo_elo < 0 OR geo_elo > 5000)")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, geo_elo, geo_elo_active FROM traders "
            "WHERE geo_accuracy_pool = 1 AND (geo_elo < 0 OR geo_elo > 5000) LIMIT 5")
    return ("geo_elo out of range [0,5000] for pool members", 1, FLOOR_GEO_ELO_RANGE, count, examples)


def check_geo_pool_sanity(cur, verbose):
    """Pool C member has geo_elo_active < GEO_ELO_POOL_SANITY_FLOOR — the sanity floor added in commit af6fafb."""
    count = _count(cur,
        f"SELECT COUNT(*) FROM traders WHERE {cd.POOL_C_SANITY_VIOLATION_WHERE}")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            f"SELECT address, geo_elo_active, geo_elo FROM traders "
            f"WHERE {cd.POOL_C_SANITY_VIOLATION_WHERE} LIMIT 5")
    return ("geo_accuracy_pool=1 with geo_elo_active < 500", 1, FLOOR_GEO_POOL_SANITY, count, examples)


def check_dup_market_id(cur, verbose):
    count = _count(cur, "SELECT COUNT(*) - COUNT(DISTINCT market_id) FROM markets")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT market_id, COUNT(*) AS cnt FROM markets "
            "GROUP BY market_id HAVING cnt > 1 LIMIT 5")
    return ("duplicate markets.market_id", 1, FLOOR_DUP_MARKET_ID, count, examples)


def check_condid_orphan(cur, verbose):
    """Trades whose market_id matches markets.condition_id only (not markets.market_id).
    Must stay 0: means the pre-fix broken JOIN pattern produced new orphan records."""
    count = _count(cur, """
        SELECT COUNT(*) FROM trades tr
        WHERE NOT EXISTS (SELECT 1 FROM markets m WHERE m.market_id = tr.market_id)
          AND EXISTS     (SELECT 1 FROM markets m WHERE m.condition_id = tr.market_id)
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT tr.trade_id, tr.market_id, tr.trader_address FROM trades tr "
            "WHERE NOT EXISTS (SELECT 1 FROM markets m WHERE m.market_id = tr.market_id) "
            "  AND EXISTS (SELECT 1 FROM markets m WHERE m.condition_id = tr.market_id) LIMIT 5")
    return ("trades only join via condition_id (JOIN-fix regression)", 1, FLOOR_CONDID_ORPHAN, count, examples)


def check_geo_recon(cur, verbose):
    """geo_resolved_trades_count stored value != recomputed COUNT(DISTINCT won/lost geo markets).
    Uses cd.GEO_RESOLVED_TRADES_COUNT_SQL as the reference computation — structurally
    prevents harness-vs-writer divergence (the root cause of the June-22 morning CRITICAL).
    Must stay 0 after reconcile_geo_resolved_counts.py fix."""
    _sub = cd.GEO_RESOLVED_TRADES_COUNT_SQL.strip()
    count = _count(cur, f"""
        SELECT COUNT(*) FROM traders
        WHERE (geo_accuracy_pool = 1 OR geo_elo IS NOT NULL)
          AND COALESCE(geo_resolved_trades_count, 0) != COALESCE(({_sub}), 0)
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, f"""
            SELECT traders.address, traders.geo_resolved_trades_count,
                   COALESCE(({_sub}), 0) AS recomputed
            FROM traders
            WHERE (geo_accuracy_pool = 1 OR geo_elo IS NOT NULL)
              AND COALESCE(geo_resolved_trades_count, 0) != COALESCE(({_sub}), 0)
            LIMIT 5
        """)
    return ("geo_resolved_trades_count mismatch vs recomputed", 1, FLOOR_GEO_RECON, count, examples)


# ---------------------------------------------------------------------------
# Tier 2 invariants — REGRESSION if count > floor
# ---------------------------------------------------------------------------

def check_pending_flagged(cur, verbose):
    """Pending trade_result on resolved, non-gap markets for flagged non-excluded traders."""
    count = _count(cur, """
        SELECT COUNT(*) FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        JOIN traders t ON t.address  = tr.trader_address
        WHERE tr.trade_result = 'pending'
          AND m.resolved = 1
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND t.is_flagged = 1
          AND t.research_excluded = 0
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT tr.trade_id, tr.trader_address, tr.market_id, m.title
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            JOIN traders t ON t.address  = tr.trader_address
            WHERE tr.trade_result = 'pending' AND m.resolved = 1
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
              AND t.is_flagged = 1 AND t.research_excluded = 0
            LIMIT 5
        """)
    return ("pending on resolved non-gap markets (flagged traders)", 2, FLOOR_PENDING_FLAGGED, count, examples)


def check_pending_geo(cur, verbose):
    """Pending trade_result on resolved, non-gap Geo/Elections markets."""
    count = _count(cur, """
        SELECT COUNT(*) FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trade_result = 'pending'
          AND m.resolved = 1
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND m.category IN ('Geopolitics', 'Elections')
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT tr.trade_id, tr.trader_address, tr.market_id, m.title, m.category
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trade_result = 'pending' AND m.resolved = 1
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
              AND m.category IN ('Geopolitics','Elections')
            LIMIT 5
        """)
    return ("pending on resolved non-gap geo/elections markets", 2, FLOOR_PENDING_GEO, count, examples)


def check_unknown_category(cur, verbose):
    """trades.market_category = 'Unknown' where the parent market has a known category."""
    count = _count(cur, """
        SELECT COUNT(*) FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.market_category = 'Unknown'
          AND m.category IS NOT NULL
          AND m.category != 'Unknown'
          AND m.category != ''
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT tr.trade_id, tr.market_id, tr.market_category,
                   m.category AS market_cat
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.market_category = 'Unknown'
              AND m.category IS NOT NULL
              AND m.category != 'Unknown' AND m.category != ''
            LIMIT 5
        """)
    return ("trades.market_category='Unknown' where market.category is known", 2, FLOOR_UNKNOWN_CAT, count, examples)


def check_timestamp_formats(cur, verbose):
    """Per-column non-canonical timestamp format counts.
    Canonical = the dominant format for each column; minority format = non-canonical.
    Always reports per-column detail; --verbose adds one example row per offending column."""

    # (table, column, canonical_is_T: bool, floor)
    # canonical_is_T=True  → canonical = T-sep; non-canonical = rows WITHOUT 'T'
    # canonical_is_T=False → canonical = space-sep; non-canonical = rows WITH 'T'
    col_specs = [
        ("trades",    "timestamp",       False, FLOOR_TS_TRADES),
        ("markets",   "end_date",        False, FLOOR_TS_MARKET_END),
        ("markets",   "resolution_date", False, FLOOR_TS_MARKET_RES),
        ("traders",   "elo_last_updated", True,  FLOOR_TS_TRADER_ELO),
        ("positions", "entry_timestamp",  True,  FLOOR_TS_POS_ENTRY),
        ("positions", "exit_timestamp",   True,  FLOOR_TS_POS_EXIT),
        ("positions", "created_at",       False, FLOOR_TS_POS_CREATED),
        ("positions", "last_updated",     False, FLOOR_TS_POS_UPDATED),
    ]

    detail = []
    total = 0
    for table, col, canonical_T, col_floor in col_specs:
        if canonical_T:
            sql = (f"SELECT COUNT(*) FROM {table} "
                   f"WHERE {col} IS NOT NULL AND {col} NOT LIKE '%T%'")
        else:
            sql = (f"SELECT COUNT(*) FROM {table} "
                   f"WHERE {col} IS NOT NULL AND {col} LIKE '%T%'")
        cnt = _count(cur, sql)
        total += cnt
        entry = {
            "column":       f"{table}.{col}",
            "canonical":    "T-sep" if canonical_T else "space-sep",
            "non_canonical": cnt,
            "floor":        col_floor,
            "status":       "REGRESSION" if cnt > col_floor else "PASS",
        }
        if verbose and cnt:
            if canonical_T:
                ex_sql = (f"SELECT {col} FROM {table} "
                          f"WHERE {col} IS NOT NULL AND {col} NOT LIKE '%T%' LIMIT 1")
            else:
                ex_sql = (f"SELECT {col} FROM {table} "
                          f"WHERE {col} IS NOT NULL AND {col} LIKE '%T%' LIMIT 1")
            cur.execute(ex_sql)
            row = cur.fetchone()
            if row:
                entry["example_value"] = row[0]
        detail.append(entry)

    # Per-column detail is always included as examples (it's metadata, not row data)
    return ("timestamp mixed formats (per-column breakdown)", 2, FLOOR_TS_TOTAL, total, detail)


def check_data_source_nulls(cur, verbose):
    """data_source IS NULL across all 4 core tables.
    Column is NOT NULL DEFAULT, so any NULL is a write-path omission regression."""
    tables = ["traders", "markets", "trades", "positions"]
    detail = []
    total = 0
    for table in tables:
        cnt = _count(cur, f"SELECT COUNT(*) FROM {table} WHERE data_source IS NULL")
        total += cnt
        detail.append({
            "table":      table,
            "null_count": cnt,
            "status":     "REGRESSION" if cnt > 0 else "PASS",
        })
    return ("data_source IS NULL (write-path omission)", 2, FLOOR_DS_NULLS, total, detail)


def check_data_source_invalid(cur, verbose):
    """data_source NOT IN canonical set, per table.
    IN-clause built from cd frozensets — shares one canonical source with write paths."""
    table_specs = [
        ("traders",   cd.DATA_SOURCE_TRADERS),
        ("markets",   cd.DATA_SOURCE_MARKETS),
        ("trades",    cd.DATA_SOURCE_TRADES),
        ("positions", cd.DATA_SOURCE_POSITIONS),
    ]
    detail = []
    total = 0
    for table, allowed_set in table_specs:
        in_clause = ",".join(f"'{v}'" for v in sorted(allowed_set))
        cnt = _count(cur,
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE data_source IS NOT NULL AND data_source NOT IN ({in_clause})")
        total += cnt
        entry = {
            "table":         table,
            "invalid_count": cnt,
            "allowed":       sorted(allowed_set),
            "status":        "REGRESSION" if cnt > 0 else "PASS",
        }
        if verbose and cnt:
            entry["examples"] = _fetch_examples(cur,
                f"SELECT data_source, COUNT(*) AS cnt FROM {table} "
                f"WHERE data_source IS NOT NULL AND data_source NOT IN ({in_clause}) "
                f"GROUP BY data_source LIMIT 5")
        detail.append(entry)
    return ("data_source not in canonical set (write-path regression)", 2, FLOOR_DS_INVALID, total, detail)


# ---------------------------------------------------------------------------
# Tier 3 invariants — REGRESSION if count > floor * (1 + TIER3_THRESHOLD)
# ---------------------------------------------------------------------------

def check_api_no_local(cur, verbose):
    """Traders with API-reported total_trades > 0 but zero local trade records."""
    count = _count(cur, """
        SELECT COUNT(*) FROM traders
        WHERE total_trades > 0
          AND NOT EXISTS (
              SELECT 1 FROM trades WHERE trades.trader_address = traders.address)
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, total_trades, win_rate FROM traders "
            "WHERE total_trades > 0 AND NOT EXISTS "
            "(SELECT 1 FROM trades WHERE trades.trader_address = traders.address) LIMIT 5")
    return ("traders with API total_trades but 0 local records", 3, FLOOR_API_NO_LOCAL, count, examples)


def check_buy_no_position(cur, verbose):
    """BUY trades with no corresponding position record for that trader+market."""
    count = _count(cur, """
        SELECT COUNT(*) FROM trades tr
        WHERE tr.side = 'BUY'
          AND NOT EXISTS (
              SELECT 1 FROM positions p
              WHERE p.trader_address = tr.trader_address
                AND p.market_id     = tr.market_id)
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT tr.trade_id, tr.trader_address, tr.market_id, tr.timestamp
            FROM trades tr
            WHERE tr.side = 'BUY'
              AND NOT EXISTS (
                  SELECT 1 FROM positions p
                  WHERE p.trader_address = tr.trader_address
                    AND p.market_id     = tr.market_id)
            LIMIT 5
        """)
    return ("BUY trades with no position record", 3, FLOOR_BUY_NO_POS, count, examples)


def check_vol_outliers(cur, verbose):
    """Traders with stored total_volume > $1B — likely a volume-accumulation bug."""
    count = _count(cur,
        "SELECT COUNT(*) FROM traders WHERE total_volume > 1000000000")
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur,
            "SELECT address, total_volume FROM traders "
            "WHERE total_volume > 1000000000 ORDER BY total_volume DESC LIMIT 5")
    return ("total_volume > $1B outliers", 3, FLOOR_VOL_OUTLIERS, count, examples)


def check_invested_mismatch(cur, verbose):
    """traders.total_invested diverges > 5% from SUM(positions.entry_total_cost)
    for closed positions only — matching the reconciler's own definition
    (reconcile_trader_aggregates.py: SUM WHERE status='closed').
    Excludes pnl_skip=1 traders: their PnL columns are deliberately preserved
    unreconciled because PnL computation failed permanently for them."""
    count = _count(cur, """
        SELECT COUNT(*) FROM (
            SELECT t.address
            FROM traders t
            JOIN positions p ON p.trader_address = t.address
            WHERE t.total_invested IS NOT NULL AND t.total_invested > 0
              AND (t.pnl_skip = 0 OR t.pnl_skip IS NULL)
              AND p.status = 'closed'
            GROUP BY t.address
            HAVING ABS(t.total_invested - SUM(p.entry_total_cost))
                   / t.total_invested > 0.05
        ) x
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT t.address, t.total_invested,
                   ROUND(SUM(p.entry_total_cost), 2) AS calc_invested,
                   ROUND(ABS(t.total_invested - SUM(p.entry_total_cost))
                         / t.total_invested * 100, 1) AS pct_diff
            FROM traders t
            JOIN positions p ON p.trader_address = t.address
            WHERE t.total_invested IS NOT NULL AND t.total_invested > 0
              AND (t.pnl_skip = 0 OR t.pnl_skip IS NULL)
              AND p.status = 'closed'
            GROUP BY t.address
            HAVING ABS(t.total_invested - SUM(p.entry_total_cost))
                   / t.total_invested > 0.05
            ORDER BY pct_diff DESC
            LIMIT 5
        """)
    return ("total_invested vs SUM(entry_total_cost) mismatch >5%", 3, FLOOR_INVESTED_MISMATCH, count, examples)


def check_succ_contradiction(cur, verbose):
    """successful_trades stored value > actual won-trade count + 5.
    Overlaps with the Tier-1 check but tracks the wider population where
    the gap exceeds a 5-trade tolerance (Teardown: recalculate_trader_stats)."""
    count = _count(cur, """
        SELECT COUNT(*) FROM (
            SELECT t.address
            FROM traders t
            JOIN trades tr ON tr.trader_address = t.address
              AND tr.trade_result = 'won'
            GROUP BY t.address
            HAVING t.successful_trades > COUNT(tr.trade_id) + 5
        ) x
    """)
    examples = []
    if verbose and count:
        examples = _fetch_examples(cur, """
            SELECT t.address, t.successful_trades,
                   COUNT(tr.trade_id) AS won_count,
                   t.successful_trades - COUNT(tr.trade_id) AS discrepancy
            FROM traders t
            JOIN trades tr ON tr.trader_address = t.address
              AND tr.trade_result = 'won'
            GROUP BY t.address
            HAVING t.successful_trades > COUNT(tr.trade_id) + 5
            ORDER BY discrepancy DESC
            LIMIT 5
        """)
    return ("successful_trades > actual won trades + 5 (Tier-3 population)", 3, FLOOR_SUCC_CONTRA, count, examples)


# ---------------------------------------------------------------------------
# All checks in display order
# ---------------------------------------------------------------------------
ALL_CHECKS = [
    # Tier 1
    check_successful_gt_total,
    check_winrate_frac_scale,
    check_winrate_pct_scale,
    check_spec_ratio,
    check_geo_elo_range,
    check_geo_pool_sanity,
    check_dup_market_id,
    check_condid_orphan,
    check_geo_recon,
    # Tier 2
    check_pending_flagged,
    check_pending_geo,
    check_unknown_category,
    check_timestamp_formats,
    check_data_source_nulls,
    check_data_source_invalid,
    # Tier 3
    check_api_no_local,
    check_buy_no_position,
    check_vol_outliers,
    check_invested_mismatch,
    check_succ_contradiction,
]


# ---------------------------------------------------------------------------
# Status logic
# ---------------------------------------------------------------------------

def determine_status(tier: int, floor: int, count: int) -> str:
    if tier == 1:
        return "CRITICAL" if count > 0 else "PASS"
    elif tier == 2:
        return "REGRESSION" if count > floor else "PASS"
    else:
        return "REGRESSION" if count > floor * (1 + TIER3_THRESHOLD) else "PASS"


# ---------------------------------------------------------------------------
# Telegram alert
# ---------------------------------------------------------------------------

async def _send_telegram_async(token: str, chat_id: str, message: str) -> None:
    from telegram import Bot
    bot = Bot(token=token)
    MAX = 4000
    if len(message) <= MAX:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML",
                               read_timeout=15, write_timeout=15)
    else:
        for chunk in [message[i:i+MAX] for i in range(0, len(message), MAX)]:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML",
                                   read_timeout=15, write_timeout=15)


def send_telegram_alert(results: list, summary: dict) -> None:
    token   = os.getenv("telegram_alerts_token")
    chat_id = os.getenv("telegram_chat_id")
    if not token or not chat_id:
        print("[TELEGRAM] Credentials not found — skipping alert.", file=sys.stderr)
        return

    criticals   = [r for r in results if r["status"] == "CRITICAL"]
    regressions = [r for r in results if r["status"] == "REGRESSION"]
    if not criticals and not regressions:
        return

    lines = [
        f"<b>🔍 DB Audit — {summary['audit_date']}</b>",
        (f"Checked {summary['total']} invariants: "
         f"{summary['critical']} CRITICAL, {summary['regression']} REGRESSION, "
         f"{summary['pass']} PASS"),
        "",
    ]
    if criticals:
        lines.append("<b>🚨 CRITICAL (Tier-1 violations):</b>")
        for r in criticals:
            lines.append(f"  • {r['name']} — {r['count']:,} rows")
        lines.append("")
    if regressions:
        lines.append("<b>⚠️ REGRESSIONS (above floor):</b>")
        for r in regressions:
            lines.append(f"  • {r['name']} — {r['count']:,} (floor {r['floor']:,})")

    try:
        asyncio.run(_send_telegram_async(token, chat_id, "\n".join(lines)))
        print("[TELEGRAM] Alert sent.")
    except Exception as exc:
        print(f"[TELEGRAM] Failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Audit runner
# ---------------------------------------------------------------------------

def run_audit(verbose: bool = False, alert: bool = False) -> tuple[int, int]:
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA busy_timeout = 120000")
    conn.execute("PRAGMA query_only = ON")  # belt-and-suspenders: prevent accidental writes
    cur = conn.cursor()

    results = []
    n = len(ALL_CHECKS)
    print(f"\nRunning {n} invariant checks against {DB_PATH.name} ...\n")

    STATUS_MARKER = {"PASS": "✓", "REGRESSION": "⚠", "CRITICAL": "✗"}

    for fn in ALL_CHECKS:
        name, tier, floor, count, examples = fn(cur, verbose)
        status = determine_status(tier, floor, count)
        results.append({
            "name":     name,
            "tier":     tier,
            "floor":    floor,
            "count":    count,
            "status":   status,
            "examples": examples,
        })
        marker = STATUS_MARKER[status]
        print(f"  [{marker}] T{tier}  {status:<12}  {count:>10,}  {name}")

    conn.close()

    n_pass       = sum(1 for r in results if r["status"] == "PASS")
    n_regression = sum(1 for r in results if r["status"] == "REGRESSION")
    n_critical   = sum(1 for r in results if r["status"] == "CRITICAL")
    n_violated   = n_regression + n_critical
    headline     = f"{n_violated} invariant{'s' if n_violated != 1 else ''} violated, {n_critical} critical."

    now = datetime.now()
    summary = {
        "audit_date": now.strftime("%Y-%m-%d"),
        "run_at":     now.isoformat(timespec="seconds"),
        "total":      len(results),
        "pass":       n_pass,
        "regression": n_regression,
        "critical":   n_critical,
        "headline":   headline,
    }

    # ---- stdout summary table ----
    print()
    print("=" * 62)
    print(f"  Total invariants : {summary['total']}")
    print(f"  PASS             : {n_pass}")
    print(f"  REGRESSION       : {n_regression}")
    print(f"  CRITICAL         : {n_critical}")
    print(f"  Headline         : {headline}")
    print("=" * 62)

    # ---- verbose: print example rows for every failing check ----
    if verbose:
        for r in results:
            if r["status"] != "PASS" and r["examples"]:
                print(f"\n  [{r['name']}]")
                for ex in r["examples"]:
                    print(f"    {ex}")

    # ---- JSON report ----
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{now.strftime('%Y-%m-%d')}-audit.json"
    out_path.write_text(json.dumps({"summary": summary, "checks": results},
                                   indent=2, default=str))
    print(f"\n  Report → {out_path}")

    if alert:
        send_telegram_alert(results, summary)

    return n_critical, n_regression


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket DB integrity audit harness — read-only.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print example violating rows for each failing check")
    parser.add_argument("--alert", action="store_true",
                        help="Send Telegram alert on CRITICAL or REGRESSION findings")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv("/home/parison/.env_trading")
    except ImportError:
        pass

    n_crit, _ = run_audit(verbose=args.verbose, alert=args.alert)
    # Exit contract (used by daily_maintenance.py):
    #   2 → Tier-1 CRITICAL found   (impossible state — caller should ABORT)
    #   0 → clean or REGRESSION-only (Telegram alert already sent; caller continues)
    sys.exit(2 if n_crit > 0 else 0)


if __name__ == "__main__":
    main()
