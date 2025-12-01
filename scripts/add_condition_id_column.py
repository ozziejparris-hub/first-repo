#!/usr/bin/env python3
"""
Add condition_id column to markets table

This migration:
1. Adds condition_id column to store the conditionId (0x...)
2. Migrates existing market_id values to condition_id
3. Prepares for storing the correct 'id' field in market_id
"""

import sqlite3

def add_condition_id_column():
    """Add condition_id column to markets table."""

    conn = sqlite3.connect('data/polymarket_tracker.db')
    cursor = conn.cursor()

    print("="*70)
    print("ADDING CONDITION_ID COLUMN TO MARKETS TABLE")
    print("="*70 + "\n")

    # Step 1: Check if column already exists
    cursor.execute("PRAGMA table_info(markets);")
    columns = [row[1] for row in cursor.fetchall()]

    if 'condition_id' in columns:
        print("[INFO] condition_id column already exists")
        conn.close()
        return

    # Step 2: Add the new column
    print("[MIGRATION] Adding condition_id column...")
    cursor.execute("ALTER TABLE markets ADD COLUMN condition_id TEXT;")

    # Step 3: Copy existing market_id values (which are conditionIds) to condition_id
    print("[MIGRATION] Copying existing market_id values to condition_id...")
    cursor.execute("UPDATE markets SET condition_id = market_id WHERE condition_id IS NULL;")

    rows_updated = cursor.rowcount
    print(f"[MIGRATION] Copied {rows_updated} market IDs to condition_id column")

    # Step 4: Create index on condition_id for faster lookups
    print("[MIGRATION] Creating index on condition_id...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_condition_id ON markets(condition_id);")

    conn.commit()

    # Step 5: Verify
    cursor.execute("SELECT COUNT(*) FROM markets WHERE condition_id IS NOT NULL;")
    count = cursor.fetchone()[0]

    print(f"\n[SUCCESS] Migration complete!")
    print(f"  - Added condition_id column")
    print(f"  - Migrated {count} existing condition IDs")
    print(f"  - Created index on condition_id")
    print(f"\nNEXT STEPS:")
    print(f"  1. Update store_market_dict() to use 'id' field for market_id")
    print(f"  2. Update store_market_dict() to use 'conditionId' for condition_id")
    print(f"  3. Run backfill script to fetch correct IDs from API")

    conn.close()

if __name__ == "__main__":
    add_condition_id_column()
