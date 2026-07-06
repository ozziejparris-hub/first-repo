#!/usr/bin/env python3
"""
monitoring/column_definitions.py — Canonical column definitions and gate logic.

INTEGRATION CONTRACT 18.5.1 — Single Source of Truth
======================================================
This module is the single canonical source of truth for every LOCAL-AUTHORITATIVE
and DERIVED column recompute in the traders table, and for all Pool C / LEGENDARY
gate conditions.

RULE: Any change to a column definition, gate threshold, or tier boundary is made
HERE and nowhere else. Consumer scripts import constants and functions from this
module — they do not define their own copies.

This module has NO dependencies on other first-repo modules. It imports only the
Python standard library so that any consumer can import it without circular-import
risk.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone


# =============================================================================
# SECTION 1 — SQL FRAGMENT CONSTANTS
#
# These are SQL text fragments — correlated subqueries or expressions — NOT
# complete statements. Callers embed them inside UPDATE … SET col = (…) or
# inside CTEs.
#
# Alias contract for all fragments in this section:
#   tr       — alias for the trades table
#   m        — alias for the markets table
#   traders  — outer table being updated (must expose an 'address' column)
#
# Callers must satisfy the above aliases before embedding a fragment.
# =============================================================================

# geo_resolved_trades_count
# ─────────────────────────
# COUNT(DISTINCT market_id) for won/lost trades on Geopolitics/Elections
# markets, excluding the April 7–18 2026 trade-gap period.
#
# CANONICAL: no price filter. The price filter (tr.price BETWEEN 0.10 AND 0.80)
# belongs to ELO *scoring* only, not to pool-eligibility counting.
# update_geo_elo.py historically included the price filter in this count — that
# was the bug fixed by reconcile_geo_resolved_counts.py. This definition is the
# corrected, authoritative form.
GEO_RESOLVED_TRADES_COUNT_SQL = """
    SELECT COUNT(DISTINCT tr.market_id)
    FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trader_address = traders.address
      AND tr.trade_result IN ('won', 'lost')
      AND m.category IN ('Geopolitics', 'Elections')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
"""

# resolved_trades_count (general — all categories)
# ─────────────────────────────────────────────────
# COUNT(DISTINCT market_id) for all won/lost trades regardless of category.
#
# CANONICAL: no m.resolved = 1 filter. trade_result IN ('won', 'lost') is the
# authoritative signal that a market was resolved for this trader. Adding
# AND m.resolved = 1 creates a second redundant condition that can diverge if
# the markets.resolved flag lags trade_result updates. evaluate_new_trader_results.py
# currently includes m.resolved = 1 — that is non-canonical and will be removed
# when that script is repointed to this module.
RESOLVED_TRADES_COUNT_SQL = """
    SELECT COUNT(DISTINCT tr.market_id)
    FROM trades tr
    WHERE tr.trader_address = traders.address
      AND tr.trade_result IN ('won', 'lost')
