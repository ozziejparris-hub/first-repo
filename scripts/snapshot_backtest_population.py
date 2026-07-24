#!/usr/bin/env python3
"""
snapshot_backtest_population.py

Freezes a backtest-window market population (monitoring/column_definitions.py
Section 6, backtest_window_sql()) into the backtest_population_snapshots
table. This is the pinned artifact B5 labelling and B3 train/validate/holdout
splits must consume -- never the live query directly.

WHY THIS EXISTS (O-45 follow-up, 2026-07-24): backtest_window_sql() is
correctly LIVE and time-varying -- tape_end grows as new trades accrue, so
the population at a fixed window_start moves day to day by design (measured:
4,690 -> 4,702 -> 4,712 within a single day). That's not a bug. The bug was
a test asserting an exact count against that moving query. The deeper fix:
anything that needs a population that must NOT move under it (a labelling
pass, a pre-registered holdout split) needs a frozen instance, not the rule
itself. See BACKTEST_WINDOW_RATIONALE / the VERSIONING note in
column_definitions.py Section 6 for the full contract.

DESIGN PRINCIPLES (mirrors elo_snapshots / order_book_snapshots):
- APPEND-ONLY. Snapshot rows are never modified once written. Composite PK
  (snapshot_id, market_id) enforces one row per market per snapshot.
- IDEMPOTENT. Re-running with the same snapshot_id is a no-op (INSERT OR IGNORE).
- Every snapshot records generated_at, sql_version (BACKTEST_WINDOW_SQL_VERSION
  at generation time), window_start, window_end -- enough to tell a snapshot
  frozen under an older query definition apart from one frozen under a newer one.

CLUSTER-LABEL STABILITY UNDER RE-PINNING (for B5's clustering build):
"A cluster label on a market stays valid whenever that market appears" is
VERIFIED for the native neg_risk/neg_risk_market_id grouping mechanism --
it's a market-level field, independent of what else is in the query, so a
later superset snapshot cannot change an existing market's grouping under it.
It is NOT YET VERIFIED for the title-inference fallback, because that
clustering step hasn't been built yet. This must be imposed as a hard design
constraint on that build, not discovered afterward: title-inference
clustering must be deterministic per-market (each market's cluster decided
against a fixed rule/threshold, never relative to what else happens to be in
the current batch) specifically so labels stay valid when a later snapshot
extends the population. Pin-now (this script) is only safe under that
constraint -- if the fallback is ever built population-relative, labels
produced against snapshot #1 would need re-validation before reuse against a
later snapshot.

Usage:
  python3 snapshot_backtest_population.py --window-start 2025-11-01 [--window-end YYYY-MM-DD] [--snapshot-id ID]
  python3 snapshot_backtest_population.py --stats            # show snapshot history
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitoring.column_definitions import backtest_window_sql, BACKTEST_WINDOW_SQL_VERSION

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')


def ensure_table(conn):
    """Create the backtest_population_snapshots table if it doesn't exist."""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS backtest_population_snapshots (
        snapshot_id     TEXT NOT NULL,
        generated_at    TEXT NOT NULL,
        sql_version     TEXT NOT NULL,
        window_start    TEXT NOT NULL,
        window_end      TEXT,
        market_id       TEXT NOT NULL,
        tape_end        TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, market_id)
    )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bt_pop_snap_id ON backtest_population_snapshots(snapshot_id)')
    conn.commit()


def run_snapshot(window_start: str, window_end: str | None = None,
                  snapshot_id: str | None = None, verbose: bool = True) -> tuple[str, int]:
    if snapshot_id is None:
        snapshot_id = f"bt_pop_{window_start}_v{BACKTEST_WINDOW_SQL_VERSION}"

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    ensure_table(conn)
    cur = conn.cursor()

    cur.execute('SELECT COUNT(*) FROM backtest_population_snapshots WHERE snapshot_id = ?', (snapshot_id,))
    existing = cur.fetchone()[0]
    if existing > 0:
        if verbose:
            print(f"Snapshot '{snapshot_id}' already exists ({existing} rows). Skipping (idempotent).")
        conn.close()
        return snapshot_id, existing

    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    params = {'window_start': window_start}
    if window_end:
        params['window_end'] = window_end
    rows = conn.execute(backtest_window_sql(window_start, window_end), params).fetchall()
    # rows: market_id, title, condition_id, resolution_date, tape_end
    snapshot_rows = [
        (snapshot_id, generated_at, BACKTEST_WINDOW_SQL_VERSION, window_start, window_end, r[0], r[4])
        for r in rows
    ]

    conn.executemany('''
        INSERT OR IGNORE INTO backtest_population_snapshots
        (snapshot_id, generated_at, sql_version, window_start, window_end, market_id, tape_end)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', snapshot_rows)
    conn.commit()
    conn.close()

    if verbose:
        print(f"Snapshot '{snapshot_id}' written: {len(snapshot_rows)} markets "
              f"(window_start={window_start}, window_end={window_end or 'open'}, "
              f"sql_version={BACKTEST_WINDOW_SQL_VERSION}, generated_at={generated_at})")
    return snapshot_id, len(snapshot_rows)


def show_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='backtest_population_snapshots'")
    if not cur.fetchone():
        print("No backtest_population_snapshots table exists yet.")
        conn.close()
        return
    cur.execute('''
        SELECT snapshot_id, generated_at, sql_version, window_start, window_end, COUNT(*)
        FROM backtest_population_snapshots
        GROUP BY snapshot_id ORDER BY generated_at DESC
    ''')
    print(f"{'snapshot_id':<28} {'generated_at':<21} {'ver':<4} {'window_start':<12} {'window_end':<12} {'count':>7}")
    for r in cur.fetchall():
        print(f"{r[0]:<28} {r[1]:<21} {r[2]:<4} {r[3]:<12} {r[4] or 'open':<12} {r[5]:>7}")
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--window-start', help='Window start YYYY-MM-DD')
    parser.add_argument('--window-end', help='Window end YYYY-MM-DD (default: open-ended)')
    parser.add_argument('--snapshot-id', help='Override snapshot_id (default: bt_pop_<window_start>_v<sql_version>)')
    parser.add_argument('--stats', action='store_true', help='Show snapshot history')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.window_start:
        run_snapshot(args.window_start, args.window_end, args.snapshot_id)
    else:
        parser.error('--window-start is required (or use --stats)')
