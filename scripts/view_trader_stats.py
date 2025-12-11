#!/usr/bin/env python3
"""
View Trader Statistics

Display trader performance statistics from the database.
Shows win rates, trade counts, and performance rankings.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.trader_statistics import TraderStatisticsCalculator
import argparse


def display_all_traders(db: Database, min_trades: int = 0):
    """Display statistics for all flagged traders."""
    print("\n" + "="*70)
    print("ALL FLAGGED TRADERS")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.address,
            t.win_rate,
            t.total_trades,
            t.successful_trades,
            t.total_volume,
            COUNT(CASE WHEN tr.trade_result = 'won' THEN 1 END) as resolved_wins,
            COUNT(CASE WHEN tr.trade_result = 'lost' THEN 1 END) as resolved_losses,
            COUNT(CASE WHEN tr.trade_result IN ('won', 'lost') THEN 1 END) as resolved_total
        FROM traders t
        LEFT JOIN trades tr ON t.address = tr.trader_address
        WHERE t.is_flagged = 1
        GROUP BY t.address
        HAVING t.total_trades >= ?
        ORDER BY t.win_rate DESC, resolved_total DESC
    """, (min_trades,))

    traders = cursor.fetchall()
    conn.close()

    if not traders:
        print(f"\nNo traders found with at least {min_trades} trades.")
        return

    print(f"\nShowing {len(traders)} traders (minimum {min_trades} trades)\n")
    print(f"{'Rank':<6}{'Address':<15}{'Win Rate':<12}{'W-L-P':<15}{'Total':<10}{'Volume':<15}")
    print("-" * 70)

    for i, (address, win_rate, total_trades, successful_trades,
            total_volume, resolved_wins, resolved_losses, resolved_total) in enumerate(traders, 1):

        addr_short = address[:12] + "..."
        pending = total_trades - resolved_total
        wlp = f"{resolved_wins}-{resolved_losses}-{pending}"
        volume_str = f"${total_volume:,.0f}" if total_volume else "$0"

        print(f"{i:<6}{addr_short:<15}{win_rate:>6.1f}%  {wlp:<15}{total_trades:<10}{volume_str:<15}")

    print()


def display_top_performers(db: Database, limit: int = 10, min_resolved: int = 5):
    """Display top performing traders."""
    print("\n" + "="*70)
    print(f"TOP {limit} PERFORMERS (minimum {min_resolved} resolved trades)")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.address,
            t.win_rate,
            t.total_trades,
            t.successful_trades,
            COUNT(CASE WHEN tr.trade_result IN ('won', 'lost') THEN 1 END) as resolved_total
        FROM traders t
        LEFT JOIN trades tr ON t.address = tr.trader_address
        WHERE t.is_flagged = 1
        GROUP BY t.address
        HAVING resolved_total >= ?
        ORDER BY t.win_rate DESC
        LIMIT ?
    """, (min_resolved, limit))

    traders = cursor.fetchall()
    conn.close()

    if not traders:
        print(f"\nNo traders found with at least {min_resolved} resolved trades.")
        return

    print(f"\n{'Rank':<6}{'Address':<20}{'Win Rate':<12}{'Wins':<10}{'Resolved':<12}{'Total':<10}")
    print("-" * 70)

    for i, (address, win_rate, total_trades, successful_trades, resolved_total) in enumerate(traders, 1):
        addr_short = address[:17] + "..."
        print(f"{i:<6}{addr_short:<20}{win_rate:>6.1f}%  {successful_trades:<10}{resolved_total:<12}{total_trades:<10}")

    print()


def display_trader_detail(db: Database, trader_address: str):
    """Display detailed statistics for a specific trader."""
    stats_calc = TraderStatisticsCalculator(db)

    # Get trader info
    trader = db.get_trader_stats(trader_address)
    if not trader:
        print(f"\n[ERROR] Trader {trader_address} not found in database.")
        return

    if not trader['is_flagged']:
        print(f"\n[WARNING] Trader {trader_address} is not flagged.")
        return

    print("\n" + "="*70)
    print(f"TRADER DETAILS: {trader_address}")
    print("="*70)

    # Get detailed stats
    stats = stats_calc.calculate_trader_win_rate(trader_address)

    print(f"\nOverall Statistics:")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Total volume: ${trader['total_volume']:,.2f}")
    print(f"  Flagged: {'Yes' if trader['is_flagged'] else 'No'}")

    print(f"\nResolved Trades:")
    print(f"  Total resolved: {stats['resolved_trades']}")
    print(f"  Won: {stats['won_trades']}")
    print(f"  Lost: {stats['lost_trades']}")
    print(f"  Win Rate: {stats['win_rate']:.2f}%")

    if not stats['has_minimum']:
        print(f"\n[NOTE] Need {stats_calc.min_resolved_trades - stats['resolved_trades']} more resolved trades for reliable statistics")

    print(f"\nPending Trades:")
    print(f"  Unresolved: {stats['total_trades'] - stats['resolved_trades']}")

    # Show recent trades
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT market_title, outcome_bet, side, trade_result, timestamp
        FROM trades
        WHERE trader_address = ?
        ORDER BY timestamp DESC
        LIMIT 10
    """, (trader_address,))

    recent_trades = cursor.fetchall()
    conn.close()

    if recent_trades:
        print(f"\nRecent Trades (last 10):")
        print(f"{'Market':<40}{'Outcome':<15}{'Side':<8}{'Result':<10}{'Date':<20}")
        print("-" * 95)

        for market, outcome, side, result, timestamp in recent_trades:
            market_short = (market[:37] + "...") if len(market) > 40 else market
            outcome_short = (outcome[:12] + "...") if len(outcome) > 15 else outcome
            result_display = result if result else "pending"

            print(f"{market_short:<40}{outcome_short:<15}{side:<8}{result_display:<10}{timestamp[:19]:<20}")

    print()


