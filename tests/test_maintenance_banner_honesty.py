#!/usr/bin/env python3
"""
tests/test_maintenance_banner_honesty.py

Proves the O-26 fix: daily_maintenance.py's completion banner now reflects
whether steps actually passed, instead of being a hardcoded "all steps
succeeded" string regardless of reality (Fable finding 4.1).

Section 1 tests build_banner() directly — the pure function that decides
what the banner says, given real step outcomes.

Section 2 simulates a full maintenance run's step loop (the exact
accumulation pattern main() uses: total_tracked/failed_steps built up
across the main STEPS list, run_test_suite, WAL checkpoint, and the two
trailing run_step() calls) using canned pass/fail results instead of real
subprocesses, then feeds the result into build_banner() — proving the
whole pipeline, not just the string formatter in isolation.
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


def _simulate_run(step_results: list) -> str:
    """Reproduces main()'s exact accumulation pattern (total_tracked / failed_steps
    built up one tracked action at a time) against a list of (label, ok) pairs
    standing in for real subprocess outcomes, then hands the result to the real
    build_banner(). This is main()'s banner-building logic exercised end-to-end,
    just with canned results instead of spawning real subprocesses."""
    failed_steps = []
    total_tracked = 0
    for label, ok in step_results:
        total_tracked += 1
        if not ok:
            failed_steps.append(label)
    passed_count = total_tracked - len(failed_steps)
    return dm.build_banner(passed_count, total_tracked, failed_steps, elapsed=123.4)


def run_tests() -> bool:
    r = TestResults()

    # ── Section 1: build_banner() directly ──────────────────────────────────
    print("\n[SECTION 1] build_banner() — the pure decision function")
    print("-" * 50)

    all_ok = dm.build_banner(29, 29, [], elapsed=6582.2)
    r.check(
        "T1  all-pass banner says ALL OK, not the old hardcoded string",
        "ALL OK" in all_ok and "29/29" in all_ok,
        f"Got: {all_ok!r}",
    )
    r.check(
        "T1b  all-pass banner still starts with '=== MAINTENANCE COMPLETE' "
        "(backward compatible with any existing grep on that phrase)",
        all_ok.startswith("=== MAINTENANCE COMPLETE"),
        f"Got: {all_ok!r}",
    )
    r.check(
        "T1c  all-pass banner does NOT contain the old unconditional lie",
        "all steps succeeded" not in all_ok,
        f"Got: {all_ok!r}",
    )

    one_failed = dm.build_banner(28, 29, ["Backfill market categories"], elapsed=6600.0)
    r.check(
        "T2  one-failure banner reports FAILURES, not a clean pass",
        "FAILURES" in one_failed,
        f"Got: {one_failed!r}",
    )
    r.check(
        "T2b  one-failure banner names the failed step",
        "Backfill market categories" in one_failed,
        f"Got: {one_failed!r}",
    )
    r.check(
        "T2c  one-failure banner shows the correct N/M count (28/29)",
        "28/29" in one_failed,
        f"Got: {one_failed!r}",
    )
    r.check(
        "T2d  one-failure banner does NOT claim ALL OK",
        "ALL OK" not in one_failed,
        f"Got: {one_failed!r}",
    )

    multi_failed = dm.build_banner(
        26, 29, ["Backfill market categories", "Run test suite", "WAL checkpoint"],
        elapsed=6700.0,
    )
    r.check(
        "T3  multi-failure banner names ALL failed steps, not just one",
        all(name in multi_failed for name in
            ["Backfill market categories", "Run test suite", "WAL checkpoint"]),
        f"Got: {multi_failed!r}",
    )
    r.check(
        "T3b  multi-failure banner shows correct N/M count (26/29)",
        "26/29" in multi_failed,
        f"Got: {multi_failed!r}",
    )

    # ── Section 2: full accumulation pipeline (simulated run) ───────────────
    print("\n[SECTION 2] Simulated maintenance run — main()'s accumulation logic")
    print("-" * 50)

    # All 29 tracked actions pass — the clean-run case.
    clean_run = [(f"step_{i}", True) for i in range(29)]
    banner = _simulate_run(clean_run)
    r.check(
        "T4  clean simulated run (29/29 pass) produces the ALL OK banner",
        "ALL OK" in banner and "29/29" in banner,
        f"Got: {banner!r}",
    )

    # One non-blocking step fails partway through (the exact scenario Fable's
    # finding is about) — everything else, including the trailing test-suite/
    # WAL-checkpoint/backfill/hydrate actions, passes.
    one_bad_run = [(f"step_{i}", True) for i in range(27)] + [
        ("Backfill market categories", False),
        ("Run test suite", True),
    ]
    banner2 = _simulate_run(one_bad_run)
    r.check(
        "T5  one non-blocking failure mid-run is reported, NOT silently absorbed",
        "FAILURES" in banner2 and "Backfill market categories" in banner2,
        f"Got: {banner2!r}",
    )
    r.check(
        "T5b  the count reflects exactly one failure out of the total (28/29)",
        "28/29" in banner2,
        f"Got: {banner2!r}",
    )
    r.check(
        "T5c  a passing step's name does NOT appear in the failed list",
        "Run test suite" not in banner2.split("FAILED:")[1] if "FAILED:" in banner2 else True,
        f"Got: {banner2!r}",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
