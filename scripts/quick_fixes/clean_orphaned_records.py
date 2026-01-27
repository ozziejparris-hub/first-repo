#!/usr/bin/env python3
"""
Clean Orphaned Database Records

Removes trades and positions that reference non-existent traders.
This can happen if traders are deleted or if data import has issues.

Usage:
    python scripts/quick_fixes/clean_orphaned_records.py
"""

import sqlite3
from pathlib import Path
from datetime import datetime


def clean_orphaned_records(db_path: str = 'data/polymarket_tracker.db'):
    """
    Clean orphaned records from database.

    Args:
        db_path: Path to database file
    """
    print("="*70)
    print("  CLEANING ORPHANED RECORDS")
    print("="*70)
    print()

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"ERROR: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Check orphaned trades
    print("Checking for orphaned trades...")
    cursor.execute("""
        SELECT COUNT(*) FROM trades t
        LEFT JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.address IS NULL
    """)
    orphaned_trades = cursor.fetchone()[0]

    if orphaned_trades > 0:
        print(f"  Found: {orphaned_trades:,} orphaned trades")

        # Delete orphaned trades
        cursor.execute("""
            DELETE FROM trades
            WHERE trader_address NOT IN (SELECT address FROM traders)
        """)
        deleted_trades = cursor.rowcount
        print(f"  Deleted: {deleted_trades:,} orphaned trades")
    else:
        print("  No orphaned trades found ✓")

    print()

    # Check orphaned positions
    print("Checking for orphaned positions...")
    cursor.execute("""
        SELECT COUNT(*) FROM positions p
        LEFT JOIN traders tr ON p.trader_address = tr.address
        WHERE tr.address IS NULL
    """)
    orphaned_positions = cursor.fetchone()[0]

    if orphaned_positions > 0:
        print(f"  Found: {orphaned_positions:,} orphaned positions")

        # Delete orphaned positions
        cursor.execute("""
            DELETE FROM positions
            WHERE trader_address NOT IN (SELECT address FROM traders)
        """)
        deleted_positions = cursor.rowcount
        print(f"  Deleted: {deleted_positions:,} orphaned positions")
    else:
        print("  No orphaned positions found ✓")

    print()

    # Commit changes
    conn.commit()
    conn.close()

    print("="*70)
    print("✅ CLEANUP COMPLETE")
    print("="*70)

    if orphaned_trades == 0 and orphaned_positions == 0:
        print("\nNo orphaned records found - database is clean!")
    else:
        total_deleted = (orphaned_trades if orphaned_trades > 0 else 0) + \
                       (orphaned_positions if orphaned_positions > 0 else 0)
        print(f"\nDeleted {total_deleted:,} orphaned records")
        print("Database integrity restored!")


if __name__ == "__main__":
    clean_orphaned_records()