"""


# =============================================================================
# SECTION 2 — GATE CONSTANTS
#
# Numeric thresholds and WHERE-clause fragments for pool membership and tier
# classification. Gate strings are built from the threshold constants via
# f-strings so a single constant change propagates to every gate that uses it.
# =============================================================================

# Threshold constants — the only place these numbers live.
GEO_ELO_POOL_SANITY_FLOOR:   float = 500.0    # minimum geo_elo_active for Pool C
GEO_ELO_LEGENDARY:           float = 2175.0
GEO_ELO_NEAR_LEGENDARY:      float = 1800.0
GEO_ELO_ELITE:               float = 1400.0
GEO_ELO_QUALIFIED:           float = 1000.0
POOL_C_MIN_RESOLVED_TRADES:  int   = 10        # minimum geo_resolved_trades_count for Pool C

# Pool C positive membership condition (WHERE fragment — no "WHERE" keyword).
#
# NULL handling: (col = 0 OR col IS NULL) admits traders whose suspect flags
# have never been set. This is intentional and canonical. The alternative bare
# (col = 0) silently excludes NULL-flagged traders in SQLite because NULL = 0
# evaluates to NULL (falsy), not TRUE. update_research_exclusions.py historically
# used the bare form, producing a slightly narrower pool than intended on each
# run before update_geo_elo.py corrected it. This module locks in the correct
# NULL-tolerant form for both callers.
POOL_C_GATE_WHERE = (
    f"geo_elo IS NOT NULL"
    f"\n  AND geo_elo_active >= {GEO_ELO_POOL_SANITY_FLOOR}"
    f"\n  AND geo_resolved_trades_count >= {POOL_C_MIN_RESOLVED_TRADES}"
    f"\n  AND geo_directionality_score IS NOT NULL"
    f"\n  AND bot_type IS NULL"
    f"\n  AND (wash_trade_suspect = 0 OR wash_trade_suspect IS NULL)"
    f"\n  AND (bot_suspect = 0 OR bot_suspect IS NULL)"
)

# Pool C UPDATE statements — always use as a pair: reset then populate.
POOL_C_RESET_SQL    = "UPDATE traders SET geo_accuracy_pool = 0"
POOL_C_POPULATE_SQL = f"UPDATE traders SET geo_accuracy_pool = 1 WHERE {POOL_C_GATE_WHERE}"

# LEGENDARY gate (WHERE fragment).
#
# CRITICAL: uses geo_elo_active, NOT geo_elo. Several legacy scripts use geo_elo
# for the LEGENDARY check; that is wrong because it ignores time-decay and
# overstates dormant traders' tier indefinitely. This is the canonical form.
LEGENDARY_GATE_WHERE = (
    f"geo_elo_active >= {GEO_ELO_LEGENDARY}"
    f"\n  AND geo_accuracy_pool = 1"
    f"\n  AND research_excluded = 0"
    f"\n  AND bot_type IS NULL"
)

# Convenience filter for research queries — always append to exclude noise traders.
RESEARCH_CLEAN_WHERE = "research_excluded = 0"

# Audit violation check — any pool member below the sanity floor is a data error.
POOL_C_SANITY_VIOLATION_WHERE = (
    f"geo_accuracy_pool = 1 AND geo_elo_active < {GEO_ELO_POOL_SANITY_FLOOR}"
)


# =============================================================================
# SECTION 3 — PURE PYTHON FUNCTIONS
#
# Column recomputes that require Python logic rather than a SQL fragment.
# All functions are pure (no DB I/O, no side effects). They can be tested
# directly and called inline by scripts that already have the raw values.
# =============================================================================

def compute_win_rate(successful_trades: int, resolved_trades_count: int) -> float:
    """
    win_rate = MIN(1.0, successful_trades / resolved_trades_count).

    Stored as a fraction in [0.0, 1.0]. The MIN(1.0) cap enforces the contract:
    if a trader placed multiple trades in a single market, successful_trades can
    exceed resolved_trades_count (which is a distinct-market count). Returns 0.0
    on divide-by-zero (no resolved trades).

    Source: reconcile_trader_aggregates.py:compute_win_rate — logic replicated exactly.
    """
    if resolved_trades_count and resolved_trades_count > 0:
        return min(1.0, successful_trades / resolved_trades_count)
    return 0.0


def compute_geo_elo_active(
    geo_elo: float | None,
    last_trade_ts: str | None,
) -> float | None:
    """
    Apply time-decay to geo_elo based on days since last qualifying geo trade.
    Formula: geo_elo * (0.5 ** (days_dormant / 180.0))

    A trader active today receives ~full score. At 180 days dormant the score
    halves; at 360 days it quarters. Returns None if either argument is None or
    if the timestamp string cannot be parsed.

    Source: update_geo_elo.py:_compute_geo_elo_active — logic replicated exactly.
    Note: the source annotated the return as float but it returns None on bad
    input; the correct annotation is float | None.
    """
    if last_trade_ts is None or geo_elo is None:
        return None
    try:
        ts = last_trade_ts.replace('Z', '+00:00').replace(' ', 'T')
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_dormant = (datetime.now(timezone.utc) - last).days
        decay = 0.5 ** (days_dormant / 180.0)
        return round(geo_elo * decay, 4)
    except Exception as e:
        print(f"[geo_elo_active] parse error for ts={last_trade_ts!r}: {e}", file=sys.stderr)
        return None


def derive_tier(
    geo_elo_active: float | None,
    geo_accuracy_pool: int,
    research_excluded: int,
    bot_type: str | None,
) -> str:
    """
    Canonical tier string from current trader state.

    Tiers in descending order:
      LEGENDARY       geo_elo_active >= 2175, clean pool member
      NEAR_LEGENDARY  geo_elo_active >= 1800, clean pool member
      ELITE           geo_elo_active >= 1400  (no pool requirement)
      QUALIFIED       geo_elo_active >= 1000  (no pool requirement)
      DEVELOPING      geo_elo_active set but < 1000
      UNRANKED        geo_elo_active is None

    Design note: ELITE and QUALIFIED do not require geo_accuracy_pool = 1. They
    represent raw ELO attainment regardless of pool membership. Only the top two
    tiers carry the full clean-pool invariant (pool=1, excl=0, bot_type=None).

    Source: snapshot_elo_scores.py:derive_tier — logic replicated exactly,
    thresholds now drawn from this module's constants.
    """
    if geo_elo_active is None:
        return 'UNRANKED'
    clean = (geo_accuracy_pool == 1 and research_excluded == 0 and bot_type is None)
    if geo_elo_active >= GEO_ELO_LEGENDARY and clean:
        return 'LEGENDARY'
    if geo_elo_active >= GEO_ELO_NEAR_LEGENDARY and clean:
        return 'NEAR_LEGENDARY'
    if geo_elo_active >= GEO_ELO_ELITE:
        return 'ELITE'
    if geo_elo_active >= GEO_ELO_QUALIFIED:
        return 'QUALIFIED'
    return 'DEVELOPING'


# =============================================================================
# SECTION 4 — ATOMIC DB HELPER
# =============================================================================

def refresh_pool_c(conn) -> tuple[int, int]:
    """
    Reset and repopulate geo_accuracy_pool in a single transaction.

    Returns (evicted_count, populated_count) where:
      evicted_count   = traders who were in Pool C before and are no longer
      populated_count = traders in Pool C after the refresh

    This is the canonical way to refresh Pool C. update_geo_elo.py and
    update_research_exclusions.py should call this instead of defining their
    own SQL, ensuring the gate definition and NULL-handling are always in sync.
    """
    prev = conn.execute(
        "SELECT COUNT(*) FROM traders WHERE geo_accuracy_pool = 1"
    ).fetchone()[0]
    with conn:
        conn.execute(POOL_C_RESET_SQL)
        populated = conn.execute(POOL_C_POPULATE_SQL).rowcount
    evicted = max(0, prev - populated)
    return (evicted, populated)


# =============================================================================
# SECTION 5 — DATA PROVENANCE
#
# Canonical data_source values, migration SQL, and backfill SQL for the four
# core tables: traders, markets, trades, positions.
#
# Migration protocol:
#   1. Run ALTER SQL below (O(1) schema-only on SQLite >= 3.37 — tested 3.45.1)
#   2. Run backfill SQL to correct rows that should not keep the DEFAULT
#   3. Verify distribution matches forensic-map projections
#   4. Only then add harness checks — never during migration
#
# Forward policy: every write path sets data_source at insertion time using the
# DEFAULT constants below. The allowed value frozensets are the canonical enum
# for each table; harness checks enforce membership post-migration.
# =============================================================================

# ── Canonical defaults (must match the DEFAULT clause in ALTER SQL) ───────────

DATA_SOURCE_TRADERS_DEFAULT   = 'live_feed'
DATA_SOURCE_MARKETS_DEFAULT   = 'live_monitoring'
DATA_SOURCE_TRADES_DEFAULT    = 'polymarket_api'
DATA_SOURCE_POSITIONS_DEFAULT = 'position_tracker'

# ── Allowed value sets (canonical enums per table) ────────────────────────────

# CONTRACT: data_source on traders is the governed 1:1 successor to discovery_source.
# Every value any INSERT path sets as discovery_source MUST be in this set.
DATA_SOURCE_TRADERS = frozenset({
    'live_feed',          # add_or_update_trader (discovery_source omitted → DEFAULT)
    'leaderboard',        # discover_leaderboard_traders.py
    'market_scan',        # discover_market_participants.py — market participant sweep
    'resolution_sweep',   # resolution_sweep.py — traders found during resolution pass
    'external_seed',      # imported from external dataset (e.g. HuggingFace parquet)
    'manual_watchlist',   # add_watched_trader.py
    'orphan_repair',      # added by orphan-repair to fix dangling trade refs
    'simulation',         # simulation framework — simulation_test.db only
    'backfill',           # one-off historical backfill script
    'blockchain_scan',    # future: on-chain scan discovery
})

DATA_SOURCE_MARKETS = frozenset({
    'live_monitoring',     # inserted during live monitoring window
    'historical_backfill', # Dec 11 2025 mass-import of historical Polymarket markets
    'background_backfill', # API gap-fill: background_backfill_worker / backfill_missing_markets
    'simulation',          # simulation framework — simulation_test.db only
    'manual_entry',        # hand-entered market record
    'api_refresh',         # refreshed via Polymarket API batch (refresh_markets)
    'stub_placeholder',    # placeholder before full market data was available
    'gamma_backfill_2026-07-02',  # O-16 Tier-1 backfill: per-ID Gamma resolution backfill
    'gamma_backfill_tier2_2026-07-06',  # O-16 Tier-2 backfill: remaining historical_backfill markets
})

DATA_SOURCE_TRADES = frozenset({
    'polymarket_api',      # fetched from Polymarket REST API (all existing rows)
    'blockchain_scan',     # future: discovered via on-chain scan at insertion time
    'background_backfill', # API gap-fill: background_backfill_worker trades
    'simulation',          # simulation framework — simulation_test.db only
    'backfill_import',     # imported from CSV or external backfill
    'computed',            # derived trade record not directly from API
})

DATA_SOURCE_POSITIONS = frozenset({
    'position_tracker',    # created by monitoring/position_tracker.py (FIFO tracking)
    'backfill_historical', # populated by a historical backfill operation
    'simulation',          # simulation framework — simulation_test.db only
    'synthetic_resolution', # position closed at market resolution (is_synthetic_close=1)
})

# ── Migration SQL — ALTER TABLE (O(1), run once per table) ───────────────────

DATA_SOURCE_ALTER_TRADERS = (
    "ALTER TABLE traders ADD COLUMN data_source TEXT NOT NULL "
    f"DEFAULT '{DATA_SOURCE_TRADERS_DEFAULT}'"
)
DATA_SOURCE_ALTER_MARKETS = (
    "ALTER TABLE markets ADD COLUMN data_source TEXT NOT NULL "
    f"DEFAULT '{DATA_SOURCE_MARKETS_DEFAULT}'"
)
DATA_SOURCE_ALTER_TRADES = (
    "ALTER TABLE trades ADD COLUMN data_source TEXT NOT NULL "
    f"DEFAULT '{DATA_SOURCE_TRADES_DEFAULT}'"
)
DATA_SOURCE_ALTER_POSITIONS = (
    "ALTER TABLE positions ADD COLUMN data_source TEXT NOT NULL "
    f"DEFAULT '{DATA_SOURCE_POSITIONS_DEFAULT}'"
)

# ── Backfill SQL — run after ALTER, before harness checks ────────────────────
#
# traders: discovery_source maps 1:1 to data_source for all existing values
#   (live_feed, leaderboard, external_seed, manual_watchlist, orphan_repair).
#   Sets data_source = discovery_source for all rows where discovery_source is
#   set; rows where discovery_source IS NULL keep the DEFAULT 'live_feed'.
DATA_SOURCE_BACKFILL_TRADERS_SQL = (
    "UPDATE traders SET data_source = discovery_source "
    "WHERE discovery_source IS NOT NULL"
)

# markets: Dec 11 2025 last_checked date identifies the 203K historical backfill.
#   All other rows keep the DEFAULT 'live_monitoring'.
DATA_SOURCE_BACKFILL_MARKETS_HISTORICAL_SQL = (
    "UPDATE markets SET data_source = 'historical_backfill' "
    "WHERE DATE(last_checked) = '2025-12-11'"
)

# trades: all existing rows are polymarket_api (matches the DEFAULT — this UPDATE
#   is a no-op but is included as an explicit audit-trail step).
DATA_SOURCE_BACKFILL_TRADES_SQL = (
    "UPDATE trades SET data_source = 'polymarket_api' WHERE data_source IS NULL"
)

# positions: synthetic closes (P&L computed at market resolution) get a distinct
#   provenance label. All others keep the DEFAULT 'position_tracker'.
DATA_SOURCE_BACKFILL_POSITIONS_SYNTHETIC_SQL = (
    "UPDATE positions SET data_source = 'synthetic_resolution' "
    "WHERE is_synthetic_close = 1"
)


# =============================================================================
# SELF-TEST  (python3 monitoring/column_definitions.py)
# =============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("column_definitions.py — self-test")
    print("=" * 70)

    # ── Threshold constants ───────────────────────────────────────────────
    print("\n── Threshold constants ──")
    print(f"  GEO_ELO_POOL_SANITY_FLOOR  : {GEO_ELO_POOL_SANITY_FLOOR}")
    print(f"  GEO_ELO_LEGENDARY          : {GEO_ELO_LEGENDARY}")
    print(f"  GEO_ELO_NEAR_LEGENDARY     : {GEO_ELO_NEAR_LEGENDARY}")
    print(f"  GEO_ELO_ELITE              : {GEO_ELO_ELITE}")
    print(f"  GEO_ELO_QUALIFIED          : {GEO_ELO_QUALIFIED}")
    print(f"  POOL_C_MIN_RESOLVED_TRADES : {POOL_C_MIN_RESOLVED_TRADES}")

    # ── SQL fragments ─────────────────────────────────────────────────────
    print("\n── SQL fragment: GEO_RESOLVED_TRADES_COUNT_SQL ──")
    print(GEO_RESOLVED_TRADES_COUNT_SQL)
    print("── SQL fragment: RESOLVED_TRADES_COUNT_SQL ──")
    print(RESOLVED_TRADES_COUNT_SQL)

    # ── Gate WHERE fragments ──────────────────────────────────────────────
    print("── Gate: POOL_C_GATE_WHERE ──")
    print(f"  {POOL_C_GATE_WHERE}")
    print(f"\n── Gate: LEGENDARY_GATE_WHERE ──")
    print(f"  {LEGENDARY_GATE_WHERE}")
    print(f"\n── Gate: POOL_C_SANITY_VIOLATION_WHERE ──")
    print(f"  {POOL_C_SANITY_VIOLATION_WHERE}")

    # ── Full UPDATE statements ────────────────────────────────────────────
    print(f"\n── POOL_C_RESET_SQL ──")
    print(f"  {POOL_C_RESET_SQL}")
    print(f"\n── POOL_C_POPULATE_SQL ──")
    print(POOL_C_POPULATE_SQL)

    # ── compute_win_rate ──────────────────────────────────────────────────
    print("\n── compute_win_rate ──")
    win_rate_cases: list[tuple[int, int, float]] = [
        (10, 10, 1.0),
        (15, 10, 1.0),   # cap at 1.0 even when successful > resolved
        ( 7, 10, 0.7),
        ( 0, 10, 0.0),
        ( 5,  0, 0.0),   # div-by-zero → 0.0
        ( 0,  0, 0.0),
    ]
    win_rate_ok = True
    for succ, res, expected in win_rate_cases:
        got = compute_win_rate(succ, res)
        ok = abs(got - expected) < 1e-9
        if not ok:
            win_rate_ok = False
        print(f"  compute_win_rate({succ:2d}, {res:2d}) = {got:.4f}  expected={expected:.4f}  {'OK' if ok else 'FAIL'}")

    # ── compute_geo_elo_active ────────────────────────────────────────────
    print("\n── compute_geo_elo_active ──")
    ts_cases = [
        ("recent (2d ago)   ", "2026-06-20T00:00:00Z"),
        ("180d ago          ", "2025-12-22T00:00:00Z"),
        ("365d ago          ", "2025-06-21T00:00:00Z"),
        ("space sep ts      ", "2026-06-20 00:00:00"),
        ("bad timestamp     ", "not-a-date"),
    ]
    for label, ts in ts_cases:
        result = compute_geo_elo_active(1500.0, ts)
        print(f"  compute_geo_elo_active(1500.0, {label!r}) = {result}")
    print(f"  compute_geo_elo_active(None,   ts) = {compute_geo_elo_active(None, '2026-06-20T00:00:00Z')}")
    print(f"  compute_geo_elo_active(1500.0, None) = {compute_geo_elo_active(1500.0, None)}")

    # ── derive_tier ───────────────────────────────────────────────────────
    print("\n── derive_tier ──")
    tier_cases: list[tuple] = [
        # (geo_elo_active, pool, excl, bot_type,  expected_tier)
        (2200.0, 1, 0, None,      'LEGENDARY'),
        (2200.0, 0, 0, None,      'ELITE'),        # not in pool → can't be LEGENDARY
        (2200.0, 1, 1, None,      'ELITE'),        # excluded → can't be LEGENDARY
        (2200.0, 1, 0, 'ARB_BOT', 'ELITE'),        # bot_type set → can't be LEGENDARY
        (2000.0, 1, 0, None,      'NEAR_LEGENDARY'),
        (2000.0, 0, 0, None,      'ELITE'),        # not in pool → can't be NEAR_LEGENDARY
        (1500.0, 1, 0, None,      'ELITE'),
        (1500.0, 0, 0, None,      'ELITE'),        # ELITE needs no pool membership
        (1200.0, 1, 0, None,      'QUALIFIED'),
        ( 800.0, 1, 0, None,      'DEVELOPING'),
        (  None, 1, 0, None,      'UNRANKED'),
    ]
    tier_ok = True
    for geo_act, pool, excl, bt, expected in tier_cases:
        got = derive_tier(geo_act, pool, excl, bt)
        ok = (got == expected)
        if not ok:
            tier_ok = False
        print(
            f"  derive_tier({str(geo_act):6}, pool={pool}, excl={excl}, bot={str(bt):<9}) "
            f"= {got!r:>16}  {'OK' if ok else 'FAIL'}"
        )

    # ── Section 5: provenance constants ──────────────────────────────────
    print("\n── Section 5: provenance defaults ──")
    print(f"  DATA_SOURCE_TRADERS_DEFAULT   : {DATA_SOURCE_TRADERS_DEFAULT!r}")
    print(f"  DATA_SOURCE_MARKETS_DEFAULT   : {DATA_SOURCE_MARKETS_DEFAULT!r}")
    print(f"  DATA_SOURCE_TRADES_DEFAULT    : {DATA_SOURCE_TRADES_DEFAULT!r}")
    print(f"  DATA_SOURCE_POSITIONS_DEFAULT : {DATA_SOURCE_POSITIONS_DEFAULT!r}")

    print("\n── Section 5: ALTER SQL (structural check) ──")
    s5_ok = True
    for name, sql, default in [
        ("traders",   DATA_SOURCE_ALTER_TRADERS,   DATA_SOURCE_TRADERS_DEFAULT),
        ("markets",   DATA_SOURCE_ALTER_MARKETS,   DATA_SOURCE_MARKETS_DEFAULT),
        ("trades",    DATA_SOURCE_ALTER_TRADES,    DATA_SOURCE_TRADES_DEFAULT),
        ("positions", DATA_SOURCE_ALTER_POSITIONS, DATA_SOURCE_POSITIONS_DEFAULT),
    ]:
        ok = (
            f"ALTER TABLE {name} ADD COLUMN data_source TEXT NOT NULL" in sql
            and f"DEFAULT '{default}'" in sql
        )
        if not ok:
            s5_ok = False
        print(f"  {name:<10}: {'OK' if ok else 'FAIL'}  {sql!r}")

    print("\n── Section 5: backfill SQL (non-empty check) ──")
    for name, sql in [
        ("traders",   DATA_SOURCE_BACKFILL_TRADERS_SQL),
        ("markets",   DATA_SOURCE_BACKFILL_MARKETS_HISTORICAL_SQL),
        ("trades",    DATA_SOURCE_BACKFILL_TRADES_SQL),
        ("positions", DATA_SOURCE_BACKFILL_POSITIONS_SYNTHETIC_SQL),
    ]:
        ok = bool(sql.strip())
        if not ok:
            s5_ok = False
        print(f"  {name:<10}: {'OK' if ok else 'FAIL'}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n── Summary ──")
    if win_rate_ok and tier_ok and s5_ok:
        print("  All assertions passed.")
    else:
        failures = []
        if not win_rate_ok:
            failures.append("compute_win_rate")
        if not tier_ok:
            failures.append("derive_tier")
        if not s5_ok:
            failures.append("section_5_provenance")
        print(f"  FAILURES in: {', '.join(failures)}")
        sys.exit(1)
