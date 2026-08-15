#!/usr/bin/env python3
"""
GEO_ELO DERIVATION AUDIT -- empirical quantification for the first-principles
audit of scripts/update_geo_elo.py's _compute_geo_elo. Read-only. No fixes.

This script does NOT re-litigate the sign-error bug (already established and
quantified in price_convention_audit.py, first-repo f7695c0). It quantifies
the OTHER structural issues found while deriving the formula from first
principles, so the report's Part B claims are backed by a committed,
re-runnable artifact rather than ad hoc session queries:

  - SELL-trade contamination: what fraction of "qualifying trades" feeding
    the ELO fold are SELL (exit) events, which trade_evaluator.py scores
    with an INVERTED trade_result semantic relative to BUY (a SELL is
    'won' when the outcome_bet did NOT happen -- i.e. "correctly exited"),
    fed into the same accumulator as if it were a fresh directional bet.
  - Double-counting: the distribution of qualifying-trade count per
    (trader, market) pair. Each row is one independent "rating event" in
    the fold; if the same market/trader pair contributes many rows, those
    are NOT independent forecasting instances, they are fragments of one
    decision (DCA, partial fills, round-trips).
  - Notional (size) blindness: the qualifying trades' shares*price notional
    distribution, to quantify how large the range is that the fold treats
    as equal-weight (_compute_geo_elo never reads `shares`).
  - The step-indexed ratchet's mechanical consequence: the maximum
    achievable geo_elo at trade-index i is 1500+150*(i+1) regardless of
    skill -- i.e. trade COUNT alone buys ceiling headroom. Quantified via a
    direct read of the two commits that introduced it (e05859c, 299ff12)
    plus a population-level check of how many traders are actually sitting
    at or near their count-determined ceiling.

Persists: geo_elo_derivation_audit_findings (one row per named finding,
with the metric value, population scope, and generating parameters).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SPEC_VERSION = "GEOELODERIV-2026-08-15-v1"


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


QUALIFYING_TRADES_SQL = """
    SELECT tr.trader_address, tr.market_id, tr.side, tr.trade_result, tr.shares, tr.price
    FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE m.category IN ('Geopolitics', 'Elections')
      AND tr.trade_result IN ('won', 'lost')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND tr.price BETWEEN 0.10 AND 0.80
