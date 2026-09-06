#!/usr/bin/env python3
"""
NULL CALIBRATION CHECK -- directional-skill test harness (2026-09-05).
Executes brain/decisions/2026-09-06-directional-skill-null-calibration.md
(trading-swarm). Read-only against production tables. Writes no metric_v2f_*
or other production table -- output goes only to the JSON artifact named on
the command line.

Answers one question: is the directional_skill_diagnostic.py harness itself
well-calibrated, or does it inflate every trader's classified-skilled rate
regardless of actual skill? Two parts:

PART 1 -- re-tabulates the per-trader p-values already persisted in the
2026-09-05 run's own artifact (data/characterizations/
directional_skill_20260905T161232Z.json). No new computation against the DB;
this is a re-read of existing output.

PART 2 -- constructs a population with ZERO skill by construction: real
post-split positions (same SQL, same columns, same filters as
load_post_split_positions() in directional_skill_diagnostic.py, imported
unchanged, not reimplemented) with each position's side drawn ONCE at random
(a fixed, recorded seed -- SYNTH_SEED, distinct from the harness's own SEED=42
used inside the null generation) and then run through
per_trader_and_aggregate() / split_half() / sign_flip_null() / classify() /
bh_correction(), all imported unchanged from directional_skill_diagnostic.py.
No harness function is modified, wrapped, or reimplemented for this run.

Reports both per-arm (synthetic-cohort, synthetic-placebo -- same trader ID
lists as 2026-09-05, so directly row-comparable to that result) and pooled
(both arms concatenated into one 338-trader population) results, plus
split-half persistence, exactly as the original artifact reports them.
Adjudicates nothing -- see brain/decisions/2026-09-06-directional-skill-
null-calibration.md for the write-up.
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
from scripts.directional_skill_diagnostic import (
    load_post_split_positions, per_trader_and_aggregate, split_half,
    REPS, MIN_SPLIT_HALF, ALPHA,
)

SYNTH_SEED = 20260906  # one-time per-position side draw; distinct from the
                        # harness's own SEED=42 used inside null generation


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# PART 1 -- p-value distribution over the already-persisted 2026-09-05 output
# ---------------------------------------------------------------------------

def part1_pvalue_distribution(original_json_path):
    d = json.load(open(original_json_path))
    cohort_pvals = [v['p_value'] for v in d['cohort']['per_trader'].values()]
    placebo_pvals = [v['p_value'] for v in d['placebo']['per_trader'].values()]
    combined_pvals = cohort_pvals + placebo_pvals

    def tabulate(pvals, label):
        arr = np.asarray(pvals, dtype=float)
        n = len(arr)
        if n == 0:
            return dict(label=label, n=0)
        below = {thr: int((arr < thr).sum()) for thr in (0.05, 0.01, 0.001)}
        below_rate = {thr: below[thr] / n for thr in below}
        # decile histogram, full range
        edges = np.linspace(0, 1, 11)
        hist, _ = np.histogram(arr, bins=edges)
        decile_counts = {f"{edges[i]:.1f}-{edges[i+1]:.1f}": int(hist[i]) for i in range(10)}
        # upper-region (p > 0.5) uniformity check
        upper = arr[arr > 0.5]
        n_upper = len(upper)
        upper_mean = float(upper.mean()) if n_upper else None  # uniform(0.5,1] expects ~0.75
        upper_frac_of_total = n_upper / n
        return dict(
            label=label, n=n,
            below_count=below, below_rate=below_rate,
            decile_histogram=decile_counts,
            upper_region=dict(
                n_p_gt_0_5=n_upper,
                frac_of_total=upper_frac_of_total,  # uniform-null expects ~0.5
                mean_p_in_upper=upper_mean,  # uniform-null expects ~0.75
            ),
            min_p=float(arr.min()), max_p=float(arr.max()), median_p=float(np.median(arr)),
        )

    return dict(
        source_artifact=original_json_path,
        cohort=tabulate(cohort_pvals, "cohort"),
        placebo=tabulate(placebo_pvals, "placebo"),
        combined=tabulate(combined_pvals, "combined (cohort+placebo)"),
    )


# ---------------------------------------------------------------------------
# PART 2 -- synthetic zero-skill population through the identical harness
# ---------------------------------------------------------------------------

def build_synthetic_df(real_df, synth_seed):
    """One-time random side draw per position (not per null replicate).
    sign=+1 keeps the recorded direction; sign=-1 flips to the complementary
    price, per the prereg's own derivation (flipped payoff = -(won - p)).
    This is exactly the same sign-flip transform sign_flip_null() applies
    inside the null -- applied ONCE here to build a zero-skill 'observed'
    dataset, not 1500 times to build a null around it."""
    rng = np.random.default_rng(synth_seed)
    df = real_df.copy()
    n = len(df)
    flip = rng.integers(0, 2, size=n) * 2 - 1  # +1 or -1, iid fair coin
    df['synth_flip'] = flip
    df['synth_won'] = np.where(flip == 1, df['won'], 1 - df['won'])
    df['synth_price'] = np.where(flip == 1, df['price'], 1 - df['price'])
    df['synth_edge'] = df['synth_won'] - df['synth_price']
    df['synth_weighted_edge'] = df['synth_edge'] * df['cost']
    # sanity: synth_weighted_edge must equal flip * real weighted_edge exactly
    check = np.allclose(df['synth_weighted_edge'].to_numpy(), (flip * df['weighted_edge']).to_numpy())
    assert check, "synthetic construction diverged from the flip*real-edge identity"
    return df, flip


def to_harness_df(synth_df):
    """Swap in the synthetic weighted_edge under the column name the harness
    functions (per_trader_and_aggregate, split_half) actually read
    ('weighted_edge'), unmodified. No harness code changes; only the input
    frame's weighted_edge is now the synthetic one."""
    out = synth_df.copy()
    out['weighted_edge'] = out['synth_weighted_edge']
    return out


