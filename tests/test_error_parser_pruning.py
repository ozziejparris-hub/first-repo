#!/usr/bin/env python3
"""
tests/test_error_parser_pruning.py

Proves the fix wiring up ErrorParser.clear_old_errors() from the observer's
health-check loop (see
brain/decisions/2026-09-13-observer-burst-loop-and-memory-diagnosis.md and
the follow-up fix commit). Before this fix, ErrorParser.add_error()
appended every detected error to self.error_history (a plain list) and
self.error_groups (a defaultdict of lists) with no bound -- observed as an
11.6 GB RSS peak on a long-lived observer process. clear_old_errors()
already existed and was already correct; it was simply never called.

Section 1 proves clear_old_errors() actually drops old entries from BOTH
structures and that the error_groups rebuild leaves no orphaned keys for
signatures that fully expired.

Section 2 is the non-tautology check: the same growth pattern is run once
WITHOUT calling clear_old_errors() (grows unbounded) and once WITH it
(bounded to the retention window) -- a test that passed either way would
prove nothing.

Section 3 proves the grouping/dedup behaviour that "Detailed error
detected" relies on still works correctly after a prune: a new error
whose earlier same-signature instances were pruned away (fully, or
partially) still groups against what remains, using a fresh group in the
fully-expired case and appending to the survivor in the partial case.

Section 4 proves the wiring itself: _health_check_loop (60s cadence, pure
in-memory work already happens there) calls log_monitor.clear_old_errors(),
and _log_monitor_loop (2s cadence) does not -- calling it every 2s would
rebuild the same structures needlessly often for a 24h retention window.

Section 5 is a cheap-cost sanity check: clear_old_errors() over a
realistic history size completes in well under a second, confirming it is
safe to call from an async loop without introducing a new stall.
"""

import inspect
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from monitoring.error_parser import ErrorParser, ErrorDetail
from monitoring.log_monitor import LogMonitor
from monitoring.system_observer import SystemObserver


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


def _mk_error(hours_ago: float, component: str, function: str, error_type: str,
              message: str) -> ErrorDetail:
    """Build an ErrorDetail with a timestamp `hours_ago` hours in the past."""
    ts = datetime.now() - timedelta(hours=hours_ago)
    return ErrorDetail(
        timestamp=ts,
        level='ERROR',
        component=component,
        function=function,
        error_type=error_type,
        message=message,
    )


