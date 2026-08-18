#!/usr/bin/env python3
"""
Scope the orphan-SELL population drop (no-FIFO-close markets, characterized
in brain/decisions/2026-08-18-no-fifo-close-markets.md, commit 969d9a1)
against the ACTUAL result-of-record populations -- v2f's true pre-split-
qualifying cohort, its OOS survivors, and its matched placebo -- rather than
the 295-trader Objective-1 superset used as a proxy in that prior pass.

Read-only against the production DB throughout. Re-derives cohort/placebo
MEMBERSHIP using v2f's own existing functions (build_presplit_cohort,
match_control) -- does NOT recompute or report any new edge/CI/thesis
result; only trader-ID set membership is used, and today's reproduced
aggregate counts (n_cohort, n_survivors, n_placebo_survivors) are diffed
against metric_v2f_oos_result's persisted 2026-08-15 values so any drift
from data accrued since that canonical run is visible rather than silent.

Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import load_entries, db_connect
from scripts.trader_skill_metric_v2d import compute_cap5_metric
from scripts.trader_skill_metric_v2e import per_trader_t_ci
from scripts.trader_skill_metric_v2f import build_presplit_cohort, match_control, T_SPLIT, M_CHOSEN, EFFECT_BAR, SEED
from scripts.characterize_no_fifo_close_markets import (
    canonical_market_ids, v2f_market_ids, no_position_subset, orphan_sell_groups,
)

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

# Verified windows (not the task prompt's loose "2026-07-25 to 2026-08-07"):
# box-down per brain/decisions/2026-08-07-session-summary.md line 5;
# zero-trade window is the tighter, more relevant figure for trade-level overlap.
OUTAGE_BOX_DOWN = ("2026-07-24 21:46:00", "2026-08-07 09:37:00")
OUTAGE_ZERO_TRADE_WINDOW = ("2026-07-25 00:00:00", "2026-08-06 23:59:59")
TODAY_OUTAGE = ("2026-08-18 14:45:50", "2026-08-18 16:19:04")  # brain/decisions/2026-08-18-outage-scope.md, commit 6f33220


def orphan_sell_trades(conn, market_ids):
    """All trades in the no-FIFO-close markets -- established (969d9a1) to be
    100% orphan SELLs (186/186 groups zero-BUY)."""
    if not market_ids:
        return pd.DataFrame(columns=['trade_id', 'trader_address', 'market_id', 'outcome', 'side',
                                      'shares', 'price', 'timestamp', 'data_source'])
    placeholders = ",".join("?" for _ in market_ids)
    rows = conn.execute(f"""
        SELECT trade_id, trader_address, market_id, outcome, side, shares, price, timestamp, data_source
        FROM trades WHERE market_id IN ({placeholders})
    """, list(market_ids)).fetchall()
    return pd.DataFrame(rows, columns=['trade_id', 'trader_address', 'market_id', 'outcome', 'side',
                                        'shares', 'price', 'timestamp', 'data_source'])


def true_oos_survivors(conn, cohort_traders, t_split):
    """Same population WHERE clause as v2f.measure_oos -- returns the
    trader-ID SET only. No bootstrap statistic is computed or reported here
    (explicit non-goal of this task: do not recompute the thesis result)."""
    if not cohort_traders:
        return set()
    placeholders = ",".join("?" for _ in cohort_traders)
    rows = conn.execute(f"""
        SELECT DISTINCT p.trader_address
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
    return {r[0] for r in rows}


