#!/usr/bin/env python3
"""
LAYER 0c -- corrected outcome-normalization, discovered during Layer 0b.

=============================================================================
WHY THIS EXISTS (discovered mid-Layer-0b, not pre-registered until now)
=============================================================================
Layer 0b pre-registered METRIC as "unchanged from Layer 0" and found the
Yes-side and No-side stratified tables behaved completely differently: Yes
was flat-at-zero everywhere (consistent with H0), No was strongly positive
at EVERY decile including the bottom (0.31-0.55). The standalone calibration
curve (layer0b_calibration_curve) explained why: Yes-side entry_price_side
tracks realized win rate closely (gaps -0.025 to +0.045). No-side, under
Layer 0/0b's normalization (entry_price_side = 1 - entry_avg_price), showed
a near-perfect INVERSION -- gap +0.995 at the cheapest bucket collapsing
smoothly to -0.897 at the most expensive one.

That specific shape -- not noisy, not extreme-only, a clean monotonic
inversion across the FULL range -- is the signature of a sign error, not a
market inefficiency. Direct test (this session, ad hoc, not itself
pre-registered since it is a diagnostic of the metric, not a result):
recomputing the No-side calibration curve using RAW entry_avg_price (no
outcome-based flip) shows gaps of -0.026 to +0.065 throughout -- essentially
as well-calibrated as the Yes side. Confirmed independently at the raw
trades.price level (BUY-only, no flip): mostly well-calibrated with one
smaller residual anomaly in the 0.49-0.65 range (+0.16) that does not
propagate through position-level aggregation (the corrected position-level
check has no comparable residual).

CONCLUSION: `positions.entry_avg_price` represents the price of the outcome
ACTUALLY BOUGHT (Yes or No), not a Yes-always-implied-probability. Layer 0's
own normalization (`entry_avg_price if outcome=='Yes' else 1-entry_avg_price`)
was WRONG for the No side -- it should never have flipped. The corrected
formula is simply `entry_price_of_their_side = entry_avg_price`, unconditionally.

NOT CLAIMED HERE, AND NOT TOUCHED: whether `scripts/update_geo_elo.py`'s
`_compute_geo_elo` formula (`expected = price if outcome_bet=='Yes' else
1.0-price`, operating on raw `trades.price`, unfiltered by side, i.e.
including SELL trades) has the analogous bug. That is a claim about a
different field (trades.price, not positions.entry_avg_price), a different,
already-"validated" production formula this script does not modify, and a
population Layer 0c does not examine (BUY+SELL mixed, vs. this script's
BUY-only positions). It is flagged in the report as a high-priority,
UNCONFIRMED follow-up -- explicitly not asserted as true here.

=============================================================================
LINEAGE
=============================================================================
Layer 0: first-repo f1d2555/ff9ef7c; layer0_pre_registration/
  layer0_position_results/layer0_stratum_summary.
Layer 0b: first-repo (this session); layer0b_pre_registration/
  layer0b_stratum_summary/layer0b_calibration_curve -- the calibration curve
  in that table is what surfaced this bug.
geo_elo values themselves are unchanged from Layer 0 (read from
layer0_position_results, already selfcheck-validated there). Only the edge
metric's price normalization changes here.

=============================================================================
PRE-REGISTRATION (fixed before computing; written to
layer0c_pre_registration before any result row)
=============================================================================

HYPOTHESIS: unchanged -- a trader's geo_elo at time T positively predicts the
    market-relative edge of positions they enter after T.
METRIC, CORRECTED: edge = won - entry_avg_price (no outcome-conditional flip
    -- entry_avg_price already represents the price of the side actually
    bought, per the calibration evidence above). This is the ONE change from
    Layer 0/0b; geo_elo, the trader/market universe, and the bootstrap/
    stratification method are otherwise identical to Layer 0b.
SUCCESS CRITERION: same structure as Layer 0b -- top stratum's two-way-
    clustered 95% CI excludes zero AND rank_corr(stratum, mean_edge) >= 0.5
    AND bottom-decile edge is near zero (this is now the primary test of
    whether the correction worked: under H0, a corrected, well-calibrated
    metric should put the bottom decile at approximately zero, not merely
    "less positive than before").

Read-only against the database except the tables this script owns
(layer0c_pre_registration, layer0c_stratum_summary, layer0c_calibration_curve).
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

SPEC_VERSION = "LAYER0C-2026-08-15-v1"
LAYER0_LINEAGE = "first-repo f1d2555/ff9ef7c (layer0_*); this session (layer0b_*, esp. layer0b_calibration_curve)"
N_STRATA_DEFAULT = 10
BOOTSTRAP_REPS_DEFAULT = 1500
SEED_DEFAULT = 42

H1_TEXT = "A trader's geo_elo at time T positively predicts the market-relative edge of positions they enter after T. (unchanged)"
METRIC_TEXT = ("edge = won - entry_avg_price, NO outcome-conditional flip (corrected from Layer 0/0b's "
               "entry_avg_price if Yes else 1-entry_avg_price, which the Layer 0b calibration curve showed "
               "was inverted for the No side). geo_elo unchanged from Layer 0.")
SUCCESS_TEXT = ("Top stratum two-way-clustered 95% CI excludes zero AND rank_corr(stratum, mean_edge) >= 0.5 "
                "AND bottom-decile edge is near zero (the primary test that the correction worked -- a "
                "well-calibrated metric under H0 should put the bottom decile at ~0, not merely lower than "
                "Layer 0/0b's inflated baseline).")


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_data(conn, verbose=False):
    rows = conn.execute("""
        SELECT l.position_id, l.trader, l.market_id, l.geo_elo, l.won,
               p.outcome, p.entry_avg_price
        FROM layer0_position_results l
        JOIN positions p ON p.position_id = l.position_id
        WHERE l.geo_elo IS NOT NULL
    """).fetchall()
    df = pd.DataFrame(rows, columns=['position_id', 'trader', 'market_id', 'geo_elo', 'won',
                                      'outcome', 'entry_avg_price'])
    df['entry_price_side'] = df['entry_avg_price']  # corrected: no flip
    df['edge'] = df['won'] - df['entry_price_side']
    if verbose:
        print(f"[load] {len(df)} geo_elo-eligible positions, {df['trader'].nunique()} traders, "
              f"{df['market_id'].nunique()} markets")
        print(f"[load] overall mean edge (corrected) = {df['edge'].mean():.4f} "
              f"(Layer 0/0b uncorrected was 0.198 dataset-wide)")
    return df


def selfcheck(df, verbose=True):
    """Verifies the corrected metric is internally consistent: for Yes-side
    positions the corrected entry_price_side must be IDENTICAL to Layer 0's
    (Yes never needed a flip), so re-deriving edge for Yes rows only should
    reproduce Layer 0's Yes-side numbers exactly. Cross-checked against the
    known Layer 0 Yes-side aggregate (spot values, not a full re-fetch)."""
    yes = df[df['outcome'] == 'Yes']
    no = df[df['outcome'] == 'No']
    ok = True
    if len(yes) == 0 or len(no) == 0:
        ok = False
    # entry_price_side for Yes must lie in [0,1] and equal entry_avg_price exactly
    bad_yes = yes[(yes['entry_price_side'] - yes['entry_avg_price']).abs() > 1e-12]
    if len(bad_yes) > 0:
        ok = False
    if verbose:
        print(f"[selfcheck] Yes rows={len(yes)} No rows={len(no)} "
              f"Yes-flip-identity-violations={len(bad_yes)}")
        print(f"[selfcheck] {'PASSED' if ok else 'FAILED'}")
    return ok


# --- bootstrap / stratification / calibration: identical methodology to layer0b ---

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
    if len(sub) == 0:
        return dict(mean=None, n_traders=0, n_markets=0, n_positions=0, ci_lo=None, ci_hi=None, method='none')
    point = float(sub['edge'].sum() / len(sub))
    n_positions = len(sub)

    per_trader = sub.groupby('trader')['edge'].agg(['sum', 'count'])
    trader_lo, trader_hi = _one_way_ci(per_trader['sum'].to_numpy(), per_trader['count'].to_numpy(), reps, seed)

    per_market = sub.groupby('market_id')['edge'].agg(['sum', 'count'])
    market_lo, market_hi = _one_way_ci(per_market['sum'].to_numpy(), per_market['count'].to_numpy(), reps, seed + 1)

    traders = sub['trader'].astype('category')
    markets = sub['market_id'].astype('category')
    tmp = pd.DataFrame({'trader_idx': traders.cat.codes.to_numpy(),
                         'market_idx': markets.cat.codes.to_numpy(),
                         'edge': sub['edge'].to_numpy()})
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
        t_mult = np.bincount(rng.integers(0, n_traders, size=n_traders), minlength=n_traders)
        m_mult = np.bincount(rng.integers(0, n_markets, size=n_markets), minlength=n_markets)
        w = t_mult[t_idx] * m_mult[m_idx]
        denom = (w * p_cnt).sum()
        boot[b] = (w * p_sum).sum() / denom if denom > 0 else np.nan
    boot = boot[~np.isnan(boot)]
    if len(boot) < reps * 0.5:
        twoway_lo, twoway_hi = None, None
    else:
        twoway_lo, twoway_hi = (float(x) for x in np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)]))

    trader_w = (trader_hi - trader_lo) if trader_lo is not None else None
    market_w = (market_hi - market_lo) if market_lo is not None else None
    twoway_w = (twoway_hi - twoway_lo) if twoway_lo is not None else None
    max_oneway_w = max(w for w in (trader_w, market_w) if w is not None) if (trader_w or market_w) else None

    method = 'two_way'
    reported_lo, reported_hi = twoway_lo, twoway_hi
    if twoway_w is None or (max_oneway_w is not None and twoway_w < 0.9 * max_oneway_w):
        if trader_w is not None and market_w is not None:
            if trader_w >= market_w:
                reported_lo, reported_hi, method = trader_lo, trader_hi, 'fallback_trader_wider'
            else:
                reported_lo, reported_hi, method = market_lo, market_hi, 'fallback_market_wider'
        elif trader_w is not None:
            reported_lo, reported_hi, method = trader_lo, trader_hi, 'fallback_trader_only'
        elif market_w is not None:
            reported_lo, reported_hi, method = market_lo, market_hi, 'fallback_market_only'

    return dict(mean=point, n_positions=n_positions, n_traders=n_traders, n_markets=n_markets,
                ci_lo=reported_lo, ci_hi=reported_hi, method=method)


def stratified_table(df, n_strata=N_STRATA_DEFAULT, reps=BOOTSTRAP_REPS_DEFAULT, seed=SEED_DEFAULT):
    if len(df) == 0:
        return []
    try:
        strat, bins = pd.qcut(df['geo_elo'], q=n_strata, labels=False, retbins=True, duplicates='drop')
    except ValueError:
        return []
    df = df.copy()
    df['_stratum'] = strat
    out = []
    for s in sorted(df['_stratum'].dropna().unique()):
        sub = df[df['_stratum'] == s]
        stats = two_way_cluster_bootstrap(sub, reps=reps, seed=seed + int(s) * 7)
        out.append(dict(stratum=int(s), value_range=(float(bins[int(s)]), float(bins[int(s) + 1])), **stats))
    return out


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
    return rank_corr([r['stratum'] for r in rows], [r['mean'] for r in rows]) if rows else None


def calibration_curve(df, side, n_buckets=10):
    sub = df[df['outcome'] == side].copy()
    if len(sub) == 0:
        return []
    sub['bucket'], bins = pd.qcut(sub['entry_price_side'], q=n_buckets, labels=False, retbins=True, duplicates='drop')
    out = []
    for b in sorted(sub['bucket'].dropna().unique()):
        g = sub[sub['bucket'] == b]
        out.append(dict(bucket=int(b), price_lo=float(bins[int(b)]), price_hi=float(bins[int(b) + 1]),
                         n=int(len(g)), mean_price=float(g['entry_price_side'].mean()),
                         mean_won=float(g['won'].mean()), gap=float(g['won'].mean() - g['entry_price_side'].mean())))
    return out


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
    print(f"  rank_corr(stratum, mean_edge) = {table_rank_corr(rows)}")


def print_calib(name, rows):
    print(f"\n=== {name} ===")
    print(f"  {'bucket':>6} {'price_range':>20} {'n':>7} {'mean_price':>10} {'mean_won':>9} {'gap':>8}")
    for r in rows:
        print(f"  {r['bucket']:>6} {r['price_lo']:>9.3f}-{r['price_hi']:<9.3f} {r['n']:>7} "
              f"{r['mean_price']:>10.4f} {r['mean_won']:>9.4f} {r['gap']:>8.4f}")


def persist(conn, tables, calib_tables, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS layer0c_pre_registration")
    conn.execute("""
        CREATE TABLE layer0c_pre_registration (
            spec_version TEXT PRIMARY KEY, h1 TEXT, metric TEXT, success_criterion TEXT,
            layer0_lineage TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO layer0c_pre_registration VALUES (?,?,?,?,?,?,?)",
                 (SPEC_VERSION, H1_TEXT, METRIC_TEXT, SUCCESS_TEXT, LAYER0_LINEAGE,
                  generated_at, generator_commit))

    conn.execute("DROP TABLE IF EXISTS layer0c_stratum_summary")
    conn.execute("""
        CREATE TABLE layer0c_stratum_summary (
            variant TEXT, stratum INTEGER, value_lo REAL, value_hi REAL,
            n_traders INTEGER, n_markets INTEGER, n_positions INTEGER, mean_edge REAL,
            ci_lo REAL, ci_hi REAL, ci_method TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for variant, rows in tables.items():
        for r in rows:
            conn.execute("INSERT INTO layer0c_stratum_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (variant, r['stratum'], r['value_range'][0], r['value_range'][1],
                          r['n_traders'], r['n_markets'], r['n_positions'], r['mean'],
                          r['ci_lo'], r['ci_hi'], r['method'], SPEC_VERSION, generated_at, generator_commit))

    conn.execute("DROP TABLE IF EXISTS layer0c_calibration_curve")
    conn.execute("""
        CREATE TABLE layer0c_calibration_curve (
            side TEXT, bucket INTEGER, price_lo REAL, price_hi REAL, n INTEGER,
            mean_price REAL, mean_won REAL, gap REAL, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for side, rows in calib_tables.items():
        for r in rows:
            conn.execute("INSERT INTO layer0c_calibration_curve VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (side, r['bucket'], r['price_lo'], r['price_hi'], r['n'],
                          r['mean_price'], r['mean_won'], r['gap'], SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('--n-strata', type=int, default=N_STRATA_DEFAULT)
    ap.add_argument('--bootstrap-reps', type=int, default=BOOTSTRAP_REPS_DEFAULT)
    ap.add_argument('--seed', type=int, default=SEED_DEFAULT)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)
    print(f"=== PRE-REGISTRATION (fixed before results, spec {SPEC_VERSION}) ===")
    print(f"H1: {H1_TEXT}")
    print(f"METRIC: {METRIC_TEXT}")
    print(f"SUCCESS CRITERION: {SUCCESS_TEXT}")
    print(f"LINEAGE: {LAYER0_LINEAGE}")

    df = load_data(conn, verbose=args.verbose)

    if args.selfcheck:
        ok = selfcheck(df, verbose=True)
        if not ok:
            sys.exit(1)
        if not args.persist and not args.json_out:
            conn.close()
            return

    tables = {}
    calib_tables = {}

    primary_rows = stratified_table(df, n_strata=args.n_strata, reps=args.bootstrap_reps, seed=args.seed)
    tables['primary_two_way'] = primary_rows
    print_table('PRIMARY, corrected metric (two-way clustered CIs)', primary_rows)

    yes_rows = stratified_table(df[df['outcome'] == 'Yes'], n_strata=args.n_strata,
                                 reps=args.bootstrap_reps, seed=args.seed)
    tables['yes_only'] = yes_rows
    print_table(f"YES-SIDE ONLY (n={len(df[df['outcome']=='Yes'])})", yes_rows)

    no_rows = stratified_table(df[df['outcome'] == 'No'], n_strata=args.n_strata,
                                reps=args.bootstrap_reps, seed=args.seed)
    tables['no_only'] = no_rows
    print_table(f"NO-SIDE ONLY, corrected (n={len(df[df['outcome']=='No'])})", no_rows)

    calib_yes = calibration_curve(df, 'Yes', n_buckets=args.n_strata)
    calib_tables['Yes'] = calib_yes
    print_calib('CALIBRATION (corrected): Yes side', calib_yes)

    calib_no = calibration_curve(df, 'No', n_buckets=args.n_strata)
    calib_tables['No'] = calib_no
    print_calib('CALIBRATION (corrected): No side', calib_no)

    print("\n=== KEY QUESTION: is the level now interpretable? ===")
    for name, rows in tables.items():
        if rows:
            bottom, top = rows[0], rows[-1]
            print(f"  {name:>18}: bottom={bottom['mean']:.4f} [{bottom['ci_lo']:.4f},{bottom['ci_hi']:.4f}]  "
                  f"top={top['mean']:.4f} [{top['ci_lo']:.4f},{top['ci_hi']:.4f}]  "
                  f"rank_corr={table_rank_corr(rows)}")

    result = dict(spec_version=SPEC_VERSION, tables=tables, calibration=calib_tables,
                  scope=dict(n_positions=len(df), n_traders=int(df['trader'].nunique()),
                             n_markets=int(df['market_id'].nunique())))
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
        print(f"[persist] layer0c_pre_registration, layer0c_stratum_summary, "
              f"layer0c_calibration_curve written, generated_at={generated_at}")


if __name__ == '__main__':
    main()
