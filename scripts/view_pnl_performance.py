#!/usr/bin/env python3
"""
View P&L Performance

Display trader performance based on position-level P&L metrics.
Shows traders who profit from early exits vs. hold-to-resolution strategies.

This complements the resolution-based win rate tracking.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.position_tracker import PositionTracker
import argparse


def display_summary(db: Database):
    """Display overall P&L summary."""
    print("\n" + "="*70)
    print("P&L PERFORMANCE SUMMARY")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    # Overall counts
    cursor.execute("SELECT COUNT(*) FROM positions")
    total_positions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'closed'")
    closed_positions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'open'")
    open_positions = cursor.fetchone()[0]

    # P&L metrics
    cursor.execute("SELECT SUM(realized_pnl) FROM positions WHERE status = 'closed'")
    total_pnl = cursor.fetchone()[0] or 0

    cursor.execute("SELECT AVG(roi_percent) FROM positions WHERE status = 'closed'")
    avg_roi = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'closed' AND realized_pnl > 0")
    profitable_positions = cursor.fetchone()[0] or 0

    profitable_rate = (profitable_positions / closed_positions * 100) if closed_positions > 0 else 0

    # Traders with P&L
    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1 AND closed_positions > 0")
    traders_with_pnl = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1 AND open_positions > 0")
    traders_with_open = cursor.fetchone()[0]

    conn.close()

    print(f"\nPositions:")
    print(f"  Total: {total_positions:,}")
    print(f"  Closed: {closed_positions:,}")
    print(f"  Open: {open_positions:,}")

    print(f"\nRealized P&L:")
    print(f"  Total: ${total_pnl:,.2f}")
    print(f"  Average ROI: {avg_roi:.2f}%")
    print(f"  Profitable positions: {profitable_positions:,} ({profitable_rate:.1f}%)")

    print(f"\nTraders:")
    print(f"  With closed positions: {traders_with_pnl:,}")
    print(f"  With open positions: {traders_with_open:,}")

    print()


def display_top_pnl(db: Database, limit: int = 10):
    """Display top traders by realized P&L."""
    print("\n" + "="*70)
    print(f"TOP {limit} TRADERS BY REALIZED P&L")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT address, realized_pnl, avg_roi, closed_positions, open_positions, total_invested
        FROM traders
        WHERE is_flagged = 1 AND closed_positions > 0
        ORDER BY realized_pnl DESC
        LIMIT ?
    """, (limit,))

    traders = cursor.fetchall()
    conn.close()

    if not traders:
        print("\nNo traders with closed positions yet.")
        return

    print(f"\n{'Rank':<6}{'Address':<20}{'P&L':<15}{'ROI':<12}{'Closed':<10}{'Open':<10}")
    print("-" * 70)

    for i, (address, pnl, roi, closed, open_pos, invested) in enumerate(traders, 1):
        addr_short = address[:17] + "..."
        pnl_str = f"${pnl:,.2f}"
        print(f"{i:<6}{addr_short:<20}{pnl_str:<15}{roi:>6.1f}%  {closed:<10}{open_pos:<10}")

    print()


