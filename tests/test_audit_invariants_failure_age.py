#!/usr/bin/env python3
"""
tests/test_audit_invariants_failure_age.py

Proves the 2026-09-09 failure-age integration of scripts/audit_invariants.py
(brain/decisions/2026-09-09-final-telegram-cut.md).

Covers the task's reproducibility list:
  - a changed result set (an invariant newly crossing its floor) alerts
  - an unchanged one (already reported, still failing) does not
  - an accepted one (in config/accepted_failures.json) does not

plus:
  - finding_keys() returns a key ONLY for REGRESSION / CRITICAL results
  - the key is the invariant NAME, not its count — a persistently-failing
    invariant whose count drifts must keep its age (not read as NEW)
  - with the live register, only the ONE kept invariant
    ("pending on resolved non-gap geo/elections markets") can alert
  - the four accepted invariants each suppress under the live register and
    each WOULD alert under an empty register (the control test, as done for
    the 2026-09-07 canonical entry in commit f882a86)
  - CRITICAL findings are still surfaced (the alert gate does not swallow them)

Exercises functions directly — no DB, no Telegram, no subprocess. audit_invariants
is import-safe (its only import-time work is `import monitoring.column_definitions`).
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from monitoring import failure_age as fa  # noqa: E402
import audit_invariants as ai  # noqa: E402


class TestResults:
    def __init__(self):
        self.run = self.passed = self.failed = 0
        self.failures = []

    def check(self, name, cond, reason=""):
        self.run += 1
        if cond:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            self.failures.append((name, reason or "condition was False"))
            print(f"  [FAIL] {name}: {reason or 'condition was False'}")

    def summary(self):
        print(f"\n{'='*70}\n  TEST SUMMARY\n{'='*70}")
        print(f"  Tests run    : {self.run}")
        print(f"  Passed       : {self.passed}  ({self.passed / max(1, self.run) * 100:.0f}%)")
        print(f"  Failed       : {self.failed}")
        for n, why in self.failures:
            print(f"    - {n}: {why}")
        print(f"{'='*70}")
        return self.failed == 0


T0 = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
NO_REGISTER = {"entries": {}}

KEPT_KEY = "audit_invariants::pending on resolved non-gap geo/elections markets"
ACCEPTED_KEYS = [
    "audit_invariants::pending on resolved non-gap markets (flagged traders)",
    "audit_invariants::timestamp mixed formats (per-column breakdown)",
    "audit_invariants::data_source not in canonical set (write-path regression)",
    "audit_invariants::total_invested vs SUM(entry_total_cost) mismatch >5%",
]


def _result(name, status, count=0):
    return {"name": name, "status": status, "tier": 2, "floor": 0,
            "count": count, "examples": []}


# The five regressions the audit currently reports, plus some passing rows.
FIVE_REGRESSIONS = [
    _result("pending on resolved non-gap markets (flagged traders)", "REGRESSION", 2213),
    _result("pending on resolved non-gap geo/elections markets", "REGRESSION", 24390),
    _result("timestamp mixed formats (per-column breakdown)", "REGRESSION", 35819),
    _result("data_source not in canonical set (write-path regression)", "REGRESSION", 577),
    _result("total_invested vs SUM(entry_total_cost) mismatch >5%", "REGRESSION", 14216),
]
PASSING = [
    _result("duplicate markets.market_id", "PASS"),
    _result("[0d/OBSERVE] comprehensive_elo out of [400,3500]", "OBSERVE"),
]


def _cycle(state, keys, now, register=NO_REGISTER):
    ns, cls = fa.reconcile(state, keys, now)
    dec = fa.evaluate(cls, register, ns, now)
    msg = fa.render_message("DB audit invariants", dec, ns, now, "/tmp/x.json")
    return ns, cls, dec, msg


def run_tests():
    r = TestResults()

    # -----------------------------------------------------------------
    # 1. finding_keys(): one key per REGRESSION/CRITICAL, name-based
    # -----------------------------------------------------------------
    keys = ai.finding_keys(FIVE_REGRESSIONS + PASSING)
    r.check("1a finding_keys returns exactly the 5 regression keys",
            keys == sorted(k for k in
                           [KEPT_KEY] + ACCEPTED_KEYS),
            f"got {keys}")
    r.check("1b a PASS / OBSERVE result gets no key",
            not any("duplicate markets" in k or "OBSERVE" in k for k in keys))
    r.check("1c every key is namespaced 'audit_invariants::<name>'",
            all(k.startswith("audit_invariants::") for k in keys))
    r.check("1d a CRITICAL result also gets a key",
            "audit_invariants::some tier-1 thing" in
            ai.finding_keys([_result("some tier-1 thing", "CRITICAL", 3)]))

    # -----------------------------------------------------------------
    # 2. key is the NAME, not the count — count drift keeps the age
    # -----------------------------------------------------------------
    day1 = [_result("pending on resolved non-gap geo/elections markets", "REGRESSION", 24103)]
    day2 = [_result("pending on resolved non-gap geo/elections markets", "REGRESSION", 24644)]
    k1 = ai.finding_keys(day1)
    k2 = ai.finding_keys(day2)
    r.check("2a a count change on the same invariant yields the SAME key", k1 == k2)
    st = fa._empty_state("ok")
    ns1, _, _, _ = _cycle(st, k1, T0)
    ns2, cls2, _, _ = _cycle(ns1, k2, T0 + timedelta(days=1))
    r.check("2b ... so day 2 sees it as 'ongoing', not 'new' (age not reset)",
            cls2["ongoing"] == k1 and cls2["new"] == [],
            f"new={cls2['new']} ongoing={cls2['ongoing']}")

    # -----------------------------------------------------------------
    # 3. a changed result set alerts; an unchanged one does not
    # -----------------------------------------------------------------
    # Start: only the geo pending is failing, already reported.
    st = fa._empty_state("ok")
    ns, cls, dec, msg = _cycle(st, [KEPT_KEY], T0)
    fa.mark_reported(ns, dec, T0)
    ns_after_report, _, dec2, msg2 = _cycle(ns, [KEPT_KEY], T0 + timedelta(hours=6))
    r.check("3a an already-reported, still-failing invariant sends nothing",
            msg2 is None and not dec2.should_send)
    # Now a second invariant crosses its floor.
    ns3, cls3, dec3, msg3 = _cycle(ns_after_report, [KEPT_KEY, ACCEPTED_KEYS[0]],
                                   T0 + timedelta(days=1))
    r.check("3b a newly-failing invariant (result set changed) alerts",
            msg3 is not None and ACCEPTED_KEYS[0] in dec3.report_new)
    r.check("3c ... and the already-reported one is not repeated as NEW",
            KEPT_KEY not in dec3.report_new)

    # -----------------------------------------------------------------
    # 4. an accepted invariant does not alert (control test)
    # -----------------------------------------------------------------
    live_reg = fa.load_register()
    r.check("4a the four audit_invariants keys are present in the live register",
            all(k in live_reg["entries"] for k in ACCEPTED_KEYS))
    r.check("4b the kept key is NOT in the register",
            KEPT_KEY not in live_reg["entries"])

    all5 = ai.finding_keys(FIVE_REGRESSIONS)
    _, _, dec_live, msg_live = _cycle(fa._empty_state("ok"), all5, T0, register=live_reg)
    _, _, dec_empty, msg_empty = _cycle(fa._empty_state("ok"), all5, T0, register=NO_REGISTER)

    r.check("4c with the live register only the KEPT invariant alerts",
            dec_live.report_new == [KEPT_KEY], f"got {dec_live.report_new}")
    for k in ACCEPTED_KEYS:
        r.check(f"4d accepted suppresses: {k.split('::')[1][:40]}",
                k not in dec_live.report_new and (msg_live is None or fa._short(k) not in msg_live))
    r.check("4e control: with an EMPTY register all five would alert",
            set(dec_empty.report_new) == set(all5),
            f"got {sorted(dec_empty.report_new)}")
    r.check("4f the KEPT invariant alerts under BOTH registers "
            "(suppression comes from the register, nothing else)",
            KEPT_KEY in dec_live.report_new and KEPT_KEY in dec_empty.report_new)

    # -----------------------------------------------------------------
    # 5. an accepted invariant PAST its review_by alerts again
    # -----------------------------------------------------------------
    expired = {"entries": {ACCEPTED_KEYS[1]: {
        "finding_key": ACCEPTED_KEYS[1], "accepted_by": "Oscar",
        "accepted_on": "2026-09-09", "reason": "x", "review_by": "2026-09-08"}}}
    _, _, dec_exp, msg_exp = _cycle(fa._empty_state("ok"), [ACCEPTED_KEYS[1]],
                                    T0, register=expired)
    r.check("5a an accepted finding past review_by produces a 'review due' message",
            msg_exp is not None and ACCEPTED_KEYS[1] in dec_exp.review_due
            and "review due" in msg_exp)

    # -----------------------------------------------------------------
    # 6. a CRITICAL finding is not swallowed by the alert gate
    # -----------------------------------------------------------------
    crit = ai.finding_keys([_result("successful_trades > total_trades", "CRITICAL", 9)])
    _, _, dec_c, msg_c = _cycle(fa._empty_state("ok"), crit, T0, register=live_reg)
    r.check("6a an un-accepted CRITICAL finding still alerts",
            msg_c is not None and crit[0] in dec_c.report_new)

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
