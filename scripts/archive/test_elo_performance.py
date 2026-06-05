#!/usr/bin/env python3
"""
Test ELO calculation performance with batch processing optimization.

Benchmarks:
- Position building
- Quick ELO update (batch processing)
- Overall throughput

Target: <0.5s per trader with batch processing
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

import time
from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


def test_performance(num_traders: int = 50):
    """
    Test ELO calculation performance with batch processing.

    Args:
        num_traders: Number of traders to test with

    Returns:
        Dict with performance metrics
    """

    print("=" * 70)
    print(f"  ELO PERFORMANCE TEST ({num_traders} traders)")
    print("=" * 70)

    db = Database()
    bridge = UnifiedELOMonitoringBridge(db)

    # Get test traders
    traders = db.get_flagged_traders()[:num_traders]

    if len(traders) < num_traders:
        print(f"\n[INFO] Only {len(traders)} traders available for testing")

    print(f"\nTesting with {len(traders)} traders...\n")

    # Test 1: Position building
    print("[TEST 1] Position Building...")
    start = time.time()
    position_results = bridge.update_positions_for_traders(traders, verbose=False)
    position_time = time.time() - start

    print(f"[OK] Completed in {position_time:.2f}s")
    print(f"   Traders processed: {position_results['traders_processed']}")
    print(f"   Time per trader: {position_time/len(traders):.3f}s")

    # Test 2: Quick ELO update (BATCH PROCESSING)
    print("\n[TEST 2] Quick ELO Update (Batch Processing)...")
    start = time.time()
    elo_results = bridge.quick_elo_update_for_traders(
        traders,
        verbose=True,
        chunk_size=50  # Batch size
    )
    elo_time = time.time() - start

    print(f"\n[OK] Completed in {elo_time:.2f}s")
    print(f"   Traders updated: {elo_results['traders_updated']}")
    print(f"   Traders failed: {elo_results['traders_failed']}")
    print(f"   Time per trader: {elo_time/len(traders):.3f}s")

    if 'chunks_processed' in elo_results:
        print(f"   Chunks processed: {elo_results['chunks_processed']}")

    # Performance summary
    total_time = position_time + elo_time
    print("\n" + "=" * 70)
    print("  PERFORMANCE SUMMARY")
    print("=" * 70)
    print(f"Total time: {total_time:.2f}s")
    print(f"Average per trader: {total_time/len(traders):.3f}s")
    print(f"Throughput: {len(traders)/total_time:.1f} traders/second")

    # Expected vs actual
    expected_sequential = len(traders) * 3  # Estimate 3s per trader (old way)
    improvement = expected_sequential / total_time

    print(f"\nEstimated sequential time: {expected_sequential:.0f}s")
    print(f"Actual time (batch): {total_time:.2f}s")
    print(f"Speed improvement: {improvement:.1f}x faster")

    print("\n" + "=" * 70)
    if total_time / len(traders) < 0.3:
        print("  [OK] EXCELLENT PERFORMANCE! (<0.3s per trader)")
    elif total_time / len(traders) < 0.5:
        print("  [OK] GOOD PERFORMANCE (<0.5s per trader)")
    elif total_time / len(traders) < 1.0:
        print("  [OK] ACCEPTABLE PERFORMANCE (<1s per trader)")
    else:
        print("  [WARN] NEEDS OPTIMIZATION (>1s per trader)")
    print("=" * 70)

    return {
        'total_time': total_time,
        'per_trader': total_time / len(traders),
        'throughput': len(traders) / total_time,
        'improvement': improvement
    }


if __name__ == "__main__":
    # Allow custom trader count
    import argparse
    parser = argparse.ArgumentParser(description='Test ELO performance')
    parser.add_argument('--traders', type=int, default=50,
                        help='Number of traders to test (default: 50)')
    args = parser.parse_args()

    # Run test
    results = test_performance(num_traders=args.traders)

    print(f"\nFinal Results:")
    print(f"  Per-trader time: {results['per_trader']:.3f}s")
    print(f"  Throughput: {results['throughput']:.1f} traders/sec")
    print(f"  Improvement: {results['improvement']:.1f}x")
