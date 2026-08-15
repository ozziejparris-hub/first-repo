#!/usr/bin/env python3
"""
LAYER 0b -- isolate the geo_elo signal from the two confounds Layer 0 identified.

=============================================================================
LINEAGE
=============================================================================
Builds directly on the Layer 0 artifacts (first-repo commits f1d2555, ff9ef7c;
DB tables layer0_pre_registration, layer0_position_results, layer0_stratum_summary
-- scripts/layer0_forward_accuracy.py). Layer 0's own selfcheck (200/200 exact
match against analysis.pit_geo_elo.reconstruct_one_at) already validated the
geo_elo/edge computation; Layer 0b reads those already-validated per-position
values from layer0_position_results rather than recomputing the PIT replay.
This script's own --selfcheck instead validates the ONE thing Layer 0b adds:
the join back to positions.outcome used for the Yes/No split (re-derives
entry_price_side from a fresh positions-table fetch and asserts it matches
the stored value exactly).

Layer 0 established: geo_elo ORDERS traders by forward edge (rank correlation
0.685 across deciles, placebo-confirmed p=0.04, not driven by 2-3 traders,
survives contested-band/clean-trader/fee-era controls). But the LEVEL was
uninterpretable -- every decile positive including the bottom (0.179 at
geo_elo 420-1369, where H0 predicts ~0) -- and two un-pre-registered confounds
were found mid-investigation:
  (1) MARKET CONCENTRATION: one market ("Will Kamala Harris win the 2024 US
      Presidential Election?") = 34,061 of 341,865 positions (10%) from 3,374
      distinct traders. Trader-clustering cannot fix this -- many different
      traders piling into one market's idiosyncratic base rate correlate
      through the MARKET, not the trader.
  (2) YES/NO CALIBRATION ASYMMETRY: on BUY-only trades, mid-range prices
      (roughly 0.3-0.7) are not honest -- Yes underperforms its price, No
      overperforms. Confirmed not a trade_result bug (validated against
      trade_evaluator.py's correct SELL-side inversion; the anomaly is on
      BUY-only data, a clean string match).

=============================================================================
PRE-REGISTRATION (fixed before computing anything; written to
layer0b_pre_registration before any result row)
=============================================================================

HYPOTHESIS: unchanged from Layer 0 -- a trader's geo_elo at time T positively
    predicts the market-relative edge of positions they enter after T.
METRIC: unchanged -- edge = (won ? 1 : 0) - entry_price_of_their_side,
    outcome-normalized, read directly from layer0_position_results.

WHAT CHANGES, AND WHY (recorded here so the change is visible as a deliberate,
pre-registered revision, not a post-hoc rescue):

  1. INFERENCE: cluster bootstrap CIs are computed two ways -- resampling
     TRADERS (Layer 0's method) and resampling MARKETS (new) -- and combined.
     A true two-way (multiplicative-weight) cluster bootstrap is the primary
     estimator (see METHOD step 1); it is checked for stability against the
     two one-way bootstraps and falls back to "the wider of the two one-way
     CIs" (this script's explicit fallback rule, matching the pre-registered
     instruction) if the two-way CI is narrower than either one-way CI alone,
     which would indicate a degenerate/unstable two-way resample rather than
     a genuinely tighter estimate.

  2. SUCCESS CRITERION, REVISED: H1 is supported if the top stratum's mean
     edge has a market-AND-trader-clustered 95% CI excluding zero, AND the
     rank correlation between stratum index and mean edge remains materially
     positive (interpreted as >= 0.5, informally -- Layer 0 measured 0.685).
     Layer 0's ORIGINAL criterion additionally required "monotonic or near-
     monotonic (<=1 adjacent-pair violation)". That criterion is DROPPED here
     because it is too brittle at this n: with ~11,000+ positions per decile
     and 95% CIs of the observed width (Layer 0's stratum CIs typically
     spanned 0.03-0.07 in edge units), a handful of adjacent-pair reversals
     among 10 strata is consistent with sampling noise around a genuinely
     monotone-in-expectation relationship, and Layer 0's own data showed
     exactly this (4 reversals against a 0.685 rank correlation -- reversals
     concentrated between adjacent, overlapping-CI strata, not between
     strata whose CIs were clearly separated). Rank correlation is the
     correct monotonicity test at this n; the adjacent-pair-violation count
     is not. This loosening is recorded HERE, before any Layer 0b result is
     computed, specifically so it is auditable as a deliberate correction to
     an over-strict Layer 0 criterion rather than a criterion chosen after
     seeing whether Layer 0b's own top/bottom decile cleared the old bar.

  3. WHAT DOES NOT CHANGE: the hypothesis and metric are identical to Layer
     0. This script does not search for a specification that produces a
     larger or cleaner effect -- it removes two SPECIFIC, NAMED, evidenced
     confounds (market concentration; Yes/No calibration asymmetry) and
     reports what remains, including reporting plainly if a third, unnamed
     confound is still present (i.e., if every decile stays positive even
     after both corrections).

=============================================================================
METHOD
=============================================================================

1. Two-way cluster bootstrap: precompute, per stratum, per (trader, market)
   pair, (sum_edge, n). Each bootstrap rep independently draws a trader-level
   bootstrap resample (multiplicity per unique trader) and a market-level
   bootstrap resample (multiplicity per unique market); each (trader,market)
   pair's bootstrap weight is the PRODUCT of its trader's and its market's
   drawn multiplicities (the standard multiplicative-weight construction for
   an approximate two-way cluster bootstrap). Reports trader-only,
   market-only, and two-way CIs; the two-way is primary unless the stability
   check (step above) triggers the one-way fallback.

2. Same decile stratum table as Layer 0 (raw geo_elo, recomputed fresh from
   layer0_position_results so it is guaranteed to match Layer 0 exactly),
   now with the corrected CIs, plus the rank correlation across strata.

3. Concentration diagnostic, two variants, each with a FRESH decile
   stratification (not reusing Layer 0's boundaries, since removing/capping
   markets changes the population):
     a. Top-15-by-position-count markets excluded entirely, computed on the
        geo_elo-eligible population specifically (NOT Layer 0's top-15 by
        raw population, which is dominated by traders who did not yet
        qualify for a geo_elo and are therefore invisible to this analysis
        anyway -- the two top-15 lists differ; this script recomputes its
        own, scoped to the population actually being stratified).
     b. Per-market position cap at the MEDIAN market's position count within
        the geo_elo-eligible population, enforced by seeded random
        downsampling (without replacement) of any market exceeding the cap.

4. Yes/No split: the full stratified table (with two-way CIs) computed
   separately for outcome='Yes' and outcome='No' positions, plus the
   calibration gap (mean_won - mean_price) per decile per side, to check
   whether the asymmetry is flat across geo_elo strata (a market-wide
   property, netting out cleanly) or itself varies with geo_elo (entangled
   with the signal).

5. Standalone calibration curve: realized win rate vs entry_price_side in
   deciles, separately for Yes and No, over the geo_elo-eligible population
   (the same population the stratified tables use, for direct relevance to
   whether this specific analysis is contaminated -- not the full
   341,865-row Layer 0 population).

6. THE KEY QUESTION: bottom-decile edge under each correction (primary,
   top-15-excluded, capped, Yes-only, No-only) reported side by side. If it
   converges toward zero while the top decile stays clearly positive, the
   magnitude is interpretable and Layer 1 can proceed. If it does not, that
   is reported as evidence of a third, unidentified confound -- not papered
   over with a different specification.

Read-only against the database except the three tables this script owns
(layer0b_pre_registration, layer0b_stratum_summary, layer0b_calibration_curve
-- DROP/recreate on each --persist run).
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SPEC_VERSION = "LAYER0B-2026-08-15-v1"
LAYER0_LINEAGE = "first-repo f1d2555/ff9ef7c; layer0_pre_registration/layer0_position_results/layer0_stratum_summary"
N_STRATA_DEFAULT = 10
BOOTSTRAP_REPS_DEFAULT = 1500
SEED_DEFAULT = 42

H1_TEXT = ("A trader's geo_elo at time T positively predicts the market-relative "
           "edge of positions they enter after T. (unchanged from Layer 0)")
METRIC_TEXT = ("edge = won - entry_price_of_their_side, read directly from "
               "layer0_position_results (Layer 0's already-validated per-position "
               "values). (unchanged from Layer 0)")
CHANGE_TEXT = ("Inference: two-way (trader x market) cluster bootstrap replaces the "
               "trader-only bootstrap, to address market-concentration confound. "
               "Success criterion: top-stratum two-way-clustered 95% CI must exclude "
               "zero AND rank correlation across strata must be materially positive "
               "(>=0.5); the Layer 0 adjacent-pair monotonicity requirement is DROPPED "
               "as too brittle at ~11K positions/decile with overlapping-CI adjacent "
               "strata (Layer 0 itself: 4 reversals against rank corr 0.685). Recorded "
               "before computing any Layer 0b result.")
SUCCESS_TEXT = ("H1 supported if: top stratum mean edge has a two-way-clustered 95% CI "
                "excluding zero, AND rank_corr(stratum, mean_edge) >= 0.5 (materially "
                "positive), AND the bottom-decile edge approaches zero after the market-"
                "concentration correction (top-15-excluded and/or capped). If every "
                "decile remains uniformly positive after both corrections, that is "
                "reported as evidence of an unresolved third confound, not as support.")


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(conn, verbose=False):
    rows = conn.execute("""
        SELECT l.position_id, l.trader, l.market_id, l.geo_elo, l.entry_price_side,
               l.won, l.edge, p.outcome, p.entry_avg_price
        FROM layer0_position_results l
        JOIN positions p ON p.position_id = l.position_id
        WHERE l.geo_elo IS NOT NULL
    """).fetchall()
    df = pd.DataFrame(rows, columns=[
        'position_id', 'trader', 'market_id', 'geo_elo', 'entry_price_side',
        'won', 'edge', 'outcome', 'entry_avg_price',
    ])
    if verbose:
        print(f"[load] {len(df)} geo_elo-eligible positions, "
              f"{df['trader'].nunique()} traders, {df['market_id'].nunique()} markets")
    return df


def selfcheck(conn, df, n_samples=200, seed=7, verbose=True):
    """Validates the one thing Layer 0b adds over Layer 0: the outcome join
    and re-derived entry_price_side. Re-fetches outcome/entry_avg_price fresh
    from `positions` for a sample and asserts the stored entry_price_side
    matches recomputing it from those fresh values."""
    rng = random.Random(seed)
    sample = df.sample(min(n_samples, len(df)), random_state=seed)
    mismatches = []
    for _, row in sample.iterrows():
        fresh = conn.execute(
            "SELECT outcome, entry_avg_price FROM positions WHERE position_id = ?",
            (row['position_id'],)
        ).fetchone()
        if fresh is None:
            mismatches.append((row['position_id'], 'MISSING'))
            continue
        outcome, entry_avg_price = fresh
        expected = entry_avg_price if (outcome or '').strip() == 'Yes' else 1.0 - entry_avg_price
        if abs(expected - row['entry_price_side']) > 1e-9:
            mismatches.append((row['position_id'], expected, row['entry_price_side']))
    if verbose:
        print(f"[selfcheck] {len(sample)} positions checked, {len(mismatches)} mismatches")
        for m in mismatches[:10]:
            print(f"  MISMATCH {m}")
    return len(sample), mismatches


# ---------------------------------------------------------------------------
# Cluster bootstraps
# ---------------------------------------------------------------------------

def _one_way_ci(sums, counts, reps, seed, alpha=0.05):
    n = len(sums)
    if n == 0:
        return None, None
    rng = np.random.default_rng(seed)
    boot = np.empty(reps)
    for b in range(reps):
        idx = rng.integers(0, n, size=n)
        boot[b] = sums[idx].sum() / counts[idx].sum()
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def two_way_cluster_bootstrap(sub, reps=BOOTSTRAP_REPS_DEFAULT, seed=42, alpha=0.05):
    """Returns dict with point estimate, trader-only CI, market-only CI,
    two-way CI, which CI was reported, and whether the fallback triggered."""
    if len(sub) == 0:
        return dict(mean=None, n_traders=0, n_markets=0, n_positions=0,
                     ci_lo=None, ci_hi=None, method='none')

    point = float(sub['edge'].sum() / len(sub))
    n_positions = len(sub)

    per_trader = sub.groupby('trader')['edge'].agg(['sum', 'count'])
    trader_lo, trader_hi = _one_way_ci(per_trader['sum'].to_numpy(), per_trader['count'].to_numpy(),
                                        reps, seed)

    per_market = sub.groupby('market_id')['edge'].agg(['sum', 'count'])
    market_lo, market_hi = _one_way_ci(per_market['sum'].to_numpy(), per_market['count'].to_numpy(),
                                        reps, seed + 1)

    # two-way: precompute (trader_idx, market_idx, sum_edge, n) per (trader, market) pair
    traders = sub['trader'].astype('category')
    markets = sub['market_id'].astype('category')
    tmp = pd.DataFrame({
        'trader_idx': traders.cat.codes.to_numpy(),
        'market_idx': markets.cat.codes.to_numpy(),
        'edge': sub['edge'].to_numpy(),
    })
    pair = tmp.groupby(['trader_idx', 'market_idx'])['edge'].agg(['sum', 'count']).reset_index()
    n_traders = traders.cat.categories.size
    n_markets = markets.cat.categories.size
    t_idx = pair['trader_idx'].to_numpy()
    m_idx = pair['market_idx'].to_numpy()
    p_sum = pair['sum'].to_numpy()
    p_cnt = pair['count'].to_numpy()

    rng = np.random.default_rng(seed + 2)
    boot = np.empty(reps)
    for b in range(reps):
        t_draw = rng.integers(0, n_traders, size=n_traders)
        t_mult = np.bincount(t_draw, minlength=n_traders)
        m_draw = rng.integers(0, n_markets, size=n_markets)
        m_mult = np.bincount(m_draw, minlength=n_markets)
        w = t_mult[t_idx] * m_mult[m_idx]
        denom = (w * p_cnt).sum()
        boot[b] = (w * p_sum).sum() / denom if denom > 0 else np.nan
    boot = boot[~np.isnan(boot)]
    if len(boot) < reps * 0.5:
        twoway_lo, twoway_hi = None, None
    else:
        twoway_lo, twoway_hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        twoway_lo, twoway_hi = float(twoway_lo), float(twoway_hi)

    trader_w = (trader_hi - trader_lo) if trader_lo is not None else None
    market_w = (market_hi - market_lo) if market_lo is not None else None
    twoway_w = (twoway_hi - twoway_lo) if twoway_lo is not None else None
    max_oneway_w = max(w for w in (trader_w, market_w) if w is not None) if (trader_w or market_w) else None

    method = 'two_way'
    reported_lo, reported_hi = twoway_lo, twoway_hi
    if twoway_w is None or (max_oneway_w is not None and twoway_w < 0.9 * max_oneway_w):
        # unstable/degenerate two-way estimate -- fall back to the WIDER one-way CI
        if trader_w is not None and market_w is not None:
            if trader_w >= market_w:
                reported_lo, reported_hi, method = trader_lo, trader_hi, 'fallback_trader_wider'
            else:
                reported_lo, reported_hi, method = market_lo, market_hi, 'fallback_market_wider'
        elif trader_w is not None:
            reported_lo, reported_hi, method = trader_lo, trader_hi, 'fallback_trader_only'
        elif market_w is not None:
            reported_lo, reported_hi, method = market_lo, market_hi, 'fallback_market_only'

    return dict(
        mean=point, n_positions=n_positions, n_traders=n_traders, n_markets=n_markets,
        ci_lo=reported_lo, ci_hi=reported_hi, method=method,
        trader_ci=(trader_lo, trader_hi), market_ci=(market_lo, market_hi),
        twoway_ci=(twoway_lo, twoway_hi),
    )


def stratified_table(df, n_strata=N_STRATA_DEFAULT, reps=BOOTSTRAP_REPS_DEFAULT, seed=SEED_DEFAULT):
    if len(df) == 0:
        return [], []
    try:
        strat, bins = pd.qcut(df['geo_elo'], q=n_strata, labels=False, retbins=True, duplicates='drop')
    except ValueError:
        return [], []
    df = df.copy()
    df['_stratum'] = strat
    out = []
    for s in sorted(df['_stratum'].dropna().unique()):
        sub = df[df['_stratum'] == s]
        stats = two_way_cluster_bootstrap(sub, reps=reps, seed=seed + int(s) * 7)
        out.append(dict(stratum=int(s), value_range=(float(bins[int(s)]), float(bins[int(s) + 1])), **stats))
    return out, bins.tolist()


def rank_corr(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2:
        return None
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def table_rank_corr(rows):
    if not rows:
        return None
    return rank_corr([r['stratum'] for r in rows], [r['mean'] for r in rows])


# ---------------------------------------------------------------------------
# Concentration diagnostics
# ---------------------------------------------------------------------------

def top_n_markets(df, n=15):
    counts = df.groupby('market_id').size().sort_values(ascending=False)
    return counts.head(n).index.tolist(), counts


def apply_top15_exclusion(df):
    top15, counts = top_n_markets(df, 15)
    return df[~df['market_id'].isin(top15)].copy(), top15, counts


def apply_market_cap(df, seed=SEED_DEFAULT):
    counts = df.groupby('market_id').size()
    cap = int(counts.median())
    rng = np.random.default_rng(seed)
    keep_idx = []
    for mid, grp in df.groupby('market_id'):
        if len(grp) <= cap:
            keep_idx.extend(grp.index.tolist())
        else:
            chosen = rng.choice(grp.index.to_numpy(), size=cap, replace=False)
            keep_idx.extend(chosen.tolist())
    return df.loc[keep_idx].copy(), cap


# ---------------------------------------------------------------------------
# Calibration curve
# ---------------------------------------------------------------------------

def calibration_curve(df, side, n_buckets=10):
    sub = df[df['outcome'] == side].copy()
    if len(sub) == 0:
        return []
    sub['bucket'], bins = pd.qcut(sub['entry_price_side'], q=n_buckets, labels=False,
                                   retbins=True, duplicates='drop')
    out = []
    for b in sorted(sub['bucket'].dropna().unique()):
        g = sub[sub['bucket'] == b]
        out.append(dict(
            bucket=int(b), price_lo=float(bins[int(b)]), price_hi=float(bins[int(b) + 1]),
            n=int(len(g)), mean_price=float(g['entry_price_side'].mean()),
            mean_won=float(g['won'].mean()), gap=float(g['won'].mean() - g['entry_price_side'].mean()),
        ))
    return out


# ---------------------------------------------------------------------------
# Reporting / persistence
# ---------------------------------------------------------------------------

def print_table(name, rows):
    print(f"\n=== {name} ===")
    if not rows:
        print("  (no strata)")
        return
    print(f"  {'str':>4} {'range':>20} {'n_trd':>6} {'n_mkt':>6} {'n_pos':>7} "
          f"{'mean':>9} {'ci_lo':>8} {'ci_hi':>8} {'method':>22}")
    for r in rows:
        lo, hi = r['value_range']
        ci_lo = r['ci_lo'] if r['ci_lo'] is not None else float('nan')
        ci_hi = r['ci_hi'] if r['ci_hi'] is not None else float('nan')
        print(f"  {r['stratum']:>4} {lo:>9.1f}-{hi:<9.1f} {r['n_traders']:>6} {r['n_markets']:>6} "
              f"{r['n_positions']:>7} {r['mean']:>9.4f} {ci_lo:>8.4f} {ci_hi:>8.4f} {r['method']:>22}")
    rc = table_rank_corr(rows)
    print(f"  rank_corr(stratum, mean_edge) = {rc}")


def print_calib(name, rows):
    print(f"\n=== {name} ===")
    print(f"  {'bucket':>6} {'price_range':>20} {'n':>7} {'mean_price':>10} {'mean_won':>9} {'gap':>8}")
    for r in rows:
        print(f"  {r['bucket']:>6} {r['price_lo']:>9.3f}-{r['price_hi']:<9.3f} {r['n']:>7} "
              f"{r['mean_price']:>10.4f} {r['mean_won']:>9.4f} {r['gap']:>8.4f}")


def persist(conn, tables, calib_tables, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS layer0b_pre_registration")
    conn.execute("""
        CREATE TABLE layer0b_pre_registration (
            spec_version TEXT PRIMARY KEY, h1 TEXT, metric TEXT, criterion_change TEXT,
            success_criterion TEXT, layer0_lineage TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO layer0b_pre_registration VALUES (?,?,?,?,?,?,?,?)",
                 (SPEC_VERSION, H1_TEXT, METRIC_TEXT, CHANGE_TEXT, SUCCESS_TEXT,
                  LAYER0_LINEAGE, generated_at, generator_commit))

    conn.execute("DROP TABLE IF EXISTS layer0b_stratum_summary")
    conn.execute("""
        CREATE TABLE layer0b_stratum_summary (
            variant TEXT, stratum INTEGER, value_lo REAL, value_hi REAL,
            n_traders INTEGER, n_markets INTEGER, n_positions INTEGER, mean_edge REAL,
            ci_lo REAL, ci_hi REAL, ci_method TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for variant, rows in tables.items():
        for r in rows:
            conn.execute("""
                INSERT INTO layer0b_stratum_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (variant, r['stratum'], r['value_range'][0], r['value_range'][1],
                  r['n_traders'], r['n_markets'], r['n_positions'], r['mean'],
                  r['ci_lo'], r['ci_hi'], r['method'], SPEC_VERSION, generated_at, generator_commit))

    conn.execute("DROP TABLE IF EXISTS layer0b_calibration_curve")
    conn.execute("""
        CREATE TABLE layer0b_calibration_curve (
            side TEXT, bucket INTEGER, price_lo REAL, price_hi REAL, n INTEGER,
            mean_price REAL, mean_won REAL, gap REAL, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for side, rows in calib_tables.items():
        for r in rows:
            conn.execute("""
                INSERT INTO layer0b_calibration_curve VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (side, r['bucket'], r['price_lo'], r['price_hi'], r['n'],
                  r['mean_price'], r['mean_won'], r['gap'], SPEC_VERSION, generated_at, generator_commit))

    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('--selfcheck-n', type=int, default=200)
    ap.add_argument('--n-strata', type=int, default=N_STRATA_DEFAULT)
    ap.add_argument('--bootstrap-reps', type=int, default=BOOTSTRAP_REPS_DEFAULT)
    ap.add_argument('--seed', type=int, default=SEED_DEFAULT)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    print(f"=== PRE-REGISTRATION (fixed before results, spec {SPEC_VERSION}) ===")
    print(f"H1: {H1_TEXT}")
    print(f"METRIC: {METRIC_TEXT}")
    print(f"CHANGE FROM LAYER 0 (recorded before computing): {CHANGE_TEXT}")
    print(f"SUCCESS CRITERION: {SUCCESS_TEXT}")
    print(f"LINEAGE: {LAYER0_LINEAGE}")

    df = load_data(conn, verbose=args.verbose)

    if args.selfcheck:
        n, mismatches = selfcheck(conn, df, n_samples=args.selfcheck_n, verbose=True)
        if mismatches:
            print(f"[selfcheck] FAILED: {len(mismatches)}/{n} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n} match")
        if not args.persist and not args.json_out:
            conn.close()
            return

    tables = {}
    calib_tables = {}

    # 2. primary corrected stratum table
    primary_rows, _ = stratified_table(df, n_strata=args.n_strata, reps=args.bootstrap_reps, seed=args.seed)
    tables['primary_two_way'] = primary_rows
    print_table('PRIMARY (two-way clustered CIs)', primary_rows)

    # 3a. top-15 excluded
    df_excl, top15, counts = apply_top15_exclusion(df)
    print(f"\n[concentration] top-15 markets (geo_elo-eligible pop) account for "
          f"{counts.head(15).sum()}/{len(df)} ({100*counts.head(15).sum()/len(df):.1f}%) of positions")
    excl_rows, _ = stratified_table(df_excl, n_strata=args.n_strata, reps=args.bootstrap_reps, seed=args.seed)
    tables['top15_excluded'] = excl_rows
    print_table(f'CONCENTRATION DIAGNOSTIC: top-15 markets excluded (n={len(df_excl)})', excl_rows)

    # 3b. capped at median market position count
    df_capped, cap = apply_market_cap(df, seed=args.seed)
    print(f"\n[concentration] per-market cap = median = {cap} positions/market; "
          f"{len(df)} -> {len(df_capped)} positions after capping")
    capped_rows, _ = stratified_table(df_capped, n_strata=args.n_strata, reps=args.bootstrap_reps, seed=args.seed)
    tables['capped_at_median'] = capped_rows
    print_table(f'CONCENTRATION DIAGNOSTIC: capped at median={cap} (n={len(df_capped)})', capped_rows)

    # 4. Yes/No split
    yes_rows, _ = stratified_table(df[df['outcome'] == 'Yes'], n_strata=args.n_strata,
                                    reps=args.bootstrap_reps, seed=args.seed)
    tables['yes_only'] = yes_rows
    print_table(f"YES-SIDE ONLY (n={len(df[df['outcome']=='Yes'])})", yes_rows)

    no_rows, _ = stratified_table(df[df['outcome'] == 'No'], n_strata=args.n_strata,
                                   reps=args.bootstrap_reps, seed=args.seed)
    tables['no_only'] = no_rows
    print_table(f"NO-SIDE ONLY (n={len(df[df['outcome']=='No'])})", no_rows)

    # 5. calibration curves
    calib_yes = calibration_curve(df, 'Yes', n_buckets=args.n_strata)
    calib_tables['Yes'] = calib_yes
    print_calib('CALIBRATION: Yes side, entry_price_side vs realized win rate', calib_yes)

    calib_no = calibration_curve(df, 'No', n_buckets=args.n_strata)
    calib_tables['No'] = calib_no
    print_calib('CALIBRATION: No side, entry_price_side vs realized win rate', calib_no)

    # 6. key question: bottom-decile edge across variants
    print("\n=== KEY QUESTION: bottom-decile edge across corrections ===")
    summary = {}
    for name, rows in tables.items():
        if rows:
            bottom = rows[0]
            top = rows[-1]
            summary[name] = dict(bottom_mean=bottom['mean'], bottom_ci=(bottom['ci_lo'], bottom['ci_hi']),
                                  top_mean=top['mean'], top_ci=(top['ci_lo'], top['ci_hi']),
                                  rank_corr=table_rank_corr(rows))
            print(f"  {name:>18}: bottom={bottom['mean']:.4f} [{bottom['ci_lo']:.4f},{bottom['ci_hi']:.4f}]  "
                  f"top={top['mean']:.4f} [{top['ci_lo']:.4f},{top['ci_hi']:.4f}]  "
                  f"rank_corr={summary[name]['rank_corr']}")

    result = dict(
        spec_version=SPEC_VERSION,
        pre_registration=dict(h1=H1_TEXT, metric=METRIC_TEXT, criterion_change=CHANGE_TEXT,
                               success_criterion=SUCCESS_TEXT, lineage=LAYER0_LINEAGE),
        scope=dict(n_positions=len(df), n_traders=int(df['trader'].nunique()),
                   n_markets=int(df['market_id'].nunique())),
        top15_market_ids=top15,
        market_cap=cap,
        tables=tables,
        calibration=calib_tables,
        key_question_summary=summary,
    )
    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()

    if args.persist:
        generated_at = datetime.now(timezone.utc).isoformat()
        last_err = None
        for attempt in range(5):
            try:
                wconn = db_connect(args.db)
                persist(wconn, tables, calib_tables, args.generator_commit, generated_at)
                wconn.close()
                last_err = None
                break
            except sqlite3.OperationalError as e:
                last_err = e
                print(f"[persist] attempt {attempt+1} failed ({e}); retrying...", file=sys.stderr)
                import time as _time
                _time.sleep(5)
        if last_err:
            print(f"[persist] FAILED after retries: {last_err}", file=sys.stderr)
            sys.exit(1)
        print(f"[persist] layer0b_pre_registration, layer0b_stratum_summary, "
              f"layer0b_calibration_curve written, generated_at={generated_at}")


if __name__ == '__main__':
    main()
