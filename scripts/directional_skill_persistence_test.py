#!/usr/bin/env python3
"""
DIRECTIONAL SKILL PERSISTENCE TEST -- executes brain/decisions/2026-09-06-
directional-skill-persistence-prereg.md (trading-swarm 7743740) INCLUDING
its dated 2026-09-06 amendment (split primary/secondary success criterion;
stratified reporting by post-split position count). Approved by Oscar
2026-09-06. Read-only against production tables. Writes no production
table -- output goes only to the JSON artifact named on the command line.

THE QUESTION (prereg, "The question"): does directional skill, measured
PIT-legally before T_split, persist out-of-sample? Direction in, direction
out -- edge is out of scope by design, not computed anywhere here.

HARNESS: per_trader_and_aggregate(), sign_flip_null(), classify(),
bh_correction(), split_half() imported unchanged from
directional_skill_diagnostic.py. weighted_pair_table(),
weighted_two_way_gap_bootstrap() imported unchanged from
trader_skill_metric_v2d.py. WEIGHT_FNS imported unchanged from
trader_skill_metric_v2c.py. No function body in any of those modules is
edited by this script.

REPS OVERRIDE, DOCUMENTED EXPLICITLY (prereg S2: REPS=10,000 for the
post-split re-classification step): per_trader_and_aggregate() and
split_half() do not take a `reps` argument -- they read the module-level
`REPS` constant from directional_skill_diagnostic.py directly inside their
own bodies. Since Python resolves a function's global names via its own
module's namespace at call time, rebinding that module attribute
(`dsd.REPS = 10000`) changes what those UNMODIFIED functions read, without
editing directional_skill_diagnostic.py's source at all. This is the
mechanism used here to run the imported, unchanged functions at
REPS=10,000. `MIN_SPLIT_HALF=20`, `ALPHA=0.05`, and `SEED=42` are left
untouched.

TWO SEPARATE, NEW, CLEARLY-RECORDED SEEDS beyond the harness's own
SEED=42 (S5, unchanged, reseeded per call site inside sign_flip_null):
SYNTH_SEED for the one-time zero-skill side draw (S8 prerequisite,
matching Step 1's method exactly) and BOOTSTRAP_SEED for the
trader-clustered persistence-rate CI (S6, a new statistic this
pre-registration introduces, not part of the pre-existing harness).

S8 HARD GATE: the synthetic-null persistence rate replicates Step 1's own
failed split-half attempt (Part 2 of the null-calibration doc), applied to
the ACTUAL twice-classifiable population (753) instead of the small frozen
338-trader population -- using split_half(), imported unchanged, on
zero-skill-by-construction post-split data. If its denominators are as
inadequate as Step 1's (1, 2, 5), this script halts before computing any
real persistence rate, per the prereg's own S8 sequencing.
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
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, M_CHOSEN, GATE_REPS_LOCAL
import scripts.directional_skill_diagnostic as dsd
from scripts.directional_skill_diagnostic import (
    load_post_split_positions, per_trader_and_aggregate, split_half,
    MIN_SPLIT_HALF, ALPHA,
)
from scripts.trader_skill_metric_v2d import weighted_pair_table, weighted_two_way_gap_bootstrap
from scripts.trader_skill_metric_v2c import WEIGHT_FNS

POST_SPLIT_REPS = 10000          # prereg S2, fixed, not tunable after seeing a result
SYNTH_SEED = 20260906            # one-time zero-skill side draw, S8 prerequisite
BOOTSTRAP_SEED = 20260907        # trader-clustered persistence-rate CI resampling
BOOTSTRAP_REPS = 10000
GOMEZ_CRAM_BENCHMARK = 0.44

EXPECTED_TWICE_CLASSIFIABLE = 753
EXPECTED_N_COHORT = 146
EXPECTED_N_COMPARISON = 607
EXPECTED_PIT_CLASSIFIABLE = 5732

STRATA = [(10, 14), (14, 23), (23, 46), (46, 83), (83, None)]

# S8 gate: adequacy judgment, documented rather than a silently-picked
# threshold. Step 1's failure was single-digit denominators (1, 2, 5).
# Below this floor is treated as a clear repeat of that failure; the
# script still reports the exact values either way, per the prereg's own
# instruction that this decision returns to Oscar, not to this script.
MIN_ADEQUATE_DENOMINATOR = 10


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def build_synthetic_df(real_df, synth_seed):
    """Identical construction to Step 1's Part 2 (null-calibration doc):
    each position's side drawn ONCE at random (not per null replicate),
    applied to the recorded (won, price) pair per the original prereg's
    own flipped-payoff derivation. Verified against the flip*real identity."""
    rng = np.random.default_rng(synth_seed)
    df = real_df.copy()
    n = len(df)
    flip = rng.integers(0, 2, size=n) * 2 - 1
    df['synth_flip'] = flip
    df['synth_won'] = np.where(flip == 1, df['won'], 1 - df['won'])
    df['synth_price'] = np.where(flip == 1, df['price'], 1 - df['price'])
    df['synth_edge'] = df['synth_won'] - df['synth_price']
    df['synth_weighted_edge'] = df['synth_edge'] * df['cost']
    assert np.allclose(df['synth_weighted_edge'].to_numpy(), (flip * df['weighted_edge']).to_numpy()), \
        "synthetic construction diverged from the flip*real-edge identity"
    out = df.copy()
    out['weighted_edge'] = out['synth_weighted_edge']
    return out


def trader_clustered_ci(outcomes, reps, seed):
    """Trader-clustered bootstrap on a binary per-trader outcome array
    (prereg S6: 'resampling traders with replacement'). Not two-way
    market clustering -- the statistic here is already one binary value
    per trader, so trader-level resampling is the correct unit."""
    arr = np.asarray(outcomes, dtype=float)
    n = len(arr)
    if n == 0:
        return dict(point=None, ci_lo=None, ci_hi=None, n=0)
    point = float(arr.mean())
    rng = np.random.default_rng(seed)
    boot = np.empty(reps)
    for b in range(reps):
        idx = rng.integers(0, n, size=n)
        boot[b] = arr[idx].mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    return dict(point=point, ci_lo=float(ci_lo), ci_hi=float(ci_hi), n=n)


def ci_relationship(a, b):
    """A's relationship to B's CI: 'above' (A entirely above B), 'below'
    (A entirely below B), 'overlap' (any overlap) -- exhaustive, no
    fourth state, per the amendment's own framing."""
    if a['ci_lo'] is None or b['ci_lo'] is None:
        return 'undetermined'
    if a['ci_lo'] > b['ci_hi']:
        return 'above'
    if a['ci_hi'] < b['ci_lo']:
        return 'below'
    return 'overlap'


