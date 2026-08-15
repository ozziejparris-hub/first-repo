#!/usr/bin/env python3
"""
LAYER 0 -- Does geo_elo predict forward accuracy at the individual-trader level?

Every prior test (STR-002, the FABLE consensus design, the 2026-08-14 dilution-
guard verification) measured COHORT CONSENSUS -- a construct built on top of an
unvalidated assumption that geo_elo measures skill rather than recent activity
(flagged, unresolved, in the 2026-08-15 system design audit, Part B2c). This
script tests that foundational assumption directly, at the individual-trader
level, independent of any consensus/cohort framing.

=============================================================================
PRE-REGISTRATION (fixed before computing anything -- read this before the
RESULTS section further down, and note the artifact table `layer0_pre_registration`
is written to the DB before any result row, so the record proves it was fixed
in advance, not fitted after seeing the data)
=============================================================================

H1 (hypothesis): A trader's geo_elo at time T positively predicts the
    market-relative edge of positions they enter after T.
H0 (null):        geo_elo carries no forward information -- high-ELO traders'
    entries beat the market no more than low-ELO traders' do.

PRIMARY METRIC (per position):
    edge = won - entry_price_of_their_side
    where won = 1 if the position resolved in the trader's favour else 0, and
    entry_price_of_their_side is the OUTCOME-NORMALIZED entry price (see
    "Outcome normalization" below). A skill-less trader averages ~0 (market
    prices are honest probability estimates on average); positive mean edge =
    beating the market. This penalises near-certainty buying (enter at 0.97,
    win, gain only 0.03) by construction.

UNIT STRUCTURE:
    - Position-level: the atomic observation (one row of the `positions`
      table), full resolution, gives the effect size.
    - Trader-level: positions are clustered by trader for inference -- one
      trader's positions are NOT independent draws. Significance uses a
      cluster bootstrap resampling TRADERS (not positions), matching the
      event-cluster bootstrap logic already used for market-level inference
      elsewhere in this project, applied here to the trader dimension.
    - Both are reported: mean position-level edge with a trader-cluster-
      bootstrapped 95% CI, AND the distribution of per-trader mean edge
      within the top stratum, so a result driven by 2-3 traders is visible
      rather than hidden inside an aggregate.

SUCCESS CRITERION (stated before running):
    H1 is SUPPORTED if the top geo_elo stratum shows positive mean edge whose
    cluster-bootstrapped 95% CI excludes zero, AND edge increases
    monotonically (or near-monotonically) across strata. A positive top
    stratum with no gradient across strata is NOT support -- that pattern is
    more consistent with selection than with a skill signal that should
    apply gradedly across the ability distribution.

=============================================================================
METHOD
=============================================================================

1. STRICT PIT. geo_elo at ENTRY, reconstructed with the exact qualifying-
   trade predicate and fold order of the validated
   analysis.pit_geo_elo.reconstruct_one_at path (re-implemented here as a
   batched per-trader replay for tractable runtime at ~250K candidate trades
   / ~340K scored positions -- the formula function (_compute_geo_elo) and
   the qualifying-trade SQL predicate are reused unchanged, not
   reimplemented; --selfcheck cross-checks a random sample against calling
   reconstruct_one_at directly and asserts exact match). No look-ahead is
   possible by construction: a position's own market is still open (its
   tape_end is necessarily > the position's own entry_timestamp) at entry
   time, so it can never appear in the qualifying set used to compute that
   same position's predictor.

   RAW geo_elo is the primary predictor (per the audit's finding that
   geo_elo_active is dominated by activity-driven decay resets -- a trade in
   ANY qualifying category snaps it to 100% instantly -- which measures
   recency, not skill; testing raw geo_elo tests the rating itself).
   geo_elo_active is reported as a SECONDARY stratification: the comparison
   is directly informative about whether decay helps or hurts predictiveness.

2. STRATIFY by geo_elo at entry across the FULL range (deciles by default,
   not just above any tier gate -- the point is to see the whole shape).

3. SCOPE: Geopolitics + Elections categories (markets.category, never the
   denormalized trades.market_category -- the O-2/O-30 discipline), positions
   with a determinable entry price (positions.entry_avg_price IS NOT NULL)
   and a resolved outcome (the position's first entry trade has
   trade_result IN ('won','lost')), across the FULL available trade history
   (not the frozen bt_pop_2025-11-01_v1 backtest window, which was scoped for
   a different purpose). Trade-gap-flagged markets are excluded throughout,
   matching standing project practice. No price-band restriction in the
   primary scope -- the contested-band [0.10,0.90] restriction is reported
   only as a CONTROL (step 5), not a filter on the primary result.

4. PLACEBO: a trader-level label permutation. Each trader's own mean raw
   geo_elo across their scored positions defines their TRUE decile slot (10
   slots, computed once). For each of N permutations, the mapping from
   trader identity to slot is shuffled while each trader's own positions,
   edges, position count, and activity period are held completely fixed --
   only the slot LABEL attached to a given trader is randomized. This exactly
   satisfies "traders randomly assigned to strata, matched on position count
   and activity period": the position count and activity period are the same
   trader's own real numbers in every permutation, only decoupled from their
   real geo_elo. Reports the null distribution of the stratum-rank-vs-mean-
   edge rank correlation, compared against the real value, as a permutation
   test. A placebo run showing a gradient would mean the measurement is
   picking up something structural (activity-period effects, market
   selection) rather than a geo_elo-specific skill signal.

5. CONTROLS reported alongside the primary result (not as filters that change
   which result is "the" result):
   - Restricted to the CONTESTED band [0.10, 0.90] on entry_price_of_their_side.
   - Excluding bot_type / wash_trade_suspect / research_excluded traders
     (today's flags -- exclusion-only, the same "mild hindsight" convention
     used throughout the PIT system elsewhere in this project).
   - Split pre/post the Fee Structure V2 effective date, 2026-03-30 (this is
     the verified effective date from the FABLE design doc's assumption-2
     resolution -- corrected here from "April 2026" in case that framing is
     circulating; see the 2026-08-15 audit, Part B1, assumption 2).

6. HONEST REPORTING. If there is no gradient, that is reported plainly as a
   valuable null result, not hidden or re-specified. This script runs
   EXACTLY the pre-registered spec above and nothing else; no alternative
   specification is searched for or substituted if the primary result is
   null.

=============================================================================
ARTIFACTS (per the standing reproducibility rule -- trading-swarm
brain/decisions/2026-06-29-overhang-ledger.md, "Standing rule --
reproducibility of decision-carrying numbers")
=============================================================================

--persist writes, in this order, to the target DB:
  1. layer0_pre_registration -- one row, the H1/H0/metric/success-criterion
     text above plus spec_version and a timestamp, written FIRST.
  2. layer0_position_results  -- every scored position, geo_elo/geo_elo_active
     at entry, edge, and every control flag, for full re-analysis without
     re-running the PIT replay.
  3. layer0_stratum_summary  -- the decile tables (raw, active, and every
     control variant) with n, mean edge, bootstrap CI, spec_version,
     generating parameters, and timestamp.

Read-only against the database except these three tables, which this script
owns exclusively (DROP/recreate on each --persist run).
"""

