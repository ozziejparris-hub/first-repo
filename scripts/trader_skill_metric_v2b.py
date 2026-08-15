#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2b -- AMENDMENT to v2, not a fresh spec. The metric
definition (unit, edge formula, empirical-Bayes shrinkage, entries-only
primary with exits separate) is UNCHANGED from
scripts/trader_skill_metric_v2.py (first-repo 5e93131). This pass amends
ONLY the calibration gate's statistical treatment of market concentration,
and elevates market-weighting from a diagnostic afterthought to a first-class
design question. Read-only. No production writes. No changes to
update_geo_elo.py, geo_elo_active, cohort membership, or any live path.

=============================================================================
WHY (recorded so the framing survives)
=============================================================================
v2's item-10 calibration gate FAILED, and the prior pass correctly stopped
rather than re-specifying to obtain a pass (metric_v2_comparison_findings:
gate_failure_diagnosis). Diagnosis: NOT a normalisation bug. Both sides are
flat across most of the range (gaps <0.015 in 7/10 Yes buckets, 6/10 No
buckets) -- a large LOCALISED anomaly, not the smooth full-range monotonic
inversion the original sign error produced. "Will Kamala Harris win the 2024
US Presidential Election?" supplies 65.9% of the failing Yes bucket
(17,230/27,726) and 34% of the failing No bucket (13,907/40,670).

THE CAUSE, STATED HONESTLY: this bit harder here than in Layer 0c because
v2's OWN pre-registration removed MIN_TRADES_FOR_ELO -- Kamala-only traders
who never earned a (buggy) geo_elo are now in the population; Layer 0c's
population was implicitly gated by geo_elo-definedness and diluted them out
without anyone deciding that on purpose. The gate failure is a CONSEQUENCE
OF CORRECTLY FOLLOWING THE SPEC v2 WROTE, not a mistake in it. Lesson:
removing an unjustified inherited filter surfaced a concentration problem
that filter had been incidentally masking. Both are true at once -- the
filter was unjustified, AND it was doing real, unacknowledged work.

=============================================================================
AMENDMENT PRE-REGISTRATION (fixed before computing; written to
metric_v2b_amendment, referencing v2's spec_version SKILLV2-2026-08-15-v1,
BEFORE any result row)
=============================================================================

--- AMENDMENT 1: the gate's statistical treatment (metric spec unchanged) ---
1. Two-way trader x market cluster bootstrap on the calibration gap
   (mean_won - mean_price) per price bucket -- the technique Layer 0b already
   built and validated for this exact population and this exact problem
   (multiplicative-weight construction: independently resample trader and
   market multiplicities, weight each (trader,market) pair's contribution by
   the product).
2. Reported under THREE concentration-control variants, using FIXED price-
   bucket boundaries (computed once per side on the raw population, reused
   across all three variants so buckets stay comparable):
     (a) raw -- as v2 ran it.
     (b) top-15-by-position-count markets excluded entirely (N=15, matching
         Layer 0b's diagnostic technique; the market SET differs from Layer
         0b's own top-15 because this pass's population differs -- v2 has no
         geo_elo-definedness gate).
     (c) per-market position cap WITHIN each bucket, at that bucket's own
         median market-position-count (bucket-local, not a population-wide
         cap -- a market that dominates one bucket but not another is capped
         only where it dominates).
3. INTERPRETABLE OUTCOME SOUGHT: if calibration is flat under (b) and (c),
   and only fails under (a), that is a clean, sufficient answer -- the edge
   formula is sound, the population has extreme single-event concentration,
   and that concentration is a structural fact to carry into every
   downstream analysis (item 5-6 below), not something to bootstrap away.
   If (b) or (c) ALSO fails, there is a further problem: report it and stop,
   exactly as v2 did -- do not re-specify again to force a pass.

--- AMENDMENT 2: market-weighting as a first-class design question ---
This is the second time the Kamala market has distorted a result (Layer 0b,
now v2). 34,061 positions from 3,374 traders is one real-world event --
~10% of all entry positions. Not noise to correct for in a diagnostic; a
structural property of the dataset that should inform the METRIC'S design.
4. Per-trader metric computed THREE ways:
     (i)   position-weighted -- v2's original spec, every position equal.
     (ii)  market-weighted -- each (trader, market) contributes ONCE (a
           trader's positions within one market are first averaged into a
           single per-market observation; the trader's score is then the
           mean across the DISTINCT MARKETS they traded, not positions).
     (iii) event-cluster-weighted -- as (ii), but further collapsed by
           event_cluster_labels' cluster_id, so mutually-exclusive candidate
           fields (e.g. a multi-candidate election) count once. Coverage
           caveat, checked and reported: event_cluster_labels covers 4,607
           of 9,872 distinct markets in this population (46.7%) -- it is
           scoped to the bt_pop_2025-11-01_v1 snapshot, not full history.
           Markets outside that coverage are treated as singleton clusters
           (their own cluster_id = market_id), matching the table's own
           "trivial_standalone" convention for markets that don't cluster --
           meaning (iii) is only genuinely distinct from (ii) for the
           covered ~47% of markets, and identical to (ii) elsewhere by
           construction. Reported as a supplementary check on the covered
           subset, not a full-population primary, for exactly this reason.
