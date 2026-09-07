#!/usr/bin/env python3
"""
tests/test_telegram_alert_gating.py

Proves the 2026-09-07 Telegram-remediation hourly-report gating fix (see
brain/decisions/2026-09-07-telegram-remediation.md, trading-swarm repo):

SystemObserver._should_send_hourly_report -- the hourly report's "HEALTHY
hours are silent" gate, fixed after it was found to always fire (it checked
metrics["status"], a key _collect_metrics() never sets; the real key is
"health_status"). Negative control: a healthy cycle with no errors must NOT
send.

NOTE (2026-09-07, failure-age tracking): the diagnostic-report and
canonical-drift change-detection gates that used to be tested here as
Sections 2 and 3 were replaced by monitoring/failure_age.py (per-finding
first_seen + accepted-failures register). Their coverage now lives in
tests/test_failure_age_tracking.py. See
brain/decisions/2026-09-07-failure-age-tracking.md.

Exercises the function directly -- no live Telegram send, no subprocess.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


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

    from monitoring.system_observer import SystemObserver as SO

    # -----------------------------------------------------------------
    # Section 1: hourly report gate
    # -----------------------------------------------------------------

    r.check(
        "T1a NEGATIVE CONTROL: healthy cycle, no errors -> NO send",
        SO._should_send_hourly_report({"health_status": "healthy", "error_count": 0}) is False,
    )
    r.check(
        "T1b healthy cycle but errors present -> send",
        SO._should_send_hourly_report({"health_status": "healthy", "error_count": 3}) is True,
    )
    r.check(
        "T1c warning cycle, no errors -> send",
        SO._should_send_hourly_report({"health_status": "warning", "error_count": 0}) is True,
    )
    r.check(
        "T1d critical cycle -> send",
        SO._should_send_hourly_report({"health_status": "critical", "error_count": 0}) is True,
    )
    r.check(
        "T1e missing health_status key entirely -> send (fail-open, not silently swallowed)",
        SO._should_send_hourly_report({"error_count": 0}) is True,
    )
    r.check(
        "T1f OLD-BUG REGRESSION GUARD: a stray 'status' key (the wrong name the "
        "bug used to read) must NOT influence the gate -- only 'health_status' matters",
        SO._should_send_hourly_report({"status": "critical", "health_status": "healthy", "error_count": 0}) is False,
    )

    # _normalize_finding is still the diagnostic report's finding-key builder
    # (now feeding monitoring/failure_age.py). Kept here as a fast structural
    # check; the gating behaviour it feeds is covered in
    # tests/test_failure_age_tracking.py.
    r.check(
        "T1g _normalize_finding strips numeric tokens (stable finding key)",
        SO._normalize_finding("Database very large: 19742 MB") == "Database very large: # MB",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
