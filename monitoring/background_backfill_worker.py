"""
Background Historical Trade Backfill Worker — passively fetches and inserts
historical trades for newly-discovered traders who have zero trades in the DB.

These traders (typically leaderboard discoveries) had no trades when they were
added, so the P&L worker has nothing to process.  This worker fetches their
trade history from the Polymarket Data API at a slow, rate-limit-safe pace
(one trader per cycle, 5 s sleep between) and inserts the trades so the P&L
worker can subsequently build positions and assign real ELO scores.

Threading model
---------------
All network I/O and SQLite writes run inside a single ThreadPoolExecutor call
(_process_trader_sync).  The asyncio event loop thread never touches the
network or SQLite directly.

A per-trader asyncio.wait_for timeout (60 s default) guards every trader.
After any successful attempt the traders.backfill_attempted column is stamped
so the trader is not retried.  On timeout the column is NOT stamped so the
trader can retry on next restart.
"""

import asyncio
import concurrent.futures
import json
import logging
import sqlite3
import time
import urllib.request
from datetime import datetime
from typing import Optional

from .database import Database

_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="backfill_worker"
)

_TRADER_TIMEOUT = 60          # per-trader budget (seconds)
_MAX_FAILURES = 3             # skip trader for the session after this many consecutive failures
_DATA_API_LIMIT = 500         # page size for the Data API
_SLEEP_BETWEEN_TRADERS = 5   # seconds — keeps Data API rate-limit safe


