#!/usr/bin/env python3
"""
Build Positions from Historical Trades

This script processes the existing 11,000+ trades in the database to create
position records by matching BUY and SELL trades using FIFO logic.

This is a ONE-TIME processing script that should be run after the migration
to populate the positions table with historical data.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.position_tracker import PositionTracker
import time


def main():
    """Build positions from all historical trades."""
    print("="*70)
    print("BUILD POSITIONS FROM HISTORICAL TRADES")
    print("="*70)

    # Initialize components
    db = Database()
    tracker = PositionTracker(db)

    # Show current state
    print("\nCurrent database state:")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    flagged_traders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM positions")
    existing_positions = cursor.fetchone()[0]

    conn.close()

    print(f"  Flagged traders: {flagged_traders}")
    print(f"  Total trades: {total_trades}")
    print(f"  Existing positions: {existing_positions}")

    # Confirm before proceeding
    print(f"\nThis will process trades for {flagged_traders} traders to create positions.")
    print("This may take several minutes...")
    proceed = input("Proceed? (yes/no): ").strip().lower()

    if proceed != 'yes':
        print("Cancelled.")
        return

    # Get all flagged traders
    traders = db.get_flagged_traders()

    print(f"\n{'='*70}")
    print(f"PROCESSING {len(traders)} TRADERS")
    print(f"{'='*70}\n")

    total_positions = 0
    total_closed = 0
    total_open = 0
    total_pnl = 0.0
    traders_processed = 0
    traders_with_positions = 0

    start_time = time.time()

    for i, trader in enumerate(traders, 1):
        # Match trades for this trader
        positions = tracker.match_trades_for_trader(trader, verbose=False)

        if positions:
            # Store positions
            tracker.store_positions(positions, verbose=False)

            # Update counters
            traders_with_positions += 1
            total_positions += len(positions)

            closed = [p for p in positions if p.status == 'closed']
            open_pos = [p for p in positions if p.status == 'open']

            total_closed += len(closed)
            total_open += len(open_pos)

            # Calculate P&L for this trader
            pnl = sum(p.realized_pnl for p in closed if p.realized_pnl is not None)
            total_pnl += pnl

        traders_processed += 1

        # Show progress
        if i % 100 == 0 or i == len(traders):
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(traders) - i) / rate if rate > 0 else 0

            print(f"[PROGRESS] Processed {i}/{len(traders)} traders "
                  f"({i/len(traders)*100:.1f}%) | "
                  f"Positions: {total_positions} | "
                  f"ETA: {eta:.0f}s")

    elapsed_total = time.time() - start_time

    # Final summary
    print(f"\n{'='*70}")
    print("POSITION BUILDING COMPLETE")
    print(f"{'='*70}")
    print(f"Time elapsed: {elapsed_total:.1f} seconds ({elapsed_total/60:.1f} minutes)")
    print(f"\nTraders:")
    print(f"  Total processed: {traders_processed}")
    print(f"  With positions: {traders_with_positions}")
    print(f"  Without positions: {traders_processed - traders_with_positions}")

    print(f"\nPositions:")
    print(f"  Total created: {total_positions}")
    print(f"  Closed positions: {total_closed}")
    print(f"  Open positions: {total_open}")

    if total_closed > 0:
        avg_pnl_per_position = total_pnl / total_closed
        print(f"\nRealized P&L:")
        print(f"  Total: ${total_pnl:,.2f}")
        print(f"  Average per closed position: ${avg_pnl_per_position:,.2f}")

    # Update trader statistics with P&L
    print(f"\n{'='*70}")
    print("UPDATING TRADER STATISTICS FROM POSITIONS TABLE")
    print(f"{'='*70}\n")

    conn = db.get_connection()
    cursor = conn.cursor()

    # Calculate stats directly from positions table (more efficient)
    cursor.execute("""
        UPDATE traders
        SET
            realized_pnl = (
                SELECT COALESCE(SUM(realized_pnl), 0)
                FROM positions
                WHERE positions.trader_address = traders.address
                AND positions.status = 'closed'
            ),
            avg_roi = (
                SELECT COALESCE(AVG(roi_percent), 0)
                FROM positions
                WHERE positions.trader_address = traders.address
                AND positions.status = 'closed'
            ),
            total_invested = (
                SELECT COALESCE(SUM(entry_total_cost), 0)
                FROM positions
                WHERE positions.trader_address = traders.address
            ),
            closed_positions = (
                SELECT COUNT(*)
                FROM positions
                WHERE positions.trader_address = traders.address
                AND positions.status = 'closed'
            ),
            open_positions = (
                SELECT COUNT(*)
                FROM positions
                WHERE positions.trader_address = traders.address
                AND positions.status = 'open'
            ),
            last_updated = CURRENT_TIMESTAMP
        WHERE is_flagged = 1
    """)

    updated_traders = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"[COMPLETE] Updated statistics for {updated_traders} traders using SQL aggregation")

    # Show top performers by P&L
    print(f"\n{'='*70}")
    print("TOP 5 PERFORMERS BY REALIZED P&L")
    print(f"{'='*70}")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT address, realized_pnl, avg_roi, closed_positions, open_positions
        FROM traders
        WHERE is_flagged = 1 AND closed_positions > 0
        ORDER BY realized_pnl DESC
        LIMIT 5
    """)

    top_traders = cursor.fetchall()
    conn.close()

    if top_traders:
        for i, (address, pnl, roi, closed, open_pos) in enumerate(top_traders, 1):
            print(f"{i}. {address[:10]}... | "
                  f"P&L: ${pnl:,.2f} | "
                  f"ROI: {roi:.1f}% | "
                  f"Positions: {closed} closed, {open_pos} open")
    else:
        print("No traders with closed positions yet.")

    print(f"\n[SUCCESS] Historical position building complete!")
    print("\nNext steps:")
    print("  - Run: python scripts/view_pnl_performance.py")
    print("  - Run: python scripts/view_trader_stats.py --top 10")
    print()


if __name__ == "__main__":
    main()
