#!/usr/bin/env python3
"""
Update Database from Analysis CSVs

Imports behavioral, weighted, and performance metrics from CSV files
into the database columns.

Run after analysis scripts have generated their CSV outputs.
"""

import sys
import csv
import sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))


def import_behavioral_metrics(db_path: str, csv_path: str) -> int:
    """Import behavioral metrics from trading_behavior CSV."""
    print(f"\n[1/3] Importing behavioral metrics from {csv_path}...")

    if not Path(csv_path).exists():
        print(f"  [SKIP] File not found: {csv_path}")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    updated = 0
    skipped = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        # Skip first 2 rows (timestamp and blank row)
        next(f)
        next(f)
        reader = csv.DictReader(f)
        for row in reader:
            trader_address = row.get('Trader Address')

            if not trader_address:
                skipped += 1
                continue

            # Extract behavioral scores
            kelly_score = row.get('Kelly Alignment Score')
            patience_score = row.get('Patience Score')
            timing_score = row.get('Optimal Timing Score')

            # Convert 'N/A' to None
            try:
                kelly_score = float(kelly_score) if kelly_score and kelly_score != 'N/A' else None
            except ValueError:
                kelly_score = None

            try:
                patience_score = float(patience_score) if patience_score and patience_score != 'N/A' else None
            except ValueError:
                patience_score = None

            try:
                timing_score = float(timing_score) if timing_score and timing_score != 'N/A' else None
            except ValueError:
                timing_score = None

            cursor.execute("""
                UPDATE traders
                SET kelly_alignment_score = ?,
                    patience_score = ?,
                    timing_score = ?
                WHERE address = ?
            """, (kelly_score, patience_score, timing_score, trader_address))

            if cursor.rowcount > 0:
                updated += 1

    conn.commit()
    conn.close()

    print(f"   Updated {updated} traders with behavioral metrics ({skipped} skipped)")
    return updated


def import_weighted_metrics(db_path: str, csv_path: str) -> int:
    """Import weighted metrics from weighted_metrics CSV."""
    print(f"\n[2/3] Importing weighted metrics from {csv_path}...")

    if not Path(csv_path).exists():
        print(f"  [SKIP] File not found: {csv_path}")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    updated = 0
    skipped = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        # Skip first 2 rows (timestamp and blank row)
        next(f)
        next(f)
        reader = csv.DictReader(f)
        for row in reader:
            trader_address = row.get('Trader Address')

            if not trader_address:
                skipped += 1
                continue

            weighted_wr = row.get('Weighted Win Rate (%)')
            resolved_count = row.get('Resolved Trades')

            try:
                weighted_wr = float(weighted_wr) if weighted_wr and weighted_wr != 'N/A' else None
            except ValueError:
                weighted_wr = None

            try:
                resolved_count = int(resolved_count) if resolved_count and resolved_count != 'N/A' else None
            except ValueError:
                resolved_count = None

            cursor.execute("""
                UPDATE traders
                SET weighted_win_rate = ?,
                    resolved_trades_count = ?
                WHERE address = ?
            """, (weighted_wr, resolved_count, trader_address))

            if cursor.rowcount > 0:
                updated += 1

    conn.commit()
    conn.close()

    print(f"   Updated {updated} traders with weighted metrics ({skipped} skipped)")
    return updated


def import_performance_metrics(db_path: str, csv_path: str) -> int:
    """Import ROI from trader_performance CSV."""
    print(f"\n[3/3] Importing performance metrics from {csv_path}...")

    if not Path(csv_path).exists():
        print(f"  [SKIP] File not found: {csv_path}")
        return 0

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    updated = 0
    skipped = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        # Skip first 2 rows (timestamp and blank row)
        next(f)
        next(f)
        reader = csv.DictReader(f)
        for row in reader:
            trader_address = row.get('Trader Address')

            if not trader_address:
                skipped += 1
                continue

            roi = row.get('ROI (%)')

            try:
                roi = float(roi) if roi and roi != 'N/A' else None
            except ValueError:
                roi = None

            cursor.execute("""
                UPDATE traders
                SET roi_percentage = ?
                WHERE address = ?
            """, (roi, trader_address))

            if cursor.rowcount > 0:
                updated += 1

    conn.commit()
    conn.close()

    print(f"   Updated {updated} traders with ROI metrics ({skipped} skipped)")
    return updated


def main():
    """Main entry point."""
    print("\n" + "="*70)
    print("  UPDATE DATABASE FROM ANALYSIS CSVs")
    print("="*70)

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
        print("\n[ERROR] Database not found in any of:")
        for path in possible_paths:
            print(f"  - {path}")
        return False

    print(f"\nUsing database: {db_path}")

    # Find most recent CSV files
    reports_dir = Path('reports')
    if not reports_dir.exists():
        print("\n[ERROR] Reports directory not found. Run analysis scripts first:")
        print("  1. py analysis/trading_behavior_analysis.py")
        print("  2. py analysis/calculate_weighted_metrics.py")
        print("  3. py analysis/trader_performance_analysis.py")
        return False

    # Find most recent CSVs
    behavioral_csvs = sorted(reports_dir.glob('trading_behavior_alltime_*.csv'), reverse=True)
    weighted_csvs = sorted(reports_dir.glob('weighted_metrics_*.csv'), reverse=True)
    performance_csvs = sorted(reports_dir.glob('trader_performance_alltime_*.csv'), reverse=True)

    behavioral_csv = behavioral_csvs[0] if behavioral_csvs else None
    weighted_csv = weighted_csvs[0] if weighted_csvs else None
    performance_csv = performance_csvs[0] if performance_csvs else None

    print(f"\nUsing CSV files:")
    print(f"  Behavioral: {behavioral_csv.name if behavioral_csv else 'NOT FOUND'}")
    print(f"  Weighted:   {weighted_csv.name if weighted_csv else 'NOT FOUND'}")
    print(f"  Performance: {performance_csv.name if performance_csv else 'NOT FOUND'}")

    if not behavioral_csv and not weighted_csv and not performance_csv:
        print("\n[ERROR] No CSV files found. Please run analysis scripts first.")
        return False

    # Import each
    total_updated = 0
    if behavioral_csv:
        total_updated += import_behavioral_metrics(str(db_path), str(behavioral_csv))
    if weighted_csv:
        total_updated += import_weighted_metrics(str(db_path), str(weighted_csv))
    if performance_csv:
        total_updated += import_performance_metrics(str(db_path), str(performance_csv))

    print("\n" + "="*70)
    print(f"   DATABASE UPDATE COMPLETE")
    print("="*70)
    print(f"  Total updates: {total_updated}")
    print()

    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
