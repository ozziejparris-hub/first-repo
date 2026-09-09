#!/usr/bin/env python3
"""
tests/test_backfill_ingest_evaluation.py

Locks the fix that stops background_backfill_worker.py hard-coding
trade_result='pending' on every backfilled trade
(2026-09-09-background-backfill-ingest-evaluation.md).

The worker now, at insert time, does ONE batch lookup of
markets.resolved / winning_outcome for the trader's markets and — for a
trade whose market is already resolved with a usable winning_outcome —
writes the real 'won'/'lost' via the canonical
monitoring.trade_evaluator.TradeEvaluator.evaluate_trade(). Everything else
still writes 'pending' for the daily evaluator
(scripts/backfill_trade_results_geo.py) to pick up.

Three things, all required:

  1. CORRECTNESS      — for trades whose correct result is known, the new
                        insert path produces the same answer as calling
                        TradeEvaluator.evaluate_trade() directly.
  2. NON-TAUTOLOGY    — the new path still writes 'pending' for: unresolved
                        market, absent market, and NULL / '' / 'unknown'
                        winning_outcome. A fix that evaluated everything
                        would be wrong.
  3. NO EXISTING ROW  — INSERT OR IGNORE: a trade_id collision leaves the
                        stored row (and its trade_result) untouched, even
                        when the market would now evaluate it differently.

Exercises the ACTUAL worker code via a monkeypatched _fetch_all_trades
against a throwaway temp DB built by Database(tmp_path). Never touches the
production database — a guard assertion is checked at temp-DB creation.

Run via run_tests.py, not bare pytest.
"""

import os
import sys
import sqlite3
import tempfile
import logging
from pathlib import Path

ROOT = Path(__file__).parent.parent
# monitoring/ ahead of scripts/ (repo convention: 'from database import ...')
sys.path.insert(0, str(ROOT / 'monitoring'))
sys.path.insert(0, str(ROOT))

from monitoring.database import Database
from monitoring.trade_evaluator import TradeEvaluator
from monitoring.background_backfill_worker import (
    BackgroundBackfillWorker,
    _resolve_ingest_trade_result,
)

_PROD_DB = (ROOT / 'data' / 'polymarket_tracker.db').resolve()
_EVAL = TradeEvaluator(None, None)
logging.disable(logging.CRITICAL)

