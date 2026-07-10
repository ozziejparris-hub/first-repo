#!/usr/bin/env python3
"""
tests/test_weekly_full_sync_gate.py

Proves the O-2 weekly --full-sync backstop is gated correctly in
scripts/daily_maintenance.py's build_steps(weekday):

  T1  Sunday (weekday=6): "Sync trade categories [full, weekly]" step present,
      with --full-sync in its args and non_blocking=True.
  T2  Sunday: "Discover leaderboard traders" (the existing weekly step) is
      still present too — the new step must not replace it.
  T3  Every non-Sunday weekday (0-5): the weekly step is ABSENT.
  T4  Every non-Sunday weekday (0-5): "Discover leaderboard traders" is
      also absent (parity check — same gate, same behaviour).
  T5  All weekdays: the base daily steps (e.g. "Sync trade categories",
      the --incremental one) are present regardless of weekday.
  T6  build_steps() is pure — calling it twice for the same weekday returns
      independent list objects (mutating one must not affect STEPS or a
      second call's result).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import daily_maintenance as dm


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


WEEKLY_FULL_SYNC_LABEL = "Sync trade categories [full, weekly]"
WEEKLY_DISCOVER_LABEL = "Discover leaderboard traders"
DAILY_INCREMENTAL_LABEL = "Sync trade categories"


def _labels(steps):
    return [s[0] for s in steps]


def _find(steps, label):
    for s in steps:
        if s[0] == label:
            return s
    return None


def run_tests() -> bool:
    r = TestResults()

    # ── T1/T2: Sunday (weekday=6) ───────────────────────────────────────────
    print("\n[SECTION 1] Sunday (weekday=6) — both weekly steps present")
    print("-" * 50)

    sunday_steps = dm.build_steps(6)
    weekly_full_sync = _find(sunday_steps, WEEKLY_FULL_SYNC_LABEL)

    r.check(
        "T1  weekly full-sync step present on Sunday",
        weekly_full_sync is not None,
        f"Expected '{WEEKLY_FULL_SYNC_LABEL}' in Sunday steps, not found. "
        f"Got labels: {_labels(sunday_steps)}",
    )

    if weekly_full_sync is not None:
        script, extra_args = weekly_full_sync[1], weekly_full_sync[2]
        non_blocking = weekly_full_sync[3] if len(weekly_full_sync) > 3 else False
        r.check(
            "T1b  weekly full-sync targets sync_trade_categories.py with --full-sync",
            script.name == "sync_trade_categories.py" and extra_args == ["--full-sync"],
            f"Got script={script}, extra_args={extra_args}",
        )
        r.check(
            "T1c  weekly full-sync is non_blocking=True (a bulk data-repair step shouldn't abort the run)",
            non_blocking is True,
            f"Got non_blocking={non_blocking}",
        )

    r.check(
        "T2  existing weekly step (Discover leaderboard traders) still present alongside it",
        _find(sunday_steps, WEEKLY_DISCOVER_LABEL) is not None,
        f"Got labels: {_labels(sunday_steps)}",
    )

    # ── T3/T4: every non-Sunday weekday ─────────────────────────────────────
    print("\n[SECTION 2] Non-Sunday weekdays (0-5) — both weekly steps absent")
    print("-" * 50)

    for weekday in range(0, 6):
        steps = dm.build_steps(weekday)
        r.check(
            f"T3  weekday={weekday}: weekly full-sync step ABSENT",
            _find(steps, WEEKLY_FULL_SYNC_LABEL) is None,
            f"Found '{WEEKLY_FULL_SYNC_LABEL}' on a non-Sunday weekday={weekday} — gate is leaking.",
        )
        r.check(
            f"T4  weekday={weekday}: Discover leaderboard traders ABSENT (parity)",
            _find(steps, WEEKLY_DISCOVER_LABEL) is None,
            f"Found '{WEEKLY_DISCOVER_LABEL}' on a non-Sunday weekday={weekday}.",
        )

    # ── T5: base daily steps present on every weekday ───────────────────────
    print("\n[SECTION 3] Base daily steps present regardless of weekday")
    print("-" * 50)

    for weekday in range(0, 7):
        steps = dm.build_steps(weekday)
        r.check(
            f"T5  weekday={weekday}: daily incremental sync step present",
            _find(steps, DAILY_INCREMENTAL_LABEL) is not None,
            f"'{DAILY_INCREMENTAL_LABEL}' missing on weekday={weekday}. Got: {_labels(steps)}",
        )

    # ── T6: purity — no shared mutable state across calls ───────────────────
    print("\n[SECTION 4] build_steps() purity")
    print("-" * 50)

    base_len_before = len(dm.STEPS)
    sunday_a = dm.build_steps(6)
    sunday_a.append(("mutated-marker", Path("x")))
    sunday_b = dm.build_steps(6)
    r.check(
        "T6  mutating one call's result doesn't leak into a fresh call",
        _find(sunday_b, "mutated-marker") is None,
        "build_steps() results are sharing a list/mutable state across calls.",
    )
    r.check(
        "T6b  STEPS module constant itself is untouched",
        len(dm.STEPS) == base_len_before,
        f"dm.STEPS length changed from {base_len_before} to {len(dm.STEPS)} — a call mutated the shared constant.",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