def postsplit_activity(conn, traders, t_split):
    """Total post-split position/market counts per trader, same population
    filter as measure_oos -- used for per-trader materiality denominators."""
    if not traders:
        return {}
    placeholders = ",".join("?" for _ in traders)
    rows = conn.execute(f"""
        SELECT p.trader_address, COUNT(*) AS n_positions, COUNT(DISTINCT p.market_id) AS n_markets
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({placeholders})
          AND p.entry_timestamp > ?
        GROUP BY p.trader_address
    """, list(traders) + [t_split]).fetchall()
    return {r[0]: dict(n_positions=r[1], n_markets=r[2]) for r in rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--t-split", default=T_SPLIT)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    conn = db_connect(args.db)
    generated_at = datetime.now(timezone.utc).isoformat()
    t_split_dt = pd.to_datetime(args.t_split)

    # --- re-derive current no-FIFO-close market population (fresh, not trusted from prior artifact) ---
    canon = canonical_market_ids(conn, args.t_split)
    v2f_ids = v2f_market_ids(conn, args.t_split)
    candidate = canon - v2f_ids
    no_fifo_ids = no_position_subset(conn, candidate)
    osc = orphan_sell_groups(conn, no_fifo_ids)

    trades = orphan_sell_trades(conn, no_fifo_ids)
    trades['ts'] = pd.to_datetime(trades['timestamp'], format='mixed', errors='coerce')
    affected_traders_all = sorted(trades['trader_address'].unique().tolist())
    affected_trade_ids = sorted(trades['trade_id'].unique().tolist())

    # --- market-level tape_end (own trades' max timestamp -- same convention as the prior characterization) ---
    market_tape_end = trades.groupby('market_id')['ts'].max()
    presplit_market_ids = set(market_tape_end[market_tape_end <= t_split_dt].dropna().index)
    presplit_trades = trades[trades['market_id'].isin(presplit_market_ids)]
    dropped_presplit_by_trader = presplit_trades.groupby('trader_address')['market_id'].nunique().to_dict()
    dropped_postsplit_by_trader = (trades[~trades['market_id'].isin(presplit_market_ids)]
                                    .groupby('trader_address')['market_id'].nunique().to_dict())

    # --- true Objective-2 membership: existing v2f logic, read-only, membership ONLY ---
    load_entries(conn)  # sanity: same call v2f's main() makes; not used downstream (build_presplit_cohort re-queries)
    presplit_data = build_presplit_cohort(conn, args.t_split)
    true_cohort = set(presplit_data['intersection']['trader'])
    elig_pool = set(presplit_data['elig_pool']['trader'])
    true_placebo_pool = match_control(presplit_data['profile'], true_cohort, elig_pool, seed=SEED)

    true_cohort_survivors = true_oos_survivors(conn, true_cohort, args.t_split)
    true_placebo_survivors = true_oos_survivors(conn, true_placebo_pool, args.t_split)

    persisted = {r[0]: dict(n_positions=r[1], n_traders=r[2], point_gap=r[3], ci_lo=r[4], ci_hi=r[5])
                 for r in conn.execute("SELECT kind, n_positions, n_traders, point_gap, ci_lo, ci_hi FROM metric_v2f_oos_result")}

    drift = dict(
        presplit_cohort_n_today=len(true_cohort),
        oos_survivors_n_today=len(true_cohort_survivors),
        oos_survivors_n_persisted_2026_08_15=persisted.get('cohort', {}).get('n_traders'),
        placebo_survivors_n_today=len(true_placebo_survivors),
        placebo_survivors_n_persisted_2026_08_15=persisted.get('placebo', {}).get('n_traders'),
    )

    # --- Q1: exact population intersection ---
    q1 = dict(
        presplit_cohort_148=sorted(true_cohort & set(affected_traders_all)),
        oos_survivors_120=sorted(true_cohort_survivors & set(affected_traders_all)),
        placebo_pool=sorted(true_placebo_pool & set(affected_traders_all)),
        placebo_survivors=sorted(true_placebo_survivors & set(affected_traders_all)),
    )
    q1_counts = {k: len(v) for k, v in q1.items()}

    # --- Q2: per-trader materiality ---
    relevant_traders = sorted(set(q1['presplit_cohort_148']) | set(q1['oos_survivors_120']) |
                               set(q1['placebo_pool']) | set(q1['placebo_survivors']))
    postsplit_totals = postsplit_activity(conn, relevant_traders, args.t_split)

    presplit_pairs, presplit_eb, sigma2_within = compute_cap5_metric(presplit_data['presplit'])
    t_ci_full = per_trader_t_ci(presplit_pairs, sigma2_within)
    n_pairs_presplit_by_trader = dict(zip(t_ci_full['trader'], t_ci_full['n_pairs']))

    per_trader = []
    for t in relevant_traders:
        total_presplit = int(n_pairs_presplit_by_trader.get(t, 0))
        dropped_presplit = int(dropped_presplit_by_trader.get(t, 0))
        post = postsplit_totals.get(t, dict(n_positions=0, n_markets=0))
        dropped_post = int(dropped_postsplit_by_trader.get(t, 0))
        per_trader.append(dict(
            trader=t,
            in_presplit_cohort=t in true_cohort, in_oos_survivors=t in true_cohort_survivors,
            in_placebo_pool=t in true_placebo_pool, in_placebo_survivors=t in true_placebo_survivors,
            presplit_total_markets=total_presplit, presplit_dropped_markets=dropped_presplit,
            presplit_dropped_fraction=(dropped_presplit / total_presplit if total_presplit else None),
            postsplit_total_positions=post['n_positions'], postsplit_total_markets=post['n_markets'],
            postsplit_dropped_markets=dropped_post,
            postsplit_dropped_fraction=(dropped_post / post['n_markets'] if post['n_markets'] else None),
        ))

    # --- Q3: qualification-boundary effect ---
    t_ci_full = t_ci_full.merge(presplit_eb[['trader', 'shrunk_mean']], on='trader', how='left')
    dropped_df = pd.DataFrame({'trader': list(dropped_presplit_by_trader.keys()),
                                'dropped_markets': list(dropped_presplit_by_trader.values())})
    boundary = t_ci_full.merge(dropped_df, on='trader', how='inner')
    boundary = boundary[boundary['dropped_markets'] > 0].copy()

    q3a = boundary[(boundary['n_pairs'] >= M_CHOSEN) & (boundary['ci_lo_t'] > 0) &
                   ((boundary['n_pairs'] - boundary['dropped_markets']) < M_CHOSEN)]
    q3b = boundary[(boundary['n_pairs'] < M_CHOSEN) &
                   ((boundary['n_pairs'] + boundary['dropped_markets']) >= M_CHOSEN)]

    cols = ['trader', 'n_pairs', 'dropped_markets', 'ci_lo_t', 'shrunk_mean']

    # --- Q4: placebo exposure rate comparison ---
    real_cohort_rate = len(q1['presplit_cohort_148']) / len(true_cohort) if true_cohort else None
    placebo_rate = len(q1['placebo_pool']) / len(true_placebo_pool) if true_placebo_pool else None

    # --- Q5: temporal distribution ---
    q5 = dict(pre_split_trades=int((trades['ts'] <= t_split_dt).sum()),
              post_split_trades=int((trades['ts'] > t_split_dt).sum()),
              pre_split_markets=len(presplit_market_ids),
              post_split_markets=len(no_fifo_ids) - len(presplit_market_ids),
              total_trades=len(trades))

    # --- Q6: interaction with known gaps ---
    def window_hits(start, end):
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        mask = trades['ts'].between(s, e)
        return dict(trade_rows=int(mask.sum()), markets=sorted(trades.loc[mask, 'market_id'].unique().tolist()),
                    traders=sorted(trades.loc[mask, 'trader_address'].unique().tolist()))

    q6 = dict(
        box_down_window=window_hits(*OUTAGE_BOX_DOWN),
        zero_trade_window=window_hits(*OUTAGE_ZERO_TRADE_WINDOW),
        today_93min_outage=window_hits(*TODAY_OUTAGE),
        gap_recovery_20260811_data_source=int((trades['data_source'] == 'gap_recovery_20260811').sum()),
    )
    # O-37 synthetic quarantine overlap: direct flag_reason check, not timestamp inference
    placeholders = ",".join("?" for _ in no_fifo_ids) if no_fifo_ids else None
    if placeholders:
        o37_rows = conn.execute(
            f"SELECT market_id, flag_reason FROM markets WHERE market_id IN ({placeholders}) AND flag_reason IS NOT NULL",
            list(no_fifo_ids)).fetchall()
    else:
        o37_rows = []
    q6['o37_or_other_flag_reason_markets'] = [dict(market_id=r[0], flag_reason=r[1]) for r in o37_rows]

    result = dict(
        generated_at=generated_at,
        db_path=os.path.abspath(args.db),
        params=dict(t_split=args.t_split, seed=SEED, m_chosen=M_CHOSEN, effect_bar=EFFECT_BAR,
                    spec_version_reproduced="SKILLV2F-2026-08-15-v1"),
        no_fifo_close_count=len(no_fifo_ids),
        no_fifo_close_market_ids=sorted(no_fifo_ids),
        orphan_sell_check=osc,
        affected_traders_all=affected_traders_all,
        affected_trade_ids=affected_trade_ids,
        true_membership_counts=dict(presplit_cohort_n=len(true_cohort), oos_survivors_n=len(true_cohort_survivors),
                                     placebo_pool_n=len(true_placebo_pool), placebo_survivors_n=len(true_placebo_survivors)),
        persisted_authoritative_2026_08_15=persisted,
        reproduction_drift=drift,
        q1_intersection=q1,
        q1_intersection_counts=q1_counts,
        q2_per_trader_materiality=per_trader,
        q3_boundary_currently_qualifying_near_edge=q3a[cols].to_dict('records'),
        q3_invisible_would_have_qualified=q3b[cols].to_dict('records'),
        q4_exposure_rate=dict(real_cohort_affected=len(q1['presplit_cohort_148']), real_cohort_total=len(true_cohort),
                               real_cohort_rate=real_cohort_rate,
                               placebo_affected=len(q1['placebo_pool']), placebo_total=len(true_placebo_pool),
                               placebo_rate=placebo_rate),
        q5_temporal=q5,
        q6_known_gap_interaction=q6,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"orphan_sell_scope_{ts}.json")
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[written] {out_path}")

    summary = {k: v for k, v in result.items() if k not in
               ('no_fifo_close_market_ids', 'affected_trade_ids', 'q2_per_trader_materiality')}
    print(json.dumps(summary, indent=2, default=str))


if __name__ == '__main__':
    main()
