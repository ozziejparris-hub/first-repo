#!/usr/bin/env python3
"""
tests/test_geo_backfill_step_registered.py

Proves the geo/elec pending-result evaluator is wired into
scripts/daily_maintenance.py's step list correctly, per
brain/decisions/2026-09-09-geo-backfill-wiring-decision.md Part 3 and
2026-09-10-geo-backfill-wiring-implementation.md.

  T1  The step "Evaluate geo/elec pending results (all traders)" is present
      on a normal (non-Sunday) weekday.
  T2  It targets backfill_trade_results_geo.py.
  T3  Its extra_args are exactly ["--limit", "1000"] (top-up sizing —
      NOT a drain; see the implementation doc for the arrival-rate basis).
  T4  It is non_blocking=True (settlement pass, never aborts maintenance).
  T5  Position: it sits strictly between "Evaluate new trader results" and
      "Reconcile geo resolved counts [post-eval]", and is immediately
      adjacent to both (the placement the decision doc specifies — one
      settlement point covers both evaluators' geo_resolved_trades_count
      writes, and it runs after the step-7 audit gate).
  T6  It is a base daily step — present on every weekday including Sunday,
      not weekly-gated.
  T7  It appears exactly once.
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


GEO_BACKFILL_LABEL = "Evaluate geo/elec pending results (all traders)"
EVAL_NEW_LABEL     = "Evaluate new trader results"
RECON_POST_LABEL   = "Reconcile geo resolved counts [post-eval]"


def _labels(steps):
    return [s[0] for s in steps]


def _find(steps, label):
    for s in steps:
        if s[0] == label:
            return s
    return None


def _index(steps, label):
    for i, s in enumerate(steps):
        if s[0] == label:
            return i
    return None


def run_tests() -> bool:
    r = TestResults()

    # ── T1-T5: a normal weekday (Wednesday = 2) ────────────────────────────
    print("\n[SECTION 1] Non-Sunday weekday — step registered with correct spec")
    print("-" * 50)

    steps = dm.build_steps(2)
    step = _find(steps, GEO_BACKFILL_LABEL)

    r.check(
        "T1  geo-backfill step present on a normal weekday",
        step is not None,
        f"Expected '{GEO_BACKFILL_LABEL}' in steps, not found. "
        f"Got labels: {_labels(steps)}",
    )

    if step is not None:
        script       = step[1]
        extra_args   = step[2] if len(step) > 2 else None
        non_blocking = step[3] if len(step) > 3 else False

        r.check(
            "T2  targets backfill_trade_results_geo.py",
            script.name == "backfill_trade_results_geo.py",
            f"Got script={script}",
        )
        r.check(
            "T3  extra_args are exactly ['--limit', '1000']",
            extra_args == ["--limit", "1000"],
            f"Got extra_args={extra_args}",
        )
        r.check(
            "T4  non_blocking is True (settlement pass, never aborts the run)",
            non_blocking is True,
            f"Got non_blocking={non_blocking}",
        )

    # ── T5: position relative to its neighbours ────────────────────────────
    print("\n[SECTION 2] Position between the two evaluators it settles with")
    print("-" * 50)

    i_geo   = _index(steps, GEO_BACKFILL_LABEL)
    i_eval  = _index(steps, EVAL_NEW_LABEL)
    i_recon = _index(steps, RECON_POST_LABEL)

    r.check(
        "T5a  both neighbour steps still present",
        i_eval is not None and i_recon is not None,
        f"Eval-new idx={i_eval}, Reconcile-post idx={i_recon}",
    )
    if None not in (i_geo, i_eval, i_recon):
        r.check(
            "T5b  ordered strictly between 'Evaluate new trader results' and "
            "'Reconcile geo resolved counts [post-eval]'",
            i_eval < i_geo < i_recon,
            f"Order was eval={i_eval}, geo={i_geo}, recon={i_recon}",
        )
        r.check(
            "T5c  immediately after 'Evaluate new trader results'",
            i_geo == i_eval + 1,
            f"geo idx {i_geo} is not eval idx {i_eval} + 1",
        )
        r.check(
            "T5d  immediately before 'Reconcile geo resolved counts [post-eval]'",
            i_geo == i_recon - 1,
            f"geo idx {i_geo} is not recon idx {i_recon} - 1",
        )

    # ── T6: base daily step, present every weekday incl. Sunday ────────────
    print("\n[SECTION 3] Base daily step — every weekday, not weekly-gated")
    print("-" * 50)

    for weekday in range(0, 7):
        wd_steps = dm.build_steps(weekday)
        r.check(
            f"T6  weekday={weekday}: geo-backfill step present",
            _find(wd_steps, GEO_BACKFILL_LABEL) is not None,
            f"Missing on weekday={weekday}. Got: {_labels(wd_steps)}",
        )

    # ── T7: appears exactly once ──────────────────────────────────────────
    print("\n[SECTION 4] Registered exactly once")
    print("-" * 50)

    count = sum(1 for s in dm.build_steps(2) if s[0] == GEO_BACKFILL_LABEL)
    r.check(
        "T7  step label appears exactly once in the list",
        count == 1,
        f"Found {count} entries with label '{GEO_BACKFILL_LABEL}'",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
