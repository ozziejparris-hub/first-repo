#!/usr/bin/env python3
"""
Compute point-in-time ELO for RQ1.1 validation.

Runs the ELO engine on trades before 2026-04-01 only,
writes results to elo_period1_cutoff column.
Production comprehensive_elo is never touched.

Usage:
    python scripts/compute_period1_elo.py          # dry run
    python scripts/compute_period1_elo.py --confirm # write to DB
"""

import sys
import os
import argparse
import sqlite3 as _sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.unified_elo_system import UnifiedELOSystem

CUTOFF_DATE = "2026-04-01"
COLUMN = "elo_period1_cutoff"


def ensure_column(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(traders)")
    cols = {row[1] for row in cursor.fetchall()}
    if COLUMN not in cols:
        cursor.execute(f"ALTER TABLE traders ADD COLUMN {COLUMN} REAL DEFAULT NULL")
        conn.commit()
        print(f"Added column {COLUMN} to traders table.")
    else:
        print(f"Column {COLUMN} already exists.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true",
                        help="Actually write to DB (default is dry run)")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  PERIOD 1 ELO COMPUTATION (cutoff: {CUTOFF_DATE})")
    print(f"  Mode: {'WRITE' if args.confirm else 'DRY RUN'}")
    print(f"{'='*60}\n")

    elo = UnifiedELOSystem()
    elo.calculate_elo_ratings(verbose=True, cutoff_date=CUTOFF_DATE)

    # Collect results from in-memory state using the same method production uses
    scores = {}
    for address in elo.elo_system.get_all_traders():
        val = elo.get_trader_global_elo(address)
        if val and val != elo.elo_system.starting_elo:
            scores[address] = val

    print(f"\n{'='*60}")
    print(f"  PERIOD 1 ELO SUMMARY")
    print(f"{'='*60}")
    print(f"Traders with Period 1 ELO scores: {len(scores)}")

    if scores:
        vals = list(scores.values())
        print(f"  Min:  {min(vals):.2f}")
        print(f"  Max:  {max(vals):.2f}")
        print(f"  Avg:  {sum(vals)/len(vals):.2f}")

    # Compare top 20 vs production comprehensive_elo
    conn = elo.get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT address, comprehensive_elo FROM traders "
        "WHERE research_excluded = 0 AND comprehensive_elo IS NOT NULL "
        "ORDER BY comprehensive_elo DESC LIMIT 20"
    )
    top20 = cursor.fetchall()

    print(f"\n  Top 20 by production comprehensive_elo vs Period 1 ELO:")
    print(f"  {'Rank':<5} {'Trader':<45} {'Prod ELO':>10} {'Period1 ELO':>12}")
    print(f"  {'-'*75}")
    for rank, (tid, prod_elo) in enumerate(top20, 1):
        p1 = scores.get(tid)
        p1_str = f"{p1:.2f}" if p1 is not None else "N/A"
        prod_str = f"{prod_elo:.2f}" if prod_elo is not None else "N/A"
        print(f"  {rank:<5} {tid:<45} {prod_str:>10} {p1_str:>12}")

    # Count research_excluded=0 traders that will receive values
    cursor.execute("SELECT COUNT(*) FROM traders WHERE research_excluded = 0")
    eligible_count = cursor.fetchone()[0]
    eligible_with_score = sum(1 for tid, _ in top20 if tid in scores)
    # Recount properly
    cursor.execute(
        "SELECT address FROM traders WHERE research_excluded = 0"
    )
    eligible_ids = {row[0] for row in cursor.fetchall()}
    eligible_with_score = sum(1 for tid in eligible_ids if tid in scores)

    print(f"\n  research_excluded=0 traders:      {eligible_count}")
    print(f"  Of those with Period 1 ELO score: {eligible_with_score}")
    print(f"  Would write {eligible_with_score} rows to {COLUMN}")

    if not args.confirm:
        print(f"\n  DRY RUN complete — nothing written to DB.")
        print(f"  Re-run with --confirm to write.")
        conn.close()
        return

    # --confirm path: write to DB
    conn.close()
    DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "polymarket_tracker.db")
    conn2 = _sqlite3.connect(DB_PATH)
    conn2.execute("PRAGMA journal_mode=WAL")
    ensure_column(conn2)

    written = 0
    cursor2 = conn2.cursor()
    for tid in eligible_ids:
        if tid in scores:
            cursor2.execute(
                f"UPDATE traders SET {COLUMN} = ? WHERE address = ?",
                (scores[tid], tid)
            )
            written += 1

    conn2.commit()
    conn2.close()
    print(f"\n  Wrote {written} rows to {COLUMN}.")
    print("  Production comprehensive_elo untouched.")


if __name__ == "__main__":
    main()
