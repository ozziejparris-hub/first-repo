#!/usr/bin/env python3
"""
Worker process for tests/test_match_control_determinism.py. Builds a fixed,
synthetic (profile, cohort_traders, elig_traders) input -- identical every
invocation -- calls match_control() with seed=42, and prints the resulting
matched-trader set as a sorted JSON list to stdout. Run as a subprocess with
varying PYTHONHASHSEED by the test harness; if match_control() is properly
determined by its seed argument, every invocation must print the identical
list regardless of the process's hash seed.

Includes deliberately duplicated feature vectors in the candidate pool (p05
== p06, p09 == p10 == p11) to stress the argsort tie-breaking path, which
becomes deterministic only once the candidate pool's row order is itself
deterministic (sorted, not raw set iteration).
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2f import match_control

COHORT = {"c1", "c2", "c3", "c4", "c5"}

# candidate pool: intentionally includes tied feature rows (p05/p06,
# p09/p10/p11) so the fix's effect on argsort tie-breaking is exercised, not
# just the top-level cohort/pool list ordering.
POOL_ROWS = {
    "p01": (12, 4, "2026-01-01", "2026-02-01"),
    "p02": (30, 9, "2026-01-05", "2026-03-01"),
    "p03": (5, 2, "2026-01-10", "2026-01-20"),
    "p04": (80, 15, "2026-01-01", "2026-04-01"),
    "p05": (20, 6, "2026-01-01", "2026-02-15"),
    "p06": (20, 6, "2026-01-01", "2026-02-15"),  # tied with p05
    "p07": (45, 11, "2026-01-01", "2026-03-15"),
    "p08": (3, 1, "2026-01-01", "2026-01-05"),
    "p09": (60, 13, "2026-01-01", "2026-03-20"),
    "p10": (60, 13, "2026-01-01", "2026-03-20"),  # tied with p09/p11
    "p11": (60, 13, "2026-01-01", "2026-03-20"),  # tied with p09/p10
    "p12": (15, 5, "2026-01-01", "2026-02-05"),
}
COHORT_ROWS = {
    "c1": (10, 3, "2026-01-01", "2026-01-15"),
    "c2": (25, 8, "2026-01-01", "2026-02-20"),
    "c3": (7, 2, "2026-01-01", "2026-01-10"),
    "c4": (50, 12, "2026-01-01", "2026-03-10"),
    "c5": (18, 5, "2026-01-01", "2026-02-01"),
}

ELIG_TRADERS = set(POOL_ROWS.keys()) | set(COHORT.copy())


def build_profile():
    rows = {**COHORT_ROWS, **POOL_ROWS}
    df = pd.DataFrame([
        dict(trader=t, n_positions=n_pos, n_markets=n_mkt, min=lo, max=hi)
        for t, (n_pos, n_mkt, lo, hi) in rows.items()
    ])
    return df


def main():
    profile = build_profile()
    matched = match_control(profile, COHORT, ELIG_TRADERS, seed=42, verbose=False)
    print(json.dumps(sorted(matched)))


if __name__ == '__main__':
    main()
