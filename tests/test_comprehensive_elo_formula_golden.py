#!/usr/bin/env python3
"""
tests/test_comprehensive_elo_formula_golden.py

Golden-file tests pinning the ELO arc design doc's §2.4 worked examples
(L/M/H/T/X) against analysis/comprehensive_elo_formula.py.

Source: ~/trading-swarm/brain/decisions/2026-07-06-elo-arc-design-FABLE.md
§2.4 ("Revised 2026-07-06 — corrected bonus scaling"). All five cases use
w_beh=0.5, apply_soft_cap=True, apply_floor=True (Stage 4 / fully-launched
behavior) — this is the design's own choice for these worked examples,
independent of the actual launch value (W_BEH=0, decided Stage 0b). These
tests pin the FORMULA's mechanics, not the deployed weight.

Each expected value was hand-derived from the design's pseudocode
independently of the implementation, then cross-checked against the
design doc's own table (the "U (canonical)" column) — every case matches
exactly, including the intermediate gain decomposition shown in the design
doc's prose (e.g. case H: "gains 960+240+20=1220 x0.8 -> 3376").
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.comprehensive_elo_formula import compute_comprehensive_elo


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


EPS = 1e-6

# (case, base, beh_mult, bonus, pnl_raw, closed, resolved, expected_comp)
CASES = [
    ("L", 1200, 1.20, 40, 1.5, 5, 15, 1940.0),
    ("M", 1600, 0.90, -20, 1.8, 10, 25, 2790.0),
    ("H", 2400, 1.20, 40, 1.4, 25, 60, 3376.0),
    ("T", 1500, 1.40, 100, 2.5, 1, 4, 1500.0),
    ("X", 2400, 1.40, 100, 2.5, 25, 60, 3500.0),
]


def _section_golden(r: TestResults):
    print("\n--- §2.4 worked examples (w_beh=0.5, soft_cap=True, floor=True) ---")
    for case, base, beh_mult, bonus, pnl_raw, closed, resolved, expected in CASES:
        result = compute_comprehensive_elo(
            base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=pnl_raw,
            closed=closed, resolved=resolved,
            w_beh=0.5, apply_soft_cap=True, apply_floor=True,
        )
        r.check(
            f"Case {case}: comp == {expected}",
            abs(result.comp - expected) < EPS,
            f"got {result.comp}",
        )


def _section_case_details(r: TestResults):
    print("\n--- Intermediate audit-trail spot checks ---")

    # Case T: both pnl AND behavioral must be thin-sample-gated (resolved=4 < 10)
    t = compute_comprehensive_elo(
        base=1500, beh_mult=1.40, bonus=100, pnl_raw=2.5, closed=1, resolved=4,
        w_beh=0.5, apply_soft_cap=True, apply_floor=True,
    )
    r.check("Case T: pnl_gated thin-gated to 1.0", abs(t.pnl_gated - 1.0) < EPS, f"got {t.pnl_gated}")
    r.check("Case T: gain_beh is exactly 0 (thin-sample gate)", t.gain_beh == 0.0, f"got {t.gain_beh}")
    r.check("Case T: gain_pnl is exactly 0", t.gain_pnl == 0.0, f"got {t.gain_pnl}")

    # Case X: hard cap must be the binding constraint (soft cap doesn't bind
    # at resolved=60: 1500+60*150=10500, well above the pre-cap 5128)
    x = compute_comprehensive_elo(
        base=2400, beh_mult=1.40, bonus=100, pnl_raw=2.5, closed=25, resolved=60,
        w_beh=0.5, apply_soft_cap=True, apply_floor=True,
    )
    r.check("Case X: hard cap is the binding constraint", x.cap_applied == "hard", f"got {x.cap_applied}")
    r.check("Case X: damp=0.8 (base 2400 in [2000,2500))", abs(x.damp - 0.8) < EPS, f"got {x.damp}")

    # Case H: gain decomposition matches the design doc's prose exactly
    # (960 pnl + 240 mult + 20 bonus = 1220 total gain, x0.8 damp = 976)
    h = compute_comprehensive_elo(
        base=2400, beh_mult=1.20, bonus=40, pnl_raw=1.4, closed=25, resolved=60,
        w_beh=0.5, apply_soft_cap=True, apply_floor=True,
    )
    r.check("Case H: gain_pnl == 960", abs(h.gain_pnl - 960.0) < EPS, f"got {h.gain_pnl}")
    r.check("Case H: gain_beh == 260 (240 mult + 20 bonus)", abs(h.gain_beh - 260.0) < EPS, f"got {h.gain_beh}")
    r.check("Case H: cap_applied == none (3376 < 3500)", h.cap_applied == "none", f"got {h.cap_applied}")


def run_tests() -> bool:
    r = TestResults()
    _section_golden(r)
    _section_case_details(r)
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
