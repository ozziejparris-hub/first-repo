#!/usr/bin/env python3
"""
tests/test_backfill_market_categories_pagination.py

Proves the fix for backfill_market_categories.py's OFFSET-pagination
skip-drift, found in the 2026-09-13 daily_maintenance audit (see
brain/decisions/2026-09-13-daily-maintenance-audit.md, trading-swarm) and
fixed the same day (see the companion decision doc for this fix).

Root cause: fetch_batch() paginated with SQL OFFSET over
WHERE category='Unknown' -- a result set that SHRINKS every time a batch
contains a row that gets reclassified out of it. The checkpoint advanced
last_processed_offset by the raw batch size fetched, not by how many rows
stayed 'Unknown'. On any batch with a mix of classified/skipped rows, the
still-unclassified rows silently and permanently drifted below the
advancing offset -- this happened on every ordinary successful run, not
only after a crash.

The fix replaces OFFSET with keyset pagination on market_id (the table's
stable primary key): WHERE market_id > last_seen_market_id. Since
market_id is never renumbered or reused, a value-based cursor cannot
drift the way a position-based one does, regardless of how many rows
enter or leave the matching set around it.

Section 1 reproduces the bug against a local, deliberately-buggy
reimplementation of the OLD offset logic (the actual code no longer
contains this bug -- reimplementing it here, inline, is the only way to
demonstrate what it used to do). A test that could pass against the
fixed code too would prove nothing; Section 1's assertions are written to
FAIL if run against keyset logic, and Section 2 proves the real,
currently-shipped fetch_batch() does not exhibit the same failure on the
identical fixture.

Section 3 confirms the UPDATE statements apply_classifications() issues
are idempotent -- applying the same classification twice produces the
same end state.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_market_categories as bmc


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


def _build_fixture_db() -> sqlite3.Connection:
    """
    10 markets, m01..m10 (lexically ordered), all category='Unknown', all
    with a title matching the keyword filter ('war'). market_id is TEXT
    PRIMARY KEY, matching production's schema shape (a stable, orderable
    key with no numeric meaning).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT
        )
    """)
    for i in range(1, 11):
        mid = f"m{i:02d}"
        conn.execute(
            "INSERT INTO markets (market_id, title, category) VALUES (?, ?, 'Unknown')",
            (mid, f"war market {mid}"),
        )
    conn.commit()
    return conn


def _reclassify(conn: sqlite3.Connection, market_ids: list[str], category: str = "Geopolitics"):
    """Simulate a HIGH-confidence classification: the row leaves the Unknown set."""
    for mid in market_ids:
        conn.execute("UPDATE markets SET category = ? WHERE market_id = ?", (category, mid))
    conn.commit()


def _old_buggy_fetch_batch(conn: sqlite3.Connection, offset: int, batch_size: int) -> list[str]:
    """
    Reimplementation of the ORIGINAL fetch_batch(), before this fix --
    OFFSET pagination over the shrinking WHERE category='Unknown' set.
    Kept here only to demonstrate the bug; the shipped code no longer has
    this shape (see backfill_market_categories.fetch_batch).
    """
    rows = conn.execute("""
        SELECT market_id FROM markets
        WHERE category = 'Unknown' AND title LIKE '%war%'
        ORDER BY market_id
        LIMIT ? OFFSET ?
    """, (batch_size, offset)).fetchall()
    return [r["market_id"] for r in rows]


def run_tests() -> bool:
    r = TestResults()

    # ── Section 1: reproduce the bug against the OLD offset logic ──────────
    print("\n[SECTION 1] Reproducing the OFFSET-pagination skip-drift bug")
    print("-" * 50)

    conn = _build_fixture_db()

    # Batch 1: offset=0, batch_size=5 -> m01..m05 (all 10 rows still Unknown)
    batch1 = _old_buggy_fetch_batch(conn, offset=0, batch_size=5)
    r.check(
        "T1a  batch 1 (offset=0) fetches the first 5 markets",
        batch1 == ["m01", "m02", "m03", "m04", "m05"],
        f"Got: {batch1}",
    )

    # Simulate a mixed outcome: m01 and m03 get classified (leave the set);
    # m02, m04, m05 are skipped (stay Unknown) -- exactly the "batch with a
    # mix" shape the audit named as the trigger.
    _reclassify(conn, ["m01", "m03"])

    # OLD code: offset advances by the raw batch size fetched (5), regardless
    # of how many rows actually left the set.
    old_offset = 0 + len(batch1)
    r.check("T1b  OLD logic advances offset to 5 (raw batch size, not rows-left-the-set)",
            old_offset == 5, f"Got offset={old_offset}")

    # Batch 2: offset=5 against the NOW-SHRUNK set (8 rows: m02,m04,m05,m06,
    # m07,m08,m09,m10). Position 5 in this new ordering is m08.
    batch2 = _old_buggy_fetch_batch(conn, offset=old_offset, batch_size=5)
    r.check(
        "T1c  batch 2 (offset=5, OLD logic) skips m06 and m07 -- they are "
        "neither in batch 1 nor batch 2",
        "m06" not in batch1 and "m06" not in batch2 and "m07" not in batch1 and "m07" not in batch2,
        f"batch1={batch1} batch2={batch2}",
    )
    r.check(
        "T1d  batch 2 actually returned rows (m08, m09, m10) -- proving "
        "m06/m07's absence is a skip, not simply 'no more rows'",
        batch2 == ["m08", "m09", "m10"],
        f"Got: {batch2}",
    )
    conn.close()

    # ── Section 2: prove the FIX doesn't reproduce this on the same fixture ─
    print("\n[SECTION 2] The shipped fix does not exhibit the same skip")
    print("-" * 50)

    conn2 = _build_fixture_db()

    batches = []
    cursor = None
    for _ in range(5):  # generous cap; the fixture only needs 2 real batches
        batch = bmc.fetch_batch(conn2, cursor, batch_size=5)
        if not batch:
            break
        ids = [m["market_id"] for m in batch]
        batches.append(ids)
        if ids == ["m01", "m02", "m03", "m04", "m05"]:
            # First batch fetched -- now simulate the same mixed outcome as
            # Section 1 (m01, m03 classified; rest stay Unknown) before the
            # next iteration's fetch_batch() call sees the shrunk set.
            _reclassify(conn2, ["m01", "m03"])
        cursor = ids[-1]

    fetched_all = [mid for batch in batches for mid in batch]

    r.check(
        "T2a  the fix's keyset pagination reaches m06 through m10 -- none "
        "of them are skipped despite the identical mixed-batch scenario",
        all(mid in fetched_all for mid in ["m06", "m07", "m08", "m09", "m10"]),
        f"Fetched overall: {fetched_all}",
    )
    r.check(
        "T2b  every market_id is fetched exactly once across all batches "
        "(no double-processing from the cursor advancing correctly)",
        sorted(fetched_all) == sorted(set(fetched_all)),
        f"Fetched overall: {fetched_all}",
    )
    r.check(
        "T2c  m01 and m03 (reclassified out of Unknown immediately after "
        "batch 1) appear ONLY in batch 1, never in any later batch -- the "
        "cursor correctly moved past them and doesn't re-surface them",
        all("m01" not in b and "m03" not in b for b in batches[1:]),
        f"Batches: {batches}",
    )
    conn2.close()

    # ── Section 3: idempotency of the UPDATE itself ─────────────────────────
    print("\n[SECTION 3] apply_classifications()'s UPDATE is idempotent")
    print("-" * 50)

    conn3 = _build_fixture_db()
    conn3.execute("CREATE TABLE trades (market_id TEXT, market_category TEXT)")
    conn3.execute("INSERT INTO trades (market_id, market_category) VALUES ('m01', 'Unknown')")
    conn3.commit()

    markets = [{"market_id": "m01", "title": "war market m01"}]
    classifications = [{"id": 1, "category": "Geopolitics", "confidence": "HIGH"}]

    classified1, skipped1 = bmc.apply_classifications(conn3, markets, classifications, False, _null_logger())
    conn3.commit()
    cat_after_first = conn3.execute("SELECT category FROM markets WHERE market_id='m01'").fetchone()[0]

    # Apply the identical classification again -- simulating a row revisited
    # via the wraparound, or re-fetched after a crash-and-restart.
    classified2, skipped2 = bmc.apply_classifications(conn3, markets, classifications, False, _null_logger())
    conn3.commit()
    cat_after_second = conn3.execute("SELECT category FROM markets WHERE market_id='m01'").fetchone()[0]

    r.check(
        "T3a  both applications report classified=1, skipped=0 (same outcome each time)",
        classified1 == 1 and classified2 == 1 and skipped1 == 0 and skipped2 == 0,
        f"first=({classified1},{skipped1}) second=({classified2},{skipped2})",
    )
    r.check(
        "T3b  category is 'Geopolitics' after both the first and second "
        "application -- reprocessing a row produces the same end state",
        cat_after_first == "Geopolitics" and cat_after_second == "Geopolitics",
        f"after first={cat_after_first!r} after second={cat_after_second!r}",
    )
    trades_cat = conn3.execute("SELECT market_category FROM trades WHERE market_id='m01'").fetchone()[0]
    r.check(
        "T3c  trades.market_category was also updated and is idempotently consistent",
        trades_cat == "Geopolitics",
        f"Got: {trades_cat!r}",
    )
    conn3.close()

    return r.summary()


class _null_logger:
    """Minimal logger stand-in -- apply_classifications() only calls
    .info/.debug/.warning/.error, all of which are no-ops here."""
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
