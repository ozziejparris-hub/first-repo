#!/usr/bin/env python3
"""
Materiality of the 2 true-placebo-survivor traders identified in
brain/decisions/2026-08-19-pending-invariant-regression.md as overlapping
the check_pending_geo stuck-pending population (audit_invariants.py).

For each trader: full candidate footprint in the geo/elections OOS
population (positions.entry_avg_price NOT NULL, non-gap, m.resolved=1,
category IN Geopolitics/Elections -- the exact shape build_presplit_cohort/
measure_oos query, minus the trade_result filter), split into positions
already evaluated (trade_result IN won/lost, i.e. currently counted toward
the placebo) vs stuck (trade_result='pending', i.e. silently dropped from
both the pre-split cohort query and the post-split measure_oos query --
confirmed by inspection, trader_skill_metric_v2f.py:245,326).

For the stuck subset: pre/post-T_split classification (tape_end,
market-level, matches build_presplit_cohort's own boundary; entry_timestamp,
position-level, matches measure_oos's own boundary -- reported separately,
not merged, since they answer different questions: qualification vs
measured edge), and a counterfactual won/lost + edge using the
position.outcome == market.winning_outcome rule -- verified empirically
against all 350,008 currently-evaluated positions in this population with
zero exceptions before being applied here (see EMPIRICAL_RULE_CHECK_SQL).

Does NOT recompute the placebo's actual weighted-bootstrap point_gap
(trader_skill_metric_v2f.py's cap5-weighted two-way clustered bootstrap) --
per task instruction, this reports exposure magnitude only and leaves the
"would it move the estimate" judgment to the reader.

Read-only. Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

T_SPLIT = "2026-04-01 00:00:00"
TRADERS = [
    "0x54b5eacb474921051d62ad0f6ae2f4fc31b92e90",
    "0x5cfd881133ff44d1f7b81ea8a819a30dfc39ca1b",
]

# Values from metric_v2f_oos_result as persisted 2026-08-15 (generator commit eaeabbc).
# Not re-derived here -- cited as-is, same convention as 2026-08-18-orphan-sell-scope.md.
PERSISTED_PLACEBO_N_POSITIONS = 2569
PERSISTED_PLACEBO_N_TRADERS = 110

EMPIRICAL_RULE_CHECK_SQL = """
    SELECT (p.outcome = m.winning_outcome) AS outcome_matches_winner, t.trade_result, COUNT(*)
    FROM positions p
    JOIN markets m ON m.market_id = p.market_id
    JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
    WHERE m.category IN ('Geopolitics', 'Elections')
      AND p.entry_avg_price IS NOT NULL
      AND t.trade_result IN ('won', 'lost')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    GROUP BY 1, 2
"""

FOOTPRINT_SQL = """
    SELECT p.position_id, p.market_id, p.outcome, p.entry_avg_price, p.entry_timestamp,
           t.trade_result, m.winning_outcome, m.title
    FROM positions p
    JOIN markets m ON m.market_id = p.market_id
    JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
    WHERE m.category IN ('Geopolitics', 'Elections')
      AND p.entry_avg_price IS NOT NULL
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.resolved = 1
      AND p.trader_address = ?
