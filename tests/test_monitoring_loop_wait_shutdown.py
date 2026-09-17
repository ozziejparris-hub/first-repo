#!/usr/bin/env python3
"""
tests/test_monitoring_loop_wait_shutdown.py

Proves the fix for monitoring_loop()'s cycle-wait, found in the 2026-09-17
diagnosis (trading-swarm
brain/decisions/2026-09-17-oos-hash-methodology-and-cycle-compounding.md)
and fixed the same day (companion decision doc for this fix).

Root cause: the cycle-wait was `for _ in range(check_interval): await
asyncio.sleep(1)` -- 900 separate event-loop wakeups at the default
900s check_interval, each a chance to be delayed by the two continuously
running background workers (pnl_worker, backfill_worker). The watchdog's
heartbeat, `await asyncio.sleep(300)` -- a SINGLE wakeup -- held perfectly
all night under the identical contention. That contrast was the
diagnosis's strongest evidence for starvation of the many-round-trip wait
specifically.

The fix (PolymarketMonitor._wait_for_next_cycle(), extracted from
monitoring_loop() so it's testable without constructing a full
PolymarketMonitor -- whose __init__ unconditionally opens the production
DB) replaces the loop with a single `asyncio.wait_for(self._stop_event.wait(),
timeout=check_interval)`. This preserves exactly one property the old loop
had that a bare `asyncio.sleep(check_interval)` would NOT: prompt reaction
to a stop request. request_stop() and stop() both now call
self._stop_event.set() in addition to setting self.is_running = False.

Section 1 confirms the wait is structurally a single await (no
range()/loop), by source inspection -- distinguishing "a single sleep"
from "a loop that happens to look short in a diff". Section 2 proves the
normal case: with no stop request, the wait blocks for the full
check_interval (using a small test-scale interval, not the production
900s). Section 3 is the one this task named as most important: it starts
the wait with a LARGE check_interval (so a bare sleep(check_interval)
would hang the test), triggers a stop mid-wait exactly as request_stop()
and stop() do, and asserts the wait ends in well under a second --
proving the starvation fix was not traded for a shutdown hang. Section 4
repeats Section 3 for stop() specifically (async, used at process
shutdown in monitoring/main_telegram_safe.py's finally block), not just
request_stop().
"""

import asyncio
import inspect
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from monitoring import monitor as monitor_module

PolymarketMonitor = monitor_module.PolymarketMonitor


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


def _bare_monitor(check_interval):
    """
    A PolymarketMonitor with only the attributes _wait_for_next_cycle(),
    request_stop(), and stop() actually touch -- built via __new__ to
    skip __init__ entirely, since __init__ unconditionally opens the
    production DB (Database() with no path override) and constructs
    live network/worker objects neither of those methods need.
    """
    m = PolymarketMonitor.__new__(PolymarketMonitor)
    m.check_interval = check_interval
    m.is_running = True
    m._stop_event = asyncio.Event()
    # stop() also touches these two if present; leave them absent to prove
    # the hasattr() guards in stop() are exercised, matching production
    # (both are always set in __init__ there).
    return m


