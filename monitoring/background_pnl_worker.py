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

A per-trader asyncio.wait_for timeout guards every trader.  Traders with
more than _LARGE_TRADER_THRESHOLD closed positions get _TRADER_TIMEOUT_LARGE
seconds; all others get _TRADER_TIMEOUT seconds.  If a trader exceeds its
budget it is skipped and marked updated so it won't immediately requeue.
"""

import asyncio
import concurrent.futures
import logging
import sqlite3
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

# Per-trader time budgets.  Traders with many closed positions involve more
# DB writes and a heavier resolved-markets join, so they get extra headroom.
_TRADER_TIMEOUT = 90               # default budget (seconds)
_TRADER_TIMEOUT_LARGE = 180        # budget for large traders
_LARGE_TRADER_THRESHOLD = 100      # closed_positions threshold for large budget

# After this many failures a trader is skipped for the rest of this session.
# pnl_last_updated is NOT stamped — the trader retries on the next restart.
_MAX_TRADER_FAILURES = 5


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

    def __init__(self, database: Database, position_tracker: PositionTracker,
                 logger: Optional[logging.Logger] = None,
                 telegram_bot=None):
        self.db = database
        self.position_tracker = position_tracker
        self.is_running = False
        self.logger = logger or logging.getLogger('pnl_worker')
        self.telegram_bot = telegram_bot  # Optional; send skip alerts if provided

        # Configuration
        self.batch_size = 10
        self.batch_sleep = 1  # seconds between batches

        # Split-batch configuration: reserve slots for backlog so Priority 1
        # traders (recent trades) cannot permanently starve never-updated traders.
        self.priority1_slots = 7   # slots for traders with trades in last hour
        self.backlog_slots = 3     # slots reserved for never-updated / stale >24 h

        # Session-level skip set: address -> consecutive fail count.  Once a
        # trader reaches _MAX_TRADER_FAILURES it is skipped for the rest of
        # this service run; pnl_last_updated is NOT stamped so the trader
        # re-enters the queue on the next restart.
        self.failed_traders: dict = {}

        # Statistics (read/written only from the event loop thread)
        self.traders_processed = 0
        self.traders_skipped = 0
        self.errors = 0
        self.start_time = None

    async def start(self):
        """Start the background P&L worker."""
        # Ensure pnl_skip column exists (idempotent — silently ignored if already present)
        conn = self.db.get_connection()
        try:
            conn.execute("ALTER TABLE traders ADD COLUMN pnl_skip BOOLEAN DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

        self.logger.info("Starting background P&L worker")
        self.is_running = True
        self.start_time = time.time()

        stats = self.db.get_pnl_worker_stats()
        self.logger.info(
            "Initial state — total: %d | never updated: %d | stale >24h: %d | up-to-date: %d",
            stats['total_active_traders'], stats['never_updated'],
            stats['stale_pnl'], stats['up_to_date'],
        )

        await self._worker_loop()

    def stop(self):
        """Stop the background P&L worker."""
        self.logger.info("Stopping")
        self.is_running = False

    # ------------------------------------------------------------------ #
    #  Worker loop                                                         #
    # ------------------------------------------------------------------ #

    def _build_batch(self) -> tuple:
        """
        Assemble a fair batch: up to priority1_slots recent-trade traders plus
        up to backlog_slots never-updated/stale traders.  Unused slots in either
        group are filled from the other so the total stays at batch_size.

        Returns (traders, p1_count, backlog_count).
        """
        p1 = self.db.get_priority1_traders(limit=self.priority1_slots)
        p1_addresses = [row[0] for row in p1]

        # Fill reserved backlog slots; expand if P1 was short
        backlog_limit = self.batch_size - len(p1)
        backlog = self.db.get_backlog_traders(limit=backlog_limit, exclude=p1_addresses) if backlog_limit > 0 else []

        # If backlog is also short, use remaining capacity for extra P1 traders
        remaining = self.batch_size - len(p1) - len(backlog)
        if remaining > 0:
            extra_p1 = self.db.get_priority1_traders(limit=self.priority1_slots + remaining)
            seen = set(p1_addresses) | {row[0] for row in backlog}
            for row in extra_p1:
                if row[0] not in seen and remaining > 0:
                    p1.append(row)
                    seen.add(row[0])
                    remaining -= 1

        return p1 + backlog, len(p1), len(backlog)

    async def _worker_loop(self):
        """Main worker loop — runs continuously."""
        while self.is_running:
            try:
                traders, p1_count, backlog_count = self._build_batch()

                if not traders:
                    self.logger.debug("All traders up-to-date, sleeping %ss", self.batch_sleep)
                    await asyncio.sleep(self.batch_sleep)
                    continue

                self.logger.info(
                    "Batch start: %d traders (priority1=%d, backlog=%d)",
                    len(traders), p1_count, backlog_count,
                )
                batch_start = time.time()

                for trader_address, last_trade, last_update, closed_positions in traders:
                    await self._process_single_trader(trader_address, closed_positions)
                    # Yield control between traders so the monitoring loop
                    # and watchdog can always wake up on schedule.
                    await asyncio.sleep(0.1)

                batch_elapsed = time.time() - batch_start
                self.logger.debug("Batch complete in %.1fs", batch_elapsed)

                if self.traders_processed % 100 == 0 and self.traders_processed > 0:
                    self._show_progress()

                await asyncio.sleep(self.batch_sleep)

            except Exception as e:
                self.logger.exception("Worker loop error")
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

        # 0. Honour pnl_skip flag — skip permanently flagged traders
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT pnl_skip FROM traders WHERE address = ?", (trader_address,)
            ).fetchone()
            pnl_skip = row[0] if row else 0
        finally:
            conn.close()

        if pnl_skip:
            self.logger.debug("pnl_skip=1 for %s — skipping", trader_address[:10])
            self.db.mark_trader_pnl_updated(trader_address)
            return {
                'trade_count': 0, 'n_positions': 0, 'n_closed': 0,
                'n_synthetic': 0, 'skipped': True, 'elapsed': time.time() - t0,
            }

        # 1. Trade count (for logging only)
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM trades WHERE trader_address = ?",
                (trader_address,)
            )
            trade_count = cursor.fetchone()[0]
        finally:
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

                # Dedup guard: if a row already exists for the same logical position
                # (same trader/market/outcome/entry_timestamp) but with a different
                # position_id (timezone artifact from the April 2026 server migration),
                # reuse the existing position_id so we update rather than duplicate.
                existing = cursor.execute("""
                    SELECT position_id FROM positions
                    WHERE trader_address = ? AND market_id = ? AND outcome = ? AND entry_timestamp = ?
                    LIMIT 1
                """, (pos_dict['trader_address'], pos_dict['market_id'],
                      pos_dict['outcome'], pos_dict['entry_timestamp'])).fetchone()
                if existing and existing[0] != pos_dict['position_id']:
                    pos_dict['position_id'] = existing[0]

                cursor.execute("""
                    INSERT INTO positions (
                        position_id, trader_address, market_id, market_title,
                        outcome, entry_shares, entry_avg_price, entry_total_cost,
                        entry_timestamp, entry_trade_ids,
                        exit_shares, exit_avg_price, exit_total_received,
                        exit_timestamp, exit_trade_ids,
                        realized_pnl, roi_percent, holding_period_hours,
                        status, remaining_shares, is_synthetic_close, last_updated, data_source
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,'position_tracker')
                    ON CONFLICT(position_id) DO UPDATE SET
                        market_title         = excluded.market_title,
                        entry_shares         = excluded.entry_shares,
                        entry_avg_price      = excluded.entry_avg_price,
                        entry_total_cost     = excluded.entry_total_cost,
                        entry_trade_ids      = excluded.entry_trade_ids,
                        exit_shares          = excluded.exit_shares,
                        exit_avg_price       = excluded.exit_avg_price,
                        exit_total_received  = excluded.exit_total_received,
                        exit_timestamp       = excluded.exit_timestamp,
                        exit_trade_ids       = excluded.exit_trade_ids,
                        realized_pnl         = excluded.realized_pnl,
                        roi_percent          = excluded.roi_percent,
                        holding_period_hours = excluded.holding_period_hours,
                        status               = excluded.status,
                        remaining_shares     = excluded.remaining_shares,
                        last_updated         = CURRENT_TIMESTAMP
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
            self.logger.exception("Position insert failed for %s", trader_address[:10])
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
                self.logger.exception("Trader update failed for %s", trader_address[:10])
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

    async def _process_single_trader(self, trader_address: str, closed_positions: int = 0):
        """
        Async entry point — submits all work to the thread pool and awaits it.

        The event loop thread itself does zero SQLite I/O here.  If the whole
        operation takes longer than the per-trader budget, it is cancelled at
        the asyncio level and the trader is marked updated to prevent a tight
        requeue loop.  The thread itself may continue briefly after the timeout
        (Python threads are not forcibly killed), but it will finish its current
        SQLite call and exit — no resources are leaked.
        """
        # Permanently skipped traders are ignored for the rest of the session.
        if self.failed_traders.get(trader_address, 0) >= _MAX_TRADER_FAILURES:
            return

        timeout = (
            _TRADER_TIMEOUT_LARGE
            if closed_positions > _LARGE_TRADER_THRESHOLD
            else _TRADER_TIMEOUT
        )

        loop = asyncio.get_event_loop()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    _THREAD_POOL,
                    self._process_trader_sync,
                    trader_address,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Timeout: %s exceeded %ds — recording failure (retry on restart if threshold reached)",
                trader_address[:10], timeout,
            )
            self.errors += 1
            await self._record_failure(trader_address, loop)
            return
        except Exception:
            self.logger.exception("Failed for %s", trader_address[:10])
            self.errors += 1
            await self._record_failure(trader_address, loop)
            return

        # Update counters (event loop thread only — no lock needed)
        self.traders_processed += 1

        elapsed = result['elapsed']
        trade_count = result['trade_count']

        if trade_count > 5000:
            self.logger.info(
                "Whale: %s — %s trades, %d positions (%d closed) in %.1fs",
                trader_address[:10], f"{trade_count:,}",
                result['n_positions'], result['n_closed'], elapsed,
            )
        elif elapsed > 5:
            self.logger.warning(
                "Slow: %s — %d trades took %.1fs",
                trader_address[:10], trade_count, elapsed,
            )

    # ------------------------------------------------------------------ #
    #  Failure tracking                                                    #
    # ------------------------------------------------------------------ #

    async def _record_failure(self, trader_address: str, loop):
        """
        Increment the failure counter for a trader.  On reaching
        _MAX_TRADER_FAILURES the trader is added to the session-level skip
        set and a Telegram alert (if configured) plus an ERROR log are emitted.
        pnl_last_updated is NOT stamped — the trader retries on next restart.
        All subsequent calls for this address within the session are no-ops.
        """
        count = self.failed_traders.get(trader_address, 0) + 1
        self.failed_traders[trader_address] = count

        if count >= _MAX_TRADER_FAILURES:
            msg = (
                f"[PNL WORKER] Skipping {trader_address[:8]}... after "
                f"{_MAX_TRADER_FAILURES} consecutive failures. "
                f"Will retry on next service restart."
            )
            self.logger.error(msg)
            if self.telegram_bot is not None:
                try:
                    await self.telegram_bot.send_message(msg)
                except Exception:
                    self.logger.warning(
                        "Failed to send PNL skip Telegram alert for %s",
                        trader_address[:10],
                    )
            # Persist skip permanently so restarts don't retry this trader
            try:
                conn = sqlite3.connect(self.db.db_path, timeout=10)
                conn.execute(
                    "UPDATE traders SET pnl_skip = 1 WHERE address = ?",
                    (trader_address,)
                )
                conn.commit()
                conn.close()
                self.logger.warning(
                    "pnl_skip=1 persisted for %s — will not retry after restart",
                    trader_address[:10],
                )
            except Exception as e:
                self.logger.error("Failed to persist pnl_skip for %s: %s", trader_address[:10], e)

    # ------------------------------------------------------------------ #
    #  Progress reporting                                                  #
    # ------------------------------------------------------------------ #

    def _show_progress(self):
        """Show worker progress statistics."""
        uptime = time.time() - self.start_time
        stats = self.db.get_pnl_worker_stats()
        self.logger.info(
            "Progress — uptime: %.1fh | processed: %d | skipped: %d | errors: %d | "
            "rate: %.1f/min | up-to-date: %d | stale: %d | never-updated: %d",
            uptime / 3600, self.traders_processed, self.traders_skipped, self.errors,
            self.traders_processed / (uptime / 60),
            stats['up_to_date'], stats['stale_pnl'], stats['never_updated'],
        )
