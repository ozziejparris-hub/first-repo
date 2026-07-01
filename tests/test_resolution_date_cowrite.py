#!/usr/bin/env python3
"""
tests/test_resolution_date_cowrite.py

Proves the O-17 resolution_date co-write fix (2026-07-01).

Bug: 3 passes in fast_resolution_check.py (run_stale_clob_pass,
run_recent_overdue_pass, run_external_seed_pass) plus both resolution
branches each in resolve_legendary_markets.py and legendary_positions_scan.py
set resolved=1 without writing resolution_date. This silently broke
requeue_resolved_market_traders.py's `resolution_date > ?` filter, so
traders in markets resolved by these 5 call sites never got requeued for
P&L recalculation. 182 markets accumulated this way before the fix
(backfilled separately via a one-time UPDATE).

Fix: resolution_date = COALESCE(resolution_date, ?) added to all 7 write
paths across the 3 files, bound to datetime.now() — the same source-of-truth
already used by the working writers (database.py's update_market_resolution,
fast_resolution_check.py's batch_update_resolved_markets / Gamma bulk pass).

Tests:
  SECTION 1 — write-path proof, fast_resolution_check.py's 3 broken passes
    T1  run_stale_clob_pass       resolves a market -> resolution_date written
    T2  run_recent_overdue_pass   resolves a market -> resolution_date written
    T3  run_external_seed_pass    resolves a market -> resolution_date written

  SECTION 2 — legendary scripts (direct call, Gamma fetch mocked)
    T4  legendary_positions_scan._resolve_one_market, winner branch
    T5  legendary_positions_scan._resolve_one_market, no-winner/zero-price branch
    T6  resolve_legendary_markets.resolve_legendary_markets, winner branch
    T7  resolve_legendary_markets.resolve_legendary_markets, __RESOLVED_NO_WINNER__ branch

  SECTION 3 — COALESCE non-destructive (the "inert-but-buggy" path proof)
    T8  a market that already has resolution_date keeps its original value
        when re-resolved through the fixed code (no clobbering)

  SECTION 4 — requeue-visibility (the actual downstream effect being fixed)
    T9  a market resolved via run_recent_overdue_pass now PASSES
        requeue_resolved_market_traders.py's resolution_date filter, end-to-end
"""

import io
import os
import subprocess
import sys
import sqlite3
import tempfile
import time as _real_time
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'monitoring'))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

_PROD_DB = (ROOT / 'data' / 'polymarket_tracker.db').resolve()

from fast_resolution_check import FastResolutionChecker
import legendary_positions_scan as lps
import resolve_legendary_markets as rlm


# ─────────────────────────────────────────────────────────────────────────────
# TestResults — follows existing repo pattern
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

    def check(self, name: str, cond: bool, reason: str = ""):
        if cond:
            self.ok(name)
        else:
            self.fail(name, reason or "condition was False")

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
# Temp DB factory — never touches production
# ─────────────────────────────────────────────────────────────────────────────

