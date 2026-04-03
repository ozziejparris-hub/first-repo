"""
Background P&L Worker - Continuously updates trader P&L without blocking monitoring.

This worker runs independently of the main monitoring loop and processes
traders at a steady pace, ensuring all traders eventually get P&L updates
without causing timeouts or blocking the monitoring system.

Threading model
---------------
ALL SQLite I/O — fetching trades, matching positions, writing positions,
updating the tr222222aders row, marking updated — runs inside a single
ThreadPoolExecutor call (_process_trader_sync).  The asyncio event loop
thread never touches SQLite directly, so it cannot block.

A 90-second asyncio.wait_for timeout guards every trader.  If a trader
exceeds that budget (e.g. because of extreme trade volume or a slow disk
flush), it is skipped and marked updated so it won't immediately requeue.
"""

import asyncio
import concurrent.futures
import time
from datetime import datetime
from typing import Optional

from .database import Database
from .position_tracker import PositionTracker

# Single-worker thread pool.  One worker is enough — we want sequential
# processing, not parallelism, to avoid lock contention on the DB.
_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="pnl_worker"
)

# Per-trader time budget.  90 s is generous even for traders with 5 000+
# trades; the timeout only fires if something has gone badly wrong.
_TRADER_TIMEOUT = 90


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
    - Never touches SQLite on the asyncio event loop thread
    - Hard per-trader timeout prevents indefinite hangs
    """

    def __init__(self, database: Database, position_tracker: PositionTracker):
        self.db = database
        self.position_tracker = position_tracker
        self.is_running = False

        # Configuration
        self.batch_size = 100
        self.batch_sleep = 10  # seconds between batches

        # Statistics (read/written only from the event loop thread)
        self.traders_processed = 0
        self.traders_skipped = 0
        self.errors = 0
        self.start_time = None

    async def start(self):
        """Start the background P&L worker."""
        safe_print("\n[P&L WORKER] Starting background P&L worker...")
        self.is_running = True
        self.start_time = time.time()

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

    # ------------------------------------------------------------------ #
    #  Worker loop                                                         #
    # ------------------------------------------------------------------ #

    async def _worker_loop(self):
        """Main worker loop — runs continuously."""
        while self.is_running:
            try:
                traders = self.db.get_traders_needing_pnl_update(limit=self.batch_size)

                if not traders:
                    safe_print(f"[P&L WORKER] All traders up-to-date, sleeping {self.batch_sleep}s...")
                    await asyncio.sleep(self.batch_sleep)
                    continue

                safe_print(f"\n[P&L WORKER] Processing batch of {len(traders)} traders...")
                batch_start = time.time()

                for trader_address, last_trade, last_update in traders:
                    await self._process_single_trader(trader_address)
                    # Yield control between traders so the monitoring loop
                    # and watchdog can always wake up on schedule.
                    await asyncio.sleep(0.1)

                batch_elapsed = time.time() - batch_start
                safe_print(f"[P&L WORKER] Batch complete in {batch_elapsed:.1f}s")

                if self.traders_processed % 100 == 0 and self.traders_processed > 0:
                    self._show_progress()

                await asyncio.sleep(self.batch_sleep)

            except Exception as e:
                safe_print(f"[P&L WORKER] [ERROR] Worker loop error: {e}")
                self.errors += 1
                await asyncio.sleep(60)

    # ------------------------------------------------------------------ #
    #  Per-trader processing — entirely off the event loop                #
    # ------------------------------------------------------------------ #

    def _process_trader_sync(self, trader_address: str) -> dict:
        """
        Complete synchronous processing for one trader.

        Runs in the thread pool — the event loop thread is completely free
        while this executes.  Opens its own SQLite connections; nothing is
        shared with connections on the event loop.

        Returns a result dict with keys:
            trade_count, n_positions, n_closed, skipped, elapsed
        """
        t0 = time.time()

        # 1. Trade count (for logging only)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM trades WHERE trader_address = ?",
            (trader_address,)
        )
        trade_count = cursor.fetchone()[0]
        conn.close()

        # 2. Match trades → positions (CPU-bound FIFO, no DB writes)
        positions = self.position_tracker.match_trades_for_trader(
            trader_address, verbose=False
        )

        if not positions:
            self.db.mark_trader_pnl_updated(trader_address)
            return {
                'trade_count': trade_count,
                'n_positions': 0,
                'n_closed': 0,
                'skipped': False,
                'elapsed': time.time() - t0,
            }

        # 2b. Apply synthetic resolution closes for any open positions in resolved markets
        resolved_markets = self.db.get_resolved_markets_for_trader(trader_address)
        if resolved_markets:
            n_synthetic = self.position_tracker.apply_synthetic_closes(
                positions, resolved_markets
            )
        else:
            n_synthetic = 0

        # 3. Persist positions (one connection, one commit for the batch)
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            for position in positions:
                if hasattr(position, 'to_dict'):
                    pos_dict = position.to_dict()
                else:
                    pos_dict = position

                cursor.execute("""
                    INSERT OR REPLACE INTO positions (
                        position_id, trader_address, market_id, market_title,
                        outcome, entry_shares, entry_avg_price, entry_total_cost,
                        entry_timestamp, entry_trade_ids,
                        exit_shares, exit_avg_price, exit_total_received,
                        exit_timestamp, exit_trade_ids,
                        realized_pnl, roi_percent, holding_period_hours,
                        status, remaining_shares, is_synthetic_close, last_updated
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                """, (
                    pos_dict['position_id'],
                    pos_dict['trader_address'],
                    pos_dict['market_id'],
                    pos_dict['market_title'],
                    pos_dict['outcome'],
                    pos_dict['entry_shares'],
                    pos_dict['entry_avg_price'],
                    pos_dict['entry_total_cost'],
                    pos_dict['entry_timestamp'],
                    pos_dict['entry_trade_ids'],
                    pos_dict['exit_shares'],
                    pos_dict['exit_avg_price'],
                    pos_dict['exit_total_received'],
                    pos_dict['exit_timestamp'],
                    pos_dict['exit_trade_ids'],
                    pos_dict['realized_pnl'],
                    pos_dict['roi_percent'],
                    pos_dict['holding_period_hours'],
                    pos_dict['status'],
                    pos_dict['remaining_shares'],
                    pos_dict.get('is_synthetic_close', 0),
                ))
            conn.commit()
        except Exception as e:
            safe_print(f"[P&L WORKER] [ERROR] Position insert failed for {trader_address[:10]}...: {e}")
            conn.rollback()
        finally:
            conn.close()

        # 4. Aggregate P&L and update traders row
        closed_positions = [p for p in positions if p.status == 'closed']
        n_closed = len(closed_positions)

        if closed_positions:
            realized_pnl = sum(p.realized_pnl for p in closed_positions if p.realized_pnl)
            avg_roi = sum(p.roi_percent for p in closed_positions if p.roi_percent) / n_closed

            conn = self.db.get_connection()
            cursor = conn.cursor()
            try:
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
                    n_closed,
                    len([p for p in positions if p.status == 'open']),
                    trader_address,
                ))
                conn.commit()
            except Exception as e:
                safe_print(f"[P&L WORKER] [ERROR] Trader update failed for {trader_address[:10]}...: {e}")
                conn.rollback()
            finally:
                conn.close()

        # 5. Mark updated (so this trader isn't requeued immediately)
        self.db.mark_trader_pnl_updated(trader_address)

        return {
            'trade_count': trade_count,
            'n_positions': len(positions),
            'n_closed': n_closed,
            'n_synthetic': n_synthetic,
            'skipped': False,
            'elapsed': time.time() - t0,
        }

    async def _process_single_trader(self, trader_address: str):
        """
        Async entry point — submits all work to the thread pool and awaits it.

        The event loop thread itself does zero SQLite I/O here.  If the whole
        operation takes longer than _TRADER_TIMEOUT seconds, it is cancelled
        at the asyncio level and the trader is marked updated to prevent a
        tight requeue loop.  The thread itself may continue briefly after the
        timeout (Python threads are not forcibly killed), but it will finish
        its current SQLite call and exit — no resources are leaked.
        """
        loop = asyncio.get_event_loop()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    _THREAD_POOL,
                    self._process_trader_sync,
                    trader_address,
                ),
                timeout=_TRADER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            safe_print(
                f"[P&L WORKER] [TIMEOUT] {trader_address[:10]}... exceeded {_TRADER_TIMEOUT}s "
                f"— skipping, will requeue after 24h"
            )
            # Best-effort mark updated so we don't requeue immediately.
            # This call is fast (one UPDATE) so it won't stall for long.
            try:
                await loop.run_in_executor(
                    _THREAD_POOL,
                    self.db.mark_trader_pnl_updated,
                    trader_address,
                )
            except Exception:
                pass
            self.errors += 1
            return
        except Exception as e:
            safe_print(f"[P&L WORKER] [ERROR] Failed for {trader_address[:10]}...: {e}")
            self.errors += 1
            return

        # Update counters (event loop thread only — no lock needed)
        self.traders_processed += 1

        elapsed = result['elapsed']
        trade_count = result['trade_count']

        if trade_count > 5000:
            safe_print(
                f"[P&L WORKER] [WHALE] {trader_address[:10]}... "
                f"{trade_count:,} trades → {result['n_positions']} positions "
                f"({result['n_closed']} closed) in {elapsed:.1f}s"
            )
        elif elapsed > 5:
            safe_print(
                f"[P&L WORKER] [SLOW] {trader_address[:10]}... "
                f"({trade_count} trades) took {elapsed:.1f}s"
            )

    # ------------------------------------------------------------------ #
    #  Progress reporting                                                  #
    # ------------------------------------------------------------------ #

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
