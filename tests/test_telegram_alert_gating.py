#!/usr/bin/env python3
"""
tests/test_telegram_alert_gating.py

Proves the 2026-09-07 Telegram-remediation gating fixes (see
brain/decisions/2026-09-07-telegram-remediation.md, trading-swarm repo):

Section 1: SystemObserver._should_send_hourly_report -- the hourly report's
"HEALTHY hours are silent" gate, fixed after it was found to always fire
(it checked metrics["status"], a key _collect_metrics() never sets; the
real key is "health_status"). Negative control: a healthy cycle with no
errors must NOT send.

Section 2: SystemObserver._diagnostic_signature / _should_send_diagnostic_report
-- the 6-hourly diagnostic report's new change-detection gate. Covers
numeric-normalization (a growing DB size shouldn't look "changed"),
first-ever-run behaviour, an unchanged CRITICAL set (must suppress -- this
is the ~228-cycles-of-noise case), a newly-appearing issue (must send), and
a non-CRITICAL cycle (must never send regardless of change).

Section 3: check_canonical_definitions.py's violation_signature /
should_alert -- the same discipline applied to the canonical-drift check's
now-working alert (Part 3: added load_dotenv, so it actually reaches
Telegram; this section proves it won't re-send the same 7 violations
identically forever).

Exercises the functions directly -- no live Telegram send, no subprocess,
no daily_maintenance run.
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

    # -----------------------------------------------------------------
    # Section 2: diagnostic report change-detection
    # -----------------------------------------------------------------

    r.check(
        "T2a _normalize_finding strips numeric tokens",
        SO._normalize_finding("Database very large: 19742 MB") == "Database very large: # MB",
    )

    critical_report_v1 = {
        "overall_status": "CRITICAL",
        "issues": ["[ANALYSIS_TOOLS] ELO Integration: File missing at scripts/integrate_behavioral_elo.py"],
        "warnings": ["[DATABASE] Database very large: 19742 MB", "[DATA_QUALITY] Last trade 1.6h ago"],
    }
    critical_report_v2_grown = {
        "overall_status": "CRITICAL",
        "issues": ["[ANALYSIS_TOOLS] ELO Integration: File missing at scripts/integrate_behavioral_elo.py"],
        "warnings": ["[DATABASE] Database very large: 19758 MB", "[DATA_QUALITY] Last trade 1.8h ago"],
    }
    sig_v1 = SO._diagnostic_signature(critical_report_v1)
    sig_v2 = SO._diagnostic_signature(critical_report_v2_grown)

    r.check(
        "T2b a drifting DB-size / hours-since-trade number does NOT count as a changed signature",
        sig_v1 == sig_v2,
        f"sig_v1={sig_v1} sig_v2={sig_v2}",
    )
    r.check(
        "T2c first-ever run (no persisted state), CRITICAL -> send",
        SO._should_send_diagnostic_report("CRITICAL", sig_v1, None) is True,
    )
    r.check(
        "T2d NEGATIVE CONTROL: identical finding set repeats, CRITICAL -> NO send "
        "(this is the real-world case that fired ~228 times over 8 weeks pre-fix)",
        SO._should_send_diagnostic_report("CRITICAL", sig_v2, sig_v1) is False,
    )

    report_with_new_issue = dict(critical_report_v2_grown)
    report_with_new_issue["issues"] = critical_report_v2_grown["issues"] + [
        "[DATABASE] Database is LOCKED (another process accessing it)"
    ]
    sig_new_issue = SO._diagnostic_signature(report_with_new_issue)
    r.check(
        "T2e a genuinely NEW issue appears -> send",
        SO._should_send_diagnostic_report("CRITICAL", sig_new_issue, sig_v1) is True,
    )

    resolved_report = {"overall_status": "CRITICAL",
                        "issues": ["[DATABASE] Database is LOCKED (another process accessing it)"],
                        "warnings": critical_report_v1["warnings"]}
    sig_resolved = SO._diagnostic_signature(resolved_report)
    r.check(
        "T2f a previously-reported issue clearing (while another remains CRITICAL) counts as changed -> send",
        SO._should_send_diagnostic_report("CRITICAL", sig_resolved, sig_v1) is True,
    )

    warning_only = {"overall_status": "WARNING", "issues": [], "warnings": critical_report_v1["warnings"]}
    sig_warning_only = SO._diagnostic_signature(warning_only)
    r.check(
        "T2g NEGATIVE CONTROL: WARNING (not CRITICAL), brand-new set, no persisted state -> NO send",
        SO._should_send_diagnostic_report("WARNING", sig_warning_only, None) is False,
    )
    r.check(
        "T2h NEGATIVE CONTROL: HEALTHY, empty set -> NO send",
        SO._should_send_diagnostic_report("HEALTHY", {"issues": [], "warnings": []}, None) is False,
    )

    # -----------------------------------------------------------------
    # Section 3: check_canonical_definitions.py's alert change-detection
    # -----------------------------------------------------------------

    import check_canonical_definitions as ccd

    v1 = [(Path("scripts/trader_skill_metric_v2.py"), 390, "SQL string contains `geo_elo >= 2175`")]
    v1_line_shifted = [(Path("scripts/trader_skill_metric_v2.py"), 999, "SQL string contains `geo_elo >= 2175`")]
    csig1 = ccd.violation_signature(v1)
    csig1_shifted = ccd.violation_signature(v1_line_shifted)

    r.check(
        "T3a violation_signature ignores line number (a same finding whose line "
        "moved due to an unrelated edit is not a 'new' finding)",
        csig1 == csig1_shifted,
    )
    r.check(
        "T3b first-ever run (no persisted state), violations present -> alert",
        ccd.should_alert(csig1, None) is True,
    )
    r.check(
        "T3c NEGATIVE CONTROL: identical violation set repeats -> NO alert "
        "(this is the real-world 7-violations-x-11-weeks case)",
        ccd.should_alert(csig1_shifted, csig1) is False,
    )

    v2_new = v1 + [(Path("scripts/some_new_file.py"), 10, "a brand new violation")]
    csig2 = ccd.violation_signature(v2_new)
    r.check(
        "T3d a NEW violation appears -> alert",
        ccd.should_alert(csig2, csig1) is True,
    )
    r.check(
        "T3e NEGATIVE CONTROL: zero violations -> NO alert",
        ccd.should_alert([], None) is False,
    )
    r.check(
        "T3f a violation clearing (7 -> 6) counts as changed -> alert",
        ccd.should_alert(ccd.violation_signature(v1), csig2) is True,
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