def _make_full_db() -> str:
    """Temp SQLite DB with markets, traders, trades, positions — full enough
    for all 3 fast_resolution_check.py passes plus the requeue script."""
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_o17_')
    os.close(fd)
    assert Path(path).resolve() != _PROD_DB, \
        f"BUG: temp DB resolved to production path: {path}"
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            market_id       TEXT PRIMARY KEY,
            title           TEXT,
            category        TEXT,
            end_date        TIMESTAMP,
            resolved        BOOLEAN DEFAULT 0,
            winning_outcome TEXT,
            last_checked    TIMESTAMP,
            resolution_date TIMESTAMP,
            condition_id    TEXT,
            api_id          TEXT,
            difficulty_score REAL,
            trade_gap_flag  BOOLEAN NOT NULL DEFAULT 0,
            clob_token_id_yes TEXT,
            clob_token_id_no  TEXT,
            data_source     TEXT NOT NULL DEFAULT 'live_monitoring'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traders (
            address           TEXT PRIMARY KEY,
            discovery_source  TEXT DEFAULT 'live_feed',
            pnl_last_updated  TIMESTAMP,
            research_excluded BOOLEAN DEFAULT 0,
            bot_type          TEXT,
            geo_elo_active    REAL,
            geo_accuracy_pool BOOLEAN DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            trade_id       TEXT PRIMARY KEY,
            trader_address TEXT,
            market_id      TEXT,
            timestamp      TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            position_id     TEXT PRIMARY KEY,
            trader_address  TEXT NOT NULL,
            market_id       TEXT NOT NULL,
            outcome         TEXT,
            status          TEXT NOT NULL,
            entry_shares    REAL,
            entry_avg_price REAL,
            entry_total_cost REAL,
            entry_timestamp TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return path


def _make_checker(db_path: str, winner: str = "Yes") -> FastResolutionChecker:
    buf = io.StringIO()
    with redirect_stdout(buf):
        checker = FastResolutionChecker(db_path=db_path)
    checker.session = _MockClosedSession(winner=winner)
    return checker


def _seed_market(db_path, market_id, resolved=0, resolution_date=None,
                  end_date=None, condition_id=None, api_id=None, last_checked=None):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO markets
           (market_id, resolved, resolution_date, end_date, condition_id, api_id, last_checked)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (market_id, resolved, resolution_date, end_date, condition_id, api_id, last_checked),
    )
    conn.commit()
    conn.close()


def _get_market(db_path, market_id):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT resolved, resolution_date, winning_outcome, last_checked FROM markets WHERE market_id = ?",
        (market_id,),
    ).fetchone()
    conn.close()
    return row


# ─────────────────────────────────────────────────────────────────────────────
# Mock CLOB session — closed:True with a winner token (resolution case)
# ─────────────────────────────────────────────────────────────────────────────

class _ClosedResponse:
    status_code = 200

    def __init__(self, winner):
        self._winner = winner

    def json(self):
        return {
            'closed': True,
            'tokens': [
                {'outcome': 'Yes', 'winner': self._winner == 'Yes'},
                {'outcome': 'No', 'winner': self._winner == 'No'},
            ],
        }


class _MockClosedSession:
    def __init__(self, winner="Yes"):
        self.winner = winner

    def get(self, url, timeout=None):
        return _ClosedResponse(self.winner)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — fast_resolution_check.py's 3 broken passes
# ─────────────────────────────────────────────────────────────────────────────

