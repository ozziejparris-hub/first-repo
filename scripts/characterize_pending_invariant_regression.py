#!/usr/bin/env python3
"""
Characterize the 2026-08-19 audit_invariants.py "pending on resolved
non-gap markets" regression (flagged traders: 0->60,345; geo/elections:
24,082->36,213). See brain/decisions/2026-08-19-pending-invariant-regression.md
for the full writeup this script generates evidence for.

Reproduces, read-only:
  - the two invariant checks' own predicates, live (trade-row counts, and
    distinct-market / distinct-trader counts for the same predicates, since
    the invariant itself only reports a trade-row count)
  - market-level overlap between the geo/elections invariant population and
    the disjoint 92-market resolved=1/trade_result='pending' population from
    scripts/characterize_pending_resolution_inconsistency.py
  - trader-level overlap between both invariant populations and the TRUE
    Objective-2 populations (pre-split cohort, OOS survivors, matched
    placebo, placebo survivors), re-derived via v2f's own committed
    functions -- same approach as scripts/characterize_orphan_sell_scope.py

Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2f import build_presplit_cohort, match_control, T_SPLIT, SEED
from scripts.characterize_orphan_sell_scope import true_oos_survivors
from scripts.trader_skill_metric_v2 import load_entries

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

# Mirrors scripts/audit_invariants.py check_pending_flagged / check_pending_geo predicates exactly.
FLAGGED_TRADE_ROWS_SQL = """
    SELECT COUNT(*) FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    JOIN traders t ON t.address  = tr.trader_address
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND t.is_flagged = 1
      AND t.research_excluded = 0
"""
GEO_TRADE_ROWS_SQL = """
    SELECT COUNT(*) FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.category IN ('Geopolitics', 'Elections')
"""
GEO_TRADERS_SQL = """
    SELECT DISTINCT tr.trader_address FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.category IN ('Geopolitics', 'Elections')
"""
GEO_MARKETS_SQL = """
    SELECT DISTINCT tr.market_id FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.category IN ('Geopolitics', 'Elections')
"""
FLAGGED_TRADERS_SQL = """
    SELECT DISTINCT tr.trader_address FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    JOIN traders t ON t.address  = tr.trader_address
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND t.is_flagged = 1
      AND t.research_excluded = 0
