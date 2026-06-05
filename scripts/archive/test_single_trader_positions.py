#!/usr/bin/env python3
"""
Test position tracking for a single trader to isolate the issue.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database
from monitoring.position_tracker import PositionTracker


def main():
    print("\n" + "="*70)
    print("  SINGLE TRADER POSITION TRACKING TEST")
    print("="*70 + "\n")

    db = Database()
    tracker = PositionTracker(db)

    # Get a trader with many trades
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT trader_address, COUNT(*) as trade_count
        FROM trades
        GROUP BY trader_address
        ORDER BY trade_count DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    if not row:
        print("[ERROR] No traders found in database")
        return

    trader_address = row[0]
    trade_count = row[1]

    print(f"Testing with trader: {trader_address}")
    print(f"Total trades: {trade_count}\n")

    # Check positions before
    cursor.execute("SELECT COUNT(*) FROM positions")
    positions_before = cursor.fetchone()[0]
    print(f"Positions in database BEFORE: {positions_before:,}\n")

    # Test position matching
    print("[1] Matching trades into positions...")
    try:
        positions = tracker.match_trades_for_trader(trader_address)
        print(f"   [OK] Matched {len(positions)} positions\n")

        if len(positions) > 0:
            print("[2] Position details (first 5):")
            for i, pos in enumerate(positions[:5], 1):
                print(f"   Position {i}:")
                print(f"      Position ID: {pos.position_id[:30]}...")
                print(f"      Market: {pos.market_title[:40]}...")
                print(f"      Outcome: {pos.outcome}")
                print(f"      Shares: {pos.entry_shares:.2f}")
                print(f"      Status: {pos.status}")
                if pos.realized_pnl is not None:
                    print(f"      P&L: ${pos.realized_pnl:.2f}")
                    print(f"      ROI: {pos.roi_percent:.1f}%")
                print()

        # Test database insert
        print(f"[3] Testing database insert for all {len(positions)} positions...")
        positions_inserted = 0

        for position in positions:
            try:
                result = db.insert_position(position)
                if result:
                    positions_inserted += 1
            except Exception as e:
                print(f"   [ERROR] Failed to insert position: {e}")
                break

        print(f"   [OK] Inserted {positions_inserted} positions\n")

        # Verify they were saved
        cursor.execute("SELECT COUNT(*) FROM positions")
        positions_after = cursor.fetchone()[0]

        print(f"[4] Verification:")
        print(f"   Positions BEFORE: {positions_before:,}")
        print(f"   Positions AFTER: {positions_after:,}")
        print(f"   New positions: {positions_after - positions_before:,}")

        if positions_after > positions_before:
            print(f"\n   [SUCCESS] Positions are being saved to database!")
        else:
            print(f"\n   [ERROR] Positions NOT saved to database!")

        # Check closed positions
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'closed'")
        closed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'open'")
        open_pos = cursor.fetchone()[0]

        print(f"\n[5] Position breakdown:")
        print(f"   Total: {positions_after:,}")
        print(f"   Closed: {closed:,}")
        print(f"   Open: {open_pos:,}")

    except AttributeError as e:
        print(f"   [ERROR] Method does not exist: {e}")
    except Exception as e:
        print(f"   [ERROR] {e}")
        import traceback
        traceback.print_exc()

    conn.close()

    print("\n" + "="*70 + "\n")

if __name__ == '__main__':
    main()
