#!/usr/bin/env python3
"""
Resync the closed_positions and open_positions counters in the traders table
from the positions table.

The two systems drift apart because traders.closed_positions is updated via
calculate_trader_pnl() (in-memory derivation from trades) while the positions
table is updated through a separate store_positions() call. Running this as
part of daily_maintenance keeps the denormalized counters consistent.
"""
import sys
import sqlite3
sys.path.insert(0, '.')

DB_PATH = 'data/polymarket_tracker.db'


def resync_position_counts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE traders SET closed_positions = (
            SELECT COUNT(*) FROM positions p
            WHERE p.trader_address = traders.address
            AND p.status = 'closed'
        )
        WHERE EXISTS (
            SELECT 1 FROM positions p
            WHERE p.trader_address = traders.address
        )
    """)
    closed_rows = cursor.rowcount

    cursor.execute("""
        UPDATE traders SET open_positions = (
            SELECT COUNT(*) FROM positions p
            WHERE p.trader_address = traders.address
            AND p.status = 'open'
        )
        WHERE EXISTS (
            SELECT 1 FROM positions p
            WHERE p.trader_address = traders.address
        )
    """)

    cursor.execute("""
        SELECT COUNT(*) FROM traders t
        WHERE t.closed_positions != (
            SELECT COUNT(*) FROM positions p
            WHERE p.trader_address = t.address
            AND p.status = 'closed'
        )
        AND t.closed_positions IS NOT NULL
    """)
    remaining = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    print(f"Resynced {closed_rows} traders' position counts")
    if remaining > 0:
        print(f"WARNING: {remaining} mismatches remain (likely live-write race — will resolve next run)")
    else:
        print("All counters consistent with positions table")


if __name__ == '__main__':
    resync_position_counts()
