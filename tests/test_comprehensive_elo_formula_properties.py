#!/usr/bin/env python3
"""
tests/test_comprehensive_elo_formula_properties.py

Property tests for analysis/comprehensive_elo_formula.py — these check
structural invariants across a grid of inputs, not single pinned values
(that's the golden-file test's job).

Properties checked:
  P1  Monotonic in pnl_raw (holding everything else fixed): comp never
      decreases as pnl_raw increases. This holds across the thin-sample
      gate and the loss-amplification branch too (both proven analytically
      to preserve monotonicity: the thin-gate only clamps values that would
      otherwise exceed 1.0 down to exactly 1.0 -- the same value the
      function returns at pnl_raw==1.0, so there's no discontinuity).
  P2  Behavioral gain is bounded. For resolved>=10, gain_beh in
      [w_beh*(-0.2*base - 100), w_beh*(0.4*base + 100)] -- derived directly
      from beh_mult's stored range [0.80,1.40] and bonus's stored range
      [-100,100]. (Note: design doc §2.2(a) states a narrower, w_beh=0.5-
      specific bound "damp*(0.20*base+100)" that was NOT one of the
      sections the 2026-07-06 Correction updated when the bonus-scaling
      fix landed -- see the design doc's Correction section, which lists
      only §2.1/§2.4/§2.5/§4.1/§5 as revised. That figure is stale by
      inspection: at w_beh=0.5 the bonus's own max contribution is
      100*0.5=50, not 100. This test uses the bound derived directly from
      the corrected formula (§2.1's code), cross-checked against all 5 of
      §2.4's worked examples in the golden test, not the possibly-stale
      §2.2 prose.)
  P3  Cap/floor compliance: apply_soft_cap=True => comp <= 1500+resolved*150+eps;
      hard cap always comp <= 3500+eps; apply_floor=True => comp >= 400-eps.
  P4  Thin-sample gates: resolved<10 => gain_beh is always exactly 0, AND
      (resolved<10 and pnl_raw>1.0) => pnl_gated is forced to exactly 1.0
      (gain_pnl==0).
"""

import sys
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.comprehensive_elo_formula import compute_comprehensive_elo, _confidence_cap