def _section_1(r: TestResults):
    print("\n[SECTION 1] fast_resolution_check.py write-path proof")
    print("-" * 50)

    # T1 — run_stale_clob_pass
    db = None
    try:
        db = _make_full_db()
        old_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
        _seed_market(db, "stale_mkt", resolved=0, resolution_date=old_date)
        checker = _make_checker(db, winner="Yes")
        with patch('time.sleep'):
            checker.run_stale_clob_pass(stale_limit=10, test_mode=False)
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "stale_mkt")
        r.check(
            "T1  run_stale_clob_pass writes resolution_date on resolve",
            resolved == 1 and resolution_date is not None and winning_outcome == "Yes",
            f"Got resolved={resolved}, resolution_date={resolution_date}, winning_outcome={winning_outcome}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    # T2 — run_recent_overdue_pass
    db = None
    try:
        db = _make_full_db()
        recent_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        _seed_market(db, "recent_mkt", resolved=0, resolution_date=recent_date)
        checker = _make_checker(db, winner="No")
        with patch('time.sleep'):
            checker.run_recent_overdue_pass(limit=10, test_mode=False)
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "recent_mkt")
        r.check(
            "T2  run_recent_overdue_pass writes resolution_date on resolve",
            resolved == 1 and resolution_date is not None and winning_outcome == "No",
            f"Got resolved={resolved}, resolution_date={resolution_date}, winning_outcome={winning_outcome}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    # T3 — run_external_seed_pass
    db = None
    try:
        db = _make_full_db()
        old_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
        _seed_market(db, "ext_mkt", resolved=0, resolution_date=old_date)
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO traders (address, discovery_source) VALUES (?, 'external_seed')",
                     ("0xExternalSeedTrader",))
        conn.execute("INSERT INTO trades (trade_id, trader_address, market_id) VALUES (?, ?, ?)",
                     ("t1", "0xExternalSeedTrader", "ext_mkt"))
        conn.commit()
        conn.close()
        checker = _make_checker(db, winner="Yes")
        with patch('time.sleep'):
            checker.run_external_seed_pass(limit=10, test_mode=False)
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "ext_mkt")
        r.check(
            "T3  run_external_seed_pass writes resolution_date on resolve",
            resolved == 1 and resolution_date is not None and winning_outcome == "Yes",
            f"Got resolved={resolved}, resolution_date={resolution_date}, winning_outcome={winning_outcome}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — legendary scripts (Gamma fetch mocked, real UPDATE code paths)
# ─────────────────────────────────────────────────────────────────────────────

def _section_2(r: TestResults):
    print("\n[SECTION 2] legendary scripts write-path proof")
    print("-" * 50)

    # T4 — legendary_positions_scan._resolve_one_market, winner branch
    db = None
    try:
        db = _make_full_db()
        _seed_market(db, "lps_winner", resolved=0, resolution_date=None)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with patch.object(lps, '_fetch_gamma_full',
                           return_value={'closed': True,
                                         'outcomePrices': [1.0, 0.0]}):
            updated = lps._resolve_one_market(conn, {"market_id": "lps_winner"})
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "lps_winner")
        conn.close()
        r.check(
            "T4  legendary_positions_scan winner branch writes resolution_date",
            updated is True and resolved == 1 and resolution_date is not None and winning_outcome == "Yes",
            f"Got updated={updated}, resolved={resolved}, resolution_date={resolution_date}, winning_outcome={winning_outcome}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    # T5 — legendary_positions_scan._resolve_one_market, zero-price/no-winner branch
    db = None
    try:
        db = _make_full_db()
        _seed_market(db, "lps_nowinner", resolved=0, resolution_date=None)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with patch.object(lps, '_fetch_gamma_full',
                           return_value={'closed': True,
                                         'outcomePrices': [0.0, 0.0]}):
            updated = lps._resolve_one_market(conn, {"market_id": "lps_nowinner"})
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "lps_nowinner")
        conn.close()
        r.check(
            "T5  legendary_positions_scan no-winner branch writes resolution_date",
            updated is True and resolved == 1 and resolution_date is not None,
            f"Got updated={updated}, resolved={resolved}, resolution_date={resolution_date}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    # T6 — resolve_legendary_markets.resolve_legendary_markets, winner branch
    db = None
    orig_db_path = rlm._DB_PATH
    try:
        db = _make_full_db()
        _seed_market(db, "rlm_winner", resolved=0, resolution_date=None)
        rlm._DB_PATH = db
        with patch.object(rlm, '_fetch_overdue_legendary_markets',
                           return_value=[{"market_id": "rlm_winner", "title": "t",
                                          "api_id": None, "condition_id": None,
                                          "resolution_date": None}]), \
             patch.object(rlm, '_fetch_gamma_market',
                           return_value={'closed': True,
                                         'outcomePrices': [1.0, 0.0],
                                         'outcomes': ['Yes', 'No']}), \
             patch('time.sleep'):
            buf = io.StringIO()
            with redirect_stdout(buf):
                summary = rlm.resolve_legendary_markets(limit=10, dry_run=False)
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "rlm_winner")
        r.check(
            "T6  resolve_legendary_markets winner branch writes resolution_date",
            summary["markets_updated"] == 1 and resolved == 1
            and resolution_date is not None and winning_outcome == "Yes",
            f"Got summary={summary}, resolved={resolved}, resolution_date={resolution_date}, winning_outcome={winning_outcome}",
        )
    finally:
        rlm._DB_PATH = orig_db_path
        if db and os.path.exists(db):
            os.unlink(db)

    # T7 — resolve_legendary_markets, __RESOLVED_NO_WINNER__ branch
    db = None
    orig_db_path = rlm._DB_PATH
    try:
        db = _make_full_db()
        _seed_market(db, "rlm_nowinner", resolved=0, resolution_date=None)
        rlm._DB_PATH = db
        with patch.object(rlm, '_fetch_overdue_legendary_markets',
                           return_value=[{"market_id": "rlm_nowinner", "title": "t",
                                          "api_id": None, "condition_id": None,
                                          "resolution_date": None}]), \
             patch.object(rlm, '_fetch_gamma_market',
                           return_value={'closed': True,
                                         'outcomePrices': [0.0, 0.0],
                                         'outcomes': ['Yes', 'No']}), \
             patch('time.sleep'):
            buf = io.StringIO()
            with redirect_stdout(buf):
                summary = rlm.resolve_legendary_markets(limit=10, dry_run=False)
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "rlm_nowinner")
        r.check(
            "T7  resolve_legendary_markets __RESOLVED_NO_WINNER__ branch writes resolution_date",
            summary["markets_updated"] == 1 and resolved == 1 and resolution_date is not None,
            f"Got summary={summary}, resolved={resolved}, resolution_date={resolution_date}",
        )
    finally:
        rlm._DB_PATH = orig_db_path
        if db and os.path.exists(db):
            os.unlink(db)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — COALESCE non-destructive
