#!/usr/bin/env python3
"""
Update Database Schema - Add Behavioral and Weighted Metrics Columns

Adds new columns to support behavioral ELO integration:
- Traders table: Kelly, patience, timing scores, weighted win rate, ROI, resolved trades count
- Markets table: Difficulty score

Safe to run multiple times (uses IF NOT EXISTS).
"""

import sqlite3
import os
from pathlib import Path


def update_schema(db_path: str):
    """
    Update database schema with new columns for behavioral metrics.

    Args:
        db_path: Path to polymarket_tracker.db
    """
    print(f"\n{'='*70}")
    print(f"  DATABASE SCHEMA UPDATE")
    print(f"{'='*70}")
    print(f"Database: {db_path}\n")

    # Connect to database (read-write mode)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if database exists and has traders table
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='traders'
    """)

    if not cursor.fetchone():
        print("[ERROR] Traders table not found. Database may be corrupted or empty.")
        conn.close()
        return False

    print("[1/2] Updating traders table...")

    # Add columns to traders table
    columns_to_add = [
        ("kelly_alignment_score", "REAL", "Position sizing intelligence (Kelly criterion)"),
        ("patience_score", "REAL", "Trading frequency discipline"),
        ("timing_score", "REAL", "Market entry/exit timing quality"),
        ("weighted_win_rate", "REAL", "Difficulty-adjusted win rate"),
        ("roi_percentage", "REAL", "Return on investment percentage"),
        ("resolved_trades_count", "INTEGER", "Number of trades in resolved markets")
    ]

    for column_name, column_type, description in columns_to_add:
        try:
            cursor.execute(f"""
                ALTER TABLE traders
                ADD COLUMN {column_name} {column_type}
            """)
            print(f"  [+] Added column: {column_name} ({description})")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"  [OK] Column already exists: {column_name}")
            else:
                print(f"  [ERROR] Failed to add {column_name}: {e}")

    print("\n[2/2] Updating markets table...")

    # Add columns to markets table
    market_columns = [
        ("difficulty_score", "REAL", "Market difficulty (volatility, liquidity, maturity)")
    ]

    for column_name, column_type, description in market_columns:
        try:
            cursor.execute(f"""
                ALTER TABLE markets
                ADD COLUMN {column_name} {column_type}
            """)
            print(f"  [+] Added column: {column_name} ({description})")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"  [OK] Column already exists: {column_name}")
            else:
                print(f"  [ERROR] Failed to add {column_name}: {e}")

    # Verify schema updates
    print("\n[VERIFICATION] Checking schema...")

    cursor.execute("PRAGMA table_info(traders)")
    trader_columns = {row[1] for row in cursor.fetchall()}

    cursor.execute("PRAGMA table_info(markets)")
    market_columns_result = {row[1] for row in cursor.fetchall()}

    expected_trader_columns = {
        "kelly_alignment_score", "patience_score", "timing_score",
        "weighted_win_rate", "roi_percentage", "resolved_trades_count"
    }

    expected_market_columns = {"difficulty_score"}

    trader_missing = expected_trader_columns - trader_columns
    market_missing = expected_market_columns - market_columns_result

    if not trader_missing and not market_missing:
        print("  [OK] All new columns added successfully!")
    else:
        if trader_missing:
            print(f"  [WARN] Missing trader columns: {trader_missing}")
        if market_missing:
            print(f"  [WARN] Missing market columns: {market_missing}")

    conn.close()

    print(f"\n{'='*70}")
    print("[SUCCESS] Schema update complete")
    print(f"{'='*70}\n")

    return True


def main():
    """Main entry point."""

    # Find database
    possible_paths = [
        Path('data/polymarket_tracker.db'),
        Path('monitoring/data/markets.db'),
        Path('polymarket_tracker.db')
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = path
            break

    if not db_path:
        print("[ERROR] Database not found in any of:")
        for path in possible_paths:
            print(f"  - {path}")
        print("\nPlease ensure the database exists before running this script.")
        return

    # Update schema
    success = update_schema(str(db_path))

    if success:
        print("Next steps:")
        print("  1. Run analysis scripts to populate new columns:")
        print("     py analysis/trading_behavior_analysis.py")
        print("     py analysis/calculate_weighted_metrics.py")
        print("     py analysis/trader_performance_analysis.py")
        print("\n  2. Run unified ELO system to integrate behavioral metrics:")
        print("     py analysis/unified_elo_system.py")
        print("\n  3. Test the integration:")
        print("     py tests/test_behavioral_integration.py")


if __name__ == '__main__':
    main()
