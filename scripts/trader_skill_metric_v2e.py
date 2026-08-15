#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2e -- AMENDMENT to v2d (lineage SKILLV2-2026-08-15-v1 ->
... -> SKILLV2D -> SKILLV2E). Builds the small-sample CI correction v2d's
findings required before any threshold could be trusted, and re-runs
threshold selection under it. Read-only. No production writes. No changes
to update_geo_elo.py, geo_elo_active, cohort membership, or any live path.
No cutover decision.

=============================================================================
WHY (recorded so the framing survives)
=============================================================================
v2d closed the weighted-gate debt cleanly (properly-weighted CIs land within
thousandths of v2c's approximation -- checked, not assumed). But it
surfaced a problem that blocks threshold selection: significance-95
qualified 14,188 of 27,236 traders (52%) -- half of everyone being
"provably better than the market" is not a skill signal, it is a broken
CI. Mechanism identified in v2d: per-trader bootstrap CIs resample that
trader's own pairs (median 4 markets under cap5), and nonparametric
bootstrap CIs are unreliably narrow at very small within-group n -- a
trader with 2-3 consistent observations gets a deceptively tight interval
(the bootstrap distribution of a 2-item resample has essentially only 3
distinct compositions and cannot represent genuine small-sample
uncertainty). This SAME mechanism explains v2d's other finding: the
"principled" cut (significance-95, 63% turnover) was LESS temporally
stable than percentile cuts (73-76%) -- the same thin, small-n traders
inflate the count and destabilise it, for one fixable reason. Fix it
before choosing a threshold.

=============================================================================
AMENDMENT PRE-REGISTRATION (fixed before computing; written to
metric_v2e_amendment before any result row)
=============================================================================

--- OBJECTIVE 1: build the small-sample correction ---
Three approaches compared, none picked a priori:
  (a) MINIMUM-PAIRS ELIGIBILITY: require >= M distinct (trader,market)
      pairs before a trader is eligible for a significance cut at all.
      Swept at M in {5,10,20,30} against the ORIGINAL (v2d) bootstrap CI,
      to isolate the eligibility filter's own effect from the CI-method
      change.
  (b) FINITE-SAMPLE-PENALISED CI: a t-distribution interval, NOT a BCa
      bootstrap -- BCa's own bias/acceleration correction is itself
      unreliable at n=2-5 (the same small-sample problem one level down),
      so it does not actually fix what's broken here. The t-interval uses
      the POPULATION sigma2_within (already well-estimated from 342,440
      positions) to get each pair's variance (sigma2_within/n_positions_in_pair)
      rather than trying to estimate a trader's own noise from 2-3 points
      -- borrowing strength for the VARIANCE the same way empirical-Bayes
      already borrows strength for the MEAN. Degrees of freedom = n_pairs-1
      (penalises thin traders directly: t_(1,0.975)=12.7, t_(2,0.975)=4.3 --
      wide by construction at low n, unlike a percentile bootstrap which
      can look artificially tight).
  (c) BOTH combined: t-interval AND minimum-pairs eligibility, swept
      together.
For each: n qualifying, median positions/markets, and an explicit
plausibility judgement (not just the number) -- a cut cannot credibly
label a majority of an untested population "skilled."

--- SANITY CHECK (the gate on trusting anything downstream) ---
Simulates a ZERO-SKILL trader (true win probability exactly equals price,
i.e. Bernoulli(price) outcomes -- the null this whole project has been
testing against throughout) with n_pairs=3, using REALISTIC price and
pair-size heterogeneity resampled from the real data (not an arbitrary
distributional assumption). Repeated 5,000 times, comparing the OLD
(nonparametric bootstrap) and NEW (t-interval) CI's empirical false-positive
rate against the nominal 5%. If the new method does not land near 5%, the
correction does not work and that is reported plainly, not glossed over.

--- OBJECTIVE 2: re-run threshold selection under the correction ---
Full v2d candidate table (percentile 1/5/10%, significance 95/99% under
the corrected CI + chosen eligibility, effect-size >=0.02/>=0.05)
re-computed with: n traders, median positions/markets, LEGENDARY overlap,
turnover (3-month PIT-correct, via tape_end as in v2d, not entry_ts), and
forward usability -- all three properties reported side by side per
candidate so the trade-off is visible in one place, not split across
sections.

--- OBJECTIVE 3: recommendation ---
Offered with reasoning addressing rank vs significance vs effect-size as
different questions, and an economic frame (geopolitics fee-free; politics
~0.04 feeRate peaking at p=0.50; entry spreads 0.001-0.02 in B4's captured
data -- an edge below the cost of entry isn't tradeable however
significant). Not presented as the script's canned text -- v2d's willingness
to override its own script's recommendation on turnover evidence was
correct and the same judgement applies here if the numbers call for it.

--- UNCHANGED CONSTRAINTS ---
No production writes. update_geo_elo.py / geo_elo_active / cohort
membership untouched. No cutover. comprehensive_elo / calibration_analysis.py
out of scope. Do not re-specify to obtain a preferred cohort size.

Persists metric_v2e_amendment, metric_v2e_correction_sweep,
metric_v2e_coverage_simulation, metric_v2e_threshold_candidates,
metric_v2e_findings.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sqlite3
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import load_entries, db_connect, SPEC_VERSION as V2_SPEC
from scripts.trader_skill_metric_v2c import build_pairs, eb_shrinkage_weighted, WEIGHT_FNS
from scripts.trader_skill_metric_v2d import (
    compute_cap5_metric, build_asof_population, turnover_check, per_trader_weighted_bootstrap,
    SPEC_VERSION as V2D_SPEC,
)

SPEC_VERSION = "SKILLV2E-2026-08-15-v1"
SEED = 42
BOOTSTRAP_REPS = 1000
COVERAGE_SIM_REPS = 5000
M_SWEEP = (5, 10, 20, 30)

AMENDMENT_WHY = (
    "v2d closed the weighted-gate debt cleanly but surfaced a broken CI: significance-95 qualified "
    "14,188/27,236 traders (52%). Mechanism: per-trader nonparametric bootstrap CIs are unreliably "
    "narrow at the median 4-market sample size under cap5 -- the same thin traders that inflate the "
    "count also explain why significance-95 (63% turnover) was LESS stable than percentile cuts "
    "(73-76%). One fixable cause behind both symptoms. Fix before choosing a threshold."
)
OBJ1_TEXT = (
    "Three approaches: (a) minimum-pairs eligibility (M in 5/10/20/30) gating the ORIGINAL bootstrap "
    "CI, to isolate the eligibility filter's own effect; (b) a t-distribution interval using the "
    "population sigma2_within (borrowing strength for variance the way EB shrinkage already borrows "
    "it for the mean) with df=n_pairs-1, NOT a BCa bootstrap (BCa's bias/acceleration correction is "
    "itself unreliable at n=2-5, the same problem one level down); (c) both combined. SANITY CHECK: "
    "simulate a zero-skill trader (Bernoulli(price) outcomes, realistic price/pair-size heterogeneity "
    "resampled from real data) at n_pairs=3, 5000 reps, check the corrected CI's false-positive rate "
    "against the nominal 5%. This is the gate on trusting anything downstream."
)
OBJ2_TEXT = (
    "Full threshold-candidate table re-run under the correction: n, median positions/markets, "
    "LEGENDARY overlap, turnover (3-month PIT-correct via tape_end), forward usability -- all three "
    "properties reported together per candidate."
)
OBJ3_TEXT = (
    "Recommendation addressing rank vs significance vs effect-size as different questions, with an "
    "economic frame (fee-free geopolitics, ~4% feeRate politics peaking at p=0.50, 0.001-0.02 entry "
    "spreads) -- an edge below the cost of entry isn't tradeable however statistically significant. "
    "Offered as a judgement on the evidence, not the script's canned output."
)


# ---------------------------------------------------------------------------
# Objective 1: corrections
# ---------------------------------------------------------------------------

def per_trader_t_ci(pairs, sigma2_within, alpha=0.05):
    """t-distribution CI per trader, using the POPULATION sigma2_within for
    each pair's variance (sigma2_within / n_positions_in_pair) rather than
    an unstable trader-specific estimate, with df = n_pairs - 1."""
    out = []
    for trader, grp in pairs.groupby('trader'):
        v = grp['pair_edge'].to_numpy()
        w = grp['weight'].to_numpy()
        n_pos = grp['n_positions'].to_numpy()
        npair = len(v)
        point = float(np.average(v, weights=w))
        if npair == 1:
            out.append((trader, point, npair, None, None))
            continue
        pair_var = sigma2_within / n_pos
        # variance of the weighted mean via error propagation (analytic pair variances)
        var_wmean = float(np.sum((w ** 2) * pair_var) / (np.sum(w) ** 2))
        se = np.sqrt(var_wmean)
        df = npair - 1
        tcrit = stats.t.ppf(1 - alpha / 2, df)
        out.append((trader, point, npair, point - tcrit * se, point + tcrit * se))
    return pd.DataFrame(out, columns=['trader', 'point', 'n_pairs', 'ci_lo_t', 'ci_hi_t'])


def eligibility_sweep(pairs, eb, trader_ci_bootstrap, m_values, verbose=False):
    """Approach (a): minimum-pairs eligibility gating the ORIGINAL v2d
    bootstrap CI (isolates the eligibility filter's own effect)."""
    n_pairs_per_trader = pairs.groupby('trader').size().rename('n_pairs')
    merged = eb.merge(trader_ci_bootstrap, on='trader').merge(n_pairs_per_trader, on='trader')
    rows = []
    for m in m_values:
        elig = merged[merged['n_pairs'] >= m]
        sig = elig[elig['ci_lo_95'] > 0]
        rows.append(dict(approach=f'eligibility_M{m}', n_eligible=len(elig), n_significant=len(sig)))
        if verbose:
            print(f"  M={m}: n_eligible={len(elig)}, n_significant(old CI)={len(sig)} "
                  f"({100*len(sig)/len(merged):.1f}% of full population)")
    return rows


def combined_sweep(pairs_t_ci_table, eb, full_n, m_values, verbose=False):
    """Approach (c): t-interval AND minimum-pairs eligibility together."""
    n_pairs_per_trader = pairs_t_ci_table.set_index('trader')['n_pairs']
    rows = []
    for m in m_values:
        elig = pairs_t_ci_table[pairs_t_ci_table['n_pairs'] >= m]
        sig = elig[elig['ci_lo_t'] > 0]
        rows.append(dict(approach=f'combined_M{m}', n_eligible=len(elig), n_significant=len(sig)))
        if verbose:
            print(f"  M={m} + t-CI: n_eligible={len(elig)}, n_significant={len(sig)} "
                  f"({100*len(sig)/full_n:.1f}% of full population)")
    return rows


# ---------------------------------------------------------------------------
# Coverage simulation
# ---------------------------------------------------------------------------

def coverage_simulation(entries_df, pairs, sigma2_within, n_pairs_sim=3, reps=COVERAGE_SIM_REPS, seed=SEED, verbose=False):
    rng = np.random.default_rng(seed)
    real_prices = entries_df['entry_avg_price'].to_numpy()
    real_pair_sizes = pairs['n_positions'].to_numpy()
    real_pair_sizes = real_pair_sizes[real_pair_sizes >= 1]

    excl_bootstrap = 0
    excl_t = 0
    boot_reps = 500  # per-simulation bootstrap reps, kept modest for total runtime

    for _ in range(reps):
        pair_edges = []
        weights = []
        n_positions_list = []
        for _ in range(n_pairs_sim):
            k = int(rng.choice(real_pair_sizes))
            prices = rng.choice(real_prices, size=k)
            wins = rng.binomial(1, prices)  # null: true win prob == price exactly
            pair_edges.append(float(np.mean(wins - prices)))
            n_positions_list.append(k)
            weights.append(min(k, 5))
        pair_edges = np.array(pair_edges)
        weights = np.array(weights, dtype=float)
        n_positions_arr = np.array(n_positions_list, dtype=float)

        # old: nonparametric bootstrap over the n_pairs_sim pair values, weighted
        idx = rng.integers(0, n_pairs_sim, size=(boot_reps, n_pairs_sim))
        bvals = pair_edges[idx]
        bw = weights[idx]
        bmeans = (bvals * bw).sum(axis=1) / bw.sum(axis=1)
        lo_b, hi_b = np.percentile(bmeans, [2.5, 97.5])
        if lo_b > 0 or hi_b < 0:
            excl_bootstrap += 1

        # new: t-interval using population sigma2_within
        point = float(np.average(pair_edges, weights=weights))
        pair_var = sigma2_within / n_positions_arr
        var_wmean = float(np.sum((weights ** 2) * pair_var) / (np.sum(weights) ** 2))
        se = np.sqrt(var_wmean)
        df = n_pairs_sim - 1
        tcrit = stats.t.ppf(0.975, df)
        lo_t, hi_t = point - tcrit * se, point + tcrit * se
        if lo_t > 0 or hi_t < 0:
            excl_t += 1

    rate_bootstrap = excl_bootstrap / reps
    rate_t = excl_t / reps
    if verbose:
        print(f"[coverage sim] n_pairs_sim={n_pairs_sim}, reps={reps}")
        print(f"  OLD (nonparametric bootstrap) false-positive rate: {rate_bootstrap:.4f} (nominal 0.05)")
        print(f"  NEW (t-interval, population variance) false-positive rate: {rate_t:.4f} (nominal 0.05)")
    return rate_bootstrap, rate_t


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def persist_amendment(conn, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2e_amendment")
    conn.execute("""
        CREATE TABLE metric_v2e_amendment (
            spec_version TEXT PRIMARY KEY, amends_spec_version TEXT, why TEXT,
            objective1 TEXT, objective2 TEXT, objective3 TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2e_amendment VALUES (?,?,?,?,?,?,?,?)",
                 (SPEC_VERSION, V2D_SPEC, AMENDMENT_WHY, OBJ1_TEXT, OBJ2_TEXT, OBJ3_TEXT,
                  generated_at, generator_commit))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--bootstrap-reps', type=int, default=BOOTSTRAP_REPS)
    ap.add_argument('--coverage-reps', type=int, default=COVERAGE_SIM_REPS)
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)
    print(f"=== AMENDMENT (spec {SPEC_VERSION}, amends {V2D_SPEC}) ===")
    print(f"WHY: {AMENDMENT_WHY}\n\nOBJECTIVE 1: {OBJ1_TEXT}\n\nOBJECTIVE 2: {OBJ2_TEXT}\n\nOBJECTIVE 3: {OBJ3_TEXT}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    if args.persist:
        persist_amendment(conn, generated_at, args.generator_commit)
        print("[persist] metric_v2e_amendment written\n")

    entries_df = load_entries(conn, verbose=args.verbose)
    pairs, eb, sigma2_within = compute_cap5_metric(entries_df)
    print(f"cap5 metric loaded: {len(eb)} traders, sigma2_within={sigma2_within:.6f}, "
          f"sigma2_between={eb['sigma2_between'].iloc[0]:.6f}\n")

    # ============================= OBJECTIVE 1 =============================
    print("=== OBJECTIVE 1: small-sample correction ===")

    print("\n--- (a) minimum-pairs eligibility, gating the ORIGINAL bootstrap CI ---")
    pairs_for_ci = pairs[['trader', 'market_id', 'pair_edge', 'weight']]
    trader_ci_bootstrap = per_trader_weighted_bootstrap(pairs_for_ci, reps=args.bootstrap_reps, seed=args.seed)
    sweep_a = eligibility_sweep(pairs, eb, trader_ci_bootstrap, M_SWEEP, verbose=True)

    print("\n--- (b) t-distribution CI (population variance, df=n_pairs-1), no eligibility filter ---")
    t_ci = per_trader_t_ci(pairs, sigma2_within)
    sig_t_only = t_ci[t_ci['ci_lo_t'] > 0]
    print(f"  t-CI alone: n_significant={len(sig_t_only)}/{len(t_ci)} "
          f"({100*len(sig_t_only)/len(t_ci):.1f}% of population)")

    print("\n--- (c) combined: t-CI AND minimum-pairs eligibility ---")
    sweep_c = combined_sweep(t_ci, eb, len(eb), M_SWEEP, verbose=True)

    print("\n[plausibility judgement] A skill cut qualifying a majority of an untested population is "
          "prima facie implausible -- under a rough null-heavy prior (most traders have no edge; a real "
          "edge is the exception, not the rule, consistent with sigma2_between being small relative to "
          "sigma2_within throughout this whole investigation), a credible range for 'provably skilled' "
          "is a SMALL minority, plausibly single-digit percent to low tens of percent, not a majority. "
          "Judged against that: (b) alone at 100% coverage would need checking numerically below; "
          "(a)/(c) at M>=20-30 should land in a materially more plausible range -- reported numerically above.")

    if args.persist:
        c2 = db_connect(args.db)
        c2.execute("DROP TABLE IF EXISTS metric_v2e_correction_sweep")
        c2.execute("""
            CREATE TABLE metric_v2e_correction_sweep (
                approach TEXT PRIMARY KEY, n_eligible INTEGER, n_significant INTEGER,
                spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        for r in sweep_a + sweep_c:
            c2.execute("INSERT INTO metric_v2e_correction_sweep VALUES (?,?,?,?,?,?)",
                       (r['approach'], r['n_eligible'], r['n_significant'], SPEC_VERSION,
                        generated_at, args.generator_commit))
        c2.execute("INSERT INTO metric_v2e_correction_sweep VALUES (?,?,?,?,?,?)",
                   ('t_ci_only', len(t_ci), len(sig_t_only), SPEC_VERSION, generated_at, args.generator_commit))
        c2.commit()
        c2.close()
        print("\n[persist] metric_v2e_correction_sweep written")

    print("\n--- SANITY CHECK: coverage simulation, zero-skill trader, n_pairs=3 ---")
    rate_bootstrap, rate_t = coverage_simulation(entries_df, pairs, sigma2_within, n_pairs_sim=3,
                                                  reps=args.coverage_reps, seed=args.seed, verbose=True)
    coverage_ok = 0.02 <= rate_t <= 0.10  # generous band around nominal 0.05
    print(f"\n[COVERAGE GATE] t-interval false-positive rate {rate_t:.4f} vs nominal 0.05, "
          f"within [0.02,0.10]: {'PASS' if coverage_ok else 'FAIL'}")

    if args.persist:
        c3 = db_connect(args.db)
        c3.execute("DROP TABLE IF EXISTS metric_v2e_coverage_simulation")
        c3.execute("""
            CREATE TABLE metric_v2e_coverage_simulation (
                method TEXT PRIMARY KEY, n_pairs_sim INTEGER, reps INTEGER, false_positive_rate REAL,
                nominal_rate REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        c3.execute("INSERT INTO metric_v2e_coverage_simulation VALUES (?,?,?,?,?,?,?,?)",
                   ('bootstrap_old', 3, args.coverage_reps, rate_bootstrap, 0.05, SPEC_VERSION,
                    generated_at, args.generator_commit))
        c3.execute("INSERT INTO metric_v2e_coverage_simulation VALUES (?,?,?,?,?,?,?,?)",
                   ('t_interval_new', 3, args.coverage_reps, rate_t, 0.05, SPEC_VERSION,
                    generated_at, args.generator_commit))
        c3.commit()
        c3.close()
        print("[persist] metric_v2e_coverage_simulation written")

    if not coverage_ok:
        print("\n[STOP] The corrected CI does not achieve nominal coverage. Per the pre-registration: "
              "nothing built on this correction is trustworthy. Stopping before Objective 2.", file=sys.stderr)
        conn.close()
        sys.exit(2)

    # ============================= OBJECTIVE 2 =============================
    print("\n=== OBJECTIVE 2: threshold candidates under the correction ===")
    # chosen correction for the significance candidates: t-CI + M=10 eligibility
    # (a middle point in the sweep -- picked and justified in the report, not
    # silently defaulted)
    M_CHOSEN = 10
    t_ci_elig = t_ci[t_ci['n_pairs'] >= M_CHOSEN]
    sig95_corrected = t_ci_elig[t_ci_elig['ci_lo_t'] > 0]

    # 99% via a fresh t critical value (not a 95%-interval rescale, unlike v2d's
    # approximation, since the t-interval is cheap enough to recompute exactly)
    def t_ci_at_alpha(pairs_df, sigma2_within, alpha):
        rows = []
        for trader, grp in pairs_df.groupby('trader'):
            v = grp['pair_edge'].to_numpy(); w = grp['weight'].to_numpy(); n_pos = grp['n_positions'].to_numpy()
            npair = len(v)
            if npair < 2:
                continue
            point = float(np.average(v, weights=w))
            pair_var = sigma2_within / n_pos
            se = np.sqrt(float(np.sum((w ** 2) * pair_var) / (np.sum(w) ** 2)))
            tcrit = stats.t.ppf(1 - alpha / 2, npair - 1)
            rows.append((trader, point, npair, point - tcrit * se, point + tcrit * se))
        return pd.DataFrame(rows, columns=['trader', 'point', 'n_pairs', 'ci_lo', 'ci_hi'])

    t_ci_99 = t_ci_at_alpha(pairs[pairs['trader'].isin(set(t_ci_elig['trader']))], sigma2_within, 0.01)
    sig99_corrected = t_ci_99[t_ci_99['ci_lo'] > 0]

    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))

    candidates = {}
    for pct in (1, 5, 10):
        thresh = eb['shrunk_mean'].quantile(1 - pct / 100)
        candidates[f'percentile_top{pct}'] = set(eb[eb['shrunk_mean'] >= thresh]['trader'])
    candidates['significance_95_corrected'] = set(sig95_corrected['trader'])
    candidates['significance_99_corrected'] = set(sig99_corrected['trader'])
    for bar in (0.02, 0.05):
        candidates[f'effect_size_{bar}'] = set(eb[eb['shrunk_mean'] >= bar]['trader'])

    cutoff_sql, eb_asof = build_asof_population(conn, entries_df, months_back=3, verbose=args.verbose)

    summary_rows = []
    for name, trader_set in candidates.items():
        if len(trader_set) == 0:
            summary_rows.append(dict(candidate=name, n_traders=0))
            continue
        sub_pairs = pairs[pairs['trader'].isin(trader_set)]
        med_pos = float(pairs[pairs['trader'].isin(trader_set)].groupby('trader')['n_positions'].sum().median())
        med_mkt = float(sub_pairs.groupby('trader').size().median())
        n_legend = len(legendary & trader_set)
        t = turnover_check(cutoff_sql, eb_asof, trader_set)
        row = dict(candidate=name, n_traders=len(trader_set), median_positions=med_pos, median_markets=med_mkt,
                  legendary_overlap=n_legend, legendary_overlap_fraction=n_legend / len(legendary) if legendary else None,
                  turnover_overlap=t.get('overlap'), turnover_fraction=t.get('overlap_fraction'),
                  turnover_cutoff=t.get('cutoff'))
        summary_rows.append(row)
        print(f"  {name:>28}: n={row['n_traders']:>6} med_pos={med_pos:>6.1f} med_mkt={med_mkt:>5.1f} "
              f"LEGENDARY={n_legend}/{len(legendary)} turnover={t.get('overlap')}/{len(trader_set)} "
              f"({t.get('overlap_fraction')})")

    if args.persist:
        c4 = db_connect(args.db)
        c4.execute("DROP TABLE IF EXISTS metric_v2e_threshold_candidates")
        c4.execute("""
            CREATE TABLE metric_v2e_threshold_candidates (
                candidate TEXT PRIMARY KEY, n_traders INTEGER, median_positions REAL, median_markets REAL,
                legendary_overlap INTEGER, legendary_overlap_fraction REAL, turnover_overlap INTEGER,
                turnover_fraction REAL, turnover_cutoff TEXT, spec_version TEXT, generated_at TEXT,
                generator_commit TEXT
            )
        """)
        for row in summary_rows:
            c4.execute("INSERT INTO metric_v2e_threshold_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                row['candidate'], row.get('n_traders'), row.get('median_positions'), row.get('median_markets'),
                row.get('legendary_overlap'), row.get('legendary_overlap_fraction'), row.get('turnover_overlap'),
                row.get('turnover_fraction'), row.get('turnover_cutoff'), SPEC_VERSION, generated_at,
                args.generator_commit))
        c4.commit()
        c4.close()
        print("[persist] metric_v2e_threshold_candidates written")

    findings = dict(
        sweep_a=sweep_a, sweep_c=sweep_c, t_ci_only=dict(n=len(t_ci), n_significant=len(sig_t_only)),
        coverage=dict(bootstrap_rate=rate_bootstrap, t_rate=rate_t, coverage_ok=coverage_ok),
        M_chosen=M_CHOSEN, threshold_candidates=summary_rows,
    )
    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()
    if args.persist:
        c5 = db_connect(args.db)
        c5.execute("DROP TABLE IF EXISTS metric_v2e_findings")
        c5.execute("CREATE TABLE metric_v2e_findings (finding TEXT PRIMARY KEY, json_value TEXT, "
                   "spec_version TEXT, generated_at TEXT, generator_commit TEXT)")
        for k, v in findings.items():
            c5.execute("INSERT INTO metric_v2e_findings VALUES (?,?,?,?,?)",
                       (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, args.generator_commit))
        c5.commit()
        c5.close()
        print("[persist] metric_v2e_findings written")


if __name__ == '__main__':
    main()
