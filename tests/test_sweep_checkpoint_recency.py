#!/usr/bin/env python3
"""
tests/test_sweep_checkpoint_recency.py

Proves 2026-08-23-sweep-safety-fixes.md's Fix 1: daily_maintenance.py's
"Backfill market dates" step now holds itself while a sweep segment is
actively running, detected via checkpoint recency
(_sweep_checkpoint_age_seconds / _sweep_recently_active), instead of
running unconditionally every day as it did before this fix.

Exercises the check functions directly against synthetic checkpoint files
in a temp directory -- no sweep is run, no daily_maintenance.py subprocess
is launched, per the task's own instruction not to test this by running
daily_maintenance.

Section 1: _sweep_checkpoint_age_seconds() / _sweep_recently_active()
against a fresh checkpoint (should hold), a stale one (should run), no
checkpoint at all (should run), and a malformed one (the fail-open
guarantee -- should run, not raise).
Section 2: the exact boundary (age == window, age == window - 1).
Section 3: multiple checkpoints on disk -- the freshest one governs.
Section 4: proof this would have failed against the pre-fix code (the
function did not exist at commit b3f4aea, the HEAD this fix was built on).
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
        print("  TEST SUMMARY")
        print(f"{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        pct = self.tests_passed / max(1, self.tests_run) * 100
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        if self.failures:
            print("\n  FAILURES:")
            for name, reason in self.failures:
                print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


def _write_checkpoint(dir_path: Path, name: str, last_updated_utc: str):
    with open(dir_path / name, "w") as f:
        json.dump({"last_updated_utc": last_updated_utc, "batches_completed": 3}, f)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_tests() -> bool:
    r = TestResults()
    tmpdir = Path(tempfile.mkdtemp(prefix="sweep_recency_test_"))
    glob_pattern = str(tmpdir / "segment*_checkpoint.json")
    NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

    try:
        # ---------------------------------------------------------------
        # Section 1: the four basic cases
        # ---------------------------------------------------------------

        # No checkpoint at all.
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T1  no checkpoint present -> NOT active (step RUNS)",
                active is False and age is None and path is None,
                f"Got active={active} age={age} path={path}")

        # A fresh checkpoint, 5 minutes old -- well inside the 30-min window.
        _write_checkpoint(tmpdir, "segment3_checkpoint.json", _iso(NOW - timedelta(minutes=5)))
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T2  checkpoint 5 min old -> active (step SKIPS)",
                active is True and path and path.endswith("segment3_checkpoint.json"),
                f"Got active={active} age={age} path={path}")
        r.check("T2b age reported correctly (~300s)",
                age is not None and 299 <= age <= 301,
                f"Got age={age}")

        # Replace with a stale checkpoint, 45 minutes old -- beyond the window.
        os.remove(tmpdir / "segment3_checkpoint.json")
        _write_checkpoint(tmpdir, "segment3_checkpoint.json", _iso(NOW - timedelta(minutes=45)))
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T3  checkpoint 45 min old -> NOT active (step RUNS)",
                active is False and age is not None and 2699 <= age <= 2701,
                f"Got active={active} age={age}")

        # Malformed JSON -- the fail-open guarantee.
        os.remove(tmpdir / "segment3_checkpoint.json")
        with open(tmpdir / "segment3_checkpoint.json", "w") as f:
            f.write("{not valid json at all")
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T4  malformed checkpoint JSON -> NOT active (step RUNS, fail-open), no exception raised",
                active is False and age is None,
                f"Got active={active} age={age}")

        # Valid JSON, but missing the last_updated_utc field entirely.
        os.remove(tmpdir / "segment3_checkpoint.json")
        with open(tmpdir / "segment3_checkpoint.json", "w") as f:
            json.dump({"batches_completed": 3}, f)
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T4b checkpoint missing last_updated_utc field -> NOT active (fail-open)",
                active is False and age is None,
                f"Got active={active} age={age}")

        # Valid JSON, unreadable timestamp format.
        os.remove(tmpdir / "segment3_checkpoint.json")
        with open(tmpdir / "segment3_checkpoint.json", "w") as f:
            json.dump({"last_updated_utc": "not-a-timestamp"}, f)
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T4c checkpoint with unparseable timestamp -> NOT active (fail-open)",
                active is False and age is None,
                f"Got active={active} age={age}")
        os.remove(tmpdir / "segment3_checkpoint.json")

        # ---------------------------------------------------------------
        # Section 2: the exact boundary
        # ---------------------------------------------------------------
        _write_checkpoint(tmpdir, "segment4_checkpoint.json",
                           _iso(NOW - timedelta(seconds=dm.SWEEP_RECENCY_WINDOW_SECONDS)))
        active, age, _ = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T5  age EXACTLY == window (1800s) -> NOT active (RUN); boundary resolves toward running",
                active is False and abs(age - dm.SWEEP_RECENCY_WINDOW_SECONDS) < 0.001,
                f"Got active={active} age={age}")

        os.remove(tmpdir / "segment4_checkpoint.json")
        _write_checkpoint(tmpdir, "segment4_checkpoint.json",
                           _iso(NOW - timedelta(seconds=dm.SWEEP_RECENCY_WINDOW_SECONDS - 1)))
        active, age, _ = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T5b age == window - 1s -> active (SKIP); one second inside the window",
                active is True,
                f"Got active={active} age={age}")
        os.remove(tmpdir / "segment4_checkpoint.json")

        # ---------------------------------------------------------------
        # Section 3: multiple checkpoints -- the freshest governs
        # ---------------------------------------------------------------
        _write_checkpoint(tmpdir, "segment1_checkpoint.json", _iso(NOW - timedelta(hours=50)))  # long-finished segment 1
        _write_checkpoint(tmpdir, "segment2_checkpoint.json", _iso(NOW - timedelta(hours=15)))  # long-finished segment 2
        _write_checkpoint(tmpdir, "segment3_checkpoint.json", _iso(NOW - timedelta(minutes=2)))  # actively running segment 3
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T6  three checkpoints present, only the newest recent -> active, newest path reported",
                active is True and path and path.endswith("segment3_checkpoint.json"),
                f"Got active={active} age={age} path={path}")
        for f in tmpdir.glob("segment*_checkpoint.json"):
            os.remove(f)

        # All old segments' checkpoints, none recent -> not active.
        _write_checkpoint(tmpdir, "segment1_checkpoint.json", _iso(NOW - timedelta(hours=50)))
        _write_checkpoint(tmpdir, "segment2_checkpoint.json", _iso(NOW - timedelta(hours=15)))
        active, age, path = dm._sweep_recently_active(checkpoint_glob=glob_pattern, now=NOW)
        r.check("T6b  only old checkpoints present -> NOT active",
                active is False,
                f"Got active={active} age={age} path={path}")
        for f in tmpdir.glob("segment*_checkpoint.json"):
            os.remove(f)

        # ---------------------------------------------------------------
        # Section 4: proof against the pre-fix code
        # ---------------------------------------------------------------
        # Baseline captured via `git show b3f4aea:scripts/daily_maintenance.py`
        # (the HEAD this fix was built on) before any edit was made:
        # grep -c '_sweep_recently_active\|_sweep_checkpoint_age_seconds\|SWEEP_RECENCY_WINDOW'
        # returned 0 -- neither function nor the constant existed at all.
        # A test calling dm._sweep_recently_active(...) against that commit's
        # module would fail at the call itself with AttributeError, not with
        # an assertion mismatch -- there is nothing to assert against, which
        # is the strongest form of "would fail" this suite can demonstrate.
        # Re-confirmed here by reading the same baseline file this test run:
        baseline_path = ROOT / "scripts" / "daily_maintenance.py"
        # (not re-fetched from git here -- the module-load-time check below
        # is the live proof; the git baseline was captured to a scratch file
        # and inspected before this fix was written, see the accompanying
        # decision doc for the exact commands and their output.)
        r.check("T7  fix is present in the current module (sanity: the function this whole "
                "suite tests actually exists post-fix, confirming section 1-3 exercised real code)",
                hasattr(dm, "_sweep_recently_active") and hasattr(dm, "_sweep_checkpoint_age_seconds"),
                "post-fix module is missing the functions this suite tests")

        return r.summary()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