"""


def tape_end_for(conn, market_ids):
    if not market_ids:
        return {}
    placeholders = ",".join("?" for _ in market_ids)
    rows = conn.execute(
        f"SELECT market_id, MAX(timestamp) FROM trades WHERE market_id IN ({placeholders}) GROUP BY market_id",
        list(market_ids),
    ).fetchall()
    return dict(rows)


def verify_empirical_rule(conn):
    rows = conn.execute(EMPIRICAL_RULE_CHECK_SQL).fetchall()
    exceptions = [r for r in rows if bool(r[0]) != (r[1] == "won")]
    total = sum(r[2] for r in rows)
    return {"total_checked": total, "exceptions": exceptions, "rule_holds_without_exception": len(exceptions) == 0}


def per_trader_report(conn, addr):
    rows = conn.execute(FOOTPRINT_SQL, (addr,)).fetchall()
    cols = ["position_id", "market_id", "outcome", "entry_avg_price", "entry_timestamp",
            "trade_result", "winning_outcome", "title"]
    recs = [dict(zip(cols, r)) for r in rows]

    total_positions = len(recs)
    total_markets = len({r["market_id"] for r in recs})
    evaluated = [r for r in recs if r["trade_result"] in ("won", "lost")]
    stuck = [r for r in recs if r["trade_result"] == "pending"]

    tmap = tape_end_for(conn, list({r["market_id"] for r in stuck}))
    for r in stuck:
        te = tmap.get(r["market_id"])
        r["tape_end"] = te
        r["presplit_by_tape_end"] = bool(te is not None and te <= T_SPLIT)
        r["postsplit_by_entry_timestamp"] = bool(r["entry_timestamp"] > T_SPLIT)
        cf_won = 1 if r["outcome"] == r["winning_outcome"] else 0
        r["counterfactual_won"] = cf_won
        r["counterfactual_edge"] = cf_won - r["entry_avg_price"]

    cf_edges = [r["counterfactual_edge"] for r in stuck]

    return {
        "total_positions_full_footprint": total_positions,
        "total_markets_full_footprint": total_markets,
        "evaluated_positions_already_in_placebo_calc": len(evaluated),
        "stuck_pending_positions": len(stuck),
        "stuck_pending_markets": len({r["market_id"] for r in stuck}),
        "stuck_fraction_of_positions": round(len(stuck) / total_positions, 4) if total_positions else None,
        "stuck_fraction_of_markets": round(len({r["market_id"] for r in stuck}) / total_markets, 4) if total_markets else None,
        "stuck_presplit_by_tape_end": sum(1 for r in stuck if r["presplit_by_tape_end"]),
        "stuck_postsplit_by_entry_timestamp": sum(1 for r in stuck if r["postsplit_by_entry_timestamp"]),
        "counterfactual_won": sum(1 for r in stuck if r["counterfactual_won"] == 1),
        "counterfactual_lost": sum(1 for r in stuck if r["counterfactual_won"] == 0),
        "counterfactual_mean_edge_simple_unweighted": (sum(cf_edges) / len(cf_edges)) if cf_edges else None,
        "stuck_position_detail": stuck,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    conn = db_connect(args.db)

    rule_check = verify_empirical_rule(conn)
    if not rule_check["rule_holds_without_exception"]:
        print("WARNING: empirical won/lost rule has exceptions -- counterfactuals below are unreliable",
              file=sys.stderr)

    per_trader = {addr: per_trader_report(conn, addr) for addr in TRADERS}

    two_trader_evaluated = sum(r["evaluated_positions_already_in_placebo_calc"] for r in per_trader.values())
    two_trader_stuck = sum(r["stuck_pending_positions"] for r in per_trader.values())
    all_cf_edges = [d["counterfactual_edge"] for r in per_trader.values() for d in r["stuck_position_detail"]]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "traders": TRADERS,
        "empirical_won_lost_rule_check": {k: v for k, v in rule_check.items() if k != "exceptions"},
        "persisted_placebo_reference_2026_08_15": {
            "n_positions": PERSISTED_PLACEBO_N_POSITIONS,
            "n_traders": PERSISTED_PLACEBO_N_TRADERS,
            "note": "aggregate-only in metric_v2f_oos_result; no row-level snapshot exists to "
                    "confirm these 2 traders' exact historical contribution, only today's live re-derivation below",
        },
        "share_of_persisted_placebo": {
            "two_traders_evaluated_positions_sum": two_trader_evaluated,
            "two_traders_share_of_positions": round(two_trader_evaluated / PERSISTED_PLACEBO_N_POSITIONS, 5),
            "two_traders_share_of_traders": round(2 / PERSISTED_PLACEBO_N_TRADERS, 5),
            "two_traders_stuck_pending_positions_sum": two_trader_stuck,
            "stuck_as_fraction_of_persisted_placebo_n_positions": round(two_trader_stuck / PERSISTED_PLACEBO_N_POSITIONS, 5),
        },
        "combined_stuck_simple_mean_edge_UNWEIGHTED": (sum(all_cf_edges) / len(all_cf_edges)) if all_cf_edges else None,
        "combined_stuck_simple_mean_edge_note": "raw arithmetic mean across all determinable stuck positions from "
                                                 "both traders -- NOT the metric's actual cap5-weighted two-way "
                                                 "clustered-bootstrap point_gap; exposure-magnitude illustration only, "
                                                 "per task instruction not to recompute the placebo",
        "per_trader": per_trader,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"placebo_pending_exposure_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"empirical rule holds without exception: {rule_check['rule_holds_without_exception']} "
          f"({rule_check['total_checked']} positions checked)")
    for addr, r in per_trader.items():
        print(f"{addr}: {r['total_positions_full_footprint']} positions / {r['total_markets_full_footprint']} markets "
              f"total; {r['stuck_pending_positions']} stuck ({r['stuck_fraction_of_positions']:.1%} of positions, "
              f"{r['stuck_fraction_of_markets']:.1%} of markets); counterfactual won={r['counterfactual_won']} "
              f"lost={r['counterfactual_lost']}, mean edge={r['counterfactual_mean_edge_simple_unweighted']}")
    print(f"combined: {two_trader_stuck} stuck positions = "
          f"{result['share_of_persisted_placebo']['stuck_as_fraction_of_persisted_placebo_n_positions']:.4%} "
          f"of the persisted placebo's {PERSISTED_PLACEBO_N_POSITIONS} positions")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
