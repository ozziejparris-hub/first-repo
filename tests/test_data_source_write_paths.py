#!/usr/bin/env python3
"""
tests/test_data_source_write_paths.py

Regression tests for the markets and traders data_source write paths.

Exercises the ACTUAL patched code from each write path against a temporary
SQLite DB that mirrors the full production schema. Never touches the
production database — a guard assertion is checked at every temp-DB creation.

10 test cases:
  PROVENANCE-ON-INSERT (new rows):
    1  background_backfill_worker  → 'background_backfill'
    2  backfill_missing_markets    → 'background_backfill'
    3  refresh_markets (new row)   → 'api_refresh'
    4  database.update_market      → 'live_monitoring' (DEFAULT; not in column list)
    5  4 traders write paths       → correct per-path value
  ORIGIN-PRESERVATION (existing rows — the critical ones):
    6  refresh_markets on existing 'historical_backfill' → data_source PRESERVED
    7  refresh_markets on resolved market → resolved + winning_outcome PRESERVED
       (regression test for the pre-existing INSERT OR REPLACE resolution-wipe bug)
    8  update_market DO UPDATE on existing market → data_source PRESERVED
    9  backfill stub then live monitor update → data_source STAYS 'background_backfill'
  HARNESS INTEGRATION:
   10  data_source harness checks pass on the test DB (0 NULLs, 0 out-of-set)
"""

import os
import sys
import sqlite3
import logging
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
# Order matters: monitoring/ must come before scripts/ so 'from database import Database'
# resolves to monitoring/database.py (used internally by refresh_markets.py).
sys.path.insert(0, str(ROOT / 'monitoring'))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

_PROD_DB = (ROOT / 'data' / 'polymarket_tracker.db').resolve()


