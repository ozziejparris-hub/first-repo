#!/usr/bin/env python3
"""
tests/test_notify_queue_batch_drain.py

Proves the fix for the notify_new_trades() compounding-slowdown mechanism
found in the 2026-09-17 diagnosis (trading-swarm
brain/decisions/2026-09-17-oos-hash-methodology-and-cycle-compounding.md)
and fixed the same day (companion decision doc for this fix).

Root cause (established in Part 1 of that diagnosis before any code was
touched): notify_new_trades() drained an unbounded, unfiltered
`WHERE notified = 0` queue one row at a time -- one asyncio.to_thread()
call per row, each opening its own connection, doing one UPDATE, and
committing/closing. background_backfill_worker.py fed that same queue
continuously (every backfilled historical trade inserted with
notified=0), and the drain only ran when a live cycle happened to see
new_trades>0. The backlog reached 143,829 rows overnight; the per-row
drain of that backlog was the dominant cost behind cycle bodies growing
2s -> 49min -> 82min -> 125min.

Part 1 of the diagnosis also established that NOTHING in the live system
consumes the seen/unseen distinction notify_new_trades() marks:
monitor.py's own pipeline computes and discards a trader_stats_map and
sends no Telegram message (self.telegram / self.elo_bot are hardcoded
None since 2026-01-27); the only other reader,
system_observer.py::_check_high_value_trades(), has had its sole call
site commented out since 2026-05-20 (commit 65deb21) and never runs.
That is why this fix can be the root-cause combination -- (ii) insert
backfilled history as already-notified, since notifying about it was
always meaningless, plus (iii) batch the drain so the mechanism can never
compound again regardless of what future writer might add notified=0
rows -- rather than a narrower read-side filter.

Section 1 reproduces the OLD per-row drain (Database.mark_trade_notified,
unchanged, called in a loop -- exactly what monitor.py's removed loop
did) against a large notified=0 population, and shows it costs one
connection+commit per row. Section 2 proves the NEW batch drain
(Database.mark_all_unnotified_as_notified) does the identical end-state
work in a single statement. A test that could pass either way would
prove nothing; the connection-count assertions are the differential Part
1 vs O(N).

Section 3 confirms notify_new_trades() is actually wired to the new
method. Section 4 proves the insert-side fix through the REAL
background_backfill_worker code path, not a reimplementation. Section 5
proves the existing ~143k-shaped legacy backlog (simulated: a mix of
old-style notified=0 rows regardless of data_source) is drained once,
completely, by the batch method -- not left alone, not filtered out.
Section 6 confirms the one other (dead) reader of `notified`,
system_observer.py's high-value-trade query, still behaves consistently
against data written under the new scheme.
"""

import inspect
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from monitoring.database import Database
from monitoring.background_backfill_worker import BackgroundBackfillWorker
from monitoring import monitor as monitor_module

_PROD_DB = (ROOT / 'data' / 'polymarket_tracker.db').resolve()

_SCHEMA = """
CREATE TABLE traders (
    address TEXT PRIMARY KEY, total_trades INTEGER,
    comprehensive_elo REAL, roi_percentage REAL,
    backfill_attempted TIMESTAMP DEFAULT NULL
);
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY, title TEXT, category TEXT, end_date TIMESTAMP,
    resolved BOOLEAN DEFAULT 0, winning_outcome TEXT,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolution_date TIMESTAMP,
    condition_id TEXT, trade_gap_flag BOOLEAN NOT NULL DEFAULT 0,
    data_source TEXT NOT NULL DEFAULT 'live_monitoring'
);
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY, trader_address TEXT, market_id TEXT,
    market_title TEXT, market_category TEXT, outcome TEXT, shares REAL, price REAL,
    side TEXT, timestamp TIMESTAMP, notified BOOLEAN DEFAULT 0,
    completed BOOLEAN DEFAULT 0, was_successful BOOLEAN, outcome_bet TEXT,
    trade_result TEXT DEFAULT 'pending', transaction_hash TEXT DEFAULT NULL,
    is_taker BOOLEAN DEFAULT NULL,
    data_source TEXT NOT NULL DEFAULT 'polymarket_api'
);
"""


