"""
Background P&L Worker - Continuously updates trader P&L without blocking monitoring.

This worker runs independently of the main monitoring loop and processes
traders at a steady pace, ensuring all traders eventually get P&L updates
without causing timeouts or blocking the monitoring system.
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

from .database import Database
from .position_tracker import PositionTracker


def safe_print(message: str, fallback: str = None):
    """Safe print that handles Windows console encoding errors."""
    try:
        print(message)
    except (OSError, UnicodeEncodeError):
        if fallback:
            try:
                print(fallback)
            except (OSError, UnicodeEncodeError):
                pass


class BackgroundPnLWorker:
    """
    Background worker that continuously updates trader P&L.

    Design principles:
    - Runs independently of monitoring loop
    - Processes traders in small batches
    - Prioritizes traders with recent activity
    - Yields control to event loop frequently
    - Never blocks or times out
    """

    def __init__(self, database: Database, position_tracker: PositionTracker):
        """
        Initialize background P&L worker.

        Args:
            database: Database instance
            position_tracker: Position tracker instance
        """
        self.db = database
        self.position_tracker = position_tracker
        self.is_running = False

        # Configuration
        self.batch_size = 20  # Process 20 traders per batch (4x faster)
        self.batch_sleep = 30  # Sleep 30 seconds between batches (4x faster)
        self.trade_limit = 2000  # Skip traders with >2000 trades

        # Statistics
        self.traders_processed = 0
        self.traders_skipped = 0
        self.errors = 0
        self.start_time = None

    async def start(self):
        """Start the background P&L worker."""
        safe_print("\n[P&L WORKER] Starting background P&L worker...")
        self.is_running = True
        self.start_time = time.time()

        # Initial statistics
        stats = self.db.get_pnl_worker_stats()
        safe_print(f"[P&L WORKER] Initial state:")
        safe_print(f"  Total active traders: {stats['total_active_traders']}")
        safe_print(f"  Never updated: {stats['never_updated']}")
        safe_print(f"  Stale P&L (>24h): {stats['stale_pnl']}")
        safe_print(f"  Up to date: {stats['up_to_date']}")

        await self._worker_loop()

    def stop(self):
        """Stop the background P&L worker."""
        safe_print("\n[P&L WORKER] Stopping...")
        self.is_running = False

    async def _worker_loop(self):
        """Main worker loop - runs continuously."""
        while self.is_running:
            try:
                # Get next batch of traders needing updates
                traders = self.db.get_traders_needing_pnl_update(limit=self.batch_size)

                if not traders:
                    # All traders up-to-date
                    safe_print(f"[P&L WORKER] All traders up-to-date, sleeping {self.batch_sleep}s...")
                    await asyncio.sleep(self.batch_sleep)
                    continue

                safe_print(f"\n[P&L WORKER] Processing batch of {len(traders)} traders...")

                # Process batch
                batch_start = time.time()
                for trader_address, last_trade, last_update in traders:
                    await self._process_single_trader(trader_address)
                    await asyncio.sleep(0.1)  # Yield control

                batch_elapsed = time.time() - batch_start
                safe_print(f"[P&L WORKER] Batch complete in {batch_elapsed:.1f}s")

                # Show progress every 10 batches
                if self.traders_processed % 100 == 0 and self.traders_processed > 0:
                    self._show_progress()

                # Sleep between batches
                await asyncio.sleep(self.batch_sleep)

            except Exception as e:
                safe_print(f"[P&L WORKER] [ERROR] Worker loop error: {e}")
                self.errors += 1
                await asyncio.sleep(60)  # Sleep on error

    async def _process_single_trader(self, trader_address: str):
        """
        Process P&L for a single trader.

        Args:
            trader_address: Trader address
        """
        try:
            start_time = time.time()

            # Check trade count first (skip whales)
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM trades
                WHERE trader_address = ?
            """, (trader_address,))
            trade_count = cursor.fetchone()[0]
            conn.close()

            if trade_count > self.trade_limit:
                safe_print(f"[P&L WORKER] [SKIP] {trader_address[:10]}... has {trade_count:,} trades (too many)")
                self.traders_skipped += 1
                self.db.mark_trader_pnl_updated(trader_address)  # Mark as updated to avoid retry
                return

            # Match trades into positions
            positions = self.position_tracker.match_trades_for_trader(trader_address, verbose=False)

            if not positions:
                self.db.mark_trader_pnl_updated(trader_address)
                self.traders_processed += 1
                return

            # Save positions to database
            for position in positions:
                self.db.insert_position(position)

            # Calculate aggregate P&L
            closed_positions = [p for p in positions if p.status == 'closed']

            if closed_positions:
                realized_pnl = sum(p.realized_pnl for p in closed_positions if p.realized_pnl)
                avg_roi = sum(p.roi_percent for p in closed_positions if p.roi_percent) / len(closed_positions)

                # Update trader table
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE traders
                    SET realized_pnl = ?,
                        avg_roi = ?,
                        roi_percentage = ?,
                        closed_positions = ?,
                        open_positions = ?
                    WHERE address = ?
                """, (
                    realized_pnl,
                    avg_roi,
                    avg_roi,
                    len(closed_positions),
                    len([p for p in positions if p.status == 'open']),
                    trader_address
                ))
                conn.commit()
                conn.close()

            # Mark as updated
            self.db.mark_trader_pnl_updated(trader_address)

            elapsed = time.time() - start_time
            if elapsed > 5:
                safe_print(f"[P&L WORKER] [SLOW] {trader_address[:10]}... ({trade_count} trades) took {elapsed:.1f}s")

            self.traders_processed += 1

        except Exception as e:
            safe_print(f"[P&L WORKER] [ERROR] Failed for {trader_address[:10]}...: {e}")
            self.errors += 1

    def _show_progress(self):
        """Show worker progress statistics."""
        uptime = time.time() - self.start_time
        stats = self.db.get_pnl_worker_stats()

        safe_print(f"\n[P&L WORKER] === PROGRESS REPORT ===")
        safe_print(f"  Uptime: {uptime/3600:.1f} hours")
        safe_print(f"  Processed: {self.traders_processed}")
        safe_print(f"  Skipped: {self.traders_skipped}")
        safe_print(f"  Errors: {self.errors}")
        safe_print(f"  Rate: {self.traders_processed/(uptime/60):.1f} traders/min")
        safe_print(f"\n  Current state:")
        safe_print(f"    Up to date: {stats['up_to_date']}")
        safe_print(f"    Stale (>24h): {stats['stale_pnl']}")
        safe_print(f"    Never updated: {stats['never_updated']}")
        safe_print(f"  ========================\n")
