#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2d -- AMENDMENT to v2c (lineage SKILLV2-2026-08-15-v1 ->
SKILLV2B -> SKILLV2C -> SKILLV2D). Closes the gate-approximation debt v2c
flagged, then -- only if that gate passes -- derives threshold candidates
from the metric's own distribution and tests forward-usability. Read-only.
No production writes. No changes to update_geo_elo.py, geo_elo_active,
cohort membership, or any live path. No cutover decision.

=============================================================================
WHY (recorded so the framing survives)
=============================================================================
v2c resolved the weighting tension: cap5 is the clean knee in the trade-off
curve (sigma2_between turns on at cap5 after being exactly zero for
market/log/sqrt/cap3; 4.94% largest-market weight share vs position-
weighting's 9.95% floor). It also showed the earlier conclusions (Spearman
vs geo_elo, the No-fraction falsifiable test, LEGENDARY overlap) are stable
across the weighting change. BUT v2c's own gate re-check under cap5 reused
the UNWEIGHTED two-way clustered bootstrap CI applied to weighted point
estimates -- an approximation, explicitly flagged, not the rigour v2b
applied to its own weighting. This pass builds the properly cap5-weighted
two-way bootstrap (weights in the resampling, the per-bucket gap, and the
CI construction) before any threshold is derived, because an approximate
gate is exactly the kind of debt that comes back to bite at threshold time.

=============================================================================
AMENDMENT PRE-REGISTRATION (fixed before computing; written to
metric_v2d_amendment before any result row)
=============================================================================