def display_summary(db: Database):
    """Display overall summary statistics."""
    print("\n" + "="*70)
    print("OVERALL STATISTICS")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    # Overall counts
    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    total_flagged = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'won'")
    won_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'lost'")
    lost_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'pending'")
    pending_trades = cursor.fetchone()[0]

    resolved_trades = won_trades + lost_trades
    overall_win_rate = (won_trades / resolved_trades * 100) if resolved_trades > 0 else 0

    # Traders with resolved trades
    cursor.execute("""
        SELECT COUNT(DISTINCT trader_address)
        FROM trades
        WHERE trade_result IN ('won', 'lost')
    """)
    traders_with_resolved = cursor.fetchone()[0]

    # Average win rate for traders with 5+ resolved trades
    cursor.execute("""
        SELECT AVG(t.win_rate)
        FROM traders t
        LEFT JOIN trades tr ON t.address = tr.trader_address
        WHERE t.is_flagged = 1
        GROUP BY t.address
        HAVING COUNT(CASE WHEN tr.trade_result IN ('won', 'lost') THEN 1 END) >= 5
    """)

    avg_win_rate_result = cursor.fetchone()
    avg_win_rate = avg_win_rate_result[0] if avg_win_rate_result and avg_win_rate_result[0] else 0

    conn.close()

    print(f"\nTraders:")
    print(f"  Total flagged traders: {total_flagged}")
    print(f"  Traders with resolved trades: {traders_with_resolved}")
    if avg_win_rate > 0:
        print(f"  Average win rate (5+ resolved): {avg_win_rate:.2f}%")

    print(f"\nTrades:")
    print(f"  Total trades: {total_trades:,}")
    print(f"  Resolved: {resolved_trades:,} ({resolved_trades/total_trades*100:.1f}%)" if total_trades > 0 else "  Resolved: 0")
    print(f"    Won: {won_trades:,}")
    print(f"    Lost: {lost_trades:,}")
    print(f"  Pending: {pending_trades:,}")

    if resolved_trades > 0:
        print(f"\nOverall Win Rate: {overall_win_rate:.2f}%")

    print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="View trader statistics from database")
    parser.add_argument('--trader', '-t', type=str, help="View specific trader by address")
    parser.add_argument('--top', type=int, default=10, help="Number of top traders to show (default: 10)")
    parser.add_argument('--min-trades', type=int, default=0, help="Minimum trades filter (default: 0)")
    parser.add_argument('--min-resolved', type=int, default=5, help="Minimum resolved trades for top performers (default: 5)")
    parser.add_argument('--all', action='store_true', help="Show all traders")
    parser.add_argument('--summary', action='store_true', help="Show summary statistics only")

    args = parser.parse_args()

    # Initialize database
    db = Database()

    # Check if database has data
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    trader_count = cursor.fetchone()[0]
    conn.close()

    if trader_count == 0:
        print("\n[ERROR] No flagged traders found in database.")
        print("Make sure the monitoring system has discovered and flagged traders.")
        return

    # Execute based on arguments
    if args.trader:
        display_trader_detail(db, args.trader)
    elif args.summary:
        display_summary(db)
    elif args.all:
        display_all_traders(db, args.min_trades)
    else:
        # Default: show summary and top performers
        display_summary(db)
        display_top_performers(db, args.top, args.min_resolved)


if __name__ == "__main__":
    main()
