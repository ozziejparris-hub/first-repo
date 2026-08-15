#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2f -- AMENDMENT to v2e (lineage SKILLV2-2026-08-15-v1
-> ... -> SKILLV2E -> SKILLV2F). Closes the cost-floor gap v2e flagged, then
asks the thesis question this entire arc exists to answer, properly and
out-of-sample, for the first time on a metric known to be correctly
normalised. Read-only. No production writes. No changes to
update_geo_elo.py, geo_elo_active, cohort membership, or any live path.
No cutover decision.

=============================================================================
WHY (recorded so the framing survives)
=============================================================================
v2e's coverage gate caught a real conceptual error before anything was
reported: the first small-sample correction used a t-interval (df=n-1) on
top of an ALREADY-KNOWN population variance -- double-penalising, since the
thin-trader penalty is already carried by the 1/n_i terms in the variance
formula. Corrected to a z-interval: coverage simulation 5.56% vs nominal 5%
(essentially exact), old bootstrap's 30.6% explaining v2d's spurious 52%
"significant" figure directly. Significance-95 + M>=10 now yields 360
traders (1.3% of the population), profile indistinguishable in kind from
percentile cohorts (median 48 positions / 23 markets).

DECISION TAKEN (recorded, not re-litigated here): significance-95 +
M>=10 is the DEFINITIONAL rule; effect-size >=0.02 is a REQUIRED SECONDARY
FILTER for "tradeable" vs merely "provably nonzero." Percentile rejected as
primary -- it always has a top 1% even under zero true skill variance, and
its better turnover was partly an artifact of rewarding volume, precisely
what this arc has corrected since Layer 0.

Every prior test of the underlying thesis (Layer 0 through the FABLE
consensus design) ran on geo_elo -- since shown improper (sign error
rewarding favourite-betting No traders), SELL-contaminated (35.7% of
qualifying rows scored under an inverted win-condition), double-counted
(86.3% of qualifying trades in multi-trade pairs), volume-weighted by
accident, and thresholded on an inherited, uncalibrated ladder. The thesis
has never been tested on a trustworthy skill measure. This pass is that
test.

=============================================================================
AMENDMENT PRE-REGISTRATION (fixed before computing; written to
metric_v2f_amendment before any result row)
=============================================================================

--- OBJECTIVE 1: close the cost-floor gap ---
For the existing 360-trader (significance-95, M>=10) cohort: distribution
of shrunk edge, counts clearing >=0.02/0.03/0.05. INTERSECTION cohort
(significant AND M>=10 AND shrunk edge>=0.02) reported explicitly with its
overlap against the 360, the 392 (effect-size>=0.02 alone), and current
LEGENDARY. Cost floor computed concretely: fee =
shares*feeRate*price*(1-price) (feeRate~0.04, elections/politics only --
geopolitics is fee-free) plus a spread cost (0.001-0.02 per B4's captured
range), evaluated at the cohort's OWN empirically observed typical entry
prices per category (not an assumed p=0.5), reported separately for
Geopolitics and Elections since the fee-free/fee-bearing split means one
blended floor would misrepresent both.

--- OBJECTIVE 2: the thesis, out-of-sample, for the first time on a
    trustworthy metric ---