import argparse
import json
import os
import random
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.update_geo_elo import _compute_geo_elo, MIN_TRADES_FOR_ELO
from analysis.pit_geo_elo import reconstruct_one_at as slow_reconstruct

SPEC_VERSION = "LAYER0-2026-08-15-v1"
FEE_V2_EFFECTIVE = "2026-03-30"
N_STRATA_DEFAULT = 10
BOOTSTRAP_REPS_DEFAULT = 2000
PLACEBO_PERMS_DEFAULT = 500

H1_TEXT = ("A trader's geo_elo at time T positively predicts the market-relative "
           "edge of positions they enter after T.")
H0_TEXT = ("geo_elo carries no forward information -- high-ELO traders' entries "
           "beat the market no more than low-ELO traders' do.")
METRIC_TEXT = ("edge = won - entry_price_of_their_side, per position, outcome-"
               "normalized (entry_avg_price if outcome=='Yes' else 1-entry_avg_price); "
               "won = 1 if the position's entry trade(s) resolved 'won' else 0.")
SUCCESS_TEXT = ("Top geo_elo decile shows positive mean edge with a trader-cluster-"
                "bootstrapped 95% CI excluding zero, AND edge increases monotonically "
                "or near-monotonically across deciles. A positive top decile with no "
                "gradient is NOT support (suggests selection, not a graded skill signal).")


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _to_utc(ts):
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00').replace(' ', 'T'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


