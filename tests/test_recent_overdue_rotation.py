#!/usr/bin/env python3
"""
tests/test_recent_overdue_rotation.py

Proves that the round-robin rotation fix in run_recent_overdue_pass() works.

Rotation fix (2026-06-30):
  1. ORDER BY last_checked ASC NULLS FIRST  (least-recently-checked first)
  2. Update last_checked on every CLOB check, not just on resolution
  3. LIMIT default 100 → 200
  4. Cap-hit [WARN] log when total_in_window > limit

Tests are designed to prove ROTATION, not just execution:
  T1  Cap-hit [WARN] fires when 250 markets > limit 200
  T2  Keystone: all 200 checked markets get last_checked updated even when closed:False
      (proves the every-check update fires on non-resolution — the critical new behaviour)
  T2b 50 markets remain NULL after run 1 (not yet reached by the cap)
  T3  Rotation: the 50 NULL markets from run 1 are visited FIRST in run 2
      (proves ORDER BY last_checked ASC NULLS FIRST drives the priority queue)
  T4  Full coverage: all 250 markets have non-NULL last_checked after 2 runs
      (proves ⌈250/200⌉ = 2 runs is sufficient — no permanent starvation)
  T5  No-cap case: [WARN] absent when 150 markets < limit 200
  T5b All 150 markets checked in one run when under limit

If T3 fails, rotation is broken — the last_checked update is not working and
ORDER BY alone cannot create rotation (checked-but-open markets never rotate down).
"""

import io
import os
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


# ─────────────────────────────────────────────────────────────────────────────
# Mock CLOB session — always returns closed:False (testing rotation, not resolution)
# ─────────────────────────────────────────────────────────────────────────────

class _ClosedFalseResponse:
    status_code = 200

    def json(self):
        return {'closed': False, 'tokens': []}


class _MockSession:
    def get(self, url, timeout=None):
        return _ClosedFalseResponse()


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

def _make_empty_db() -> str:
    """
    Create a temp SQLite DB with the full markets schema.

    Pre-creating the markets table (with condition_id and all columns that
    run_recent_overdue_pass needs) means Database.__init__'s CREATE TABLE IF
    NOT EXISTS is a no-op, and its ALTER TABLE migrations fail silently
    (column already exists). The other tables (traders, trades, positions) are
    still created by Database.__init__.
    """
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_rotation_')
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
    conn.commit()
    conn.close()
    return path


