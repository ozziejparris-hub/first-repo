#!/usr/bin/env python3
"""
Vacuum and Optimize Database

Reclaims unused space and optimizes database performance.
Run this periodically to keep the database fast and compact.

Usage:
    python scripts/quick_fixes/vacuum_database.py
"""

import sqlite3
from pathlib import Path
from datetime import datetime


def vacuum_database(db_path: str = 'data/polymarket_tracker.db'):
    """
    Vacuum and optimize database.

    Args:
        db_path: Path to database file
    """
    print("="*70)
    print("  DATABASE VACUUM & OPTIMIZATION")
    print("="*70)
    print()

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"ERROR: Database not found at {db_path}")
        return

    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    print("This may take a few minutes for large databases...")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get size before
    cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    size_before = cursor.fetchone()[0] / (1024 * 1024)

    print(f"Size before: {size_before:.2f} MB")

    # Run VACUUM
    print("Running VACUUM...")
    cursor.execute("VACUUM")

    # Run ANALYZE to update query planner statistics
    print("Running ANALYZE...")
    cursor.execute("ANALYZE")

    # Get size after
    cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
    size_after = cursor.fetchone()[0] / (1024 * 1024)

    print(f"Size after: {size_after:.2f} MB")

    saved = size_before - size_after
    percentage = (saved / size_before * 100) if size_before > 0 else 0

    print()
    print("="*70)
    print("✅ OPTIMIZATION COMPLETE")
    print("="*70)
    print()
    print(f"Space saved: {saved:.2f} MB ({percentage:.1f}%)")

    if saved > 0.1:
        print("Database has been optimized!")
    else:
        print("Database was already optimal - no significant space saved.")

    conn.close()


if __name__ == "__main__":
    vacuum_database()
