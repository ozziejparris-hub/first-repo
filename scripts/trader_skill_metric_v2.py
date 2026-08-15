#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2 -- build and characterise a replacement for geo_elo,
alongside it, not instead of it. Read-only. No production writes. Does not
modify update_geo_elo.py, geo_elo_active, or cohort membership. Cutover is a
separate, later decision made on evidence from this pass.

=============================================================================
WHY (the geo_elo derivation audit's findings -- recorded so the rationale is
legible later; artifacts: elo_formula_audit_findings, geo_elo_derivation_audit,
first-repo 57ed326)
=============================================================================
- SIGN ERROR in code AND docstring: expected = price if Yes else 1-price, but
  price already equals P(the traded outcome wins) for both sides (paired
  Yes/No trades within 60s of each other sum to 1.000 +/- 0.001). The written
  spec was wrong from the birth commit -- every prior code-vs-spec validation
  passed because the code faithfully implemented a wrong formula.
- IMPROPER under the bug: a zero-skill trader buying favoured No positions
  earns expected 2*price-1 > 0 per trade -- free rating for zero edge, and
  not exotic (71% of these markets resolve No; volume clusters on favourites).
- SELL trades are NOT excluded (no side filter anywhere in
  _fetch_qualifying_trades). 35.7% of the qualifying population is SELL,
  folded in under trade_evaluator.py's INVERTED win-condition, unflagged.
- SEVERE DOUBLE-COUNTING: 86.3% of qualifying trades belong to a
  (trader,market) pair with >1 qualifying trade -- the K-schedule counts
  decision fragments, not decisions.
- Not size-weighted; no time-to-resolution weighting.
- Every constant (K-schedule, starting rating, ratchet, MIN_TRADES, tier
  ladder, decay half-life) traced to origin: none calibrated against data.

=============================================================================
PRE-REGISTRATION (fixed before computing; written to
metric_v2_pre_registration before any result row)
=============================================================================

PURPOSE: build a trustworthy trader skill metric alongside geo_elo (not
replacing it), and characterise how it compares. This is a construction +
characterisation pass, not a hypothesis test with a single H1/H0.

--- DECISION 1: NOT a rating. ---
The output is mean market-relative edge per independent decision, with a
confidence interval, plus a shrunk point estimate for ranking. Rationale: it
is directly interpretable ("beats the market by X, CI [a,b]"), it is what we
actually want to know, and -- the decisive argument -- it makes bugs VISIBLE.
The sign error hid for months inside a sequential accumulator; on a
mean-edge-vs-price plot it would have been obvious immediately (see item 10,
the calibration gate, below). We accept losing rating-like continuity with
geo_elo; the audit established that continuity is lost anyway (the sign fix
alone reshuffles LEGENDARY membership by 46%).

--- DECISION 2: ENTRIES ONLY for the primary metric; exits measured separately. ---
Identifying mispricing (entry) and timing an exit are different skills, and
folding them together under a borrowed win-condition is exactly what produced
the SELL problem in geo_elo. This deliberately drops the exit side of every
position from the primary metric -- recorded as a considered choice, not a
silent omission. Exits get their own parallel metric (see below) so the
information isn't lost and the two can be compared (item 11).

--- THE METRIC ---
1. UNIT: one observation per independent decision = one (trader, market,
   side) position from the positions table's FIFO aggregation, NOT raw
   trades. Structurally fixes geo_elo's double-counting rather than patching
   it.
2. EDGE (entries) = won - entry_avg_price. NO conditional flip -- the field
   already means P(win) regardless of side (established empirically, Part A
   of the price-convention audit). This is exactly what
   layer0c_corrected_metric.py already validated; the same normalization
   principle is reused here (not reimported as code, since this script needs
   the UNRESTRICTED entries population -- no [0.10,0.80] band, no
   geo_elo-definedness gate -- which layer0_position_results/layer0c do not
   provide).