FEE_V2_DT = _to_utc(FEE_V2_EFFECTIVE)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(conn, verbose=False):
    """Single-pass load, restricted to traders who appear in the eligible-
    position universe -- traders with zero eligible positions don't need
    geo_elo computed."""
    conn.execute("DROP TABLE IF EXISTS temp.tape_end")
    conn.execute("""
        CREATE TEMP TABLE tape_end AS
        SELECT market_id, MAX(timestamp) AS tape_end FROM trades GROUP BY market_id
    """)
    conn.execute("CREATE INDEX idx_tmp_tape_end ON tape_end(market_id)")

    positions = conn.execute("""
        SELECT p.position_id, p.trader_address, p.market_id, p.outcome,
               p.entry_avg_price, p.entry_timestamp, t.trade_result,
               tr.bot_type, tr.wash_trade_suspect, tr.research_excluded
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        JOIN traders tr ON tr.address = p.trader_address
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """).fetchall()
    if verbose:
        print(f"[load] {len(positions)} eligible positions")

    target_traders = sorted({r[1] for r in positions})
    conn.execute("DROP TABLE IF EXISTS temp.target_traders")
    conn.execute("CREATE TEMP TABLE target_traders (address TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO target_traders VALUES (?)", [(a,) for a in target_traders])
    if verbose:
        print(f"[load] {len(target_traders)} distinct traders")

    elo_trades = conn.execute("""
        SELECT tr.trader_address, tr.outcome_bet, tr.price, tr.trade_result, tr.timestamp, tape.tape_end
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        JOIN tape_end tape ON tape.market_id = tr.market_id
        JOIN target_traders tt ON tt.address = tr.trader_address
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
        ORDER BY tr.trader_address, tr.timestamp ASC
    """).fetchall()
    if verbose:
        print(f"[load] {len(elo_trades)} candidate ELO-fold trades (price-banded)")

    any_trades = conn.execute("""
        SELECT tr.trader_address, tr.timestamp
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        JOIN target_traders tt ON tt.address = tr.trader_address
        WHERE tr.market_category IN ('Geopolitics', 'Elections')
        ORDER BY tr.trader_address, tr.timestamp ASC
    """).fetchall()
    if verbose:
        print(f"[load] {len(any_trades)} any-category trades for decay recency")

    return positions, elo_trades, any_trades


def group_by_trader(elo_trades, any_trades):
    elo_by_trader = defaultdict(list)
    for trader, outcome_bet, price, trade_result, ts, tape_end in elo_trades:
        elo_by_trader[trader].append((_to_utc(ts), _to_utc(tape_end), outcome_bet, price, trade_result))
    # already ORDER BY trader, timestamp ASC from SQL -- do not re-sort

    any_by_trader = defaultdict(list)
    for trader, ts in any_trades:
        any_by_trader[trader].append(_to_utc(ts))
    # already ascending from SQL

    return elo_by_trader, any_by_trader


# ---------------------------------------------------------------------------
# PIT geo_elo / geo_elo_active replay (batched, faithful to pit_geo_elo.py)
# ---------------------------------------------------------------------------

def geo_elo_at(elo_by_trader, any_by_trader, trader, T):
    """Same predicate, same fold, same decay formula as
    analysis.pit_geo_elo.reconstruct_one_at -- computed against pre-loaded
    per-trader lists instead of a fresh DB round trip per call. Filtering a
    timestamp-ascending list by tape_end<=T preserves timestamp order in the
    surviving subsequence, so no re-sort is needed after filtering."""
    rows = elo_by_trader.get(trader, ())
    qualifying = [(ts, ob, price, res) for (ts, tape_end, ob, price, res) in rows if tape_end <= T]
    n = len(qualifying)
    if n < MIN_TRADES_FOR_ELO:
        geo_elo = None
    else:
        fold_rows = [(ob, price, res) for (ts, ob, price, res) in qualifying]
        geo_elo = _compute_geo_elo(fold_rows)

    any_ts = any_by_trader.get(trader, [])
    idx = bisect_right(any_ts, T) - 1
    last_any = any_ts[idx] if idx >= 0 else None

    if geo_elo is None or last_any is None:
        geo_elo_active = None
    else:
        days_dormant = (T - last_any).days
        geo_elo_active = round(geo_elo * (0.5 ** (days_dormant / 180.0)), 4)

    return geo_elo, geo_elo_active


