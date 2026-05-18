#!/usr/bin/env python3
"""
Recalculate Trader Statistics

Manually recalculates win rates for all flagged traders based on
their resolved trades. This is useful after:
- Running backfill_trade_results.py
- Manual database updates
- Fixing data issues
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.trader_statistics import TraderStatisticsCalculator


def main():
    """Recalculate statistics for all flagged traders."""
    print("="*70)
    print("TRADER STATISTICS RECALCULATION")
    print("="*70)

    # Initialize components
    db = Database()
    stats_calculator = TraderStatisticsCalculator(db, min_resolved_trades=5)

    # Show current state
    print("\nCurrent database state:")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    flagged_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT trader_address)
        FROM trades
        WHERE trade_result IN ('won', 'lost')
    """)
    traders_with_resolved = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE trade_result IN ('won', 'lost')
    """)
    resolved_trades_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE trade_result = 'won'
    """)
    won_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM trades
        WHERE trade_result = 'lost'
    """)
    lost_count = cursor.fetchone()[0]

    conn.close()

    print(f"  Flagged traders: {flagged_count}")
    print(f"  Traders with resolved trades: {traders_with_resolved}")
    print(f"  Total resolved trades: {resolved_trades_count}")
    print(f"    Won: {won_count}")
    print(f"    Lost: {lost_count}")

    if resolved_trades_count == 0:
        print("\n[WARNING] No resolved trades found!")
        print("Make sure to run:")
        print("  1. python scripts/backfill_trade_results.py")
        print("  2. python monitoring/fast_resolution_check.py")
        return

    # Auto-proceed in non-interactive mode
    print(f"\nThis will recalculate win rates for {flagged_count} flagged traders.")
    print(f"Minimum threshold: {stats_calculator.min_resolved_trades} resolved trades")
    print("Auto-proceeding (non-interactive mode)")

    # Run recalculation
    results = stats_calculator.recalculate_all_flagged_traders(verbose=True)

    # Show final state
    print("\n" + "="*70)
    print("RECALCULATION SUMMARY")
    print("="*70)
    print(f"Traders processed: {results['traders_processed']}")
    print(f"Traders updated: {results['traders_updated']}")
    print(f"Traders with {stats_calculator.min_resolved_trades}+ resolved trades: {results['traders_with_minimum']}")

    if results['traders_with_minimum'] > 0:
        print(f"Average win rate: {results['average_win_rate']:.2f}%")

    # Show top performers
    if results['traders_with_minimum'] > 0:
        print("\n" + "="*70)
        print("TOP 5 PERFORMERS (by win rate)")
        print("="*70)

        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT address, win_rate, total_trades, successful_trades
            FROM traders
            WHERE is_flagged = 1
            AND win_rate > 0
            ORDER BY win_rate DESC
            LIMIT 5
        """)

        top_traders = cursor.fetchall()
        conn.close()

        if top_traders:
            for i, (address, win_rate, total_trades, successful_trades) in enumerate(top_traders, 1):
                print(f"{i}. {address[:10]}... | Win Rate: {win_rate:.1f}% | "
                      f"Wins: {successful_trades} | Total: {total_trades}")
        else:
            print("No traders with calculated win rates yet.")

    print("\n[SUCCESS] Recalculation complete!")
    print("\nNext steps:")
    print("  - Run: python scripts/view_trader_stats.py")
    print("  - Check trader performance in your monitoring dashboard")
    print()


if __name__ == "__main__":
    main()