"""
GEO_DATA_SOURCE_SQL = """
    SELECT tr.data_source, COUNT(*) FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trade_result = 'pending'
      AND m.resolved = 1
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.category IN ('Geopolitics', 'Elections')
    GROUP BY 1
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--pending92-artifact", default=None,
                     help="path to a characterize_pending_resolution_inconsistency.py output JSON; "
                          "defaults to the newest file in data/characterizations/ matching that prefix")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()

    flagged_trade_rows = cur.execute(FLAGGED_TRADE_ROWS_SQL).fetchone()[0]
    geo_trade_rows = cur.execute(GEO_TRADE_ROWS_SQL).fetchone()[0]
    geo_traders = {r[0] for r in cur.execute(GEO_TRADERS_SQL).fetchall()}
    geo_markets = {r[0] for r in cur.execute(GEO_MARKETS_SQL).fetchall()}
    flagged_traders = {r[0] for r in cur.execute(FLAGGED_TRADERS_SQL).fetchall()}
    geo_data_source = dict(cur.execute(GEO_DATA_SOURCE_SQL).fetchall())

    # --- market-level overlap against the disjoint 92-market population ---
    pending92_path = args.pending92_artifact
    if pending92_path is None:
        cand_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")
        cands = sorted(f for f in os.listdir(cand_dir) if f.startswith("pending_resolution_inconsistency_"))
        pending92_path = os.path.join(cand_dir, cands[-1]) if cands else None
    pending92_ids = set()
    if pending92_path and os.path.exists(pending92_path):
        with open(pending92_path) as f:
            pending92_ids = set(json.load(f)["pending_market_ids"])

    # --- trader-level overlap against the TRUE Objective-2 populations ---
    load_entries(conn)
    presplit_data = build_presplit_cohort(conn, T_SPLIT)
    true_cohort = set(presplit_data["intersection"]["trader"])
    elig_pool = set(presplit_data["elig_pool"]["trader"])
    true_placebo_pool = match_control(presplit_data["profile"], true_cohort, elig_pool, seed=SEED)
    true_cohort_survivors = true_oos_survivors(conn, true_cohort, T_SPLIT)
    true_placebo_survivors = true_oos_survivors(conn, true_placebo_pool, T_SPLIT)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "pending92_artifact_used": pending92_path,
        "invariant_predicate_unit": "trade rows (COUNT(*) FROM trades JOIN markets [JOIN traders]), NOT markets and NOT (trader,market) pairs",
        "live_readings": {
            "check_pending_flagged_trade_rows": flagged_trade_rows,
            "check_pending_geo_trade_rows": geo_trade_rows,
            "geo_distinct_markets": len(geo_markets),
            "geo_distinct_traders": len(geo_traders),
            "flagged_distinct_traders": len(flagged_traders),
        },
        "audit_json_readings_this_morning": {
            "date": "2026-08-19", "run_at": "2026-08-19T06:02:09",
            "pending_flagged": 60345, "pending_geo": 36213,
        },
        "audit_json_readings_prior_day": {
            "date": "2026-08-18", "run_at": "2026-08-18T06:02:43",
            "pending_flagged": 0, "pending_geo": 24082,
        },
        "geo_population_data_source_breakdown": geo_data_source,
        "market_overlap_92_vs_geo_invariant": {
            "pending92_market_count": len(pending92_ids),
            "geo_invariant_market_count": len(geo_markets),
            "intersection": len(pending92_ids & geo_markets),
            "pending92_minus_geo_invariant": len(pending92_ids - geo_markets),
            "note": "expect pending92 to be a strict subset of geo_invariant markets: 92 requires ALL "
                    "position entry-trades pending + canonical-symmetric-diff-only + tape_end<T_split; "
                    "the invariant requires only >=1 pending trade row, any category filter is Geo/Elections "
                    "only for the geo variant, DB-wide with no T_split bound.",
        },
        "true_objective2_membership": {
            "true_cohort_n": len(true_cohort),
            "true_cohort_survivors_n": len(true_cohort_survivors),
            "true_placebo_pool_n": len(true_placebo_pool),
            "true_placebo_survivors_n": len(true_placebo_survivors),
        },
        "cohort_overlap": {
            "geo_pending_traders_x_true_cohort": sorted(geo_traders & true_cohort),
            "geo_pending_traders_x_true_cohort_survivors": sorted(geo_traders & true_cohort_survivors),
            "geo_pending_traders_x_true_placebo_pool": sorted(geo_traders & true_placebo_pool),
            "geo_pending_traders_x_true_placebo_survivors": sorted(geo_traders & true_placebo_survivors),
            "flagged_pending_traders_x_true_cohort_NOW": sorted(flagged_traders & true_cohort),
            "note": "flagged_pending_traders_x_true_cohort_NOW is measured AFTER today's "
                    "evaluate_new_trader_results.py step already drained the flagged population to "
                    "(near-)zero; it does NOT reconstruct this morning's 60,345-row population, which "
                    "left no persisted snapshot (audit ran with verbose=False, examples=[]) and is not "
                    "reconstructable post-hoc.",
        },
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"pending_invariant_regression_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"flagged_trade_rows={flagged_trade_rows} geo_trade_rows={geo_trade_rows} "
          f"geo_markets={len(geo_markets)} geo_traders={len(geo_traders)}")
    print(f"cohort overlap: geo_x_cohort={len(geo_traders & true_cohort)} "
          f"geo_x_cohort_survivors={len(geo_traders & true_cohort_survivors)} "
          f"geo_x_placebo_pool={len(geo_traders & true_placebo_pool)} "
          f"geo_x_placebo_survivors={len(geo_traders & true_placebo_survivors)}")
    print(f"market overlap: pending92 ({len(pending92_ids)}) subset-of geo_invariant ({len(geo_markets)}): "
          f"intersection={len(pending92_ids & geo_markets)}, pending92-only={len(pending92_ids - geo_markets)}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