class TestResults:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def ok(self, name: str):
        self.tests_run += 1
        self.tests_passed += 1

    def fail(self, name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((name, reason))

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
            print(f"\n  FAILURES (first 20):")
            for name, reason in self.failures[:20]:
                print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


EPS = 1e-6

BASES = [1000, 1500, 1999, 2000, 2400, 2500, 2999, 3000]
CLOSED_VALS = [0, 1, 2, 3, 5, 10, 20, 30]
RESOLVED_VALS = [0, 1, 5, 9, 10, 11, 25, 60, 200]
BEH_MULT_VALS = [0.80, 0.95, 1.00, 1.20, 1.40]
BONUS_VALS = [-100, -50, 0, 40, 100]
W_BEH_VALS = [0.0, 0.25, 0.5, 1.0]
PNL_RAW_SWEEP = [round(0.40 + 0.05 * i, 2) for i in range(int((2.50 - 0.40) / 0.05) + 1)]  # 0.40..2.50 step .05


def _section_monotonic(r: TestResults):
    print("\n--- P1: monotonic in pnl_raw ---")
    n_cases = 0
    for base, closed, resolved, w_beh in product(BASES, CLOSED_VALS, RESOLVED_VALS, [0.0, 0.5]):
        n_cases += 1
        comps = [
            compute_comprehensive_elo(
                base=base, beh_mult=1.10, bonus=20, pnl_raw=p, closed=closed, resolved=resolved,
                w_beh=w_beh, apply_soft_cap=False, apply_floor=False,
            ).comp
            for p in PNL_RAW_SWEEP
        ]
        non_decreasing = all(comps[i] <= comps[i + 1] + EPS for i in range(len(comps) - 1))
        r.check(
            f"monotonic base={base} closed={closed} resolved={resolved} w_beh={w_beh}",
            non_decreasing,
            f"comps={comps}",
        )
    print(f"  ({n_cases} (base,closed,resolved,w_beh) combos, {len(PNL_RAW_SWEEP)}-point pnl_raw sweep each)")


def _section_behavioral_bound(r: TestResults):
    print("\n--- P2: behavioral gain bounded by [w_beh*(-0.2*base-100), w_beh*(0.4*base+100)] ---")
    n_cases = 0
    for base, resolved, beh_mult, bonus, w_beh in product(
        BASES, [r_ for r_ in RESOLVED_VALS if r_ >= 10], BEH_MULT_VALS, BONUS_VALS, W_BEH_VALS
    ):
        n_cases += 1
        result = compute_comprehensive_elo(
            base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=1.0, closed=10, resolved=resolved,
            w_beh=w_beh, apply_soft_cap=False, apply_floor=False,
        )
        lower = w_beh * (base * (0.80 - 1.0) - 100)
        upper = w_beh * (base * (1.40 - 1.0) + 100)
        r.check(
            f"gain_beh in bounds base={base} beh_mult={beh_mult} bonus={bonus} w_beh={w_beh}",
            lower - EPS <= result.gain_beh <= upper + EPS,
            f"gain_beh={result.gain_beh} not in [{lower},{upper}]",
        )
    print(f"  ({n_cases} combos checked)")


def _section_caps(r: TestResults):
    print("\n--- P3: cap/floor compliance ---")
    n_cases = 0
    for base, closed, resolved, beh_mult, bonus, w_beh, pnl_raw in product(
        BASES, CLOSED_VALS, RESOLVED_VALS, [0.80, 1.40], [-100, 100], [0.0, 0.5, 1.0],
        [0.40, 1.0, 2.50],
    ):
        n_cases += 1
        soft = compute_comprehensive_elo(
            base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=pnl_raw, closed=closed, resolved=resolved,
            w_beh=w_beh, apply_soft_cap=True, apply_floor=True,
        )
        soft_cap_bound = 1500 + resolved * 150
        r.check(
            f"soft cap respected base={base} resolved={resolved} pnl_raw={pnl_raw} w_beh={w_beh}",
            soft.comp <= soft_cap_bound + EPS,
            f"comp={soft.comp} > soft_cap {soft_cap_bound}",
        )
        r.check(
            f"hard cap respected base={base} resolved={resolved} pnl_raw={pnl_raw} w_beh={w_beh}",
            soft.comp <= 3500 + EPS,
            f"comp={soft.comp} > 3500",
        )
        r.check(
            f"floor respected base={base} resolved={resolved} pnl_raw={pnl_raw} w_beh={w_beh}",
            soft.comp >= 400 - EPS,
            f"comp={soft.comp} < 400",
        )
        # apply_soft_cap=False must never be below the hard-cap-only value's need for a soft check
        hard_only = compute_comprehensive_elo(
            base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=pnl_raw, closed=closed, resolved=resolved,
            w_beh=w_beh, apply_soft_cap=False, apply_floor=False,
        )
        r.check(
            f"hard cap alone still respected (soft_cap=False) base={base} resolved={resolved}",
            hard_only.comp <= 3500 + EPS,
            f"comp={hard_only.comp} > 3500",
        )
    print(f"  ({n_cases} combos checked)")


def _section_thin_sample(r: TestResults):
    print("\n--- P4: thin-sample gates (resolved < 10) ---")
    n_cases = 0
    thin_resolved = [0, 1, 5, 9]
    for base, resolved, beh_mult, bonus, w_beh, pnl_raw in product(
        BASES, thin_resolved, BEH_MULT_VALS, BONUS_VALS, [0.25, 0.5, 1.0], PNL_RAW_SWEEP
    ):
        n_cases += 1
        result = compute_comprehensive_elo(
            base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=pnl_raw, closed=10, resolved=resolved,
            w_beh=w_beh, apply_soft_cap=False, apply_floor=False,
        )
        r.check(
            f"gain_beh==0 thin sample resolved={resolved} beh_mult={beh_mult} bonus={bonus} w_beh={w_beh}",
            result.gain_beh == 0.0,
            f"gain_beh={result.gain_beh}",
        )
        if pnl_raw > 1.0:
            r.check(
                f"pnl_gated forced to 1.0 (thin sample, pnl_raw={pnl_raw} > 1.0, resolved={resolved})",
                abs(result.pnl_gated - 1.0) < EPS,
                f"pnl_gated={result.pnl_gated}",
            )
            r.check(
                f"gain_pnl==0 (thin sample, pnl_raw={pnl_raw} > 1.0, resolved={resolved})",
                result.gain_pnl == 0.0,
                f"gain_pnl={result.gain_pnl}",
            )
    print(f"  ({n_cases} combos checked)")


def run_tests() -> bool:
    r = TestResults()
    _section_monotonic(r)
    _section_behavioral_bound(r)
    _section_caps(r)
    _section_thin_sample(r)
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
