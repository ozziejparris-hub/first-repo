#!/usr/bin/env python3
"""
tests/test_o15_naive_aware_datetime.py

Proves the O-15 naive/aware datetime fix (2026-07-06) in
monitoring/position_tracker.py's Position.close_position().

Bug: apply_synthetic_closes() parses markets.resolution_date via
datetime.fromisoformat(raw_date). Before the O-16/O-3 timestamp
normalization fix (same day), ~66,319 resolution_date rows were stored
in ISO8601-with-offset format ("...+00:00"), which fromisoformat() turns
into a timezone-AWARE datetime. entry_timestamp (parsed from trades.timestamp,
always canonical/naive) stays timezone-NAIVE. close_position()'s
`exit_timestamp - self.entry_timestamp` then raised:
    TypeError: can't subtract offset-naive and offset-aware datetimes
Proven live via monitoring.log tracebacks: 7,218 occurrences, causing
1,420 traders to accumulate 5 consecutive background_pnl_worker failures
and get permanently pnl_skip=1'd (see brain/decisions O-15 investigation).

Because the exception fired mid-loop in apply_synthetic_closes(), BEFORE
_process_trader_sync's position-persist step, it aborted writing ALL of
that trader's positions for the cycle (not just the offending one) --
this is the direct mechanism behind "BUY trades with no position record"
growing ~17K/day.

Fix: close_position() now strips tzinfo from both exit_timestamp and
self.entry_timestamp (all timestamps in this system are UTC, so this is
lossless -- same reasoning already used by column_definitions.py's
dormancy-decay guard, which this fix mirrors).

Tests:
  T1  aware exit_timestamp + naive entry_timestamp (the actual bug case,
      e.g. synthetic close against a pre-fix resolution_date) no longer
      raises TypeError
  T2  T1's computed holding_period_hours is numerically correct -- proves
      stripping tzinfo doesn't shift the instant (lossless, since all
      timestamps are UTC)
  T3  naive exit_timestamp + aware entry_timestamp (the mirror-image case)
      also succeeds and computes correctly
  T4  both-naive (the normal real-SELL-match case) is unaffected -- no
      regression
  T5  both-aware is unaffected -- no regression
  T6  realized_pnl / status fields are computed independent of the
      tzinfo-strip (guards against the fix accidentally touching
      unrelated computation)
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monitoring.position_tracker import Position


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


def _make_position(entry_timestamp) -> Position:
    return Position(
        trader_address="0xO15TestTrader00000000000000000000000000",
        market_id="0xO15TestMarket0000000000000000000000000000",
        market_title="O-15 test market",
        outcome="Yes",
        entry_shares=100.0,
        entry_avg_price=0.40,
        entry_timestamp=entry_timestamp,
        entry_trade_ids=["trade1"],
    )


def _section_1(r: TestResults):
    print("\n--- T1/T2: aware exit_timestamp + naive entry_timestamp (the actual bug) ---")

    entry_naive = datetime(2026, 1, 1, 0, 0, 0)               # trades.timestamp, always naive
    exit_aware = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)  # pre-fix resolution_date

    pos = _make_position(entry_naive)

    try:
        pos.close_position(
            exit_shares=100.0,
            exit_avg_price=1.0,
            exit_timestamp=exit_aware,
            exit_trade_ids=[],
        )
        r.ok("T1 aware exit_timestamp - naive entry_timestamp does not raise TypeError")
    except TypeError as e:
        r.fail("T1 aware exit_timestamp - naive entry_timestamp does not raise TypeError", str(e))
        return

    r.check(
        "T2 holding_period_hours is numerically correct (24h, instant unchanged by tzinfo strip)",
        pos.holding_period_hours == 24.0,
        f"Expected 24.0, got {pos.holding_period_hours}",
    )
    r.check(
        "T2b status computed correctly (fully closed)",
        pos.status == "closed" and pos.remaining_shares == 0,
        f"status={pos.status}, remaining_shares={pos.remaining_shares}",
    )


def _section_2(r: TestResults):
    print("\n--- T3: naive exit_timestamp + aware entry_timestamp (mirror-image case) ---")

    entry_aware = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    exit_naive = datetime(2026, 1, 1, 12, 0, 0)

    pos = _make_position(entry_aware)

    try:
        pos.close_position(
            exit_shares=100.0,
            exit_avg_price=1.0,
            exit_timestamp=exit_naive,
            exit_trade_ids=[],
        )
        r.ok("T3 naive exit_timestamp - aware entry_timestamp does not raise TypeError")
    except TypeError as e:
        r.fail("T3 naive exit_timestamp - aware entry_timestamp does not raise TypeError", str(e))
        return

    r.check(
        "T3b holding_period_hours correct (12h)",
        pos.holding_period_hours == 12.0,
        f"Expected 12.0, got {pos.holding_period_hours}",
    )


def _section_3(r: TestResults):
    print("\n--- T4/T5: no-regression on same-tzinfo pairs (the normal real-SELL-match case) ---")

    # T4: both naive -- the everyday case (trades.timestamp on both sides)
    entry_naive = datetime(2026, 3, 1, 6, 0, 0)
    exit_naive = datetime(2026, 3, 3, 6, 0, 0)
    pos = _make_position(entry_naive)
    pos.close_position(100.0, 0.6, exit_naive, ["trade2"])
    r.check(
        "T4 both-naive unaffected (48h)",
        pos.holding_period_hours == 48.0,
        f"Expected 48.0, got {pos.holding_period_hours}",
    )

    # T5: both aware
    entry_aware = datetime(2026, 3, 1, 6, 0, 0, tzinfo=timezone.utc)
    exit_aware = datetime(2026, 3, 1, 18, 0, 0, tzinfo=timezone.utc)
    pos2 = _make_position(entry_aware)
    pos2.close_position(100.0, 0.6, exit_aware, ["trade3"])
    r.check(
        "T5 both-aware unaffected (12h)",
        pos2.holding_period_hours == 12.0,
        f"Expected 12.0, got {pos2.holding_period_hours}",
    )


def _section_4(r: TestResults):
    print("\n--- T6: P&L computation unaffected by the tzinfo-strip guard ---")

    entry_naive = datetime(2026, 1, 1, 0, 0, 0)
    exit_aware = datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
    pos = _make_position(entry_naive)  # entry_shares=100, entry_avg_price=0.40 -> cost_basis=40
    pos.close_position(
        exit_shares=50.0,
        exit_avg_price=1.0,   # winning synthetic close
        exit_timestamp=exit_aware,
        exit_trade_ids=[],
    )
    expected_pnl = 50.0 * 1.0 - (40.0 * 0.5)  # 50 - 20 = 30
    r.check(
        "T6a realized_pnl correct with mixed naive/aware inputs",
        abs(pos.realized_pnl - expected_pnl) < 1e-9,
        f"Expected {expected_pnl}, got {pos.realized_pnl}",
    )
    r.check(
        "T6b partial close status correct",
        pos.status == "partially_closed" and pos.remaining_shares == 50.0,
        f"status={pos.status}, remaining_shares={pos.remaining_shares}",
    )


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
