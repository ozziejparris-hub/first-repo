#!/usr/bin/env python3
"""
tests/test_sweep_terminal_signal.py

Proves 2026-08-23-sweep-safety-fixes.md's Fix 2:
data/characterizations/sweep_common/sweep_terminal_signal.py's
write_terminal_marker() and send_telegram_terminal().

Every Telegram-related test in this file monkeypatches
sweep_terminal_signal.asyncio.run so NO real network call is ever made,
regardless of whether real telegram_alerts_token / telegram_chat_id
credentials are present in the environment (they are, on this box) --
this suite must never actually send a message. Restored in a
try/finally around every such test.

Section 1: write_terminal_marker() on a simulated normal completion.
Section 2: write_terminal_marker() on a simulated abort (a threshold
fired, not waited for).
Section 3: an unhandled exception inside a driver-shaped try/except still
produces a marker (simulated, not a real crash).
Section 4: send_telegram_terminal() -- simulated success, simulated
failure (proving the failure does not raise or propagate), and missing
credentials.
Section 5: structural check -- no per-batch call site exists in the
module (send_telegram_terminal is defined once, invoked nowhere inside
the module itself; it's the caller's job to call it once per exit, never
per batch).
Section 6: proof against the pre-fix state -- the module did not exist
at all before this fix.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'data' / 'characterizations' / 'sweep_common'))

import sweep_terminal_signal as sts


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


def run_tests() -> bool:
    r = TestResults()
    tmpdir = Path(tempfile.mkdtemp(prefix="sweep_terminal_test_"))

    try:
        # ---------------------------------------------------------------
        # Section 1: normal completion
        # ---------------------------------------------------------------
        marker_path = tmpdir / "segmentTEST_terminal.json"
        state = sts.write_terminal_marker(
            marker_path,
            status="COMPLETE",
            batches_completed=121,
            n_batches=121,
            cumulative_processed=60500,
            cumulative_tally={"resolved": 59236, "open": 910, "indeterminate": 326, "no_clob_response": 28},
            reason=None,
        )
        r.check("T1  write_terminal_marker returns the state it wrote",
                state["status"] == "COMPLETE" and state["batches_completed"] == 121,
                f"Got {state}")
        r.check("T1b marker file actually exists on disk",
                marker_path.exists(), "marker file missing after write")
        with open(marker_path) as f:
            on_disk = json.load(f)
        r.check("T1c marker on disk matches what was written, byte for byte on the fields that matter",
                on_disk["status"] == "COMPLETE" and on_disk["cumulative_processed"] == 60500
                and on_disk["reason"] is None,
                f"Got {on_disk}")
        r.check("T1d atomic write left no .tmp file behind",
                not marker_path.with_suffix(".json.tmp").exists(),
                "leftover .tmp file found")
        r.check("T1e written_at_utc is present and looks like a timestamp",
                "written_at_utc" in on_disk and on_disk["written_at_utc"].endswith("Z"),
                f"Got {on_disk.get('written_at_utc')}")

        # ---------------------------------------------------------------
        # Section 2: a simulated abort (a threshold fired -- not waited for)
        # ---------------------------------------------------------------
        marker_path.unlink()
        abort_reason = "ABORT CONDITION 3 (cumulative >20%, floor met): cum_indet_rate=23.4% after batch 45"
        state = sts.write_terminal_marker(
            marker_path,
            status="ABORTED",
            batches_completed=45,
            n_batches=985,
            cumulative_processed=22500,
            cumulative_tally={"resolved": 17000, "open": 400, "indeterminate": 4900, "no_clob_response": 200},
            reason=abort_reason,
        )
        r.check("T2  simulated abort marker records status=ABORTED",
                state["status"] == "ABORTED", f"Got {state['status']}")
        r.check("T2b  simulated abort marker records the specific abort reason verbatim",
                state["reason"] == abort_reason, f"Got {state['reason']}")
        r.check("T2c  abort marker is distinguishable from a completion marker by batches_completed < n_batches",
                state["batches_completed"] < state["n_batches"], f"Got {state}")

        # An invalid status is rejected outright, not silently written --
        # a wrong marker is worse than none.
        try:
            sts.write_terminal_marker(marker_path, status="BOGUS", batches_completed=1,
                                       n_batches=1, cumulative_processed=1, cumulative_tally={})
            r.fail("T2d  invalid status is rejected", "no exception raised for status='BOGUS'")
        except ValueError:
            r.ok("T2d  invalid status is rejected (ValueError, not silently written)")

        # ---------------------------------------------------------------
        # Section 3: unhandled exception inside a driver-shaped try/except
        # ---------------------------------------------------------------
        marker_path.unlink()

        def _simulated_driver_body():
            # Stands in for segment2_write.py's batch loop hitting something
            # genuinely unexpected -- not an abort condition, an actual bug
            # or environment failure (e.g. a KeyError from a malformed API
            # response the extraction code didn't anticipate).
            raise KeyError("token.winner")

        exc_marker_written = False
        exc_reraised = False
        try:
            try:
                _simulated_driver_body()
            except Exception as exc:
                sts.write_terminal_marker(
                    marker_path,
                    status="EXCEPTION",
                    batches_completed=12,
                    n_batches=985,
                    cumulative_processed=6000,
                    cumulative_tally={"resolved": 5800, "open": 150, "indeterminate": 45, "no_clob_response": 5},
                    reason=f"{type(exc).__name__}: {exc}",
                )
                exc_marker_written = True
                raise  # a real driver must not swallow the actual error
        except KeyError:
            exc_reraised = True

        r.check("T3  unhandled exception path still writes a marker before propagating",
                exc_marker_written, "marker was not written before the exception propagated")
        r.check("T3b  the exception itself is NOT swallowed -- it still propagates to the caller",
                exc_reraised, "exception was swallowed instead of propagating")
        with open(marker_path) as f:
            exc_state = json.load(f)
        r.check("T3c  exception marker records status=EXCEPTION and the exception's own message",
                exc_state["status"] == "EXCEPTION" and "token.winner" in exc_state["reason"],
                f"Got {exc_state}")

        # ---------------------------------------------------------------
        # Section 4: send_telegram_terminal() -- NEVER a real network call
        # ---------------------------------------------------------------
        real_asyncio_run = sts.asyncio.run

        # 4a/4b need the credential check to pass so control actually
        # reaches asyncio.run (the thing being stubbed) -- this box's real
        # telegram_alerts_token/telegram_chat_id live in /home/parison/.env_trading
        # and are only loaded into os.environ by scripts that call
        # load_dotenv() themselves (as audit_invariants.py's __main__ does);
        # a bare `python3 tests/...` process does not have them set. Using
        # obviously-fake values here, not the real ones, is also simply
        # safer regardless of what happens to be loaded.
        import os as _os

        def _with_fake_creds():
            saved = {k: _os.environ.get(k) for k in ("telegram_alerts_token", "telegram_chat_id")}
            _os.environ["telegram_alerts_token"] = "fake-token-for-test"
            _os.environ["telegram_chat_id"] = "fake-chat-id-for-test"
            return saved

        def _restore_creds(saved):
            for k, v in saved.items():
                if v is None:
                    _os.environ.pop(k, None)
                else:
                    _os.environ[k] = v

        # 4a: simulated success.
        saved_creds = _with_fake_creds()
        sts.asyncio.run = lambda coro: coro.close()  # accept and discard, like a successful send
        try:
            result = sts.send_telegram_terminal("[SWEEP] segmentTEST COMPLETE: 121/121 batches")
            r.check("T4a  simulated successful send returns True, no exception",
                    result is True, f"Got {result}")
        finally:
            sts.asyncio.run = real_asyncio_run
            _restore_creds(saved_creds)

        # 4b: simulated failure (network error, API error, anything) --
        # the function must swallow it and return False, never raise.
        def _raise(coro):
            coro.close()
            raise ConnectionError("simulated network failure -- no real send attempted")
        saved_creds = _with_fake_creds()
        sts.asyncio.run = _raise
        try:
            raised = False
            result = None
            try:
                result = sts.send_telegram_terminal("[SWEEP] segmentTEST ABORTED: condition 3 fired")
            except Exception:
                raised = True
            r.check("T4b  simulated send failure does NOT raise out of send_telegram_terminal",
                    raised is False, "exception propagated out of send_telegram_terminal")
            r.check("T4c  simulated send failure returns False (informational, not fatal)",
                    result is False, f"Got {result}")
        finally:
            sts.asyncio.run = real_asyncio_run
            _restore_creds(saved_creds)

        # 4d: missing credentials -- also must not raise, must not attempt
        # a send at all (belt-and-suspenders: asyncio.run still stubbed to
        # something that would fail loudly if it were ever reached).
        sts.asyncio.run = lambda coro: (_ for _ in ()).throw(
            AssertionError("asyncio.run should not be reached with no credentials"))
        try:
            import os
            saved = {k: os.environ.pop(k, None) for k in ("telegram_alerts_token", "telegram_chat_id")}
            try:
                result = sts.send_telegram_terminal("[SWEEP] should not send")
                r.check("T4d  missing credentials -> returns False, no exception, no send attempted",
                        result is False, f"Got {result}")
            finally:
                for k, v in saved.items():
                    if v is not None:
                        os.environ[k] = v
        finally:
            sts.asyncio.run = real_asyncio_run

        # ---------------------------------------------------------------
        # Section 5: no per-batch call site in the module itself
        # ---------------------------------------------------------------
        module_source = Path(sts.__file__).read_text()
        r.check("T5  send_telegram_terminal is defined exactly once in the module (no duplicate/loop wrapper)",
                module_source.count("def send_telegram_terminal") == 1,
                f"Got {module_source.count('def send_telegram_terminal')} definitions")
        r.check("T5b  the module contains no call to send_telegram_terminal( ) at all -- "
                "it is a library function for a caller to invoke once per exit, "
                "never invoked from inside this module (so certainly never per-batch here)",
                "send_telegram_terminal(" not in module_source.split("def send_telegram_terminal")[1]
                if "def send_telegram_terminal" in module_source else False,
                "found a call to send_telegram_terminal within the module's own body")

        # ---------------------------------------------------------------
        # Section 6: proof against the pre-fix state
        # ---------------------------------------------------------------
        # The module data/characterizations/sweep_common/sweep_terminal_signal.py
        # did not exist at all before this fix (new file, this commit) --
        # `import sweep_terminal_signal` itself would fail with
        # ModuleNotFoundError against any pre-fix checkout, which is the
        # strongest form of "this test would fail against the old code":
        # there is no old code for it to run against.
        r.check("T6  sanity: the module this whole suite tests is actually importable post-fix",
                hasattr(sts, "write_terminal_marker") and hasattr(sts, "send_telegram_terminal"),
                "post-fix module is missing the functions this suite tests")

        return r.summary()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
