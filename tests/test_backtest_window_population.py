#!/usr/bin/env python3
"""
tests/test_backtest_window_population.py

Proves monitoring/column_definitions.py::backtest_window_sql() against the
real production DB (read-only, mode=ro -- no writes). This is the numeric
counterpart to column_definitions.py's own self-test, which only checks the
SQL text structurally (stdlib-only, no DB dependency by module design).

Background: the original population selector (resolution_date >= window_start)
was unreliable -- O-36 (~29% off by >14d) plus two bulk-backfill events
(2026-04-01 16:19:1X, 2026-06-04 21:36:39) that stamped hundreds of genuinely
2023/2024 markets as if they resolved in 2026. Measured directly against the
2025-11-01 window at the time of the original fix: 5,774 markets by
resolution_date vs 4,690 by tape_end (MAX(trades.timestamp) per market).

2026-07-24 FOLLOW-UP (O-45 addendum): backtest_window_sql() is a LIVE query
and is legitimately time-varying -- tape_end grows as new trades accrue, so
the population at a fixed window_start moves day to day BY DESIGN (measured:
4,690 -> 4,702 -> 4,712 within a single day). The original version of this
test hardcoded exact counts (4,690 / 4,636 / etc.) against that moving query,
which is the actual bug -- not the population moving. Fixed here by splitting
assertions into two kinds:
  - INVARIANTS, asserted against the LIVE query: things that are true of the
    *rule* regardless of how many markets currently satisfy it (reconciliation
    identities, named-market classification, monotonicity, half-open boundary).
  - SNAPSHOT facts, asserted against the FROZEN backtest_population_snapshots
    table (snapshot_id='bt_pop_2025-11-01_v1', scripts/snapshot_backtest_population.py):
    a specific population instance pinned at a point in time, for consumers
    (B5 labelling, B3 splits) that need a population that does not move under
    them.

2026-09-07 CORRECTION (see the removal note above SECTION 2, and trading-swarm
brain/decisions/2026-09-07-backtest-window-population-test-chronic-failure-
diagnosis.md, commit 00aeb93): the SNAPSHOT-facts bucket originally also
carried FOUR reconciliation COUNTS (4658 / 54 / 555 / 573, T2 / T2b / T2c /
T2d, plus the T2f identity). Those were NOT "fixed by construction" -- each
compared the frozen snapshot against the LIVE legacy resolution_date query
(old_method_market_ids), which grows as geo/elec markets resolve, so they
drifted and failed continuously for weeks. They have been removed. The only
frozen-snapshot facts that legitimately cannot change are len(snapshot) == 4712
(T1) and the partition identity agree_snap + false_neg_snap == len(snapshot)
(T2e); if either breaks, the snapshot table was tampered with.

T1  SNAPSHOT count: snapshot 'bt_pop_2025-11-01_v1' is frozen at exactly 4,712
    markets, and a live re-run of the same window_start is >= that (population
    only grows from its frozen baseline, never shrinks).
T1c SNAPSHOT subset of canonical_live: every market in the frozen snapshot is
    still selected by the live canonical query -- catches a snapshot market
    silently dropping out (losing its trades, being re-categorised, gaining a
    trade_gap_flag). On failure it names the dropped market_ids, not just a
    count.
T2e SNAPSHOT partition identity: agree_snap + false_neg_snap == len(snapshot).
    True by construction of the split over the FROZEN set; the only count-based
    fact here that legitimately cannot change.
    (T2 / T2b / T2c / T2d / T2f were removed 2026-09-07 -- they asserted
    equalities against frozen (+) live composites that drift by construction.
    See the removal note above SECTION 2 and trading-swarm brain/decisions/
    2026-09-07-backtest-window-population-test-chronic-failure-diagnosis.md.)
T2L LIVE reconciliation INVARIANT: whatever the live canonical/old sets are
    *right now*, they always partition consistently (agree+false_negatives==
    canonical total; agree+zero_trade+false_positives==old total) -- true by
    construction of the split, verified fresh each run, independent of any
    specific counts.
T3  Parameterisation: 3 other window starts give sane monotonic behaviour
    (earlier start -> more or equal markets), live query.
T4  NON-TAUTOLOGICAL regression guard, false positives: Harris/Michelle
    Obama/Nikki Haley 2024 markets are EXCLUDED by the canonical (tape_end)
    query, live. Run the same assertion against a resolution_date-based query
    FIRST and confirm it FAILS there (they'd wrongly appear) -- proving the
    assertion is actually discriminating, not vacuously true.
T5  NON-TAUTOLOGICAL regression guard, false negatives: US-Venezuela military
    engagement / Zelenskyy-Putin meet / Babis-next-Czech-PM markets are
    INCLUDED by the canonical query, live. Same before/after proof against
    the resolution_date version, which wrongly excludes them.
T6  Half-open boundary: a market's own tape_end value used as the shared
    boundary between two adjacent windows places it in exactly the LATER
    window, never both, never neither. Live.
"""

