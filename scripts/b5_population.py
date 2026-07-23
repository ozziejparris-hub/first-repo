#!/usr/bin/env python3
"""
b5_population.py — B5 event-clustering population selector.

B5 (event clustering, the last PIT component before B3) needs the full set of
backtest-window geo/elec markets to cluster, not just the 151 STR-002 signals
scripts/enrich_str002_metadata.py already tags. This is the entry point B5
uses to get that population.

Imports the canonical window definition from monitoring/column_definitions.py
(Section 6) rather than filtering on markets.resolution_date directly. This
was reinvented independently 3 times before it was made canonical (B2/B1b-
prices' population figure, the RQ1.1 ELO-persistence period split, and B5's
own scoping pass) — see BACKTEST_WINDOW_RATIONALE in column_definitions.py for
why tape_end (event-time) and not resolution_date (write-time) is correct
here, and why that's the inverse of O-33's write-time rule, not a violation
of it.

Read-only. No writes to data/polymarket_tracker.db.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.column_definitions import backtest_window_sql

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')

# B5's default backtest window matches the rest of the PIT arc (B1a/B1b).
DEFAULT_WINDOW_START = '2025-11-01'


def fetch_population(conn, window_start: str = DEFAULT_WINDOW_START, window_end: str | None = None):
    """Returns the list of (market_id, title, condition_id, resolution_date,
    tape_end) rows B5 clusters over. resolution_date is carried through for
    reference/debugging only -- see the DO-NOT-FILTER comment at its source
    in column_definitions.py."""
    params = {'window_start': window_start}
    if window_end:
        params['window_end'] = window_end
    return conn.execute(backtest_window_sql(window_start, window_end), params).fetchall()


def main():
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=30)
    rows = fetch_population(conn)
    print(f"B5 population @ window_start={DEFAULT_WINDOW_START}: {len(rows)} markets")
    conn.close()


if __name__ == '__main__':
    main()
