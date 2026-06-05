#!/usr/bin/env python3
"""
Test ELO caching performance improvement.

This script tests the performance difference between:
1. First run: Full base ELO calculation (slow)
2. Second run: Cached base ELO (fast)

Expected results:
- First run: ~200s+ (market resolution checks)
- Second run: <10s (using cached data)
"""

import sys
import os
import time
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


def test_caching_performance(num_traders: int = 20):
    """Test ELO caching performance."""
    print("="*70)
    print(f"  ELO CACHING PERFORMANCE TEST ({num_traders} traders)")
    print("="*70)

    # Initialize bridge
    db = Database()
    bridge = UnifiedELOMonitoringBridge(db=db)

    # Get some traders
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT trader_address
        FROM trades
        LIMIT ?
    """, (num_traders,))
    traders = [row[0] for row in cursor.fetchall()]

    print(f"\nTesting with {len(traders)} traders...")

    # TEST 1: First run (should calculate base ELO)
    print("\n" + "="*70)
    print("TEST 1: First run (will calculate base ELO)")
    print("="*70)

    start = time.time()
    result1 = bridge.quick_elo_update_for_traders(traders, verbose=True, force_refresh=False)
    time1 = time.time() - start

    print(f"\n[TEST 1] Completed in {time1:.2f}s")
    print(f"   Per trader: {time1/len(traders):.3f}s")
    print(f"   Throughput: {len(traders)/time1:.1f} traders/second")

    # Wait a moment
    print("\nWaiting 2 seconds before second run...")
    time.sleep(2)

    # TEST 2: Second run (should use cached base ELO)
    print("\n" + "="*70)
    print("TEST 2: Second run (should use cached base ELO)")
    print("="*70)

    start = time.time()
    result2 = bridge.quick_elo_update_for_traders(traders, verbose=True, force_refresh=False)
    time2 = time.time() - start

    print(f"\n[TEST 2] Completed in {time2:.2f}s")
    print(f"   Per trader: {time2/len(traders):.3f}s")
    print(f"   Throughput: {len(traders)/time2:.1f} traders/second")

    # Summary
    print("\n" + "="*70)
    print("  CACHING PERFORMANCE SUMMARY")
    print("="*70)

    speedup = time1 / time2 if time2 > 0 else 0
    time_saved = time1 - time2

    print(f"\nFirst run (uncached):  {time1:.2f}s ({time1/len(traders):.3f}s per trader)")
    print(f"Second run (cached):   {time2:.2f}s ({time2/len(traders):.3f}s per trader)")
    print(f"\nSpeedup: {speedup:.1f}x faster")
    print(f"Time saved: {time_saved:.2f}s ({int(time_saved/60)}m {int(time_saved%60)}s)")

    # Performance check
    if time2 / len(traders) < 0.5:
        print("\n[OK] Cached performance meets target (<0.5s per trader)")
    elif time2 / len(traders) < 1.0:
        print("\n[GOOD] Cached performance is acceptable (<1s per trader)")
    else:
        print("\n[WARN] Cached performance still needs optimization (>1s per trader)")

    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test ELO caching performance")
    parser.add_argument("--traders", type=int, default=20, help="Number of traders to test")
    args = parser.parse_args()

    test_caching_performance(args.traders)