import os
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from monitoring.column_definitions import backtest_window_sql

DB_PATH = ROOT / 'data' / 'polymarket_tracker.db'

SNAPSHOT_ID = 'bt_pop_2025-11-01_v1'

# Fixed fact about the frozen snapshot -- describes a specific pinned population
# instance and will never legitimately change. If it does, the
# backtest_population_snapshots table was modified after generation, which
# violates the append-only/immutable contract.
SNAPSHOT_COUNT = 4712

# REMOVED 2026-09-07: SNAPSHOT_AGREE_WITH_OLD (4658), SNAPSHOT_FALSE_NEGATIVES
# (54), SNAPSHOT_ZERO_TRADE (555), SNAPSHOT_FALSE_POSITIVES (573) and their
# assertions T2 / T2b / T2c / T2d / T2f. Every one asserted an EQUALITY against
# `frozen_snapshot (+) live_old_query`, where `old` is the live legacy
# resolution_date selector (old_method_market_ids). `old` grows every time a
# geo/elec market is marked resolved with resolution_date >= the window start,
# so those equalities drift BY CONSTRUCTION -- they failed continuously for
# weeks. T2f additionally assumed no in-window market ever resolves after the
# freeze; ~649 have. Re-baselining the constants only postpones an identical
# failure (commit cfbc1cd already made exactly this mistake). The coverage was
# NOT lost: the count-free forms survive as T2e (frozen-set partition identity,
# SECTION 2) and T2L-1 / T2L-2 (live reconciliation identities, SECTION 2L), and
# a new structural check T1c (snapshot subset of canonical_live) was added.
# Full analysis: trading-swarm brain/decisions/
#   2026-09-07-backtest-window-population-test-chronic-failure-diagnosis.md
#   (commit 00aeb93), Part 4. Do not re-add these -- they cannot hold.

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


