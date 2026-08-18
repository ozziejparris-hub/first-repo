#!/usr/bin/env python3
"""
Characterize the 166-markets-with-trades-but-no-FIFO-closed-position
component of the v2f-vs-canonical population shortfall (first reported in
brain/decisions/2026-08-16-canonical-infrastructure-recon.md; the sibling
88/103-market pending-trade_result component was characterized separately
in brain/decisions/2026-08-18-pending-resolution-inconsistency.md).

Reproduces the canonical population (backtest_window_sql's actual
WHERE/JOIN shape, monitoring/column_definitions.py:469-499) and the v2f
implicit population (build_presplit_cohort's WHERE clause,
scripts/trader_skill_metric_v2f.py:236-247), takes the canonical-only
symmetric difference, and reports the subset of it that has ZERO rows in
`positions` at all -- i.e. markets where the trades table has activity but
PositionTracker's FIFO matcher never produced a position (the 166/161
population, distinct from the pending-trade_result 88/104 population,
which DOES have position rows).

Read-only against the production DB. Writes one JSON artifact per run
(timestamped, not overwritten) recording the generating parameters
(window_end, db path, run timestamp) alongside the results.
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


def no_position_subset(conn, candidate_market_ids):
    """Of candidate_market_ids (canonical-only), which have ZERO rows in
    positions at all -- the zero-position/no-FIFO-close population, distinct
    from the pending-trade_result population (which has position rows)."""
    if not candidate_market_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_market_ids)
    ids = list(candidate_market_ids)
    has_positions = {
        r[0] for r in conn.execute(
            f"SELECT DISTINCT market_id FROM positions WHERE market_id IN ({placeholders})", ids
        ).fetchall()
    }
    return candidate_market_ids - has_positions


def orphan_sell_groups(conn, market_ids):
    """For the no-position markets, every (trader, market, outcome) group
    with trades but no position is expected -- by the failure-mode finding
    of this characterization -- to consist entirely of SELL trades with zero
    matching BUY trades anywhere in `trades` for that group. Returns the
    count of groups and how many fail to fit that pattern (buy_count > 0),
    so a future re-run can detect if a new/different failure mode appears."""
    if not market_ids:
        return {"groups": 0, "zero_buy_groups": 0, "nonzero_buy_groups": 0}
    placeholders = ",".join("?" for _ in market_ids)
    ids = list(market_ids)
    groups = conn.execute(
        f"SELECT DISTINCT trader_address, market_id, outcome FROM trades WHERE market_id IN ({placeholders})",
        ids,
    ).fetchall()
    zero_buy = 0
    nonzero_buy = 0
    for trader, mid, outcome in groups:
        n = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE trader_address=? AND market_id=? AND outcome=? AND side='BUY'",
            (trader, mid, outcome),
        ).fetchone()[0]
        if n == 0:
            zero_buy += 1
        else:
            nonzero_buy += 1
    return {"groups": len(groups), "zero_buy_groups": zero_buy, "nonzero_buy_groups": nonzero_buy}


def cohort_overlap(conn, market_ids):
    """Trader-level overlap between the no-position markets and the
    metric_v2f_intersection_cohort table (295-trader Objective-1
    significant/M>=10/edge>=0.02 superset -- the best available *persisted*
    proxy for the true 148-pre-split/120-post-split Objective-2 cohort,
    which has no persisted membership snapshot; see
    brain/decisions/2026-08-18-pending-resolution-inconsistency.md)."""
    if not market_ids:
        return {"cohort_superset_size": 0, "affected_traders": [], "affected_trade_rows": 0, "affected_markets": 0}
    placeholders = ",".join("?" for _ in market_ids)
    ids = list(market_ids)
    cohort = {r[0] for r in conn.execute("SELECT trader FROM metric_v2f_intersection_cohort").fetchall()}
    cohort_ph = ",".join("?" for _ in cohort)
    rows = conn.execute(
        f"""SELECT trader_address, market_id FROM trades
            WHERE market_id IN ({placeholders}) AND trader_address IN ({cohort_ph})""",
        ids + list(cohort),
    ).fetchall()
    affected_traders = sorted({r[0] for r in rows})
    affected_markets = sorted({r[1] for r in rows})
    return {
        "cohort_superset_size": len(cohort),
        "affected_traders": affected_traders,
        "affected_trade_rows": len(rows),
        "affected_markets": affected_markets,
    }


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


def category_and_outcome_mix(conn, market_ids, baseline_ids):
    def mix(ids, col):
        if not ids:
            return {}
        ph = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT {col}, COUNT(*) FROM markets WHERE market_id IN ({ph}) GROUP BY {col}", list(ids)).fetchall()
        return {str(r[0]): r[1] for r in rows}

    return {
        "no_position_category_mix": mix(market_ids, "category"),
        "baseline_category_mix": mix(baseline_ids, "category"),
        "no_position_winning_outcome_yes_no": {
            k: v for k, v in mix(market_ids, "winning_outcome").items() if k in ("Yes", "No")
        },
    }


def trade_count_distribution(conn, market_ids, baseline_ids):
    def counts(ids):
        if not ids:
            return []
        ph = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT COUNT(*) FROM trades WHERE market_id IN ({ph}) GROUP BY market_id", list(ids)).fetchall()
        return sorted(r[0] for r in rows)

    import statistics
    no_pos_counts = counts(market_ids)
    baseline_counts = counts(baseline_ids)
    return {
        "no_position_median_trades": statistics.median(no_pos_counts) if no_pos_counts else None,
        "no_position_n": len(no_pos_counts),
        "baseline_median_trades": statistics.median(baseline_counts) if baseline_counts else None,
        "baseline_n": len(baseline_counts),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--window-end", default=DEFAULT_WINDOW_END,
                     help="tape_end upper bound, matches T_split by default (2026-04-01 00:00:00)")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations"))
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    canon = canonical_market_ids(conn, args.window_end)
    v2f = v2f_market_ids(conn, args.window_end)
    canonical_only = canon - v2f
    no_pos = no_position_subset(conn, canonical_only)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "params": {"window_end": args.window_end},
        "canonical_population": len(canon),
        "v2f_population": len(v2f),
        "symmetric_diff_canonical_only": len(canonical_only),
        "no_fifo_close_count": len(no_pos),
        "no_fifo_close_market_ids": sorted(no_pos),
        "orphan_sell_check": orphan_sell_groups(conn, no_pos),
        "cohort_overlap": cohort_overlap(conn, no_pos),
        "tape_end_month_buckets": bucket_by_tape_end(conn, no_pos, "month"),
        "trade_count_distribution": trade_count_distribution(conn, no_pos, canon),
        "category_and_outcome_mix": category_and_outcome_mix(conn, no_pos, canon),
        "bucketing_note": "bucketed by MAX(trades.timestamp) per market (tape_end), NOT markets.resolution_date -- resolution_date is documented elsewhere as mutable with no audit trail and is not a reliable ordering key.",
        "cohort_note": "cohort_overlap uses metric_v2f_intersection_cohort (295-trader persisted superset) as a proxy for the true 148/120 Objective-2 cohort, which has no persisted membership snapshot as of 2026-08-18.",
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"no_fifo_close_markets_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"canonical_population={len(canon)} v2f_population={len(v2f)} "
          f"symmetric_diff={len(canonical_only)} no_fifo_close_count={len(no_pos)}")
    print(f"cohort overlap: {len(result['cohort_overlap']['affected_traders'])} traders, "
          f"{result['cohort_overlap']['affected_trade_rows']} trade rows, "
          f"{len(result['cohort_overlap']['affected_markets'])} markets")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