def stratify(per_trader_result, count_by_trader, strata):
    """Per-trader post-split BH classification, binned by post-split
    position count. Returns per-bin trader count and BH-skilled rate."""
    out = []
    for lo, hi in strata:
        label = f"[{lo},{hi if hi is not None else 'inf'})"
        in_bin = [t for t in per_trader_result if count_by_trader.get(t, 0) >= lo and
                  (hi is None or count_by_trader.get(t, 0) < hi)]
        n = len(in_bin)
        bh_skilled = sum(1 for t in in_bin if per_trader_result[t]['bh_significant'])
        out.append(dict(bin=label, lo=lo, hi=hi, n_traders=n, n_bh_skilled=bh_skilled,
                         bh_rate=(bh_skilled / n) if n else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--pit-pool-json', default='data/characterizations/directional_skill_pit_legal_pool_20260906T160303Z.json')
    ap.add_argument('--twice-classifiable-json', default='data/characterizations/directional_skill_twice_classifiable_population_20260906T170928Z.json')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('--force-past-gate', action='store_true',
                     help='override the S8 STOP gate -- NOT for normal use, only for post-hoc inspection after a STOP')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dsd.REPS = POST_SPLIT_REPS  # documented override, see module docstring
    print(f"[reps override] directional_skill_diagnostic.REPS set to {dsd.REPS} for this run "
          f"(prereg S2; module file unchanged)")

    pb = json.load(open(args.pit_pool_json))
    pit_classifiable = set(pb['per_trader_result']['per_trader'].keys())
    tc = json.load(open(args.twice_classifiable_json))
    twice_classifiable = sorted(tc['twice_classifiable_traders'])
    cohort_traders = sorted(tc['persistence_cohort_traders'])
    comparison_traders = sorted(tc['comparison_group_traders'])

    print(f"[input] PIT-legal classifiable: {len(pit_classifiable)}  "
          f"twice-classifiable: {len(twice_classifiable)}  "
          f"cohort (N): {len(cohort_traders)}  comparison: {len(comparison_traders)}")
    mismatches = []
    if len(pit_classifiable) != EXPECTED_PIT_CLASSIFIABLE:
        mismatches.append(f"PIT-legal classifiable {len(pit_classifiable)} != {EXPECTED_PIT_CLASSIFIABLE}")
    if len(twice_classifiable) != EXPECTED_TWICE_CLASSIFIABLE:
        mismatches.append(f"twice-classifiable {len(twice_classifiable)} != {EXPECTED_TWICE_CLASSIFIABLE}")
    if len(cohort_traders) != EXPECTED_N_COHORT:
        mismatches.append(f"cohort {len(cohort_traders)} != {EXPECTED_N_COHORT}")
    if len(comparison_traders) != EXPECTED_N_COMPARISON:
        mismatches.append(f"comparison {len(comparison_traders)} != {EXPECTED_N_COMPARISON}")
    if mismatches:
        print(f"[STOP] input counts contradict committed figures: {mismatches}", file=sys.stderr)
        sys.exit(1)

    conn = db_connect(args.db)
    print("\n=== loading REAL post-split positions for the twice-classifiable population ===")
    real_df = load_post_split_positions(conn, twice_classifiable, T_SPLIT)
    print(f"[positions] {len(real_df)} real post-split resolved positions, "
          f"{real_df['trader'].nunique()} distinct traders")
    count_by_trader = real_df.groupby('trader').size().to_dict()

    if args.selfcheck:
        print("\n=== selfcheck: recompute weighted_edge for a sample, verify trader-count consistency ===")
        sample = real_df.sample(min(300, len(real_df)), random_state=7)
        mism = []
        for _, row in sample.iterrows():
            we_expected = (row['won'] - row['price']) * row['cost']
            if abs(we_expected - row['weighted_edge']) > 1e-9:
                mism.append((row['trader'], row['market_id']))
        print(f"[selfcheck] {len(sample)} positions re-derived, {len(mism)} mismatches")
        counts_ge10 = sum(1 for t in twice_classifiable if count_by_trader.get(t, 0) >= M_CHOSEN)
        print(f"[selfcheck] traders with >= M_CHOSEN({M_CHOSEN}) real post-split positions: "
              f"{counts_ge10}/{len(twice_classifiable)} (all should qualify by population construction)")
        if mism or counts_ge10 != len(twice_classifiable):
            print("[selfcheck] FAILED", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED")

    # =========================================================================
    # S8 HARD GATE -- synthetic-zero-skill null, replicating Step 1's split-half
    # method on the ACTUAL twice-classifiable population
    # =========================================================================
    print(f"\n=== S8 HARD GATE: synthetic zero-skill null (SYNTH_SEED={SYNTH_SEED}) ===")
    synth_df = build_synthetic_df(real_df, SYNTH_SEED)
    synth_cohort_df = synth_df[synth_df['trader'].isin(cohort_traders)]
    synth_comparison_df = synth_df[synth_df['trader'].isin(comparison_traders)]
    synth_pooled_df = synth_df

    print("[synthetic] per-trader + aggregate classification, both groups + pooled (context)")
    synth_cohort_result = per_trader_and_aggregate(synth_cohort_df, cohort_traders, "synthetic-cohort", verbose=True)
    synth_comparison_result = per_trader_and_aggregate(synth_comparison_df, comparison_traders, "synthetic-comparison", verbose=True)
    synth_pooled_result = per_trader_and_aggregate(synth_pooled_df, twice_classifiable, "synthetic-pooled", verbose=True)

    print("\n[synthetic] split-half persistence -- THE S8 gate check (mirrors Step 1's failed attempt)")
    synth_cohort_split = split_half(synth_cohort_df, "synthetic-cohort", verbose=True)
    synth_comparison_split = split_half(synth_comparison_df, "synthetic-comparison", verbose=True)
    synth_pooled_split = split_half(synth_pooled_df, "synthetic-pooled", verbose=True)

    denominators = dict(
        synthetic_cohort=synth_cohort_split['persistence_denominator'],
        synthetic_comparison=synth_comparison_split['persistence_denominator'],
        synthetic_pooled=synth_pooled_split['persistence_denominator'],
    )
    print(f"\n[S8 gate] denominators per group: {denominators} "
          f"(Step 1's failure: cohort=2, placebo=1, pooled=5; floor for this run: {MIN_ADEQUATE_DENOMINATOR})")
    gate_inadequate = any(d is not None and d < MIN_ADEQUATE_DENOMINATOR for d in denominators.values()) or \
        any(d is None for d in denominators.values())

    s8_result = dict(
        synth_seed=SYNTH_SEED,
        synthetic_cohort=dict(classification=synth_cohort_result, split_half=synth_cohort_split),
        synthetic_comparison=dict(classification=synth_comparison_result, split_half=synth_comparison_split),
        synthetic_pooled=dict(classification=synth_pooled_result, split_half=synth_pooled_split),
        denominators=denominators,
        min_adequate_denominator=MIN_ADEQUATE_DENOMINATOR,
        gate_inadequate=gate_inadequate,
    )

    # Primary in-house null used for the A1/A2/A3 comparison: the pooled
    # synthetic-cohort's own post-split BH-skilled rate under zero-skill
    # data -- the direct chance-floor analogue of the real persistence
    # rate's own definition (fraction of a fixed, real, pre-split-selected
    # group reclassified as BH-skilled post-split), reported alongside the
    # split-half denominators the S8 gate specifically checks.
    cohort_null_outcomes = [1 if v['bh_significant'] else 0 for v in synth_cohort_result['per_trader'].values()]
    null_ci = trader_clustered_ci(cohort_null_outcomes, BOOTSTRAP_REPS, BOOTSTRAP_SEED)
    s8_result['null_persistence_rate_cohort_denominator_form'] = null_ci
    print(f"[S8] synthetic-cohort post-split BH-skilled rate (chance-floor analogue of the real "
          f"persistence rate): point={null_ci['point']:.4f} CI=[{null_ci['ci_lo']:.4f},{null_ci['ci_hi']:.4f}] "
          f"n={null_ci['n']}")

    if gate_inadequate and not args.force_past_gate:
        print("\n[STOP] S8 gate: at least one synthetic-null split-half denominator is below the "
              f"adequacy floor ({MIN_ADEQUATE_DENOMINATOR}), or undefined (den=0). Per the "
              "pre-registration's own S8 sequencing, this halts before computing any real "
              "persistence rate. Not adjusted, not enlarged. Reported for Oscar.", file=sys.stderr)
        out = dict(
            spec="directional_skill_persistence_test", status="STOPPED_AT_S8_GATE",
            generated_at=datetime.now(timezone.utc).isoformat(), script_commit=git_commit(repo_dir),
            seed=SEED, post_split_reps=POST_SPLIT_REPS, t_split=T_SPLIT, m_chosen=M_CHOSEN,
            n_twice_classifiable=len(twice_classifiable), n_cohort=len(cohort_traders),
            n_comparison=len(comparison_traders), s8=s8_result,
        )
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, 'w') as f:
            json.dump(out, f, indent=2, default=str)
        print(f"[json] written to {args.json_out}")
        conn.close()
        sys.exit(2)

    print(f"\n[S8 gate] PASSED (all denominators >= {MIN_ADEQUATE_DENOMINATOR}) -- proceeding to the real test")

    # =========================================================================
    # REAL TEST -- post-split re-classification at REPS=10,000
    # =========================================================================
    cohort_post_df = real_df[real_df['trader'].isin(cohort_traders)]
    comparison_post_df = real_df[real_df['trader'].isin(comparison_traders)]

    print("\n=== REAL post-split classification, both groups (REPS=10,000) ===")
    cohort_result = per_trader_and_aggregate(cohort_post_df, cohort_traders, "persistence-cohort", verbose=True)
    comparison_result = per_trader_and_aggregate(comparison_post_df, comparison_traders, "comparison-group", verbose=True)

    cohort_outcomes = [1 if v['bh_significant'] else 0 for v in cohort_result['per_trader'].values()]
    real_ci = trader_clustered_ci(cohort_outcomes, BOOTSTRAP_REPS, BOOTSTRAP_SEED)
    print(f"[persistence rate] point={real_ci['point']:.4f} CI=[{real_ci['ci_lo']:.4f},{real_ci['ci_hi']:.4f}] "
          f"n={real_ci['n']}")

    comparison_outcomes = [1 if v['bh_significant'] else 0 for v in comparison_result['per_trader'].values()]
    comparison_ci = trader_clustered_ci(comparison_outcomes, BOOTSTRAP_REPS, BOOTSTRAP_SEED)
    print(f"[comparison group post-split BH-skilled rate, context] point={comparison_ci['point']:.4f} "
          f"CI=[{comparison_ci['ci_lo']:.4f},{comparison_ci['ci_hi']:.4f}] n={comparison_ci['n']}")

    # ---- primary axis: vs. in-house synthetic null ----
    primary_state_raw = ci_relationship(real_ci, null_ci)
    primary_cell = dict(above='A1', below='A3', overlap='A2', undetermined='undetermined')[primary_state_raw]
    print(f"\n[PRIMARY axis] real persistence CI vs. synthetic-null CI: {primary_state_raw} -> {primary_cell}")

    # ---- secondary axis: vs. Gomez-Cram 44% ----
    if real_ci['ci_lo'] is None:
        secondary_cell = 'undetermined'
    elif real_ci['ci_lo'] >= GOMEZ_CRAM_BENCHMARK:
        secondary_cell = 'B1'
    elif real_ci['ci_hi'] < GOMEZ_CRAM_BENCHMARK:
        secondary_cell = 'B3'
    else:
        secondary_cell = 'B2'
    print(f"[SECONDARY axis] real persistence CI vs. Gomez-Cram 44%: {secondary_cell}")
    print(f"\n[NAMED OUTCOME CELL] {primary_cell} x {secondary_cell}")

    # =========================================================================
    # AGGREGATE TEST (S4) -- two-way trader x market clustered bootstrap
    # =========================================================================
    print(f"\n=== AGGREGATE TEST (S4): two-way trader x market clustered bootstrap, "
          f"reps={GATE_REPS_LOCAL}, seed={SEED} -- NOT comparable to the 2026-09-05 p=0.006/0.214 pair ===")
    cohort_pairs = weighted_pair_table(cohort_post_df, WEIGHT_FNS['cap5'])
    cohort_agg = weighted_two_way_gap_bootstrap(cohort_pairs, reps=GATE_REPS_LOCAL, seed=SEED)
    comparison_pairs = weighted_pair_table(comparison_post_df, WEIGHT_FNS['cap5'])
    comparison_agg = weighted_two_way_gap_bootstrap(comparison_pairs, reps=GATE_REPS_LOCAL, seed=SEED)
    print(f"[cohort aggregate] point_gap={cohort_agg.get('point_gap')} "
          f"CI=[{cohort_agg.get('ci_lo')},{cohort_agg.get('ci_hi')}] n_pairs={cohort_agg.get('n_pairs')}")
    print(f"[comparison aggregate, context] point_gap={comparison_agg.get('point_gap')} "
          f"CI=[{comparison_agg.get('ci_lo')},{comparison_agg.get('ci_hi')}] n_pairs={comparison_agg.get('n_pairs')}")

    # =========================================================================
    # STRATIFIED REPORTING (amendment 2) -- five pre-specified bins
    # =========================================================================
    print(f"\n=== STRATIFIED persistence rate by post-split position count, bins={STRATA} ===")
    cohort_strat = stratify(cohort_result['per_trader'], count_by_trader, STRATA)
    comparison_strat = stratify(comparison_result['per_trader'], count_by_trader, STRATA)
    for label, rows in (('cohort', cohort_strat), ('comparison', comparison_strat)):
        for row in rows:
            print(f"  [{label}] {row['bin']}: n={row['n_traders']} bh_skilled={row['n_bh_skilled']} "
                  f"rate={row['bh_rate']}")

    conn.close()

    out = dict(
        spec="directional_skill_persistence_test", status="COMPLETED",
        generated_at=datetime.now(timezone.utc).isoformat(), script_commit=git_commit(repo_dir),
        seed=SEED, post_split_reps=POST_SPLIT_REPS, synth_seed=SYNTH_SEED,
        bootstrap_seed=BOOTSTRAP_SEED, bootstrap_reps=BOOTSTRAP_REPS,
        t_split=T_SPLIT, m_chosen=M_CHOSEN, gate_reps_local=GATE_REPS_LOCAL,
        gomez_cram_benchmark=GOMEZ_CRAM_BENCHMARK,
        n_twice_classifiable=len(twice_classifiable), n_cohort=len(cohort_traders),
        n_comparison=len(comparison_traders),
        twice_classifiable_traders=twice_classifiable,
        persistence_cohort_traders=cohort_traders,
        comparison_group_traders=comparison_traders,
        s8=s8_result,
        real_cohort_classification=cohort_result,
        real_comparison_classification=comparison_result,
        real_persistence_ci=real_ci,
        real_comparison_ci=comparison_ci,
        primary_axis=dict(relationship=primary_state_raw, cell=primary_cell),
        secondary_axis=dict(cell=secondary_cell, benchmark=GOMEZ_CRAM_BENCHMARK),
        named_outcome_cell=f"{primary_cell}x{secondary_cell}",
        aggregate_test=dict(cohort=cohort_agg, comparison_context=comparison_agg),
        stratified_cohort=cohort_strat,
        stratified_comparison=comparison_strat,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
