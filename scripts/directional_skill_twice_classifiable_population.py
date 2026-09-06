#!/usr/bin/env python3
"""
TWICE-CLASSIFIABLE POPULATION COUNT -- Part 3 of brain/decisions/
2026-09-06-match-control-determinism-fix.md. Answers Open Question 1 from
the persistence pre-registration (trading-swarm 7743740, §3): how many of
Part B's PIT-legal classifiable traders (5,732) ALSO have >= M_CHOSEN post-
split resolved positions.

COUNTS ONLY. Does not compute, and must never compute, any post-split
sign-flip null, p-value, classification, or outcome-dependent quantity --
that computation is the pre-registered persistence test itself, reserved
for its own approved run. This script only counts post-split RESOLVED
positions per trader (a structural fact -- category/gap-flag/entry-price/
trade-result-closed, per the project's standard "resolved position"
filter -- not a direction or an outcome), using load_post_split_positions()
imported unchanged from directional_skill_diagnostic.py for the identical
structural filter Part B and Step 3 already used, then a plain
groupby().size(). No sign_flip_null, classify, bh_correction, or
per_trader_and_aggregate call appears anywhere in this file.

Pre-split BH classification is READ from Part B's already-committed
artifact (directional_skill_pit_legal_pool_20260906T160303Z.json,
per_trader_result.per_trader[trader].bh_significant) -- not recomputed.
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
from scripts.trader_skill_metric_v2f import T_SPLIT, M_CHOSEN
from scripts.directional_skill_diagnostic import load_post_split_positions

EXPECTED_CLASSIFIABLE = 5732
EXPECTED_RAW_SURVIVORS = 711
EXPECTED_BH_SURVIVORS = 504


def distribution_stats(counts):
    arr = np.asarray(counts, dtype=float)
    if len(arr) == 0:
        return dict(n_traders=0)
    return dict(
        n_traders=len(arr),
        median=float(np.median(arr)), mean=float(np.mean(arr)),
        p10=float(np.percentile(arr, 10)), p25=float(np.percentile(arr, 25)),
        p75=float(np.percentile(arr, 75)), p90=float(np.percentile(arr, 90)),
        max=int(arr.max()), min=int(arr.min()),
    )


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--pit-pool-json', default='data/characterizations/directional_skill_pit_legal_pool_20260906T160303Z.json')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = json.load(open(args.pit_pool_json))
    per_trader = d['per_trader_result']['per_trader']
    classifiable_traders = sorted(per_trader.keys())

    print(f"[part b readback] classifiable pre-split traders: {len(classifiable_traders)}")
    if len(classifiable_traders) != EXPECTED_CLASSIFIABLE:
        print(f"[STOP] classifiable count {len(classifiable_traders)} != Part B's reported "
              f"{EXPECTED_CLASSIFIABLE} -- contradicts the Part B doc.", file=sys.stderr)
        sys.exit(1)

    bh_skilled = set(t for t, v in per_trader.items() if v['bh_significant'])
    not_bh_skilled = set(classifiable_traders) - bh_skilled
    print(f"[part b readback] pre-split BH-skilled: {len(bh_skilled)}, "
          f"pre-split NOT BH-skilled: {len(not_bh_skilled)}")

    conn = db_connect(args.db)
    print(f"\n=== counting POST-split resolved positions per trader "
          f"(structural filter only, no classification) ===")
    post_split_df = load_post_split_positions(conn, classifiable_traders, T_SPLIT)
    conn.close()

    counts = post_split_df.groupby('trader').size()
    all_counts = counts.reindex(classifiable_traders, fill_value=0).astype(int)

    if args.selfcheck:
        print("\n=== selfcheck: cross-check against Part B's own survival counts "
              "(any >=1 post-split position, no min threshold) -- pure re-derivation, "
              "load_post_split_positions() has no randomness, must match exactly ===")
        any_position = set(all_counts[all_counts >= 1].index)
        raw_skilled_set = set(d['raw_skilled_traders'])
        bh_skilled_set = set(d['bh_skilled_traders'])
        recomputed_raw_survivors = sorted(any_position & raw_skilled_set)
        recomputed_bh_survivors = sorted(any_position & bh_skilled_set)
        raw_match = recomputed_raw_survivors == sorted(d['survival']['raw_survivors'])
        bh_match = recomputed_bh_survivors == sorted(d['survival']['bh_survivors'])
        print(f"[selfcheck] recomputed raw survivors: {len(recomputed_raw_survivors)} "
              f"(Part B: {len(d['survival']['raw_survivors'])}) match={raw_match}")
        print(f"[selfcheck] recomputed bh survivors: {len(recomputed_bh_survivors)} "
              f"(Part B: {len(d['survival']['bh_survivors'])}) match={bh_match}")
        if not (raw_match and bh_match):
            print("[selfcheck] FAILED: re-derivation diverged from Part B's committed survival "
                  "lists -- this function is pure SQL + groupby, no randomness, so any mismatch "
                  "here is a real bug, not the match_control()-style nondeterminism.", file=sys.stderr)
            sys.exit(1)
        if len(recomputed_raw_survivors) != EXPECTED_RAW_SURVIVORS or len(recomputed_bh_survivors) != EXPECTED_BH_SURVIVORS:
            print(f"[STOP] survival counts ({len(recomputed_raw_survivors)} raw / "
                  f"{len(recomputed_bh_survivors)} bh) != Part B's reported "
                  f"({EXPECTED_RAW_SURVIVORS} raw / {EXPECTED_BH_SURVIVORS} bh) -- "
                  f"contradicts the Part B doc.", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED: exact match, as expected for a pure counting function")

    print(f"\n=== TWICE-CLASSIFIABLE POPULATION: n >= M_CHOSEN ({M_CHOSEN}) post-split ===")
    twice_classifiable = set(all_counts[all_counts >= M_CHOSEN].index)
    twice_classifiable_bh = twice_classifiable & bh_skilled
    twice_classifiable_not_bh = twice_classifiable & not_bh_skilled

    print(f"[1] twice-classifiable population size: {len(twice_classifiable)}")
    print(f"[2] of those, pre-split BH-skilled (persistence cohort, N): {len(twice_classifiable_bh)}")
    print(f"[3] of those, pre-split NOT BH-skilled (comparison group): {len(twice_classifiable_not_bh)}")

    dist_all = distribution_stats(all_counts.loc[sorted(twice_classifiable)])
    dist_bh = distribution_stats(all_counts.loc[sorted(twice_classifiable_bh)])
    dist_not_bh = distribution_stats(all_counts.loc[sorted(twice_classifiable_not_bh)])
    print(f"[4] post-split position-count distribution, twice-classifiable population: {dist_all}")
    print(f"[5a] ... pre-split BH-skilled subset: {dist_bh}")
    print(f"[5b] ... pre-split NOT BH-skilled subset: {dist_not_bh}")

    print(f"\n=== [6] SENSITIVITY REFERENCE ONLY -- M_CHOSEN={M_CHOSEN} is FIXED by the "
          f"pre-registration and not changed by this table ===")
    sensitivity = {}
    for thresh in (5, 15, 20):
        grp = set(all_counts[all_counts >= thresh].index)
        grp_bh = grp & bh_skilled
        grp_not_bh = grp & not_bh_skilled
        sensitivity[thresh] = dict(
            total=len(grp), bh_skilled=len(grp_bh), not_bh_skilled=len(grp_not_bh),
        )
        print(f"  threshold={thresh}: total={len(grp)} bh_skilled={len(grp_bh)} "
              f"not_bh_skilled={len(grp_not_bh)}")

    out = dict(
        spec="directional_skill_twice_classifiable_population",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        t_split=T_SPLIT, m_chosen=M_CHOSEN,
        source_pit_pool_json=args.pit_pool_json,
        n_classifiable_presplit=len(classifiable_traders),
        n_presplit_bh_skilled=len(bh_skilled),
        n_presplit_not_bh_skilled=len(not_bh_skilled),
        twice_classifiable_population_size=len(twice_classifiable),
        persistence_cohort_size_N=len(twice_classifiable_bh),
        comparison_group_size=len(twice_classifiable_not_bh),
        twice_classifiable_traders=sorted(twice_classifiable),
        persistence_cohort_traders=sorted(twice_classifiable_bh),
        comparison_group_traders=sorted(twice_classifiable_not_bh),
        post_split_count_distribution_all=dist_all,
        post_split_count_distribution_bh_skilled=dist_bh,
        post_split_count_distribution_not_bh_skilled=dist_not_bh,
        sensitivity_reference=sensitivity,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
