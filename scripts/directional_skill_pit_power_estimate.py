#!/usr/bin/env python3
"""
POWER ESTIMATE for the PIT-legal directional-skill cohort. Part C of
brain/decisions/2026-09-06-discrepancy-pit-pool-power.md. Read-only against
production tables. Writes no metric_v2f_* or other production table --
output goes only to the JSON artifact named on the command line.

Consumes the raw/BH skilled-and-survived trader lists from a
directional_skill_pit_legal_pool_*.json artifact (Part B). Builds a matched
placebo of comparable size via match_control() (imported unchanged from
trader_skill_metric_v2f.py -- same greedy nearest-neighbour matcher used to
build the original 2026-09-05 placebo). Measures out-of-sample edge for each
group via measure_oos() (imported unchanged) -- the SAME machinery as the
result of record (+0.0316, CI[-0.0088,+0.0710], n=3,032/120): two-way
trader x market clustered bootstrap (weighted_two_way_gap_bootstrap), cap5
weighting (weighted_pair_table / WEIGHT_FNS['cap5']), empirical-Bayes
shrinkage (inside build_presplit_cohort's eb output, reused for the
matching profile only -- measure_oos itself reports the unshrunk bootstrap
CI, matching the result-of-record's own reported quantity).

No harness or measurement function is modified. No minimum count, weighting,
or restriction is adjusted to produce a tighter interval -- this is exactly
measure_oos() as committed, called on Part B's actual survivor lists.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import (
    T_SPLIT, SEED, build_presplit_cohort, match_control, measure_oos,
)

# Category-specific cost floors, cited as-is from the project's prior
# cost-floor work (trader_skill_metric_v2f SPREAD_LO/SPREAD_HI context),
# reported here for comparison only, not recomputed.
COST_FLOOR_GEOPOLITICS = (0.0005, 0.010)
COST_FLOOR_ELECTIONS = (0.0056, 0.020)

# Result of record, cited for comparison, not recomputed here.
RESULT_OF_RECORD = dict(point_gap=0.0316, ci_lo=-0.0088, ci_hi=0.0710,
                         n_positions=3032, n_traders=120, width=0.0710 - (-0.0088))


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def half_width_mde(r):
    """Half the CI width, as a practical proxy for the minimum true effect
    magnitude distinguishable from zero at this sample's precision -- not a
    formal power calculation (would need an assumed alternative and
    simulation), reported as an approximation, labelled as such."""
    if r.get('ci_lo') is None or r.get('ci_hi') is None:
        return None
    return (r['ci_hi'] - r['ci_lo']) / 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--pit-pool-json', required=True,
                     help='directional_skill_pit_legal_pool_*.json from Part B')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(args.pit_pool_json))
    raw_survivors = set(d['survival']['raw_survivors'])
    bh_survivors = set(d['survival']['bh_survivors'])
    print(f"[input] raw survivors={len(raw_survivors)} bh survivors={len(bh_survivors)} "
          f"from {args.pit_pool_json}")

    conn = db_connect(args.db)

    print("\n=== rebuilding presplit profile + eligible pool (for matching only) ===")
    presplit_data = build_presplit_cohort(conn, T_SPLIT, verbose=args.verbose)
    elig_traders = set(presplit_data['elig_pool']['trader'])
    profile = presplit_data['profile']

    if args.selfcheck:
        # elig_pool here is filtered on n_pairs (cap5 trader-market PAIRS) >=
        # M_CHOSEN, while Part B's survivor lists are filtered on raw
        # per_trader_and_aggregate POSITION count >= M_CHOSEN -- two different
        # units of count (a trader with several positions in the same market
        # contributes multiple positions but one pair). Some survivors are
        # expected to fall outside elig_pool under the stricter pair-count
        # definition; reported, not treated as a failure. What IS asserted:
        # every survivor must have at least one presplit pair at all (i.e. be
        # present in `profile`), since match_control() requires prof.loc[t]
        # to succeed for every cohort member.
        missing_raw = raw_survivors - elig_traders
        missing_bh = bh_survivors - elig_traders
        no_profile_raw = raw_survivors - set(profile['trader'])
        no_profile_bh = bh_survivors - set(profile['trader'])
        print(f"[selfcheck] raw survivors outside elig_pool (n_pairs>=M_CHOSEN presplit, "
              f"pair-count not position-count): {len(missing_raw)}/{len(raw_survivors)}")
        print(f"[selfcheck] bh survivors outside elig_pool: {len(missing_bh)}/{len(bh_survivors)}")
        print(f"[selfcheck] raw survivors with no presplit profile row at all: {len(no_profile_raw)}")
        print(f"[selfcheck] bh survivors with no presplit profile row at all: {len(no_profile_bh)}")
        assert not no_profile_raw, f"selfcheck FAILED: {len(no_profile_raw)} raw survivors have no profile row"
        assert not no_profile_bh, f"selfcheck FAILED: {len(no_profile_bh)} bh survivors have no profile row"
        print("[selfcheck] PASSED (profile-row precondition for match_control)")

    results = {}
    for label, cohort in (("raw", raw_survivors), ("bh", bh_survivors)):
        print(f"\n=== {label.upper()} cohort (n={len(cohort)}) ===")
        placebo = match_control(profile, cohort, elig_traders, seed=SEED, verbose=True)
        print(f"[{label}] matched placebo n={len(placebo)}")

        cohort_result = measure_oos(conn, cohort, T_SPLIT, verbose=True, label=f"{label}-cohort")
        placebo_result = measure_oos(conn, placebo, T_SPLIT, verbose=True, label=f"{label}-placebo")

        cohort_width = (cohort_result['ci_hi'] - cohort_result['ci_lo']) if cohort_result.get('ci_hi') is not None else None
        placebo_width = (placebo_result['ci_hi'] - placebo_result['ci_lo']) if placebo_result.get('ci_hi') is not None else None
        cohort_mde = half_width_mde(cohort_result)
        placebo_mde = half_width_mde(placebo_result)

        for r, w, mde, tag in ((cohort_result, cohort_width, cohort_mde, "cohort"),
                                (placebo_result, placebo_width, placebo_mde, "placebo")):
            if w is not None:
                print(f"[{label}-{tag}] point_gap={r['point_gap']:.4f} CI=[{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] "
                      f"width={w:.4f} ({w*100:.1f}pp) mde~{mde:.4f} "
                      f"n_positions={r['n_positions']} n_traders={r['n_surviving_traders']}")
            else:
                print(f"[{label}-{tag}] no positions/no result")

        results[label] = dict(
            cohort_n_input=len(cohort), placebo_n_input=len(placebo),
            cohort=cohort_result, placebo=placebo_result,
            cohort_width=cohort_width, placebo_width=placebo_width,
            cohort_mde_half_width=cohort_mde, placebo_mde_half_width=placebo_mde,
        )

    conn.close()

    print("\n=== COMPARISON TO RESULT OF RECORD AND COST FLOORS ===")
    print(f"result of record: point_gap={RESULT_OF_RECORD['point_gap']} "
          f"CI=[{RESULT_OF_RECORD['ci_lo']}, {RESULT_OF_RECORD['ci_hi']}] "
          f"width={RESULT_OF_RECORD['width']:.4f} ({RESULT_OF_RECORD['width']*100:.1f}pp) "
          f"n_positions={RESULT_OF_RECORD['n_positions']} n_traders={RESULT_OF_RECORD['n_traders']}")
    print(f"cost floors: geopolitics {COST_FLOOR_GEOPOLITICS}, elections {COST_FLOOR_ELECTIONS}")
    for label in ("raw", "bh"):
        w = results[label]['cohort_width']
        mde = results[label]['cohort_mde_half_width']
        if w is not None:
            exceeds_record = w > RESULT_OF_RECORD['width']
            print(f"[{label}] cohort width {w*100:.1f}pp "
                  f"{'EXCEEDS' if exceeds_record else 'within'} the ~8pp result-of-record width; "
                  f"mde~{mde:.4f} vs geo floor {COST_FLOOR_GEOPOLITICS} / elec floor {COST_FLOOR_ELECTIONS}")

    out = dict(
        spec="directional_skill_pit_power_estimate",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        seed=SEED, t_split=T_SPLIT,
        input_pit_pool_json=args.pit_pool_json,
        result_of_record=RESULT_OF_RECORD,
        cost_floor_geopolitics=COST_FLOOR_GEOPOLITICS,
        cost_floor_elections=COST_FLOOR_ELECTIONS,
        results=results,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
