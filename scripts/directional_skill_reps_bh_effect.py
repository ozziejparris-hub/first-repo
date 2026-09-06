#!/usr/bin/env python3
"""
REPS EFFECT ON BH-ADJUSTED CLASSIFICATION -- premise test. Executes brain/
decisions/2026-09-06-reps-bh-effect-isolation.md. Read-only against
production tables. Writes no production table -- output goes only to the
JSON artifact named on the command line.

ONE QUESTION: on a population with NO skill by construction, does
BH-adjusted classification differ materially between REPS=1,500 and
REPS=10,000? The 2026-09-06 persistence run (first-repo ea1140e) found
BH=0 at REPS=10,000 on all three synthetic zero-skill groups; the
2026-09-05 real test found BH rates of 19.2%/29.4% at REPS=1,500. This
script isolates whether that gap is a REPS artifact (BH admitting false
positives at 1,500) or something else, on the SAME synthetic construction
used by the 2026-09-06 run.

Reuses build_synthetic_df() imported UNCHANGED from
directional_skill_persistence_test.py (same construction: real post-split
positions for the 753 twice-classifiable traders, each position's side
drawn once at random). REPS override via the same documented module-
attribute rebind that script already used
(directional_skill_diagnostic.REPS -- a module-level constant
per_trader_and_aggregate() reads directly; rebinding it changes what the
UNMODIFIED imported function reads, without editing its source).

Does NOT recompute pre-split classification, N=146, the 5,732 PIT-legal
population, or any real trader's classification. Does NOT compute any
persistence rate. Does NOT touch MIN_ADEQUATE_DENOMINATOR or the S8 gate.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED
import scripts.directional_skill_diagnostic as dsd
from scripts.directional_skill_diagnostic import load_post_split_positions, per_trader_and_aggregate
from scripts.directional_skill_persistence_test import build_synthetic_df

REPS_VALUES = [1500, 3000, 5000, 10000]
SYNTH_SEEDS = [20260906, 31337, 99991]  # 20260906 is the 2026-09-06 persistence run's own seed

# The 2026-09-06 persistence run's committed figures at REPS=10000,
# SYNTH_SEED=20260906 -- reproduction target for the STOP-condition check.
REFERENCE_ARTIFACT = 'data/characterizations/directional_skill_persistence_20260906T191615Z.json'


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def floor_pvalue(reps):
    return 1.0 / (reps + 1)


def analyze_group(df, trader_ids, reps, label, verbose=False):
    dsd.REPS = reps
    result = per_trader_and_aggregate(df, trader_ids, label, verbose=verbose)
    n = result['n_classifiable']
    raw = result['raw_skilled_count']
    bh = result['bh_skilled_count']
    pvals = [v['p_value'] for v in result['per_trader'].values()]
    distinct = len(set(pvals))
    floor = floor_pvalue(reps)
    pinned = sum(1 for p in pvals if abs(p - floor) < 1e-12)
    return dict(
        reps=reps, group=label, n_classifiable=n,
        raw_skilled=raw, raw_rate=(raw / n) if n else None,
        bh_skilled=bh, bh_rate=(bh / n) if n else None,
        distinct_pvalues=distinct, pinned_at_floor=pinned,
        floor_pvalue=floor,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--twice-classifiable-json', default='data/characterizations/directional_skill_twice_classifiable_population_20260906T170928Z.json')
    ap.add_argument('--reference-json', default=REFERENCE_ARTIFACT)
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--reps', default=','.join(str(r) for r in REPS_VALUES),
                     help='comma-separated REPS values; drop 3000/5000 with --reps=1500,10000 if runtime is prohibitive')
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reps_values = [int(x) for x in args.reps.split(',')]

    tc = json.load(open(args.twice_classifiable_json))
    twice_classifiable = sorted(tc['twice_classifiable_traders'])
    cohort_traders = sorted(tc['persistence_cohort_traders'])
    comparison_traders = sorted(tc['comparison_group_traders'])
    print(f"[population] twice-classifiable={len(twice_classifiable)} cohort={len(cohort_traders)} "
          f"comparison={len(comparison_traders)}")

    conn = db_connect(args.db)
    real_df = load_post_split_positions(conn, twice_classifiable, T_SPLIT)
    conn.close()
    print(f"[positions] {len(real_df)} real post-split resolved positions loaded "
          f"(shared across all seeds/REPS -- only the synthetic side-draw varies)")

    runs = []
    t0 = datetime.now(timezone.utc)
    for synth_seed in SYNTH_SEEDS:
        print(f"\n=== SYNTH_SEED={synth_seed} ===")
        synth_df = build_synthetic_df(real_df, synth_seed)
        synth_cohort_df = synth_df[synth_df['trader'].isin(cohort_traders)]
        synth_comparison_df = synth_df[synth_df['trader'].isin(comparison_traders)]
        synth_pooled_df = synth_df

        for reps in reps_values:
            reps_t0 = datetime.now(timezone.utc)
            print(f"  --- REPS={reps} ---")
            cohort_r = analyze_group(synth_cohort_df, cohort_traders, reps, f"seed{synth_seed}-cohort-r{reps}", args.verbose)
            comparison_r = analyze_group(synth_comparison_df, comparison_traders, reps, f"seed{synth_seed}-comparison-r{reps}", args.verbose)
            pooled_r = analyze_group(synth_pooled_df, twice_classifiable, reps, f"seed{synth_seed}-pooled-r{reps}", args.verbose)
            elapsed = (datetime.now(timezone.utc) - reps_t0).total_seconds()
            print(f"    cohort: raw={cohort_r['raw_skilled']}/{cohort_r['n_classifiable']} "
                  f"({cohort_r['raw_rate']*100:.1f}%) bh={cohort_r['bh_skilled']} "
                  f"({cohort_r['bh_rate']*100:.1f}%) distinct_p={cohort_r['distinct_pvalues']} "
                  f"pinned={cohort_r['pinned_at_floor']}")
            print(f"    comparison: raw={comparison_r['raw_skilled']}/{comparison_r['n_classifiable']} "
                  f"({comparison_r['raw_rate']*100:.1f}%) bh={comparison_r['bh_skilled']} "
                  f"({comparison_r['bh_rate']*100:.1f}%) distinct_p={comparison_r['distinct_pvalues']} "
                  f"pinned={comparison_r['pinned_at_floor']}")
            print(f"    pooled: raw={pooled_r['raw_skilled']}/{pooled_r['n_classifiable']} "
                  f"({pooled_r['raw_rate']*100:.1f}%) bh={pooled_r['bh_skilled']} "
                  f"({pooled_r['bh_rate']*100:.1f}%) distinct_p={pooled_r['distinct_pvalues']} "
                  f"pinned={pooled_r['pinned_at_floor']}")
            print(f"    [timing] {elapsed:.1f}s for this REPS value, 3 groups")
            runs.append(dict(synth_seed=synth_seed, reps=reps, elapsed_seconds=elapsed,
                              cohort=cohort_r, comparison=comparison_r, pooled=pooled_r))

    total_elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\n[total runtime] {total_elapsed:.1f}s across {len(SYNTH_SEEDS)} seeds x {len(reps_values)} REPS values")

    selfcheck_result = None
    if args.selfcheck:
        print("\n=== selfcheck: reproduce the 2026-09-06 persistence run's committed figures "
              f"at SYNTH_SEED=20260906, REPS=10000 ===")
        ref = json.load(open(args.reference_json))
        target = next(r for r in runs if r['synth_seed'] == 20260906 and r['reps'] == 10000)
        ref_cohort = ref['s8']['synthetic_cohort']['classification']
        ref_comparison = ref['s8']['synthetic_comparison']['classification']
        ref_pooled = ref['s8']['synthetic_pooled']['classification']
        checks = [
            ('cohort raw', target['cohort']['raw_skilled'], ref_cohort['raw_skilled_count']),
            ('cohort bh', target['cohort']['bh_skilled'], ref_cohort['bh_skilled_count']),
            ('comparison raw', target['comparison']['raw_skilled'], ref_comparison['raw_skilled_count']),
            ('comparison bh', target['comparison']['bh_skilled'], ref_comparison['bh_skilled_count']),
            ('pooled raw', target['pooled']['raw_skilled'], ref_pooled['raw_skilled_count']),
            ('pooled bh', target['pooled']['bh_skilled'], ref_pooled['bh_skilled_count']),
        ]
        mism = [(name, got, want) for name, got, want in checks if got != want]
        for name, got, want in checks:
            print(f"  {name}: got={got} reference={want} {'OK' if got == want else 'MISMATCH'}")
        if mism:
            print(f"\n[STOP] synthetic construction did NOT reproduce the 2026-09-06 committed "
                  f"figures: {mism}. Reproducibility failure -- reported, not worked around.", file=sys.stderr)
            selfcheck_result = dict(passed=False, mismatches=mism)
            out = dict(
                spec="directional_skill_reps_bh_effect", status="STOPPED_REPRODUCIBILITY_FAILURE",
                generated_at=datetime.now(timezone.utc).isoformat(), script_commit=git_commit(repo_dir),
                synth_seeds=SYNTH_SEEDS, reps_values=reps_values, harness_seed=SEED, t_split=T_SPLIT,
                selfcheck=selfcheck_result, runs=runs,
            )
            os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
            with open(args.json_out, 'w') as f:
                json.dump(out, f, indent=2, default=str)
            print(f"[json] written to {args.json_out}")
            sys.exit(1)
        print("[selfcheck] PASSED -- 2026-09-06 committed figures reproduced exactly")
        selfcheck_result = dict(passed=True, mismatches=[])

    # ---- range across draws, per (reps, group) ----
    print("\n=== BH RATE RANGE ACROSS SYNTHETIC DRAWS, per REPS/group ===")
    range_table = []
    for reps in reps_values:
        for group in ('cohort', 'comparison', 'pooled'):
            rates = [r[group]['bh_rate'] for r in runs if r['reps'] == reps]
            counts = [r[group]['bh_skilled'] for r in runs if r['reps'] == reps]
            row = dict(reps=reps, group=group, bh_rates_across_seeds=rates,
                       bh_counts_across_seeds=counts,
                       min_bh_rate=min(rates), max_bh_rate=max(rates))
            range_table.append(row)
            print(f"  REPS={reps} {group}: bh_rates={['%.4f' % x for x in rates]} "
                  f"(range [{row['min_bh_rate']*100:.1f}%, {row['max_bh_rate']*100:.1f}%])")

    out = dict(
        spec="directional_skill_reps_bh_effect", status="COMPLETED",
        generated_at=datetime.now(timezone.utc).isoformat(), script_commit=git_commit(repo_dir),
        synth_seeds=SYNTH_SEEDS, reps_values=reps_values, harness_seed=SEED, t_split=T_SPLIT,
        total_runtime_seconds=total_elapsed,
        selfcheck=selfcheck_result,
        runs=runs,
        range_across_draws=range_table,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
