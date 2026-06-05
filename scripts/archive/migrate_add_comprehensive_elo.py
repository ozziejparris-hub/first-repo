#!/usr/bin/env python3
"""
Database Migration: Add Comprehensive ELO Fields

Adds comprehensive ELO tracking fields to the traders table.

BEFORE RUNNING:
- Backup is created automatically
- Check backup exists before proceeding

RUN:
python scripts/migrate_add_comprehensive_elo.py

ROLLBACK:
cp data/polymarket_tracker.db.backup_YYYYMMDD_HHMMSS data/polymarket_tracker.db
"""

import sqlite3
import os
import shutil
from datetime import datetime


def create_backup(db_path: str) -> str:
    """Create timestamped backup of database."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f"{db_path}.backup_{timestamp}"

    print(f"Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)

    # Verify backup
    if not os.path.exists(backup_path):
        raise Exception(f"Backup failed! {backup_path} not created")

    backup_size = os.path.getsize(backup_path)
    original_size = os.path.getsize(db_path)

    if backup_size != original_size:
        raise Exception(f"Backup size mismatch! Original: {original_size}, Backup: {backup_size}")

    print(f"[OK] Backup created successfully ({backup_size:,} bytes)")
    return backup_path


def add_column_safe(cursor, table: str, column: str, column_type: str, default: str):
    """Add column if it doesn't exist."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type} DEFAULT {default}")
        print(f"[OK] Added {table}.{column}")
        return True
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print(f"[WARN] {table}.{column} already exists")
            return False
        else:
            raise


def migrate(db_path: str = None):
    """Run migration to add comprehensive ELO fields."""

    # Default path
    if db_path is None:
        db_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'data',
            'polymarket_tracker.db'
        )

    if not os.path.exists(db_path):
        raise Exception(f"Database not found: {db_path}")

    print("="*70)
    print("  COMPREHENSIVE ELO MIGRATION")
    print("="*70)
    print(f"Database: {db_path}")
    print(f"Size: {os.path.getsize(db_path):,} bytes")
    print()

    # Create backup
    backup_path = create_backup(db_path)
    print()

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count traders before
    cursor.execute("SELECT COUNT(*) FROM traders")
    trader_count = cursor.fetchone()[0]
    print(f"Traders in database: {trader_count}")
    print()

    print("Adding comprehensive ELO fields...")
    print()

    # Add comprehensive_elo field
    add_column_safe(
        cursor,
        'traders',
        'comprehensive_elo',
        'REAL',
        '1500'
    )

    # Add base_category_elo field
    add_column_safe(
        cursor,
        'traders',
        'base_category_elo',
        'REAL',
        '1500'
    )

    # Add elo_last_updated field
    add_column_safe(
        cursor,
        'traders',
        'elo_last_updated',
        'TIMESTAMP',
        'NULL'
    )

    # Optional: Add component modifier fields for debugging
    print()
    print("Adding component modifier fields (optional)...")
    print()

    add_column_safe(
        cursor,
        'traders',
        'behavioral_modifier',
        'REAL',
        '1.0'
    )

    add_column_safe(
        cursor,
        'traders',
        'advanced_modifier',
        'REAL',
        '1.0'
    )

    add_column_safe(
        cursor,
        'traders',
        'pnl_modifier',
        'REAL',
        '1.0'
    )

    # Create indexes
    print()
    print("Creating performance indexes...")
    print()

    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_traders_comprehensive_elo
            ON traders(comprehensive_elo DESC)
        """)
        print("[OK] Created index: idx_traders_comprehensive_elo")
    except Exception as e:
        print(f"[WARN] Index creation warning: {e}")

    try:
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_traders_elo_updated
            ON traders(elo_last_updated DESC)
        """)
        print("[OK] Created index: idx_traders_elo_updated")
    except Exception as e:
        print(f"[WARN] Index creation warning: {e}")

    # Commit changes
    conn.commit()

    # Verify migration
    print()
    print("Verifying migration...")
    print()

    cursor.execute("PRAGMA table_info(traders)")
    columns = cursor.fetchall()

    required_columns = [
        'comprehensive_elo',
        'base_category_elo',
        'elo_last_updated',
        'behavioral_modifier',
        'advanced_modifier',
        'pnl_modifier'
    ]

    found_columns = [col[1] for col in columns]

    for required in required_columns:
        if required in found_columns:
            print(f"[OK] Verified: {required}")
        else:
            print(f"[ERROR] MISSING: {required}")

    # Count traders after
    cursor.execute("SELECT COUNT(*) FROM traders")
    trader_count_after = cursor.fetchone()[0]

    if trader_count != trader_count_after:
        print(f"\n[WARN] WARNING: Trader count changed! Before: {trader_count}, After: {trader_count_after}")
    else:
        print(f"\n[OK] Trader count unchanged: {trader_count}")

    conn.close()

    print()
    print("="*70)
    print("  MIGRATION COMPLETE!")
    print("="*70)
    print(f"Backup: {backup_path}")
    print(f"Database: {db_path}")
    print()
    print("Next steps:")
    print("1. Test with: python -c \"from monitoring.database import Database; db = Database(); print('OK')\"")
    print("2. Verify with: python scripts/view_trader_rankings.py")
    print()
    print("To rollback:")
    print(f"cp {backup_path} {db_path}")
    print("="*70)


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n[ERROR] MIGRATION FAILED: {e}")
        print("\nDatabase unchanged (or restore from backup)")
        import traceback
        traceback.print_exc()
        exit(1)
