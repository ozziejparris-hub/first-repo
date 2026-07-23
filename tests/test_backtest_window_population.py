#!/usr/bin/env python3
"""
tests/test_backtest_window_population.py

Proves monitoring/column_definitions.py::backtest_window_sql() against the
real production DB (read-only, mode=ro -- no writes). This is the numeric
counterpart to column_definitions.py's own self-test, which only checks the
SQL text structurally (stdlib-only, no DB dependency by module design).

Background: the current population selector (resolution_date >= window_start)
is unreliable -- O-36 (~29% off by >14d) plus two bulk-backfill events
(2026-04-01 16:19:1X, 2026-06-04 21:36:39) that stamped hundreds of genuinely
2023/2024 markets as if they resolved in 2026. Measured directly against the
2025-11-01 window: 5,774 markets by resolution_date vs 4,690 by tape_end
(MAX(trades.timestamp) per market) -- 573 false positives (old markets
wrongly pulled in), 54 false negatives (in-window markets wrongly excluded),
565 zero-trade markets (correctly dropped by both methods, structurally).

T1  Canonical count at window_start=2025-11-01 is exactly 4,690.
T2  Reconciliation holds: 4,690 = 4,636 (agree with the old resolution_date
    method) + 54 (false negatives the old method wrongly excluded).
T3  Parameterisation: 3 other window starts give sane monotonic behaviour
    (earlier start -> more or equal markets).
T4  NON-TAUTOLOGICAL regression guard, false positives: Harris/Michelle
    Obama/Nikki Haley 2024 markets are EXCLUDED by the canonical (tape_end)
    query. Run the same assertion against a resolution_date-based query
    FIRST and confirm it FAILS there (they'd wrongly appear) -- proving the
    assertion is actually discriminating, not vacuously true.
T5  NON-TAUTOLOGICAL regression guard, false negatives: US-Venezuela military
    engagement / Zelenskyy-Putin meet / Babis-next-Czech-PM markets are
    INCLUDED by the canonical query. Same before/after proof against the
    resolution_date version, which wrongly excludes them.
T6  Half-open boundary: a market's own tape_end value used as the shared
    boundary between two adjacent windows places it in exactly the LATER
    window, never both, never neither.
"""

import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from monitoring.column_definitions import backtest_window_sql

DB_PATH = ROOT / 'data' / 'polymarket_tracker.db'

# Known false positives (real event 2024, wrongly pulled into the
# resolution_date>=2025-11-01 window by bulk-backfill contamination).
FALSE_POSITIVE_IDS = {
    '0xc6485bb7ea46d7bb89beb9c91e7572ecfc72a6273789496f78bc5e989e4d1638': 'Kamala Harris win 2024',
    '0x230144e34a84dfd0ebdc6de7fde37780e28154f6f84dd8880c7f0e58d302d448': 'Michelle Obama win 2024',
    '0xced9f9d90c94db9f1e1dbd7d9fba82fe4fa7431c0d4e91e28896c8ac2d6acadd': 'Nikki Haley win 2024',
}

# Known false negatives (real Nov-2025+ activity, wrongly excluded by
# resolution_date>=2025-11-01 because resolution_date is early/NULL-stamped).
FALSE_NEGATIVE_IDS = {
    '0x3d16ed6f91ad7d3ffb1633e792a6b5595cbd30cf8a9f63883ade9e6e97c8bdc8': 'US-Venezuela military engagement by October 31',
    '0xa56afcf5b2db4531f9f339edc04acc9c29a777127b79164cf8850556d164f5ea': 'Zelenskyy and Putin not meet',
    '0x90394c2848abe272fc43ab6d3842efc6ebcf41aee50ec9fdca1980a6452ff19a': 'Babis next Czech PM',
}

# A real market's own tape_end, used as the exact shared boundary in T6.
BOUNDARY_MARKET_ID = '0xee44d5936019f87f0fee643d930ac34139e7211ebdde3f3d27c290bb9fdd5929'  # Giuliani NYC
BOUNDARY_TAPE_END = '2025-11-03 04:50:49'


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


def _ro_conn():
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=30)
    return conn


def canonical_market_ids(conn, window_start, window_end=None):
    params = {'window_start': window_start}
    if window_end:
        params['window_end'] = window_end
    rows = conn.execute(backtest_window_sql(window_start, window_end), params).fetchall()
    return {r[0] for r in rows}


def old_method_market_ids(conn, window_start):
    """The pre-existing resolution_date-based selector, for before/after
    non-tautology proof only -- never used for real population selection."""
    rows = conn.execute("""
        SELECT market_id FROM markets
        WHERE category IN ('Geopolitics', 'Elections')
          AND resolved = 1
          AND resolution_date >= ?
          AND (trade_gap_flag = 0 OR trade_gap_flag IS NULL)
    """, (window_start,)).fetchall()
    return {r[0] for r in rows}


def tape_end_map(conn, market_ids):
    """market_id -> tape_end (or None if the market has zero trades)."""
    if not market_ids:
        return {}
    placeholders = ','.join('?' for _ in market_ids)
    rows = conn.execute(f"""
        SELECT market_id, MAX(timestamp) FROM trades
        WHERE market_id IN ({placeholders})
        GROUP BY market_id
    """, list(market_ids)).fetchall()
    found = dict(rows)
    return {mid: found.get(mid) for mid in market_ids}