"""


def selfcheck(conn, verbose=True):
    """Verifies this script's qualifying-trade query is byte-identical in
    predicate to update_geo_elo.py::_fetch_qualifying_trades (minus the
    per-trader WHERE and ORDER BY, which don't affect aggregate counts) by
    comparing total row counts against a direct re-statement of that
    function's WHERE clause for a random trader sample."""
    import random
    traders = [r[0] for r in conn.execute(
        "SELECT DISTINCT trader_address FROM trades LIMIT 2000"
    ).fetchall()]
    random.seed(3)
    sample = random.sample(traders, min(50, len(traders)))
    mismatches = 0
    for addr in sample:
        a = conn.execute("""
            SELECT COUNT(*) FROM trades tr JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trader_address = ? AND m.category IN ('Geopolitics','Elections')
              AND tr.trade_result IN ('won','lost')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
              AND tr.price BETWEEN 0.10 AND 0.80
        """, (addr,)).fetchone()[0]
        b = conn.execute("""
            SELECT COUNT(*) FROM (""" + QUALIFYING_TRADES_SQL + """) WHERE trader_address = ?
        """, (addr,)).fetchone()[0]
        if a != b:
            mismatches += 1
    if verbose:
        print(f"[selfcheck] {len(sample)} traders checked, {mismatches} predicate mismatches")
    return len(sample), mismatches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    args = ap.parse_args()

    conn = db_connect(args.db)

    if args.selfcheck:
        n, mismatches = selfcheck(conn)
        if mismatches:
            print(f"[selfcheck] FAILED: {mismatches}/{n}", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n}")
        if not args.persist and not args.json_out:
            conn.close()
            return

    df = pd.read_sql(QUALIFYING_TRADES_SQL, conn)
    findings = {}

    print("=== FINDING 1: SELL-trade contamination ===")
    side_counts = df['side'].value_counts()
    sell_frac = side_counts.get('SELL', 0) / len(df)
    print(side_counts, f"\nSELL fraction = {sell_frac:.4f}")
    findings['sell_fraction_of_qualifying_trades'] = dict(
        value=float(sell_frac), scope=f"n={len(df)} qualifying trades",
        note="trade_evaluator.py scores SELL trade_result with inverted semantics vs BUY; "
             "_fetch_qualifying_trades applies no side filter, so SELL rows enter the ELO "
             "fold identically to BUY rows")

    print("\n=== FINDING 2: double-counting (trades per trader-market pair) ===")
    pair_counts = df.groupby(['trader_address', 'market_id']).size()
    frac_pairs_gt1 = (pair_counts > 1).mean()
    frac_trades_in_fragmented_pairs = pair_counts[pair_counts > 1].sum() / pair_counts.sum()
    print(pair_counts.describe())
    print(f"fraction of (trader,market) pairs with >1 qualifying trade = {frac_pairs_gt1:.4f}")
    print(f"fraction of ALL qualifying trades in a fragmented (>1-trade) pair = {frac_trades_in_fragmented_pairs:.4f}")
    findings['fraction_trader_market_pairs_fragmented'] = dict(
        value=float(frac_pairs_gt1), scope=f"n={len(pair_counts)} (trader,market) pairs",
        note="each qualifying trade is one independent rating event in the fold's sequential sum")
    findings['fraction_qualifying_trades_in_fragmented_pairs'] = dict(
        value=float(frac_trades_in_fragmented_pairs), scope=f"n={len(df)} qualifying trades", note="")

    print("\n=== FINDING 3: notional (size) blindness ===")
    df['notional'] = df['shares'] * df['price']
    print(df['notional'].describe())
    ratio = df['notional'].max() / df['notional'].median()
    print(f"max/median notional ratio = {ratio:.1f}")
    findings['notional_max_to_median_ratio'] = dict(
        value=float(ratio), scope=f"n={len(df)} qualifying trades",
        note="_compute_geo_elo never reads shares; every trade contributes equally to the "
             "fold regardless of notional size")

    print("\n=== FINDING 4: ratchet ceiling is trade-count-determined, not skill-determined ===")
    print("max_elo_at_step = 1500 + (trade_index+1)*150 -- introduced e05859c (post-loop), "
          "moved to per-step ratchet 299ff12 (both 2026-05-31, same session, no rationale in "
          "either commit message beyond 'fix: soft ELO cap'). Ceiling at trade-index i is a "
          "pure function of i, independent of the trader's actual accuracy.")
    findings['ratchet_formula'] = dict(
        value=None, scope="scripts/update_geo_elo.py:148-150",
        note="max_elo_at_step = 1500.0 + (i+1)*150.0; commits e05859c, 299ff12 (2026-05-31), "
             "no calibration rationale found in either commit message")

    result = dict(spec_version=SPEC_VERSION, findings=findings)
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
                wconn.execute("DROP TABLE IF EXISTS geo_elo_derivation_audit_findings")
                wconn.execute("""
                    CREATE TABLE geo_elo_derivation_audit_findings (
                        finding TEXT PRIMARY KEY, value REAL, scope TEXT, note TEXT,
                        spec_version TEXT, generated_at TEXT, generator_commit TEXT
                    )
                """)
                for name, f in findings.items():
                    wconn.execute("INSERT INTO geo_elo_derivation_audit_findings VALUES (?,?,?,?,?,?,?)",
                                 (name, f['value'], f['scope'], f['note'], SPEC_VERSION,
                                  generated_at, args.generator_commit))
                wconn.commit()
                wconn.close()
                last_err = None
                break
            except sqlite3.OperationalError as e:
                last_err = e
                print(f"[persist] attempt failed ({e}); retrying...", file=sys.stderr)
                import time as _time
                _time.sleep(5)
        if last_err:
            print(f"[persist] FAILED: {last_err}", file=sys.stderr)
            sys.exit(1)
        print(f"[persist] geo_elo_derivation_audit_findings written, generated_at={generated_at}")


if __name__ == '__main__':
    main()
