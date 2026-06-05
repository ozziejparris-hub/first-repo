#!/usr/bin/env python3
"""
Database Migration: Add Position Tracking

Creates the positions table for tracking matched BUY/SELL trades and P&L calculation.
This complements the existing resolution-based evaluation system by capturing
early-exit profits.

DISCOVERY NOTES:
- Existing P&L logic in analysis/ is READ-ONLY and resolution-based only
- No position matching exists anywhere in the codebase
- This is a NEW system that works ALONGSIDE resolution tracking
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


def migrate_add_positions(db_path: str = "data/polymarket_tracker.db"):
    """Add positions table and P&L fields to traders table."""

    print("\n" + "="*70)
    print("DATABASE MIGRATION: Add Position Tracking")
    print("="*70 + "\n")

    # Backup database first
    backup_path = backup_database(db_path)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    changes_made = []

    # ===== CREATE POSITIONS TABLE =====
    print("\n[MIGRATION] Creating positions table...")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY,
            trader_address TEXT NOT NULL,
            market_id TEXT NOT NULL,
            market_title TEXT,
            outcome TEXT NOT NULL,

            -- Entry (BUY trades)
            entry_shares REAL NOT NULL,
            entry_avg_price REAL NOT NULL,
            entry_total_cost REAL NOT NULL,
            entry_timestamp TIMESTAMP NOT NULL,
            entry_trade_ids TEXT,

            -- Exit (SELL trades)
            exit_shares REAL,
            exit_avg_price REAL,
            exit_total_received REAL,
            exit_timestamp TIMESTAMP,
            exit_trade_ids TEXT,

            -- P&L Metrics
            realized_pnl REAL,
            roi_percent REAL,
            holding_period_hours REAL,

            -- Position Status
            status TEXT NOT NULL,
            remaining_shares REAL,

            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (trader_address) REFERENCES traders(address)
        )
    """)

    changes_made.append("Created table: positions")
    print("[OK] Created positions table")

    # ===== CREATE INDEXES =====
    print("\n[MIGRATION] Creating indexes...")

    indexes = [
        ("idx_positions_trader", "CREATE INDEX IF NOT EXISTS idx_positions_trader ON positions(trader_address)"),
        ("idx_positions_market", "CREATE INDEX IF NOT EXISTS idx_positions_market ON positions(market_id)"),
        ("idx_positions_status", "CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)"),
        ("idx_positions_trader_status", "CREATE INDEX IF NOT EXISTS idx_positions_trader_status ON positions(trader_address, status)"),
        ("idx_positions_trader_market", "CREATE INDEX IF NOT EXISTS idx_positions_trader_market ON positions(trader_address, market_id, outcome)"),
    ]

    for idx_name, idx_sql in indexes:
        cursor.execute(idx_sql)
        changes_made.append(f"Created index: {idx_name}")
        print(f"[OK] Created index: {idx_name}")

    # ===== ADD P&L FIELDS TO TRADERS TABLE =====
    print("\n[MIGRATION] Adding P&L fields to traders table...")

    # Check current columns
    cursor.execute("PRAGMA table_info(traders)")
    existing_columns = {col[1] for col in cursor.fetchall()}

    pnl_columns = [
        ("realized_pnl", "REAL DEFAULT 0"),
        ("unrealized_pnl", "REAL DEFAULT 0"),
        ("total_pnl", "REAL DEFAULT 0"),
        ("avg_roi", "REAL DEFAULT 0"),
        ("total_invested", "REAL DEFAULT 0"),
        ("closed_positions", "INTEGER DEFAULT 0"),
        ("open_positions", "INTEGER DEFAULT 0"),
    ]

    for col_name, col_type in pnl_columns:
        if col_name not in existing_columns:
            cursor.execute(f"ALTER TABLE traders ADD COLUMN {col_name} {col_type}")
            changes_made.append(f"Added column to traders: {col_name} {col_type}")
            print(f"[OK] Added column: {col_name}")
        else:
            print(f"[SKIP] Column '{col_name}' already exists")

    # Commit changes
    conn.commit()

    # ===== VERIFICATION =====
    print("\n[VERIFICATION] Checking new schema...")

    # Verify positions table
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'")
    positions_schema = cursor.fetchone()
    if positions_schema:
        print("[OK] Positions table exists")

    # Verify traders columns
    cursor.execute("PRAGMA table_info(traders)")
    trader_columns = {col[1] for col in cursor.fetchall()}

    pnl_cols_present = sum(1 for col, _ in pnl_columns if col in trader_columns)
    print(f"[OK] Traders table has {pnl_cols_present}/{len(pnl_columns)} P&L columns")

    # Get counts
    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    flagged_traders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM positions")
    total_positions = cursor.fetchone()[0]

    conn.close()

    # ===== SUMMARY =====
    print("\n" + "="*70)
    print("MIGRATION COMPLETE")
    print("="*70)

    print("\nChanges made:")
    for change in changes_made:
        print(f"  + {change}")

    print("\nDatabase state:")
    print(f"  Flagged traders: {flagged_traders}")
    print(f"  Total trades: {total_trades}")
    print(f"  Total positions: {total_positions} (ready for historical build)")

    print(f"\nBackup saved to: {backup_path}")
    print("\n[SUCCESS] Migration completed successfully!")

    print("\nNext steps:")
    print("  1. Run: python scripts/build_positions_historical.py")
    print("  2. Run: python scripts/view_pnl_performance.py")
    print()


def main():
    """Main entry point."""
    migrate_add_positions()


if __name__ == "__main__":
    main()
