#!/usr/bin/env python3
"""
Empirical convergence check between the canonical monitoring.trade_evaluator
.TradeEvaluator.evaluate_trade() and scripts.backfill_trade_results_geo
.evaluate_trade() -- the two implementations of win/loss determination
named in brain/decisions/2026-08-19-elo-write-architecture-recon.md as
"structurally identical but not the same function."

Runs BOTH implementations, read-only, against every already-evaluated
(trade_result IN ('won','lost')) Geopolitics/Elections trade, comparing
outputs row by row. Neither implementation is called with any DB/network
object attached that could cause a write -- TradeEvaluator.evaluate_trade()
itself is a pure function of its arguments (verified by reading
monitoring/trade_evaluator.py: no self.db/self.client reference inside the
method), instantiated here with (None, None) since those constructor args
are unused by evaluate_trade().

Also runs both against the stored trade_result as a three-way sanity check
(TradeEvaluator vs geo-backfill vs what's actually persisted), though the
task's primary question is TradeEvaluator vs geo-backfill agreement.

Read-only. Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.trade_evaluator import TradeEvaluator
from scripts.backfill_trade_results_geo import evaluate_trade as geo_evaluate_trade

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

FETCH_SQL = """
    SELECT t.trade_id, t.outcome_bet, t.outcome, t.side, m.winning_outcome, t.trade_result
    FROM trades t
    JOIN markets m ON m.market_id = t.market_id
    WHERE t.trade_result IN ('won', 'lost')
      AND m.category IN ('Geopolitics', 'Elections')
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None, help="cap rows compared (for a quick check)")
    ap.add_argument("--max-examples", type=int, default=50)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    sql = FETCH_SQL
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    te = TradeEvaluator(None, None)  # database/client unused by evaluate_trade()

    compared = 0
    te_vs_geo_agree = 0
    te_vs_geo_disagree = []
    te_vs_stored_mismatch = []
    geo_vs_stored_mismatch = []
    te_result_counts = {"won": 0, "lost": 0, "invalid": 0}
    geo_result_counts = {"won": 0, "lost": 0, "invalid": 0}

    cur = conn.execute(sql)
    for row in cur:
        compared += 1
        trade_dict = {
            "trade_id": row["trade_id"],
            "outcome_bet": row["outcome_bet"],
            "outcome": row["outcome"],
            "side": row["side"],
        }
        te_result = te.evaluate_trade(trade_dict, row["winning_outcome"])
        geo_result = geo_evaluate_trade(row["outcome_bet"], row["side"], row["winning_outcome"])

        te_result_counts[te_result] = te_result_counts.get(te_result, 0) + 1
        geo_result_counts[geo_result] = geo_result_counts.get(geo_result, 0) + 1

        if te_result == geo_result:
            te_vs_geo_agree += 1
        else:
            if len(te_vs_geo_disagree) < args.max_examples:
                te_vs_geo_disagree.append({
                    "trade_id": row["trade_id"], "outcome_bet": row["outcome_bet"],
                    "outcome": row["outcome"], "side": row["side"],
                    "winning_outcome": row["winning_outcome"], "stored_trade_result": row["trade_result"],
                    "trade_evaluator_result": te_result, "geo_backfill_result": geo_result,
                })

        if te_result != row["trade_result"] and len(te_vs_stored_mismatch) < args.max_examples:
            te_vs_stored_mismatch.append({
                "trade_id": row["trade_id"], "stored": row["trade_result"], "trade_evaluator_result": te_result,
            })
        if geo_result != row["trade_result"] and len(geo_vs_stored_mismatch) < args.max_examples:
            geo_vs_stored_mismatch.append({
                "trade_id": row["trade_id"], "stored": row["trade_result"], "geo_backfill_result": geo_result,
            })

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "population": "trade_result IN ('won','lost') AND markets.category IN ('Geopolitics','Elections')",
        "rows_compared": compared,
        "trade_evaluator_vs_geo_backfill": {
            "agree": te_vs_geo_agree,
            "disagree": compared - te_vs_geo_agree,
            "disagreement_examples": te_vs_geo_disagree,
        },
        "trade_evaluator_result_distribution": te_result_counts,
        "geo_backfill_result_distribution": geo_result_counts,
        "trade_evaluator_vs_stored_trade_result": {
            "mismatch_count": len(te_vs_stored_mismatch) if len(te_vs_stored_mismatch) < args.max_examples
                              else f">= {args.max_examples} (capped)",
            "examples": te_vs_stored_mismatch,
        },
        "geo_backfill_vs_stored_trade_result": {
            "mismatch_count": len(geo_vs_stored_mismatch) if len(geo_vs_stored_mismatch) < args.max_examples
                              else f">= {args.max_examples} (capped)",
            "examples": geo_vs_stored_mismatch,
        },
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"trade_evaluator_convergence_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"rows_compared={compared}")
    print(f"TradeEvaluator vs geo-backfill: agree={te_vs_geo_agree} disagree={compared - te_vs_geo_agree}")
    print(f"TradeEvaluator result distribution: {te_result_counts}")
    print(f"geo-backfill result distribution: {geo_result_counts}")
    print(f"TradeEvaluator vs stored trade_result mismatches (capped at {args.max_examples}): {len(te_vs_stored_mismatch)}")
    print(f"geo-backfill vs stored trade_result mismatches (capped at {args.max_examples}): {len(geo_vs_stored_mismatch)}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