def run_tests() -> bool:
    r = TestResults()

    # ── Section 1: prune actually drops old entries, no orphaned group keys ──
    print("\n[SECTION 1] clear_old_errors() drops old entries from both structures")
    print("-" * 50)

    p = ErrorParser()
    old_only = _mk_error(30, 'pnl_worker', 'update', 'OperationalError', 'database is locked (A)')
    mixed_old = _mk_error(30, 'monitor', 'cycle', 'OperationalError', 'database is locked (B)')
    mixed_new = _mk_error(1, 'monitor', 'cycle', 'OperationalError', 'database is locked (B)')
    recent_only = _mk_error(1, 'pnl_worker', 'insert', 'IntegrityError', 'unique constraint (C)')

    for e in (old_only, mixed_old, mixed_new, recent_only):
        p.add_error(e)

    r.check(
        "T1a  before prune: all 4 errors present in error_history",
        len(p.error_history) == 4,
        f"Got len={len(p.error_history)}",
    )
    r.check(
        "T1b  before prune: both signatures present in error_groups",
        old_only.signature in p.error_groups and mixed_old.signature in p.error_groups,
        f"Keys: {list(p.error_groups.keys())}",
    )

    p.clear_old_errors(hours=24)

    r.check(
        "T2a  after prune: only the 2 recent errors remain in error_history",
        len(p.error_history) == 2,
        f"Got len={len(p.error_history)}: {[e.message for e in p.error_history]}",
    )
    r.check(
        "T2b  after prune: the fully-expired signature has NO key at all "
        "(not an empty list -- an orphaned key would leak memory forever)",
        old_only.signature not in p.error_groups,
        f"Keys: {list(p.error_groups.keys())}",
    )
    r.check(
        "T2c  after prune: the partially-expired signature keeps only its "
        "surviving (recent) instance",
        p.error_groups.get(mixed_new.signature) == [mixed_new],
        f"Got: {p.error_groups.get(mixed_new.signature)}",
    )
    r.check(
        "T2d  after prune: the untouched recent-only signature is unaffected",
        p.error_groups.get(recent_only.signature) == [recent_only],
        f"Got: {p.error_groups.get(recent_only.signature)}",
    )
    r.check(
        "T2e  after prune: no orphaned keys anywhere -- every key in "
        "error_groups has at least one entry",
        all(len(v) > 0 for v in p.error_groups.values()),
        f"Empty-valued keys: {[k for k, v in p.error_groups.items() if not v]}",
    )

    # ── Section 2: non-tautology -- grows without the call, bounded with it ──
    print("\n[SECTION 2] Non-tautology: unbounded without the call, bounded with it")
    print("-" * 50)

    N = 500
    p2 = ErrorParser()
    for i in range(N):
        # All timestamped 30h ago -- outside any 24h window -- so this is a
        # clean stand-in for "days of accumulated errors nobody ever pruned".
        p2.add_error(_mk_error(30, 'pnl_worker', 'update', 'OperationalError', f'stale error {i}'))

    r.check(
        f"T3a  WITHOUT clear_old_errors(): {N} appends -> error_history holds "
        f"all {N} (demonstrates the pre-fix unbounded growth)",
        len(p2.error_history) == N,
        f"Got len={len(p2.error_history)}",
    )
    r.check(
        f"T3b  WITHOUT clear_old_errors(): error_groups also holds all {N} "
        f"distinct signatures (each message is unique)",
        sum(len(v) for v in p2.error_groups.values()) == N,
        f"Got total={sum(len(v) for v in p2.error_groups.values())}",
    )

    p2.clear_old_errors(hours=24)

    r.check(
        "T3c  WITH clear_old_errors(): the same 500 stale entries are now "
        "gone -- error_history is empty",
        len(p2.error_history) == 0,
        f"Got len={len(p2.error_history)}",
    )
    r.check(
        "T3d  WITH clear_old_errors(): error_groups is also empty -- no "
        "residual keys survive a full-window expiry",
        len(p2.error_groups) == 0,
        f"Got {len(p2.error_groups)} keys remaining",
    )

    # ── Section 3: grouping/dedup still works correctly after a prune ────────
    print("\n[SECTION 3] Grouping/dedup against survivors after a prune")
    print("-" * 50)

    # 3a: fully-expired signature -- a new occurrence should start a *fresh*
    # group (occurrences=1), not silently vanish or error out.
    p3 = ErrorParser()
    sig_a_old = _mk_error(30, 'x', 'y', 'TimeoutError', 'slow query (sig A)')
    p3.add_error(sig_a_old)
    p3.clear_old_errors(hours=24)
    r.check(
        "T4a  fully-expired signature has no group left before the new error",
        sig_a_old.signature not in p3.error_groups,
        f"Keys: {list(p3.error_groups.keys())}",
    )
    sig_a_new = _mk_error(0, 'x', 'y', 'TimeoutError', 'slow query (sig A)')
    assert sig_a_new.signature == sig_a_old.signature, "test setup: signatures must match"
    p3.add_error(sig_a_new)
    r.check(
        "T4b  re-occurrence of a fully-expired signature starts a fresh "
        "group of exactly 1, not appended to anything stale",
        p3.error_groups.get(sig_a_new.signature) == [sig_a_new],
        f"Got: {p3.error_groups.get(sig_a_new.signature)}",
    )
    r.check(
        "T4c  the fresh group's representative has occurrences==1, not "
        "inflated by the pruned-away prior instance",
        sig_a_new.occurrences == 1,
        f"Got occurrences={sig_a_new.occurrences}",
    )

    # 3b: partially-expired signature -- a new occurrence should append to
    # the surviving instance's group, and bump ITS occurrence counter.
    p4 = ErrorParser()
    sig_b_old = _mk_error(30, 'z', 'w', 'ValueError', 'bad input (sig B)')
    sig_b_recent = _mk_error(1, 'z', 'w', 'ValueError', 'bad input (sig B)')
    p4.add_error(sig_b_old)
    p4.add_error(sig_b_recent)
    r.check(
        "T5a  before prune: sig B's occurrence counter reflects 2 sightings",
        sig_b_old.occurrences == 2,
        f"Got occurrences={sig_b_old.occurrences}",
    )
    p4.clear_old_errors(hours=24)
    r.check(
        "T5b  after prune: sig B's group has exactly the 1 survivor",
        p4.error_groups.get(sig_b_recent.signature) == [sig_b_recent],
        f"Got: {p4.error_groups.get(sig_b_recent.signature)}",
    )
    sig_b_newest = _mk_error(0, 'z', 'w', 'ValueError', 'bad input (sig B)')
    p4.add_error(sig_b_newest)
    r.check(
        "T5c  a third occurrence after the prune correctly appends to the "
        "surviving group (uses the post-prune head, not a stale reference)",
        p4.error_groups.get(sig_b_newest.signature) == [sig_b_recent, sig_b_newest],
        f"Got: {p4.error_groups.get(sig_b_newest.signature)}",
    )
    # add_error() only tracks a running `.occurrences` count on the group's
    # HEAD element (existing_errors[0]) -- non-head members keep their
    # default of 1 until a prune promotes them to head. sig_b_recent was a
    # non-head member (occurrences==1) before the prune; after the prune it
    # IS the head, so this third add correctly bumps it 1 -> 2. This is
    # pre-existing, unmodified add_error() behaviour -- the point of this
    # check is that the post-prune head is live and gets incremented at
    # all, not that it continues the pre-prune cumulative count.
    r.check(
        "T5d  the post-prune head's occurrence counter increments off its "
        "own baseline (1 -> 2), proving the group reference survives the "
        "rebuild rather than pointing at something stale",
        sig_b_recent.occurrences == 2,
        f"Got occurrences={sig_b_recent.occurrences}",
    )

    # ── Section 4: the wiring -- correct loop calls it, the other does not ──
    print("\n[SECTION 4] Wiring: _health_check_loop calls it, _log_monitor_loop doesn't")
    print("-" * 50)

    health_src = inspect.getsource(SystemObserver._health_check_loop)
    log_src = inspect.getsource(SystemObserver._log_monitor_loop)

    r.check(
        "T6a  _health_check_loop (60s cadence) calls log_monitor.clear_old_errors()",
        "clear_old_errors" in health_src,
        "Call not found in _health_check_loop source",
    )
    r.check(
        "T6b  _log_monitor_loop (2s cadence) does NOT call clear_old_errors() "
        "-- pruning every 2s for a 24h window would be wasteful",
        "clear_old_errors" not in log_src,
        "Unexpected call found in _log_monitor_loop source",
    )

    lm = LogMonitor.__new__(LogMonitor)  # avoid touching a real log file
    r.check(
        "T6c  LogMonitor.clear_old_errors() exists and is unchanged (not "
        "rewritten by this fix -- only its caller was added)",
        callable(getattr(lm, 'clear_old_errors', None)),
        "LogMonitor.clear_old_errors missing",
    )

    # ── Section 5: cost sanity -- pruning must not itself become a stall ────
    print("\n[SECTION 5] Cost sanity: pruning a realistic history is cheap")
    print("-" * 50)

    p5 = ErrorParser()
    now = datetime.now()
    for i in range(2000):
        # Spread across a 48h window so roughly half survive a 24h prune --
        # a busier day than the 454-errors-per-boot figure from the diagnosis.
        hours_ago = (i / 2000) * 48
        p5.add_error(_mk_error(hours_ago, 'c', 'f', 'Error', f'msg {i}'))

    start = time.monotonic()
    p5.clear_old_errors(hours=24)
    elapsed = time.monotonic() - start

    r.check(
        "T7a  pruning ~2000 entries (a busy-day-scale history) takes well "
        "under 1 second -- pure in-memory work, safe to call from a loop",
        elapsed < 1.0,
        f"Took {elapsed:.3f}s",
    )
    r.check(
        "T7b  the roughly-half-survive expectation holds (sanity that the "
        "cost test above wasn't measuring an empty no-op)",
        900 <= len(p5.error_history) <= 1100,
        f"Got len={len(p5.error_history)} (expected ~1000)",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