class TestResults:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def ok(self, name):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, reason):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")

    def check(self, name, cond, reason=""):
        self.ok(name) if cond else self.fail(name, reason or "condition was False")

    def summary(self):
        print(f"\n{'='*70}\n  TEST SUMMARY\n{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        pct = self.tests_passed / max(1, self.tests_run) * 100
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        for name, reason in self.failures:
            print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_notify_queue_')
    os.close(fd)
    assert Path(path).resolve() != _PROD_DB, \
        f"BUG: temp DB path is the production DB: {path}"
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return path


def _seed_unnotified_trades(path, n, prefix="t", data_source="polymarket_api"):
    conn = sqlite3.connect(path)
    conn.execute("INSERT OR IGNORE INTO traders (address, total_trades) VALUES ('0xseed', 0)")
    for i in range(n):
        conn.execute(
            "INSERT INTO trades (trade_id, trader_address, market_id, outcome, "
            "shares, price, side, timestamp, notified, data_source) "
            "VALUES (?, '0xseed', '0xm', 'Yes', 10, 0.5, 'BUY', '2026-01-01 00:00:00', 0, ?)",
            (f"{prefix}{i}", data_source),
        )
    conn.commit()
    conn.close()


class _CountingConnWrapper:
    """Wraps a Database instance to count get_connection() calls without
    touching sqlite3 itself -- isolates the count to exactly the calls the
    method under test makes."""
    def __init__(self, db: Database):
        self._db = db
        self.connection_count = 0
        self._real_get_connection = db.get_connection

        def counting_get_connection():
            self.connection_count += 1
            return self._real_get_connection()

        db.get_connection = counting_get_connection

    def __getattr__(self, name):
        return getattr(self._db, name)


def run_tests() -> bool:
    r = TestResults()
    N = 500

    # ── Section 1: OLD per-row drain -- one connection+commit per row ──────
    print("\n[SECTION 1] OLD per-row drain (Database.mark_trade_notified in a loop)")
    print("-" * 50)

    path1 = _make_db()
    _seed_unnotified_trades(path1, N)
    db1 = Database(path1)
    counted1 = _CountingConnWrapper(db1)

    unnotified = db1.get_unnotified_trades()
    r.check("T1a  seeded exactly N unnotified rows", len(unnotified) == N,
            f"Got {len(unnotified)}")

    counted1.connection_count = 0  # reset: only count the drain itself, not the fetch above

    # This is exactly what monitor.py's removed loop did:
    #   for trade in unnotified_trades:
    #       await asyncio.to_thread(self.db.mark_trade_notified, trade['trade_id'])
    for trade in unnotified:
        db1.mark_trade_notified(trade['trade_id'])

    r.check(
        "T1b  OLD drain opens exactly one connection PER ROW (the O(N) cost "
        "this fix removes)",
        counted1.connection_count == N,
        f"Got {counted1.connection_count} connections for N={N} rows",
    )
    remaining1 = db1.get_unnotified_trades()
    r.check("T1c  OLD drain does eventually mark every row notified",
            len(remaining1) == 0, f"{len(remaining1)} rows still unnotified")
    os.unlink(path1)

    # ── Section 2: NEW batch drain -- one statement regardless of N ────────
    print("\n[SECTION 2] NEW batch drain (Database.mark_all_unnotified_as_notified)")
    print("-" * 50)

    path2 = _make_db()
    _seed_unnotified_trades(path2, N)
    db2 = Database(path2)
    counted2 = _CountingConnWrapper(db2)

    unnotified2 = db2.get_unnotified_trades()
    r.check("T2a  seeded exactly N unnotified rows (fresh fixture)",
            len(unnotified2) == N, f"Got {len(unnotified2)}")

    counted2.connection_count = 0  # reset: only count the drain itself, not the fetch above

    rowcount = db2.mark_all_unnotified_as_notified()

    r.check(
        "T2b  NEW drain opens exactly ONE connection regardless of N -- "
        "proves the fix, not just a coincidence of small N",
        counted2.connection_count == 1,
        f"Got {counted2.connection_count} connections for N={N} rows",
    )
    r.check("T2c  NEW drain reports rowcount == N",
            rowcount == N, f"Got rowcount={rowcount}")
    remaining2 = db2.get_unnotified_trades()
    r.check("T2d  NEW drain marks every row notified, same end state as OLD",
            len(remaining2) == 0, f"{len(remaining2)} rows still unnotified")
    os.unlink(path2)

    # ── Section 3: notify_new_trades() is wired to the new method ──────────
    print("\n[SECTION 3] notify_new_trades() calls the batch method, not the old loop")
    print("-" * 50)

    src = inspect.getsource(monitor_module.PolymarketMonitor.notify_new_trades)
    r.check(
        "T3a  notify_new_trades() calls mark_all_unnotified_as_notified",
        "mark_all_unnotified_as_notified" in src,
        "batch method not referenced in notify_new_trades() source",
    )
    r.check(
        "T3b  notify_new_trades() no longer calls the per-row mark_trade_notified",
        "self.db.mark_trade_notified" not in src,
        "old per-row call is still present in notify_new_trades()",
    )
    r.check(
        "T3c  notify_new_trades() still computes Processing/Bundled output "
        "(the fix changed only queue entry + drain, not what a notification "
        "does)",
        "Processing" in src and "Bundled into" in src and "trader_stats_map" in src,
        "notify_new_trades()'s existing bundling/stats behaviour was altered",
    )
    os.unlink  # no fixture to clean up in this section

    # ── Section 4: insert-side fix, through the REAL worker code path ──────
    print("\n[SECTION 4] background_backfill_worker inserts notified=1 (real code path)")
    print("-" * 50)

    path4 = _make_db()
    conn4 = sqlite3.connect(path4)
    conn4.execute("INSERT OR IGNORE INTO traders (address, total_trades) VALUES ('0xbf1', 0)")
    conn4.commit()
    conn4.close()

    db4 = Database(path4)
    worker = BackgroundBackfillWorker(db4, logger=__import__('logging').getLogger('t4'))
    worker._fetch_all_trades = lambda addr: [{
        'transactionHash': 'txBF1', 'asset': 'ASSETBF1', 'timestamp': 1735689600,
        'conditionId': '0xmBF1', 'title': 'seeded', 'outcome': 'Yes',
        'size': 10, 'price': 0.4, 'side': 'BUY', 'proxyWallet': None,
    }]
    worker._process_trader_sync('0xbf1')

    conn4b = sqlite3.connect(path4)
    conn4b.row_factory = sqlite3.Row
    row = conn4b.execute("SELECT * FROM trades WHERE trade_id = 'txBF1-ASSETBF1'").fetchone()
    conn4b.close()

    r.check("T4a  backfilled row was inserted", row is not None, "row missing")
    r.check(
        "T4b  backfilled row has notified=1 (was hardcoded 0 before this "
        "fix) -- it never enters the unnotified queue at all now",
        row is not None and row['notified'] == 1,
        f"notified={row and row['notified']!r}",
    )
    r.check("T4c  data_source is still 'background_backfill' (unrelated column, untouched)",
            row is not None and row['data_source'] == 'background_backfill',
            f"data_source={row and row['data_source']!r}")
    still_unnotified4 = Database(path4).get_unnotified_trades()
    r.check(
        "T4d  the backfilled row does not appear in get_unnotified_trades()",
        all(t['trade_id'] != 'txBF1-ASSETBF1' for t in still_unnotified4),
        f"unexpectedly present: {still_unnotified4}",
    )
    os.unlink(path4)

    # ── Section 5: the existing ~143k-shaped legacy backlog is drained once ─
    print("\n[SECTION 5] A pre-existing mixed-source backlog is drained ONCE, completely")
    print("-" * 50)

    path5 = _make_db()
    # Simulate the accumulated state as of this fix: a mix of old-style
    # notified=0 rows from both sources (pre-fix backfill rows plus a
    # handful of genuinely new live rows) -- exactly the shape of the real
    # ~143,829-row backlog this diagnosis found.
    _seed_unnotified_trades(path5, 300, prefix="legacy_bf_", data_source="background_backfill")
    _seed_unnotified_trades(path5, 5, prefix="live_", data_source="polymarket_api")
    db5 = Database(path5)

    pre = db5.get_unnotified_trades()
    r.check("T5a  fixture has the full mixed pre-fix backlog (305 rows)",
            len(pre) == 305, f"Got {len(pre)}")

    rowcount5 = db5.mark_all_unnotified_as_notified()
    r.check(
        "T5b  the batch drain is applied uniformly to notified=0 rows "
        "regardless of data_source -- the accumulated backlog is drained "
        "ONCE, not left alone and not filtered out permanently",
        rowcount5 == 305,
        f"Got rowcount={rowcount5}",
    )
    post = db5.get_unnotified_trades()
    r.check("T5c  no rows remain unnotified after the one-time drain",
            len(post) == 0, f"{len(post)} rows still unnotified")
    os.unlink(path5)

    # ── Section 6: the one other (dead) reader of `notified` stays consistent ─
    print("\n[SECTION 6] system_observer.py's dead high-value-trade query stays consistent")
    print("-" * 50)

    path6 = _make_db()
    conn6 = sqlite3.connect(path6)
    conn6.execute(
        "INSERT INTO traders (address, total_trades, comprehensive_elo, roi_percentage) "
        "VALUES ('0xhv1', 5, 1600, 10.0)"
    )
    # A backfilled trade, post-fix (notified=1), large enough to have matched
    # the high-value-trade predicate if it were live and recent.
    conn6.execute(
        "INSERT INTO trades (trade_id, trader_address, market_id, outcome, shares, "
        "price, side, timestamp, notified, data_source) VALUES "
        "('hv1', '0xhv1', '0xmhv1', 'Yes', 5000, 0.9, 'BUY', datetime('now'), 1, "
        "'background_backfill')"
    )
    conn6.commit()
    conn6.close()

    # Exact predicate from system_observer.py::_check_high_value_trades()
    # (the only other reader of `notified` in the codebase; its sole call
    # site has been commented out since 2026-05-20, commit 65deb21 -- dead
    # code, not revived by this fix).
    conn6b = sqlite3.connect(path6)
    conn6b.row_factory = sqlite3.Row
    candidates = conn6b.execute("""
        SELECT tr.trade_id FROM trades tr
        JOIN traders t ON tr.trader_address = t.address
        WHERE t.comprehensive_elo >= 1550
          AND tr.timestamp >= datetime('now', '-30 minutes')
          AND tr.timestamp <= datetime('now')
          AND (tr.shares * tr.price) >= 1000
          AND (tr.notified = 0 OR tr.notified IS NULL)
    """).fetchall()
    conn6b.close()

    r.check(
        "T6a  a backfilled trade (notified=1 under the fix) correctly does "
        "NOT match system_observer's high-value-trade candidate predicate "
        "-- consistent behaviour if that dead code were ever revived, not "
        "a regression introduced by this fix",
        len(candidates) == 0,
        f"Unexpectedly matched: {[dict(c) for c in candidates]}",
    )
    os.unlink(path6)

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
