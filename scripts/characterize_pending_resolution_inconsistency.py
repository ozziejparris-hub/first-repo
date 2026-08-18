#!/usr/bin/env python3
"""
Characterize the markets.resolved=1 / trades.trade_result='pending'
inconsistency (first reported as 88 markets in
brain/decisions/2026-08-16-canonical-infrastructure-recon.md, reproduced as
101 in brain/decisions/2026-08-18-system-state-census.md via an ad-hoc
query). This script makes that count reproducible: it re-derives the
canonical population (backtest_window_sql's actual WHERE/JOIN shape,
monitoring/column_definitions.py:469-499), the v2f implicit population
(build_presplit_cohort's WHERE clause, scripts/trader_skill_metric_v2f.py),
and reports the pending-entry-trade subset of their symmetric difference,
bucketed by tape_end (MAX(trades.timestamp) per market -- the best
available timestamp; markets.resolution_date is documented elsewhere as
mutable with no audit trail, see O-36 / resolution_date COALESCE-guard
docs, and is NOT used here as the bucketing key for that reason).

Read-only against the production DB. Writes one JSON artifact per run
(timestamped, not overwritten) recording the generating parameters
(window_end, db path, run timestamp) alongside the results, per the
project's committed-script/durable-artifact convention.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
DEFAULT_WINDOW_END = "2026-04-01 00:00:00"  # T_split, scripts/trader_skill_metric_v2f.py:135

TAPE_END_CTE = "SELECT market_id, MAX(timestamp) AS tape_end FROM trades GROUP BY market_id"

CANONICAL_BASE_WHERE = (
    "m.resolved = 1"
    " AND m.category IN ('Geopolitics', 'Elections')"
    " AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)"
)


def canonical_market_ids(conn, window_end):
    q = f"""
        WITH tape_end AS ({TAPE_END_CTE})
        SELECT m.market_id
        FROM markets m JOIN tape_end te ON te.market_id = m.market_id
        WHERE {CANONICAL_BASE_WHERE}
          AND te.tape_end < ?
    """
    return {r[0] for r in conn.execute(q, (window_end,)).fetchall()}


def v2f_market_ids(conn, window_end):
    # Mirrors build_presplit_cohort's WHERE clause, scripts/trader_skill_metric_v2f.py:236-247,
    # projected to distinct market_id (per 2026-08-16-canonical-infrastructure-recon.md Query B).
    q = f"""
        WITH tape_end AS ({TAPE_END_CTE})
        SELECT DISTINCT p.market_id
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        JOIN tape_end te ON te.market_id = p.market_id
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND te.tape_end <= ?
    """
    return {r[0] for r in conn.execute(q, (window_end,)).fetchall()}


def pending_subset(conn, candidate_market_ids):
    """Of candidate_market_ids (canonical-only, i.e. symmetric-diff markets),
    which ones have >=1 position AND every position's entry trade has
    trade_result='pending' -- the exact 08-16 definition of the 88/101
    population (not just 'any trade pending')."""
    if not candidate_market_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_market_ids)
    ids = list(candidate_market_ids)
    has_positions = {
        r[0] for r in conn.execute(
            f"SELECT DISTINCT market_id FROM positions WHERE market_id IN ({placeholders})", ids
        ).fetchall()
    }
    not_all_pending = {
        r[0] for r in conn.execute(
            f"""
            SELECT DISTINCT p.market_id
            FROM positions p
            JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
            WHERE p.market_id IN ({placeholders}) AND t.trade_result != 'pending'
            """, ids
        ).fetchall()
    }
    return (has_positions & candidate_market_ids) - not_all_pending


def bucket_by_tape_end(conn, market_ids, granularity="month"):
    if not market_ids:
        return {}
    placeholders = ",".join("?" for _ in market_ids)
    fmt = "%Y-%m" if granularity == "month" else "%Y-%m-%d"
    rows = conn.execute(
        f"""
        WITH tape_end AS ({TAPE_END_CTE})
        SELECT strftime('{fmt}', te.tape_end) AS bucket, COUNT(*) AS n
        FROM tape_end te WHERE te.market_id IN ({placeholders})
        GROUP BY bucket ORDER BY bucket
        """, list(market_ids)
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--window-end", default=DEFAULT_WINDOW_END,
                     help="tape_end upper bound, matches T_split by default (2026-04-01 00:00:00)")
    ap.add_argument("--no-window", action="store_true",
                     help="drop the tape_end upper bound entirely (DB-wide, not scoped to the canonical pre-T_split population)")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations"))
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    window_end = None if args.no_window else args.window_end
    if window_end:
        canon = canonical_market_ids(conn, window_end)
        v2f = v2f_market_ids(conn, window_end)
    else:
        # DB-wide: window_end far in the future so the tape_end upper bound is a no-op.
        far_future = "2999-01-01 00:00:00"
        canon = canonical_market_ids(conn, far_future)
        v2f = v2f_market_ids(conn, far_future)

    canonical_only = canon - v2f
    pending = pending_subset(conn, canonical_only)
    buckets = bucket_by_tape_end(conn, pending, "month")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "params": {"window_end": window_end, "no_window": args.no_window},
        "canonical_population": len(canon),
        "v2f_population": len(v2f),
        "symmetric_diff_canonical_only": len(canonical_only),
        "pending_resolution_inconsistency_count": len(pending),
        "pending_market_ids": sorted(pending),
        "tape_end_month_buckets": buckets,
        "bucketing_note": "bucketed by MAX(trades.timestamp) per market (tape_end), NOT markets.resolution_date -- resolution_date is documented elsewhere as mutable with no audit trail and is not a reliable ordering key.",
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"pending_resolution_inconsistency_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"canonical_population={len(canon)} v2f_population={len(v2f)} "
          f"symmetric_diff={len(canonical_only)} pending_inconsistency_count={len(pending)}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