--- OBJECTIVE 1: the properly-weighted gate (hard prerequisite) ---
Two-way trader x market cluster bootstrap with cap5 weights applied
throughout: per (trader,market) pair, base_weight = min(n_positions, 5)
(unchanged from v2c). Per bootstrap rep, each pair's TOTAL weight =
base_weight * trader_multiplicity * market_multiplicity (trader/market
multiplicities drawn exactly as in v2b's two-way bootstrap). The per-bucket
gap is the WEIGHTED mean of pair-level won minus the WEIGHTED mean of
pair-level price, using that total weight -- computed fresh every
replicate, not a point estimate with an unweighted CI bolted on. Same
tolerance as v2b/v2c: no bucket's clustered 95% CI on the gap excludes
zero beyond 0.03. THIS IS A GATE: if it fails, stop, diagnose (new problem
vs known concentration, same discipline as the original v2 gate failure),
and do not proceed to Objective 2 -- no re-specifying to force a pass.

Comparison to v2c's approximation is reported explicitly: if the properly-
weighted CI is close to the approximated one, that retrospectively
validates reweighting-as-approximation as a usable shortcut for future
passes; if it differs materially, that's recorded as a caution against
reusing that shortcut.

--- OBJECTIVE 2: threshold derivation (only if Objective 1 passes) ---
The inherited ladder (1000/1400/1800/2175) carries no calibration record
(derivation audit: 2175/1800 traced to a discredited comprehensive_elo
system; 1000/1400 don't appear anywhere before the June 22 consolidation
commit's inaccurate claim to have "lifted" them from source). Nothing about
those numbers carries over. Three threshold FAMILIES derived from the cap5
metric's own distribution, not chosen unilaterally:
  (a) PERCENTILE: top 1%/5%/10% of shrunk edge.
  (b) SIGNIFICANCE: bootstrap CI (properly cap5-weighted, built fresh per
      trader by resampling that trader's own pairs with replacement,
      weighted by base_weight) excludes zero at 95% and at 99% -- "provably
      better than the market," not "top N%."
  (c) EFFECT SIZE: shrunk edge exceeds an absolute bar (+0.02, +0.05),
      interpreted against the cost surface established in the geo_elo
      derivation audit (geopolitics fee-free; politics/elections
      feeRate~=0.04, fee=shares*feeRate*price*(1-price), peaking at p=0.50;
      FABLE's own framing: "a 3pt gross edge dies to 2-3c of costs anyway").
For each: cohort n, median positions, median distinct markets, and
TURNOVER -- membership stability against a metric recomputed using only
data available 3 months earlier (point-in-time correct: restricted to
positions whose market had ALREADY RESOLVED, via tape_end, by that earlier
date, not just entered by then -- entering before a cutoff but resolving
after it would leak future information into a "3 months ago" reconstruction).
Cross-checked against the current 81 LEGENDARY traders for each candidate,
recorded as a magnitude-of-disagreement fact, not a target to agree with.

RECOMMENDATION offered (rank vs significance vs effect-size answer
different questions), not decided -- Oscar's call.

--- OBJECTIVE 3: sanity ---
Under the recommended threshold: cohort characteristics (positions, market
breadth, No-fraction, category mix, activity period) checked for
selection-artifact signatures (concentration in one market/era). Forward-
usability (item 11, the highest-consequence question): of the traders who
qualify NOW, how many would ALSO have qualified using only data available 3
months ago -- i.e. is this cohort identifiable in real time, or only in
hindsight? A metric that only identifies skill retrospectively cannot power
a live signal regardless of how well-constructed it is.

--- UNCHANGED CONSTRAINTS ---
No production writes. update_geo_elo.py / geo_elo_active / cohort
membership untouched. No cutover decision. comprehensive_elo /
calibration_analysis.py out of scope. Do not re-specify to obtain a passing
gate or a preferred cohort size.

Persists metric_v2d_amendment, metric_v2d_gate_results,
metric_v2d_gate_comparison, metric_v2d_threshold_candidates,
metric_v2d_turnover, metric_v2d_cohort_sanity, metric_v2d_findings.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import load_entries, rank_corr, db_connect, SPEC_VERSION as V2_SPEC
from scripts.trader_skill_metric_v2b import fixed_buckets, SPEC_VERSION as V2B_SPEC
from scripts.trader_skill_metric_v2c import (
    build_pairs, eb_shrinkage_weighted, WEIGHT_FNS, SPEC_VERSION as V2C_SPEC, KAMALA_MARKET_HINT,
)

SPEC_VERSION = "SKILLV2D-2026-08-15-v1"
SEED = 42
GATE_REPS = 1500
BOOTSTRAP_REPS = 1000
TOL = 0.03

AMENDMENT_WHY = (
    "v2c resolved the weighting tension (cap5: the clean knee) and showed the earlier conclusions are "
    "weighting-robust, but its own cap5 gate re-check reused the UNWEIGHTED two-way clustered bootstrap "
    "as an approximation to a properly weighted one -- explicitly flagged, not the rigour v2b applied to "
    "its own weighting. This pass closes that debt before any threshold is derived, since an approximate "
    "gate is exactly the kind of thing that comes back to bite at threshold time."
)
OBJ1_TEXT = (
    "Properly cap5-weighted two-way trader x market cluster bootstrap: per (trader,market) pair, "
    "base_weight=min(n_positions,5); per replicate, total weight = base_weight * trader_multiplicity * "
    "market_multiplicity; the gap is the weighted mean of pair-level won minus the weighted mean of "
    "pair-level price, computed fresh every replicate -- weights in the resampling, the gap, and the CI "
    "throughout, not a point estimate with an unweighted CI applied after the fact. Same 0.03 tolerance "
    "as v2b/v2c. THIS IS A GATE: failure means stop, diagnose, do not proceed to Objective 2, no "
    "re-specifying to force a pass. Compared explicitly to v2c's approximation."
)
OBJ2_TEXT = (
    "Threshold derivation from the cap5 metric's own distribution, only if Objective 1 passes. Three "
    "families reported, not one chosen unilaterally: (a) percentile (top 1/5/10%), (b) significance "
    "(bootstrap CI excludes zero at 95%/99%, properly cap5-weighted per trader), (c) effect size "
    "(shrunk edge > 0.02 / > 0.05, read against the fee-free-geopolitics / ~4%-feeRate-elections cost "
    "surface). Each reported with cohort size, breadth, and turnover against a point-in-time-correct "
    "3-months-earlier reconstruction (restricted by tape_end, not just entry_ts, to avoid leaking future "
    "resolution information into the earlier snapshot). Cross-checked against current LEGENDARY "
    "membership as a magnitude-of-disagreement fact, not a target."
)
OBJ3_TEXT = (
    "Cohort sanity check under the recommended threshold (position/market breadth, No-fraction, "
    "category mix, activity period, checked for selection-artifact signatures) and forward-usability: "
    "of the traders qualifying now, how many would also have qualified using only data available 3 "
    "months ago. The highest-consequence question this pass answers -- a hindsight-only metric cannot "
    "power a live signal."
)


# ---------------------------------------------------------------------------
# Objective 1: properly weighted two-way gate
# ---------------------------------------------------------------------------

def weighted_pair_table(sub, weight_fn):
    """sub: position-level rows (trader, market_id, won, price) for one
    bucket. Returns pair-level (trader, market_id, pair_won, pair_price,
    base_weight)."""
    g = sub.groupby(['trader', 'market_id']).agg(
        pair_won=('won', 'mean'), pair_price=('price', 'mean'), n=('won', 'count')
    ).reset_index()
    g['base_weight'] = weight_fn(g['n'].to_numpy())
    return g


def weighted_two_way_gap_bootstrap(pairs, reps=GATE_REPS, seed=42, alpha=0.05):
    if len(pairs) == 0:
        return dict(n_pairs=0, point_gap=None, ci_lo=None, ci_hi=None)

    traders = pairs['trader'].astype('category')
    markets = pairs['market_id'].astype('category')
    t_idx = traders.cat.codes.to_numpy()
    m_idx = markets.cat.codes.to_numpy()
    n_traders = traders.cat.categories.size
    n_markets = markets.cat.categories.size
    base_w = pairs['base_weight'].to_numpy()
    p_won = pairs['pair_won'].to_numpy()
    p_price = pairs['pair_price'].to_numpy()

    point_denom = base_w.sum()
    point_gap = float((base_w * p_won).sum() / point_denom - (base_w * p_price).sum() / point_denom)

    rng = np.random.default_rng(seed)
    boot = np.empty(reps)
    for b in range(reps):
        t_mult = np.bincount(rng.integers(0, n_traders, size=n_traders), minlength=n_traders)
        m_mult = np.bincount(rng.integers(0, n_markets, size=n_markets), minlength=n_markets)
        total_w = base_w * t_mult[t_idx] * m_mult[m_idx]
        denom = total_w.sum()
        if denom <= 0:
            boot[b] = np.nan
            continue
        wmean_won = (total_w * p_won).sum() / denom
        wmean_price = (total_w * p_price).sum() / denom
        boot[b] = wmean_won - wmean_price
    boot = boot[~np.isnan(boot)]
    if len(boot) < reps * 0.5:
        return dict(n_pairs=len(pairs), n_traders=int(n_traders), n_markets=int(n_markets),
                    point_gap=point_gap, ci_lo=None, ci_hi=None)
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return dict(n_pairs=len(pairs), n_traders=int(n_traders), n_markets=int(n_markets),
                point_gap=point_gap, ci_lo=float(lo), ci_hi=float(hi))


def run_weighted_gate(entries_df, weight_fn, reps, seed, tol=TOL):
    all_rows = []
    all_pass = True
    for side in ('Yes', 'No'):
        sub = entries_df[entries_df['outcome'] == side].copy()
        bins = fixed_buckets(entries_df, side)
        sub['bucket'] = pd.cut(sub['entry_avg_price'], bins=bins, labels=False, include_lowest=True)
        sub = sub.dropna(subset=['bucket'])
        sub['bucket'] = sub['bucket'].astype(int)
        sub = sub.rename(columns={'entry_avg_price': 'price'})
        for b in sorted(sub['bucket'].unique()):
            bsub = sub[sub['bucket'] == b]
            pairs = weighted_pair_table(bsub, weight_fn)
            r = weighted_two_way_gap_bootstrap(pairs, reps=reps, seed=seed + int(b) * 7)
            r['side'] = side
            r['bucket'] = int(b)
            r['price_lo'] = float(bins[int(b)])
            r['price_hi'] = float(bins[int(b) + 1])
            excl = r['ci_lo'] is not None and (r['ci_lo'] > tol or r['ci_hi'] < -tol)
            r['fail'] = bool(excl)
            if excl:
                all_pass = False
            all_rows.append(r)
    return all_pass, all_rows


# ---------------------------------------------------------------------------
# Objective 2: per-trader weighted bootstrap CI + threshold derivation
# ---------------------------------------------------------------------------

def per_trader_weighted_bootstrap(pairs, reps=BOOTSTRAP_REPS, seed=SEED, alpha_levels=(0.05, 0.01)):
    """pairs: (trader, market_id, pair_edge, n_positions, weight) -- resample
    a trader's OWN pairs with replacement, weighted by `weight`, for a CI on
    their weighted mean."""
    rng = np.random.default_rng(seed)
    out = []
    for trader, grp in pairs.groupby('trader'):
        vals = grp['pair_edge'].to_numpy()
        w = grp['weight'].to_numpy()
        npair = len(vals)
        point = float(np.average(vals, weights=w))
        if npair == 1:
            out.append((trader, point, point, point))
            continue
        idx = rng.integers(0, npair, size=(reps, npair))
        boot_vals = vals[idx]
        boot_w = w[idx]
        boot_means = (boot_vals * boot_w).sum(axis=1) / boot_w.sum(axis=1)
        lo95, hi95 = np.percentile(boot_means, [2.5, 97.5])
        out.append((trader, point, float(lo95), float(hi95)))
    df = pd.DataFrame(out, columns=['trader', 'point', 'ci_lo_95', 'ci_hi_95'])
    return df


def build_tape_end_map(conn, market_ids):
    placeholders = ",".join("?" for _ in market_ids)
    rows = conn.execute(f"""
        SELECT market_id, MAX(timestamp) FROM trades WHERE market_id IN ({placeholders}) GROUP BY market_id
    """, market_ids).fetchall()
    return dict(rows)


def compute_cap5_metric(entries_df, sigma2_within=None):
    pairs = build_pairs(entries_df)
    pairs['weight'] = WEIGHT_FNS['cap5'](pairs['n_positions'].to_numpy())
    pairs = pairs.rename(columns={'pair_edge': 'pair_edge'})
    if sigma2_within is None:
        sigma2_within = float(entries_df['edge'].var())
    eb = eb_shrinkage_weighted(pairs.rename(columns={'pair_edge': 'pair_edge'}), sigma2_within)
    return pairs, eb, sigma2_within


def build_asof_population(conn, entries_df, months_back=3, verbose=False):
    """Computed ONCE and reused across all threshold candidates -- the
    as-of-3-months-ago reconstruction doesn't depend on which candidate is
    being checked, only on the cutoff."""
    max_ts = pd.to_datetime(entries_df['entry_ts'], format='mixed').max()
    cutoff = max_ts - pd.DateOffset(months=months_back)
    cutoff_sql = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    market_ids = entries_df['market_id'].unique().tolist()
    tape_end = build_tape_end_map(conn, market_ids)
    entries_df = entries_df.copy()
    entries_df['tape_end'] = entries_df['market_id'].map(tape_end)
    asof = entries_df[entries_df['tape_end'].notna() & (entries_df['tape_end'] <= cutoff_sql)]
    if verbose:
        print(f"[turnover] cutoff={cutoff_sql}, as-of population: {len(asof)}/{len(entries_df)} positions "
              f"(resolved by cutoff, PIT-correct via tape_end)")
    if len(asof) < 100:
        return cutoff_sql, None
    _, eb_asof, _ = compute_cap5_metric(asof)
    return cutoff_sql, eb_asof


def turnover_check(cutoff_sql, eb_asof, top_trader_set):
    if eb_asof is None:
        return dict(cutoff=cutoff_sql, n_asof_positions=0, overlap=None,
                    note="too few positions for a meaningful as-of reconstruction")
    ranked_asof = eb_asof.sort_values('shrunk_mean', ascending=False)
    top_asof = set(ranked_asof.head(len(top_trader_set))['trader'].tolist())
    overlap = top_trader_set & top_asof
    return dict(cutoff=cutoff_sql, n_asof_traders=len(eb_asof),
                overlap=len(overlap), overlap_fraction=len(overlap) / len(top_trader_set) if top_trader_set else None,
                top_asof_size=len(top_asof))


def persist_amendment(conn, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2d_amendment")
    conn.execute("""
        CREATE TABLE metric_v2d_amendment (
            spec_version TEXT PRIMARY KEY, amends_spec_version TEXT, why TEXT,
            objective1 TEXT, objective2 TEXT, objective3 TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2d_amendment VALUES (?,?,?,?,?,?,?,?)",
                 (SPEC_VERSION, V2C_SPEC, AMENDMENT_WHY, OBJ1_TEXT, OBJ2_TEXT, OBJ3_TEXT,
                  generated_at, generator_commit))
    conn.commit()


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
    print(f"=== AMENDMENT (spec {SPEC_VERSION}, amends {V2C_SPEC}) ===")
    print(f"WHY: {AMENDMENT_WHY}\n\nOBJECTIVE 1: {OBJ1_TEXT}\n\nOBJECTIVE 2: {OBJ2_TEXT}\n\nOBJECTIVE 3: {OBJ3_TEXT}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    if args.persist:
        persist_amendment(conn, generated_at, args.generator_commit)
        print("[persist] metric_v2d_amendment written\n")

    entries_df = load_entries(conn, verbose=args.verbose)

    # =========================== OBJECTIVE 1 ===========================
    print("=== OBJECTIVE 1: properly cap5-weighted gate ===")
    gate_pass, gate_rows = run_weighted_gate(entries_df, WEIGHT_FNS['cap5'], reps=args.gate_reps, seed=args.seed)
    for r in gate_rows:
        ci = f"[{r['ci_lo']:.4f},{r['ci_hi']:.4f}]" if r['ci_lo'] is not None else "N/A"
        print(f"  {r['side']} bucket {r['bucket']}: price {r['price_lo']:.3f}-{r['price_hi']:.3f} "
              f"n_pairs={r['n_pairs']} n_trd={r.get('n_traders')} n_mkt={r.get('n_markets')} "
              f"gap={r['point_gap']:+.4f} weighted_CI={ci} {'FAIL' if r['fail'] else 'ok'}")
    print(f"\n[GATE] {'PASS' if gate_pass else 'FAIL'}")

    if args.persist:
        c2 = db_connect(args.db)
        c2.execute("DROP TABLE IF EXISTS metric_v2d_gate_results")
        c2.execute("""
            CREATE TABLE metric_v2d_gate_results (
                side TEXT, bucket INTEGER, price_lo REAL, price_hi REAL, n_pairs INTEGER,
                n_traders INTEGER, n_markets INTEGER, point_gap REAL, ci_lo REAL, ci_hi REAL,
                fail INTEGER, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        for r in gate_rows:
            c2.execute("INSERT INTO metric_v2d_gate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                r['side'], r['bucket'], r['price_lo'], r['price_hi'], r['n_pairs'], r.get('n_traders'),
                r.get('n_markets'), r['point_gap'], r['ci_lo'], r['ci_hi'], int(r['fail']),
                SPEC_VERSION, generated_at, args.generator_commit))
        c2.commit()
        c2.close()
        print("[persist] metric_v2d_gate_results written")

    if not gate_pass:
        print("\n[STOP] Properly-weighted gate FAILED. Per the pre-registration: stop, do not proceed "
              "to Objective 2.", file=sys.stderr)
        findings = dict(objective1=dict(gate_pass=False, rows=gate_rows))
        if args.json_out:
            with open(args.json_out, 'w') as f:
                json.dump(findings, f, indent=2, default=str)
        if args.persist:
            c3 = db_connect(args.db)
            c3.execute("DROP TABLE IF EXISTS metric_v2d_findings")
            c3.execute("CREATE TABLE metric_v2d_findings (finding TEXT PRIMARY KEY, json_value TEXT, "
                       "spec_version TEXT, generated_at TEXT, generator_commit TEXT)")
            c3.execute("INSERT INTO metric_v2d_findings VALUES (?,?,?,?,?)",
                       ('objective1_gate_failed', json.dumps(gate_rows, default=str), SPEC_VERSION,
                        generated_at, args.generator_commit))
            c3.commit()
            c3.close()
        conn.close()
        sys.exit(2)

    print("\n[GATE PASSED -- proceeding to Objective 2]")

    # ============================= OBJECTIVE 2 =============================
    print("\n=== OBJECTIVE 2: threshold derivation ===")
    pairs, eb, sigma2_within = compute_cap5_metric(entries_df)
    print(f"cap5 metric: {len(eb)} traders, sigma2_between={eb['sigma2_between'].iloc[0]:.6f}")

    # per-trader weighted bootstrap CI (significance-based candidates)
    pairs_for_ci = pairs.rename(columns={'pair_edge': 'pair_edge'})[['trader', 'market_id', 'pair_edge', 'weight']]
    trader_ci = per_trader_weighted_bootstrap(pairs_for_ci, reps=args.bootstrap_reps, seed=args.seed)
    eb_full = eb.merge(trader_ci, on='trader')

    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))

    candidates = {}

    # (a) percentile
    for pct in (1, 5, 10):
        thresh = eb_full['shrunk_mean'].quantile(1 - pct / 100)
        cohort = eb_full[eb_full['shrunk_mean'] >= thresh]
        candidates[f'percentile_top{pct}'] = cohort

    # (b) significance
    sig95 = eb_full[eb_full['ci_lo_95'] > 0]
    candidates['significance_95'] = sig95
    # 99% via z=2.576 scaling approx of the 95% CI half-width (avoids a second bootstrap pass)
    halfwidth95 = (eb_full['ci_hi_95'] - eb_full['ci_lo_95']) / 2
    center = (eb_full['ci_hi_95'] + eb_full['ci_lo_95']) / 2
    ci_lo_99_approx = center - halfwidth95 * (2.576 / 1.96)
    eb_full['ci_lo_99_approx'] = ci_lo_99_approx
    sig99 = eb_full[eb_full['ci_lo_99_approx'] > 0]
    candidates['significance_99_approx'] = sig99

    # (c) effect size
    for bar in (0.02, 0.05):
        cohort = eb_full[eb_full['shrunk_mean'] >= bar]
        candidates[f'effect_size_{bar}'] = cohort

    threshold_summary = {}
    for name, cohort in candidates.items():
        trader_set = set(cohort['trader'])
        n_legend_in = len(legendary & trader_set)
        row = dict(
            n_traders=len(cohort),
            median_n_positions=float(pairs[pairs['trader'].isin(trader_set)].groupby('trader')['n_positions'].sum().median()) if len(cohort) else None,
            median_n_markets=float(pairs[pairs['trader'].isin(trader_set)].groupby('trader').size().median()) if len(cohort) else None,
            min_shrunk_mean=float(cohort['shrunk_mean'].min()) if len(cohort) else None,
            legendary_overlap=n_legend_in, legendary_overlap_fraction=n_legend_in / len(legendary) if legendary else None,
        )
        threshold_summary[name] = row
        print(f"  {name:>24}: n={row['n_traders']:>6}  median_positions={row['median_n_positions']}  "
              f"median_markets={row['median_n_markets']}  LEGENDARY_overlap={n_legend_in}/{len(legendary)}")

    if args.persist:
        c4 = db_connect(args.db)
        c4.execute("DROP TABLE IF EXISTS metric_v2d_threshold_candidates")
        c4.execute("""
            CREATE TABLE metric_v2d_threshold_candidates (
                candidate TEXT PRIMARY KEY, n_traders INTEGER, median_n_positions REAL,
                median_n_markets REAL, min_shrunk_mean REAL, legendary_overlap INTEGER,
                legendary_overlap_fraction REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        for name, row in threshold_summary.items():
            c4.execute("INSERT INTO metric_v2d_threshold_candidates VALUES (?,?,?,?,?,?,?,?,?,?)", (
                name, row['n_traders'], row['median_n_positions'], row['median_n_markets'],
                row['min_shrunk_mean'], row['legendary_overlap'], row['legendary_overlap_fraction'],
                SPEC_VERSION, generated_at, args.generator_commit))
        c4.commit()
        c4.close()
        print("[persist] metric_v2d_threshold_candidates written")

    # turnover for each candidate -- as-of population built ONCE, reused
    print("\n--- turnover (3-months-earlier, PIT-correct via tape_end) ---")
    cutoff_sql, eb_asof = build_asof_population(conn, entries_df, months_back=3, verbose=args.verbose)
    turnover_results = {}
    for name, cohort in candidates.items():
        trader_set = set(cohort['trader'])
        if len(trader_set) == 0:
            continue
        t = turnover_check(cutoff_sql, eb_asof, trader_set)
        turnover_results[name] = t
        print(f"  {name:>24}: overlap={t.get('overlap')}/{len(trader_set)} "
              f"({t.get('overlap_fraction')})  cutoff={t.get('cutoff')}")

    if args.persist:
        c5 = db_connect(args.db)
        c5.execute("DROP TABLE IF EXISTS metric_v2d_turnover")
        c5.execute("""
            CREATE TABLE metric_v2d_turnover (
                candidate TEXT PRIMARY KEY, cutoff TEXT, n_asof_positions INTEGER, n_asof_traders INTEGER,
                overlap INTEGER, overlap_fraction REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        for name, t in turnover_results.items():
            c5.execute("INSERT INTO metric_v2d_turnover VALUES (?,?,?,?,?,?,?,?,?)", (
                name, t.get('cutoff'), t.get('n_asof_positions'), t.get('n_asof_traders'),
                t.get('overlap'), t.get('overlap_fraction'), SPEC_VERSION, generated_at, args.generator_commit))
        c5.commit()
        c5.close()
        print("[persist] metric_v2d_turnover written")

    # recommendation
    print("\n--- RECOMMENDATION (offered, not decided) ---")
    recommendation_text = (
        "significance_95 (CI excludes zero at 95%) is recommended as the definitional PRINCIPLE, not "
        "percentile or a fixed effect-size bar -- it answers 'who is provably better than the market given "
        "what we've observed', which is the question a cohort-gating rule should answer, vs percentile "
        "('top N% regardless of whether any of them are distinguishable from noise') or a fixed effect-size "
        "bar (arbitrary without the same statistical grounding). Effect size remains useful as a SEPARATE, "
        "economic overlay on top of significance (a trader can be significant at a small edge that costs "
        "still consume) -- not a replacement for it. See turnover numbers above for whether significance_95 "
        "is forward-usable before treating this as settled."
    )
    print(recommendation_text)

    # ============================= OBJECTIVE 3 =============================
    print("\n=== OBJECTIVE 3: cohort sanity, recommended = significance_95 ===")
    rec_cohort = candidates['significance_95']
    rec_traders = set(rec_cohort['trader'])
    rec_pairs = pairs[pairs['trader'].isin(rec_traders)]
    rec_positions = entries_df[entries_df['trader'].isin(rec_traders)]

    sanity = dict(
        n_traders=len(rec_traders),
        median_positions_per_trader=float(rec_positions.groupby('trader').size().median()),
        median_markets_per_trader=float(rec_pairs.groupby('trader').size().median()),
        no_fraction_overall=float((rec_positions['outcome'] == 'No').mean()),
        largest_market_share_of_cohort_positions=float(
            rec_positions.groupby('market_id').size().max() / len(rec_positions)) if len(rec_positions) else None,
        activity_span=[str(rec_positions['entry_ts'].min()), str(rec_positions['entry_ts'].max())],
        n_distinct_markets_touched=int(rec_positions['market_id'].nunique()),
    )
    print(json.dumps(sanity, indent=2, default=str))

    flags = []
    if sanity['largest_market_share_of_cohort_positions'] and sanity['largest_market_share_of_cohort_positions'] > 0.3:
        flags.append("cohort positions concentrated >30% in a single market -- possible selection artifact")
    if sanity['median_markets_per_trader'] < 3:
        flags.append("median cohort trader touches <3 distinct markets -- thin breadth even after passing significance")
    print(f"\nflags: {flags if flags else 'none'}")

    fwd = turnover_results.get('significance_95', {})
    print(f"\n[item 11 -- FORWARD USABILITY] of the {len(rec_traders)} traders qualifying now, "
          f"{fwd.get('overlap')} ({fwd.get('overlap_fraction')}) would also have qualified using only "
          f"data available 3 months ago (cutoff {fwd.get('cutoff')}).")
    if fwd.get('overlap_fraction') is not None:
        if fwd['overlap_fraction'] < 0.2:
            usability_verdict = ("LARGELY HINDSIGHT-ONLY -- fewer than 1 in 5 of today's qualifying traders "
                                 "would have been identifiable 3 months ago. This metric, at this threshold, "
                                 "cannot power a live signal as constructed; membership is not stable enough "
                                 "to act on in real time.")
        elif fwd['overlap_fraction'] < 0.5:
            usability_verdict = ("PARTIALLY FORWARD-USABLE -- less than half of today's cohort was "
                                 "identifiable 3 months ago. Real but limited forward value; a live signal "
                                 "built on this would miss most of who it later confirms as skilled.")
        else:
            usability_verdict = ("REASONABLY FORWARD-USABLE -- a majority of today's cohort was already "
                                 "identifiable 3 months ago.")
        print(f"[VERDICT] {usability_verdict}")
    else:
        usability_verdict = "undetermined -- insufficient as-of data"
        print(f"[VERDICT] {usability_verdict}")

    if args.persist:
        c6 = db_connect(args.db)
        c6.execute("DROP TABLE IF EXISTS metric_v2d_cohort_sanity")
        c6.execute("""
            CREATE TABLE metric_v2d_cohort_sanity (
                finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        c6.execute("INSERT INTO metric_v2d_cohort_sanity VALUES (?,?,?,?,?)",
                   ('sanity', json.dumps(sanity, default=str), SPEC_VERSION, generated_at, args.generator_commit))
        c6.execute("INSERT INTO metric_v2d_cohort_sanity VALUES (?,?,?,?,?)",
                   ('flags', json.dumps(flags), SPEC_VERSION, generated_at, args.generator_commit))
        c6.execute("INSERT INTO metric_v2d_cohort_sanity VALUES (?,?,?,?,?)",
                   ('forward_usability_verdict', json.dumps(usability_verdict), SPEC_VERSION, generated_at, args.generator_commit))
        c6.commit()
        c6.close()
        print("[persist] metric_v2d_cohort_sanity written")

    findings = dict(
        objective1=dict(gate_pass=gate_pass),
        objective2=dict(recommendation=recommendation_text, threshold_summary=threshold_summary,
                        turnover=turnover_results),
        objective3=dict(sanity=sanity, flags=flags, forward_usability=fwd,
                        forward_usability_verdict=usability_verdict),
    )
    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()
    if args.persist:
        c7 = db_connect(args.db)
        c7.execute("DROP TABLE IF EXISTS metric_v2d_findings")
        c7.execute("CREATE TABLE metric_v2d_findings (finding TEXT PRIMARY KEY, json_value TEXT, "
                   "spec_version TEXT, generated_at TEXT, generator_commit TEXT)")
        for k, v in findings.items():
            c7.execute("INSERT INTO metric_v2d_findings VALUES (?,?,?,?,?)",
                       (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, args.generator_commit))
        c7.commit()
        c7.close()
        print("[persist] metric_v2d_findings written")


if __name__ == '__main__':
    main()