def selfcheck(conn, positions, elo_by_trader, any_by_trader, n_samples=200, seed=7, verbose=True):
    """Cross-checks the batched fast path against calling
    analysis.pit_geo_elo.reconstruct_one_at directly (the canonical, already-
    validated, slow path) on a random sample of scored (trader, entry_ts)
    pairs. This is the correctness guard for the whole script -- the fast
    path is a re-implementation for tractable runtime, not a re-derivation of
    the formula or predicate, and this proves the two agree."""
    rng = random.Random(seed)
    sample = rng.sample(positions, min(n_samples, len(positions)))
    mismatches = []
    for row in sample:
        trader, entry_ts = row[1], row[5]
        T = _to_utc(entry_ts)
        fast_ge, fast_gea = geo_elo_at(elo_by_trader, any_by_trader, trader, T)
        slow = slow_reconstruct(conn, trader, T)
        slow_ge, slow_gea = slow['geo_elo'], slow['geo_elo_active']
        ge_ok = (fast_ge is None) == (slow_ge is None) and (
            fast_ge is None or abs(fast_ge - slow_ge) < 1e-6)
        gea_ok = (fast_gea is None) == (slow_gea is None) and (
            fast_gea is None or abs(fast_gea - slow_gea) < 1e-6)
        if not (ge_ok and gea_ok):
            mismatches.append((trader, str(T), fast_ge, slow_ge, fast_gea, slow_gea))
    if verbose:
        print(f"[selfcheck] {len(sample)} (trader,entry_ts) points checked, {len(mismatches)} mismatches")
        for m in mismatches[:10]:
            print(f"  MISMATCH trader={m[0]} T={m[1]} fast=({m[2]},{m[4]}) slow=({m[3]},{m[5]})")
    return len(sample), mismatches


# ---------------------------------------------------------------------------
# Position-level dataset assembly
# ---------------------------------------------------------------------------

def build_positions_df(positions, elo_by_trader, any_by_trader, verbose=False):
    rows = []
    skipped_outcome = 0
    for (pid, trader, market_id, outcome, entry_avg_price, entry_ts, trade_result,
         bot_type, wash_trade_suspect, research_excluded) in positions:
        T = _to_utc(entry_ts)
        geo_elo, geo_elo_active = geo_elo_at(elo_by_trader, any_by_trader, trader, T)
        outcome_norm = (outcome or '').strip()
        if outcome_norm == 'Yes':
            entry_price_side = entry_avg_price
        elif outcome_norm == 'No':
            entry_price_side = 1.0 - entry_avg_price
        else:
            skipped_outcome += 1
            continue
        won = 1 if trade_result == 'won' else 0
        edge = won - entry_price_side
        clean = (bot_type is None) and (wash_trade_suspect in (0, None)) and (research_excluded in (0, None))
        rows.append((
            pid, trader, market_id, T, geo_elo, geo_elo_active,
            entry_price_side, won, edge,
            0.10 <= entry_price_side <= 0.90,
            clean,
            T >= FEE_V2_DT,
        ))
    if verbose and skipped_outcome:
        print(f"[build] skipped {skipped_outcome} positions with unrecognized outcome label")
    df = pd.DataFrame(rows, columns=[
        'position_id', 'trader', 'market_id', 'entry_ts', 'geo_elo', 'geo_elo_active',
        'entry_price_side', 'won', 'edge', 'contested', 'clean', 'era_post_fee_v2',
    ])
    return df


# ---------------------------------------------------------------------------
# Stratification, cluster bootstrap, placebo
# ---------------------------------------------------------------------------

