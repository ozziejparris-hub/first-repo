#!/usr/bin/env python3
"""
tests/test_match_control_determinism.py

Proves the match_control() determinism fix (trader_skill_metric_v2f.py:279,
fixed 2026-09-06). See brain/decisions/2026-09-06-match-control-determinism-fix.md
(trading-swarm) for the full defect write-up.

Bug: cohort_traders and elig_traders are Python sets at every call site in
this codebase. match_control() called list() on them directly, before
shuffling and before building the candidate pool -- CPython's set iteration
order for strings depends on the per-process hash seed (PYTHONHASHSEED,
randomized fresh per process by default), so the function's greedy match
result depended on that process-level entropy even at a fixed `seed`
argument. Fix: sort every set-derived sequence before use.

This is exactly the check that surfaced the original defect (Part 1D custody
work, three fresh-process re-runs of the pre-fix code producing six distinct
placebo survivor counts) -- reproduced here as an assertion, not an eyeball
check, spawning the SAME construction in separate subprocess invocations
with varying PYTHONHASHSEED and asserting byte-identical output.

Tests:
  T1  five fresh-process runs (three explicit PYTHONHASHSEED values plus two
      with PYTHONHASHSEED unset, i.e. genuinely random per the Python
      default) produce IDENTICAL matched-trader output
  T2  the matched output is non-trivial: correct size (one match per cohort
      trader, all 5 cohort members present), no cohort trader matched to
      itself, no duplicate candidate used twice -- proves the determinism
      fix did not degrade the matching logic itself
  T3  the reference matched set has stayed stable across three additional
      ad hoc PYTHONHASHSEED values not used in T1, as an extra margin
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKER = ROOT / 'tests' / '_match_control_determinism_worker.py'


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


def run_worker(pythonhashseed):
    env = os.environ.copy()
    if pythonhashseed is None:
        env.pop('PYTHONHASHSEED', None)
    else:
        env['PYTHONHASHSEED'] = str(pythonhashseed)
    result = subprocess.run(
        [sys.executable, str(WORKER)], capture_output=True, text=True, env=env, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"worker failed (PYTHONHASHSEED={pythonhashseed}): {result.stderr[:2000]}")
    return json.loads(result.stdout.strip())


def _section_1(r: TestResults):
    print("\n=== SECTION 1: fresh-process determinism across varying PYTHONHASHSEED ===")
    seeds_to_try = [0, 1, 12345, None, None]  # None = unset -> Python's own random default
    outputs = [run_worker(s) for s in seeds_to_try]
    for s, o in zip(seeds_to_try, outputs):
        print(f"  PYTHONHASHSEED={'<unset/random>' if s is None else s} -> {o}")
    reference = outputs[0]
    all_identical = all(o == reference for o in outputs)
    r.check(
        "T1 five fresh-process runs (varying PYTHONHASHSEED, including unset/random) "
        "produce identical match_control() output",
        all_identical,
        f"outputs differed: {outputs}",
    )
    return reference


def _section_2(r: TestResults, reference):
    print("\n=== SECTION 2: matched output is non-trivial (fix didn't degrade matching logic) ===")
    r.check("T2a matched set has exactly one candidate per cohort trader (5)",
            len(reference) == 5, f"got {len(reference)}: {reference}")
    r.check("T2b no cohort trader appears in its own matched-control output",
            not (set(reference) & {"c1", "c2", "c3", "c4", "c5"}),
            f"cohort trader leaked into matches: {reference}")
    r.check("T2c every matched candidate came from the eligible pool",
            all(t.startswith("p") for t in reference),
            f"unexpected trader id in matches: {reference}")
    r.check("T2d no candidate matched twice (greedy 1:1 still holds)",
            len(reference) == len(set(reference)),
            f"duplicate candidate in matches: {reference}")


def _section_3(r: TestResults, reference):
    print("\n=== SECTION 3: additional PYTHONHASHSEED margin ===")
    extra_seeds = [7, 999, 424242]
    outputs = [run_worker(s) for s in extra_seeds]
    for s, o in zip(extra_seeds, outputs):
        print(f"  PYTHONHASHSEED={s} -> {o}")
    r.check(
        "T3 three additional PYTHONHASHSEED values (not used in Section 1) "
        "also match the reference output",
        all(o == reference for o in outputs),
        f"outputs differed from reference {reference}: {outputs}",
    )


def run_tests() -> bool:
    r = TestResults()
    reference = _section_1(r)
    _section_2(r, reference)
    _section_3(r, reference)
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