# ─────────────────────────────────────────────────────────────────────────────
# TestResults — follows existing repo pattern (tests/test_behavioral_integration.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestResults:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def ok(self, name: str):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")

    def summary(self) -> bool:
        print(f"\n{'='*70}")
        print(f"  TEST SUMMARY")
        print(f"{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        pct = self.tests_passed / max(1, self.tests_run) * 100
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        if self.failures:
            print(f"\n  FAILURES:")
            for name, reason in self.failures:
                print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test DB factory — exact production schema, never touches production
# ─────────────────────────────────────────────────────────────────────────────
# These CREATE TABLE statements mirror the live production schema exactly
# (derived from: sqlite3 data/polymarket_tracker.db ".schema traders|markets|trades|positions").

_CREATE_TRADERS = """
CREATE TABLE IF NOT EXISTS traders (
    address TEXT PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    successful_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    total_volume REAL DEFAULT 0.0,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_flagged BOOLEAN DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    avg_roi REAL DEFAULT 0,
    total_invested REAL DEFAULT 0,
    closed_positions INTEGER DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    comprehensive_elo REAL DEFAULT 1500,
    base_category_elo REAL DEFAULT 1500,
    elo_last_updated TIMESTAMP DEFAULT NULL,
    behavioral_modifier REAL DEFAULT 1.0,
    advanced_modifier REAL DEFAULT 1.0,
    pnl_modifier REAL DEFAULT 1.0,
    kelly_alignment_score REAL,
    patience_score REAL,
    timing_score REAL,
    weighted_win_rate REAL,
    roi_percentage REAL,
    resolved_trades_count INTEGER,
    pnl_last_updated TIMESTAMP,
    pnl_update_priority INTEGER DEFAULT 0,
    username TEXT,
    discovery_source TEXT DEFAULT 'live_feed',
    watched INTEGER DEFAULT 0,
    wash_trade_suspect BOOLEAN NOT NULL DEFAULT 0,
    bot_suspect BOOLEAN NOT NULL DEFAULT 0,
    specialist_category TEXT,
    specialisation_ratio REAL,
    bot_type TEXT,
    research_excluded BOOLEAN NOT NULL DEFAULT 0,
    elo_period1_cutoff REAL DEFAULT NULL,
    backfill_attempted TIMESTAMP DEFAULT NULL,
    geo_elo REAL DEFAULT NULL,
    geo_resolved_trades_count INTEGER DEFAULT 0,
    geo_directionality_score REAL DEFAULT NULL,
    geo_accuracy_pool BOOLEAN DEFAULT 0,
    wallet_creation_date TEXT DEFAULT NULL,
    true_wallet_age_days INTEGER DEFAULT NULL,
    funding_wallet TEXT DEFAULT NULL,
    is_contract_wallet BOOLEAN DEFAULT NULL,
    pnl_skip BOOLEAN DEFAULT 0,
    geo_elo_active REAL,
    data_source TEXT NOT NULL DEFAULT 'live_feed'
)
"""

_CREATE_MARKETS = """
CREATE TABLE IF NOT EXISTS markets (
    market_id TEXT PRIMARY KEY,
    title TEXT,
    category TEXT,
    end_date TIMESTAMP,
    resolved BOOLEAN DEFAULT 0,
    winning_outcome TEXT,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolution_date TIMESTAMP,
    condition_id TEXT,
    api_id TEXT,
    difficulty_score REAL,
    trade_gap_flag BOOLEAN NOT NULL DEFAULT 0,
    clob_token_id_yes TEXT,
    clob_token_id_no TEXT,
    data_source TEXT NOT NULL DEFAULT 'live_monitoring'
)
"""

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    trader_address TEXT,
    market_id TEXT,
    market_title TEXT,
    market_category TEXT,
    outcome TEXT,
    shares REAL,
    price REAL,
    side TEXT,
    timestamp TIMESTAMP,
    notified BOOLEAN DEFAULT 0,
    completed BOOLEAN DEFAULT 0,
    was_successful BOOLEAN,
    outcome_bet TEXT,
    trade_result TEXT DEFAULT 'pending',
    transaction_hash TEXT DEFAULT NULL,
    is_taker BOOLEAN DEFAULT NULL,
    data_source TEXT NOT NULL DEFAULT 'polymarket_api',
    FOREIGN KEY (trader_address) REFERENCES traders(address)
)
"""

_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    trader_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_title TEXT,
    outcome TEXT NOT NULL,
    entry_shares REAL NOT NULL,
    entry_avg_price REAL NOT NULL,
    entry_total_cost REAL NOT NULL,
    entry_timestamp TIMESTAMP NOT NULL,
    entry_trade_ids TEXT,
    exit_shares REAL,
    exit_avg_price REAL,
    exit_total_received REAL,
    exit_timestamp TIMESTAMP,
    exit_trade_ids TEXT,
    realized_pnl REAL,
    roi_percent REAL,
    holding_period_hours REAL,
    status TEXT NOT NULL,
    remaining_shares REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_synthetic_close BOOLEAN DEFAULT 0,
    data_source TEXT NOT NULL DEFAULT 'position_tracker',
    FOREIGN KEY (trader_address) REFERENCES traders(address)
)
"""


