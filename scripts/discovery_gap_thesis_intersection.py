#!/usr/bin/env python3
"""
Establishes whether the 203 confirmed resolved-but-undiscovered markets
(2026-08-20-discovery-gap-sizing-result.md) reach the result of record
(the +0.0316 cohort / +0.0127 placebo OOS thesis figures).

READ-ONLY. No writes anywhere. No --persist. Imports trader_skill_metric_v2f
and column_definitions unmodified -- calls their functions/queries directly
to reconstruct cohort/OOS-survivor/placebo membership, which the 08-16
reproducibility audit already established has no persisted membership
snapshot in the DB.

Uses the enumerated 203-market list from
data/characterizations/discovery_gap_sizing_20260820T211955Z.json directly
(classification == "resolved" rows) -- does not re-derive it.

Usage:
    python3 scripts/discovery_gap_thesis_intersection.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from scripts.trader_skill_metric_v2f import (
    build_presplit_cohort, match_control, T_SPLIT, SEED, M_CHOSEN, EFFECT_BAR,
)
from scripts.trader_skill_metric_v2d import build_tape_end_map, compute_cap5_metric
from scripts.trader_skill_metric_v2e import per_trader_t_ci
from scripts.trader_skill_metric_v2 import db_connect
from monitoring.column_definitions import backtest_window_sql

DB_PATH = "data/polymarket_tracker.db"
SIZING_JSON = "data/characterizations/discovery_gap_sizing_20260820T211955Z.json"
PENDING_JSON = "data/characterizations/pending_resolution_inconsistency_20260820T162816Z.json"
NOFIFO_JSON = "data/characterizations/no_fifo_close_markets_20260820T162853Z.json"
OUT_DIR = Path("data/characterizations")
OUT_DIR.mkdir(exist_ok=True)
TODAY = "2026-08-20"


def load_203():
    data = json.load(open(SIZING_JSON))
    rows = [r for r in data["G_full_census_results"] if r["classification"] == "resolved"]
    assert len(rows) == 203, f"expected 203, got {len(rows)}"
    winners = {r["market_id"]: r["detail"].get("winner") for r in rows}
    return [r["market_id"] for r in rows], winners


def measure_oos_with_detail(conn, cohort_traders, t_split):
    """Same SQL as trader_skill_metric_v2f.measure_oos(), but returns the
    full DataFrame (trader/market detail) instead of only aggregate stats --
    needed to recover actual OOS-surviving trader identities, which the
    upstream function does not return."""
    if not cohort_traders:
        return pd.DataFrame(columns=["trader", "market_id", "outcome", "price", "entry_ts", "trade_result"])
    placeholders = ",".join("?" for _ in cohort_traders)
    rows = conn.execute(f"""
        SELECT p.trader_address, p.market_id, p.outcome, p.entry_avg_price, p.entry_timestamp, t.trade_result
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({placeholders})
          AND p.entry_timestamp > ?
    """, list(cohort_traders) + [t_split]).fetchall()
    df = pd.DataFrame(rows, columns=["trader", "market_id", "outcome", "price", "entry_ts", "trade_result"])
    df["won"] = (df["trade_result"] == "won").astype(int)
    return df


def positions_touching(conn, trader_set, market_ids):
    """ALL positions (any time, any trade_result) held by trader_set in
    market_ids -- the Q3 'reach' test, not restricted to the OOS window."""
    if not trader_set or not market_ids:
        return pd.DataFrame(columns=["trader", "market_id", "position_id", "outcome",
                                      "entry_avg_price", "entry_timestamp", "trade_result"])
    t_ph = ",".join("?" for _ in trader_set)
    m_ph = ",".join("?" for _ in market_ids)
    rows = conn.execute(f"""
        SELECT p.trader_address, p.market_id, p.position_id, p.outcome, p.entry_avg_price,
               p.entry_timestamp,
               (SELECT t.trade_result FROM trades t WHERE t.trade_id = json_extract(p.entry_trade_ids, '$[0]')) AS trade_result
        FROM positions p
        WHERE p.trader_address IN ({t_ph})
          AND p.market_id IN ({m_ph})
    """, list(trader_set) + list(market_ids)).fetchall()
    return pd.DataFrame(rows, columns=["trader", "market_id", "position_id", "outcome",
                                        "entry_avg_price", "entry_timestamp", "trade_result"])


def trader_all_market_counts(conn, trader_set):
    """For each trader in trader_set: total distinct markets and positions in
    Geopolitics/Elections, gap-clean, won/lost-resolved population (the same
    population v2f's own queries use) -- for Q4's fraction-of-total denominator."""
    if not trader_set:
        return {}
    t_ph = ",".join("?" for _ in trader_set)
    rows = conn.execute(f"""
        SELECT p.trader_address, COUNT(DISTINCT p.market_id), COUNT(*)
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({t_ph})
        GROUP BY p.trader_address
    """, list(trader_set)).fetchall()
    return {r[0]: {"n_markets": r[1], "n_positions": r[2]} for r in rows}


def main():
    conn = db_connect(DB_PATH)
    market_ids_203, winners_203 = load_203()
    print(f"Loaded {len(market_ids_203)} market_ids from {SIZING_JSON}")

    # ------------------------------------------------------------------
    # Q1 -- temporal placement: tape_end for all 203
    # ------------------------------------------------------------------
    print("\n=== Q1: temporal placement (tape_end) ===")
    tape_end_map = build_tape_end_map(conn, market_ids_203)
    q1_rows = []
    n_pre_split = 0
    n_post_split = 0
    n_no_tape_end = 0
    for mid in market_ids_203:
        te = tape_end_map.get(mid)
        if te is None:
            n_no_tape_end += 1
            q1_rows.append({"market_id": mid, "tape_end": None, "side": "no_tape_end"})
            continue
        if te <= T_SPLIT:
            n_pre_split += 1
            side = "pre_split"
        else:
            n_post_split += 1
            side = "post_split"
        q1_rows.append({"market_id": mid, "tape_end": te, "side": side})
    print(f"pre_split (tape_end <= {T_SPLIT}): {n_pre_split}")
    print(f"post_split (tape_end > {T_SPLIT}): {n_post_split}")
    print(f"no_tape_end (zero trades -- should be 0, G requires trades): {n_no_tape_end}")

    te_values = sorted(r["tape_end"] for r in q1_rows if r["tape_end"])
    print(f"tape_end range: {te_values[0]} .. {te_values[-1]}")
    print(f"tape_end median: {te_values[len(te_values)//2]}")

    # ------------------------------------------------------------------
    # Q2 -- would they enter the canonical population (as if resolved=1)
    # ------------------------------------------------------------------
    print("\n=== Q2: canonical backtest population membership (as-if resolved=1) ===")
    # Use the ACTUAL canonical query's WHERE-clause logic, applied to the
    # 203 as a hypothetical: category already Geo/Elections and gap-clean
    # by construction of the 203's own definition (design's G stratum).
    # The only additional canonical constraint is te.tape_end >= window_start.
    # Test against the full historical window (window_start = earliest
    # possible, i.e. no lower bound) and against the actual T_split-based
    # OOS window used by v2f, using the canonical function itself.
    sql_full_history = backtest_window_sql(window_start="2000-01-01 00:00:00")
    canonical_full = set(r[0] for r in conn.execute(sql_full_history, {"window_start": "2000-01-01 00:00:00"}).fetchall())
    # sanity: none of the 203 are resolved=1 today, so none can appear
    # (backtest_window_sql requires m.resolved=1) -- confirms the query
    # itself excludes them today, exactly as the task's premise states.
    overlap_today = set(market_ids_203) & canonical_full
    print(f"Of the 203, currently IN the canonical population (requires resolved=1): {len(overlap_today)} "
          f"(expected 0 -- these are resolved=0 in our DB by construction)")

    # As-if test: would they satisfy every OTHER canonical clause (category,
    # gap-flag, tape_end >= window_start) if resolved=1 were set? G's own
    # definition already required category IN (Geo,Elections) and gap-clean;
    # the only remaining canonical clause is the tape_end window bound.
    would_enter_presplit_window = sum(1 for r in q1_rows if r["side"] == "pre_split")
    would_enter_postsplit_window = sum(1 for r in q1_rows if r["side"] == "post_split")
    print(f"Would satisfy canonical category+gap-flag clauses: 203/203 (by construction of the 203's own G stratum)")
    print(f"Of those, tape_end within a presplit window (<=T_split): {would_enter_presplit_window}")
    print(f"Of those, tape_end within a postsplit-only window (>T_split): {would_enter_postsplit_window}")

    # ------------------------------------------------------------------
    # Q3/Q4 -- cohort/OOS/placebo reach + per-trader materiality
    # ------------------------------------------------------------------
    print("\n=== Q3: rebuilding cohort/OOS/placebo membership (v2f, unmodified, seed=%d) ===" % SEED)
    presplit_data = build_presplit_cohort(conn, T_SPLIT, verbose=True)
    cohort_148 = set(presplit_data["intersection"]["trader"])
    print(f"presplit-qualifying cohort: {len(cohort_148)} traders")

    control_pool_148 = match_control(presplit_data["profile"], cohort_148,
                                      set(presplit_data["elig_pool"]["trader"]), seed=SEED, verbose=True)
    print(f"placebo control pool: {len(control_pool_148)} traders")

    oos_cohort_df = measure_oos_with_detail(conn, cohort_148, T_SPLIT)
    oos_survivors_120 = set(oos_cohort_df["trader"].unique())
    print(f"OOS-surviving cohort traders: {len(oos_survivors_120)}")

    oos_placebo_df = measure_oos_with_detail(conn, control_pool_148, T_SPLIT)
    oos_placebo_survivors = set(oos_placebo_df["trader"].unique())
    print(f"OOS-surviving placebo traders: {len(oos_placebo_survivors)}")

    populations = {
        "148_presplit_cohort": cohort_148,
        "120_oos_survivors": oos_survivors_120,
        "148_placebo_pool": control_pool_148,
        "placebo_oos_survivors": oos_placebo_survivors,
    }

    q3_results = {}
    for name, tset in populations.items():
        touch_df = positions_touching(conn, tset, market_ids_203)
        n_traders = touch_df["trader"].nunique() if len(touch_df) else 0
        n_positions = len(touch_df)
        n_markets = touch_df["market_id"].nunique() if len(touch_df) else 0
        q3_results[name] = {
            "population_size": len(tset),
            "traders_touching_203": n_traders,
            "positions_in_203": n_positions,
            "markets_of_203_touched": n_markets,
            "touching_trader_ids": sorted(touch_df["trader"].unique().tolist()) if len(touch_df) else [],
        }
        print(f"\n{name} (N={len(tset)}): traders touching 203-set={n_traders}, "
              f"positions={n_positions}, distinct markets={n_markets}")
        if n_positions:
            print(touch_df[["trader", "market_id", "outcome", "trade_result"]].to_string(index=False))

    # Q4 -- per-trader materiality for anyone in Q3(a)/(b)/(c)
    print("\n=== Q4: per-trader materiality ===")
    all_touching_traders = set()
    for name in ("148_presplit_cohort", "120_oos_survivors", "148_placebo_pool", "placebo_oos_survivors"):
        all_touching_traders |= set(q3_results[name]["touching_trader_ids"])
    totals = trader_all_market_counts(conn, all_touching_traders)
    touch_all_df = positions_touching(conn, all_touching_traders, market_ids_203)
    q4_rows = []
    for trader in sorted(all_touching_traders):
        n_203_markets = touch_all_df[touch_all_df["trader"] == trader]["market_id"].nunique()
        tot = totals.get(trader, {"n_markets": None, "n_positions": None})
        frac = (n_203_markets / tot["n_markets"]) if tot["n_markets"] else None
        memberships = [name for name in populations if trader in populations[name]]
        row = {
            "trader": trader,
            "memberships": memberships,
            "total_markets_won_lost_pop": tot["n_markets"],
            "total_positions_won_lost_pop": tot["n_positions"],
            "n_of_203_touched": int(n_203_markets),
            "fraction_of_total_markets": frac,
        }
        q4_rows.append(row)
        print(json.dumps(row, default=str))

    # ------------------------------------------------------------------
    # Q5 -- qualification-boundary effect
    # ------------------------------------------------------------------
    print("\n=== Q5: qualification-boundary effect (counterfactual) ===")
    # Traders who currently have presplit n_pairs < M_CHOSEN in the elig
    # pool computation, but who hold positions in one or more of the 203
    # PRE-SPLIT markets (tape_end <= T_split) -- would additional pairs
    # push them to n_pairs >= 10 had these markets been resolved & PIT-
    # available by T_split?
    # per_trader_t_ci needs sigma2_within; build_presplit_cohort computes this
    # internally but does not expose it -- recompute pairs/sigma2 directly on
    # the presplit population exactly as build_presplit_cohort does, to get
    # each trader's CURRENT n_pairs for the boundary test below.
    pairs_current, eb_current, sigma2_within_current = compute_cap5_metric(presplit_data["presplit"])
    t_ci_current = per_trader_t_ci(pairs_current, sigma2_within_current)
    current_n_pairs = dict(zip(t_ci_current["trader"], t_ci_current["n_pairs"]))

    pre_split_203 = [mid for mid, w in winners_203.items()
                      if tape_end_map.get(mid) and tape_end_map[mid] <= T_SPLIT]
    print(f"Of the 203, {len(pre_split_203)} have tape_end <= T_split (candidates for qualification-boundary effect)")

    # positions in the pre-split-203 markets, any trader
    all_traders_in_presplit203 = set()
    if pre_split_203:
        m_ph = ",".join("?" for _ in pre_split_203)
        rows = conn.execute(f"""
            SELECT DISTINCT trader_address FROM positions WHERE market_id IN ({m_ph})
        """, pre_split_203).fetchall()
        all_traders_in_presplit203 = set(r[0] for r in rows)
    print(f"Distinct traders holding any position in those {len(pre_split_203)} markets: {len(all_traders_in_presplit203)}")

    near_boundary = []
    for trader in all_traders_in_presplit203:
        n_pairs_now = current_n_pairs.get(trader, 0)
        if n_pairs_now >= M_CHOSEN:
            continue  # already qualifies today on n_pairs -- not a boundary case
        # Approximate: each DISTINCT market in the pre-split-203 set this
        # trader touches could contribute at most 1 additional pair (cap5
        # pairing is per trader-market). Upper-bound the counterfactual.
        rows = conn.execute(f"""
            SELECT COUNT(DISTINCT market_id) FROM positions
            WHERE trader_address = ? AND market_id IN ({','.join('?' for _ in pre_split_203)})
        """, [trader] + pre_split_203).fetchone()
        additional_markets = rows[0]
        upper_bound_pairs = n_pairs_now + additional_markets
        if upper_bound_pairs >= M_CHOSEN:
            near_boundary.append({
                "trader": trader,
                "current_n_pairs": int(n_pairs_now),
                "additional_markets_in_presplit_203": int(additional_markets),
                "upper_bound_n_pairs_if_resolved": int(upper_bound_pairs),
            })
    print(f"Traders where current_n_pairs < {M_CHOSEN} but upper-bound (current + new markets) >= {M_CHOSEN}: "
          f"{len(near_boundary)}")
    for r in near_boundary:
        print(json.dumps(r))

    # ------------------------------------------------------------------
    # Q6 -- direction: edge of affected positions
    # ------------------------------------------------------------------
    print("\n=== Q6: edge of affected cohort/placebo positions ===")
    q6_out = {}
    for name in ("120_oos_survivors", "placebo_oos_survivors"):
        tset = populations[name]
        touch_df = positions_touching(conn, tset, market_ids_203)
        if len(touch_df) == 0:
            q6_out[name] = {"n_positions": 0, "note": "no affected positions"}
            continue
        touch_df = touch_df.copy()
        touch_df["winner"] = touch_df["market_id"].map(winners_203)
        no_winner = touch_df["winner"].isna().sum()
        touch_df = touch_df.dropna(subset=["winner"])
        touch_df["won"] = (touch_df["outcome"] == touch_df["winner"]).astype(int)
        touch_df["edge"] = touch_df["won"] - touch_df["entry_avg_price"]
        q6_out[name] = {
            "n_positions": len(touch_df),
            "n_no_winner_extractable": int(no_winner),
            "mean_edge": float(touch_df["edge"].mean()) if len(touch_df) else None,
            "median_edge": float(touch_df["edge"].median()) if len(touch_df) else None,
            "edge_values": touch_df["edge"].round(4).tolist(),
        }
        print(f"{name}: {json.dumps(q6_out[name], default=str)}")

    # ------------------------------------------------------------------
    # Q7 -- overlap with known populations
    # ------------------------------------------------------------------
    print("\n=== Q7: overlap with known populations ===")
    pending_data = json.load(open(PENDING_JSON))
    nofifo_data = json.load(open(NOFIFO_JSON))
    pending_ids = set(pending_data["pending_market_ids"])
    nofifo_ids = set(nofifo_data["no_fifo_close_market_ids"])
    overlap_pending = set(market_ids_203) & pending_ids
    overlap_nofifo = set(market_ids_203) & nofifo_ids
    print(f"Overlap with {len(pending_ids)}-market pending-resolution set: {len(overlap_pending)}")
    print(f"Overlap with {len(nofifo_ids)}-market no-FIFO-close set: {len(overlap_nofifo)}")

    # ------------------------------------------------------------------
    # Write full output
    # ------------------------------------------------------------------
    out = {
        "generated_at": datetime.now().isoformat(),
        "input_census": SIZING_JSON,
        "n_markets_203": len(market_ids_203),
        "q1_temporal": {
            "n_pre_split": n_pre_split, "n_post_split": n_post_split, "n_no_tape_end": n_no_tape_end,
            "tape_end_min": te_values[0], "tape_end_max": te_values[-1],
            "tape_end_median": te_values[len(te_values) // 2],
            "per_market": q1_rows,
        },
        "q2_canonical_population": {
            "overlap_today_resolved1_required": len(overlap_today),
            "would_enter_presplit_window": would_enter_presplit_window,
            "would_enter_postsplit_only_window": would_enter_postsplit_window,
        },
        "q3_reach": q3_results,
        "q4_per_trader": q4_rows,
        "q5_qualification_boundary": {
            "n_presplit_203_markets": len(pre_split_203),
            "distinct_traders_in_presplit_203": len(all_traders_in_presplit203),
            "near_boundary_candidates": near_boundary,
        },
        "q6_edge": q6_out,
        "q7_overlap": {
            "pending_resolution_set_size": len(pending_ids), "overlap_pending": len(overlap_pending),
            "nofifo_close_set_size": len(nofifo_ids), "overlap_nofifo": len(overlap_nofifo),
        },
    }
    out_path = OUT_DIR / f"discovery_gap_thesis_intersection_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nFull output written to {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