class BackgroundBackfillWorker:
    """
    Background worker that fetches historical trades for zero-trade traders.

    Design principles:
    - Runs independently of the monitoring loop
    - Processes one trader per cycle at an API-safe pace
    - Stamps backfill_attempted after every successful fetch (skip on timeout)
    - Never touches SQLite or the network on the asyncio event loop thread
    - Hard per-trader timeout prevents indefinite hangs
    """

    def __init__(self, database: Database, logger: Optional[logging.Logger] = None):
        self.db = database
        self.is_running = False
        self.logger = logger or logging.getLogger('backfill_worker')

        self.batch_size = 1
        self.batch_sleep = _SLEEP_BETWEEN_TRADERS

        # session-level failure tracking: address -> consecutive fail count
        self.failed_traders: dict = {}

        # statistics (read/written only from the event loop thread)
        self.traders_processed = 0
        self.errors = 0
        self.start_time = None

        self._ensure_column()

    def _ensure_column(self):
        """Add backfill_attempted column to traders table if not already present."""
        try:
            conn = self.db.get_connection()
            conn.execute(
                "ALTER TABLE traders ADD COLUMN backfill_attempted TIMESTAMP DEFAULT NULL"
            )
            conn.commit()
            conn.close()
            self.logger.info("Added backfill_attempted column to traders table")
        except sqlite3.OperationalError:
            pass  # column already exists — normal after first run

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    async def start(self):
        """Start the background backfill worker."""
        self.logger.info("Starting background historical trade backfill worker")
        self.is_running = True
        self.start_time = time.time()

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM traders
            WHERE is_flagged = 1
            AND research_excluded = 0
            AND (SELECT COUNT(*) FROM trades WHERE trader_address = traders.address) = 0
            AND backfill_attempted IS NULL
        """)
        pending = cursor.fetchone()[0]
        conn.close()
        self.logger.info("Backfill queue: %d traders with zero trades awaiting fetch", pending)

        await self._worker_loop()

    def stop(self):
        """Stop the background backfill worker."""
        self.logger.info("Stopping")
        self.is_running = False

    # ------------------------------------------------------------------ #
    #  Worker loop                                                         #
    # ------------------------------------------------------------------ #

    def _build_batch(self) -> list:
        """
        Select the next trader to backfill.

        Priority: watched traders first, then manual_watchlist discovery source,
        then highest comprehensive_elo.  Only considers traders with zero trades
        and no prior backfill attempt.
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT address FROM traders
            WHERE is_flagged = 1
            AND research_excluded = 0
            AND (SELECT COUNT(*) FROM trades WHERE trader_address = traders.address) = 0
            AND backfill_attempted IS NULL
            ORDER BY
                CASE WHEN watched = 1 THEN 0 ELSE 1 END ASC,
                CASE WHEN discovery_source = 'manual_watchlist' THEN 0 ELSE 1 END ASC,
                comprehensive_elo DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()
        return [row[0]] if row else []

    async def _worker_loop(self):
        """Main worker loop — processes one trader per cycle."""
        while self.is_running:
            try:
                batch = self._build_batch()

                if not batch:
                    self.logger.debug("No traders pending backfill, sleeping %ds", self.batch_sleep)
                    await asyncio.sleep(self.batch_sleep)
                    continue

                trader_address = batch[0]
                await self._process_single_trader(trader_address)

                if self.traders_processed % 100 == 0 and self.traders_processed > 0:
                    self._show_progress()

                await asyncio.sleep(self.batch_sleep)

            except Exception:
                self.logger.exception("Worker loop error")
                self.errors += 1
                await asyncio.sleep(60)

    # ------------------------------------------------------------------ #
    #  Per-trader processing — entirely off the event loop                #
    # ------------------------------------------------------------------ #

    def _fetch_all_trades(self, address: str) -> list:
        """
        Paginate through the Data API and return all trades for the address.

        Uses urllib.request (no external dependencies).  Raises on HTTP error.
        """
        all_trades = []
        offset = 0

        while True:
            url = (
                f"https://data-api.polymarket.com/trades"
                f"?user={address}&limit={_DATA_API_LIMIT}&offset={offset}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            if not data:
                break

            all_trades.extend(data)

            if len(data) < _DATA_API_LIMIT:
                break

            offset += _DATA_API_LIMIT

        return all_trades

    def _stamp_backfill_attempted(self, trader_address: str):
        """Write backfill_attempted = NOW for this trader."""
        try:
            conn = self.db.get_connection()
            conn.execute(
                "UPDATE traders SET backfill_attempted = datetime('now') WHERE address = ?",
                (trader_address,),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            self.logger.warning(
                "Could not stamp backfill_attempted for %s: %s",
                trader_address[:10], exc,
            )

    def _process_trader_sync(self, trader_address: str) -> dict:
        """
        Fetch and insert historical trades for one trader.

        Runs entirely in the thread pool — the event loop thread is completely
        free while this executes.  Stamps backfill_attempted after a successful
        fetch (not on exception, so timeouts can retry on restart).

        Returns a dict with keys: n_inserted, n_total, elapsed.
        """
        t0 = time.time()

        raw_trades = self._fetch_all_trades(trader_address)
        n_total = len(raw_trades)
        n_inserted = 0

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            for trade in raw_trades:
                tx_hash = trade.get("transactionHash", "")
                asset = trade.get("asset", "")
                trade_id = f"{tx_hash}-{asset[:8]}"

                raw_ts = trade.get("timestamp")
                try:
                    if isinstance(raw_ts, (int, float)):
                        ts = raw_ts / 1000 if raw_ts > 1e10 else raw_ts
                        timestamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        timestamp = str(raw_ts)
                except Exception:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                condition_id = trade.get("conditionId", "")
                title = trade.get("title", "Unknown Market")

                cursor.execute("""
                    INSERT OR IGNORE INTO trades (
                        trade_id, trader_address, market_id, market_title,
                        market_category, outcome, outcome_bet, shares, price,
                        side, timestamp, notified, completed, was_successful,
                        trade_result
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,0,NULL,'pending')
                """, (
                    trade_id,
                    trade.get("proxyWallet", trader_address),
                    condition_id,
                    title,
                    "Unknown",
                    trade.get("outcome", ""),
                    trade.get("outcome", ""),
                    float(trade.get("size", 0) or 0),
                    float(trade.get("price", 0) or 0),
                    trade.get("side", ""),
                    timestamp,
                ))
                n_inserted += cursor.rowcount

                cursor.execute("""
                    INSERT OR IGNORE INTO markets (market_id, title, category, resolved)
                    VALUES (?, ?, 'Unknown', 0)
                """, (condition_id, title))

            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
        else:
            conn.close()

        self._stamp_backfill_attempted(trader_address)

        return {
            "n_inserted": n_inserted,
            "n_total": n_total,
            "elapsed": time.time() - t0,
        }

    async def _process_single_trader(self, trader_address: str):
        """
        Async entry point — submits all work to the thread pool and awaits it.

        The event loop thread does zero I/O here.  On timeout backfill_attempted
        is NOT stamped so the trader can retry on the next service restart.
        """
        if self.failed_traders.get(trader_address, 0) >= _MAX_FAILURES:
            return

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
            self.logger.warning(
                "Timeout: %s exceeded %ds — will retry on restart",
                trader_address[:10], _TRADER_TIMEOUT,
            )
            self.errors += 1
            await self._record_failure(trader_address, loop)
            return
        except Exception:
            self.logger.exception("Failed for %s", trader_address[:10])
            self.errors += 1
            await self._record_failure(trader_address, loop)
            return

        self.traders_processed += 1
        self.logger.info(
            "Backfilled %s: %d trades inserted (fetched %d, elapsed %.1fs)",
            trader_address[:10], result["n_inserted"], result["n_total"], result["elapsed"],
        )

    # ------------------------------------------------------------------ #
    #  Failure tracking                                                    #
    # ------------------------------------------------------------------ #

    async def _record_failure(self, trader_address: str, loop):
        """
        Increment the failure counter.  On reaching _MAX_FAILURES the trader
        is skipped for the rest of this session.  backfill_attempted is NOT
        stamped so the trader retries on restart.
        """
        count = self.failed_traders.get(trader_address, 0) + 1
        self.failed_traders[trader_address] = count

        if count >= _MAX_FAILURES:
            self.logger.error(
                "[BACKFILL] Skipping %s... after %d consecutive failures — "
                "will retry on next service restart.",
                trader_address[:8], _MAX_FAILURES,
            )

    # ------------------------------------------------------------------ #
    #  Progress reporting                                                  #
    # ------------------------------------------------------------------ #

    def _show_progress(self):
        """Log worker progress statistics."""
        uptime = time.time() - self.start_time

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM traders
            WHERE is_flagged = 1
            AND research_excluded = 0
            AND (SELECT COUNT(*) FROM trades WHERE trader_address = traders.address) = 0
            AND backfill_attempted IS NULL
        """)
        remaining = cursor.fetchone()[0]
        conn.close()

        self.logger.info(
            "Progress — uptime: %.1fh | processed: %d | errors: %d | "
            "rate: %.1f/hr | remaining: %d",
            uptime / 3600,
            self.traders_processed,
            self.errors,
            self.traders_processed / (uptime / 3600) if uptime > 0 else 0,
            remaining,
        )