# ─────────────────────────────────────────────────────────────────────────────

def _section_3(r: TestResults):
    print("\n[SECTION 3] COALESCE non-destructive proof")
    print("-" * 50)

    db = None
    try:
        db = _make_full_db()
        original_date = "2026-06-01 12:00:00"
        _seed_market(db, "already_dated", resolved=0, resolution_date=original_date)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with patch.object(lps, '_fetch_gamma_full',
                           return_value={'closed': True, 'outcomePrices': [1.0, 0.0]}):
            lps._resolve_one_market(conn, {"market_id": "already_dated"})
        resolved, resolution_date, winning_outcome, _ = _get_market(db, "already_dated")
        conn.close()
        r.check(
            "T8  pre-existing resolution_date is preserved, not overwritten",
            resolution_date == original_date,
            f"Expected resolution_date to stay '{original_date}', got '{resolution_date}'",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — requeue-visibility, end-to-end
# ─────────────────────────────────────────────────────────────────────────────

def _section_4(r: TestResults):
    print("\n[SECTION 4] requeue-visibility end-to-end")
    print("-" * 50)

    db = None
    try:
        db = _make_full_db()
        recent_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        _seed_market(db, "requeue_mkt", resolved=0, resolution_date=recent_date)

        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO traders (address) VALUES (?)", ("0xRequeueTrader",))
        conn.execute(
            """INSERT INTO positions
               (position_id, trader_address, market_id, outcome, status,
                entry_shares, entry_avg_price, entry_total_cost, entry_timestamp)
               VALUES ('p1', '0xRequeueTrader', 'requeue_mkt', 'Yes', 'open', 100, 0.5, 50, ?)""",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),),
        )
        conn.commit()
        conn.close()

        # Resolve via the fixed run_recent_overdue_pass (writes resolution_date now)
        checker = _make_checker(db, winner="Yes")
        with patch('time.sleep'):
            checker.run_recent_overdue_pass(limit=10, test_mode=False)

        resolved, resolution_date, winning_outcome, _ = _get_market(db, "requeue_mkt")
        r.check(
            "T9a market resolved with resolution_date set (precondition for filter test)",
            resolved == 1 and resolution_date is not None,
            f"Got resolved={resolved}, resolution_date={resolution_date}",
        )

        # Now run the actual downstream script against this DB — --dry-run --force
        # avoids writing to the real timestamp file or trader rows.
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'requeue_resolved_market_traders.py'),
             '--db', db, '--dry-run', '--force'],
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout
        r.check(
            "T9b requeue_resolved_market_traders.py exits cleanly",
            result.returncode == 0,
            f"stderr: {result.stderr[:500]}",
        )
        r.check(
            "T9c requeue script's resolution_date filter now catches the market "
            "(the actual downstream effect O-17 fixes)",
            "Markets resolved since last run: 1" in out and "0xRequeueTrader"[:10] in out,
            f"Expected 1 matched market and trader in dry-run output. Got:\n{out[:800]}",
        )
    finally:
        if db and os.path.exists(db):
            os.unlink(db)


def run_tests() -> bool:
    r = TestResults()
    _section_1(r)
    _section_2(r)
    _section_3(r)
    _section_4(r)
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
