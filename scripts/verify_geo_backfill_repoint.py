#!/usr/bin/env python3
"""
Before/after verification for the 2026-08-19 repoint of
backfill_trade_results_geo.py onto the canonical TradeEvaluator (see
brain/decisions/2026-08-19-trade-evaluator-repoint.md).

Extracts the PRE-repoint evaluate_trade() function directly from a given
git revision (default: the commit immediately before the repoint) and
compares its output against the CURRENT, in-repo (post-repoint, hardened)
monitoring.trade_evaluator.TradeEvaluator.evaluate_trade() -- across two
populations:

  1. Every already-evaluated (trade_result IN ('won','lost')) Geo/Elections
     trade -- the same population scripts/compare_trade_evaluators.py used.
  2. The CURRENT stuck-pending population that backfill_trade_results_geo.py
     --dry-run would actually fetch today (fetch_pending_trades' own SQL,
     re-executed here unmodified in shape).

A test that would pass regardless of whether the repoint changed anything
would prove nothing; this one would fail if either (a) TradeEvaluator's
hardened side-handling produces a different result than the old local
function on any real row, or (b) the repoint's mechanical wiring (dict
construction, added `outcome` column, method call shape) introduced a
transcription error.

Read-only. Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.trade_evaluator import TradeEvaluator

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVALUATED_SQL = """
    SELECT t.trade_id, t.outcome_bet, t.outcome, t.side, m.winning_outcome, t.trade_result
    FROM trades t JOIN markets m ON m.market_id = t.market_id
    WHERE t.trade_result IN ('won', 'lost') AND m.category IN ('Geopolitics', 'Elections')
"""

PENDING_SQL = """
    SELECT t.trade_id, t.outcome_bet, t.outcome, t.side, m.winning_outcome
    FROM trades t JOIN markets m ON m.market_id = t.market_id
    WHERE (t.trade_result = 'pending' OR t.trade_result IS NULL)
      AND m.resolved = 1
      AND m.winning_outcome IS NOT NULL
      AND m.winning_outcome NOT IN ('unknown', '')
      AND m.category IN ('Geopolitics', 'Elections')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND t.timestamp <= datetime('now')
"""


def load_pre_repoint_evaluate_trade(rev: str):
    """Extract the module-level evaluate_trade() function as it existed at
    `rev`, by execing that revision's file content in an isolated namespace.
    Avoids hand-transcribing the old logic (transcription risk)."""
    blob = subprocess.run(
        ["git", "show", f"{rev}:scripts/backfill_trade_results_geo.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    ns: dict = {
        "__name__": "pre_repoint_geo_backfill",
        "__file__": os.path.join(REPO_ROOT, "scripts", "backfill_trade_results_geo.py"),
    }
    # The old module runs sys.path.insert / imports column_definitions at
    # module scope; harmless (idempotent) to exec here since we only need
    # the evaluate_trade function object out of the namespace afterward.
    exec(compile(blob, f"<git:{rev}:backfill_trade_results_geo.py>", "exec"), ns)
    if "evaluate_trade" not in ns:
        raise RuntimeError(f"revision {rev} has no module-level evaluate_trade() -- "
                            f"wrong revision, or the repoint predates it")
    return ns["evaluate_trade"]


def compare(conn, sql, old_fn, new_evaluator, max_examples):
    compared = 0
    agree = 0
    disagreements = []
    for row in conn.execute(sql):
        compared += 1
        old_result = old_fn(row["outcome_bet"], row["side"], row["winning_outcome"])
        new_result = new_evaluator.evaluate_trade(
            {"outcome_bet": row["outcome_bet"], "outcome": row["outcome"], "side": row["side"]},
            row["winning_outcome"],
        )
        if old_result == new_result:
            agree += 1
        elif len(disagreements) < max_examples:
            disagreements.append({
                "trade_id": row["trade_id"], "outcome_bet": row["outcome_bet"], "outcome": row["outcome"],
                "side": row["side"], "winning_outcome": row["winning_outcome"],
                "old_result": old_result, "new_result": new_result,
            })
    return {"compared": compared, "agree": agree, "disagree": compared - agree, "disagreement_examples": disagreements}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--pre-repoint-rev", default="HEAD",
                     help="git revision holding the pre-repoint file (default: HEAD, i.e. the last commit)")
    ap.add_argument("--max-examples", type=int, default=50)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    old_evaluate_trade = load_pre_repoint_evaluate_trade(args.pre_repoint_rev)
    new_evaluator = TradeEvaluator(None, None)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    evaluated_result = compare(conn, EVALUATED_SQL, old_evaluate_trade, new_evaluator, args.max_examples)
    pending_result = compare(conn, PENDING_SQL, old_evaluate_trade, new_evaluator, args.max_examples)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "pre_repoint_rev": args.pre_repoint_rev,
        "already_evaluated_population": evaluated_result,
        "current_stuck_pending_population": pending_result,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"geo_backfill_repoint_verification_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"[already-evaluated] compared={evaluated_result['compared']} "
          f"agree={evaluated_result['agree']} disagree={evaluated_result['disagree']}")
    print(f"[stuck-pending]     compared={pending_result['compared']} "
          f"agree={pending_result['agree']} disagree={pending_result['disagree']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
