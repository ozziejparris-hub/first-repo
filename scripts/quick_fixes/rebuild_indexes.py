#!/usr/bin/env python3
"""
Rebuild Database Indexes

Recreates indexes to improve query performance.
Useful if queries are running slow or if database has grown significantly.

Usage:
    python scripts/quick_fixes/rebuild_indexes.py
"""

import sqlite3
from pathlib import Path
from datetime import datetime


def rebuild_indexes(db_path: str = 'data/polymarket_tracker.db'):
    """
    Rebuild database indexes.

    Args:
        db_path: Path to database file
    """
    print("="*70)
    print("  REBUILDING DATABASE INDEXES")
    print("="*70)
    print()

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"ERROR: Database not found at {db_path}")
        return

    print(f"Database: {db_path}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get existing indexes
    cursor.execute("""
        SELECT name, tbl_name FROM sqlite_master
        WHERE type='index' AND sql IS NOT NULL
    """)
    indexes = cursor.fetchall()

    print(f"Found {len(indexes)} indexes to rebuild")
    print()

    # Reindex all tables
    print("Reindexing tables...")

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    for table in tables:
        if table.startswith('sqlite_'):
            continue  # Skip system tables

        print(f"  Reindexing: {table}")
        try:
            cursor.execute(f"REINDEX {table}")
        except Exception as e:
            print(f"    Warning: {e}")

    conn.commit()

    print()
    print("="*70)
    print("✅ INDEX REBUILD COMPLETE")
    print("="*70)
    print()
    print(f"Rebuilt indexes for {len(tables)} tables")
    print("Query performance should be improved!")

    conn.close()


if __name__ == "__main__":
    rebuild_indexes()