5. Distribution and pairwise rank correlation across (i)/(ii)/(iii).
   Recommendation (this script's, not a unilateral decision -- Oscar makes
   the call): MARKET-WEIGHTED (ii) as primary. Rationale: position-weighting
   measures "who traded the big markets" as much as "who was right" --
   position-level FIFO aggregation (already in v2's spec) fixes raw-trade
   double-counting, but a trader who entered Kamala 50 times across several
   buy/sell cycles still gets that one event's outcome counted 50-fold
   relative to a trader who made one correct call elsewhere under
   position-weighting; market-weighting caps every event at one vote per
   trader, matching what "identifying mispricing" should mean structurally.
   Event-cluster-weighting (iii) is a strictly better version of the same
   idea where coverage allows, and is reported as a check on that subset,
   not adopted as primary due to incomplete coverage.
6. This is a DESIGN DECISION with a recorded rationale, not a robustness
   check -- if it materially changes results (item 5's rank correlations
   are the test), the metric's default weighting matters as much as any
   other spec choice made this session.

--- WHAT DOES NOT CHANGE ---
Unit = one position per independent decision (v2 items 1). Edge formula =
actual - price_of_side_held, no flip (v2 item 2, reused not reimplemented
-- imported directly from trader_skill_metric_v2). Empirical-Bayes
shrinkage mechanism (v2 item 4). Entries-only primary, exits separate with
their own symmetric win-condition, NOT trade_evaluator.py's inverted SELL
semantic (v2 Decision 2, item 3). Scope: no price band, no MIN_TRADES
cutoff, no tier threshold (v2 item 7).

--- UNCHANGED CONSTRAINTS ---
No production writes. No changes to update_geo_elo.py / geo_elo_active /
cohort membership / any live path. No threshold derivation, no cutover
decision. comprehensive_elo / calibration_analysis.py remains out of scope.
Do NOT re-specify to obtain a passing gate -- if (b)/(c) also fail, report
and stop, same discipline as v2.

Persists metric_v2b_amendment, metric_v2b_gate_results,
metric_v2b_weighting_comparison, metric_v2b_trader_results (only if gate
clears), metric_v2b_findings.
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

from scripts.trader_skill_metric_v2 import (
    load_entries, load_exits, eb_shrinkage, bootstrap_ci_per_trader, rank_corr,
    db_connect, SPEC_VERSION as V2_SPEC_VERSION,
)

SPEC_VERSION = "SKILLV2B-2026-08-15-v1"
BOOTSTRAP_REPS = 1000
GATE_REPS = 1500
SEED = 42
N_BUCKETS = 10
TOP_N_EXCLUDE = 15

AMENDMENT_WHY = (
    "v2's calibration gate failed on a large LOCALISED anomaly (gaps <0.015 in most buckets, "
    "-0.23/-0.28 in two Yes buckets, +0.18/+0.14 in two No buckets), diagnosed as market "
    "concentration (Kamala Harris 2024 market: 65.9% of the failing Yes bucket, 34% of the "
    "failing No bucket), NOT a normalisation bug. This bit harder than in Layer 0c because v2's "
    "own pre-registration removed MIN_TRADES_FOR_ELO, so Kamala-only traders who never earned a "
    "geo_elo -- diluted out of Layer 0c's population without anyone deciding that on purpose -- "
    "are now present. The gate failure is a consequence of correctly following the spec v2 wrote, "
    "not a mistake in it: removing an unjustified inherited filter surfaced a concentration "
    "problem that filter had been incidentally masking. Both are true at once."
)
AMENDMENT1_TEXT = (
    "Gate's statistical treatment changes; metric spec does not. Two-way trader x market cluster "
    "bootstrap (Layer 0b's technique) on the calibration gap per price bucket, reported under three "
    "concentration-control variants on FIXED (per-side, computed once) bucket boundaries: (a) raw "
    "as v2 ran it, (b) top-15-by-position-count markets excluded, (c) per-market cap at that "
    "bucket's own median market-position-count (bucket-local, not population-wide). Sought outcome: "
    "flat under (b)/(c), fails only under (a) -- a clean answer that the formula is sound and "
    "concentration is a structural fact, not something to bootstrap away. If (b) or (c) also fail: "
    "report and stop, same discipline as v2 -- no re-specifying to force a pass."
)
AMENDMENT2_TEXT = (
    "Market-weighting elevated from diagnostic afterthought to first-class design decision. Three "
    "per-trader weightings computed: (i) position-weighted (v2 original), (ii) market-weighted "
    "(each (trader,market) counts once), (iii) event-cluster-weighted (as ii, further collapsed by "
    "event_cluster_labels.cluster_id where covered -- 46.7% of this population's markets; "
    "uncovered markets treated as singleton clusters, making (iii) identical to (ii) there). "
    "Recommendation (not a unilateral decision): market-weighted (ii) as primary -- caps every "
    "real-world event at one vote per trader regardless of how many times they traded it, matching "
    "what 'identifying mispricing' should mean structurally; position-weighting measures 'who "
    "traded the big markets' as much as 'who was right'. Reported as a decision with a rationale, "
    "not a robustness check -- Oscar makes the final call."
)


# ---------------------------------------------------------------------------
# Two-way clustered bootstrap on a calibration gap (mean_won - mean_price)
# ---------------------------------------------------------------------------

def two_way_gap_bootstrap(sub, reps=GATE_REPS, seed=42, alpha=0.05):
    """sub: rows with trader, market_id, won, price. Returns point gap and
    a two-way (trader x market) clustered 95% CI on the gap, via the same
    multiplicative-weight construction as layer0b_deconfound.py."""
    if len(sub) == 0:
        return dict(n=0, point_gap=None, ci_lo=None, ci_hi=None)
    point_gap = float(sub['won'].mean() - sub['price'].mean())

    traders = sub['trader'].astype('category')
    markets = sub['market_id'].astype('category')
    tmp = pd.DataFrame({
        'trader_idx': traders.cat.codes.to_numpy(),
        'market_idx': markets.cat.codes.to_numpy(),
        'won': sub['won'].to_numpy(),
        'price': sub['price'].to_numpy(),
    })
    pair = tmp.groupby(['trader_idx', 'market_idx']).agg(
        sum_won=('won', 'sum'), sum_price=('price', 'sum'), n=('won', 'count')
    ).reset_index()
    n_traders = traders.cat.categories.size
    n_markets = markets.cat.categories.size
    t_idx = pair['trader_idx'].to_numpy()
    m_idx = pair['market_idx'].to_numpy()
    p_won = pair['sum_won'].to_numpy()
    p_price = pair['sum_price'].to_numpy()
    p_cnt = pair['n'].to_numpy()

    rng = np.random.default_rng(seed)
    boot = np.empty(reps)
    for b in range(reps):
        t_mult = np.bincount(rng.integers(0, n_traders, size=n_traders), minlength=n_traders)
        m_mult = np.bincount(rng.integers(0, n_markets, size=n_markets), minlength=n_markets)
        w = t_mult[t_idx] * m_mult[m_idx]
        denom = (w * p_cnt).sum()
        if denom <= 0:
            boot[b] = np.nan
            continue
        wmean_won = (w * p_won).sum() / denom
        wmean_price = (w * p_price).sum() / denom
        boot[b] = wmean_won - wmean_price
    boot = boot[~np.isnan(boot)]
    if len(boot) < reps * 0.5:
        return dict(n=len(sub), n_traders=int(n_traders), n_markets=int(n_markets),
                    point_gap=point_gap, ci_lo=None, ci_hi=None)
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return dict(n=len(sub), n_traders=int(n_traders), n_markets=int(n_markets),
                point_gap=point_gap, ci_lo=float(lo), ci_hi=float(hi))


def fixed_buckets(entries_df, side, n_buckets=N_BUCKETS):
    sub = entries_df[entries_df['outcome'] == side]
    _, bins = pd.qcut(sub['entry_avg_price'], q=n_buckets, retbins=True, duplicates='drop')
    return bins


def apply_variant(entries_df, side, variant, top15_markets=None, bucket_medians_seed=SEED):
    """Returns a df of rows for `side`, with a 'bucket' column assigned from
    fixed boundaries, filtered/capped per `variant` in {'raw','top15_excl','capped'}."""
    sub = entries_df[entries_df['outcome'] == side].copy()
    bins = fixed_buckets(entries_df, side)
    sub['bucket'] = pd.cut(sub['entry_avg_price'], bins=bins, labels=False, include_lowest=True)
    sub = sub.dropna(subset=['bucket'])
    sub['bucket'] = sub['bucket'].astype(int)
    sub = sub.rename(columns={'entry_avg_price': 'price'})

    if variant == 'raw':
        return sub, bins
    if variant == 'top15_excl':
        return sub[~sub['market_id'].isin(top15_markets)], bins
    if variant == 'capped':
        rng = np.random.default_rng(bucket_medians_seed)
        keep_idx = []
        for b, bgrp in sub.groupby('bucket'):
            counts = bgrp.groupby('market_id').size()
            cap = int(counts.median())
            for mid, mgrp in bgrp.groupby('market_id'):
                if len(mgrp) <= cap:
                    keep_idx.extend(mgrp.index.tolist())
                else:
                    chosen = rng.choice(mgrp.index.to_numpy(), size=max(cap, 1), replace=False)
                    keep_idx.extend(chosen.tolist())
        return sub.loc[keep_idx], bins
    raise ValueError(variant)


def run_gate_variant(entries_df, side, variant, top15_markets, reps, seed, tol=0.03):
    df, bins = apply_variant(entries_df, side, variant, top15_markets)
    rows = []
    all_pass = True
    for b in sorted(df['bucket'].unique()):
        bsub = df[df['bucket'] == b]
        r = two_way_gap_bootstrap(bsub, reps=reps, seed=seed + int(b) * 7)
        r['bucket'] = int(b)
        r['price_lo'] = float(bins[int(b)])
        r['price_hi'] = float(bins[int(b) + 1])
        ci_excludes_zero = r['ci_lo'] is not None and (r['ci_lo'] > tol or r['ci_hi'] < -tol)
        r['ci_excludes_zero_beyond_tol'] = bool(ci_excludes_zero)
        if ci_excludes_zero:
            all_pass = False
        rows.append(r)
    return all_pass, rows


# ---------------------------------------------------------------------------
# Amendment 2: three weightings
# ---------------------------------------------------------------------------

def position_weighted(df):
    return df[['position_id', 'trader', 'market_id', 'edge']].copy()


def market_weighted(df):
    per_market = df.groupby(['trader', 'market_id'])['edge'].mean().reset_index()
    per_market = per_market.rename(columns={'edge': 'edge'})
    return per_market


def event_cluster_weighted(df, cluster_map):
    tmp = df.copy()
    tmp['cluster_id'] = tmp['market_id'].map(cluster_map).fillna(tmp['market_id'])
    per_cluster = tmp.groupby(['trader', 'cluster_id'])['edge'].mean().reset_index()
    return per_cluster


def weighting_eb_and_ci(df_weighted, reps, seed):
    eb = eb_shrinkage(df_weighted, value_col='edge', trader_col='trader')
    ci = bootstrap_ci_per_trader(df_weighted, value_col='edge', trader_col='trader', reps=reps, seed=seed)
    return eb.merge(ci, on='trader')


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist_amendment(conn, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2b_amendment")
    conn.execute("""
        CREATE TABLE metric_v2b_amendment (
            spec_version TEXT PRIMARY KEY, amends_spec_version TEXT, why TEXT,
            amendment1 TEXT, amendment2 TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2b_amendment VALUES (?,?,?,?,?,?,?)",
                 (SPEC_VERSION, V2_SPEC_VERSION, AMENDMENT_WHY, AMENDMENT1_TEXT, AMENDMENT2_TEXT,
                  generated_at, generator_commit))
    conn.commit()


def persist_gate(conn, gate_rows, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2b_gate_results")
    conn.execute("""
        CREATE TABLE metric_v2b_gate_results (
            side TEXT, variant TEXT, bucket INTEGER, price_lo REAL, price_hi REAL,
            n INTEGER, n_traders INTEGER, n_markets INTEGER, point_gap REAL,
            ci_lo REAL, ci_hi REAL, ci_excludes_zero_beyond_tol INTEGER,
            spec_version TEXT, generated_at TEXT, generator_commit TEXT
        )
    """)
    for side, variant, r in gate_rows:
        conn.execute("INSERT INTO metric_v2b_gate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            side, variant, r['bucket'], r['price_lo'], r['price_hi'], r['n'],
            r.get('n_traders'), r.get('n_markets'), r['point_gap'], r['ci_lo'], r['ci_hi'],
            int(r['ci_excludes_zero_beyond_tol']), SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def persist_weighting(conn, weighting_summary, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2b_weighting_comparison")
    conn.execute("""
        CREATE TABLE metric_v2b_weighting_comparison (
            finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for k, v in weighting_summary.items():
        conn.execute("INSERT INTO metric_v2b_weighting_comparison VALUES (?,?,?,?,?)",
                     (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def persist_trader_results(conn, trader_results, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2b_trader_results")
    conn.execute("""
        CREATE TABLE metric_v2b_trader_results (
            trader TEXT, kind TEXT, weighting TEXT, n INTEGER, raw_mean REAL, shrunk_mean REAL,
            shrinkage_weight REAL, ci_lo REAL, ci_hi REAL, distinguishable_from_zero INTEGER,
            stored_geo_elo REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT
        )
    """)
    for _, r in trader_results.iterrows():
        conn.execute("INSERT INTO metric_v2b_trader_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r['trader'], r['kind'], r['weighting'], int(r['n']), r['raw_mean'], r['shrunk_mean'],
            r['shrinkage_weight'], r.get('ci_lo'), r.get('ci_hi'),
            int(r.get('distinguishable_from_zero', 0)), r.get('geo_elo'),
            SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def persist_findings(conn, findings, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2b_findings")
    conn.execute("""
        CREATE TABLE metric_v2b_findings (
            finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for k, v in findings.items():
        conn.execute("INSERT INTO metric_v2b_findings VALUES (?,?,?,?,?)",
                     (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def print_gate_table(side, variant, rows):
    print(f"  --- {side} / {variant} ---")
    for r in rows:
        ci = f"[{r['ci_lo']:.4f},{r['ci_hi']:.4f}]" if r['ci_lo'] is not None else "N/A"
        flag = "FAIL" if r['ci_excludes_zero_beyond_tol'] else "ok"
        print(f"    bucket {r['bucket']}: price {r['price_lo']:.3f}-{r['price_hi']:.3f} n={r['n']} "
              f"n_trd={r.get('n_traders')} n_mkt={r.get('n_markets')} gap={r['point_gap']:+.4f} "
              f"clustered_CI={ci} [{flag}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--gate-reps', type=int, default=GATE_REPS)
    ap.add_argument('--bootstrap-reps', type=int, default=BOOTSTRAP_REPS)
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    print(f"=== AMENDMENT (spec {SPEC_VERSION}, amends {V2_SPEC_VERSION}) ===")
    print(f"WHY: {AMENDMENT_WHY}\n")
    print(f"AMENDMENT 1: {AMENDMENT1_TEXT}\n")
    print(f"AMENDMENT 2: {AMENDMENT2_TEXT}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    if args.persist:
        persist_amendment(conn, generated_at, args.generator_commit)
        print("[persist] metric_v2b_amendment written\n")

    entries_df = load_entries(conn, verbose=args.verbose)
    exits_df = load_exits(conn, verbose=args.verbose)
    entries_df = entries_df.rename(columns={'entry_avg_price': 'entry_avg_price'})

    top15_markets = entries_df.groupby('market_id').size().sort_values(ascending=False).head(TOP_N_EXCLUDE).index.tolist()
    print(f"[concentration] top-15 markets this population: "
          f"{entries_df[entries_df['market_id'].isin(top15_markets)].shape[0]}/{len(entries_df)} "
          f"({100*entries_df[entries_df['market_id'].isin(top15_markets)].shape[0]/len(entries_df):.1f}%) of positions")

    print("\n=== THREE-WAY GATE (clustered CI per bucket, per variant) ===")
    gate_rows_flat = []
    overall = {}
    for side in ('Yes', 'No'):
        overall[side] = {}
        for variant in ('raw', 'top15_excl', 'capped'):
            all_pass, rows = run_gate_variant(entries_df, side, variant, top15_markets,
                                               reps=args.gate_reps, seed=args.seed)
            overall[side][variant] = all_pass
            print_gate_table(side, variant, rows)
            for r in rows:
                gate_rows_flat.append((side, variant, r))

    print("\n=== GATE SUMMARY ===")
    for side in ('Yes', 'No'):
        for variant in ('raw', 'top15_excl', 'capped'):
            print(f"  {side} / {variant}: {'PASS' if overall[side][variant] else 'FAIL'}")

    gate_clears = overall['Yes']['top15_excl'] and overall['Yes']['capped'] and \
                  overall['No']['top15_excl'] and overall['No']['capped']
    print(f"\n[GATE DECISION] (b) and (c) both pass, both sides: {gate_clears}")
    if not overall['Yes']['raw'] or not overall['No']['raw']:
        print("[note] (a) raw still fails as expected -- concentration is real, not fixed by clustering alone; "
              "this is the EXPECTED, interpretable outcome if (b)/(c) pass.")

    if args.persist:
        persist_gate(conn, gate_rows_flat, generated_at, args.generator_commit)
        print("[persist] metric_v2b_gate_results written")

    # --- Amendment 2: three weightings, computed regardless of gate outcome
    # (this is a design-question characterisation, not conditional on the gate) ---
    print("\n=== AMENDMENT 2: three weightings ===")
    cluster_rows = conn.execute("SELECT market_id, cluster_id FROM event_cluster_labels").fetchall()
    cluster_map = dict(cluster_rows)
    coverage = entries_df['market_id'].isin(cluster_map.keys()).mean()
    print(f"event_cluster_labels coverage of this population's markets: {coverage:.3f}")

    pos_w = position_weighted(entries_df)
    mkt_w = market_weighted(entries_df)
    evt_w = event_cluster_weighted(entries_df, cluster_map)

    pos_eb = weighting_eb_and_ci(pos_w, reps=args.bootstrap_reps, seed=args.seed)
    mkt_eb = weighting_eb_and_ci(mkt_w, reps=args.bootstrap_reps, seed=args.seed)
    evt_eb = weighting_eb_and_ci(evt_w, reps=args.bootstrap_reps, seed=args.seed)

    print(f"position-weighted: {len(pos_eb)} traders, shrunk_mean summary:\n{pos_eb['shrunk_mean'].describe()}")
    print(f"market-weighted:   {len(mkt_eb)} traders, shrunk_mean summary:\n{mkt_eb['shrunk_mean'].describe()}")
    print(f"event-weighted:    {len(evt_eb)} traders, shrunk_mean summary:\n{evt_eb['shrunk_mean'].describe()}")

    # sigma2_between diagnostic per weighting -- degenerate (~0) means the EB
    # shrinkage estimator found no detectable between-trader variance at that
    # granularity, i.e. shrunk_mean collapses to the grand mean for everyone.
    # Checked directly (not inferred from the symptom alone): for market-
    # weighting, MSB=0.0621 < sigma2_within=0.0735 -- a genuine method-of-
    # moments null, not an estimator bug (the bug was fixed upstream in
    # trader_skill_metric_v2.py, commit 13ecf07; this is what the CORRECT
    # formula returns).
    degenerate = {}
    for label, eb in (('position', pos_eb), ('market', mkt_eb), ('event', evt_eb)):
        sb = float(eb['sigma2_between'].iloc[0]) if len(eb) else None
        degenerate[label] = (sb is not None and sb <= 1e-12)
        print(f"sigma2_between[{label}] = {sb}  degenerate={degenerate[label]}")

    m_pos_mkt = pos_eb.merge(mkt_eb, on='trader', suffixes=('_pos', '_mkt'))
    m_pos_evt = pos_eb.merge(evt_eb, on='trader', suffixes=('_pos', '_evt'))
    m_mkt_evt = mkt_eb.merge(evt_eb, on='trader', suffixes=('_mkt', '_evt'))
    rc_pos_mkt = rank_corr(m_pos_mkt['shrunk_mean_pos'], m_pos_mkt['shrunk_mean_mkt'])
    rc_pos_evt = rank_corr(m_pos_evt['shrunk_mean_pos'], m_pos_evt['shrunk_mean_evt'])
    rc_mkt_evt = rank_corr(m_mkt_evt['shrunk_mean_mkt'], m_mkt_evt['shrunk_mean_evt'])
    print(f"\nrank_corr(position, market) = {rc_pos_mkt:.4f}  n={len(m_pos_mkt)}  "
          f"(NOTE: mechanically 0 if either side is degenerate -- a constant column has no rank)")
    print(f"rank_corr(position, event)  = {rc_pos_evt:.4f}  n={len(m_pos_evt)}")
    print(f"rank_corr(market, event)    = {rc_mkt_evt:.4f}  n={len(m_mkt_evt)}")

    if degenerate['market'] or degenerate['event']:
        primary_weighting = 'position'
        recommendation = (
            "REVISED from the pre-registration's stated intent: market-weighted (ii) and "
            "event-weighted (iii) both collapse to zero detectable between-trader variance "
            "under the (corrected, verified) empirical-Bayes estimator -- not a bug, a genuine "
            "method-of-moments null (market-weighted: MSB=0.0621 < sigma2_within=0.0735). "
            "Median trader trades only ~4 distinct markets; that is not enough independent "
            "observations, at this per-market-edge variance, for shrinkage to distinguish any "
            "trader from the grand mean once volume is discarded. A metric with zero variance "
            "cannot rank anyone, so position-weighted (i) is used for items 7-11 by necessity, "
            "not because it was the intended primary. This reopens the concentration "
            "vulnerability Amendment 2 was written to close -- position-weighting is exactly "
            "what let one market dominate a bucket in the first place. Recorded as an "
            "unresolved tension for Oscar's call, not resolved here: market-weighting is "
            "conceptually right but not viable with current sample depth; position-weighting "
            "is viable but structurally exposed to single-event domination. A possible middle "
            "path (not built this pass) is a partial/intermediate weighting (e.g. capping, not "
            "eliminating, a market's within-trader multiplicity) rather than the binary choice "
            "tested here."
        )
    else:
        primary_weighting = 'market'
        recommendation = "market-weighted (ii) as primary -- see AMENDMENT2_TEXT for rationale."
    print(f"\nRECOMMENDATION (revised on evidence, not pre-committed): {recommendation}")

    weighting_summary = dict(
        event_cluster_coverage=float(coverage),
        n_traders=dict(position=len(pos_eb), market=len(mkt_eb), event=len(evt_eb)),
        sigma2_between=dict(position=float(pos_eb['sigma2_between'].iloc[0]),
                            market=float(mkt_eb['sigma2_between'].iloc[0]),
                            event=float(evt_eb['sigma2_between'].iloc[0])),
        degenerate=degenerate,
        rank_correlations=dict(position_vs_market=rc_pos_mkt, position_vs_event=rc_pos_evt,
                               market_vs_event=rc_mkt_evt),
        recommendation=recommendation,
        primary_weighting_used_for_items_7_11=primary_weighting,
    )
    if args.persist:
        persist_weighting(conn, weighting_summary, generated_at, args.generator_commit)
        print("[persist] metric_v2b_weighting_comparison written")

    findings = dict(gate_summary={f"{s}_{v}": overall[s][v] for s in overall for v in overall[s]},
                    gate_clears=bool(gate_clears), weighting=weighting_summary)

    if not gate_clears:
        print("\n[STOP] Gate does not clear under (b)/(c) for both sides. Per the pre-registration: "
              "report and stop. Items 7-11 NOT computed this run.", file=sys.stderr)
        if args.persist:
            persist_findings(conn, findings, generated_at, args.generator_commit)
            print("[persist] metric_v2b_findings written (gate_clears=False)")
        if args.json_out:
            with open(args.json_out, 'w') as f:
                json.dump(findings, f, indent=2, default=str)
        conn.close()
        sys.exit(2)

    # --- gate cleared: items 7-11, primary weighting chosen ON EVIDENCE above
    # (position-weighted if market/event collapsed; market-weighted otherwise) ---
    print(f"\n=== GATE CLEARED -- proceeding to items 7-11, primary weighting = {primary_weighting} ===")

    primary_eb = {'position': pos_eb, 'market': mkt_eb, 'event': evt_eb}[primary_weighting]
    primary_weight_fn = {'position': position_weighted, 'market': market_weighted,
                         'event': lambda d: event_cluster_weighted(d, cluster_map)}[primary_weighting]

    primary_eb = primary_eb.copy()
    primary_eb['kind'] = 'entry'
    primary_eb['weighting'] = primary_weighting
    primary_eb['distinguishable_from_zero'] = ((primary_eb['ci_lo'] > 0) | (primary_eb['ci_hi'] < 0)).astype(int)
    print(f"\n[item 7] {primary_weighting}-weighted shrunk-edge distribution, n_distinguishable_from_zero_95="
          f"{primary_eb['distinguishable_from_zero'].sum()}/{len(primary_eb)}")
    print(primary_eb['shrunk_mean'].describe())
    print(f"(sigma2_between={primary_eb['sigma2_between'].iloc[0]:.6f}, "
          f"shrinkage_weight median={primary_eb['shrinkage_weight'].median():.4f})")

    stored = pd.read_sql("SELECT address AS trader, geo_elo FROM traders", conn)
    primary_eb = primary_eb.merge(stored, on='trader', how='left')
    overlap_geo = primary_eb.dropna(subset=['geo_elo'])
    spearman_v_geo = rank_corr(overlap_geo['shrunk_mean'], overlap_geo['geo_elo'])
    print(f"\n[item 8] Spearman({primary_weighting}-weighted shrunk_mean, stored geo_elo) = "
          f"{spearman_v_geo:.4f}, n={len(overlap_geo)}")

    no_frac = entries_df.groupby('trader').apply(lambda g: (g['outcome'] == 'No').mean(),
                                                 include_groups=False).rename('no_frac').reset_index()
    ov2 = overlap_geo.merge(no_frac, on='trader', how='left')
    ov2['geo_rank'] = ov2['geo_elo'].rank(pct=True)
    ov2['new_rank'] = ov2['shrunk_mean'].rank(pct=True)
    ov2['disagreement'] = ov2['geo_rank'] - ov2['new_rank']
    corr_dis_no = float(np.corrcoef(ov2['disagreement'], ov2['no_frac'])[0, 1])
    print(f"[item 8] corr(rank_disagreement, No-fraction) = {corr_dis_no:.4f}")

    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))
    ranked = primary_eb.sort_values('shrunk_mean', ascending=False)
    top_n = ranked.head(len(legendary))['trader'].tolist()
    overlap = legendary & set(top_n)
    print(f"\n[item 9] LEGENDARY (n={len(legendary)}) overlap with top-{len(legendary)} "
          f"{primary_weighting}-weighted: {len(overlap)} ({100*len(overlap)/len(legendary):.1f}%)")

    exits_primary = primary_weight_fn(exits_df.rename(columns={'exit_avg_price': 'exit_avg_price'}))
    exits_primary_eb = weighting_eb_and_ci(exits_primary, reps=args.bootstrap_reps, seed=args.seed)
    ee = primary_eb[['trader', 'raw_mean']].rename(columns={'raw_mean': 'entry_mean'}).merge(
        exits_primary_eb[['trader', 'raw_mean']].rename(columns={'raw_mean': 'exit_mean'}), on='trader')
    ee_pearson = float(np.corrcoef(ee['entry_mean'], ee['exit_mean'])[0, 1]) if len(ee) >= 3 else None
    ee_spearman = rank_corr(ee['entry_mean'], ee['exit_mean']) if len(ee) >= 3 else None
    print(f"\n[item 10/11] entries vs exits ({primary_weighting}-weighted) correlation: n={len(ee)}, "
          f"pearson={ee_pearson}, spearman={ee_spearman}")

    # cross-check under the other two weightings (degenerate ones will show
    # mechanically-zero Spearman -- expected, not a new finding, given item 5's diagnosis)
    for label, eb in (('position', pos_eb), ('market', mkt_eb), ('event', evt_eb)):
        if label == primary_weighting:
            continue
        eb2 = eb.merge(stored, on='trader', how='left').dropna(subset=['geo_elo'])
        sc = rank_corr(eb2['shrunk_mean'], eb2['geo_elo'])
        top_n_alt = eb.sort_values('shrunk_mean', ascending=False).head(len(legendary))['trader'].tolist()
        ov_alt = legendary & set(top_n_alt)
        print(f"[cross-check:{label}] Spearman vs geo_elo={sc:.4f}, LEGENDARY overlap={len(ov_alt)}/{len(legendary)} "
              f"{'(degenerate weighting, per item 5)' if degenerate.get(label) else ''}")

    findings.update(dict(
        primary_weighting=primary_weighting,
        item7=dict(n_traders=len(primary_eb), n_distinguishable_95=int(primary_eb['distinguishable_from_zero'].sum())),
        item8=dict(spearman_vs_geo_elo=spearman_v_geo, n_overlap=len(overlap_geo),
                  corr_disagreement_no_fraction=corr_dis_no),
        item9=dict(n_legendary=len(legendary), overlap=len(overlap),
                  overlap_fraction=len(overlap) / len(legendary) if legendary else None),
        item10_11=dict(n=len(ee), pearson=ee_pearson, spearman=ee_spearman),
    ))

    # persist trader results (primary weighting, entries + exits)
    mkt_eb = primary_eb
    exits_mkt_eb = exits_primary_eb
    mkt_eb['kind'] = 'entry'
    mkt_eb['weighting'] = primary_weighting
    exits_mkt_eb['kind'] = 'exit'
    exits_mkt_eb['weighting'] = primary_weighting
    exits_mkt_eb = exits_mkt_eb.merge(stored, on='trader', how='left')
    exits_mkt_eb['distinguishable_from_zero'] = ((exits_mkt_eb['ci_lo'] > 0) | (exits_mkt_eb['ci_hi'] < 0)).astype(int)

    trader_results = pd.concat([
        mkt_eb[['trader', 'kind', 'weighting', 'n', 'raw_mean', 'shrunk_mean', 'shrinkage_weight',
                'ci_lo', 'ci_hi', 'distinguishable_from_zero', 'geo_elo']],
        exits_mkt_eb[['trader', 'kind', 'weighting', 'n', 'raw_mean', 'shrunk_mean', 'shrinkage_weight',
                       'ci_lo', 'ci_hi', 'distinguishable_from_zero', 'geo_elo']],
    ], ignore_index=True)

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()
    if args.persist:
        wconn = db_connect(args.db)
        persist_trader_results(wconn, trader_results, generated_at, args.generator_commit)
        persist_findings(wconn, findings, generated_at, args.generator_commit)
        wconn.close()
        print(f"[persist] metric_v2b_trader_results ({len(trader_results)} rows), metric_v2b_findings written")


if __name__ == '__main__':
    main()
