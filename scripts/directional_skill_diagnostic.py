#!/usr/bin/env python3
"""
DIRECTIONAL SKILL TEST -- Gomez-Cram randomised-direction benchmark.
Executes brain/decisions/2026-09-05-directional-skill-prereg.md (trading-swarm
cf88f8a). Read-only against production tables. Writes no metric_v2f_* or other
production table -- output goes only to the JSON artifact named on the command
line.

FIXED CONSTRAINT (prereg, top section): POST-SPLIT positions only
(entry_timestamp > T_SPLIT). This is not a parameter -- running on full history
would reintroduce the selection circularity the prereg exists to avoid.

Null construction (prereg "The null construction"): per position, actual
weighted edge = (won - entry_avg_price) * entry_total_cost. Complementary price
is derived as 1-p (not looked up), which makes the flipped-direction payoff
exactly the negative of the actual weighted edge -- a sign-flip (Rademacher)
randomization on each position's own weighted edge, not position-count (cap5)
weighted. Every threshold below is copied verbatim from the prereg, not
re-derived here:
  - Minimum trades to classify a trader: 10 (M_CHOSEN reuse).
  - Split-half minimum: 20 total (>=10 per half).
  - Classification bar: 95th percentile, one-tailed, per trader's own null.
  - Evidence-rate bands: <=10% unimpressive, >=20% meaningful, 10-20% needs
    the cohort-vs-placebo comparison.
  - Separation: cohort rate exceeds placebo rate by >=10pp AND cohort's
    pooled aggregate clears its own 95th pctile while placebo's does not --
    both required.
  - Multiple-comparison correction: Benjamini-Hochberg, alpha=0.05, reported
    alongside the raw (uncorrected) rate.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, M_CHOSEN

REPS = 1500
MIN_SPLIT_HALF = 20
ALPHA = 0.05


def load_post_split_positions(conn, trader_list, t_split):
    """Identical structural filter to measure_oos() in trader_skill_metric_v2f.py
    -- category, entry_avg_price not null, trade_result won/lost, gap-clean --
    plus entry_total_cost for the dollar-weighted statistic this test needs
    (measure_oos itself does not select this column)."""
    placeholders = ",".join("?" for _ in trader_list)
    rows = conn.execute(f"""
        SELECT p.trader_address, p.market_id, p.entry_avg_price, p.entry_total_cost,
               p.entry_timestamp, t.trade_result
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({placeholders})
          AND p.entry_timestamp > ?
    """, list(trader_list) + [t_split]).fetchall()
    df = pd.DataFrame(rows, columns=['trader', 'market_id', 'price', 'cost', 'entry_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    df['edge'] = df['won'] - df['price']
    df['weighted_edge'] = df['edge'] * df['cost']
    return df


def sign_flip_null(weighted_edges, reps, seed):
    """Actual statistic (no flip) vs a reps-length null built from independent
    per-position fair-coin sign flips -- per prereg's derivation, this is
    exactly equivalent to Gomez-Cram's randomised-direction benchmark under
    the 1-p complementary-price assumption."""
    rng = np.random.default_rng(seed)
    n = len(weighted_edges)
    actual = float(weighted_edges.sum())
    null = np.empty(reps)
    for b in range(reps):
        signs = rng.integers(0, 2, size=n) * 2 - 1
        null[b] = float((signs * weighted_edges).sum())
    return actual, null


def classify(actual, null):
    p_value = float((np.sum(null >= actual) + 1) / (len(null) + 1))
    threshold_95 = float(np.percentile(null, 95))
    return dict(
        actual=actual, null_p95=threshold_95, p_value=p_value,
        skilled=bool(actual > threshold_95),
        percentile_rank=float((null < actual).mean() * 100),
    )


def bh_correction(pvals, alpha=ALPHA):
    pvals = np.asarray(pvals, dtype=float)
    m = len(pvals)
    if m == 0:
        return np.array([], dtype=bool)
    order = np.argsort(pvals)
    sorted_p = pvals[order]
    thresh = (np.arange(1, m + 1) / m) * alpha
    passed = sorted_p <= thresh
    k = (np.max(np.where(passed)[0]) + 1) if passed.any() else 0
    reject = np.zeros(m, dtype=bool)
    reject[order[:k]] = True
    return reject


def per_trader_and_aggregate(df, all_trader_ids, label, verbose=False):
    counts = df.groupby('trader').size()
    zero_position_traders = [t for t in all_trader_ids if t not in set(counts.index)]
    below_min_traders = counts[(counts >= 1) & (counts < M_CHOSEN)].index.tolist()
    classifiable_traders = counts[counts >= M_CHOSEN].index.tolist()

    per_trader = {}
    pvals = []
    order = []
    for trader in classifiable_traders:
        g = df[df['trader'] == trader]
        actual, null = sign_flip_null(g['weighted_edge'].to_numpy(), REPS, SEED)
        res = classify(actual, null)
        res['n_positions'] = int(len(g))
        per_trader[trader] = res
        pvals.append(res['p_value'])
        order.append(trader)

    reject = bh_correction(pvals, ALPHA)
    for i, trader in enumerate(order):
        per_trader[trader]['bh_significant'] = bool(reject[i])

    n_classifiable = len(per_trader)
    raw_skilled = sum(1 for v in per_trader.values() if v['skilled'])
    bh_skilled = sum(1 for v in per_trader.values() if v['bh_significant'])

    agg_actual, agg_null = sign_flip_null(df['weighted_edge'].to_numpy(), REPS, SEED)
    agg_result = classify(agg_actual, agg_null)

    if verbose:
        print(f"[{label}] n_traders(frozen)={len(all_trader_ids)} n_zero_position={len(zero_position_traders)} "
              f"n_below_min(1-{M_CHOSEN-1})={len(below_min_traders)} n_classifiable(>={M_CHOSEN})={n_classifiable}")
        print(f"[{label}] raw skilled={raw_skilled}/{n_classifiable} "
              f"({raw_skilled/n_classifiable*100:.1f}% if n>0) "
              f"bh skilled={bh_skilled}/{n_classifiable}")
        print(f"[{label}] aggregate: actual={agg_result['actual']:.4f} "
              f"null_p95={agg_result['null_p95']:.4f} skilled={agg_result['skilled']} "
              f"percentile_rank={agg_result['percentile_rank']:.2f}")

    return dict(
        n_total_frozen=len(all_trader_ids),
        n_zero_position=len(zero_position_traders),
        n_below_min=len(below_min_traders),
        n_classifiable=n_classifiable,
        raw_skilled_count=raw_skilled,
        raw_rate=(raw_skilled / n_classifiable) if n_classifiable else None,
        bh_skilled_count=bh_skilled,
        bh_rate=(bh_skilled / n_classifiable) if n_classifiable else None,
        aggregate=agg_result,
        per_trader=per_trader,
        n_total_positions=int(len(df)),
    )


def split_half(df, label, verbose=False):
    counts = df.groupby('trader').size()
    eligible = counts[counts >= MIN_SPLIT_HALF].index.tolist()
    rng = np.random.default_rng(SEED)
    num = 0
    den = 0
    per_trader = {}
    for trader in eligible:
        g = df[df['trader'] == trader].reset_index(drop=True)
        n = len(g)
        perm = rng.permutation(n)
        half = n // 2
        idx_a, idx_b = perm[:half], perm[half:]
        wa = g.loc[idx_a, 'weighted_edge'].to_numpy()
        wb = g.loc[idx_b, 'weighted_edge'].to_numpy()
        actual_a, null_a = sign_flip_null(wa, REPS, SEED)
        actual_b, null_b = sign_flip_null(wb, REPS, SEED)
        res_a = classify(actual_a, null_a)
        res_b = classify(actual_b, null_b)
        per_trader[trader] = dict(half_a=res_a, half_b=res_b, n=int(n))
        if res_a['skilled']:
            den += 1
            if res_b['skilled']:
                num += 1
    rate = (num / den) if den else None
    if verbose:
        print(f"[{label} split-half] n_eligible(>= {MIN_SPLIT_HALF})={len(eligible)} "
              f"persistence={num}/{den} ({rate*100:.1f}% if den>0 else 'n/a')")
    return dict(n_eligible=len(eligible), persistence_numerator=num,
                persistence_denominator=den, persistence_rate=rate, per_trader=per_trader)


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--frozen-json', default='data/characterizations/track2_ci_power_20260905T104945Z.json')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(args.frozen_json))
    cohort = d['cohort_trader_list']
    control = d['control_trader_list']

    conn = db_connect(args.db)

    print(f"=== SCOPING VERIFICATION: T_SPLIT={T_SPLIT} (post-split only) ===")
    cohort_df = load_post_split_positions(conn, cohort, T_SPLIT)
    control_df = load_post_split_positions(conn, control, T_SPLIT)
    min_entry_cohort = cohort_df['entry_ts'].min() if len(cohort_df) else None
    min_entry_control = control_df['entry_ts'].min() if len(control_df) else None
    print(f"cohort: n_positions={len(cohort_df)} n_traders={cohort_df['trader'].nunique()} "
          f"min(entry_timestamp)={min_entry_cohort} (must be > {T_SPLIT})")
    print(f"placebo: n_positions={len(control_df)} n_traders={control_df['trader'].nunique()} "
          f"min(entry_timestamp)={min_entry_control} (must be > {T_SPLIT})")
    assert min_entry_cohort > T_SPLIT, "SCOPING VIOLATION: a pre-split position leaked into the cohort set"
    assert min_entry_control > T_SPLIT, "SCOPING VIOLATION: a pre-split position leaked into the placebo set"
    print("[SCOPING OK] every position in both populations has entry_timestamp > T_SPLIT.\n")

    print("=== PER-TRADER + AGGREGATE ===")
    cohort_result = per_trader_and_aggregate(cohort_df, cohort, "cohort", verbose=True)
    placebo_result = per_trader_and_aggregate(control_df, control, "placebo", verbose=True)

    print("\n=== SPLIT-HALF PERSISTENCE ===")
    cohort_split = split_half(cohort_df, "cohort", verbose=True)
    placebo_split = split_half(control_df, "placebo", verbose=True)

    print("\n=== COHORT vs PLACEBO SEPARATION (primary output) ===")
    rate_diff_raw = (cohort_result['raw_rate'] - placebo_result['raw_rate']) if (
        cohort_result['raw_rate'] is not None and placebo_result['raw_rate'] is not None) else None
    rate_diff_bh = (cohort_result['bh_rate'] - placebo_result['bh_rate']) if (
        cohort_result['bh_rate'] is not None and placebo_result['bh_rate'] is not None) else None
    cond_rate = rate_diff_raw is not None and rate_diff_raw >= 0.10
    cond_aggregate = cohort_result['aggregate']['skilled'] and not placebo_result['aggregate']['skilled']
    separation = cond_rate and cond_aggregate
    print(f"raw rate diff (cohort - placebo): {rate_diff_raw}")
    print(f"bh rate diff (cohort - placebo): {rate_diff_bh}")
    print(f"condition A (rate diff >= 10pp): {cond_rate}")
    print(f"condition B (cohort aggregate skilled AND placebo aggregate not skilled): {cond_aggregate}")
    print(f"SEPARATION (both conditions): {separation}")

    result = dict(
        spec="directional_skill_diagnostic", seed=SEED, reps=REPS, t_split=T_SPLIT,
        min_trades_per_trader=M_CHOSEN, min_trades_split_half=MIN_SPLIT_HALF, alpha=ALPHA,
        generated_at=datetime.now(timezone.utc).isoformat(),
        diagnostic_script_commit=git_commit(repo_dir),
        cohort=cohort_result, placebo=placebo_result,
        cohort_split_half=cohort_split, placebo_split_half=placebo_split,
        separation=dict(rate_diff_raw=rate_diff_raw, rate_diff_bh=rate_diff_bh,
                        condition_rate=cond_rate, condition_aggregate=cond_aggregate,
                        separation=separation),
    )

    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")

    conn.close()


if __name__ == '__main__':
    main()