def make_test_db() -> str:
    """
    Create a fresh temporary SQLite DB with the full production schema.
    Returns the file path. Caller is responsible for cleanup via os.unlink().
    Production-guard assertion is checked here and cannot be bypassed.
    """
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_ds_writepath_')
    os.close(fd)
    assert Path(path).resolve() != _PROD_DB, \
        f"BUG: make_test_db() returned the production path: {path}"
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute(_CREATE_TRADERS)
    conn.execute(_CREATE_MARKETS)
    conn.execute(_CREATE_TRADES)
    conn.execute(_CREATE_POSITIONS)
    conn.commit()
    conn.close()
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_market(db_path: str, market_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _fetch_trader(db_path: str, address: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM traders WHERE address = ?", (address,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _seed_trader(db_path: str, address: str):
    """Insert a minimal trader row so FK constraints are satisfied."""
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR IGNORE INTO traders (address, total_trades) VALUES (?, 0)", (address,))
    conn.commit()
    conn.close()


def _seed_market(db_path: str, market_id: str, resolved: int = 0,
                 winning_outcome=None, data_source: str = 'live_monitoring'):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO markets (market_id, title, category, resolved, winning_outcome, data_source) "
        "VALUES (?, 'Seeded market', 'Test', ?, ?, ?)",
        (market_id, resolved, winning_outcome, data_source)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# PROVENANCE-ON-INSERT TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_1_backfill_worker_stub_new_market(results: TestResults):
    """
    background_backfill_worker._process_trader_sync: a market first seen during
    a backfill run (stub created at monitoring/background_backfill_worker.py:327-330)
    gets data_source='background_backfill'.

    Exercises the actual patched code by monkeypatching _fetch_all_trades to
    return a synthetic trade, then calling _process_trader_sync directly.
    """
    print("\n[TEST 1] background_backfill_worker stub → data_source='background_backfill'")
    db_path = make_test_db()
    try:
        from monitoring.database import Database
        from monitoring.background_backfill_worker import BackgroundBackfillWorker

        db = Database(db_path)
        _seed_trader(db_path, '0xtest001')
        worker = BackgroundBackfillWorker(db, logger=logging.getLogger('test.t1'))

        worker._fetch_all_trades = lambda addr: [{
            'transactionHash': 'tx_t1_abc',
            'asset':           'TOKEN_A',
            'timestamp':       1700000000,
            'conditionId':     '0xmkt_t1_001',
            'title':           'Backfill worker test market',
            'outcome':         'Yes',
            'size':            10,
            'price':           0.5,
            'side':            'BUY',
            'proxyWallet':     '0xtest001',
        }]

        worker._process_trader_sync('0xtest001')

        market = _fetch_market(db_path, '0xmkt_t1_001')
        if market is None:
            results.fail("T1 backfill_worker stub", "market row not inserted at all")
        elif market['data_source'] != 'background_backfill':
            results.fail("T1 backfill_worker stub",
                         f"expected 'background_backfill', got {market['data_source']!r}")
        else:
            results.ok("T1 backfill_worker stub → data_source='background_backfill'")
    finally:
        os.unlink(db_path)


def test_2_backfill_missing_markets_new_market(results: TestResults):
    """
    backfill_missing_markets.insert_market: a brand-new market row gets
    data_source='background_backfill' (scripts/backfill_missing_markets.py:134-151).
    """
    print("\n[TEST 2] backfill_missing_markets.insert_market → data_source='background_backfill'")
    db_path = make_test_db()
    try:
        import backfill_missing_markets as bmm

        row = {
            'market_id':       '0xmkt_t2_001',
            'title':           'BMM test market',
            'category':        'Test',
            'end_date':        '2026-12-31',
            'resolved':        0,
            'winning_outcome': None,
            'condition_id':    '0xmkt_t2_001',
            'resolution_date': None,
        }
        conn = sqlite3.connect(db_path)
        inserted = bmm.insert_market(conn, row, dry_run=False)
        conn.close()

        market = _fetch_market(db_path, '0xmkt_t2_001')
        if market is None:
            results.fail("T2 backfill_missing_markets new", "market row not inserted")
        elif market['data_source'] != 'background_backfill':
            results.fail("T2 backfill_missing_markets new",
                         f"expected 'background_backfill', got {market['data_source']!r}")
        else:
            results.ok("T2 backfill_missing_markets → data_source='background_backfill'")
    finally:
        os.unlink(db_path)


def test_3_refresh_markets_new_market(results: TestResults):
    """
    refresh_markets.MarketRefresher.store_markets: a brand-new market (first time
    seen by the refresh) gets data_source='api_refresh'
    (scripts/refresh_markets.py:271-286, the redesigned INSERT ... ON CONFLICT).
    """
    print("\n[TEST 3] refresh_markets (brand-new row) → data_source='api_refresh'")
    db_path = make_test_db()
    try:
        import refresh_markets as rm

        refresher = rm.MarketRefresher(db_path=db_path)
        refresher.store_markets([{
            'id':          '9001',
            'conditionId': '0xmkt_t3_001',
            'question':    'Refresh test market',
            'category':    'Test',
            'endDate':     '2026-12-31',
        }], test_mode=False)

        market = _fetch_market(db_path, '0xmkt_t3_001')
        if market is None:
            results.fail("T3 refresh_markets new", "market row not inserted")
        elif market['data_source'] != 'api_refresh':
            results.fail("T3 refresh_markets new",
                         f"expected 'api_refresh', got {market['data_source']!r}")
        else:
            results.ok("T3 refresh_markets (new row) → data_source='api_refresh'")
    finally:
        os.unlink(db_path)


def test_4_database_update_market_new_row(results: TestResults):
    """
    database.update_market (live-monitor main path): a brand-new market gets
    data_source='live_monitoring' via the column DEFAULT.
    The column is absent from the INSERT column list — this verifies the
    DEFAULT fires correctly and the path needs no explicit patch.
    """
    print("\n[TEST 4] database.update_market (new row) → data_source='live_monitoring' (DEFAULT)")
    db_path = make_test_db()
    try:
        from monitoring.database import Database

        db = Database(db_path)
        db.update_market(
            market_id='0xmkt_t4_001',
            title='Live monitor test',
            category='Test',
            end_date=datetime(2026, 12, 31),
            resolved=False,
        )

        market = _fetch_market(db_path, '0xmkt_t4_001')
        if market is None:
            results.fail("T4 update_market new row", "market row not inserted")
        elif market['data_source'] != 'live_monitoring':
            results.fail("T4 update_market new row",
                         f"expected 'live_monitoring', got {market['data_source']!r}")
        else:
            results.ok("T4 update_market new row → data_source='live_monitoring' (DEFAULT)")
    finally:
        os.unlink(db_path)


def test_5_traders_four_paths(results: TestResults):
    """
    All 4 traders write paths set data_source correctly:
      5a  database.add_or_update_trader      → 'live_feed' (DEFAULT; no column arg)
      5b  discover_market_participants SQL   → 'market_scan'
      5c  discover_leaderboard_traders SQL  → 'leaderboard'
      5d  add_watched_trader.cmd_add        → 'manual_watchlist'

    5b and 5c use the exact INSERT SQL from those scripts (the SQL IS the patch;
    calling the full method would require mocking multi-step API pagination).
    5d calls cmd_add directly with _fetch_profile monkeypatched to bypass HTTP.
    """
    print("\n[TEST 5] 4 traders write paths → correct data_source per path")
    db_path = make_test_db()
    try:
        from monitoring.database import Database
        import add_watched_trader as awt

        db = Database(db_path)

        # 5a: add_or_update_trader — no data_source arg → DEFAULT 'live_feed'
        db.add_or_update_trader('0xtrader_5a', 5, 3, 0.6, 1000.0, False)
        t = _fetch_trader(db_path, '0xtrader_5a')
        if t is None:
            results.fail("T5a add_or_update_trader", "row not inserted")
        elif t['data_source'] != 'live_feed':
            results.fail("T5a add_or_update_trader",
                         f"expected 'live_feed', got {t['data_source']!r}")
        else:
            results.ok("T5a add_or_update_trader → data_source='live_feed' (DEFAULT)")

        # 5b: discover_market_participants exact INSERT SQL → 'market_scan'
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            INSERT INTO traders (
                address, total_trades, successful_trades, win_rate,
                total_volume, is_flagged, discovery_source, data_source, username, last_updated
            ) VALUES (?, ?, 0, 0.0, ?, ?, 'market_scan', 'market_scan', ?, ?)
            ON CONFLICT(address) DO NOTHING
        """, ('0xtrader_5b', 10, 500.0, False, None, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        t = _fetch_trader(db_path, '0xtrader_5b')
        if t is None:
            results.fail("T5b discover_market_participants SQL", "row not inserted")
        elif t['data_source'] != 'market_scan':
            results.fail("T5b discover_market_participants SQL",
                         f"expected 'market_scan', got {t['data_source']!r}")
        else:
            results.ok("T5b discover_market_participants SQL → data_source='market_scan'")

        # 5c: discover_leaderboard_traders exact INSERT SQL → 'leaderboard'
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            INSERT INTO traders (
                address, total_trades, successful_trades, win_rate,
                total_volume, is_flagged, discovery_source, data_source, username, last_updated
            ) VALUES (?, ?, 0, 0.0, ?, ?, 'leaderboard', 'leaderboard', ?, ?)
            ON CONFLICT(address) DO NOTHING
        """, ('0xtrader_5c', 20, 2000.0, True, 'TopTrader', datetime.now().isoformat()))
        conn.commit()
        conn.close()
        t = _fetch_trader(db_path, '0xtrader_5c')
        if t is None:
            results.fail("T5c discover_leaderboard_traders SQL", "row not inserted")
        elif t['data_source'] != 'leaderboard':
            results.fail("T5c discover_leaderboard_traders SQL",
                         f"expected 'leaderboard', got {t['data_source']!r}")
        else:
            results.ok("T5c discover_leaderboard_traders SQL → data_source='leaderboard'")

        # 5d: add_watched_trader.cmd_add → 'manual_watchlist' (monkeypatch HTTP)
        orig_fetch = awt._fetch_profile
        awt._fetch_profile = lambda addr: {}
        try:
            awt.cmd_add(db_path, '0xtrader_5d', username='WatchMe', dry_run=False)
        finally:
            awt._fetch_profile = orig_fetch
        t = _fetch_trader(db_path, '0xtrader_5d')
        if t is None:
            results.fail("T5d add_watched_trader cmd_add", "row not inserted")
        elif t['data_source'] != 'manual_watchlist':
            results.fail("T5d add_watched_trader cmd_add",
                         f"expected 'manual_watchlist', got {t['data_source']!r}")
        else:
            results.ok("T5d add_watched_trader.cmd_add → data_source='manual_watchlist'")
    finally:
        os.unlink(db_path)


# ─────────────────────────────────────────────────────────────────────────────
# ORIGIN-PRESERVATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

def test_6_refresh_preserves_historical_backfill_origin(results: TestResults):
    """
    refresh_markets on an existing 'historical_backfill' market must NOT
    overwrite data_source to 'api_refresh'. Origin is preserved by the
    DO UPDATE's intentional omission of data_source.
    """
    print("\n[TEST 6] refresh on existing historical_backfill → data_source PRESERVED")
    db_path = make_test_db()
    try:
        import refresh_markets as rm

        _seed_market(db_path, '0xmkt_t6_001', data_source='historical_backfill')

        rm.MarketRefresher(db_path=db_path).store_markets([{
            'id':          '42',
            'conditionId': '0xmkt_t6_001',
            'question':    'Historical market updated title',
            'category':    'Politics',
            'endDate':     '2026-06-01',
        }], test_mode=False)

        market = _fetch_market(db_path, '0xmkt_t6_001')
        if market is None:
            results.fail("T6 refresh preserves origin", "market row missing")
        elif market['data_source'] != 'historical_backfill':
            results.fail("T6 refresh preserves origin",
                         f"ORIGIN WIPED: expected 'historical_backfill', got {market['data_source']!r}")
        else:
            results.ok("T6 refresh preserves historical_backfill origin (not clobbered by api_refresh)")
    finally:
        os.unlink(db_path)


def test_7_refresh_preserves_resolution_state(results: TestResults):
    """
    refresh_markets on an existing RESOLVED market must NOT wipe resolved=1
    or winning_outcome. This is the regression test for the pre-existing
    INSERT OR REPLACE bug that zeroed those fields on every refresh run.

    The new INSERT ... ON CONFLICT DO UPDATE intentionally omits resolved and
    winning_outcome from the DO UPDATE clause.
    """
    print("\n[TEST 7] refresh on resolved market → resolved + winning_outcome PRESERVED (bug-fix lock)")
    db_path = make_test_db()
    try:
        import refresh_markets as rm

        _seed_market(db_path, '0xmkt_t7_001',
                     resolved=1, winning_outcome='Yes',
                     data_source='historical_backfill')

        rm.MarketRefresher(db_path=db_path).store_markets([{
            'id':          '99',
            'conditionId': '0xmkt_t7_001',
            'question':    'Resolved market refreshed',
            'category':    'Crypto',
            'endDate':     '2025-12-01',
        }], test_mode=False)

        market = _fetch_market(db_path, '0xmkt_t7_001')
        if market is None:
            results.fail("T7 refresh preserves resolution", "market row missing")
            return

        failures = []
        if market['resolved'] != 1:
            failures.append(f"resolved WIPED to {market['resolved']!r} (expected 1)")
        if market['winning_outcome'] != 'Yes':
            failures.append(f"winning_outcome WIPED to {market['winning_outcome']!r} (expected 'Yes')")
        if market['data_source'] != 'historical_backfill':
            failures.append(f"data_source WIPED to {market['data_source']!r} (expected 'historical_backfill')")

        if failures:
            results.fail("T7 refresh preserves resolution", "; ".join(failures))
        else:
            results.ok("T7 refresh preserves resolved=1 + winning_outcome='Yes' + data_source (all 3 preserved)")
    finally:
        os.unlink(db_path)


def test_8_update_market_do_update_preserves_data_source(results: TestResults):
    """
    database.update_market (live-monitor path) calls DO UPDATE on an existing
    market — data_source must be untouched because it is absent from the
    DO UPDATE SET clause (monitoring/database.py:434-443).
    """
    print("\n[TEST 8] update_market DO UPDATE → data_source PRESERVED (first-writer-wins)")
    db_path = make_test_db()
    try:
        from monitoring.database import Database

        _seed_market(db_path, '0xmkt_t8_001', data_source='background_backfill')

        db = Database(db_path)
        db.update_market(
            market_id='0xmkt_t8_001',
            title='Updated by live monitor',
            category='Test',
            resolved=False,
        )

        market = _fetch_market(db_path, '0xmkt_t8_001')
        if market is None:
            results.fail("T8 update_market DO UPDATE", "market row missing")
        elif market['data_source'] != 'background_backfill':
            results.fail("T8 update_market DO UPDATE",
                         f"data_source CLOBBERED: expected 'background_backfill', got {market['data_source']!r}")
        else:
            results.ok("T8 update_market DO UPDATE preserves data_source='background_backfill'")
    finally:
        os.unlink(db_path)


def test_9_first_writer_wins_market(results: TestResults):
    """
    End-to-end first-writer-wins sequence for a market:
      Step 1 — background_backfill_worker creates the stub
               (data_source='background_backfill')
      Step 2 — live monitor calls update_market (DO UPDATE path)
    After Step 2, data_source must STILL be 'background_backfill'.
    """
    print("\n[TEST 9] First-writer-wins: backfill stub → live monitor update → 'background_backfill' survives")
    db_path = make_test_db()
    try:
        from monitoring.database import Database
        from monitoring.background_backfill_worker import BackgroundBackfillWorker

        db = Database(db_path)
        _seed_trader(db_path, '0xtest009')
        worker = BackgroundBackfillWorker(db, logger=logging.getLogger('test.t9'))
        worker._fetch_all_trades = lambda addr: [{
            'transactionHash': 'tx_t9_xyz',
            'asset':           'TOKEN_B',
            'timestamp':       1700000001,
            'conditionId':     '0xmkt_t9_001',
            'title':           'First-writer-wins test market',
            'outcome':         'No',
            'size':            5,
            'price':           0.4,
            'side':            'BUY',
            'proxyWallet':     '0xtest009',
        }]
        worker._process_trader_sync('0xtest009')

        # Verify Step 1
        m1 = _fetch_market(db_path, '0xmkt_t9_001')
        if m1 is None or m1['data_source'] != 'background_backfill':
            results.fail("T9 first-writer-wins",
                         f"Step 1 failed: market={m1}")
            return

        # Step 2: live monitor touches the same market
        db.update_market(
            market_id='0xmkt_t9_001',
            title='First-writer-wins test market (monitor updated)',
            category='Test',
            resolved=False,
        )

        m2 = _fetch_market(db_path, '0xmkt_t9_001')
        if m2['data_source'] != 'background_backfill':
            results.fail("T9 first-writer-wins",
                         f"live monitor CLOBBERED origin: expected 'background_backfill', got {m2['data_source']!r}")
        else:
            results.ok("T9 first-writer-wins: backfill origin survives live monitor DO UPDATE")
    finally:
        os.unlink(db_path)


# ─────────────────────────────────────────────────────────────────────────────
# HARNESS INTEGRATION TEST
# ─────────────────────────────────────────────────────────────────────────────

def test_10_harness_checks_on_test_db(results: TestResults):
    """
    After exercising all write paths on a single test DB, the two data_source
    harness checks must return count=0:
      - check_data_source_nulls   → 0 NULL data_source values
      - check_data_source_invalid → 0 values outside the canonical frozenset

    Any non-zero count means a write path is setting an illegal or missing
    data_source value.
    """
    print("\n[TEST 10] Harness checks on populated test DB → 0 NULLs + 0 out-of-set")
    db_path = make_test_db()
    try:
        import refresh_markets as rm
        import backfill_missing_markets as bmm
        import add_watched_trader as awt
        import audit_invariants as ai
        from monitoring.database import Database
        from monitoring.background_backfill_worker import BackgroundBackfillWorker

        db = Database(db_path)

        # — markets: all 4 paths —
        _seed_trader(db_path, '0xtest010')
        worker = BackgroundBackfillWorker(db, logger=logging.getLogger('test.t10'))
        worker._fetch_all_trades = lambda addr: [{
            'transactionHash': 'tx_t10_aaa',
            'asset':           'TOKEN_C',
            'timestamp':       1700000002,
            'conditionId':     '0xmkt_t10_001',
            'title':           'Harness test market 1',
            'outcome':         'Yes',
            'size':            3,
            'price':           0.6,
            'side':            'BUY',
            'proxyWallet':     '0xtest010',
        }]
        worker._process_trader_sync('0xtest010')

        conn = sqlite3.connect(db_path)
        bmm.insert_market(conn, {
            'market_id': '0xmkt_t10_002', 'title': 'BMM harness', 'category': 'Test',
            'end_date': '2026-12-31', 'resolved': 0, 'winning_outcome': None,
            'condition_id': '0xmkt_t10_002', 'resolution_date': None,
        }, dry_run=False)
        conn.close()

        rm.MarketRefresher(db_path=db_path).store_markets([{
            'id': '1001', 'conditionId': '0xmkt_t10_003',
            'question': 'RM harness', 'category': 'Test', 'endDate': '2026-12-31',
        }], test_mode=False)

        db.update_market('0xmkt_t10_004', 'Live monitor harness', 'Test')

        # — traders: all 4 paths —
        db.add_or_update_trader('0xtrader_t10_live', 1, 0, 0.0, 0.0, False)

        conn = sqlite3.connect(db_path)
        conn.execute("""
            INSERT INTO traders (
                address, total_trades, successful_trades, win_rate,
                total_volume, is_flagged, discovery_source, data_source, username, last_updated
            ) VALUES (?, 5, 0, 0.0, 200.0, 0, 'market_scan', 'market_scan', NULL, ?)
            ON CONFLICT(address) DO NOTHING
        """, ('0xtrader_t10_scan', datetime.now().isoformat()))
        conn.execute("""
            INSERT INTO traders (
                address, total_trades, successful_trades, win_rate,
                total_volume, is_flagged, discovery_source, data_source, username, last_updated
            ) VALUES (?, 15, 0, 0.0, 1500.0, 1, 'leaderboard', 'leaderboard', 'LB10', ?)
            ON CONFLICT(address) DO NOTHING
        """, ('0xtrader_t10_lb', datetime.now().isoformat()))
        conn.commit()
        conn.close()

        orig_fetch = awt._fetch_profile
        awt._fetch_profile = lambda addr: {}
        try:
            awt.cmd_add(db_path, '0xtrader_t10_watch', username=None, dry_run=False)
        finally:
            awt._fetch_profile = orig_fetch

        # — run harness checks —
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _, _, _, null_count, null_detail   = ai.check_data_source_nulls(cur, verbose=True)
        _, _, _, invalid_count, inv_detail = ai.check_data_source_invalid(cur, verbose=True)
        conn.close()

        if null_count > 0:
            results.fail("T10a harness null check",
                         f"{null_count} NULL data_source values — detail: {null_detail}")
        else:
            results.ok("T10a harness check_data_source_nulls → 0 NULLs across all 4 tables")

        if invalid_count > 0:
            results.fail("T10b harness invalid check",
                         f"{invalid_count} out-of-set data_source values — detail: {inv_detail}")
        else:
            results.ok("T10b harness check_data_source_invalid → 0 out-of-set values")
    finally:
        os.unlink(db_path)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def main() -> bool:
    print("\n" + "="*70)
    print("  DATA SOURCE WRITE-PATH TESTS  (10 cases)")
    print("="*70)
    print(f"\n  Production DB guard : {_PROD_DB}")
    print(f"  Temp DBs            : {tempfile.gettempdir()}/test_ds_writepath_*.db")
    print(f"  Production touched  : NEVER\n")

    results = TestResults()

    # PROVENANCE-ON-INSERT
    test_1_backfill_worker_stub_new_market(results)
    test_2_backfill_missing_markets_new_market(results)
    test_3_refresh_markets_new_market(results)
    test_4_database_update_market_new_row(results)
    test_5_traders_four_paths(results)

    # ORIGIN-PRESERVATION
    test_6_refresh_preserves_historical_backfill_origin(results)
    test_7_refresh_preserves_resolution_state(results)
    test_8_update_market_do_update_preserves_data_source(results)
    test_9_first_writer_wins_market(results)

    # HARNESS INTEGRATION
    test_10_harness_checks_on_test_db(results)

    success = results.summary()
    if success:
        print("All assertions passed.\n")
    else:
        print("FAILURES detected — do not commit until all pass.\n")
    return success


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
