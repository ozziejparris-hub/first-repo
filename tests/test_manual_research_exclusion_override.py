#!/usr/bin/env python3
"""
tests/test_manual_research_exclusion_override.py

Proves the O-23 fix: a durable manual research exclusion (manual_override=1)
survives update_research_exclusions.py's daily recompute, which previously
silently reverted it (Fable finding 2.5 — 0x44a1159b, excluded 2026-06-10,
reverted within a day, back in the pool ~4 weeks before anyone noticed).

Runs the ACTUAL production logic (run_exclusion_pass(), extracted from main())
against a throwaway temp DB — never touches data/polymarket_tracker.db.

  T1  THE fix: a manually-excluded trader (meets every derived-clear condition,
      discovery_source='leaderboard' so BOTH clear queries are live candidates)
      stays research_excluded=1 after run_exclusion_pass().
  T2  Regression: a normal derived-exclusion trader (bot_type set, no manual
      override) still gets excluded/stays excluded exactly as before.
  T3  Regression: a normal clean trader (no manual override, not currently
      excluded) is left alone — the override machinery doesn't over-exclude.
  T4  Regression: a normal excluded-but-legitimately-clean trader (no manual
      override, meets every clear condition) still clears normally — proves
      the fix didn't accidentally freeze the whole CLEAR_SQL path.
  T5  manual_exclusion_reason is preserved through the pass (not clobbered).
"""

import sys
import sqlite3
import tempfile
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import update_research_exclusions as ure


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


def _make_temp_db() -> str:
    """Minimal schema covering everything run_exclusion_pass() touches:
    traders (all columns EXCLUDE_SQL/CLEAR_SQL/LEADERBOARD_CLEAR_SQL/SYNC_*
    reference) plus an empty positions table (the LP_ARTIFACT/ARB_BOT
    auto-taggers join against it; empty is a legitimate no-positions state)."""
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_o23_')
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE traders (
            address TEXT PRIMARY KEY,
            resolved_trades_count INTEGER,
            bot_suspect INTEGER DEFAULT 0,
            wash_trade_suspect INTEGER DEFAULT 0,
            bot_type TEXT,
            research_excluded INTEGER DEFAULT 0,
            is_flagged INTEGER DEFAULT 0,
            discovery_source TEXT,
            watched INTEGER DEFAULT 0,
            comprehensive_elo REAL,
            manual_override INTEGER DEFAULT 0,
            manual_exclusion_reason TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE positions (
            position_id INTEGER PRIMARY KEY,
            trader_address TEXT,
            market_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    return path


def _insert(conn, **kwargs):
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    conn.execute(f"INSERT INTO traders ({cols}) VALUES ({placeholders})", list(kwargs.values()))


def run_tests() -> bool:
    r = TestResults()
    db_path = None
    try:
        db_path = _make_temp_db()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")

        # T1 subject: mirrors 0x44a1159b exactly — manually excluded, meets every
        # CLEAR_SQL condition, discovery_source='leaderboard' so LEADERBOARD_CLEAR_SQL
        # is also a live path that could revert it.
        _insert(conn, address="0xMANUAL", resolved_trades_count=148, bot_suspect=0,
                wash_trade_suspect=0, bot_type=None, research_excluded=1, is_flagged=1,
                discovery_source="leaderboard", manual_override=1,
                manual_exclusion_reason="single_market_concentration (60 trades, 1 market)")

        # T2 subject: normal derived exclusion (bot_type set), no manual override —
        # must stay excluded via the ordinary EXCLUDE_SQL/CLEAR_SQL logic, unaffected
        # by the fix.
        _insert(conn, address="0xBOTTYPE", resolved_trades_count=50, bot_suspect=0,
                wash_trade_suspect=0, bot_type="LP_ARTIFACT", research_excluded=1,
                is_flagged=0, discovery_source=None, manual_override=0)

        # T3 subject: normal clean trader, already included, no manual override —
        # must be left alone (not spuriously excluded by anything the fix touches).
        _insert(conn, address="0xCLEAN", resolved_trades_count=40, bot_suspect=0,
                wash_trade_suspect=0, bot_type=None, research_excluded=0, is_flagged=1,
                discovery_source=None, manual_override=0)

        # T4 subject: legitimately-excluded-but-now-clean trader, no manual override —
        # must still clear via CLEAR_SQL exactly as before the fix.
        _insert(conn, address="0xNORMALCLEAR", resolved_trades_count=30, bot_suspect=0,
                wash_trade_suspect=0, bot_type=None, research_excluded=1, is_flagged=0,
                discovery_source=None, manual_override=0)

        conn.commit()

        ure.run_exclusion_pass(conn)

        rows = {row[0]: row for row in conn.execute(
            "SELECT address, research_excluded, manual_override, manual_exclusion_reason "
            "FROM traders ORDER BY address"
        )}

        r.check(
            "T1  manually-excluded trader (0xMANUAL) STAYS excluded after the recompute",
            rows["0xMANUAL"][1] == 1,
            f"Expected research_excluded=1, got {rows['0xMANUAL'][1]}. "
            f"THIS IS THE BUG if it fails — manual exclusions are being silently reverted again.",
        )

        r.check(
            "T2  normal derived-exclusion trader (0xBOTTYPE, bot_type set) still excluded — no regression",
            rows["0xBOTTYPE"][1] == 1,
            f"Expected research_excluded=1, got {rows['0xBOTTYPE'][1]}.",
        )

        r.check(
            "T3  normal clean trader (0xCLEAN) left alone — no over-exclusion side effect",
            rows["0xCLEAN"][1] == 0,
            f"Expected research_excluded=0 (unchanged), got {rows['0xCLEAN'][1]}.",
        )

        r.check(
            "T4  legitimately-clean trader with no override (0xNORMALCLEAR) still clears normally",
            rows["0xNORMALCLEAR"][1] == 0,
            f"Expected research_excluded=0 (cleared by CLEAR_SQL), got {rows['0xNORMALCLEAR'][1]}. "
            f"If this fails, the manual_override guard is over-blocking CLEAR_SQL entirely.",
        )

        r.check(
            "T5  manual_exclusion_reason preserved through the pass, not clobbered",
            rows["0xMANUAL"][3] == "single_market_concentration (60 trades, 1 market)",
            f"Got manual_exclusion_reason={rows['0xMANUAL'][3]!r}",
        )

        conn.close()

    finally:
        if db_path and os.path.exists(db_path):
            os.unlink(db_path)

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
