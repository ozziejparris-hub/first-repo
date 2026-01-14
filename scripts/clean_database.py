#!/usr/bin/env python3
"""
Clean Database - Remove Simulation Contamination

Removes simulation data while preserving real monitoring data:
- Simulation traders: total_trades < 100, recent updates
- Simulation markets: Non-standard market IDs
- Associated trades and positions

Usage:
    py scripts/clean_database.py                  # Interactive mode
    py scripts/clean_database.py --auto           # Auto-confirm
    py scripts/clean_database.py --dry-run        # Preview only
"""

import sys
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database


def analyze_contamination(conn):
    """Analyze extent of contamination."""
    cursor = conn.cursor()

    print("=" * 70)
    print("  DATABASE CONTAMINATION ANALYSIS")
    print("=" * 70)
    print()

    # Trader analysis
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN total_trades < 100 THEN 1 END) as potential_simulation,
            COUNT(CASE WHEN total_trades >= 100 THEN 1 END) as likely_real,
            MIN(total_trades) as min_trades,
            MAX(total_trades) as max_trades,
            AVG(total_trades) as avg_trades
        FROM traders
    """)

    row = cursor.fetchone()
    print("[TRADERS]")
    print(f"  Total:                {row[0]:,}")
    print(f"  Potential simulation: {row[1]:,} (total_trades < 100)")
    print(f"  Likely real:          {row[2]:,} (total_trades >= 100)")
    print(f"  Trade range:          {row[3]}-{row[4]} (avg: {row[5]:.1f})")
    print()

    # Market analysis
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(CASE WHEN resolved = 1 THEN 1 END) as resolved,
            COUNT(CASE WHEN resolved = 0 THEN 1 END) as pending,
            COUNT(CASE WHEN last_checked > datetime('now', '-7 days') THEN 1 END) as recent
        FROM markets
    """)

    row = cursor.fetchone()
    print("[MARKETS]")
    print(f"  Total:           {row[0]:,}")
    print(f"  Resolved:        {row[1]:,}")
    print(f"  Pending:         {row[2]:,}")
    print(f"  Recent updates:  {row[3]:,} (< 7 days)")
    print()

    # Trade analysis
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            MIN(timestamp) as earliest,
            MAX(timestamp) as latest
        FROM trades
    """)

    row = cursor.fetchone()
    print("[TRADES]")
    print(f"  Total:    {row[0]:,}")
    print(f"  Earliest: {row[1]}")
    print(f"  Latest:   {row[2]}")
    print()

    # Identify simulation traders
    cursor.execute("""
        SELECT
            COUNT(*) as count,
            MIN(win_rate) as min_wr,
            MAX(win_rate) as max_wr,
            AVG(win_rate) as avg_wr,
            COUNT(CASE WHEN win_rate = 0 THEN 1 END) as zero_wr
        FROM traders
        WHERE total_trades < 100
        AND last_updated > datetime('now', '-7 days')
    """)

    row = cursor.fetchone()
    print("[SIMULATION DETECTION]")
    print(f"  Traders matching criteria:     {row[0]:,}")
    if row[0] > 0:
        print(f"  Win rate range:                {row[1]:.1%} - {row[2]:.1%}")
        print(f"  Average win rate:              {row[3]:.1%}")
        print(f"  Traders with 0% win rate:      {row[4]:,} [SIMULATION INDICATOR]")
    print()

    return row[0], row[4]


def get_simulation_traders(conn):
    """Get list of simulation trader addresses."""
    cursor = conn.cursor()

    # Simulation criteria:
    # 1. total_trades < 100 (simulation was 500 traders with ~26 trades each)
    # 2. Updated recently (within 7 days)
    # 3. OR win_rate = 0 (broken calculation, simulation artifact)

    cursor.execute("""
        SELECT address, total_trades, win_rate, last_updated
        FROM traders
        WHERE (
            (total_trades < 100 AND last_updated > datetime('now', '-7 days'))
            OR (win_rate = 0 AND total_trades > 0)
        )
    """)

    return cursor.fetchall()


def clean_database(conn, dry_run=False):
    """Remove simulation data."""
    cursor = conn.cursor()

    # Get simulation traders
    sim_traders = get_simulation_traders(conn)

    if not sim_traders:
        print("[OK] No simulation traders found!")
        return

    addresses = [t[0] for t in sim_traders]

    print(f"[CLEAN] Found {len(sim_traders)} simulation traders to remove")
    print()

    if dry_run:
        print("[DRY RUN] Would delete:")
        for i, (addr, trades, wr, updated) in enumerate(sim_traders[:10], 1):
            print(f"  {i}. {addr[:20]}... ({trades} trades, {wr:.1%} WR, updated: {updated})")
        if len(sim_traders) > 10:
            print(f"  ... and {len(sim_traders) - 10} more")
        print()

        # Count what would be deleted
        placeholders = ','.join('?' * len(addresses))

        cursor.execute(f"SELECT COUNT(*) FROM trades WHERE trader_address IN ({placeholders})", addresses)
        trades_count = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) FROM positions WHERE trader_address IN ({placeholders})", addresses)
        positions_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM markets
            WHERE last_checked > datetime('now', '-7 days')
            AND market_id IN (
                SELECT DISTINCT market_id FROM trades
                WHERE trader_address IN ({})
            )
        """.format(placeholders), addresses)
        markets_count = cursor.fetchone()[0]

        print(f"[DRY RUN] Would also delete:")
        print(f"  - {trades_count:,} trades")
        print(f"  - {positions_count:,} positions")
        print(f"  - {markets_count:,} simulation markets")
        print()
        print("[DRY RUN] No changes made. Run without --dry-run to execute.")
        return

    # Delete for real
    print("[DELETE] Removing simulation data...")

    placeholders = ','.join('?' * len(addresses))

    # Delete trades
    cursor.execute(f"DELETE FROM trades WHERE trader_address IN ({placeholders})", addresses)
    trades_deleted = cursor.rowcount
    print(f"  [1/4] Deleted {trades_deleted:,} trades")

    # Delete positions
    cursor.execute(f"DELETE FROM positions WHERE trader_address IN ({placeholders})", addresses)
    positions_deleted = cursor.rowcount
    print(f"  [2/4] Deleted {positions_deleted:,} positions")

    # Delete traders
    cursor.execute(f"DELETE FROM traders WHERE address IN ({placeholders})", addresses)
    traders_deleted = cursor.rowcount
    print(f"  [3/4] Deleted {traders_deleted:,} traders")

    # Delete simulation markets (recent, low activity)
    cursor.execute("""
        DELETE FROM markets
        WHERE market_id IN (
            SELECT m.market_id
            FROM markets m
            LEFT JOIN trades t ON m.market_id = t.market_id
            WHERE m.last_checked > datetime('now', '-7 days')
            GROUP BY m.market_id
            HAVING COUNT(t.trade_id) < 10
        )
    """)
    markets_deleted = cursor.rowcount
    print(f"  [4/4] Deleted {markets_deleted:,} low-activity markets")

    conn.commit()

    print()
    print("[OK] Database cleaned successfully!")
    print()


