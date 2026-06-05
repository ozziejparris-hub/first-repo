#!/usr/bin/env python3
"""
Database migration to add trade outcome tracking.

Adds columns to trades table:
- outcome_bet: TEXT - which outcome the trader bet on
- trade_result: TEXT - 'won', 'lost', 'pending', 'invalid'

Creates indexes for efficient querying.
"""

import sys
import os
import shutil
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database


def backup_database(db_path: str) -> str:
    """Create backup of database before migration."""
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print(f"[OK] Backup created: {backup_path}")

    return backup_path


def migrate_add_trade_outcomes(db_path: str = "data/polymarket_tracker.db"):
    """Run migration to add trade outcome columns and indexes."""

    print("\n" + "="*70)
    print("DATABASE MIGRATION: Add Trade Outcome Tracking")
    print("="*70 + "\n")

    # Backup database first
    backup_path = backup_database(db_path)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current schema
    cursor.execute("PRAGMA table_info(trades)")
    columns = {col[1] for col in cursor.fetchall()}

    print("Current trades table columns:")
    for col in sorted(columns):
        print(f"  - {col}")

    # Track what we're adding
    changes_made = []

    # Add outcome_bet column
    if 'outcome_bet' not in columns:
        print("\n[MIGRATION] Adding 'outcome_bet' column...")
        cursor.execute("""
            ALTER TABLE trades
            ADD COLUMN outcome_bet TEXT
        """)
        changes_made.append("Added column: outcome_bet TEXT")
        print("[OK] Added 'outcome_bet' column")
    else:
        print("\n[SKIP] Column 'outcome_bet' already exists")

    # Add trade_result column with default 'pending'
    if 'trade_result' not in columns:
        print("\n[MIGRATION] Adding 'trade_result' column...")
        cursor.execute("""
            ALTER TABLE trades
            ADD COLUMN trade_result TEXT DEFAULT 'pending'
        """)
        changes_made.append("Added column: trade_result TEXT DEFAULT 'pending'")
        print("[OK] Added 'trade_result' column")
    else:
        print("\n[SKIP] Column 'trade_result' already exists")

    # Set default value for existing rows
    if 'trade_result' in columns or changes_made:
        print("\n[MIGRATION] Setting default 'pending' for existing trades...")
        cursor.execute("""
            UPDATE trades
            SET trade_result = 'pending'
            WHERE trade_result IS NULL
        """)
        updated = cursor.rowcount
        print(f"[OK] Set {updated} trades to 'pending' status")

    # Create indexes
    print("\n[MIGRATION] Creating indexes...")

    indexes_to_create = [
        ("idx_trades_market_result", "CREATE INDEX IF NOT EXISTS idx_trades_market_result ON trades(market_id, trade_result)"),
        ("idx_trades_trader_result", "CREATE INDEX IF NOT EXISTS idx_trades_trader_result ON trades(trader_address, trade_result)"),
        ("idx_market_has_trades", "CREATE INDEX IF NOT EXISTS idx_market_has_trades ON trades(market_id)"),
    ]

    for idx_name, idx_sql in indexes_to_create:
        cursor.execute(idx_sql)
        changes_made.append(f"Created index: {idx_name}")
        print(f"[OK] Created index: {idx_name}")

    # Commit changes
    conn.commit()

    # Verify new schema
    cursor.execute("PRAGMA table_info(trades)")
    new_columns = {col[1] for col in cursor.fetchall()}

    # Get index list
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='trades'")
    indexes = [row[0] for row in cursor.fetchall()]

    # Get statistics
    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'pending'")
    pending_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'won'")
    won_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'lost'")
    lost_trades = cursor.fetchone()[0]

    conn.close()

    # Print summary
    print("\n" + "="*70)
    print("MIGRATION COMPLETE")
    print("="*70)

    print("\nChanges made:")
    for change in changes_made:
        print(f"  + {change}")

    print("\nNew schema verification:")
    print(f"  Columns in trades table: {len(new_columns)}")
    if 'outcome_bet' in new_columns:
        print("    + outcome_bet")
    if 'trade_result' in new_columns:
        print("    + trade_result")

    print(f"\n  Indexes on trades table: {len(indexes)}")
    for idx in sorted(indexes):
        if idx.startswith('idx_'):
            print(f"    + {idx}")

    print(f"\nTrade statistics:")
    print(f"  Total trades: {total_trades}")
    print(f"  Pending: {pending_trades}")
    print(f"  Won: {won_trades}")
    print(f"  Lost: {lost_trades}")

    print(f"\nBackup saved to: {backup_path}")
    print("\n[SUCCESS] Migration completed successfully!")
    print("\nNext steps:")
    print("  1. Run: python scripts/test_trade_evaluation.py")
    print("  2. Run: python scripts/backfill_trade_results.py")
    print()


def main():
    """Main entry point."""
    migrate_add_trade_outcomes()


if __name__ == "__main__":
    main()
