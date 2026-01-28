"""
Test script for background P&L worker.

Run this to test the worker independently before integrating into main monitoring.
"""

import asyncio
from monitoring.database import Database
from monitoring.position_tracker import PositionTracker
from monitoring.background_pnl_worker import BackgroundPnLWorker


async def test_worker():
    """Test background worker for 2 minutes."""
    print("="*60)
    print("  TESTING BACKGROUND P&L WORKER")
    print("="*60)
    print()

    db = Database()
    tracker = PositionTracker(db)
    worker = BackgroundPnLWorker(db, tracker)

    print("Testing background worker for 2 minutes...")
    print()

    # Run worker for 2 minutes
    task = asyncio.create_task(worker.start())

    try:
        await asyncio.sleep(120)  # 2 minutes
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")

    worker.stop()

    # Wait for worker to finish
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.TimeoutError:
        print("[WARNING] Worker didn't stop cleanly within 5 seconds")

    print("\n" + "="*60)
    print("  TEST COMPLETE")
    print("="*60)

    # Show final stats
    stats = db.get_pnl_worker_stats()
    print(f"\nFinal Statistics:")
    print(f"  Traders processed: {worker.traders_processed}")
    print(f"  Traders skipped: {worker.traders_skipped}")
    print(f"  Errors: {worker.errors}")
    print()
    print(f"Database State:")
    print(f"  Total active traders: {stats['total_active_traders']}")
    print(f"  Up to date: {stats['up_to_date']}")
    print(f"  Stale (>24h): {stats['stale_pnl']}")
    print(f"  Never updated: {stats['never_updated']}")
    print()

    if worker.traders_processed > 0:
        print("✅ SUCCESS: Worker processed traders successfully!")
    else:
        print("⚠️  WARNING: No traders were processed")


if __name__ == "__main__":
    try:
        asyncio.run(test_worker())
    except KeyboardInterrupt:
        print("\n\nTest interrupted")