def display_top_roi(db: Database, limit: int = 10, min_positions: int = 5):
    """Display top traders by average ROI."""
    print("\n" + "="*70)
    print(f"TOP {limit} TRADERS BY AVERAGE ROI (minimum {min_positions} closed positions)")
    print("="*70)

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT address, realized_pnl, avg_roi, closed_positions, open_positions
        FROM traders
        WHERE is_flagged = 1 AND closed_positions >= ?
        ORDER BY avg_roi DESC
        LIMIT ?
    """, (min_positions, limit))

    traders = cursor.fetchall()
    conn.close()

    if not traders:
        print(f"\nNo traders with at least {min_positions} closed positions yet.")
        return

    print(f"\n{'Rank':<6}{'Address':<20}{'ROI':<12}{'P&L':<15}{'Closed':<10}{'Open':<10}")
    print("-" * 70)

    for i, (address, pnl, roi, closed, open_pos) in enumerate(traders, 1):
        addr_short = address[:17] + "..."
        pnl_str = f"${pnl:,.2f}"
        print(f"{i:<6}{addr_short:<20}{roi:>6.1f}%  {pnl_str:<15}{closed:<10}{open_pos:<10}")

    print()


def display_trader_positions(db: Database, trader_address: str, limit: int = 10):
    """Display positions for a specific trader."""
    tracker = PositionTracker(db)

    print("\n" + "="*70)
    print(f"POSITIONS FOR TRADER: {trader_address}")
    print("="*70)

    # Get trader stats
    trader = db.get_trader_stats(trader_address)
    if not trader:
        print(f"\n[ERROR] Trader {trader_address} not found.")
        return

    if not trader['is_flagged']:
        print(f"\n[WARNING] Trader {trader_address} is not flagged.")
        return

    print(f"\nOverall P&L Statistics:")
    print(f"  Realized P&L: ${trader.get('realized_pnl', 0):,.2f}")
    print(f"  Average ROI: {trader.get('avg_roi', 0):.2f}%")
    print(f"  Total Invested: ${trader.get('total_invested', 0):,.2f}")
    print(f"  Closed Positions: {trader.get('closed_positions', 0)}")
    print(f"  Open Positions: {trader.get('open_positions', 0)}")

    # Get closed positions
    closed_positions = tracker.get_positions_for_trader(trader_address, status='closed')

    if closed_positions:
        print(f"\nClosed Positions (showing last {min(limit, len(closed_positions))}):")
        print(f"{'Market':<40}{'Outcome':<12}{'P&L':<15}{'ROI':<12}{'Days':<10}")
        print("-" * 95)

        for pos in closed_positions[:limit]:
            market = (pos['market_title'][:37] + "...") if len(pos['market_title']) > 40 else pos['market_title']
            outcome = pos['outcome'][:9] + "..." if len(pos['outcome']) > 12 else pos['outcome']
            pnl = f"${pos['realized_pnl']:,.2f}" if pos['realized_pnl'] else "$0.00"
            roi = f"{pos['roi_percent']:.1f}%" if pos['roi_percent'] else "0.0%"
            days = f"{pos['holding_period_hours']/24:.1f}" if pos['holding_period_hours'] else "0.0"

            print(f"{market:<40}{outcome:<12}{pnl:<15}{roi:<12}{days:<10}")

    # Get open positions
    open_positions = tracker.get_positions_for_trader(trader_address, status='open')

    if open_positions:
        print(f"\nOpen Positions (showing last {min(limit, len(open_positions))}):")
        print(f"{'Market':<40}{'Outcome':<12}{'Shares':<12}{'Avg Price':<12}")
        print("-" * 80)

        for pos in open_positions[:limit]:
            market = (pos['market_title'][:37] + "...") if len(pos['market_title']) > 40 else pos['market_title']
            outcome = pos['outcome'][:9] + "..." if len(pos['outcome']) > 12 else pos['outcome']
            shares = f"{pos['entry_shares']:.1f}"
            price = f"${pos['entry_avg_price']:.3f}"

            print(f"{market:<40}{outcome:<12}{shares:<12}{price:<12}")

    print()


def compare_metrics(db: Database, limit: int = 10):
    """Compare P&L-based vs resolution-based rankings."""
    print("\n" + "="*70)
    print("P&L VS RESOLUTION-BASED COMPARISON")
    print("="*70)
    print("\nComparing trading skill (P&L) vs prediction accuracy (win rate)")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            address,
            realized_pnl,
            avg_roi,
            closed_positions,
            win_rate,
            successful_trades
        FROM traders
        WHERE is_flagged = 1
        AND closed_positions > 0
        AND successful_trades > 0
        ORDER BY (realized_pnl + win_rate) DESC
        LIMIT ?
    """, (limit,))

    traders = cursor.fetchall()
    conn.close()

    if not traders:
        print("\nNo traders with both P&L and resolution data yet.")
        return

    print(f"\n{'Rank':<6}{'Address':<17}{'P&L':<15}{'ROI':<10}{'Win Rate':<12}{'Wins':<8}")
    print("-" * 70)

    for i, (address, pnl, roi, closed, win_rate, wins) in enumerate(traders, 1):
        addr_short = address[:14] + "..."
        pnl_str = f"${pnl:,.2f}"
        print(f"{i:<6}{addr_short:<17}{pnl_str:<15}{roi:>5.1f}%  {win_rate:>6.1f}%  {wins:<8}")

    print("\nNote: Higher P&L indicates profitable trading (early exits)")
    print("      Higher win rate indicates accurate predictions (hold to resolution)")
    print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="View P&L performance metrics")
    parser.add_argument('--trader', '-t', type=str, help="View specific trader positions")
    parser.add_argument('--top', type=int, default=10, help="Number of top traders to show (default: 10)")
    parser.add_argument('--min-positions', type=int, default=5, help="Minimum closed positions for ROI ranking (default: 5)")
    parser.add_argument('--compare', action='store_true', help="Compare P&L vs resolution rankings")
    parser.add_argument('--summary-only', action='store_true', help="Show summary only")

    args = parser.parse_args()

    # Initialize database
    db = Database()

    # Check if database has positions
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM positions")
    position_count = cursor.fetchone()[0]
    conn.close()

    if position_count == 0:
        print("\n[ERROR] No positions found in database.")
        print("Run: python scripts/build_positions_historical.py")
        return

    # Execute based on arguments
    if args.trader:
        display_trader_positions(db, args.trader)
    elif args.summary_only:
        display_summary(db)
    elif args.compare:
        display_summary(db)
        compare_metrics(db, args.top)
    else:
        # Default: show summary and top performers
        display_summary(db)
        display_top_pnl(db, args.top)
        display_top_roi(db, args.top, args.min_positions)


if __name__ == "__main__":
    main()