COHORT: the Objective-1 intersection (significant, M>=10, edge>=0.02).
SPLIT: T_split = 2026-04-01 00:00:00, chosen on volume/power grounds ALONE,
before computing any outcome -- quarterly position counts show 63% of all
positions (216,972) fall on or before 2026-03-31 and 37% (125,468) after,
a well-powered split on both sides; it also happens to match the original
FABLE design's own train/validation boundary (2026-03-31), an independent
prior endorsement of this date, not chosen to flatter this pass's result.
COHORT DEFINITION uses ONLY positions whose market had already resolved by
T_split (tape_end <= T_split, not merely entered by then -- the same PIT
discipline as every "as-of" reconstruction in this arc), with sigma2_within
re-estimated fresh on that pre-split population (not reusing the
full-population value, matching v2d/v2e's own convention for "what a live
system would have actually known"). MEASUREMENT: mean market-relative edge
across every position entered by a surviving cohort member AFTER T_split,
two-way trader x market clustered, cap5-weighted -- the same machinery
that passed its own properly-weighted gate in v2d, applied here to a plain
mean rather than a calibration-bucket gap. This is the INDIVIDUAL-trader
question, not the consensus question -- deliberately, per the pre-
registration's own instruction not to reintroduce the >=2-member consensus
construct (which cost ~99% of sample under geo_elo) before the simpler
question is answered.
PLACEBO: a control cohort matched on pre-split position count, market
breadth, and activity period from the SAME M>=10-eligible pool, but NOT
selected on edge (nearest-neighbour match, greedy, without replacement,
seeded) -- measured on the identical post-split window. A non-null control
would mean the measurement is picking up something structural, and the
cohort result would not be interpretable on its own.
ANSWER REPORTED PLAINLY EITHER WAY -- a null result is a real, valuable
answer and the reason this whole arc built a trustworthy metric was to be
able to believe it.

--- OBJECTIVE 3: consensus, ONLY if Objective 2 is positive ---
If, and only if, the out-of-sample cohort edge is positive with a CI that
excludes zero AND the placebo does not: test whether >=2 cohort members
agreeing on the same market predicts better than a single member's
position, out-of-sample, same window. If consensus adds nothing over the
individual-trader signal, that is reported as a major simplification, not
suppressed for not matching the original design's assumption.

--- UNCHANGED CONSTRAINTS ---
No production writes. update_geo_elo.py / geo_elo_active / cohort
membership untouched. No cutover. Do not re-specify to obtain a preferred
result. A null Objective 2 result is reported as null.

Persists metric_v2f_amendment, metric_v2f_cost_floor,
metric_v2f_intersection_cohort, metric_v2f_oos_result,
metric_v2f_placebo_result, metric_v2f_findings (and
metric_v2f_consensus_result only if Objective 3 runs).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import load_entries, db_connect
from scripts.trader_skill_metric_v2c import build_pairs, eb_shrinkage_weighted, WEIGHT_FNS
from scripts.trader_skill_metric_v2d import (
    weighted_pair_table, weighted_two_way_gap_bootstrap, compute_cap5_metric, build_tape_end_map,
    GATE_REPS,
)
from scripts.trader_skill_metric_v2e import per_trader_t_ci

SPEC_VERSION = "SKILLV2F-2026-08-15-v1"
SEED = 42
GATE_REPS_LOCAL = 1500
M_CHOSEN = 10
EFFECT_BAR = 0.02
T_SPLIT = "2026-04-01 00:00:00"
FEE_RATE_ELECTIONS = 0.04
SPREAD_LO, SPREAD_HI = 0.001, 0.02

AMENDMENT_WHY = (
    "v2e's coverage gate caught a real bug (t-interval double-penalising on top of an already-known "
    "population variance) before reporting; corrected to a z-interval, 5.56% vs nominal 5%. "
    "Significance-95 + M>=10 now yields 360 traders (1.3%), a plausible, non-thin cohort. Decision taken: "
    "significance-95+M>=10 is the definitional rule, effect-size>=0.02 the required secondary filter for "
    "'tradeable.' Every prior test of the underlying thesis ran on geo_elo, since shown improper, SELL-"
    "contaminated, double-counted, volume-weighted by accident, and thresholded on an uncalibrated ladder. "
    "This pass asks the thesis question on a trustworthy metric for the first time, out-of-sample."
)
OBJ1_TEXT = (
    "Distribution of the 360-trader cohort's shrunk edge; intersection with effect-size>=0.02 reported "
    "explicitly (not assumed from similar counts); cost floor computed concretely at the cohort's own "
    "empirical typical prices, separately for Geopolitics (fee-free) and Elections (~4% feeRate peaking "
    "at p=0.50), since a blended number would misrepresent both."
)
OBJ2_TEXT = (
    "Thesis test, individual-trader form (not consensus), out-of-sample: cohort defined using ONLY data "
    "resolved by T_split=2026-04-01 (chosen on volume/power grounds before computing any outcome -- 63%/"
    "37% pre/post split, matching FABLE's own original train/validation boundary), edge measured only on "
    "positions entered after T_split, two-way trader x market clustered CI, cap5-weighted. Placebo: a "
    "matched control cohort (same eligibility pool, not selected on edge) measured identically. Reported "
    "plainly either way -- null is a real, valuable answer."
)
OBJ3_TEXT = (
    "Only if Objective 2 is positive (OOS CI excludes zero, positive direction, AND placebo does not): "
    "does >=2-member consensus predict better than a single member's position, out-of-sample, same "
    "window. If consensus adds nothing, reported as a major simplification, not suppressed."
)


def persist_amendment(conn, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2f_amendment")
    conn.execute("""
        CREATE TABLE metric_v2f_amendment (
            spec_version TEXT PRIMARY KEY, amends_spec_version TEXT, why TEXT,
            objective1 TEXT, objective2 TEXT, objective3 TEXT, t_split TEXT,
            registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2f_amendment VALUES (?,?,?,?,?,?,?,?,?)",
                 (SPEC_VERSION, "SKILLV2E-2026-08-15-v1", AMENDMENT_WHY, OBJ1_TEXT, OBJ2_TEXT, OBJ3_TEXT,
                  T_SPLIT, generated_at, generator_commit))
    conn.commit()


# ---------------------------------------------------------------------------
# Objective 1
# ---------------------------------------------------------------------------

def full_population_cohort(entries_df, conn, verbose=False):
    """Reproduces v2e's 360-trader (significance-95, M>=10) cohort on the
    full population, for Objective 1's characterisation."""
    pairs, eb, sigma2_within = compute_cap5_metric(entries_df)
    t_ci = per_trader_t_ci(pairs, sigma2_within)
    elig = t_ci[t_ci['n_pairs'] >= M_CHOSEN]
    sig95 = elig[elig['ci_lo_t'] > 0]
    eb_full = eb.merge(t_ci[['trader', 'ci_lo_t', 'ci_hi_t']], on='trader')
    if verbose:
        print(f"[objective1] reproduced cohort: {len(sig95)} traders (expect 360)")
    return pairs, eb_full, sig95


def cost_floor(entries_df, cohort_traders, conn, verbose=False):
    rows = conn.execute("""
        SELECT p.position_id, p.trader_address, m.category, p.entry_avg_price
        FROM positions p JOIN markets m ON m.market_id = p.market_id
        WHERE p.trader_address IN ({})
    """.format(",".join("?" for _ in cohort_traders)), list(cohort_traders)).fetchall()
    df = pd.DataFrame(rows, columns=['position_id', 'trader', 'category', 'price'])
    df = df[df['category'].isin(['Geopolitics', 'Elections'])]

    out = {}
    for cat in ('Geopolitics', 'Elections'):
        sub = df[df['category'] == cat]
        if len(sub) == 0:
            continue
        median_price = float(sub['price'].median())
        p25, p75 = float(sub['price'].quantile(0.25)), float(sub['price'].quantile(0.75))
        fee_rate = 0.0 if cat == 'Geopolitics' else FEE_RATE_ELECTIONS
        fee_at_median = fee_rate * median_price * (1 - median_price)
        fee_at_p25 = fee_rate * p25 * (1 - p25)
        fee_at_p75 = fee_rate * p75 * (1 - p75)
        cost_lo = SPREAD_LO / 2 + min(fee_at_median, fee_at_p25, fee_at_p75)
        cost_hi = SPREAD_HI / 2 + max(fee_at_median, fee_at_p25, fee_at_p75)
        out[cat] = dict(n_positions=len(sub), median_price=median_price, p25_price=p25, p75_price=p75,
                        fee_rate=fee_rate, fee_at_median=fee_at_median,
                        cost_floor_lo=cost_lo, cost_floor_hi=cost_hi)
        if verbose:
            print(f"  {cat}: n={len(sub)} median_price={median_price:.3f} fee_rate={fee_rate} "
                  f"fee_at_median={fee_at_median:.4f} cost_floor=[{cost_lo:.4f},{cost_hi:.4f}]")
    return out


# ---------------------------------------------------------------------------
# Objective 2: OOS cohort definition, measurement, placebo
# ---------------------------------------------------------------------------

def build_presplit_cohort(conn, t_split, verbose=False):
    rows = conn.execute("""
        SELECT p.position_id, p.trader_address, p.market_id, p.outcome, p.entry_avg_price,
               p.entry_timestamp, t.trade_result
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """).fetchall()
    df = pd.DataFrame(rows, columns=['position_id', 'trader', 'market_id', 'outcome',
                                      'entry_avg_price', 'entry_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    df['edge'] = df['won'] - df['entry_avg_price']

    market_ids = df['market_id'].unique().tolist()
    tape_end = build_tape_end_map(conn, market_ids)
    df['tape_end'] = df['market_id'].map(tape_end)
    presplit = df[df['tape_end'].notna() & (df['tape_end'] <= t_split)].copy()
    if verbose:
        print(f"[presplit] {len(presplit)}/{len(df)} positions resolved by {t_split} (PIT-correct via tape_end)")

    pairs, eb, sigma2_within = compute_cap5_metric(presplit)
    t_ci = per_trader_t_ci(pairs, sigma2_within)
    elig = t_ci[t_ci['n_pairs'] >= M_CHOSEN]
    sig95 = elig[elig['ci_lo_t'] > 0]
    eb2 = eb.merge(t_ci[['trader', 'ci_lo_t']], on='trader')
    intersection = sig95.merge(eb2[['trader', 'shrunk_mean']], on='trader')
    intersection = intersection[intersection['shrunk_mean'] >= EFFECT_BAR]

    # activity profile for matching, from presplit pairs
    profile = pairs.groupby('trader').agg(
        n_positions=('n_positions', 'sum'), n_markets=('market_id', 'nunique')
    ).reset_index()
    activity = presplit.groupby('trader')['entry_ts'].agg(['min', 'max']).reset_index()
    profile = profile.merge(activity, on='trader')

    return dict(full_df=df, presplit=presplit, pairs=pairs, eb=eb2, sig95=sig95,
                intersection=intersection, profile=profile, elig_pool=elig)


def match_control(profile, cohort_traders, elig_traders, seed=SEED, verbose=False):
    """Greedy nearest-neighbour match on (log positions, log markets, activity
    span in days), from the M>=10-eligible pool, excluding the cohort itself."""
    prof = profile.set_index('trader')
    cohort_list = list(cohort_traders)
    pool = [t for t in elig_traders if t not in cohort_traders]
    pool_feats = {}
    for t in pool:
        r = prof.loc[t]
        span_days = (pd.to_datetime(r['max']) - pd.to_datetime(r['min'])).days
        pool_feats[t] = np.array([np.log1p(r['n_positions']), np.log1p(r['n_markets']), np.log1p(span_days)])

    rng = np.random.default_rng(seed)
    order = list(cohort_list)
    rng.shuffle(order)
    used = set()
    matches = {}
    pool_arr = np.array(list(pool_feats.values()))
    pool_keys = list(pool_feats.keys())
    for t in order:
        r = prof.loc[t]
        span_days = (pd.to_datetime(r['max']) - pd.to_datetime(r['min'])).days
        feat = np.array([np.log1p(r['n_positions']), np.log1p(r['n_markets']), np.log1p(span_days)])
        dists = np.linalg.norm(pool_arr - feat, axis=1)
        order_idx = np.argsort(dists)
        for idx in order_idx:
            cand = pool_keys[idx]
            if cand not in used:
                used.add(cand)
                matches[t] = cand
                break
    if verbose:
        print(f"[match] matched {len(matches)}/{len(cohort_list)} cohort traders to controls")
    return set(matches.values())


def measure_oos(conn, cohort_traders, t_split, verbose=False, label=""):
    if len(cohort_traders) == 0:
        return dict(n_positions=0, n_traders=0, point_gap=None, ci_lo=None, ci_hi=None)
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
    df = pd.DataFrame(rows, columns=['trader', 'market_id', 'outcome', 'price', 'entry_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    if verbose:
        print(f"[oos:{label}] {len(df)} positions, {df['trader'].nunique()} surviving traders, after {t_split}")
    if len(df) == 0:
        return dict(n_positions=0, n_traders=0, point_gap=None, ci_lo=None, ci_hi=None)

    pairs = weighted_pair_table(df, WEIGHT_FNS['cap5'])
    r = weighted_two_way_gap_bootstrap(pairs, reps=GATE_REPS_LOCAL, seed=SEED)
    r['n_positions'] = len(df)
    r['n_surviving_traders'] = int(df['trader'].nunique())
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)
    print(f"=== AMENDMENT (spec {SPEC_VERSION}) ===")
    print(f"WHY: {AMENDMENT_WHY}\n\nOBJECTIVE 1: {OBJ1_TEXT}\n\nOBJECTIVE 2: {OBJ2_TEXT}\n\nOBJECTIVE 3: {OBJ3_TEXT}\n")
    print(f"T_SPLIT = {T_SPLIT}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    if args.persist:
        persist_amendment(conn, generated_at, args.generator_commit)
        print("[persist] metric_v2f_amendment written\n")

    entries_df = load_entries(conn, verbose=args.verbose)

    # ============================= OBJECTIVE 1 =============================
    print("=== OBJECTIVE 1: cost-floor gap ===")
    pairs_full, eb_full, sig95_full = full_population_cohort(entries_df, conn, verbose=args.verbose)
    print(f"\nshrunk edge distribution, 360-cohort:")
    dist = eb_full[eb_full['trader'].isin(set(sig95_full['trader']))]['shrunk_mean']
    print(dist.describe())
    for bar in (0.02, 0.03, 0.05):
        n = (dist >= bar).sum()
        print(f"  clearing >= {bar}: {n}/{len(dist)}")

    intersection_traders = set(eb_full[(eb_full['trader'].isin(set(sig95_full['trader']))) &
                                       (eb_full['shrunk_mean'] >= EFFECT_BAR)]['trader'])
    effect_only_traders = set(eb_full[eb_full['shrunk_mean'] >= EFFECT_BAR]['trader'])
    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))

    print(f"\nINTERSECTION cohort (sig-95 AND M>=10 AND edge>=0.02): n={len(intersection_traders)}")
    print(f"  overlap with 360-cohort: {len(intersection_traders & set(sig95_full['trader']))}/{len(intersection_traders)}")
    print(f"  overlap with 392 (effect>=0.02 alone): {len(intersection_traders & effect_only_traders)}/{len(intersection_traders)}")
    print(f"  overlap with LEGENDARY: {len(intersection_traders & legendary)}/{len(legendary)}")

    cf = cost_floor(entries_df, intersection_traders, conn, verbose=True)

    if args.persist:
        c2 = db_connect(args.db)
        c2.execute("DROP TABLE IF EXISTS metric_v2f_cost_floor")
        c2.execute("""CREATE TABLE metric_v2f_cost_floor (category TEXT PRIMARY KEY, n_positions INTEGER,
            median_price REAL, p25_price REAL, p75_price REAL, fee_rate REAL, fee_at_median REAL,
            cost_floor_lo REAL, cost_floor_hi REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT)""")
        for cat, r in cf.items():
            c2.execute("INSERT INTO metric_v2f_cost_floor VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (cat, r['n_positions'], r['median_price'], r['p25_price'], r['p75_price'], r['fee_rate'],
                        r['fee_at_median'], r['cost_floor_lo'], r['cost_floor_hi'], SPEC_VERSION,
                        generated_at, args.generator_commit))
        c2.execute("DROP TABLE IF EXISTS metric_v2f_intersection_cohort")
        c2.execute("""CREATE TABLE metric_v2f_intersection_cohort (trader TEXT PRIMARY KEY, spec_version TEXT,
            generated_at TEXT, generator_commit TEXT)""")
        for t in intersection_traders:
            c2.execute("INSERT INTO metric_v2f_intersection_cohort VALUES (?,?,?,?)",
                       (t, SPEC_VERSION, generated_at, args.generator_commit))
        c2.commit()
        c2.close()
        print("[persist] metric_v2f_cost_floor, metric_v2f_intersection_cohort written")

    # ============================= OBJECTIVE 2 =============================
    print(f"\n=== OBJECTIVE 2: out-of-sample thesis test, T_split={T_SPLIT} ===")
    presplit_data = build_presplit_cohort(conn, T_SPLIT, verbose=args.verbose)
    oos_cohort = set(presplit_data['intersection']['trader'])
    print(f"pre-split intersection cohort: {len(oos_cohort)} traders")

    control_cohort = match_control(presplit_data['profile'], oos_cohort,
                                    set(presplit_data['elig_pool']['trader']), seed=args.seed, verbose=args.verbose)

    oos_result = measure_oos(conn, oos_cohort, T_SPLIT, verbose=True, label="cohort")
    placebo_result = measure_oos(conn, control_cohort, T_SPLIT, verbose=True, label="placebo")

    print(f"\n[OOS COHORT RESULT] n_positions={oos_result.get('n_positions')} "
          f"n_traders={oos_result.get('n_surviving_traders')} gap={oos_result.get('point_gap')} "
          f"CI=[{oos_result.get('ci_lo')},{oos_result.get('ci_hi')}]")
    print(f"[OOS PLACEBO RESULT] n_positions={placebo_result.get('n_positions')} "
          f"n_traders={placebo_result.get('n_surviving_traders')} gap={placebo_result.get('point_gap')} "
          f"CI=[{placebo_result.get('ci_lo')},{placebo_result.get('ci_hi')}]")

    cohort_excludes_zero = (oos_result.get('ci_lo') is not None and
                            (oos_result['ci_lo'] > 0 or oos_result['ci_hi'] < 0))
    cohort_positive = cohort_excludes_zero and oos_result['ci_lo'] > 0
    placebo_excludes_zero = (placebo_result.get('ci_lo') is not None and
                             (placebo_result['ci_lo'] > 0 or placebo_result['ci_hi'] < 0))

    print(f"\n[VERDICT] cohort CI excludes zero: {cohort_excludes_zero} (positive direction: {cohort_positive})")
    print(f"[VERDICT] placebo CI excludes zero: {placebo_excludes_zero}")
    if cohort_positive and not placebo_excludes_zero:
        thesis_verdict = "SUPPORTED, interpretable -- cohort shows a genuine out-of-sample edge, placebo does not."
    elif cohort_positive and placebo_excludes_zero:
        thesis_verdict = "NOT INTERPRETABLE -- placebo is also non-null; the measurement is picking up something structural, not cohort-specific skill."
    elif not cohort_excludes_zero:
        thesis_verdict = "NULL -- the cohort's out-of-sample edge does not exclude zero. The thesis is not supported at this cohort/window."
    else:
        thesis_verdict = "NEGATIVE -- the cohort's out-of-sample edge is significantly negative."
    print(f"[THESIS VERDICT] {thesis_verdict}")

    if args.persist:
        c3 = db_connect(args.db)
        c3.execute("DROP TABLE IF EXISTS metric_v2f_oos_result")
        c3.execute("""CREATE TABLE metric_v2f_oos_result (kind TEXT PRIMARY KEY, n_positions INTEGER,
            n_traders INTEGER, point_gap REAL, ci_lo REAL, ci_hi REAL, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT)""")
        c3.execute("INSERT INTO metric_v2f_oos_result VALUES (?,?,?,?,?,?,?,?,?)",
                   ('cohort', oos_result.get('n_positions'), oos_result.get('n_surviving_traders'),
                    oos_result.get('point_gap'), oos_result.get('ci_lo'), oos_result.get('ci_hi'),
                    SPEC_VERSION, generated_at, args.generator_commit))
        c3.execute("INSERT INTO metric_v2f_oos_result VALUES (?,?,?,?,?,?,?,?,?)",
                   ('placebo', placebo_result.get('n_positions'), placebo_result.get('n_surviving_traders'),
                    placebo_result.get('point_gap'), placebo_result.get('ci_lo'), placebo_result.get('ci_hi'),
                    SPEC_VERSION, generated_at, args.generator_commit))
        c3.commit()
        c3.close()
        print("[persist] metric_v2f_oos_result written")

    findings = dict(
        objective1=dict(intersection_n=len(intersection_traders), cost_floor=cf),
        objective2=dict(t_split=T_SPLIT, presplit_cohort_n=len(oos_cohort), control_n=len(control_cohort),
                        oos_result=oos_result, placebo_result=placebo_result,
                        thesis_verdict=thesis_verdict),
    )

    # ============================= OBJECTIVE 3 =============================
    run_consensus = cohort_positive and not placebo_excludes_zero
    if run_consensus:
        print("\n=== OBJECTIVE 3: consensus test (Objective 2 was positive and interpretable) ===")
        placeholders = ",".join("?" for _ in oos_cohort)
        rows = conn.execute(f"""
            SELECT p.trader_address, p.market_id, p.outcome, p.entry_avg_price, p.entry_timestamp, t.trade_result
            FROM positions p JOIN markets m ON m.market_id = p.market_id
            JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
            WHERE m.category IN ('Geopolitics','Elections') AND p.entry_avg_price IS NOT NULL
              AND t.trade_result IN ('won','lost') AND (m.trade_gap_flag=0 OR m.trade_gap_flag IS NULL)
              AND p.trader_address IN ({placeholders}) AND p.entry_timestamp > ?
        """, list(oos_cohort) + [T_SPLIT]).fetchall()
        oos_df = pd.DataFrame(rows, columns=['trader', 'market_id', 'outcome', 'price', 'entry_ts', 'trade_result'])
        oos_df['won'] = (oos_df['trade_result'] == 'won').astype(int)

        market_voters = oos_df.groupby('market_id')['trader'].nunique()
        consensus_markets = set(market_voters[market_voters >= 2].index)
        single_markets = set(market_voters[market_voters == 1].index)

        consensus_df = oos_df[oos_df['market_id'].isin(consensus_markets)]
        single_df = oos_df[oos_df['market_id'].isin(single_markets)]

        pairs_c = weighted_pair_table(consensus_df, WEIGHT_FNS['cap5']) if len(consensus_df) else None
        pairs_s = weighted_pair_table(single_df, WEIGHT_FNS['cap5']) if len(single_df) else None
        r_c = weighted_two_way_gap_bootstrap(pairs_c, reps=GATE_REPS_LOCAL, seed=SEED) if pairs_c is not None and len(pairs_c) else dict(n_pairs=0)
        r_s = weighted_two_way_gap_bootstrap(pairs_s, reps=GATE_REPS_LOCAL, seed=SEED) if pairs_s is not None and len(pairs_s) else dict(n_pairs=0)
        print(f"[consensus markets (>=2 voters)] n_positions={len(consensus_df)} gap={r_c.get('point_gap')} "
              f"CI=[{r_c.get('ci_lo')},{r_c.get('ci_hi')}]")
        print(f"[single-voter markets] n_positions={len(single_df)} gap={r_s.get('point_gap')} "
              f"CI=[{r_s.get('ci_lo')},{r_s.get('ci_hi')}]")
        findings['objective3'] = dict(consensus=r_c, single=r_s)
        if args.persist:
            c4 = db_connect(args.db)
            c4.execute("DROP TABLE IF EXISTS metric_v2f_consensus_result")
            c4.execute("""CREATE TABLE metric_v2f_consensus_result (kind TEXT PRIMARY KEY, n_positions INTEGER,
                point_gap REAL, ci_lo REAL, ci_hi REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT)""")
            c4.execute("INSERT INTO metric_v2f_consensus_result VALUES (?,?,?,?,?,?,?,?)",
                       ('consensus', len(consensus_df), r_c.get('point_gap'), r_c.get('ci_lo'), r_c.get('ci_hi'),
                        SPEC_VERSION, generated_at, args.generator_commit))
            c4.execute("INSERT INTO metric_v2f_consensus_result VALUES (?,?,?,?,?,?,?,?)",
                       ('single', len(single_df), r_s.get('point_gap'), r_s.get('ci_lo'), r_s.get('ci_hi'),
                        SPEC_VERSION, generated_at, args.generator_commit))
            c4.commit()
            c4.close()
            print("[persist] metric_v2f_consensus_result written")
    else:
        print(f"\n=== OBJECTIVE 3: SKIPPED -- Objective 2 was not positive-and-interpretable "
              f"(verdict: {thesis_verdict}). Per the pre-registration, consensus is not tested. ===")

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()
    if args.persist:
        c5 = db_connect(args.db)
        c5.execute("DROP TABLE IF EXISTS metric_v2f_findings")
        c5.execute("CREATE TABLE metric_v2f_findings (finding TEXT PRIMARY KEY, json_value TEXT, "
                   "spec_version TEXT, generated_at TEXT, generator_commit TEXT)")
        for k, v in findings.items():
            c5.execute("INSERT INTO metric_v2f_findings VALUES (?,?,?,?,?)",
                       (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, args.generator_commit))
        c5.commit()
        c5.close()
        print("[persist] metric_v2f_findings written")


if __name__ == '__main__':
    main()
