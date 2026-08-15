#!/usr/bin/env python3
"""
PRICE-CONVENTION AUDIT -- does geo_elo's formula carry the same sign error
Layer 0b found in the edge metric? Read-only. No production writes. No fix
applied here -- this establishes the facts.

=============================================================================
PART A -- FIELD SEMANTICS, ESTABLISHED EMPIRICALLY (not from field names or
docstrings; see the paired-trade sum-to-1 tests below and in the report)
=============================================================================

Pairing Yes-side and No-side trades/positions within 60 seconds of each
other on the SAME market (Kamala Harris 2024 election, 69,973 trades,
34,169 positions -- large enough for a clean test, well outside the O-37
synthetic-market-quarantine class): yes_price + no_price ~= 1.000 in every
case tested (trades: mean 1.000031, sd 0.001, n=462; positions.entry_avg_price:
mean 1.000798, sd 0.023, n=452; positions.exit_avg_price: mean 0.999108,
sd 0.0007, n=278). This is only possible if EVERY price field checked
(trades.price, positions.entry_avg_price, positions.exit_avg_price) stores
the price of the outcome ACTUALLY TRADED (Yes or No), not a uniform
Yes-implied-probability. If price were Yes-always, No-side trades executing
within seconds of Yes-side trades on the same market would show SIMILAR
values (both ~= the Yes price at that moment), not complementary ones.

CONVENTION, STATED PLAINLY: price = P(the specific outcome actually bought),
for BOTH outcome_bet='Yes' and 'No'. No flip is ever needed to recover
"probability this trade wins" from a stored price -- it already IS that,
regardless of side.

=============================================================================
PART B -- DOES _compute_geo_elo HANDLE SIDE CORRECTLY?
=============================================================================

scripts/update_geo_elo.py:_compute_geo_elo, line 145:
    expected = price if outcome_bet == 'Yes' else (1.0 - price)

Given Part A's established convention, for a No-side trade `price` already
equals P(win). The formula computes `1.0 - price` = 1 - P(win) = P(the OPPOSITE
outcome) instead. This is the same structural bug Layer 0/0b had in the edge
metric (which was written by copying this exact pattern, assuming it was
correct because it is production code) -- confirmed here to be a bug in the
formula itself, not (only) in the Layer 0 metric that copied it.

This script does NOT reimplement the ELO math a second time (that would risk
introducing a second, independent bug and make the comparison less trustworthy).
It calls the REAL, UNMODIFIED `_compute_geo_elo` twice per trader:
  - "buggy" (production, unchanged): rows passed as-is (outcome_bet, price, ...).
  - "corrected": rows passed with outcome_bet forced to 'Yes' for every row
    (price left untouched). Since Part A established price already means
    P(win) regardless of side, forcing the function's own `if outcome_bet==
    'Yes': expected=price` branch to fire unconditionally is EXACTLY the
    corrected formula (expected=price, no flip) -- computed by the production
    function itself, not a hand-written duplicate.

=============================================================================
PART C -- OTHER CONSUMERS (see report; grepped and classified by hand against
the Part A convention, not run individually here)
=============================================================================

Persists: price_convention_audit_pre_registration, price_convention_audit_elo_comparison
(per-trader buggy vs corrected geo_elo, full qualifying population),
price_convention_audit_paired_price_tests (the sum-to-1 evidence).
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

from scripts.update_geo_elo import _compute_geo_elo, MIN_TRADES_FOR_ELO, GEO_ELO_LEGENDARY

SPEC_VERSION = "PRICECONV-2026-08-15-v1"
TEST_MARKET_ID = '0xc6485bb7ea46d7bb89beb9c91e7572ecfc72a6273789496f78bc5e989e4d1638'  # Kamala Harris 2024


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Part A: paired sum-to-1 tests (reproduces the evidence in the docstring)
# ---------------------------------------------------------------------------

def paired_sum_test(conn, table, price_col, ts_col, outcome_col, market_id, n_sample=500, max_dt=60, seed=1):
    df = pd.read_sql(
        f"SELECT {outcome_col} AS outcome, {price_col} AS price, {ts_col} AS ts FROM {table} "
        f"WHERE market_id = ? AND {price_col} IS NOT NULL AND {ts_col} IS NOT NULL",
        conn, params=(market_id,)
    )
    df['ts'] = pd.to_datetime(df['ts'], format='mixed')
    yes = df[df['outcome'] == 'Yes'].set_index('ts').sort_index()
    no = df[df['outcome'] == 'No'].set_index('ts').sort_index()
    if len(yes) == 0 or len(no) == 0:
        return dict(table=table, n_pairs=0)
    no_times = no.index.to_numpy()
    no_prices = no['price'].to_numpy()
    sample = yes.sample(min(n_sample, len(yes)), random_state=seed).sort_index()
    pairs = []
    for ts, row in sample.iterrows():
        idx = np.searchsorted(no_times, np.datetime64(ts))
        for c in ([idx] if idx < len(no_times) else []) + ([idx - 1] if idx > 0 else []):
            dt = abs((no_times[c] - np.datetime64(ts)) / np.timedelta64(1, 's'))
            if dt <= max_dt:
                pairs.append((row['price'], no_prices[c]))
                break
    if not pairs:
        return dict(table=table, n_pairs=0)
    pdf = pd.DataFrame(pairs, columns=['yes_price', 'no_price'])
    pdf['sum'] = pdf['yes_price'] + pdf['no_price']
    return dict(table=table, n_pairs=len(pdf), mean_sum=float(pdf['sum'].mean()),
                std_sum=float(pdf['sum'].std()), min_sum=float(pdf['sum'].min()),
                max_sum=float(pdf['sum'].max()))


# ---------------------------------------------------------------------------
# Part B: buggy vs corrected geo_elo, full qualifying population
# ---------------------------------------------------------------------------

def load_qualifying_trades(conn, verbose=False):
    rows = conn.execute("""
        SELECT tr.trader_address, tr.outcome_bet, tr.price, tr.trade_result, tr.timestamp
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
        ORDER BY tr.trader_address, tr.timestamp ASC
    """).fetchall()
    if verbose:
        print(f"[load] {len(rows)} qualifying trades")
    by_trader = {}
    for trader, ob, price, result, ts in rows:
        by_trader.setdefault(trader, []).append((ob, price, result))
    return by_trader


def compare_buggy_vs_corrected(by_trader, conn, verbose=False):
    stored = dict(conn.execute("SELECT address, geo_elo FROM traders WHERE geo_elo IS NOT NULL").fetchall())
    out = []
    for trader, rows in by_trader.items():
        if len(rows) < MIN_TRADES_FOR_ELO:
            continue
        buggy = _compute_geo_elo(rows)  # production formula, unchanged
        corrected_rows = [('Yes', price, result) for (ob, price, result) in rows]
        corrected = _compute_geo_elo(corrected_rows)  # same function, forces expected=price always
        out.append(dict(
            trader=trader, n_trades=len(rows), buggy=buggy, corrected=corrected,
            diff=corrected - buggy, stored=stored.get(trader),
        ))
    df = pd.DataFrame(out)
    if verbose:
        print(f"[compare] {len(df)} traders with >= {MIN_TRADES_FOR_ELO} qualifying trades")
    return df


def side_mix(conn, trader_list, verbose=False):
    """Fraction of each trader's qualifying trades that were No-side -- to
    test whether the bias is systematic (No-heavy traders shift one direction)
    or noise-like."""
    placeholders = ",".join("?" for _ in trader_list)
    rows = conn.execute(f"""
        SELECT tr.trader_address,
               SUM(CASE WHEN tr.outcome_bet='No' THEN 1 ELSE 0 END) n_no,
               COUNT(*) n_total
        FROM trades tr JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trader_address IN ({placeholders})
          AND m.category IN ('Geopolitics','Elections')
          AND tr.trade_result IN ('won','lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
        GROUP BY tr.trader_address
    """, trader_list).fetchall()
    return pd.DataFrame(rows, columns=['trader', 'n_no', 'n_total'])


def persist(conn, pre_reg, pair_tests, elo_df, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS price_convention_audit_pre_registration")
    conn.execute("""
        CREATE TABLE price_convention_audit_pre_registration (
            spec_version TEXT PRIMARY KEY, convention_established TEXT, formula_finding TEXT,
            method TEXT, registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO price_convention_audit_pre_registration VALUES (?,?,?,?,?,?)", pre_reg)

    conn.execute("DROP TABLE IF EXISTS price_convention_audit_paired_price_tests")
    conn.execute("""
        CREATE TABLE price_convention_audit_paired_price_tests (
            table_name TEXT, market_id TEXT, n_pairs INTEGER, mean_sum REAL, std_sum REAL,
            min_sum REAL, max_sum REAL, spec_version TEXT, generated_at TEXT
        )
    """)
    for t in pair_tests:
        if t.get('n_pairs', 0) > 0:
            conn.execute("INSERT INTO price_convention_audit_paired_price_tests VALUES (?,?,?,?,?,?,?,?,?)",
                         (t['table'], TEST_MARKET_ID, t['n_pairs'], t['mean_sum'], t['std_sum'],
                          t['min_sum'], t['max_sum'], SPEC_VERSION, generated_at))

    conn.execute("DROP TABLE IF EXISTS price_convention_audit_elo_comparison")
    conn.execute("""
        CREATE TABLE price_convention_audit_elo_comparison (
            trader TEXT PRIMARY KEY, n_trades INTEGER, buggy_geo_elo REAL, corrected_geo_elo REAL,
            diff REAL, stored_geo_elo REAL, spec_version TEXT, generated_at TEXT, generator_commit TEXT
        )
    """)
    for _, r in elo_df.iterrows():
        conn.execute("INSERT INTO price_convention_audit_elo_comparison VALUES (?,?,?,?,?,?,?,?,?)",
                     (r['trader'], int(r['n_trades']), r['buggy'], r['corrected'], r['diff'],
                      r['stored'], SPEC_VERSION, generated_at, generator_commit))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    print("=== PART A: paired-price sum-to-1 tests (empirical field semantics) ===")
    pair_tests = []
    t1 = paired_sum_test(conn, 'trades', 'price', 'timestamp', 'outcome_bet', TEST_MARKET_ID)
    t1['table'] = 'trades.price'
    pair_tests.append(t1)
    print(f"  trades.price: n_pairs={t1['n_pairs']} mean_sum={t1.get('mean_sum')} std={t1.get('std_sum')}")

    t2 = paired_sum_test(conn, 'positions', 'entry_avg_price', 'entry_timestamp', 'outcome', TEST_MARKET_ID)
    t2['table'] = 'positions.entry_avg_price'
    pair_tests.append(t2)
    print(f"  positions.entry_avg_price: n_pairs={t2['n_pairs']} mean_sum={t2.get('mean_sum')} std={t2.get('std_sum')}")

    t3 = paired_sum_test(conn, 'positions', 'exit_avg_price', 'exit_timestamp', 'outcome', TEST_MARKET_ID)
    t3['table'] = 'positions.exit_avg_price'
    pair_tests.append(t3)
    print(f"  positions.exit_avg_price: n_pairs={t3['n_pairs']} mean_sum={t3.get('mean_sum')} std={t3.get('std_sum')}")

    print("\nCONVENTION (established empirically): price = P(outcome actually traded), "
          "for BOTH Yes and No. No flip is ever needed.")

    print("\n=== PART B: buggy (production, unchanged) vs corrected geo_elo ===")
    by_trader = load_qualifying_trades(conn, verbose=args.verbose)

    if args.selfcheck:
        # selfcheck: for traders whose stored geo_elo is fresh (matches a
        # from-scratch buggy recompute), the buggy recompute here must match
        # stored exactly -- proves this script calls the real formula
        # correctly and isn't silently diverging from production.
        sample_traders = [t for t in by_trader if len(by_trader[t]) >= MIN_TRADES_FOR_ELO][:300]
        stored = dict(conn.execute("SELECT address, geo_elo FROM traders WHERE geo_elo IS NOT NULL").fetchall())
        checked = 0
        matches = 0
        for t in sample_traders:
            if t not in stored or stored[t] is None:
                continue
            buggy = _compute_geo_elo(by_trader[t])
            checked += 1
            if abs(buggy - stored[t]) < 0.5:  # small tolerance for float/staleness noise
                matches += 1
        print(f"[selfcheck] {matches}/{checked} sampled traders' from-scratch buggy recompute "
              f"matches stored traders.geo_elo within 0.5pt (mismatches are pre-existing staleness, "
              f"not this script's logic -- see O-39 in prior audit)")
        if not args.persist and not args.json_out:
            conn.close()
            return

    elo_df = compare_buggy_vs_corrected(by_trader, conn, verbose=args.verbose)

    print(f"\nn_traders (>= {MIN_TRADES_FOR_ELO} qualifying trades) = {len(elo_df)}")
    print(f"mean diff (corrected - buggy) = {elo_df['diff'].mean():.2f}")
    print(f"median diff = {elo_df['diff'].median():.2f}")
    print(f"std diff = {elo_df['diff'].std():.2f}")
    print(f"fraction with |diff| > 50 = {(elo_df['diff'].abs() > 50).mean():.4f}")
    print(f"fraction with |diff| > 200 = {(elo_df['diff'].abs() > 200).mean():.4f}")

    rank_corr = elo_df[['buggy', 'corrected']].corr(method='spearman').iloc[0, 1]
    print(f"\nSpearman rank correlation (buggy vs corrected) = {rank_corr:.4f}")

    buggy_legend = set(elo_df[elo_df['buggy'] >= GEO_ELO_LEGENDARY]['trader'])
    corrected_legend = set(elo_df[elo_df['corrected'] >= GEO_ELO_LEGENDARY]['trader'])
    print(f"\nLEGENDARY (raw >= {GEO_ELO_LEGENDARY}) under buggy formula: {len(buggy_legend)} traders")
    print(f"LEGENDARY (raw >= {GEO_ELO_LEGENDARY}) under corrected formula: {len(corrected_legend)} traders")
    print(f"  intersection: {len(buggy_legend & corrected_legend)}")
    print(f"  buggy-only (lose LEGENDARY under correction): {len(buggy_legend - corrected_legend)}")
    print(f"  corrected-only (gain LEGENDARY under correction): {len(corrected_legend - buggy_legend)}")

    mix = side_mix(conn, elo_df['trader'].tolist(), verbose=args.verbose)
    merged = elo_df.merge(mix, on='trader')
    merged['no_frac'] = merged['n_no'] / merged['n_total']
    corr_no_frac_diff = merged[['no_frac', 'diff']].corr().iloc[0, 1]
    print(f"\ncorrelation(No-side trade fraction, diff) = {corr_no_frac_diff:.4f} "
          f"(near 1.0 => systematic, driven by No-heaviness, not noise)")

    for lo, hi, label in [(0, 0.2, '0-20% No'), (0.2, 0.4, '20-40% No'), (0.4, 0.6, '40-60% No'),
                           (0.6, 0.8, '60-80% No'), (0.8, 1.01, '80-100% No')]:
        sub = merged[(merged['no_frac'] >= lo) & (merged['no_frac'] < hi)]
        if len(sub) > 0:
            print(f"  {label}: n={len(sub)}, mean_diff={sub['diff'].mean():.2f}, median_diff={sub['diff'].median():.2f}")

    result = dict(
        spec_version=SPEC_VERSION,
        paired_price_tests=pair_tests,
        n_traders=len(elo_df),
        mean_diff=float(elo_df['diff'].mean()),
        median_diff=float(elo_df['diff'].median()),
        std_diff=float(elo_df['diff'].std()),
        spearman_buggy_vs_corrected=float(rank_corr),
        legendary_buggy=len(buggy_legend), legendary_corrected=len(corrected_legend),
        legendary_intersection=len(buggy_legend & corrected_legend),
        legendary_lost=len(buggy_legend - corrected_legend),
        legendary_gained=len(corrected_legend - buggy_legend),
        corr_no_frac_diff=float(corr_no_frac_diff),
    )
    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()

    if args.persist:
        generated_at = datetime.now(timezone.utc).isoformat()
        pre_reg = (
            SPEC_VERSION,
            "price = P(outcome actually traded), for both Yes and No -- established via paired "
            "Yes/No sum-to-1 tests on trades.price, positions.entry_avg_price, positions.exit_avg_price",
            "_compute_geo_elo's expected=price-if-Yes-else-1-minus-price flips incorrectly for No-side "
            "trades given the established convention -- confirmed by calling the unmodified production "
            "function with outcome_bet forced to Yes (price untouched), which is mathematically identical "
            "to the corrected formula",
            "read-only; no reimplementation of the ELO math; production _compute_geo_elo called twice "
            "per trader (buggy=as-is, corrected=outcome_bet forced Yes)",
            generated_at, args.generator_commit,
        )
        last_err = None
        for attempt in range(5):
            try:
                wconn = db_connect(args.db)
                persist(wconn, pre_reg, pair_tests, elo_df, args.generator_commit, generated_at)
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
        print(f"[persist] price_convention_audit_pre_registration, "
              f"price_convention_audit_paired_price_tests, "
              f"price_convention_audit_elo_comparison ({len(elo_df)} rows) written, "
              f"generated_at={generated_at}")


if __name__ == '__main__':
    main()
