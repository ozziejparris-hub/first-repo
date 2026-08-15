#!/usr/bin/env python3
"""
ELO FORMULA AUDIT -- quantifies the structural issues found in
scripts/update_geo_elo.py::_compute_geo_elo beyond the confirmed sign error
(see price_convention_audit.py / price_convention_audit_elo_comparison for
the sign-error blast radius). Read-only. No production writes.

Reproduces, as committed and re-runnable numbers rather than ad hoc session
queries, the evidence behind the 2026-08-15 geo_elo derivation audit's Part B:

1. SELL contamination: what fraction of _fetch_qualifying_trades' qualifying
   population (as the query is ACTUALLY written -- there is no side='BUY'
   filter despite that having been assumed in an earlier prompt) is SELL,
   not BUY. trade_evaluator.py inverts trade_result's meaning for SELL
   ("won" = the outcome you sold against did NOT happen), so folding SELL
   rows into the same actual/expected accounting as BUY rows conflates two
   different behavioral acts under one label.

2. Double-counting: the distribution of qualifying-trade count per
   (trader, market) pair. Each row is one independent "rating event" in the
   fold; if a trader's repeated buys/sells in the same market are not
   independent forecasts, the K-factor schedule (which decays with raw trade
   count) is being driven by trade FRAGMENTATION, not by genuine independent
   prediction count.

3. Position-size (notional) range within the qualifying population --
   _compute_geo_elo does not read `shares` at all (only
   _compute_geo_directionality does), so this quantifies how large the
   unweighted-by-size range actually is in practice.

Persists elo_formula_audit_pre_registration and elo_formula_audit_findings.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


QUALIFYING_TRADE_WHERE = """
    m.category IN ('Geopolitics', 'Elections')
    AND tr.trade_result IN ('won', 'lost')
    AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    AND tr.price BETWEEN 0.10 AND 0.80
"""


def side_composition(conn):
    rows = conn.execute(f"""
        SELECT tr.side, tr.trade_result, COUNT(*) n
        FROM trades tr JOIN markets m ON m.market_id = tr.market_id
        WHERE {QUALIFYING_TRADE_WHERE}
        GROUP BY tr.side, tr.trade_result
    """).fetchall()
    df = pd.DataFrame(rows, columns=['side', 'trade_result', 'n'])
    total = df['n'].sum()
    by_side = df.groupby('side')['n'].sum()
    return dict(
        total_qualifying_trades=int(total),
        buy_n=int(by_side.get('BUY', 0)), sell_n=int(by_side.get('SELL', 0)),
        sell_fraction=float(by_side.get('SELL', 0) / total),
        by_side_and_result={f"{r.side}_{r.trade_result}": int(r.n) for r in df.itertuples()},
    )


def double_counting(conn):
    rows = conn.execute(f"""
        SELECT trader_address, market_id, COUNT(*) n FROM (
            SELECT tr.trader_address, tr.market_id
            FROM trades tr JOIN markets m ON m.market_id = tr.market_id
            WHERE {QUALIFYING_TRADE_WHERE}
        )
        GROUP BY trader_address, market_id
    """).fetchall()
    df = pd.DataFrame(rows, columns=['trader', 'market_id', 'n'])
    multi = df[df['n'] > 1]
    return dict(
        n_trader_market_pairs=int(len(df)),
        pct_pairs_with_gt1_trade=float((df['n'] > 1).mean()),
        pct_qualifying_trades_from_multi_trade_pairs=float(multi['n'].sum() / df['n'].sum()),
        max_trades_single_pair=int(df['n'].max()),
        median_trades_per_pair=float(df['n'].median()),
    )


def notional_range(conn):
    rows = conn.execute(f"""
        SELECT tr.shares * tr.price AS notional
        FROM trades tr JOIN markets m ON m.market_id = tr.market_id
        WHERE {QUALIFYING_TRADE_WHERE}
    """).fetchall()
    df = pd.DataFrame(rows, columns=['notional'])
    return dict(
        n=int(len(df)), min=float(df['notional'].min()), median=float(df['notional'].median()),
        mean=float(df['notional'].mean()), max=float(df['notional'].max()),
        max_over_median_ratio=float(df['notional'].max() / df['notional'].median()),
        shares_used_in_compute_geo_elo=False,
    )


def persist(conn, findings, generator_commit, generated_at):
    conn.execute("DROP TABLE IF EXISTS elo_formula_audit_pre_registration")
    conn.execute("""
        CREATE TABLE elo_formula_audit_pre_registration (
            spec_version TEXT PRIMARY KEY, scope TEXT, method TEXT,
            registered_at TEXT, generator_commit TEXT
        )
    """)
    conn.execute("INSERT INTO elo_formula_audit_pre_registration VALUES (?,?,?,?,?)", (
        "ELOFORMULA-2026-08-15-v1",
        "Quantify structural issues in _compute_geo_elo's qualifying-trade population beyond the "
        "confirmed sign error: SELL contamination, double-counting via repeated trades per "
        "(trader,market), and unweighted position-size range.",
        "Direct SQL against the exact predicate _fetch_qualifying_trades uses (QUALIFYING_TRADE_WHERE "
        "in this script, byte-identical to update_geo_elo.py). Read-only.",
        generated_at, generator_commit,
    ))

    conn.execute("DROP TABLE IF EXISTS elo_formula_audit_findings")
    conn.execute("""
        CREATE TABLE elo_formula_audit_findings (
            finding TEXT PRIMARY KEY, json_value TEXT, spec_version TEXT, generated_at TEXT,
            generator_commit TEXT
        )
    """)
    for k, v in findings.items():
        conn.execute("INSERT INTO elo_formula_audit_findings VALUES (?,?,?,?,?)",
                     (k, json.dumps(v), "ELOFORMULA-2026-08-15-v1", generated_at, generator_commit))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    args = ap.parse_args()

    conn = db_connect(args.db)

    side = side_composition(conn)
    print("=== SELL contamination (no side='BUY' filter exists in _fetch_qualifying_trades) ===")
    print(json.dumps(side, indent=2))

    dbl = double_counting(conn)
    print("\n=== Double-counting: qualifying trades per (trader, market) pair ===")
    print(json.dumps(dbl, indent=2))

    notl = notional_range(conn)
    print("\n=== Notional (position-size) range -- shares NOT used in _compute_geo_elo ===")
    print(json.dumps(notl, indent=2))

    findings = dict(side_composition=side, double_counting=dbl, notional_range=notl)

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(findings, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()

    if args.persist:
        generated_at = datetime.now(timezone.utc).isoformat()
        last_err = None
        for attempt in range(5):
            try:
                wconn = db_connect(args.db)
                persist(wconn, findings, args.generator_commit, generated_at)
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
        print(f"[persist] elo_formula_audit_pre_registration, elo_formula_audit_findings written, "
              f"generated_at={generated_at}")


if __name__ == '__main__':
    main()