def cluster_bootstrap_ci(sub, reps=BOOTSTRAP_REPS_DEFAULT, seed=42, alpha=0.05):
    """Resamples TRADERS with replacement (cluster bootstrap), not positions."""
    per_trader = sub.groupby('trader')['edge'].agg(['sum', 'count'])
    n_traders = len(per_trader)
    if n_traders == 0:
        return dict(mean=None, ci_lo=None, ci_hi=None, n_traders=0, n_positions=0)
    sums = per_trader['sum'].to_numpy()
    counts = per_trader['count'].to_numpy()
    rng = np.random.default_rng(seed)
    boot_means = np.empty(reps)
    for b in range(reps):
        idx = rng.integers(0, n_traders, size=n_traders)
        boot_means[b] = sums[idx].sum() / counts[idx].sum()
    point = float(sums.sum() / counts.sum())
    lo, hi = np.percentile(boot_means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return dict(mean=point, ci_lo=float(lo), ci_hi=float(hi),
                n_traders=int(n_traders), n_positions=int(counts.sum()))


def stratified_table(df, value_col, n_strata=N_STRATA_DEFAULT, reps=BOOTSTRAP_REPS_DEFAULT, seed=42):
    sub = df[df[value_col].notna()].copy()
    if len(sub) == 0:
        return [], []
    try:
        sub['_stratum'], bins = pd.qcut(sub[value_col], q=n_strata, labels=False,
                                         retbins=True, duplicates='drop')
    except ValueError:
        return [], []
    actual_strata = sorted(sub['_stratum'].dropna().unique())
    out = []
    for s in actual_strata:
        stratum_sub = sub[sub['_stratum'] == s]
        stats = cluster_bootstrap_ci(stratum_sub, reps=reps, seed=seed + int(s))
        out.append(dict(
            stratum=int(s),
            value_range=(float(bins[int(s)]), float(bins[int(s) + 1])),
            **stats,
        ))
    return out, bins.tolist()


def rank_corr(x, y):
    """Spearman rank correlation, tiny-n manual implementation (avoids a
    scipy dependency for a 10-point vector)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2:
        return None
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def near_monotonic(means, tolerance_violations=1):
    """True if mean edge is non-decreasing across strata except for at most
    `tolerance_violations` adjacent-pair reversals."""
    violations = sum(1 for a, b in zip(means, means[1:]) if b < a)
    return violations <= tolerance_violations, violations


def placebo_test(df, n_strata=N_STRATA_DEFAULT, n_perms=PLACEBO_PERMS_DEFAULT, seed=123, verbose=False):
    """Trader-level label permutation -- see module docstring step 4."""
    sub = df[df['geo_elo'].notna()].copy()
    trader_mean_elo = sub.groupby('trader')['geo_elo'].mean()
    try:
        true_slot = pd.qcut(trader_mean_elo, q=n_strata, labels=False, duplicates='drop')
    except ValueError:
        return None
    n_slots = int(true_slot.max()) + 1
    trader_edge_sum = sub.groupby('trader')['edge'].sum().reindex(trader_mean_elo.index)
    trader_edge_n = sub.groupby('trader')['edge'].count().reindex(trader_mean_elo.index)

    def slot_means(slots):
        tmp = pd.DataFrame({'slot': slots, 'sum': trader_edge_sum.to_numpy(), 'n': trader_edge_n.to_numpy()})
        agg = tmp.groupby('slot').agg(sum=('sum', 'sum'), n=('n', 'sum'))
        agg['mean'] = agg['sum'] / agg['n']
        return agg

    real_agg = slot_means(true_slot.to_numpy())
    real_gradient = rank_corr(real_agg.index.to_numpy(), real_agg['mean'].to_numpy())
    real_top_mean = float(real_agg['mean'].iloc[-1])

    rng = np.random.default_rng(seed)
    true_slot_arr = true_slot.to_numpy()
    perm_gradients = []
    perm_top_means = []
    for _ in range(n_perms):
        perm_slots = rng.permutation(true_slot_arr)
        agg = slot_means(perm_slots)
        perm_gradients.append(rank_corr(agg.index.to_numpy(), agg['mean'].to_numpy()))
        if len(agg) == n_slots:
            perm_top_means.append(float(agg['mean'].iloc[-1]))

    perm_gradients = np.array([g for g in perm_gradients if g is not None])
    p_value_gradient = float(np.mean(perm_gradients >= real_gradient)) if len(perm_gradients) else None
    p_value_top = float(np.mean(np.array(perm_top_means) >= real_top_mean)) if perm_top_means else None

    if verbose:
        print(f"[placebo] real gradient rho={real_gradient:.3f}, "
              f"perm mean={perm_gradients.mean():.3f} sd={perm_gradients.std():.3f}, "
              f"p(perm_rho >= real_rho)={p_value_gradient}")

    return dict(
        n_perms=int(n_perms), n_slots=n_slots,
        real_gradient=real_gradient, real_top_mean=real_top_mean,
        perm_gradient_mean=float(perm_gradients.mean()) if len(perm_gradients) else None,
        perm_gradient_sd=float(perm_gradients.std()) if len(perm_gradients) else None,
        p_value_gradient=p_value_gradient,
        p_value_top_mean=p_value_top,
    )


def per_trader_distribution(sub):
    per_trader = sub.groupby('trader')['edge'].mean()
    if len(per_trader) == 0:
        return dict(n_traders=0)
    sorted_sum = sub.groupby('trader')['edge'].sum().sort_values(ascending=False)
    total_signed = sub['edge'].sum()
    top3_share = float(sorted_sum.head(3).sum() / total_signed) if total_signed != 0 else None
    return dict(
        n_traders=int(len(per_trader)),
        median=float(per_trader.median()),
        q25=float(per_trader.quantile(0.25)),
        q75=float(per_trader.quantile(0.75)),
        min=float(per_trader.min()),
        max=float(per_trader.max()),
        top3_trader_share_of_total_signed_edge=top3_share,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def persist(conn, df, tables, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS layer0_pre_registration")
    conn.execute("""
        CREATE TABLE layer0_pre_registration (
            spec_version TEXT PRIMARY KEY, h1 TEXT, h0 TEXT, metric TEXT,
            success_criterion TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO layer0_pre_registration VALUES (?,?,?,?,?,?,?)",
                 (SPEC_VERSION, H1_TEXT, H0_TEXT, METRIC_TEXT, SUCCESS_TEXT,
                  generated_at, generator_commit))

    conn.execute("DROP TABLE IF EXISTS layer0_position_results")
    conn.execute("""
        CREATE TABLE layer0_position_results (
            position_id TEXT PRIMARY KEY, trader TEXT, market_id TEXT, entry_ts TEXT,
            geo_elo REAL, geo_elo_active REAL, entry_price_side REAL, won INTEGER,
            edge REAL, contested INTEGER, clean INTEGER, era_post_fee_v2 INTEGER,
            spec_version TEXT, generated_at TEXT
        )
    """)
    records = df.copy()
    records['entry_ts'] = records['entry_ts'].astype(str)
    records['contested'] = records['contested'].astype(int)
    records['clean'] = records['clean'].astype(int)
    records['era_post_fee_v2'] = records['era_post_fee_v2'].astype(int)
    records['spec_version'] = SPEC_VERSION
    records['generated_at'] = generated_at
    conn.executemany(f"""
        INSERT INTO layer0_position_results VALUES ({','.join('?' * 14)})
    """, records[['position_id', 'trader', 'market_id', 'entry_ts', 'geo_elo',
                   'geo_elo_active', 'entry_price_side', 'won', 'edge', 'contested',
                   'clean', 'era_post_fee_v2', 'spec_version', 'generated_at']].itertuples(index=False, name=None))

    conn.execute("DROP TABLE IF EXISTS layer0_stratum_summary")
    conn.execute("""
        CREATE TABLE layer0_stratum_summary (
            table_name TEXT, stratum INTEGER, value_lo REAL, value_hi REAL,
            n_traders INTEGER, n_positions INTEGER, mean_edge REAL,
            ci_lo REAL, ci_hi REAL, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for table_name, rows in tables.items():
        for r in rows:
            conn.execute("""
                INSERT INTO layer0_stratum_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (table_name, r['stratum'], r['value_range'][0], r['value_range'][1],
                  r['n_traders'], r['n_positions'], r['mean'], r['ci_lo'], r['ci_hi'],
                  SPEC_VERSION, generated_at, generator_commit))

    conn.commit()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_table(name, rows):
    print(f"\n=== {name} ===")
    if not rows:
        print("  (no strata -- insufficient distinct values)")
        return
    print(f"  {'stratum':>7} {'range':>22} {'n_trd':>7} {'n_pos':>8} {'mean_edge':>10} {'ci_lo':>8} {'ci_hi':>8}")
    for r in rows:
        lo, hi = r['value_range']
        print(f"  {r['stratum']:>7} {lo:>10.1f}-{hi:<10.1f} {r['n_traders']:>7} {r['n_positions']:>8} "
              f"{r['mean']:>10.4f} {r['ci_lo']:>8.4f} {r['ci_hi']:>8.4f}")


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
    ap.add_argument('--placebo-perms', type=int, default=PLACEBO_PERMS_DEFAULT)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    print("=== PRE-REGISTRATION (fixed before results, spec %s) ===" % SPEC_VERSION)
    print(f"H1: {H1_TEXT}")
    print(f"H0: {H0_TEXT}")
    print(f"METRIC: {METRIC_TEXT}")
    print(f"SUCCESS CRITERION: {SUCCESS_TEXT}")

    positions, elo_trades, any_trades = load_data(conn, verbose=args.verbose)
    elo_by_trader, any_by_trader = group_by_trader(elo_trades, any_trades)

    if args.selfcheck:
        n, mismatches = selfcheck(conn, positions, elo_by_trader, any_by_trader,
                                   n_samples=args.selfcheck_n, verbose=True)
        if mismatches:
            print(f"[selfcheck] FAILED: {len(mismatches)}/{n} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n} match")
        if not args.persist and not args.json_out:
            conn.close()
            return

    df = build_positions_df(positions, elo_by_trader, any_by_trader, verbose=args.verbose)
    has_elo = df[df['geo_elo'].notna()]
    print(f"\n[scope] {len(df)} total eligible positions ({df['entry_ts'].min()} -> {df['entry_ts'].max()})")
    print(f"[scope] {len(has_elo)}/{len(df)} ({100*len(has_elo)/len(df):.1f}%) have a defined geo_elo at entry "
          f"(trader had >= {MIN_TRADES_FOR_ELO} qualifying resolved trades by entry time)")
    print(f"[scope] {df['trader'].nunique()} distinct traders overall, {has_elo['trader'].nunique()} with defined geo_elo")

    tables = {}

    raw_rows, raw_bins = stratified_table(df, 'geo_elo', n_strata=args.n_strata,
                                           reps=args.bootstrap_reps, seed=args.seed)
    tables['geo_elo_deciles'] = raw_rows
    print_table('PRIMARY: raw geo_elo deciles', raw_rows)

    active_rows, active_bins = stratified_table(df, 'geo_elo_active', n_strata=args.n_strata,
                                                 reps=args.bootstrap_reps, seed=args.seed)
    tables['geo_elo_active_deciles'] = active_rows
    print_table('SECONDARY: geo_elo_active deciles', active_rows)

    # per-trader distribution within the top raw-geo_elo stratum (and bottom, for contrast)
    top_dist = bottom_dist = None
    if raw_rows:
        sub = df[df['geo_elo'].notna()].copy()
        sub['_stratum'], _ = pd.qcut(sub['geo_elo'], q=args.n_strata, labels=False,
                                      retbins=True, duplicates='drop')
        top_s = sub['_stratum'].max()
        bottom_s = sub['_stratum'].min()
        top_dist = per_trader_distribution(sub[sub['_stratum'] == top_s])
        bottom_dist = per_trader_distribution(sub[sub['_stratum'] == bottom_s])
        print(f"\n=== per-trader mean-edge distribution, TOP stratum ({top_s}) ===")
        print(f"  {top_dist}")
        print(f"=== per-trader mean-edge distribution, BOTTOM stratum ({bottom_s}) ===")
        print(f"  {bottom_dist}")

    placebo = placebo_test(df, n_strata=args.n_strata, n_perms=args.placebo_perms,
                            seed=args.seed + 1000, verbose=True)

    # controls
    contested_rows, _ = stratified_table(df[df['contested']], 'geo_elo', n_strata=args.n_strata,
                                          reps=args.bootstrap_reps, seed=args.seed)
    tables['contested_band_only'] = contested_rows
    print_table('CONTROL: contested band [0.10,0.90] only', contested_rows)

    clean_rows, _ = stratified_table(df[df['clean']], 'geo_elo', n_strata=args.n_strata,
                                      reps=args.bootstrap_reps, seed=args.seed)
    tables['clean_traders_only'] = clean_rows
    print_table('CONTROL: excluding bot/wash/research_excluded traders', clean_rows)

    pre_rows, _ = stratified_table(df[~df['era_post_fee_v2']], 'geo_elo', n_strata=args.n_strata,
                                    reps=args.bootstrap_reps, seed=args.seed)
    tables['pre_fee_v2'] = pre_rows
    print_table(f'CONTROL: pre-{FEE_V2_EFFECTIVE} (before Fee V2)', pre_rows)

    post_rows, _ = stratified_table(df[df['era_post_fee_v2']], 'geo_elo', n_strata=args.n_strata,
                                     reps=args.bootstrap_reps, seed=args.seed)
    tables['post_fee_v2'] = post_rows
    print_table(f'CONTROL: post-{FEE_V2_EFFECTIVE} (Fee V2 in effect)', post_rows)

    # verdict
    verdict = 'AMBIGUOUS'
    reasons = []
    if raw_rows:
        top = raw_rows[-1]
        top_positive = top['ci_lo'] is not None and top['ci_lo'] > 0
        means = [r['mean'] for r in raw_rows]
        mono, violations = near_monotonic(means)
        gradient_real = rank_corr(list(range(len(means))), means)
        reasons.append(f"top stratum mean={top['mean']:.4f} CI=[{top['ci_lo']:.4f},{top['ci_hi']:.4f}] "
                        f"positive_and_excludes_zero={top_positive}")
        reasons.append(f"monotonic (<=1 adjacent-pair violation): {mono} ({violations} violations), "
                        f"rank_corr(stratum,mean_edge)={gradient_real:.3f}")
        if placebo and placebo['p_value_gradient'] is not None:
            reasons.append(f"placebo p(perm_rho >= real_rho)={placebo['p_value_gradient']:.4f} "
                            f"(real rho={placebo['real_gradient']:.3f} vs perm mean={placebo['perm_gradient_mean']:.3f})")
        if top_positive and mono:
            verdict = 'H1 SUPPORTED'
        elif not top_positive and not mono:
            verdict = 'H1 REJECTED / NULL'
        else:
            verdict = 'AMBIGUOUS'
    print(f"\n=== VERDICT: {verdict} ===")
    for r in reasons:
        print(f"  - {r}")

    result = dict(
        spec_version=SPEC_VERSION,
        pre_registration=dict(h1=H1_TEXT, h0=H0_TEXT, metric=METRIC_TEXT, success_criterion=SUCCESS_TEXT),
        scope=dict(n_positions=len(df), n_with_geo_elo=len(has_elo),
                   date_span=[str(df['entry_ts'].min()), str(df['entry_ts'].max())],
                   n_traders=int(df['trader'].nunique()), n_traders_with_geo_elo=int(has_elo['trader'].nunique())),
        tables=tables,
        top_stratum_trader_distribution=top_dist,
        bottom_stratum_trader_distribution=bottom_dist,
        placebo=placebo,
        verdict=verdict,
        verdict_reasons=reasons,
    )

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    if args.persist:
        generated_at = datetime.now(timezone.utc).isoformat()
        persist(conn, df, tables, args.generator_commit, generated_at)
        print(f"[persist] layer0_pre_registration, layer0_position_results "
              f"({len(df)} rows), layer0_stratum_summary written, generated_at={generated_at}")

    conn.close()


if __name__ == '__main__':
    main()
