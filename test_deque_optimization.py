"""
Test script to verify deque optimization performance improvement.

This script tests the FIFO matching algorithm speed before/after deque optimization.
"""

import time
from monitoring.database import Database
from monitoring.position_tracker import PositionTracker


def test_trader_processing():
    """Test position tracking on traders with varying trade counts."""
    print("="*60)
    print("  DEQUE OPTIMIZATION PERFORMANCE TEST")
    print("="*60)
    print()

    db = Database()
    tracker = PositionTracker(db)

    # Find traders with different trade counts
    conn = db.get_connection()
    cursor = conn.cursor()

    test_ranges = [
        (100, 500, "Small traders (100-500 trades)"),
        (500, 1000, "Medium traders (500-1000 trades)"),
        (1000, 2000, "Large traders (1000-2000 trades)"),
        (2000, 10000, "Whale traders (2000+ trades)")
    ]

    all_results = []

    for min_trades, max_trades, label in test_ranges:
        cursor.execute("""
            SELECT trader_address, COUNT(*) as trade_count
            FROM trades
            GROUP BY trader_address
            HAVING COUNT(*) BETWEEN ? AND ?
            ORDER BY trade_count DESC
            LIMIT 3
        """, (min_trades, max_trades))

        results = cursor.fetchall()

        if results:
            print(f"\n{label}:")
            print("-" * 60)

            for trader, count in results:
                start = time.time()
                positions = tracker.match_trades_for_trader(trader, verbose=False)
                elapsed = time.time() - start

                rate = count / elapsed if elapsed > 0 else 0

                print(f"  {trader[:10]}... : {count:,} trades")
                print(f"    Time: {elapsed:.2f}s")
                print(f"    Rate: {rate:.0f} trades/second")
                print(f"    Positions: {len(positions)}")

                all_results.append({
                    'count': count,
                    'time': elapsed,
                    'rate': rate
                })

                # Flag slow processing
                if elapsed > 10:
                    print(f"    ⚠️  SLOW - Expected <5s with deque optimization")
                elif elapsed > 5:
                    print(f"    ⚠️  Moderate - Could be faster")
                else:
                    print(f"    ✅ FAST - Deque optimization working!")
        else:
            print(f"\n{label}:")
            print(f"  No traders found in this range")

    conn.close()

    # Summary
    if all_results:
        print("\n" + "="*60)
        print("  SUMMARY")
        print("="*60)

        total_trades = sum(r['count'] for r in all_results)
        total_time = sum(r['time'] for r in all_results)
        avg_rate = total_trades / total_time if total_time > 0 else 0

        print(f"\nTotal traders tested: {len(all_results)}")
        print(f"Total trades processed: {total_trades:,}")
        print(f"Total time: {total_time:.1f}s")
        print(f"Average rate: {avg_rate:.0f} trades/second")

        print("\nExpected Performance:")
        print("  - 500 trades: ~1-2s (was 2-4s with list)")
        print("  - 1000 trades: ~2-4s (was 8-12s with list)")
        print("  - 2000 trades: ~4-8s (was 30-40s with list)")
        print("  - 5000 trades: ~15-25s (was 3-5min with list)")

        # Check if optimization is working
        large_traders = [r for r in all_results if r['count'] >= 1000]
        if large_traders:
            avg_time_per_1k = sum(r['time'] for r in large_traders) / sum(r['count']/1000 for r in large_traders)
            print(f"\nAverage time per 1000 trades: {avg_time_per_1k:.1f}s")

            if avg_time_per_1k < 3:
                print("✅ Deque optimization is working perfectly!")
            elif avg_time_per_1k < 6:
                print("✅ Deque optimization is working well")
            else:
                print("⚠️  Optimization may not be applied correctly")

    else:
        print("\n⚠️  No traders found for testing")
        print("Database may be empty or have very few trades")


if __name__ == "__main__":
    try:
        test_trader_processing()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
