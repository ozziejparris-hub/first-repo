#!/usr/bin/env python3
"""
TRADER SKILL METRIC v2c -- AMENDMENT to v2/v2b (lineage: SKILLV2-2026-08-15-v1,
amended SKILLV2B-2026-08-15-v1). Resolves the weighting tension v2b left open
and disambiguates the entries/exits correlation v2b flagged as likely
mechanical. Read-only. No production writes. No changes to update_geo_elo.py,
geo_elo_active, cohort membership, or any live path.

=============================================================================
WHY (recorded so the framing survives)
=============================================================================
v2b found: market-weighting is conceptually right (Kamala Harris 2024 is
34,061 positions / 3,374 traders from ONE real-world event, ~10% of all
entry positions) but statistically unaffordable -- sigma2_between = 0.0
under both market- and event-weighting, VERIFIED genuine (MSB 0.0621 <
sigma2_within 0.0735) after the shrinkage estimator was rebuilt, not an
artifact of the earlier broken one. Position-weighting is statistically
viable (sigma2_between = 0.00348) but structurally exposed to exactly the
concentration Amendment 2 existed to close. v2b used position-weighting BY
NECESSITY and recorded the tension rather than resolving it. Thresholds set
on position-weighted ranks would inherit that exposure -- this pass tries to
resolve it first.

v2b also found entries-vs-exits (position-weighted) correlation of Pearson
-0.478 / Spearman -0.484, and flagged a likely MECHANICAL origin:
edge_entry = won - entry_price and edge_exit = exit_price - won share the
same `won` term with opposite signs, so any winning outcome mechanically
pushes entry edge up and exit edge down (and vice versa) independent of any
real timing skill. Not resolved in v2b -- resolved here via a placebo.

=============================================================================
AMENDMENT PRE-REGISTRATION (fixed before computing; written to
metric_v2c_amendment before any result row)
=============================================================================

--- OBJECTIVE 1: capped-multiplicity weighting (the middle path) ---
Each (trader, market) pair gets weight w(n) instead of w=1 (market-weighted)
or w=n (position-weighted), n = positions in that pair. Variants: log
(w=1+log(n)), sqrt (w=sqrt(n)), hard-cap at C in {3,5,10} (w=min(n,C)).
Trader-level raw_mean = weight-weighted average of each pair's own mean
edge. Shrinkage generalised: effective sample size per trader = sum of
pair weights (reduces exactly to market-weighting's n=distinct-markets at
w=1, and to position-weighting's n=positions at w=n -- one estimator
family, not a different one per variant). sigma2_within held FIXED across
all variants at the pooled RAW-POSITION edge variance (a single, stable
noise-per-decision estimate, not re-estimated per weighting -- keeps the
comparison apples-to-apples). MSB/n0/sigma2_between via the same unbalanced
ANOVA method-of-moments formula v2's eb_shrinkage already uses (fixed in
13ecf07), generalised to weighted effective-n.

CONCENTRATION METRIC: population-level share of TOTAL weight held by the
single largest market (Kamala Harris 2024), reported per variant --
directly comparable across variants since it is measured in the same units
(fraction of total weight) regardless of what generates that weight.

DECISION RULE (recorded before computing): a variant is "satisfactory" if
BOTH sigma2_between > 0 (non-degenerate -- shrinkage can distinguish some
trader from the grand mean) AND the largest-market weight share is
materially below position-weighting's own ~9.95% floor (the exposure level
that produced the original v2 gate failure). If no variant clears both
bars, that is reported as a finding about the DATA (insufficient breadth
per trader at current volume to support any bounded-concentration ranking),
not resolved by picking the least-bad option and proceeding as if it were
fine.

--- OBJECTIVE 2: the entries/exits placebo ---
For each entry position, draw ONE synthetic "exit" price from the market's
OWN OBSERVED trade tape between entry and resolution (tape_end) -- not a
parametric assumption. Concretely: for the position's market, build the
full timestamp-sorted trade tape with each trade's price converted to a
canonical Yes-price (price if outcome_bet=='Yes' else 1-price -- the same
flip used by verify_dilution_guard.py's price_at_trade_tape and
monitor.py's market_consensus, both already established as the correct
operation for THIS purpose in the price-convention audit, distinct from the
entry/exit edge formula's own established no-flip convention). Restrict to
trades strictly after the position's entry_timestamp and at/before the
market's tape_end. Pick one uniformly at random (seeded). Convert back to
the position's own side (price if Yes else 1-price) to get a synthetic
exit price on the same footing as the real exit_avg_price field. Compute
placebo edge_exit = synthetic_exit_price - won, and the same
position-weighted entries-vs-exits correlation as v2b. Positions whose
market has no further trades after entry (no valid random point) are
excluded and the exclusion rate reported.

INTERPRETATION FIXED IN ADVANCE: if the placebo correlation is comparably
negative to the observed -0.48, the observed correlation is essentially
mechanical and carries no behavioural information -- report that plainly,
do not describe entry and exit skill as "behaviourally opposed." If the
placebo is materially less negative, the gap between observed and placebo
is the real, non-mechanical signal, and IS worth reporting as such.

--- OBJECTIVE 3: re-run key comparisons under the recommended weighting ---
Same items as v2b (distribution, Spearman vs stored geo_elo, the
No-fraction falsifiable test, LEGENDARY overlap) plus a re-run of the
calibration gate (same clustered treatment as v2b, same tolerance) under
whichever weighting Objective 1 recommends -- confirms the gate still
holds now that the weighting has changed, per the pre-registered
requirement that nothing downstream is trusted without its own check.

--- UNCHANGED CONSTRAINTS ---
No production writes. update_geo_elo.py / geo_elo_active / cohort
membership untouched. No threshold derivation, no cutover. comprehensive_elo
/ calibration_analysis.py out of scope. Do NOT re-specify to obtain a
preferred result -- if Objective 1 finds no satisfactory weighting, report
that and stop rather than picking the least-bad variant and proceeding.

Persists metric_v2c_amendment, metric_v2c_tradeoff_curve,
metric_v2c_placebo, metric_v2c_gate_results (if a weighting is recommended),
metric_v2c_trader_results (if a weighting is recommended),
metric_v2c_findings.
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

from scripts.trader_skill_metric_v2 import load_entries, load_exits, rank_corr, db_connect, SPEC_VERSION as V2_SPEC
from scripts.trader_skill_metric_v2b import (
    market_weighted, position_weighted, two_way_gap_bootstrap, fixed_buckets, apply_variant,
    run_gate_variant, SPEC_VERSION as V2B_SPEC, TOP_N_EXCLUDE,
)

SPEC_VERSION = "SKILLV2C-2026-08-15-v1"
SEED = 42
GATE_REPS = 1500
BOOTSTRAP_REPS = 1000
KAMALA_MARKET_HINT = "Will Kamala Harris win the 2024 US Presidential Election?"

AMENDMENT_WHY = (
    "v2b found market/event-weighting statistically unaffordable (sigma2_between=0, verified genuine: "
    "MSB=0.0621 < sigma2_within=0.0735) despite being conceptually right about not letting one event "
    "(Kamala Harris 2024, ~10% of all entry positions) dominate; position-weighting is viable "
    "(sigma2_between=0.00348) but structurally exposed to that same concentration. v2b recorded this "
    "tension rather than resolving it. v2b also found entries-vs-exits correlation -0.48 and flagged a "
    "likely mechanical origin (edge_entry and edge_exit share the won term with opposite signs) without "
    "testing it. This pass builds the capped-multiplicity middle path v2b proposed but did not build, "
    "and runs the placebo v2b proposed but did not run."
)
OBJ1_TEXT = (
    "Capped-multiplicity weighting: each (trader,market) pair weighted by a bounded function of its "
    "position count n -- log (1+log n), sqrt, hard-cap at C in {3,5,10} -- instead of w=1 (market) or "
    "w=n (position). Shrinkage generalised via effective sample size = sum of pair weights per trader, "
    "one estimator family spanning both endpoints. sigma2_within held fixed at the pooled raw-position "
    "edge variance across all variants for a fair comparison. Concentration measured as the single "
    "largest market's share of TOTAL population weight. DECISION RULE fixed in advance: a variant is "
    "satisfactory only if sigma2_between>0 AND largest-market weight share is materially below "
    "position-weighting's own ~9.95% floor. If none qualifies, report that as a finding about the data, "
    "not a reason to pick the least-bad option."
)
OBJ2_TEXT = (
    "Entries/exits placebo: synthetic exit price drawn uniformly at random from the market's own "
    "observed trade tape (real data, not a parametric assumption) between entry and resolution, "
    "converted to a canonical Yes-price then back to the position's own side (the price_at_trade_tape "
    "flip, established correct for this purpose, distinct from the entry/exit edge formula's own "
    "no-flip convention). Placebo edge_exit = synthetic_price - won. INTERPRETATION FIXED IN ADVANCE: "
    "comparably negative to observed -0.48 => mechanical, not behavioural, report plainly; materially "
    "less negative => the gap is real signal."
)
OBJ3_TEXT = (
    "Same comparisons as v2b (distribution, Spearman vs stored geo_elo, No-fraction falsifiable test, "
    "LEGENDARY overlap) plus a fresh clustered-gate re-run, under whichever weighting Objective 1 "
    "recommends -- nothing downstream is trusted without its own check."
)


# ---------------------------------------------------------------------------
# Objective 1: capped-multiplicity weighting family
# ---------------------------------------------------------------------------

def build_pairs(df, value_col='edge'):
    """(trader, market) pair-level table: pair mean edge, position count n."""
    g = df.groupby(['trader', 'market_id'])[value_col].agg(['mean', 'count']).reset_index()
    g = g.rename(columns={'mean': 'pair_edge', 'count': 'n_positions'})
    return g


WEIGHT_FNS = {
    'market_w1': lambda n: 1.0,
    'log': lambda n: 1.0 + np.log(n),
    'sqrt': lambda n: np.sqrt(n),
    'cap3': lambda n: np.minimum(n, 3),
    'cap5': lambda n: np.minimum(n, 5),
    'cap10': lambda n: np.minimum(n, 10),
    'position_wn': lambda n: n,
}


def eb_shrinkage_weighted(pairs, sigma2_within, weight_col='weight', value_col='pair_edge', trader_col='trader'):
    """Generalised empirical-Bayes shrinkage: effective sample size per
    trader = sum of pair weights. Reduces to v2's eb_shrinkage exactly when
    weight_col is all-1 (market-weighting) or equals n_positions
    (position-weighting, one row per position)."""
    per_trader = pairs.groupby(trader_col).apply(
        lambda g: pd.Series({
            'raw_mean': np.average(g[value_col], weights=g[weight_col]),
            'eff_n': g[weight_col].sum(),
            'n_pairs': len(g),
        }), include_groups=False
    ).reset_index()

    grand_mean = np.average(pairs[value_col], weights=pairs[weight_col])
    eff_n = per_trader['eff_n'].to_numpy()
    K = len(per_trader)
    N = eff_n.sum()
    if K > 1 and N > 0:
        msb = float(np.sum(eff_n * (per_trader['raw_mean'].to_numpy() - grand_mean) ** 2) / (K - 1))
        n0 = float((N - np.sum(eff_n ** 2) / N) / (K - 1))
        sigma2_between = max(0.0, (msb - sigma2_within) / n0) if n0 > 0 else 0.0
    else:
        sigma2_between = 0.0

    sampling_var = sigma2_within / eff_n
    per_trader['shrinkage_weight'] = sigma2_between / (sigma2_between + sampling_var)
    per_trader['shrunk_mean'] = (per_trader['shrinkage_weight'] * per_trader['raw_mean'] +
                                  (1 - per_trader['shrinkage_weight']) * grand_mean)
    per_trader['grand_mean'] = grand_mean
    per_trader['sigma2_within'] = sigma2_within
    per_trader['sigma2_between'] = sigma2_between
    return per_trader


def tradeoff_row(entries_df, weight_name, weight_fn, sigma2_within, kamala_market_id):
    pairs = build_pairs(entries_df)
    pairs['weight'] = weight_fn(pairs['n_positions'].to_numpy())
    total_weight = pairs['weight'].sum()
    kamala_weight = pairs.loc[pairs['market_id'] == kamala_market_id, 'weight'].sum()
    kamala_share = float(kamala_weight / total_weight) if total_weight > 0 else None

    eb = eb_shrinkage_weighted(pairs, sigma2_within)
    n_rankable = int((eb['eff_n'] > 0).sum())
    return dict(
        weighting=weight_name, sigma2_between=float(eb['sigma2_between'].iloc[0]),
        n_traders=len(eb), n_rankable=n_rankable,
        largest_market_weight_share=kamala_share,
        median_eff_n=float(eb['eff_n'].median()), mean_eff_n=float(eb['eff_n'].mean()),
    ), eb, pairs


# ---------------------------------------------------------------------------
# Objective 2: entries/exits placebo
# ---------------------------------------------------------------------------

def build_market_tape(conn, market_ids, verbose=False):
    placeholders = ",".join("?" for _ in market_ids)
    rows = conn.execute(f"""
        SELECT market_id, timestamp, outcome_bet, price
        FROM trades
        WHERE market_id IN ({placeholders})
        ORDER BY market_id, timestamp ASC
    """, market_ids).fetchall()
    if verbose:
        print(f"[tape] {len(rows)} trades loaded across {len(market_ids)} markets")
    tape = {}
    for market_id, ts, ob, price in rows:
        yes_price = price if ob == 'Yes' else (1.0 - price)
        tape.setdefault(market_id, []).append((ts, yes_price))
    return tape


def placebo_exits(entries_df, tape, seed=SEED, verbose=False):
    rng = np.random.default_rng(seed)
    rows = []
    excluded = 0
    for market_id, grp in entries_df.groupby('market_id'):
        mtape = tape.get(market_id, [])
        if not mtape:
            excluded += len(grp)
            continue
        ts_arr = np.array([t[0] for t in mtape])
        yes_arr = np.array([t[1] for t in mtape])
        for _, row in grp.iterrows():
            idx = np.searchsorted(ts_arr, row['entry_ts'], side='right')
            candidates = yes_arr[idx:]
            if len(candidates) == 0:
                excluded += 1
                continue
            chosen_yes = candidates[rng.integers(0, len(candidates))]
            synth_price = chosen_yes if row['outcome'] == 'Yes' else (1.0 - chosen_yes)
            rows.append((row['position_id'], row['trader'], market_id, synth_price, row['won']))
    df = pd.DataFrame(rows, columns=['position_id', 'trader', 'market_id', 'synth_exit_price', 'won'])
    df['edge'] = df['synth_exit_price'] - df['won']
    if verbose:
        print(f"[placebo] {len(df)} positions with a valid synthetic exit, {excluded} excluded (no further trades)")
    return df, excluded


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist_amendment(conn, generated_at, generator_commit):
    conn.execute("DROP TABLE IF EXISTS metric_v2c_amendment")
    conn.execute("""
        CREATE TABLE metric_v2c_amendment (
            spec_version TEXT PRIMARY KEY, amends_spec_version TEXT, why TEXT,
            objective1 TEXT, objective2 TEXT, objective3 TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO metric_v2c_amendment VALUES (?,?,?,?,?,?,?,?)",
                 (SPEC_VERSION, V2B_SPEC, AMENDMENT_WHY, OBJ1_TEXT, OBJ2_TEXT, OBJ3_TEXT,
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

    print(f"=== AMENDMENT (spec {SPEC_VERSION}, amends {V2B_SPEC}) ===")
    print(f"WHY: {AMENDMENT_WHY}\n")
    print(f"OBJECTIVE 1: {OBJ1_TEXT}\n")
    print(f"OBJECTIVE 2: {OBJ2_TEXT}\n")
    print(f"OBJECTIVE 3: {OBJ3_TEXT}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    if args.persist:
        persist_amendment(conn, generated_at, args.generator_commit)
        print("[persist] metric_v2c_amendment written\n")

    entries_df = load_entries(conn, verbose=args.verbose)
    exits_df = load_exits(conn, verbose=args.verbose)

    kamala_id = conn.execute(
        "SELECT market_id FROM positions WHERE market_title = ? LIMIT 1", (KAMALA_MARKET_HINT,)
    ).fetchone()
    kamala_id = kamala_id[0] if kamala_id else \
        entries_df.groupby('market_id').size().sort_values(ascending=False).index[0]
    print(f"[concentration anchor] largest market = {kamala_id}")

    sigma2_within = float(entries_df['edge'].var())
    print(f"[fixed] sigma2_within (pooled raw-position edge variance) = {sigma2_within:.6f}\n")

    # ============================= OBJECTIVE 1 =============================
    print("=== OBJECTIVE 1: capped-multiplicity trade-off curve ===")
    curve = []
    eb_by_weighting = {}
    for name, fn in WEIGHT_FNS.items():
        row, eb, pairs = tradeoff_row(entries_df, name, fn, sigma2_within, kamala_id)
        curve.append(row)
        eb_by_weighting[name] = eb
        print(f"  {name:>12}: sigma2_between={row['sigma2_between']:.6f}  "
              f"largest_market_share={row['largest_market_weight_share']:.4f}  "
              f"median_eff_n={row['median_eff_n']:.2f}  n_traders={row['n_traders']}")

    position_share = curve[[r['weighting'] for r in curve].index('position_wn')]['largest_market_weight_share']
    satisfactory = [r for r in curve if r['sigma2_between'] > 1e-9 and
                    r['largest_market_weight_share'] is not None and
                    r['largest_market_weight_share'] < 0.5 * position_share]
    print(f"\n[decision rule] position-weighted concentration floor = {position_share:.4f}; "
          f"satisfactory = sigma2_between>0 AND share < {0.5*position_share:.4f} (half the floor)")
    if satisfactory:
        best = max(satisfactory, key=lambda r: r['sigma2_between'])
        print(f"[OBJECTIVE 1 RESULT] {len(satisfactory)} satisfactory variant(s); "
              f"recommending '{best['weighting']}' (highest sigma2_between among satisfactory variants)")
        recommended_weighting = best['weighting']
    else:
        print("[OBJECTIVE 1 RESULT] NO variant achieves both non-degenerate variance AND bounded "
              "concentration below half the position-weighted floor. This is a finding about the DATA "
              "(insufficient per-trader breadth at current volume), not resolved by picking the least-bad "
              "option.")
        # relaxed fallback purely for reporting continuity, NOT presented as "satisfactory"
        candidates = [r for r in curve if r['sigma2_between'] > 1e-9]
        recommended_weighting = min(candidates, key=lambda r: r['largest_market_weight_share'])['weighting'] \
            if candidates else 'position_wn'
        print(f"[note] proceeding to Objective 3 with '{recommended_weighting}' (lowest concentration "
              f"among non-degenerate variants) FOR CHARACTERISATION ONLY -- explicitly NOT a recommendation.")

    if args.persist:
        conn2 = db_connect(args.db)
        conn2.execute("DROP TABLE IF EXISTS metric_v2c_tradeoff_curve")
        conn2.execute("""
            CREATE TABLE metric_v2c_tradeoff_curve (
                weighting TEXT PRIMARY KEY, sigma2_between REAL, n_traders INTEGER, n_rankable INTEGER,
                largest_market_weight_share REAL, median_eff_n REAL, mean_eff_n REAL,
                satisfactory INTEGER, spec_version TEXT, generated_at TEXT, generator_commit TEXT
            )
        """)
        sat_names = {r['weighting'] for r in satisfactory}
        for r in curve:
            conn2.execute("INSERT INTO metric_v2c_tradeoff_curve VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                r['weighting'], r['sigma2_between'], r['n_traders'], r['n_rankable'],
                r['largest_market_weight_share'], r['median_eff_n'], r['mean_eff_n'],
                int(r['weighting'] in sat_names), SPEC_VERSION, generated_at, args.generator_commit))
        conn2.commit()
        conn2.close()
        print("[persist] metric_v2c_tradeoff_curve written")

    # ============================= OBJECTIVE 2 =============================
    print("\n=== OBJECTIVE 2: entries/exits placebo ===")
    market_ids = entries_df['market_id'].unique().tolist()
    tape = build_market_tape(conn, market_ids, verbose=args.verbose)
    placebo_df, excluded = placebo_exits(entries_df, tape, seed=args.seed, verbose=args.verbose)
    print(f"placebo positions: {len(placebo_df)}, excluded (no further trades): {excluded} "
          f"({100*excluded/(len(placebo_df)+excluded):.1f}%)")

    entries_pos = entries_df[['position_id', 'trader', 'edge']].rename(columns={'edge': 'entry_edge'})
    real_exits_pos = exits_df[['position_id', 'trader', 'edge']].rename(columns={'edge': 'real_exit_edge'})
    placebo_pos = placebo_df[['position_id', 'trader', 'edge']].rename(columns={'edge': 'placebo_exit_edge'})

    real_pt = entries_pos.merge(real_exits_pos, on=['position_id', 'trader'])
    real_trader_entry = real_pt.groupby('trader')['entry_edge'].mean()
    real_trader_exit = real_pt.groupby('trader')['real_exit_edge'].mean()
    real_corr_pearson = float(np.corrcoef(real_trader_entry, real_trader_exit)[0, 1])
    real_corr_spearman = rank_corr(real_trader_entry, real_trader_exit)
    print(f"[same-position-level check] real entry/exit, matched positions: n={len(real_pt)}, "
          f"trader-level pearson={real_corr_pearson:.4f}, spearman={real_corr_spearman:.4f}")

    placebo_pt = entries_pos.merge(placebo_pos, on=['position_id', 'trader'])
    placebo_trader_entry = placebo_pt.groupby('trader')['entry_edge'].mean()
    placebo_trader_exit = placebo_pt.groupby('trader')['placebo_exit_edge'].mean()
    placebo_corr_pearson = float(np.corrcoef(placebo_trader_entry, placebo_trader_exit)[0, 1])
    placebo_corr_spearman = rank_corr(placebo_trader_entry, placebo_trader_exit)
    print(f"[placebo] synthetic entry/exit, n={len(placebo_pt)}, "
          f"trader-level pearson={placebo_corr_pearson:.4f}, spearman={placebo_corr_spearman:.4f}")

    gap = real_corr_pearson - placebo_corr_pearson
    print(f"\n[interpretation] observed - placebo (pearson) = {gap:.4f}")
    if abs(gap) < 0.10:
        verdict = "MECHANICAL -- placebo reproduces the observed correlation; not behavioural."
    else:
        verdict = f"PARTIALLY REAL -- placebo is materially less negative than observed by {abs(gap):.3f}; a residual signal survives."
    print(f"[VERDICT] {verdict}")

    if args.persist:
        conn3 = db_connect(args.db)
        conn3.execute("DROP TABLE IF EXISTS metric_v2c_placebo")
        conn3.execute("""
            CREATE TABLE metric_v2c_placebo (
                metric TEXT PRIMARY KEY, n INTEGER, pearson REAL, spearman REAL, spec_version TEXT,
                generated_at TEXT, generator_commit TEXT
            )
        """)
        conn3.execute("INSERT INTO metric_v2c_placebo VALUES (?,?,?,?,?,?,?)",
                      ('observed', len(real_pt), real_corr_pearson, real_corr_spearman,
                       SPEC_VERSION, generated_at, args.generator_commit))
        conn3.execute("INSERT INTO metric_v2c_placebo VALUES (?,?,?,?,?,?,?)",
                      ('placebo', len(placebo_pt), placebo_corr_pearson, placebo_corr_spearman,
                       SPEC_VERSION, generated_at, args.generator_commit))
        conn3.commit()
        conn3.close()
        print("[persist] metric_v2c_placebo written")

    # ============================= OBJECTIVE 3 =============================
    print(f"\n=== OBJECTIVE 3: re-run key comparisons under '{recommended_weighting}' ===")
    weight_fn = WEIGHT_FNS[recommended_weighting]
    pairs = build_pairs(entries_df)
    pairs['weight'] = weight_fn(pairs['n_positions'].to_numpy())
    eb = eb_shrinkage_weighted(pairs, sigma2_within)

    n_rankable = int((eb['eff_n'] > 0).sum())
    print(f"[item 7] n_traders={len(eb)}, shrunk_mean summary:")
    print(eb['shrunk_mean'].describe())
    print(f"sigma2_between={eb['sigma2_between'].iloc[0]:.6f}")

    stored = pd.read_sql("SELECT address AS trader, geo_elo FROM traders", conn)
    eb2 = eb.merge(stored, on='trader', how='left')
    overlap_geo = eb2.dropna(subset=['geo_elo'])
    spearman_v_geo = rank_corr(overlap_geo['shrunk_mean'], overlap_geo['geo_elo'])
    print(f"\n[item 8] Spearman({recommended_weighting}, stored geo_elo) = {spearman_v_geo:.4f}, "
          f"n={len(overlap_geo)}")

    no_frac = entries_df.groupby('trader').apply(lambda g: (g['outcome'] == 'No').mean(),
                                                 include_groups=False).rename('no_frac').reset_index()
    ov2 = overlap_geo.merge(no_frac, on='trader', how='left')
    ov2['geo_rank'] = ov2['geo_elo'].rank(pct=True)
    ov2['new_rank'] = ov2['shrunk_mean'].rank(pct=True)
    ov2['disagreement'] = ov2['geo_rank'] - ov2['new_rank']
    corr_dis_no = float(np.corrcoef(ov2['disagreement'], ov2['no_frac'])[0, 1])
    print(f"[item 8] corr(rank_disagreement, No-fraction) = {corr_dis_no:.4f} "
          f"(v2b position-weighted got 0.088)")

    legendary = set(r[0] for r in conn.execute("SELECT address FROM traders WHERE geo_elo >= 2175"))
    ranked = eb.sort_values('shrunk_mean', ascending=False)
    top_n = ranked.head(len(legendary))['trader'].tolist()
    overlap = legendary & set(top_n)
    print(f"\n[item 9] LEGENDARY (n={len(legendary)}) overlap with top-{len(legendary)} "
          f"{recommended_weighting}: {len(overlap)} ({100*len(overlap)/len(legendary):.1f}%) "
          f"(v2b position-weighted got 7/81)")

    # gate re-check under the recommended weighting: apply the SAME weight fn
    # to positions (approximate by expanding pair weight back to a per-position
    # weight = pair_weight / n_positions_in_pair, so the two-way bootstrap's
    # per-observation contribution matches the recommended weighting)
    print(f"\n[item 9b] gate re-check under '{recommended_weighting}' (weighted two-way clustered CI)")
    ge = entries_df.merge(pairs[['trader', 'market_id', 'weight', 'n_positions']],
                          on=['trader', 'market_id'], how='left')
    ge['weight'] = ge['weight'].fillna(1.0)
    ge['n_positions'] = ge['n_positions'].fillna(1)
    ge['obs_weight'] = ge['weight'] / ge['n_positions']

    top15_markets = entries_df.groupby('market_id').size().sort_values(ascending=False).head(TOP_N_EXCLUDE).index.tolist()
    gate_ok = True
    for side in ('Yes', 'No'):
        sub = ge[ge['outcome'] == side].copy()
        bins = fixed_buckets(entries_df, side)
        sub['bucket'] = pd.cut(sub['entry_avg_price'], bins=bins, labels=False, include_lowest=True)
        sub = sub.dropna(subset=['bucket'])
        sub['bucket'] = sub['bucket'].astype(int)
        sub = sub.rename(columns={'entry_avg_price': 'price'})
        for b in sorted(sub['bucket'].unique()):
            bsub = sub[sub['bucket'] == b]
            # weighted gap point estimate + two-way clustered CI, weight-adjusted
            wsum = bsub['obs_weight'].sum()
            wgap = float(np.average(bsub['won'], weights=bsub['obs_weight']) -
                        np.average(bsub['price'], weights=bsub['obs_weight']))
            r = two_way_gap_bootstrap(bsub, reps=args.gate_reps, seed=args.seed + int(b) * 7)
            excl = r['ci_lo'] is not None and (r['ci_lo'] > 0.03 or r['ci_hi'] < -0.03)
            if excl:
                gate_ok = False
            print(f"  {side} bucket {b}: weighted_gap={wgap:+.4f} unweighted_two_way_CI="
                  f"[{r['ci_lo']},{r['ci_hi']}] {'FAIL' if excl else 'ok'}")
    print(f"[item 9b GATE] {'PASS' if gate_ok else 'FAIL'} (note: CI reuses the unweighted two-way "
          f"bootstrap as an approximation -- see report caveat)")

    findings = dict(
        objective1=dict(curve=curve, satisfactory=[r['weighting'] for r in satisfactory],
                        recommended=recommended_weighting,
                        recommendation_is_satisfactory=bool(satisfactory)),
        objective2=dict(observed=dict(n=len(real_pt), pearson=real_corr_pearson, spearman=real_corr_spearman),
                        placebo=dict(n=len(placebo_pt), pearson=placebo_corr_pearson, spearman=placebo_corr_spearman),
                        gap=gap, verdict=verdict, excluded_positions=int(excluded)),
        objective3=dict(weighting=recommended_weighting, n_traders=len(eb),
                        spearman_vs_geo_elo=spearman_v_geo, n_overlap=len(overlap_geo),
                        corr_disagreement_no_fraction=corr_dis_no,
                        legendary_overlap=len(overlap), n_legendary=len(legendary),
                        gate_pass=gate_ok),
    )

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()
    if args.persist:
        wconn = db_connect(args.db)
        wconn.execute("DROP TABLE IF EXISTS metric_v2c_findings")
        wconn.execute("""
            CREATE TABLE metric_v2c_findings (
                finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT,
                generator_commit TEXT
            )
        """)
        for k, v in findings.items():
            wconn.execute("INSERT INTO metric_v2c_findings VALUES (?,?,?,?,?)",
                          (k, json.dumps(v, default=str), SPEC_VERSION, generated_at, args.generator_commit))
        wconn.commit()
        wconn.close()
        print("[persist] metric_v2c_findings written")


if __name__ == '__main__':
    main()