def run_tests() -> bool:
    r = TestResults()

    # ── Section 1: the wait is structurally a single await ─────────────────
    print("\n[SECTION 1] The cycle-wait is a single await, not a loop")
    print("-" * 50)

    src = inspect.getsource(PolymarketMonitor._wait_for_next_cycle)
    # Strip the docstring (it quotes the OLD `range(...)` pattern by name,
    # in backticks, to explain what this replaced) so these assertions
    # check the executable code, not the prose describing it. The
    # docstring is the first `"""..."""` block in the function source;
    # slicing after its closing `"""` leaves only executable code.
    first_quote = src.index('"""')
    second_quote = src.index('"""', first_quote + 3) + 3
    code_only = src[second_quote:]

    r.check(
        "T1a  no range()-based polling loop remains in the executable code",
        "range(" not in code_only,
        "a range() loop is still present in _wait_for_next_cycle()'s code",
    )
    r.check(
        "T1b  exactly one asyncio.wait_for(...) call site in the executable code",
        code_only.count("asyncio.wait_for(") == 1,
        f"found {code_only.count('asyncio.wait_for(')} call sites",
    )
    r.check(
        "T1c  waits on the stop event, timeout is check_interval",
        "self._stop_event.wait()" in code_only and "timeout=self.check_interval" in code_only,
        "does not wait on _stop_event with check_interval as the timeout",
    )
    loop_src = inspect.getsource(PolymarketMonitor.monitoring_loop)
    r.check(
        "T1d  monitoring_loop() itself no longer contains the old "
        "`for _ in range(self.check_interval)` pattern",
        "for _ in range(self.check_interval)" not in loop_src,
        "old polling loop pattern still present in monitoring_loop()",
    )

    # ── Section 2: normal case -- no stop request, waits the full interval ──
    print("\n[SECTION 2] Normal case: no stop request, wait lasts ~check_interval")
    print("-" * 50)

    async def _normal_case():
        m = _bare_monitor(check_interval=0.2)  # test-scale, not production 900s
        t0 = time.monotonic()
        await m._wait_for_next_cycle()
        return time.monotonic() - t0

    elapsed = asyncio.run(_normal_case())
    r.check(
        "T2a  wait lasts approximately check_interval (0.2s) when nothing "
        "requests a stop",
        0.18 <= elapsed <= 1.0,
        f"elapsed={elapsed:.3f}s, expected ~0.2s",
    )

    # ── Section 3: request_stop() ends the wait promptly, even mid-wait ────
    print("\n[SECTION 3] request_stop() mid-wait ends it promptly (THE shutdown test)")
    print("-" * 50)

    async def _stop_mid_wait(interval, delay, stopper):
        m = _bare_monitor(check_interval=interval)
        t0 = time.monotonic()
        wait_task = asyncio.create_task(m._wait_for_next_cycle())
        await asyncio.sleep(delay)
        stopper(m)
        await wait_task
        return time.monotonic() - t0, m.is_running

    # check_interval=300s -- a bare `asyncio.sleep(check_interval)` here
    # would hang this test for 5 minutes. If the fix regressed to that,
    # this assertion fails loudly rather than the test just running slow.
    elapsed3, is_running3 = asyncio.run(
        _stop_mid_wait(300, 0.05, lambda m: m.request_stop())
    )
    r.check(
        "T3a  request_stop() called 0.05s into a 300s wait ends the wait "
        "in well under 1s, not anywhere near 300s -- this is the property "
        "the old 900-round-trip loop had that a bare sleep(check_interval) "
        "would NOT: no shutdown hang traded for the starvation fix",
        elapsed3 < 1.0,
        f"elapsed={elapsed3:.3f}s (expected << 300s, budget < 1.0s)",
    )
    r.check("T3b  is_running is False after request_stop()",
            is_running3 is False, f"is_running={is_running3}")

    # ── Section 4: async stop() (the actual shutdown-path caller) ───────────
    print("\n[SECTION 4] stop() (async, used at process shutdown) ends the wait promptly")
    print("-" * 50)

    async def _stop_mid_wait_async(interval, delay):
        m = _bare_monitor(check_interval=interval)
        # stop() also touches these if present (see monitor.py); the
        # hasattr() guards there mean their absence here is fine, but set
        # them to mirror the real object's shape as closely as this
        # lightweight fixture reasonably can.
        t0 = time.monotonic()
        wait_task = asyncio.create_task(m._wait_for_next_cycle())
        await asyncio.sleep(delay)
        await m.stop()
        await wait_task
        return time.monotonic() - t0, m.is_running

    elapsed4, is_running4 = asyncio.run(_stop_mid_wait_async(300, 0.05))
    r.check(
        "T4a  stop() called 0.05s into a 300s wait ends the wait in well "
        "under 1s -- the exact path monitoring/main_telegram_safe.py's "
        "finally block exercises at process shutdown",
        elapsed4 < 1.0,
        f"elapsed={elapsed4:.3f}s (expected << 300s, budget < 1.0s)",
    )
    r.check("T4b  is_running is False after stop()",
            is_running4 is False, f"is_running={is_running4}")

    # ── Section 5: no stop at all still respects the full timeout (no false wake) ─
    print("\n[SECTION 5] Sanity: an unrelated event does not wake the wait early")
    print("-" * 50)

    async def _unrelated_event_does_not_wake():
        m = _bare_monitor(check_interval=0.3)
        other_event = asyncio.Event()
        t0 = time.monotonic()
        wait_task = asyncio.create_task(m._wait_for_next_cycle())
        await asyncio.sleep(0.05)
        other_event.set()  # not m._stop_event -- must not affect the wait
        await wait_task
        return time.monotonic() - t0

    elapsed5 = asyncio.run(_unrelated_event_does_not_wake())
    r.check(
        "T5a  setting an unrelated asyncio.Event does not wake the wait "
        "early -- only this monitor's own _stop_event does",
        elapsed5 >= 0.28,
        f"elapsed={elapsed5:.3f}s, expected ~0.3s (woke early)",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