def run_tests() -> bool:
    r = TestResults()
    conn = _ro_conn()

    print("\n[SECTION 1] Canonical count at 2025-11-01")
    print("-" * 50)
    canonical = canonical_market_ids(conn, '2025-11-01')
    r.check(
        "T1  canonical (tape_end) count at window_start=2025-11-01 is exactly 4,690",
        len(canonical) == 4690,
        f"Expected 4690, got {len(canonical)}",
    )

    print("\n[SECTION 2] Reconciliation: 4,690 = 4,636 (agree) + 54 (false negatives)")
    print("-" * 50)
    old = old_method_market_ids(conn, '2025-11-01')
    agree = canonical & old
    false_negatives = canonical - old
    old_only = old - canonical  # splits into zero-trade + genuine stale-tape_end false positives
    old_only_tape_end = tape_end_map(conn, old_only)
    zero_trade = {mid for mid, te in old_only_tape_end.items() if te is None}
    false_positives = {mid for mid, te in old_only_tape_end.items()
                        if te is not None and te < '2025-11-01'}

    r.check(
        "T2  4,636 markets agree between old and canonical methods",
        len(agree) == 4636,
        f"Expected 4636, got {len(agree)}",
    )
    r.check(
        "T2b 54 false negatives (canonical includes, old method excluded)",
        len(false_negatives) == 54,
        f"Expected 54, got {len(false_negatives)}",
    )
    r.check(
        "T2c 565 zero-trade markets (old method included, no tape_end to anchor on -- "
        "dropped structurally by canonical's INNER JOIN, not a resolution_date error)",
        len(zero_trade) == 565,
        f"Expected 565, got {len(zero_trade)}",
    )
    r.check(
        "T2d 573 genuine false positives (old method included, real tape_end predates "
        "the window -- these are the resolution_date-is-wrong cases)",
        len(false_positives) == 573,
        f"Expected 573, got {len(false_positives)}",
    )
    r.check(
        "T2e reconciliation: agree + false_negatives == canonical total",
        len(agree) + len(false_negatives) == len(canonical),
        f"{len(agree)} + {len(false_negatives)} != {len(canonical)}",
    )
    r.check(
        "T2f reconciliation: agree + zero_trade + false_positives == old total",
        len(agree) + len(zero_trade) + len(false_positives) == len(old),
        f"{len(agree)} + {len(zero_trade)} + {len(false_positives)} != {len(old)}",
    )

    print("\n[SECTION 3] Parameterisation -- monotonic behaviour across window starts")
    print("-" * 50)
    counts = {}
    for start in ('2025-09-01', '2025-11-01', '2026-01-01', '2026-03-01'):
        counts[start] = len(canonical_market_ids(conn, start))
        print(f"  window_start={start}: {counts[start]} markets")
    starts_sorted = sorted(counts.keys())
    monotonic = all(counts[starts_sorted[i]] >= counts[starts_sorted[i + 1]]
                     for i in range(len(starts_sorted) - 1))
    r.check(
        "T3  earlier window_start yields >= markets than a later one, across all 4 points",
        monotonic,
        f"Not monotonic: {counts}",
    )

    print("\n[SECTION 4] NON-TAUTOLOGICAL false-positive regression guard")
    print("-" * 50)
    for mid, label in FALSE_POSITIVE_IDS.items():
        in_old = mid in old
        r.check(
            f"T4a  [{label}] DOES appear in the old resolution_date-based result "
            f"(proves the assertion below is discriminating, not vacuous)",
            in_old,
            f"{label} ({mid[:16]}...) was expected in the old (buggy) result but wasn't -- "
            f"the regression guard below would be tautological if this fails",
        )
    for mid, label in FALSE_POSITIVE_IDS.items():
        in_canonical = mid in canonical
        r.check(
            f"T4b  [{label}] correctly EXCLUDED from the canonical (tape_end) result",
            not in_canonical,
            f"{label} ({mid[:16]}...) wrongly appears in the canonical result",
        )

    print("\n[SECTION 5] NON-TAUTOLOGICAL false-negative regression guard")
    print("-" * 50)
    for mid, label in FALSE_NEGATIVE_IDS.items():
        in_old = mid in old
        r.check(
            f"T5a  [{label}] is ABSENT from the old resolution_date-based result "
            f"(proves the assertion below is discriminating, not vacuous)",
            not in_old,
            f"{label} ({mid[:16]}...) was expected to be missing from the old (buggy) "
            f"result but was present -- the regression guard below would be tautological",
        )
    for mid, label in FALSE_NEGATIVE_IDS.items():
        in_canonical = mid in canonical
        r.check(
            f"T5b  [{label}] correctly INCLUDED in the canonical (tape_end) result",
            in_canonical,
            f"{label} ({mid[:16]}...) is wrongly missing from the canonical result",
        )

    print("\n[SECTION 6] Half-open boundary -- a market's own tape_end as the shared split point")
    print("-" * 50)
    window_a = canonical_market_ids(conn, '2025-10-01', BOUNDARY_TAPE_END)   # tape_end < boundary
    window_b = canonical_market_ids(conn, BOUNDARY_TAPE_END, '2025-12-01')   # tape_end >= boundary
    in_a = BOUNDARY_MARKET_ID in window_a
    in_b = BOUNDARY_MARKET_ID in window_b
    r.check(
        "T6  boundary market appears in exactly the LATER window (in B, not A) "
        "when its own tape_end is used as the shared window_end/window_start",
        (not in_a) and in_b,
        f"Expected (in_a=False, in_b=True), got (in_a={in_a}, in_b={in_b})",
    )

    conn.close()
    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