def verify_cleanup(conn):
    """Verify database is clean."""
    cursor = conn.cursor()

    print("=" * 70)
    print("  VERIFICATION")
    print("=" * 70)
    print()

    # Check for remaining contamination
    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE total_trades < 100
        AND last_updated > datetime('now', '-7 days')
    """)

    remaining = cursor.fetchone()[0]

    if remaining == 0:
        print("[OK] No simulation traders remaining")
    else:
        print(f"[WARN] {remaining} potential simulation traders still present")

    # Show trader distribution
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            MIN(total_trades) as min_trades,
            MAX(total_trades) as max_trades,
            AVG(total_trades) as avg_trades,
            COUNT(CASE WHEN win_rate > 0 THEN 1 END) as with_wins
        FROM traders
    """)

    row = cursor.fetchone()
    print()
    print("[TRADERS AFTER CLEANUP]")
    print(f"  Total:          {row[0]:,}")
    if row[0] > 0:
        print(f"  Trade range:    {row[1]}-{row[2]} (avg: {row[3]:.1f})")
        print(f"  With win rate:  {row[4]:,} ({row[4]/max(1,row[0])*100:.1f}%)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Clean simulation data from database',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be deleted without making changes')
    parser.add_argument('--auto', action='store_true',
                       help='Auto-confirm deletion (skip prompt)')

    args = parser.parse_args()

    # Connect to database
    db = Database()
    conn = db.get_connection()

    # Analyze
    num_simulation, num_zero_wr = analyze_contamination(conn)

    if num_simulation == 0:
        print("[OK] Database appears clean!")
        conn.close()
        return

    # Confirm
    if not args.dry_run and not args.auto:
        print("=" * 70)
        response = input(f"\nDelete {num_simulation:,} simulation traders? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("[CANCELLED] No changes made")
            conn.close()
            return
        print()

    # Clean
    clean_database(conn, dry_run=args.dry_run)

    # Verify
    if not args.dry_run:
        verify_cleanup(conn)

    conn.close()


if __name__ == '__main__':
    main()
