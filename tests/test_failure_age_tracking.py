#!/usr/bin/env python3
"""
tests/test_failure_age_tracking.py

Proves the 2026-09-07 failure-age tracking + accepted-failures register
(monitoring/failure_age.py, wired into scripts/check_canonical_definitions.py
and monitoring/system_observer.py). See
brain/decisions/2026-09-07-failure-age-tracking.md.

Covers, per the task's reproducibility list:
  - a new finding alerts
  - an unchanged (already-reported) finding does not
  - a registered finding does not
  - a registered finding past its review date does
  - age is computed correctly across a simulated restart (file round-trip)
  - a corrupt state file degrades safely

plus: missing-file degradation, pre-age-schema migration (no invented history),
a finding that disappears and returns (fresh first_seen, not resurrected),
resolved-finding messaging, the "nothing to report -> no message" rule, the
15-line cap, diagnostic warnings tracked-but-not-alertable, register robustness,
line-number-independent keys, and that nothing ever writes to the register.

Exercises the functions directly -- no live Telegram send, no subprocess.
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from monitoring import failure_age as fa  # noqa: E402


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
        if cond:
            self.ok(name)
        else:
            self.fail(name, reason or "condition was False")

    def summary(self):
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


T0 = datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
NO_REGISTER = {"entries": {}}


def _cycle(state, keys, now, register=NO_REGISTER, alertable=None):
    """One reconcile+evaluate+render pass. Returns (new_state, classification, decision, message)."""
    new_state, cls = fa.reconcile(state, keys, now)
    decision = fa.evaluate(cls, register, new_state, now, alertable_keys=alertable)
    msg = fa.render_message("test check", decision, new_state, now, "/tmp/x.json")
    return new_state, cls, decision, msg


def run_tests():
    r = TestResults()

    # ---------------------------------------------------------------
    # 1. a NEW finding alerts; an UNCHANGED (reported) finding does not
    # ---------------------------------------------------------------
    st0 = fa._empty_state("ok")  # a good, empty prior state -> genuinely new
    st1, _, dec1, msg1 = _cycle(st0, ["c::f.py::hardcoded X"], T0)
    r.check("1a a new finding is classified new and produces a message",
            dec1.report_new == ["c::f.py::hardcoded X"] and msg1 is not None)
    r.check("1b the new-finding message leads with '! NEW'",
            "! NEW" in msg1 and "f.py" in msg1, msg1)

    fa.mark_reported(st1, dec1, T0)  # Oscar has now seen it
    now1 = T0 + timedelta(days=1)
    st2, _, dec2, msg2 = _cycle(st1, ["c::f.py::hardcoded X"], now1)
    r.check("1c NEGATIVE CONTROL: same finding next run, already reported -> NO message",
            msg2 is None and dec2.report_new == [] and dec2.should_send is False)
    r.check("1d the finding's age is now tracked (first_seen preserved)",
            fa.age_days(st2["findings"]["c::f.py::hardcoded X"]["first_seen_utc"], now1) == 1)

    # ---------------------------------------------------------------
    # 2. a REGISTERED finding does not alert; PAST its review date it does
    # ---------------------------------------------------------------
    key = "c::legacy.py::accepted thing"
    reg_current = {"entries": {key: {
        "finding_key": key, "accepted_by": "Oscar", "accepted_on": "2026-09-07",
        "reason": "known, scheduled", "review_by": "2026-12-01"}}}
    stA = fa._empty_state("ok")
    stA1, _, decA1, msgA1 = _cycle(stA, [key], T0, register=reg_current)
    r.check("2a a finding accepted in the register (in review window) -> NO message",
            msgA1 is None and decA1.report_new == [] and decA1.review_due == [])

    reg_expired = {"entries": {key: {
        "finding_key": key, "accepted_by": "Oscar", "accepted_on": "2026-06-01",
        "reason": "known", "review_by": "2026-09-01"}}}  # review_by in the past vs T0
    stB1, _, decB1, msgB1 = _cycle(stA, [key], T0, register=reg_expired)
    r.check("2b same finding, register entry PAST review_by -> review-due message",
            msgB1 is not None and decB1.review_due == [key] and decB1.report_new == [])
    r.check("2c the review-due line is distinct from a new-failure line",
            "review due" in msgB1 and "! NEW" not in msgB1, msgB1)

    fa.mark_reported(stB1, decB1, T0)
    stB2, _, decB2, msgB2 = _cycle(stB1, [key], T0 + timedelta(hours=6), register=reg_expired)
    r.check("2d review-due re-alert is gated to once per calendar day",
            msgB2 is None and decB2.review_due == [])
    stB3, _, decB3, msgB3 = _cycle(stB1, [key], T0 + timedelta(days=1), register=reg_expired)
    r.check("2e review-due re-alerts again the next day (still unresolved, still past review)",
            msgB3 is not None and decB3.review_due == [key])

    # ---------------------------------------------------------------
    # 3. age computed correctly ACROSS A SIMULATED RESTART (file round-trip)
    # ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / ".state.json"
        # run 1: finding first seen at T0
        s_a, _ = fa.reconcile(fa.load_state(sp), ["c::x.py::old bug"], T0)
        fa.save_state(sp, s_a, T0, check="canonical_definitions")
        # ... 30 days pass, process restarts: only the FILE persists ...
        reloaded = fa.load_state(sp)
        r.check("3a state survives a restart (prior_state_status == 'ok' on reload)",
                reloaded["prior_state_status"] == "ok"
                and "c::x.py::old bug" in reloaded["findings"])
        now30 = T0 + timedelta(days=30)
        s_b, cls_b = fa.reconcile(reloaded, ["c::x.py::old bug"], now30)
        age = fa.age_days(s_b["findings"]["c::x.py::old bug"]["first_seen_utc"], now30)
        r.check("3b age is computed from first_seen (30d), NOT from file mtime",
                age == 30 and "c::x.py::old bug" in cls_b["ongoing"])

    # ---------------------------------------------------------------
    # 4. a CORRUPT state file degrades safely
    # ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / ".state.json"
        sp.write_text("{ this is not valid json ")
        st = fa.load_state(sp)
        r.check("4a corrupt file -> prior_state_status 'corrupt', empty findings, no raise",
                st["prior_state_status"] == "corrupt" and st["findings"] == {})
        quarantined = list(Path(d).glob(".state.json.corrupt-*"))
        r.check("4b the corrupt file is quarantined (copied aside) before overwrite",
                len(quarantined) == 1)
        s2, cls2, dec2, msg = _cycle(st, ["c::y.py::z"], T0)
        r.check("4c after a corrupt read, the finding is treated as newly seen "
                "and flagged age_unknown_at_first_seen",
                s2["findings"]["c::y.py::z"]["age_unknown_at_first_seen"] is True
                and "c::y.py::z" in cls2["new"])
        fa.save_state(sp, s2, T0)
        r.check("4d the rewritten state file is valid JSON again",
                isinstance(json.loads(sp.read_text()), dict))

    # ---------------------------------------------------------------
    # 5. MISSING state file
    # ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        st = fa.load_state(Path(d) / "nope.json")
        r.check("5a missing file -> prior_state_status 'missing', no raise",
                st["prior_state_status"] == "missing" and st["findings"] == {})
        s2, cls2, _, _ = _cycle(st, ["c::a::b"], T0)
        r.check("5b findings from a missing-file run are flagged age_unknown_at_first_seen",
                s2["findings"]["c::a::b"]["age_unknown_at_first_seen"] is True)

    # ---------------------------------------------------------------
    # 6. PRE-AGE-SCHEMA migration -- no invented history
    # ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / ".canonical_drift_state.json"
        sp.write_text(json.dumps({"violations": ["c::old::v1 shape", "c::old::v2 shape"]}))
        st = fa.load_state(sp)
        r.check("6a a pre-age-schema (flat) file is recognised, not treated as corrupt",
                st["prior_state_status"] == "pre_age_schema" and st["findings"] == {})
        now = T0
        s2, cls2, _, msg = _cycle(st, ["c::old::v1 shape", "c::old::v2 shape"], now)
        both = s2["findings"]["c::old::v1 shape"], s2["findings"]["c::old::v2 shape"]
        r.check("6b every migrated finding gets TODAY as first_seen (no back-dating)",
                all(f["first_seen_utc"] == now.isoformat() for f in both))
        r.check("6c every migrated finding is flagged age_unknown_at_first_seen",
                all(f["age_unknown_at_first_seen"] is True for f in both))
        r.check("6d the one-time migration message says 'tracking (age unknown)', not '! NEW'",
                msg is not None and "tracking (age unknown)" in msg and "! NEW" not in msg, msg)

    # ---------------------------------------------------------------
    # 7. a finding DISAPPEARS then RETURNS -> fresh first_seen, not resurrected
    # ---------------------------------------------------------------
    k = "c::flap.py::intermittent"
    s = fa._empty_state("ok")
    s, _, dec, _ = _cycle(s, [k], T0)
    fa.mark_reported(s, dec, T0)
    s, _, _, _ = _cycle(s, [], T0 + timedelta(days=5))          # resolved
    r.check("7a on disappearance the finding moves to resolved_history",
            k in s["resolved_history"] and k not in s["findings"])
    back = T0 + timedelta(days=20)
    s, cls_back, _, _ = _cycle(s, [k], back)
    r.check("7b on return it is a NEW finding with a FRESH first_seen (age clock restarts)",
            k in cls_back["new"] and k in cls_back["returned"]
            and s["findings"][k]["first_seen_utc"] == back.isoformat())
    r.check("7c the prior episode is kept for context (recorded, cheaply)",
            len(s["findings"][k].get("prior_episodes", [])) == 1)
    r.check("7d age after return counts from the return date, not the original",
            fa.age_days(s["findings"][k]["first_seen_utc"], back) == 0)

    # ---------------------------------------------------------------
    # 8. RESOLVED-finding messaging
    # ---------------------------------------------------------------
    k = "c::fix.py::will be fixed"
    s = fa._empty_state("ok")
    s, _, dec, _ = _cycle(s, [k], T0)
    fa.mark_reported(s, dec, T0)                              # Oscar was told
    s, _, dec, msg = _cycle(s, [], T0 + timedelta(days=12))
    r.check("8a a reported finding clearing -> a 'resolved ... was failing 12d' message",
            msg is not None and "resolved" in msg and "12d" in msg, msg)

    k2 = "c::quiet.py::never reported"
    s2 = fa._empty_state("ok")
    s2, _, _, _ = _cycle(s2, [k2], T0)                          # NOT reported
    s2, _, dec2, msg2 = _cycle(s2, [], T0 + timedelta(days=3))
    r.check("8b NEGATIVE CONTROL: a finding Oscar never saw, silently clearing -> NO message",
            msg2 is None and dec2.resolved == [])

    # ---------------------------------------------------------------
    # 9. "nothing to report -> no message"
    # ---------------------------------------------------------------
    _, _, dec_clean, msg_clean = _cycle(fa._empty_state("ok"), [], T0)
    r.check("9a zero findings -> render_message returns None (send nothing at all)",
            msg_clean is None and dec_clean.should_send is False)

    # ---------------------------------------------------------------
    # 10. 15-line cap even with many simultaneous new findings
    # ---------------------------------------------------------------
    many = [f"c::file{i}.py::hardcoded thing number {i}" for i in range(40)]
    _, _, _, msg_many = _cycle(fa._empty_state("ok"), many, T0)
    r.check("10a a message with 40 new findings is still <= 15 lines",
            msg_many is not None and len(msg_many.splitlines()) <= 15,
            f"{len(msg_many.splitlines())} lines")
    r.check("10b ... and it points at the state file for the rest",
            "more" in msg_many or "state" in msg_many)

    # ---------------------------------------------------------------
    # 11. diagnostic WARNINGS: age-tracked on disk, never alertable
    # ---------------------------------------------------------------
    issue_keys = ["diagnostic::issue::[DB] locked"]
    warn_keys = ["diagnostic::warning::[DB] very large: # MB"]
    s = fa._empty_state("ok")
    new_state, cls = fa.reconcile(s, issue_keys + warn_keys, T0)
    dec = fa.evaluate(cls, NO_REGISTER, new_state, T0, alertable_keys=set(issue_keys))
    r.check("11a a warning key is tracked in the state file (age visible)",
            warn_keys[0] in new_state["findings"])
    r.check("11b ... but a warning never appears in report_new / review_due / resolved",
            warn_keys[0] not in dec.report_new
            and issue_keys[0] in dec.report_new)
    msg = fa.render_message("system diagnostic", dec, new_state, T0, "/tmp/x")
    r.check("11c ... and never in the message body",
            msg is not None and "very large" not in msg)

    # ---------------------------------------------------------------
    # 12. REGISTER robustness / it is never written
    # ---------------------------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        rp = Path(d) / "reg.json"
        r.check("12a absent register file -> {'entries': {}}, no raise, no file created",
                fa.load_register(rp) == {"entries": {}} and not rp.exists())
        rp.write_text("{ not json")
        r.check("12b corrupt register -> empty, no raise, file left untouched",
                fa.load_register(rp) == {"entries": {}} and rp.read_text() == "{ not json")
        rp.write_text(json.dumps({"accepted": [
            {"finding_key": "k1", "accepted_by": "Oscar", "accepted_on": "2026-09-07",
             "reason": "ok", "review_by": "2026-12-01"},
            {"finding_key": "k2", "accepted_by": "Oscar", "accepted_on": "2026-09-07",
             "reason": "bad date", "review_by": "not-a-date"},
            {"finding_key": "k3", "reason": "missing fields"},
        ]}))
        reg = fa.load_register(rp)
        r.check("12c a valid entry loads; entries with a bad review_by or missing "
                "fields are skipped (the rest still load)",
                list(reg["entries"]) == ["k1"])

    real_register = fa.load_register()  # the committed config/accepted_failures.json
    r.check("12d the committed register is present and seeded EMPTY",
            real_register == {"entries": {}})

    # ---------------------------------------------------------------
    # 13. finding keys are line-number independent (canonical check)
    # ---------------------------------------------------------------
    import check_canonical_definitions as ccd
    k_a = ccd.finding_keys([(Path("scripts/x.py"), 390, "SQL string contains `geo_elo >= 2175`")])
    k_b = ccd.finding_keys([(Path("scripts/x.py"), 999, "SQL string contains `geo_elo >= 2175`")])
    r.check("13a a finding whose line moved yields the SAME key (age is not reset)",
            k_a == k_b and k_a[0].startswith("canonical_definitions::scripts/x.py::"))

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
