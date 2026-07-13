#!/usr/bin/env python3
"""
tests/test_comprehensive_elo_formula_equivalence.py

THE zero-diff equivalence test: compute_comprehensive_elo(w_beh=0,
apply_soft_cap=False, apply_floor=False) MUST equal production Writer B's
formula (scripts/apply_full_elo_modifiers.py) EXACTLY, across a
comprehensive input grid. This is the test the design doc's Correction
section says would have caught the original bonus-leak/soft-cap/floor bugs
before Stage 2 shipped -- it asserts ZERO diffs, not a rounding epsilon.

Reference implementation: tests/_writer_b_reference.py, a verbatim port of
apply_full_elo_modifiers.py's formula lines. Kept as a separate file (not
imported from the module under test) so the two are genuinely independent
and a real divergence can't be masked by shared code.

Grid covers: base ELO across and around both dampening thresholds
(2000, 2500) and the empirical population extremes (479-3500); closed
positions across every confidence-cap breakpoint (0,1,2,3,4,5,9,10,19,20,25);
resolved trades across the thin-sample breakpoint (0,1,9,10,11,25,60,200);
pnl_raw swept 0.40-2.50 in 0.05 steps PLUS every cap boundary +/-0.01
(1.30,1.45,1.60,1.80,2.00,2.20) and the thin-gate boundary (1.00) +/-0.01.

The mult==0.0 copy-trader exclusion is tested separately (Writer B skips
that trader entirely -- there is no "production value" to diff against).
"""

import sys
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.comprehensive_elo_formula import compute_comprehensive_elo
from tests._writer_b_reference import writer_b_reference


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


BASES = [479, 1000, 1500, 1999, 2000, 2001, 2400, 2499, 2500, 2501, 3000, 3500]
CLOSED = [0, 1, 2, 3, 4, 5, 9, 10, 19, 20, 25]
RESOLVED = [0, 1, 9, 10, 11, 25, 60, 200]
PNL_RAW = sorted(set(
    [round(0.40 + 0.05 * i, 2) for i in range(int((2.50 - 0.40) / 0.05) + 1)]
    + [0.99, 1.00, 1.01, 1.29, 1.30, 1.31, 1.44, 1.45, 1.46,
       1.59, 1.60, 1.61, 1.79, 1.80, 1.81, 1.99, 2.00, 2.01, 2.19, 2.20, 2.21, 2.49, 2.50]
))
# beh_mult/bonus are irrelevant at w_beh=0 -- swept to prove that, not because
# they should change anything.
BEH_MULT_NOISE = [0.80, 1.00, 1.40]
BONUS_NOISE = [-100, 0, 100]


def _section_equivalence(r: TestResults):
    print("\n--- Zero-diff equivalence: compute(w_beh=0, soft_cap=False, floor=False) vs Writer B ---")
    grid_size = 0
    diff_count = 0
    first_diffs = []
    for base, closed, resolved, pnl_raw in product(BASES, CLOSED, RESOLVED, PNL_RAW):
        grid_size += 1
        produced = compute_comprehensive_elo(
            base=base, beh_mult=1.20, bonus=40, pnl_raw=pnl_raw, closed=closed, resolved=resolved,
            w_beh=0.0, apply_soft_cap=False, apply_floor=False,
        ).comp
        reference = writer_b_reference(base, pnl_raw, closed, resolved)
        if produced != reference:
            diff_count += 1
            if len(first_diffs) < 10:
                first_diffs.append((base, closed, resolved, pnl_raw, produced, reference))

    r.check(
        f"ZERO DIFFS across {grid_size}-point grid",
        diff_count == 0,
        f"{diff_count} diffs found. First few: {first_diffs}",
    )
    print(f"  Grid size  : {grid_size}")
    print(f"  Diff count : {diff_count}")


def _section_beh_mult_bonus_irrelevant(r: TestResults):
    print("\n--- beh_mult/bonus must not affect the result at w_beh=0 (bonus-leak regression) ---")
    n_checked = 0
    for base, closed, resolved in product(BASES, CLOSED, RESOLVED):
        for pnl_raw in [0.60, 1.00, 1.80, 2.50]:
            n_checked += 1
            values = set()
            for beh_mult, bonus in product(BEH_MULT_NOISE, BONUS_NOISE):
                result = compute_comprehensive_elo(
                    base=base, beh_mult=beh_mult, bonus=bonus, pnl_raw=pnl_raw,
                    closed=closed, resolved=resolved,
                    w_beh=0.0, apply_soft_cap=False, apply_floor=False,
                )
                values.add(result.comp)
            r.check(
                f"comp identical across all beh_mult/bonus combos base={base} closed={closed} "
                f"resolved={resolved} pnl_raw={pnl_raw}",
                len(values) == 1,
                f"got {len(values)} distinct values: {values}",
            )
    print(f"  ({n_checked} (base,closed,resolved,pnl_raw) combos, {len(BEH_MULT_NOISE)*len(BONUS_NOISE)} beh_mult/bonus pairs each)")


def _section_copy_trader_exclusion(r: TestResults):
    print("\n--- mult==0.0 copy-trader exclusion (Writer B skips; not a comparable case) ---")
    for base, closed, resolved in product([1000, 2400], [0, 5, 20], [0, 25]):
        reference = writer_b_reference(base, 0.0, closed, resolved)
        r.check(
            f"writer_b_reference returns None for mult=0.0 (base={base}, closed={closed}, resolved={resolved})",
            reference is None,
            f"got {reference}",
        )
    # Document (do not assert equivalence): compute_comprehensive_elo has no
    # analogous skip -- pnl_raw=0.0 is out-of-domain for it, matching the
    # module docstring's contract. A caller integrating this into a writer
    # must replicate the copy-trader skip itself, upstream of the call.
    result = compute_comprehensive_elo(
        base=2400, beh_mult=1.0, bonus=0, pnl_raw=0.0, closed=5, resolved=25,
        w_beh=0.0, apply_soft_cap=False, apply_floor=False,
    )
    r.check(
        "compute_comprehensive_elo has no crash on pnl_raw=0.0 (out-of-domain, not asserted equivalent)",
        isinstance(result.comp, float),
        f"got {result}",
    )


def run_tests() -> bool:
    r = TestResults()
    _section_equivalence(r)
    _section_beh_mult_bonus_irrelevant(r)
    _section_copy_trader_exclusion(r)
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
