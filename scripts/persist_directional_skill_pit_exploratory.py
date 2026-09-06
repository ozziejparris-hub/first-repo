#!/usr/bin/env python3
"""
CUSTODY: persist the 2026-09-06 PIT-pool/power-estimate edge measurements as
EXPLORATORY -- Part 1D of brain/decisions/2026-09-06-directional-skill-
exploratory-custody.md.

THESE FIGURES ARE NOT PRE-REGISTERED. They were produced as an unavoidable
by-product of directional_skill_pit_power_estimate.py's clustered-bootstrap
POWER ESTIMATE (Step 3, first-repo 4feb97f), not as a planned test of
anything. They do NOT supersede, amend, or touch the result of record
(+0.0316, CI[-0.0088,+0.0710], n=3,032/120, metric_v2f_oos_result), which
stands permanently per Oscar's 2026-08-21 decision. This script writes ONLY
to new, separately-named tables/artifacts -- it never touches
metric_v2f_oos_result, metric_v2f_intersection_cohort, metric_v2f_findings,
or metric_v2f_consensus_result.

WHAT THIS SCRIPT DOES: re-derives the trader-level MEMBERSHIP of the four
2026-09-06 groups (raw-cohort, raw-placebo, bh-cohort, bh-placebo) by calling
build_presplit_cohort() / match_control() (imported unchanged from
trader_skill_metric_v2f.py, same seed) -- the exact same calls
directional_skill_pit_power_estimate.py already made, whose trader-level
output was not previously saved (only aggregates were). It also determines,
per placebo trader, whether they individually survived into the post-split
window (load_post_split_positions(), imported unchanged), since
measure_oos() itself reports only a surviving COUNT, not which traders.

THIS IS CUSTODY WORK ON AN ALREADY-COMPLETED EXPLORATORY RESULT, NOT A NEW
MEASUREMENT: the --selfcheck flag recomputes measure_oos() on each
re-derived group and asserts the point_gap/CI/n_positions match the already-
persisted Step 3 JSON artifact within tolerance -- a determinism check, not
a new statistical test. It is not, and must not be treated as, any part of
the Part 2 directional-skill PERSISTENCE test (a different, not-yet-run
question), which this script does not touch.

Follows the Objective-1 persistence pattern (metric_v2f_intersection_cohort)
-- trader-level membership persisted, not just aggregates -- named as the
mechanism behind the 2026-08-16 UNREPRODUCIBLE verdict for Objective 2,
which persisted only aggregate counts.
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
from scripts.directional_skill_diagnostic import load_post_split_positions

SPEC_VERSION = "DIRSKILL-PIT-EXPLORATORY-2026-09-06-v1"
IS_EXPLORATORY = 1
IS_PREREGISTERED = 0
PRODUCED_AS_BYPRODUCT_OF = (
    "clustered-bootstrap power estimate (Step 3, directional_skill_pit_power_estimate.py, "
    "first-repo 4feb97f) -- not a planned/pre-registered test"
)
ASYMMETRY_NOTE = (
    "1B FINDING (see 2026-09-06-directional-skill-exploratory-custody.md): the cohort "
    "arm was drawn from an already post-split-survival-filtered list (Part B's "
    "raw/bh_survivors, defined as skilled AND with >=1 post-split resolved position), "
    "while the placebo arm was matched on PRE-split profile only via match_control(), "
    "with no post-split-survival condition -- hence cohort measure_oos surviving rate is "
    "100% by construction and placebo's is ~52-56%. The two arms are NOT like-for-like "
    "as constructed. Not fixed here; reported for any reader of these figures."
)

MDE_HALF_WIDTH = dict(raw=dict(cohort=0.0209, placebo=0.0257), bh=dict(cohort=0.0248, placebo=0.0289))


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def build_groups(conn, pit_pool_json):
    d = json.load(open(pit_pool_json))
    raw_survivors = set(d['survival']['raw_survivors'])
    bh_survivors = set(d['survival']['bh_survivors'])

    presplit_data = build_presplit_cohort(conn, T_SPLIT, verbose=False)
    elig_traders = set(presplit_data['elig_pool']['trader'])
    profile = presplit_data['profile']

    matched_placebo_raw = match_control(profile, raw_survivors, elig_traders, seed=SEED, verbose=False)
    matched_placebo_bh = match_control(profile, bh_survivors, elig_traders, seed=SEED, verbose=False)

    post_split_raw_placebo = load_post_split_positions(conn, matched_placebo_raw, T_SPLIT)
    post_split_bh_placebo = load_post_split_positions(conn, matched_placebo_bh, T_SPLIT)
    survived_raw_placebo = set(post_split_raw_placebo['trader'].unique()) if len(post_split_raw_placebo) else set()
    survived_bh_placebo = set(post_split_bh_placebo['trader'].unique()) if len(post_split_bh_placebo) else set()

    return dict(
        raw=dict(cohort=raw_survivors, placebo=matched_placebo_raw, placebo_survived=survived_raw_placebo),
        bh=dict(cohort=bh_survivors, placebo=matched_placebo_bh, placebo_survived=survived_bh_placebo),
    )


NONDETERMINISM_NOTE = (
    "DISCOVERED 2026-09-06 (this custody pass): match_control() "
    "(trader_skill_metric_v2f.py) does not fully determine its output from its "
    "`seed` parameter alone. cohort_traders and elig_traders are Python sets; "
    "match_control() calls list() on them before shuffling/iterating, and CPython's "
    "set iteration order for strings depends on the process-level hash seed "
    "(PYTHONHASHSEED), which is randomized fresh per process by default and is not "
    "fixed by this function's seed argument. Re-running match_control() with the "
    "identical seed=42 in a separate process (this script) reproduced the COHORT "
    "membership exactly (cohort membership does not depend on match_control at all -- "
    "it is Part B's already-persisted survivor list) but did NOT reproduce the "
    "PLACEBO membership or its resulting point_gap/CI from the committed Step 3 "
    "artifact. This affects every prior placebo constructed via match_control(), "
    "including the 2026-08-15 result-of-record placebo and the 2026-09-06 Step 3 "
    "placebo -- neither is exactly reconstructable from its recorded seed alone. Not "
    "fixed here, per this task's scope; reported as a finding."
)


def selfcheck(conn, groups, power_json_path, verbose=True):
    """Recomputes measure_oos() on each re-derived group and compares it to the
    already-persisted Step 3 artifact -- a determinism check on already-completed
    exploratory work, not a new measurement. NOTE: as discovered during this task,
    the placebo arms are NOT expected to match exactly -- see NONDETERMINISM_NOTE.
    Cohort mismatches, by contrast, indicate a real bug (cohort membership is a
    fixed list from Part B, no match_control() involved) and remain fatal."""
    power = json.load(open(power_json_path))
    mism = []
    for rule in ('raw', 'bh'):
        for role in ('cohort', 'placebo'):
            traders = groups[rule][role]
            recomputed = measure_oos(conn, traders, T_SPLIT, verbose=False, label=f"selfcheck-{rule}-{role}")
            persisted = power['results'][rule][role]
            for field in ('point_gap', 'ci_lo', 'ci_hi', 'n_positions'):
                a, b = recomputed.get(field), persisted.get(field)
                if a is None or b is None:
                    if a != b:
                        mism.append((rule, role, field, a, b))
                    continue
                tol = 1e-6 if field == 'n_positions' else 1e-4
                if abs(a - b) > tol:
                    mism.append((rule, role, field, a, b))
            if verbose:
                print(f"[selfcheck] {rule}-{role}: recomputed point_gap={recomputed.get('point_gap')} "
                      f"vs persisted {persisted.get('point_gap')}")
            if role == 'placebo':
                groups[rule]['placebo_redevrived_result'] = recomputed
    cohort_mism = [m for m in mism if m[1] == 'cohort']
    placebo_mism = [m for m in mism if m[1] == 'placebo']
    return dict(cohort_mismatches=cohort_mism, placebo_mismatches=placebo_mism, all_mismatches=mism)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--pit-pool-json', default='data/characterizations/directional_skill_pit_legal_pool_20260906T160303Z.json')
    ap.add_argument('--power-json', default='data/characterizations/directional_skill_pit_power_estimate_20260906T160818Z.json')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    generated_at = datetime.now(timezone.utc).isoformat()
    generator_commit = git_commit(repo_dir)

    conn = db_connect(args.db)
    print("=== re-deriving trader-level membership (deterministic, same seed as Step 3) ===")
    groups = build_groups(conn, args.pit_pool_json)
    for rule in ('raw', 'bh'):
        print(f"[{rule}] cohort n={len(groups[rule]['cohort'])} placebo n={len(groups[rule]['placebo'])} "
              f"placebo survived n={len(groups[rule]['placebo_survived'])}")

    mism = dict(cohort_mismatches=[], placebo_mismatches=[], all_mismatches=[])
    if args.selfcheck:
        print("\n=== selfcheck: recompute measure_oos(), compare to persisted Step 3 JSON ===")
        mism = selfcheck(conn, groups, args.power_json, verbose=True)
        if mism['cohort_mismatches']:
            print(f"[selfcheck] FAILED: {len(mism['cohort_mismatches'])} COHORT mismatches "
                  f"(cohort membership does not involve match_control -- this would be a real bug): "
                  f"{mism['cohort_mismatches']}", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] cohort figures match the persisted Step 3 artifact exactly, as expected")
        if mism['placebo_mismatches']:
            print(f"[selfcheck] PLACEBO figures do NOT match the persisted Step 3 artifact "
                  f"({len(mism['placebo_mismatches'])} field mismatches). This is the expected "
                  f"signature of the match_control() PYTHONHASHSEED nondeterminism discovered in "
                  f"this task -- see NONDETERMINISM_NOTE. NOT treated as a script failure; both the "
                  f"original committed figures and this run's re-derivation are persisted, clearly "
                  f"labelled, below.")
        else:
            print("[selfcheck] placebo figures also matched exactly this run (can happen by chance "
                  "of process hash-seed) -- still not proof of guaranteed reproducibility; "
                  "NONDETERMINISM_NOTE still applies to the mechanism.")

    power = json.load(open(args.power_json))

    aggregate_rows = []
    membership_rows = []
    for rule in ('raw', 'bh'):
        for role in ('cohort', 'placebo'):
            traders = groups[rule][role]
            r = power['results'][rule][role]  # original, committed Step 3 figures -- never overwritten
            group_name = f"{rule}_{role}"
            membership_verified = (role == 'cohort')  # cohort: exact by construction; placebo: see note
            redevrived = groups[rule].get('placebo_redevrived_result') if role == 'placebo' else None
            aggregate_rows.append(dict(
                group_name=group_name, selection_rule=rule, role=role,
                n_traders_input=len(traders),
                n_traders_surviving=r.get('n_surviving_traders'),
                n_positions=r.get('n_positions'),
                point_gap=r.get('point_gap'), ci_lo=r.get('ci_lo'), ci_hi=r.get('ci_hi'),
                mde_half_width=MDE_HALF_WIDTH[rule][role],
                is_exploratory=IS_EXPLORATORY, is_preregistered=IS_PREREGISTERED,
                produced_as_byproduct_of=PRODUCED_AS_BYPRODUCT_OF,
                asymmetry_note=ASYMMETRY_NOTE,
                membership_verified_matches_original=int(membership_verified),
                nondeterminism_note=(NONDETERMINISM_NOTE if role == 'placebo' else None),
                redevrived_point_gap=(redevrived.get('point_gap') if redevrived else None),
                redevrived_ci_lo=(redevrived.get('ci_lo') if redevrived else None),
                redevrived_ci_hi=(redevrived.get('ci_hi') if redevrived else None),
                redevrived_n_positions=(redevrived.get('n_positions') if redevrived else None),
                redevrived_n_traders_surviving=(redevrived.get('n_surviving_traders') if redevrived else None),
                spec_version=SPEC_VERSION, seed=SEED, t_split=T_SPLIT,
                generated_at=generated_at, generator_commit=generator_commit,
                source_pit_pool_json=args.pit_pool_json, source_power_estimate_json=args.power_json,
            ))
            survived_set = traders if role == 'cohort' else groups[rule]['placebo_survived']
            for t in sorted(traders):
                membership_rows.append(dict(
                    trader=t, group_name=group_name, role=role, selection_rule=rule,
                    survived_post_split=int(t in survived_set),
                    membership_verified_matches_original=int(membership_verified),
                    spec_version=SPEC_VERSION, generated_at=generated_at, generator_commit=generator_commit,
                ))

    print(f"\n[summary] {len(aggregate_rows)} aggregate rows, {len(membership_rows)} membership rows")

    if args.persist:
        c = db_connect(args.db)
        c.execute("DROP TABLE IF EXISTS directional_skill_pit_exploratory_result")
        c.execute("""CREATE TABLE directional_skill_pit_exploratory_result (
            group_name TEXT PRIMARY KEY, selection_rule TEXT, role TEXT,
            n_traders_input INTEGER, n_traders_surviving INTEGER, n_positions INTEGER,
            point_gap REAL, ci_lo REAL, ci_hi REAL, mde_half_width REAL,
            is_exploratory INTEGER, is_preregistered INTEGER,
            produced_as_byproduct_of TEXT, asymmetry_note TEXT,
            membership_verified_matches_original INTEGER, nondeterminism_note TEXT,
            redevrived_point_gap REAL, redevrived_ci_lo REAL, redevrived_ci_hi REAL,
            redevrived_n_positions INTEGER, redevrived_n_traders_surviving INTEGER,
            spec_version TEXT, seed INTEGER, t_split TEXT,
            generated_at TEXT, generator_commit TEXT,
            source_pit_pool_json TEXT, source_power_estimate_json TEXT)""")
        for row in aggregate_rows:
            c.execute("""INSERT INTO directional_skill_pit_exploratory_result VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                row['group_name'], row['selection_rule'], row['role'],
                row['n_traders_input'], row['n_traders_surviving'], row['n_positions'],
                row['point_gap'], row['ci_lo'], row['ci_hi'], row['mde_half_width'],
                row['is_exploratory'], row['is_preregistered'],
                row['produced_as_byproduct_of'], row['asymmetry_note'],
                row['membership_verified_matches_original'], row['nondeterminism_note'],
                row['redevrived_point_gap'], row['redevrived_ci_lo'], row['redevrived_ci_hi'],
                row['redevrived_n_positions'], row['redevrived_n_traders_surviving'],
                row['spec_version'], row['seed'], row['t_split'],
                row['generated_at'], row['generator_commit'],
                row['source_pit_pool_json'], row['source_power_estimate_json']))

        c.execute("DROP TABLE IF EXISTS directional_skill_pit_exploratory_membership")
        c.execute("""CREATE TABLE directional_skill_pit_exploratory_membership (
            trader TEXT, group_name TEXT, role TEXT, selection_rule TEXT,
            survived_post_split INTEGER, membership_verified_matches_original INTEGER,
            spec_version TEXT, generated_at TEXT, generator_commit TEXT,
            PRIMARY KEY (trader, group_name))""")
        for row in membership_rows:
            c.execute("""INSERT INTO directional_skill_pit_exploratory_membership VALUES
                (?,?,?,?,?,?,?,?,?)""", (
                row['trader'], row['group_name'], row['role'], row['selection_rule'],
                row['survived_post_split'], row['membership_verified_matches_original'],
                row['spec_version'], row['generated_at'], row['generator_commit']))
        c.commit()
        c.close()
        print("[persist] directional_skill_pit_exploratory_result, "
              "directional_skill_pit_exploratory_membership written (NOT metric_v2f_oos_result)")

    conn.close()

    out = dict(
        spec="persist_directional_skill_pit_exploratory",
        is_exploratory=bool(IS_EXPLORATORY), is_preregistered=bool(IS_PREREGISTERED),
        produced_as_byproduct_of=PRODUCED_AS_BYPRODUCT_OF, asymmetry_note=ASYMMETRY_NOTE,
        generated_at=generated_at, generator_commit=generator_commit,
        seed=SEED, t_split=T_SPLIT, spec_version=SPEC_VERSION,
        source_pit_pool_json=args.pit_pool_json, source_power_estimate_json=args.power_json,
        selfcheck_mismatches=mism,
        aggregate_rows=aggregate_rows, membership_rows=membership_rows,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
