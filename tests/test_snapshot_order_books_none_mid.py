#!/usr/bin/env python3
"""
tests/test_snapshot_order_books_none_mid.py

Proves the fix for: snapshot_market() (scripts/snapshot_order_books.py) wrote
a successful order-book snapshot, then threw formatting a None mid_price/
bid_depth/ask_depth with `.3f`/`.0f` in the post-commit log line -- caught by
the surrounding broad `except Exception`, mislabeled as a DB write error, and
counted as a capture failure even though the row was committed.

mid_price/bid_depth/ask_depth are legitimately None for a one-sided book
(fetch_book only sets each when its own side is non-empty) -- not an error
condition, and should never turn a successful write into a reported failure.

T1  A one-sided book (bids only, no asks) writes its row to
    order_book_snapshots successfully.
T2  snapshot_market() returns True for that same call -- the return value
    must reflect the DB write outcome, not whether the log line formatted.
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

_PROD_DB = (ROOT / 'data' / 'polymarket_tracker.db').resolve()

import snapshot_order_books as sob


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


def _make_db() -> str:
    """Temp SQLite DB with just the two tables snapshot_market() touches."""
    fd, path = tempfile.mkstemp(suffix='.db', prefix='test_snapshot_ob_')
    os.close(fd)
    assert Path(path).resolve() != _PROD_DB, \
        f"BUG: temp DB resolved to production path: {path}"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            clob_token_id_yes TEXT,
            clob_token_id_no TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE order_book_snapshots (
            market_id       TEXT NOT NULL,
            snapshot_ts     TEXT NOT NULL,
            signal_id       TEXT,
            snapshot_type   TEXT NOT NULL,
            direction       TEXT NOT NULL,
            token_id        TEXT NOT NULL,
            bids_json       TEXT,
            asks_json       TEXT,
            mid_price       REAL,
            spread          REAL,
            bid_depth_10    REAL,
            ask_depth_10    REAL,
            clob_market_price_yes REAL,
            PRIMARY KEY (market_id, snapshot_ts, direction)
        )
    """)
    conn.execute(
        "INSERT INTO markets (market_id, clob_token_id_yes, clob_token_id_no) VALUES (?, ?, ?)",
        ("0xtestmarket", "tok_yes", "tok_no"),
    )
    conn.commit()
    conn.close()
    return path


# One-sided book: bids present, no asks. Per fetch_book's own logic this
# means mid_price=None, spread=None, ask_depth=None -- bid_depth is the only
# populated depth. This is the exact shape that crashed the old print line.
_ONE_SIDED_BOOK_RESULT = (
    [{'price': '0.42', 'size': '100'}],  # bids
    [],                                    # asks
    None,                                  # mid_price
    None,                                  # spread
    100.0,                                 # bid_depth
    None,                                  # ask_depth
)


def run_tests() -> bool:
    r = TestResults()

    print("\n[SECTION] One-sided book (mid_price/ask_depth None) — write vs. reported outcome")
    print("-" * 50)

    db = None
    try:
        db = _make_db()
        conn = sqlite3.connect(db)

        with patch.object(sob, 'fetch_book', return_value=_ONE_SIDED_BOOK_RESULT), \
             patch.object(sob, 'fetch_clob_market_price', return_value=None):
            result = sob.snapshot_market(conn, 'TEST-SIGNAL', '0xtestmarket', 'YES', 'daily')

        row = conn.execute(
            "SELECT mid_price, bid_depth_10, ask_depth_10 FROM order_book_snapshots "
            "WHERE market_id = ? AND signal_id = ?",
            ('0xtestmarket', 'TEST-SIGNAL'),
        ).fetchone()

        r.check(
            "T1  row committed to order_book_snapshots despite None mid_price/ask_depth",
            row is not None,
            f"Expected one row for TEST-SIGNAL/0xtestmarket, found none. Row: {row}",
        )
        if row is not None:
            r.check(
                "T1b  committed row's mid_price/ask_depth are the actual None values, not corrupted",
                row[0] is None and row[2] is None and row[1] == 100.0,
                f"Expected (mid_price=None, bid_depth_10=100.0, ask_depth_10=None), got {row}",
            )

        r.check(
            "T2  snapshot_market() returns True for a successful write "
            "(pre-fix this returned False: the write succeeds, then the log "
            "line's `mid={mid_price:.3f}` raises on None, is caught by the "
            "broad except, and mislabels the capture as failed)",
            result is True,
            f"Expected True (row IS committed above), got {result!r}.",
        )

        conn.close()
    finally:
        if db and os.path.exists(db):
            os.unlink(db)

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