def selfcheck(cohort_synth, control_synth, n_samples=200, seed=7, verbose=True):
    """Re-derives synth_weighted_edge for a random sample directly from
    (won, price, cost, synth_flip) and asserts exact match against the
    stored column -- catches any construction/aggregation drift."""
    mism = []
    for name, df in (('cohort', cohort_synth), ('control', control_synth)):
        sample = df.sample(min(n_samples, len(df)), random_state=seed)
        for _, row in sample.iterrows():
            flip = row['synth_flip']
            won_expected = row['won'] if flip == 1 else 1 - row['won']
            price_expected = row['price'] if flip == 1 else 1 - row['price']
            edge_expected = won_expected - price_expected
            we_expected = edge_expected * row['cost']
            if abs(we_expected - row['synth_weighted_edge']) > 1e-9:
                mism.append((name, row['trader'], row['market_id']))
    if verbose:
        total = min(n_samples, len(cohort_synth)) + min(n_samples, len(control_synth))
        print(f"[selfcheck] {total} synthetic positions re-derived, {len(mism)} mismatches")
    return len(cohort_synth.sample(min(n_samples, len(cohort_synth)), random_state=seed)) + \
        len(control_synth.sample(min(n_samples, len(control_synth)), random_state=seed)), mism


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--frozen-json', default='data/characterizations/track2_ci_power_20260905T104945Z.json')
    ap.add_argument('--original-json', default='data/characterizations/directional_skill_20260905T161232Z.json',
                     help='the persisted 2026-09-05 result artifact, source for Part 1')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--synth-seed', type=int, default=SYNTH_SEED)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=== PART 1: p-value distribution, 2026-09-05 persisted artifact ===")
    part1 = part1_pvalue_distribution(args.original_json)
    if args.verbose:
        for arm in ('cohort', 'placebo', 'combined'):
            t = part1[arm]
            print(f"[{arm}] n={t['n']} below0.05={t['below_rate'][0.05]:.3f} "
                  f"below0.01={t['below_rate'][0.01]:.3f} below0.001={t['below_rate'][0.001]:.3f} "
                  f"upper(p>0.5) frac_of_total={t['upper_region']['frac_of_total']:.3f} "
                  f"(uniform-null expects ~0.5) mean_p_in_upper={t['upper_region']['mean_p_in_upper']}")

    print("\n=== PART 2: synthetic zero-skill population, identical harness ===")
    d = json.load(open(args.frozen_json))
    cohort_ids = d['cohort_trader_list']
    control_ids = d['control_trader_list']
    overlap = set(cohort_ids) & set(control_ids)
    if overlap:
        print(f"[WARNING] {len(overlap)} traders appear in both frozen lists", file=sys.stderr)

    conn = db_connect(args.db)
    cohort_real = load_post_split_positions(conn, cohort_ids, T_SPLIT)
    control_real = load_post_split_positions(conn, control_ids, T_SPLIT)
    conn.close()

    cohort_synth, cohort_flip = build_synthetic_df(cohort_real, args.synth_seed)
    control_synth, control_flip = build_synthetic_df(control_real, args.synth_seed + 1)

    if args.selfcheck:
        n, mism = selfcheck(cohort_synth, control_synth, verbose=True)
        if mism:
            print(f"[selfcheck] FAILED: {len(mism)}/{n} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n} match")

    cohort_h = to_harness_df(cohort_synth)
    control_h = to_harness_df(control_synth)

    print("[synthetic-cohort] per-trader + aggregate (identical harness functions, unmodified)")
    synth_cohort_result = per_trader_and_aggregate(cohort_h, cohort_ids, "synthetic-cohort", verbose=True)
    print("[synthetic-placebo] per-trader + aggregate")
    synth_placebo_result = per_trader_and_aggregate(control_h, control_ids, "synthetic-placebo", verbose=True)

    print("\n[synthetic-cohort] split-half persistence")
    synth_cohort_split = split_half(cohort_h, "synthetic-cohort", verbose=True)
    print("[synthetic-placebo] split-half persistence")
    synth_placebo_split = split_half(control_h, "synthetic-placebo", verbose=True)

    print("\n=== POOLED (both synthetic arms concatenated, 338 frozen traders) ===")
    pooled_df = pd.concat([cohort_h, control_h], ignore_index=True)
    pooled_ids = list(cohort_ids) + list(control_ids)
    pooled_result = per_trader_and_aggregate(pooled_df, pooled_ids, "synthetic-pooled", verbose=True)
    pooled_split = split_half(pooled_df, "synthetic-pooled", verbose=True)

    result = dict(
        spec="directional_skill_null_calibration",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        harness_seed=SEED, harness_reps=REPS, t_split=T_SPLIT,
        min_trades_per_trader=M_CHOSEN, min_trades_split_half=MIN_SPLIT_HALF, alpha=ALPHA,
        synth_seed_cohort=args.synth_seed, synth_seed_control=args.synth_seed + 1,
        part1_pvalue_distribution=part1,
        part2=dict(
            synthetic_cohort=synth_cohort_result,
            synthetic_placebo=synth_placebo_result,
            synthetic_cohort_split_half=synth_cohort_split,
            synthetic_placebo_split_half=synth_placebo_split,
            synthetic_pooled=pooled_result,
            synthetic_pooled_split_half=pooled_split,
        ),
    )

    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