3. EDGE (exits, DEFINED HERE, not reused from trade_evaluator.py's inverted
   SELL semantic): edge_exit = exit_avg_price - won. Symmetric to the entry
   formula by construction: buying LOW relative to eventual truth is a good
   entry (edge_entry = won - price > 0 when price undershoots the truth);
   selling HIGH relative to eventual truth is a good exit (edge_exit =
   price - won > 0 when price overshoots the truth, i.e. you got out before
   the market caught up, or held that long precisely because the market was
   still underpricing your risk correctly). `won` is the SAME fact both
   times (did the position's outcome side ultimately win), sourced once from
   the entry trade's trade_result -- this is a market-level fact independent
   of which event (entry or exit) is being scored, so reusing it for both is
   correct, not double-dipping. exit_avg_price uses the same "price of the
   side actually traded" convention as entry_avg_price (independently
   confirmed in the price-convention audit's paired-sum test on
   positions.exit_avg_price, mean sum 0.999 +/- 0.0007) -- no flip needed
   here either.
4. AGGREGATION: per-trader mean edge, with empirical-Bayes (James-Stein-style)
   shrinkage toward the population mean, weighted inversely by sample
   size/variance. This REPLACES both geo_elo's K-schedule and its ratchet
   cap with one principled mechanism -- both were ad hoc attempts to solve
   the same problem (don't overreact to small samples).
5. UNCERTAINTY: nonparametric bootstrap CI per trader, on the RAW per-trader
   mean (shrinkage's effect on the point estimate is reported separately and
   is fully inspectable: raw mean, shrunk mean, n, and shrinkage weight are
   all reported side by side, per trader).
6. SCOPE: Geopolitics + Elections (markets.category, never the denormalized
   trades.market_category), resolved outcomes (entry trade's trade_result IN
   ('won','lost')), entries only for the primary metric, trade-gap-flagged
   markets excluded. Full available history, no date restriction.
7. EXPLICITLY NOT APPLIED: the [0.10,0.80] price band (its origin was
   anti-arb filtering -- a different, already-audited purpose the FABLE
   design doc conflated with the later contested-band choice -- not a
   property of what makes an observation valid for this metric),
   MIN_TRADES_FOR_ELO=5 (shrinkage handles small samples principledly
   instead of a hard cutoff), and no tier threshold (thresholds are a
   downstream choice to be re-derived from this metric's OWN distribution
   later, not inherited).

--- GATE (item 10) ---
Before any interpretation of the results below, this script computes mean
edge vs. entry price in deciles, separately for Yes and No. A correctly
normalised metric shows both sides flat around zero with no monotonic
inversion (matching the already-established Layer 0c/0b calibration
curves). If either side shows a clear monotonic trend beyond bootstrap
noise, THIS IS A GATE FAILURE: STOP, do not interpret the rest of the
results, and report the failure plainly rather than proceeding.

--- EXPLICITLY OUT OF SCOPE THIS PASS ---
No production writes. No changes to update_geo_elo.py, geo_elo_active,
cohort membership, or any live path. No threshold derivation, no cutover
decision -- those come after this metric is trusted. comprehensive_elo /
calibration_analysis.py's analogous bug: separate system, separate scope,
still open.

Persists metric_v2_pre_registration, metric_v2_trader_results,
metric_v2_calibration_curve, metric_v2_comparison_findings.
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

SPEC_VERSION = "SKILLV2-2026-08-15-v1"
BOOTSTRAP_REPS = 1000
SEED = 42
N_CALIB_BUCKETS = 10

PURPOSE_TEXT = ("Build and characterise a trustworthy trader-skill metric alongside geo_elo (not "
                "replacing it in production). Construction + characterisation pass, not a single "
                "hypothesis test.")
DECISION1_TEXT = ("NOT a rating. Output = mean market-relative edge per independent decision, with a "
                   "bootstrap CI, plus an empirical-Bayes-shrunk point estimate for ranking. Directly "
                   "interpretable, and makes bugs visible on a mean-edge-vs-price plot (the sign error "
                   "hid for months inside geo_elo's sequential accumulator). Rating-like continuity with "
                   "geo_elo is accepted as lost -- the audit established the sign fix alone reshuffles "
                   "LEGENDARY membership 46%, so continuity was already gone.")
DECISION2_TEXT = ("ENTRIES ONLY for the primary metric; exits measured separately with their own "
                   "symmetric win-condition (edge_exit = exit_price - won), not reusing "
                   "trade_evaluator.py's inverted SELL semantic. Entry (mispricing identification) and "
                   "exit (timing) are different skills; folding them together under one borrowed "
                   "win-condition is exactly what produced geo_elo's SELL contamination. This drops the "
                   "exit event of every position from the primary metric -- a considered choice, not a "
                   "silent omission.")
METRIC_SPEC_TEXT = ("unit=one position (trader,market,side) via positions table FIFO, not raw trades; "
                     "edge_entry=won-entry_avg_price (no flip); edge_exit=exit_avg_price-won (symmetric, "
                     "defined here not reused from trade_evaluator.py); aggregation=per-trader mean with "
                     "empirical-Bayes shrinkage toward population mean, inverse-variance weighted; "
                     "uncertainty=nonparametric bootstrap CI on raw per-trader mean; scope=Geopolitics+"
                     "Elections, resolved, trade-gap-clean, full history, NO price band, NO min-trades "
                     "cutoff, NO tier threshold.")
GATE_TEXT = ("Mean edge vs. entry price in deciles, separately Yes/No, must be flat around zero with no "
             "monotonic inversion. Gate failure means STOP and report failure, not interpret results.")


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_entries(conn, verbose=False):
    rows = conn.execute("""
        SELECT p.position_id, p.trader_address, p.market_id, p.outcome,
               p.entry_avg_price, p.entry_timestamp, t.trade_result
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
    df['edge'] = df['won'] - df['entry_avg_price']  # no flip
    if verbose:
        print(f"[load] entries: {len(df)} positions, {df['trader'].nunique()} traders")
    return df


def load_exits(conn, verbose=False):
    rows = conn.execute("""
        SELECT p.position_id, p.trader_address, p.market_id, p.outcome,
               p.exit_avg_price, p.exit_timestamp, t.trade_result
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.exit_avg_price IS NOT NULL
          AND p.exit_timestamp IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """).fetchall()
    df = pd.DataFrame(rows, columns=['position_id', 'trader', 'market_id', 'outcome',
                                      'exit_avg_price', 'exit_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    df['edge'] = df['exit_avg_price'] - df['won']  # symmetric, sign-flipped vs entry
    if verbose:
        print(f"[load] exits: {len(df)} positions, {df['trader'].nunique()} traders")
    return df


def selfcheck(conn, entries_df, exits_df, n_samples=200, seed=7, verbose=True):
    """Re-derives edge for a random sample directly from a fresh per-row DB
    fetch (not the batch-loaded frame) and asserts exact match -- catches any
    join/aggregation drift between the batch load and the source tables."""
    import random
    rng = random.Random(seed)
    mism = []
    esample = entries_df.sample(min(n_samples, len(entries_df)), random_state=seed)
    for _, row in esample.iterrows():
        fresh = conn.execute("SELECT entry_avg_price FROM positions WHERE position_id = ?",
                             (row['position_id'],)).fetchone()
        if fresh is None or abs(fresh[0] - row['entry_avg_price']) > 1e-9:
            mism.append(('entry', row['position_id']))
    xsample = exits_df.sample(min(n_samples, len(exits_df)), random_state=seed)
    for _, row in xsample.iterrows():
        fresh = conn.execute("SELECT exit_avg_price FROM positions WHERE position_id = ?",
                             (row['position_id'],)).fetchone()
        if fresh is None or abs(fresh[0] - row['exit_avg_price']) > 1e-9:
            mism.append(('exit', row['position_id']))
    if verbose:
        print(f"[selfcheck] {len(esample)} entries + {len(xsample)} exits checked, {len(mism)} mismatches")
    return len(esample) + len(xsample), mism


# ---------------------------------------------------------------------------
# Empirical-Bayes shrinkage + bootstrap CI
# ---------------------------------------------------------------------------

def eb_shrinkage(df, value_col='edge', trader_col='trader'):
    """One-way random-effects (James-Stein-style) shrinkage. sigma2_within
    estimated as the pooled sample variance of individual edges (a common,
    transparent approximation -- treats per-position noise as roughly
    homogeneous across traders rather than modelling price-dependent
    Bernoulli variance separately). sigma2_between estimated via the
    standard UNBALANCED one-way ANOVA method-of-moments estimator (Efron-
    Morris style: sigma2_between = max(0, (MSB - sigma2_within) / n_0),
    n_0 = (N - sum(n_i^2)/N) / (K-1)) rather than a naive n_i-weighted
    variance-of-means minus mean-sampling-variance -- the naive version
    degenerates (collapses sigma2_between to ~0 for EVERY trader) on
    populations dominated by small groups (e.g. market-weighted or event-
    weighted aggregation, where most traders have very few distinct
    markets/clusters), because weighting the "between" term by n_i lets a
    few high-n traders' own internal averaging (which mechanically pulls
    their mean toward the grand mean) dominate the estimate. Caught via a
    concrete symptom: shrunk_mean was bit-for-bit identical across all
    27,236 traders under market-/event-weighting in an initial run of
    trader_skill_metric_v2b.py -- not a real finding, a degenerate
    estimator. Fixed here (shared by v2 and v2b) before any interpretive
    result was reported. sigma2_between clipped to >=0 (negative implies
    no detectable between-trader true-skill variance beyond noise --
    shrink fully to the grand mean)."""
    per_trader = df.groupby(trader_col)[value_col].agg(['mean', 'var', 'count']).rename(
        columns={'mean': 'raw_mean', 'var': 'raw_var', 'count': 'n'})
    per_trader['raw_var'] = per_trader['raw_var'].fillna(df[value_col].var())

    grand_mean = df[value_col].mean()
    sigma2_within = df[value_col].var()  # pooled individual-observation variance

    sampling_var = sigma2_within / per_trader['n']

    n_i = per_trader['n'].to_numpy(dtype=float)
    K = len(per_trader)
    N = n_i.sum()
    if K > 1 and N > 0:
        msb = float(np.sum(n_i * (per_trader['raw_mean'].to_numpy() - grand_mean) ** 2) / (K - 1))
        n0 = float((N - np.sum(n_i ** 2) / N) / (K - 1))
        sigma2_between = max(0.0, (msb - sigma2_within) / n0) if n0 > 0 else 0.0
    else:
        sigma2_between = 0.0

    per_trader['shrinkage_weight'] = sigma2_between / (sigma2_between + sampling_var)
    per_trader['shrunk_mean'] = (per_trader['shrinkage_weight'] * per_trader['raw_mean'] +
                                  (1 - per_trader['shrinkage_weight']) * grand_mean)
    per_trader['grand_mean'] = grand_mean
    per_trader['sigma2_within'] = sigma2_within
    per_trader['sigma2_between'] = sigma2_between
    return per_trader.reset_index()


def bootstrap_ci_per_trader(df, value_col='edge', trader_col='trader', reps=BOOTSTRAP_REPS,
                             seed=SEED, alpha=0.05, verbose=False):
    rng = np.random.default_rng(seed)
    out = []
    for trader, grp in df.groupby(trader_col):
        vals = grp[value_col].to_numpy()
        n = len(vals)
        if n == 1:
            out.append((trader, vals[0], vals[0]))
            continue
        idx = rng.integers(0, n, size=(reps, n))
        boot_means = vals[idx].mean(axis=1)
        lo, hi = np.percentile(boot_means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
        out.append((trader, lo, hi))
    ci_df = pd.DataFrame(out, columns=[trader_col, 'ci_lo', 'ci_hi'])
    if verbose:
        print(f"[bootstrap] {len(ci_df)} traders, {reps} reps each")
    return ci_df


# ---------------------------------------------------------------------------
# Gate: calibration sanity check
# ---------------------------------------------------------------------------

def calibration_gate(entries_df, n_buckets=N_CALIB_BUCKETS, tol=0.05):
    results = {}
    gate_pass = True
    for side in ('Yes', 'No'):
        sub = entries_df[entries_df['outcome'] == side].copy()
        sub['bucket'], bins = pd.qcut(sub['entry_avg_price'], q=n_buckets, labels=False,
                                       retbins=True, duplicates='drop')
        rows = []
        for b in sorted(sub['bucket'].dropna().unique()):
            g = sub[sub['bucket'] == b]
            rows.append(dict(bucket=int(b), price_lo=float(bins[int(b)]), price_hi=float(bins[int(b) + 1]),
                              n=int(len(g)), mean_price=float(g['entry_avg_price'].mean()),
                              mean_won=float(g['won'].mean()), gap=float(g['won'].mean() - g['entry_avg_price'].mean())))
        gaps = [r['gap'] for r in rows]
        max_abs_gap = max(abs(g) for g in gaps) if gaps else 0.0
        # monotonic trend check: rank correlation between bucket index and gap
        rc = np.corrcoef(range(len(gaps)), gaps)[0, 1] if len(gaps) > 2 else 0.0
        side_pass = max_abs_gap < tol and abs(rc) < 0.7
        gate_pass = gate_pass and side_pass
        results[side] = dict(rows=rows, max_abs_gap=max_abs_gap, trend_corr=float(rc), passed=side_pass)
    return gate_pass, results


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------

def rank_corr(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def rank_comparison(conn, entries_shrunk, verbose=False):
    stored = pd.read_sql("SELECT address AS trader, geo_elo FROM traders WHERE geo_elo IS NOT NULL", conn)
    merged = entries_shrunk.merge(stored, on='trader', how='inner')
    spearman = rank_corr(merged['shrunk_mean'], merged['geo_elo'])

    # no-heavy concentration diagnostic: per-trader No-fraction among their positions
    return merged, spearman


def no_heavy_concentration(entries_df, merged, verbose=False):
    no_frac = entries_df.groupby('trader').apply(
        lambda g: (g['outcome'] == 'No').mean(), include_groups=False
    ).rename('no_frac').reset_index()
    m2 = merged.merge(no_frac, on='trader', how='left')
    m2['geo_elo_rank'] = m2['geo_elo'].rank(pct=True)
    m2['new_rank'] = m2['shrunk_mean'].rank(pct=True)
    m2['rank_disagreement'] = m2['geo_elo_rank'] - m2['new_rank']  # positive: geo_elo ranks them higher than new metric does
    corr_disagreement_no_frac = float(np.corrcoef(m2['rank_disagreement'], m2['no_frac'])[0, 1])
    return m2, corr_disagreement_no_frac


def legendary_overlap(conn, entries_shrunk, verbose=False):
    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))
    ranked = entries_shrunk.sort_values('shrunk_mean', ascending=False)
    top_n = ranked.head(len(legendary))['trader'].tolist()
    overlap = legendary & set(top_n)
    return dict(n_legendary=len(legendary), n_top_new=len(top_n),
                overlap=len(overlap), overlap_fraction=len(overlap) / len(legendary) if legendary else None)


def entries_exits_correlation(entries_eb, exits_eb, min_n=3):
    e = entries_eb[entries_eb['n'] >= min_n][['trader', 'raw_mean']].rename(columns={'raw_mean': 'entry_mean'})
    x = exits_eb[exits_eb['n'] >= min_n][['trader', 'raw_mean']].rename(columns={'raw_mean': 'exit_mean'})
    merged = e.merge(x, on='trader', how='inner')
    if len(merged) < 3:
        return dict(n=len(merged), pearson=None, spearman=None)
    pearson = float(np.corrcoef(merged['entry_mean'], merged['exit_mean'])[0, 1])
    spearman = rank_corr(merged['entry_mean'], merged['exit_mean'])
    return dict(n=len(merged), pearson=pearson, spearman=spearman)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist(conn, pre_reg_rows, trader_results, calib_rows, findings, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS metric_v2_pre_registration")
    conn.execute("""
        CREATE TABLE metric_v2_pre_registration (
            spec_version TEXT PRIMARY KEY, purpose TEXT, decision1 TEXT, decision2 TEXT,
            metric_spec TEXT, gate TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2_pre_registration VALUES (?,?,?,?,?,?,?,?)", pre_reg_rows)

    conn.execute("DROP TABLE IF EXISTS metric_v2_trader_results")
    conn.execute("""
        CREATE TABLE metric_v2_trader_results (
            trader TEXT, kind TEXT, n INTEGER, raw_mean REAL, shrunk_mean REAL,
            shrinkage_weight REAL, ci_lo REAL, ci_hi REAL, distinguishable_from_zero INTEGER,
            stored_geo_elo REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT,
            PRIMARY KEY (trader, kind)
        )
    """)
    for _, r in trader_results.iterrows():
        conn.execute("INSERT INTO metric_v2_trader_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r['trader'], r['kind'], int(r['n']), r['raw_mean'], r['shrunk_mean'], r['shrinkage_weight'],
            r.get('ci_lo'), r.get('ci_hi'), int(r.get('distinguishable_from_zero', 0)),
            r.get('geo_elo'), SPEC_VERSION, generated_at, generator_commit,
        ))

    conn.execute("DROP TABLE IF EXISTS metric_v2_calibration_curve")
    conn.execute("""
        CREATE TABLE metric_v2_calibration_curve (
            side TEXT, bucket INTEGER, price_lo REAL, price_hi REAL, n INTEGER,
            mean_price REAL, mean_won REAL, gap REAL, spec_version TEXT, generated_at TEXT
        )
    """)
    for side, rows in calib_rows.items():
        for r in rows:
            conn.execute("INSERT INTO metric_v2_calibration_curve VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (side, r['bucket'], r['price_lo'], r['price_hi'], r['n'],
                          r['mean_price'], r['mean_won'], r['gap'], SPEC_VERSION, generated_at))

    conn.execute("DROP TABLE IF EXISTS metric_v2_comparison_findings")
    conn.execute("""
        CREATE TABLE metric_v2_comparison_findings (
            finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for k, v in findings.items():
        conn.execute("INSERT INTO metric_v2_comparison_findings VALUES (?,?,?,?,?)",
                     (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('--bootstrap-reps', type=int, default=BOOTSTRAP_REPS)
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    print(f"=== PRE-REGISTRATION (fixed before results, spec {SPEC_VERSION}) ===")
    print(f"PURPOSE: {PURPOSE_TEXT}")
    print(f"DECISION 1: {DECISION1_TEXT}")
    print(f"DECISION 2: {DECISION2_TEXT}")
    print(f"METRIC SPEC: {METRIC_SPEC_TEXT}")
    print(f"GATE: {GATE_TEXT}")

    entries_df = load_entries(conn, verbose=args.verbose)
    exits_df = load_exits(conn, verbose=args.verbose)

    if args.selfcheck:
        n, mism = selfcheck(conn, entries_df, exits_df, verbose=True)
        if mism:
            print(f"[selfcheck] FAILED: {len(mism)}/{n} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n} match")
        if not args.persist and not args.json_out:
            conn.close()
            return

    print(f"\n[scope] entries: {len(entries_df)} positions, {entries_df['trader'].nunique()} traders, "
          f"date span {entries_df['entry_ts'].min()} -> {entries_df['entry_ts'].max()}")
    print(f"[scope] exits: {len(exits_df)} positions, {exits_df['trader'].nunique()} traders")

    # --- GATE FIRST ---
    print("\n=== GATE (item 10): calibration sanity check -- must pass before interpreting anything else ===")
    gate_pass, gate_results = calibration_gate(entries_df)
    for side, r in gate_results.items():
        print(f"  {side}: max|gap|={r['max_abs_gap']:.4f} trend_corr={r['trend_corr']:.3f} PASS={r['passed']}")
        for row in r['rows']:
            print(f"    bucket {row['bucket']}: price {row['price_lo']:.3f}-{row['price_hi']:.3f} "
                  f"n={row['n']} mean_price={row['mean_price']:.4f} mean_won={row['mean_won']:.4f} gap={row['gap']:+.4f}")
    print(f"\n[GATE] {'PASSED' if gate_pass else 'FAILED'}")
    if not gate_pass:
        print("[GATE] FAILED -- stopping per pre-registration. Not proceeding to interpretation "
              "(items 7-9, 11 are NOT computed this run).", file=sys.stderr)
        gate_findings = dict(
            scope=dict(n_entries=len(entries_df), n_entry_traders=int(entries_df['trader'].nunique()),
                       n_exits=len(exits_df), n_exit_traders=int(exits_df['trader'].nunique())),
            gate=dict(passed=False,
                      yes=dict(max_abs_gap=gate_results['Yes']['max_abs_gap'],
                               trend_corr=gate_results['Yes']['trend_corr']),
                      no=dict(max_abs_gap=gate_results['No']['max_abs_gap'],
                              trend_corr=gate_results['No']['trend_corr'])),
        )
        if args.json_out:
            with open(args.json_out, 'w') as f:
                json.dump(dict(gate_pass=False, gate_results=gate_results), f, indent=2, default=str)
        if args.persist:
            generated_at = datetime.now(timezone.utc).isoformat()
            pre_reg_rows = (SPEC_VERSION, PURPOSE_TEXT, DECISION1_TEXT, DECISION2_TEXT, METRIC_SPEC_TEXT,
                            GATE_TEXT, generated_at, args.generator_commit)
            calib_rows = {side: r['rows'] for side, r in gate_results.items()}
            empty_trader_results = pd.DataFrame(columns=['trader', 'kind', 'n', 'raw_mean', 'shrunk_mean',
                                                          'shrinkage_weight', 'ci_lo', 'ci_hi',
                                                          'distinguishable_from_zero', 'geo_elo'])
            last_err = None
            for attempt in range(5):
                try:
                    wconn = db_connect(args.db)
                    persist(wconn, pre_reg_rows, empty_trader_results, calib_rows, gate_findings,
                           args.generator_commit, generated_at)
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
            else:
                print(f"[persist] GATE FAILURE recorded: metric_v2_pre_registration, "
                      f"metric_v2_calibration_curve (showing the failing buckets), "
                      f"metric_v2_comparison_findings (gate=False). "
                      f"metric_v2_trader_results is empty -- items 7-9/11 not computed. "
                      f"generated_at={generated_at}")
        conn.close()
        sys.exit(2)

    # --- entries: shrinkage + bootstrap ---
    entries_eb = eb_shrinkage(entries_df)
    entries_ci = bootstrap_ci_per_trader(entries_df, reps=args.bootstrap_reps, seed=args.seed, verbose=args.verbose)
    entries_full = entries_eb.merge(entries_ci, on='trader')
    entries_full['distinguishable_from_zero'] = ((entries_full['ci_lo'] > 0) | (entries_full['ci_hi'] < 0)).astype(int)
    entries_full['kind'] = 'entry'

    print(f"\n=== ITEM 7: distribution of shrunk edge across traders ===")
    print(entries_full['shrunk_mean'].describe())
    n_dist_from_zero = entries_full['distinguishable_from_zero'].sum()
    print(f"distinguishable from zero at 95% (raw-mean bootstrap CI): {n_dist_from_zero}/{len(entries_full)} "
          f"({100*n_dist_from_zero/len(entries_full):.1f}%)")
    print(f"sigma2_within={entries_eb['sigma2_within'].iloc[0]:.4f} sigma2_between={entries_eb['sigma2_between'].iloc[0]:.6f} "
          f"grand_mean={entries_eb['grand_mean'].iloc[0]:.4f}")

    # --- exits: shrinkage + bootstrap ---
    exits_eb = eb_shrinkage(exits_df)
    exits_ci = bootstrap_ci_per_trader(exits_df, reps=args.bootstrap_reps, seed=args.seed, verbose=args.verbose)
    exits_full = exits_eb.merge(exits_ci, on='trader')
    exits_full['distinguishable_from_zero'] = ((exits_full['ci_lo'] > 0) | (exits_full['ci_hi'] < 0)).astype(int)
    exits_full['kind'] = 'exit'

    # --- item 8: rank comparison vs current geo_elo ---
    merged, spearman = rank_comparison(conn, entries_full, verbose=args.verbose)
    print(f"\n=== ITEM 8: rank comparison vs current (buggy, stored) geo_elo ===")
    print(f"n overlapping traders = {len(merged)}, Spearman(shrunk_mean, geo_elo) = {spearman:.4f}")

    m2, corr_disagreement_no_frac = no_heavy_concentration(entries_df, merged, verbose=args.verbose)
    print(f"corr(rank_disagreement, No-fraction) = {corr_disagreement_no_frac:.4f} "
          f"(positive => geo_elo over-ranks No-heavy traders relative to the corrected metric, "
          f"as the improperness finding predicts)")

    # --- item 9: LEGENDARY overlap ---
    legend = legendary_overlap(conn, entries_full, verbose=args.verbose)
    print(f"\n=== ITEM 9: LEGENDARY overlap ===")
    print(json.dumps(legend, indent=2))

    # --- item 11: entries vs exits correlation ---
    ee_corr = entries_exits_correlation(entries_eb, exits_eb)
    print(f"\n=== ITEM 11: entries-skill vs exits-skill correlation per trader ===")
    print(json.dumps(ee_corr, indent=2))

    # attach stored geo_elo to trader_results for persistence
    stored = pd.read_sql("SELECT address AS trader, geo_elo FROM traders", conn)
    entries_full = entries_full.merge(stored, on='trader', how='left')
    exits_full = exits_full.merge(stored, on='trader', how='left')

    trader_results = pd.concat([
        entries_full[['trader', 'kind', 'n', 'raw_mean', 'shrunk_mean', 'shrinkage_weight',
                       'ci_lo', 'ci_hi', 'distinguishable_from_zero', 'geo_elo']],
        exits_full[['trader', 'kind', 'n', 'raw_mean', 'shrunk_mean', 'shrinkage_weight',
                     'ci_lo', 'ci_hi', 'distinguishable_from_zero', 'geo_elo']],
    ], ignore_index=True)

    calib_rows = {side: r['rows'] for side, r in gate_results.items()}

    findings = dict(
        scope=dict(n_entries=len(entries_df), n_entry_traders=int(entries_df['trader'].nunique()),
                   n_exits=len(exits_df), n_exit_traders=int(exits_df['trader'].nunique())),
        gate=dict(passed=gate_pass, yes=dict(max_abs_gap=gate_results['Yes']['max_abs_gap'],
                                              trend_corr=gate_results['Yes']['trend_corr']),
                  no=dict(max_abs_gap=gate_results['No']['max_abs_gap'],
                          trend_corr=gate_results['No']['trend_corr'])),
        distribution=dict(n_traders=len(entries_full),
                          n_distinguishable_from_zero_95=int(n_dist_from_zero),
                          shrunk_mean_summary=entries_full['shrunk_mean'].describe().to_dict()),
        rank_comparison=dict(n_overlap=len(merged), spearman=spearman,
                             corr_disagreement_no_frac=corr_disagreement_no_frac),
        legendary_overlap=legend,
        entries_exits_correlation=ee_corr,
    )

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()

    if args.persist:
        generated_at = datetime.now(timezone.utc).isoformat()
        pre_reg_rows = (SPEC_VERSION, PURPOSE_TEXT, DECISION1_TEXT, DECISION2_TEXT, METRIC_SPEC_TEXT,
                        GATE_TEXT, generated_at, args.generator_commit)
        last_err = None
        for attempt in range(5):
            try:
                wconn = db_connect(args.db)
                persist(wconn, pre_reg_rows, trader_results, calib_rows, findings,
                       args.generator_commit, generated_at)
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
        print(f"[persist] metric_v2_pre_registration, metric_v2_trader_results ({len(trader_results)} rows), "
              f"metric_v2_calibration_curve, metric_v2_comparison_findings written, generated_at={generated_at}")


if __name__ == '__main__':
    main()