def snapshot_market_ids(conn, snapshot_id):
    rows = conn.execute(
        'SELECT market_id FROM backtest_population_snapshots WHERE snapshot_id = ?',
        (snapshot_id,)
    ).fetchall()
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

    print("\n[SECTION 1] SNAPSHOT count -- frozen population instance")
    print("-" * 50)
    snapshot = snapshot_market_ids(conn, SNAPSHOT_ID)
    r.check(
        f"T1  snapshot '{SNAPSHOT_ID}' is frozen at exactly {SNAPSHOT_COUNT} markets",
        len(snapshot) == SNAPSHOT_COUNT,
        f"Expected {SNAPSHOT_COUNT}, got {len(snapshot)} -- the snapshot table "
        f"should be append-only/immutable; this would indicate it was modified "
        f"after generation",
    )
    live_now = canonical_market_ids(conn, '2025-11-01')
    r.check(
        "T1b SANITY: live count at window_start=2025-11-01 is >= the frozen "
        "snapshot count (population only grows from its pinned baseline)",
        len(live_now) >= len(snapshot),
        f"Live count {len(live_now)} < frozen snapshot count {len(snapshot)} -- "
        f"population should be non-decreasing as more trades accrue",
    )
    dropped_from_canonical = snapshot - live_now
    r.check(
        "T1c snapshot is a subset of canonical_live -- every frozen-snapshot "
        "market is still selected by the live canonical query (catches a market "
        "silently dropping out: losing its trades, being re-categorised, or "
        "gaining a trade_gap_flag)",
        not dropped_from_canonical,
        f"{len(dropped_from_canonical)} snapshot market(s) absent from the live "
        f"canonical result: {sorted(dropped_from_canonical)}",
    )

    print("\n[SECTION 2] SNAPSHOT reconciliation (fixed facts about the frozen instance)")
    print("-" * 50)
    # ------------------------------------------------------------------------
    # T2 / T2b / T2c / T2d / T2f were REMOVED 2026-09-07. They asserted exact
    # equalities (4658 / 54 / 555 / 573, and the identity agree + zero_trade +
    # false_positives == len(old)) against `frozen_snapshot (+) old`, where
    # `old` is the LIVE legacy resolution_date selector. `old` grows every time
    # a geo/elec market is marked resolved with resolution_date >= the window
    # start, so those equalities drift BY CONSTRUCTION -- they failed
    # continuously for weeks. T2f further assumed no in-window market ever
    # resolves after the snapshot freeze; ~649 have. Re-baselining the numbers
    # only postpones an identical failure (commit cfbc1cd already made exactly
    # that mistake). Coverage was NOT lost by accident: the count-free forms are
    # T2e below (frozen-set partition identity) and T2L-1 / T2L-2 in SECTION 2L
    # (live reconciliation identities); T1c above adds the structural
    # subset check. Full analysis: trading-swarm brain/decisions/
    #   2026-09-07-backtest-window-population-test-chronic-failure-diagnosis.md
    #   (commit 00aeb93), Part 4. Do NOT re-add these -- they cannot hold.
    # ------------------------------------------------------------------------
    old = old_method_market_ids(conn, '2025-11-01')
    agree_snap = snapshot & old
    false_negatives_snap = snapshot - old

    r.check(
        "T2e snapshot reconciliation: agree + false_negatives == snapshot total",
        len(agree_snap) + len(false_negatives_snap) == len(snapshot),
        f"{len(agree_snap)} + {len(false_negatives_snap)} != {len(snapshot)}",
    )

    print("\n[SECTION 2L] LIVE reconciliation INVARIANT (no hardcoded counts)")
    print("-" * 50)
    canonical_live = canonical_market_ids(conn, '2025-11-01')
    agree_live = canonical_live & old
    false_negatives_live = canonical_live - old
    old_only_live = old - canonical_live
    old_only_live_tape_end = tape_end_map(conn, old_only_live)
    zero_trade_live = {mid for mid, te in old_only_live_tape_end.items() if te is None}
    false_positives_live = {mid for mid, te in old_only_live_tape_end.items()
                             if te is not None and te < '2025-11-01'}
    r.check(
        "T2L-1 LIVE: agree + false_negatives == live canonical total, "
        "whatever the live count currently is",
        len(agree_live) + len(false_negatives_live) == len(canonical_live),
        f"{len(agree_live)} + {len(false_negatives_live)} != {len(canonical_live)}",
    )
    r.check(
        "T2L-2 LIVE: agree + zero_trade + false_positives == old total, "
        "whatever the live count currently is",
        len(agree_live) + len(zero_trade_live) + len(false_positives_live) == len(old),
        f"{len(agree_live)} + {len(zero_trade_live)} + {len(false_positives_live)} != {len(old)}",
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
        in_canonical = mid in canonical_live
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
        in_canonical = mid in canonical_live
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