def _make_checker(db_path: str) -> FastResolutionChecker:
    """Instantiate checker against temp DB (schema created here), mock session."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        checker = FastResolutionChecker(db_path=db_path)
    checker.session = _MockSession()
    return checker


def _seed_markets(db_path: str, n: int):
    """
    Insert n unresolved markets with resolution_date 3 days ago (within the 0-7 day window).
    All seeded with last_checked = NULL so they start at equal priority.
    """
    res_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(db_path)
    for i in range(n):
        conn.execute(
            "INSERT OR IGNORE INTO markets (market_id, resolved, resolution_date, last_checked) "
            "VALUES (?, 0, ?, NULL)",
            (f"market_{i:04d}", res_date),
        )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# DB query helpers
# ─────────────────────────────────────────────────────────────────────────────

def _null_last_checked(db_path: str) -> set:
    """Market IDs with last_checked IS NULL."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT market_id FROM markets WHERE last_checked IS NULL"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def _checked_since(db_path: str, since: datetime) -> set:
    """Market IDs whose last_checked >= since (i.e. updated during or after `since`)."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT market_id FROM markets WHERE last_checked >= ?",
        (since.strftime('%Y-%m-%d %H:%M:%S.%f'),),
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ─────────────────────────────────────────────────────────────────────────────
# Run helper — suppresses time.sleep, captures stdout
# ─────────────────────────────────────────────────────────────────────────────

def _run_pass(checker: FastResolutionChecker, limit: int) -> str:
    """Run the recent-overdue pass; return captured stdout. time.sleep is mocked."""
    buf = io.StringIO()
    with redirect_stdout(buf), patch('time.sleep'):
        checker.run_recent_overdue_pass(limit=limit, test_mode=False)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> bool:
    r = TestResults()

    # ── Section 1: Rotation test (250 markets, limit=200) ──────────────────
    print("\n[SECTION 1] Rotation — 250 markets, limit=200")
    print("-" * 50)

    db = None
    try:
        db = _make_empty_db()
        checker = _make_checker(db)
        _seed_markets(db, 250)

        # ── RUN 1 ──
        output1 = _run_pass(checker, limit=200)

        # T1: cap-hit warning must appear
        r.check(
            "T1  [WARN] cap-hit fires when 250 > limit 200",
            "[WARN]" in output1,
            f"Expected '[WARN]' in pass output. Got:\n{output1[:600]}",
        )

        # T2: keystone — all 200 checked markets get last_checked updated
        null_after_run1 = _null_last_checked(db)
        checked_after_run1 = 250 - len(null_after_run1)
        r.check(
            f"T2  keystone: 200 markets got last_checked updated in run 1 (got {checked_after_run1})",
            checked_after_run1 == 200,
            f"Expected 200 non-NULL last_checked after run 1, got {checked_after_run1}. "
            f"If this is 0, the every-check update is not firing.",
        )

        # T2b: 50 remain NULL (not reached by the cap)
        r.check(
            f"T2b 50 markets still NULL after run 1 (got {len(null_after_run1)})",
            len(null_after_run1) == 50,
            f"Expected exactly 50 NULL-last_checked after run 1, got {len(null_after_run1)}.",
        )

        unchecked_after_run1 = null_after_run1  # these MUST be visited first in run 2

        # Small real sleep to ensure run 2 timestamps are strictly after run 1
        _real_time.sleep(0.01)

        # ── RUN 2 ──
        t_before_run2 = datetime.now()
        output2 = _run_pass(checker, limit=200)

        # T3: rotation — the 50 formerly-NULL markets were checked in run 2
        checked_in_run2 = _checked_since(db, t_before_run2)
        rotated = unchecked_after_run1 & checked_in_run2
        r.check(
            f"T3  rotation: all 50 previously-unchecked markets visited in run 2 "
            f"(rotated={len(rotated)}, checked_in_run2={len(checked_in_run2)})",
            len(rotated) == 50,
            f"Expected all 50 formerly-NULL markets in run-2 set. "
            f"rotated={len(rotated)}/50. "
            f"If rotated=0, ORDER BY last_checked is not sorting NULLs first. "
            f"If rotated<50, some NULL markets were skipped — ordering or update broken.",
        )

        # T4: full coverage — all 250 checked after 2 runs
        null_after_run2 = _null_last_checked(db)
        r.check(
            f"T4  full coverage: 0 NULL last_checked after ⌈250/200⌉=2 runs (got {len(null_after_run2)})",
            len(null_after_run2) == 0,
            f"Expected 0 NULL after 2 runs. Got {len(null_after_run2)} still NULL. "
            f"These markets would never be checked (permanent starvation).",
        )

    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    # ── Section 2: No-cap case (150 markets, limit=200) ────────────────────
    print("\n[SECTION 2] No-cap case — 150 markets, limit=200")
    print("-" * 50)

    db2 = None
    try:
        db2 = _make_empty_db()
        checker2 = _make_checker(db2)
        _seed_markets(db2, 150)

        output_nocap = _run_pass(checker2, limit=200)

        r.check(
            "T5  [WARN] absent when 150 markets < limit 200",
            "[WARN]" not in output_nocap,
            f"Did not expect '[WARN]' but found it in:\n{output_nocap[:400]}",
        )

        null_after_nocap = _null_last_checked(db2)
        r.check(
            f"T5b all 150 markets checked in single run (null remaining: {len(null_after_nocap)})",
            len(null_after_nocap) == 0,
            f"Expected 0 NULL after 1 run with 150 < 200 limit, got {len(null_after_nocap)}.",
        )

    finally:
        if db2 and os.path.exists(db2):
            os.unlink(db2)

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