# Full production column set for the columns the worker's insert path touches —
# Database().init_database() only builds a minimal schema; the rest is added by
# migrations scattered across the codebase. Mirrors `.schema` on production.
_SCHEMA = """
CREATE TABLE traders (
    address TEXT PRIMARY KEY, total_trades INTEGER,
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


# ── temp DB helpers ──────────────────────────────────────────────────────────

def _make_db() -> str:
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_bf_ingest_')
    os.close(fd)
    assert Path(path).resolve() != _PROD_DB, \
        f"BUG: temp DB path is the production DB: {path}"
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return path


def _seed_trader(path, address):
    conn = sqlite3.connect(path)
    conn.execute("INSERT OR IGNORE INTO traders (address, total_trades) VALUES (?, 0)", (address,))
    conn.commit()
    conn.close()


def _seed_market(path, market_id, resolved, winning_outcome):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO markets (market_id, title, category, resolved, winning_outcome, data_source) "
        "VALUES (?, 'seeded', 'Geopolitics', ?, ?, 'test')",
        (market_id, resolved, winning_outcome),
    )
    conn.commit()
    conn.close()


def _seed_trade(path, trade_id, trader, market_id, trade_result):
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO trades (trade_id, trader_address, market_id, outcome, outcome_bet, "
        "side, timestamp, trade_result, data_source) "
        "VALUES (?, ?, ?, 'Yes', 'Yes', 'BUY', '2026-01-01 00:00:00', ?, 'polymarket_api')",
        (trade_id, trader, market_id, trade_result),
    )
    conn.commit()
    conn.close()


def _fetch_trade(path, trade_id):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _api_trade(tx, asset, condition_id, outcome, side):
    return {
        'transactionHash': tx, 'asset': asset, 'timestamp': 1735689600,
        'conditionId': condition_id, 'title': 'seeded', 'outcome': outcome,
        'size': 10, 'price': 0.4, 'side': side, 'proxyWallet': None,
    }


def _run_worker(path, address, api_trades):
    worker = BackgroundBackfillWorker(Database(path), logger=logging.getLogger('t'))
    worker._fetch_all_trades = lambda addr: api_trades
    worker._process_trader_sync(address)


# ── 1. CORRECTNESS ───────────────────────────────────────────────────────────

def _correctness(r):
    print("\n[1] CORRECTNESS — new insert path == TradeEvaluator.evaluate_trade()")
    # (outcome_bet, side, winning_outcome, expected)
    cases = [
        ('Yes', 'BUY',  'Yes', 'won'),
        ('Yes', 'BUY',  'No',  'lost'),
        ('No',  'BUY',  'No',  'won'),
        ('Yes', 'SELL', 'No',  'won'),
        ('Yes', 'SELL', 'Yes', 'lost'),
        ('Up',  'BUY',  'Down', 'lost'),
    ]
    for i, (ob, side, wo, expected) in enumerate(cases):
        direct = _EVAL.evaluate_trade({'outcome_bet': ob, 'side': side}, wo)
        r.check(f"1.{i}a direct evaluator == expected ({ob}/{side}/{wo})",
                direct == expected, f"evaluator gave {direct!r}, expected {expected!r}")

        helper = _resolve_ingest_trade_result({'outcome': ob, 'side': side}, (1, wo))
        r.check(f"1.{i}b helper == direct evaluator ({ob}/{side}/{wo})",
                helper == direct, f"helper gave {helper!r}, evaluator gave {direct!r}")

    # full worker path: seeded resolved market, real insert
    path = _make_db()
    try:
        _seed_trader(path, '0xc1')
        _seed_market(path, '0xmC1', resolved=1, winning_outcome='No')
        _run_worker(path, '0xc1', [_api_trade('txC1', 'ASSETC1', '0xmC1', 'Yes', 'BUY')])
        row = _fetch_trade(path, 'txC1-ASSETC1')
        r.check("1.full worker inserts 'lost' for bet Yes / winner No on resolved market",
                row is not None and row['trade_result'] == 'lost',
                f"row={row and row['trade_result']!r}")
        r.check("1.full data_source still 'background_backfill'",
                row is not None and row['data_source'] == 'background_backfill',
                f"row={row and row['data_source']!r}")
    finally:
        os.unlink(path)


# ── 2. NON-TAUTOLOGY — still writes 'pending' ─────────────────────────────────

def _non_tautology(r):
    print("\n[2] NON-TAUTOLOGY — new path still writes 'pending' where it must")

    # helper-level fall-throughs
    r.check("2.a helper: market absent (None) -> pending",
            _resolve_ingest_trade_result({'outcome': 'Yes', 'side': 'BUY'}, None) == 'pending')
    r.check("2.b helper: market not resolved (resolved=0) -> pending",
            _resolve_ingest_trade_result({'outcome': 'Yes', 'side': 'BUY'}, (0, 'Yes')) == 'pending')
    r.check("2.c helper: winning_outcome NULL -> pending",
            _resolve_ingest_trade_result({'outcome': 'Yes', 'side': 'BUY'}, (1, None)) == 'pending')
    r.check("2.d helper: winning_outcome '' -> pending",
            _resolve_ingest_trade_result({'outcome': 'Yes', 'side': 'BUY'}, (1, '')) == 'pending')
    r.check("2.e helper: winning_outcome 'unknown' -> pending",
            _resolve_ingest_trade_result({'outcome': 'Yes', 'side': 'BUY'}, (1, 'unknown')) == 'pending')
    r.check("2.f helper: unusable outcome ('' bet) -> pending (evaluator 'invalid')",
            _resolve_ingest_trade_result({'outcome': '', 'side': 'BUY'}, (1, 'Yes')) == 'pending')

    # full worker path: UNRESOLVED seeded market
    path = _make_db()
    try:
        _seed_trader(path, '0xn1')
        _seed_market(path, '0xmN1', resolved=0, winning_outcome=None)
        _run_worker(path, '0xn1', [_api_trade('txN1', 'ASSETN1', '0xmN1', 'Yes', 'BUY')])
        row = _fetch_trade(path, 'txN1-ASSETN1')
        r.check("2.g full worker: unresolved market -> trade_result='pending'",
                row is not None and row['trade_result'] == 'pending',
                f"row={row and row['trade_result']!r}")
    finally:
        os.unlink(path)

    # full worker path: ABSENT market (never seeded; worker stubs it resolved=0)
    path = _make_db()
    try:
        _seed_trader(path, '0xn2')
        _run_worker(path, '0xn2', [_api_trade('txN2', 'ASSETN2', '0xmN2_absent', 'Yes', 'BUY')])
        row = _fetch_trade(path, 'txN2-ASSETN2')
        r.check("2.h full worker: market absent from markets -> trade_result='pending'",
                row is not None and row['trade_result'] == 'pending',
                f"row={row and row['trade_result']!r}")
    finally:
        os.unlink(path)

    # full worker path: resolved market but winning_outcome 'unknown'
    path = _make_db()
    try:
        _seed_trader(path, '0xn3')
        _seed_market(path, '0xmN3', resolved=1, winning_outcome='unknown')
        _run_worker(path, '0xn3', [_api_trade('txN3', 'ASSETN3', '0xmN3', 'Yes', 'BUY')])
        row = _fetch_trade(path, 'txN3-ASSETN3')
        r.check("2.i full worker: resolved + winning_outcome='unknown' -> 'pending'",
                row is not None and row['trade_result'] == 'pending',
                f"row={row and row['trade_result']!r}")
    finally:
        os.unlink(path)

    # mixed batch: one evaluable + one not, same trader/run
    path = _make_db()
    try:
        _seed_trader(path, '0xn4')
        _seed_market(path, '0xmN4a', resolved=1, winning_outcome='Yes')
        _seed_market(path, '0xmN4b', resolved=0, winning_outcome=None)
        _run_worker(path, '0xn4', [
            _api_trade('txN4a', 'ASSETN4A', '0xmN4a', 'Yes', 'BUY'),
            _api_trade('txN4b', 'ASSETN4B', '0xmN4b', 'Yes', 'BUY'),
        ])
        a = _fetch_trade(path, 'txN4a-ASSETN4A')
        b = _fetch_trade(path, 'txN4b-ASSETN4B')
        r.check("2.j mixed batch: resolved leg -> 'won'",
                a is not None and a['trade_result'] == 'won', f"a={a and a['trade_result']!r}")
        r.check("2.k mixed batch: unresolved leg -> 'pending'",
                b is not None and b['trade_result'] == 'pending', f"b={b and b['trade_result']!r}")
    finally:
        os.unlink(path)


# ── 3. NO EXISTING ROW CHANGED ───────────────────────────────────────────────

def _no_existing_row_changed(r):
    print("\n[3] NO EXISTING ROW CHANGED — INSERT OR IGNORE leaves stored rows alone")
    path = _make_db()
    try:
        _seed_trader(path, '0xe1')
        # market resolved such that the trade would evaluate to 'lost'
        _seed_market(path, '0xmE1', resolved=1, winning_outcome='No')
        # pre-existing row for the SAME trade_id the worker will compute, stored as 'won'
        # worker trade_id = f"{tx}-{asset[:8]}" -> 'txE1-ASSETE1'
        _seed_trade(path, 'txE1-ASSETE1', '0xe1', '0xmE1', trade_result='won')

        before = _fetch_trade(path, 'txE1-ASSETE1')
        _run_worker(path, '0xe1', [_api_trade('txE1', 'ASSETE1', '0xmE1', 'Yes', 'BUY')])
        after = _fetch_trade(path, 'txE1-ASSETE1')

        r.check("3.a pre-existing trade_result unchanged ('won' stays 'won')",
                after is not None and after['trade_result'] == 'won',
                f"after={after and after['trade_result']!r} (expected 'won')")
        r.check("3.b pre-existing data_source unchanged ('polymarket_api' preserved)",
                after is not None and after['data_source'] == 'polymarket_api',
                f"after={after and after['data_source']!r}")
        r.check("3.c row identical before/after the backfill run",
                before == after, "row dict changed")

        # sanity: a genuinely-new trade in the same run IS evaluated
        _run_worker(path, '0xe1', [_api_trade('txE1b', 'ASSETE1B', '0xmE1', 'Yes', 'BUY')])
        newrow = _fetch_trade(path, 'txE1b-ASSETE1B')
        r.check("3.d sanity: a NEW trade in the same market IS evaluated ('lost')",
                newrow is not None and newrow['trade_result'] == 'lost',
                f"newrow={newrow and newrow['trade_result']!r}")
    finally:
        os.unlink(path)


def run_tests():
    r = TestResults()
    _correctness(r)
    _non_tautology(r)
    _no_existing_row_changed(r)
    return r.summary()


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)
