#!/usr/bin/env python3
"""
DIRECTIONAL SKILL PERSISTENCE TEST -- executes brain/decisions/2026-09-06-
directional-skill-persistence-prereg.md (trading-swarm 7743740) INCLUDING
BOTH its dated amendments: the 2026-09-06 amendment (split primary/
secondary success criterion; stratified reporting by post-split position
count) and Amendment 2026-09-06b (S8 null established by an alternative
route, fixed numerically at 0%). Approved by Oscar 2026-09-06. Read-only
against production tables. Writes no production table -- output goes only
to the JSON artifact named on the command line.

THE QUESTION (prereg, "The question"): does directional skill, measured
PIT-legally before T_split, persist out-of-sample? Direction in, direction
out -- edge is out of scope by design, not computed anywhere here.

HARNESS: per_trader_and_aggregate(), sign_flip_null(), classify(),
bh_correction() imported unchanged from directional_skill_diagnostic.py.
weighted_pair_table(), weighted_two_way_gap_bootstrap() imported unchanged
from trader_skill_metric_v2d.py. WEIGHT_FNS imported unchanged from
trader_skill_metric_v2c.py. No function body in any of those modules is
edited by this script.

REPS OVERRIDE, DOCUMENTED EXPLICITLY (prereg S2: REPS=10,000 for the
post-split re-classification step): per_trader_and_aggregate() does not
take a `reps` argument -- it reads the module-level `REPS` constant from
directional_skill_diagnostic.py directly inside its own body. Since Python
resolves a function's global names via its own module's namespace at call
time, rebinding that module attribute (`dsd.REPS = 10000`) changes what
this UNMODIFIED function reads, without editing
directional_skill_diagnostic.py's source at all. `ALPHA=0.05` and
`SEED=42` are left untouched.

NULL, PER AMENDMENT 2026-09-06b: the S8 gate as originally specified
(split-half persistence on an adequate denominator) was NOT MET when
first attempted (first-repo `ea1140e`) -- the synthetic-cohort split-half
denominator was 6, below the documented floor of 10. That gate is NOT
retried here. Instead, per the amendment, the null is FIXED NUMERICALLY
at 0% (BH-adjusted persistence rate under zero skill), established by the
REPS premise test (first-repo `6dc0bf5`): BH=0 in all 36 tested cells (3
synthetic draws x 4 REPS values x 3 groups), zero spread across draws.
This script does not recompute that evidence -- it verifies (via
--selfcheck) that the cited artifact still shows BH=0 in all 36 cells,
then uses the fixed null point directly. No synthetic-null construction,
split_half() call, or MIN_ADEQUATE_DENOMINATOR gate appears in this
script.

BOOTSTRAP_SEED (new, beyond the harness's own SEED=42, S5, unchanged,
reseeded per call site inside sign_flip_null): trader-clustered
persistence-rate CI resampling (S6, a new statistic this pre-registration
introduces, not part of the pre-existing harness).
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
from scripts.directional_skill_diagnostic import load_post_split_positions, per_trader_and_aggregate
from scripts.trader_skill_metric_v2d import weighted_pair_table, weighted_two_way_gap_bootstrap
from scripts.trader_skill_metric_v2c import WEIGHT_FNS

POST_SPLIT_REPS = 10000          # prereg S2, fixed, not tunable after seeing a result
BOOTSTRAP_SEED = 20260907        # trader-clustered persistence-rate CI resampling
BOOTSTRAP_REPS = 10000
GOMEZ_CRAM_BENCHMARK = 0.44

EXPECTED_TWICE_CLASSIFIABLE = 753
EXPECTED_N_COHORT = 146
EXPECTED_N_COMPARISON = 607
EXPECTED_PIT_CLASSIFIABLE = 5732

STRATA = [(10, 14), (14, 23), (23, 46), (46, 83), (83, None)]

# Amendment 2026-09-06b: the null the real persistence rate is judged
# against, fixed numerically, not computed by this script.
NULL_POINT = 0.0
NULL_PROVENANCE = dict(
    established_by="REPS premise test (first-repo 6dc0bf5)",
    artifact="data/characterizations/directional_skill_reps_bh_effect_20260906T193257Z.json",
    amendment="Amendment 2026-09-06b, 2026-09-06-directional-skill-persistence-prereg.md",
    evidence="BH-adjusted classification == 0 in all 36 tested cells "
             "(3 independent synthetic draws x 4 REPS values x 3 groups), "
             "zero spread across draws",
    s8_as_originally_specified="NOT MET -- synthetic-cohort split-half denominator "
                                "was 6, below the documented floor of 10 (first-repo ea1140e)",
)


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


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


def primary_axis_state(real_ci, null_point=NULL_POINT):
    """A-axis, per Amendment 2026-09-06b: the null is fixed at a single
    point (0%), not a CI, so the CI-vs-CI rule reduces to a CI-vs-point
    rule, stated exactly as the amendment fixes it:
    A1 (established) iff the real CI's lower bound is STRICTLY greater
    than the null point (the CI excludes it). A2 (no persistence)
    otherwise (the CI touches or includes the null point). A3 (reversal)
    is structurally unreachable -- a bounded proportion cannot fall below
    a null fixed at the statistic's own floor -- and is never returned,
    exactly as the amendment states in advance."""
    if real_ci['ci_lo'] is None:
        return 'undetermined'
    if real_ci['ci_lo'] > null_point:
        return 'A1'
    return 'A2'


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
    ap.add_argument('--reps-effect-json', default=NULL_PROVENANCE['artifact'],
                     help='REPS premise test artifact -- verified (not recomputed) by --selfcheck '
                          'to still show BH=0 in all 36 cells before the fixed null is used')
    ap.add_argument('--selfcheck', action='store_true')
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

        print(f"\n=== selfcheck: verify (not recompute) the REPS-effect artifact still shows "
              f"BH=0 in all 36 cells, per Amendment 2026-09-06b ===")
        reps_effect = json.load(open(args.reps_effect_json))
        non_zero = [(r['synth_seed'], r['reps'], g)
                    for r in reps_effect['runs'] for g in ('cohort', 'comparison', 'pooled')
                    if r[g]['bh_skilled'] != 0]
        print(f"[selfcheck] {len(reps_effect['runs']) * 3} cells checked, "
              f"{len(non_zero)} with BH != 0")
        if non_zero:
            print(f"[selfcheck] FAILED: the null-provenance artifact no longer supports a "
                  f"fixed null of 0% -- {non_zero}", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED -- fixed null of 0% remains supported")

    print(f"\n=== NULL, per Amendment 2026-09-06b (not computed here -- established by an "
          f"alternative route, verified above) ===")
    print(f"  null point: {NULL_POINT} (BH-adjusted persistence rate under zero skill)")
    print(f"  provenance: {NULL_PROVENANCE}")

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

    # ---- primary axis: vs. the fixed null (Amendment 2026-09-06b) ----
    primary_cell = primary_axis_state(real_ci, NULL_POINT)
    print(f"\n[PRIMARY axis] real persistence CI lower bound ({real_ci['ci_lo']}) vs. "
          f"fixed null point ({NULL_POINT}): {primary_cell} "
          f"(A3 is structurally unreachable under this null, per Amendment 2026-09-06b)")

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
        seed=SEED, post_split_reps=POST_SPLIT_REPS,
        bootstrap_seed=BOOTSTRAP_SEED, bootstrap_reps=BOOTSTRAP_REPS,
        t_split=T_SPLIT, m_chosen=M_CHOSEN, gate_reps_local=GATE_REPS_LOCAL,
        gomez_cram_benchmark=GOMEZ_CRAM_BENCHMARK,
        n_twice_classifiable=len(twice_classifiable), n_cohort=len(cohort_traders),
        n_comparison=len(comparison_traders),
        twice_classifiable_traders=twice_classifiable,
        persistence_cohort_traders=cohort_traders,
        comparison_group_traders=comparison_traders,
        null_point=NULL_POINT, null_provenance=NULL_PROVENANCE,
        real_cohort_classification=cohort_result,
        real_comparison_classification=comparison_result,
        real_persistence_ci=real_ci,
        real_comparison_ci=comparison_ci,
        primary_axis=dict(cell=primary_cell, a3_structurally_unreachable=True),
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
