#!/usr/bin/env python3
"""
scripts/migrate_add_data_source.py — Add data_source column to 4 core tables.

Usage:
    python scripts/migrate_add_data_source.py           # dry run (safe, no writes)
    python scripts/migrate_add_data_source.py --apply   # execute migration

Migration sequence (tight, per-table):
    1. traders  : ALTER  → backfill from discovery_source
    2. markets  : ALTER  → backfill historical_backfill for Dec-11 rows
    3. trades   : ALTER  → explicit no-op backfill (default already correct)
    4. positions: ALTER  → backfill synthetic_resolution for is_synthetic_close=1

After all ALTERs + backfills, runs a verification pass:
    - Distribution per table (SELECT data_source, COUNT(*) GROUP BY)
    - No NULLs on any row
    - All values within the canonical frozenset for that table
    - Distribution shape matches expectation (bucket counts)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import monitoring.column_definitions as cd

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _column_exists(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == "data_source" for r in rows)


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _print_banner(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


# ── Per-table migration steps ─────────────────────────────────────────────────

class TableMigration:
    def __init__(
        self,
        table: str,
        alter_sql: str,
        backfill_sql: str,
        backfill_label: str,
        allowed: frozenset,
        expected_buckets: int,
    ):
        self.table = table
        self.alter_sql = alter_sql
        self.backfill_sql = backfill_sql
        self.backfill_label = backfill_label
        self.allowed = allowed
        self.expected_buckets = expected_buckets


MIGRATIONS: list[TableMigration] = [
    TableMigration(
        table="traders",
        alter_sql=cd.DATA_SOURCE_ALTER_TRADERS,
        backfill_sql=cd.DATA_SOURCE_BACKFILL_TRADERS_SQL,
        backfill_label="discovery_source → data_source",
        allowed=cd.DATA_SOURCE_TRADERS,
        expected_buckets=5,
    ),
    TableMigration(
        table="markets",
        alter_sql=cd.DATA_SOURCE_ALTER_MARKETS,
        backfill_sql=cd.DATA_SOURCE_BACKFILL_MARKETS_HISTORICAL_SQL,
        backfill_label="Dec-11 rows → historical_backfill",
        allowed=cd.DATA_SOURCE_MARKETS,
        expected_buckets=2,
    ),
    TableMigration(
        table="trades",
        alter_sql=cd.DATA_SOURCE_ALTER_TRADES,
        backfill_sql=cd.DATA_SOURCE_BACKFILL_TRADES_SQL,
        backfill_label="explicit no-op (default = polymarket_api)",
        allowed=cd.DATA_SOURCE_TRADES,
        expected_buckets=1,
    ),
    TableMigration(
        table="positions",
        alter_sql=cd.DATA_SOURCE_ALTER_POSITIONS,
        backfill_sql=cd.DATA_SOURCE_BACKFILL_POSITIONS_SYNTHETIC_SQL,
        backfill_label="is_synthetic_close=1 → synthetic_resolution",
        allowed=cd.DATA_SOURCE_POSITIONS,
        expected_buckets=2,
    ),
]


# ── Dry-run preview ───────────────────────────────────────────────────────────

def run_dry(conn: sqlite3.Connection) -> None:
    _print_banner("DRY RUN — no changes will be written")

    for m in MIGRATIONS:
        col_exists = _column_exists(conn, m.table)
        total = _row_count(conn, m.table)

        print(f"\n[{m.table}]")
        print(f"  Total rows      : {total:,}")
        print(f"  Column exists   : {col_exists}")

        if col_exists:
            print(f"  ALTER SQL       : SKIP (column already present)")
        else:
            print(f"  ALTER SQL       : {m.alter_sql}")

        # Estimate backfill impact without writing
        if m.table == "traders":
            affected = conn.execute(
                "SELECT COUNT(*) FROM traders WHERE discovery_source IS NOT NULL"
            ).fetchone()[0]
            null_keep = conn.execute(
                "SELECT COUNT(*) FROM traders WHERE discovery_source IS NULL"
            ).fetchone()[0]
            print(f"  Backfill        : {m.backfill_label}")
            print(f"    rows updated  : ~{affected:,}  (discovery_source IS NOT NULL)")
            print(f"    rows keeping DEFAULT: ~{null_keep:,}  (discovery_source IS NULL → 'live_feed')")

        elif m.table == "markets":
            affected = conn.execute(
                "SELECT COUNT(*) FROM markets WHERE DATE(last_checked) = '2025-12-11'"
            ).fetchone()[0]
            live = _row_count(conn, "markets") - affected
            print(f"  Backfill        : {m.backfill_label}")
            print(f"    rows updated  : ~{affected:,}  (DATE(last_checked) = '2025-12-11')")
            print(f"    rows keeping DEFAULT: ~{live:,}  → 'live_monitoring'")

        elif m.table == "trades":
            null_count = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE data_source IS NULL"
            ).fetchone()[0] if col_exists else total
            print(f"  Backfill        : {m.backfill_label}")
            if col_exists:
                print(f"    rows updated  : {null_count:,}  (data_source IS NULL — should be 0 post-ALTER)")
            else:
                print(f"    rows updated  : 0  (all rows get DEFAULT 'polymarket_api'; backfill WHERE IS NULL → 0 matches)")

        elif m.table == "positions":
            affected = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE is_synthetic_close = 1"
            ).fetchone()[0]
            tracker = _row_count(conn, "positions") - affected
            print(f"  Backfill        : {m.backfill_label}")
            print(f"    rows updated  : ~{affected:,}  (is_synthetic_close = 1)")
            print(f"    rows keeping DEFAULT: ~{tracker:,}  → 'position_tracker'")

        print(f"  Allowed values  : {sorted(m.allowed)}")
        print(f"  Expected buckets: {m.expected_buckets}")

    _print_banner("DRY RUN COMPLETE — pass --apply to execute")


# ── Live migration ────────────────────────────────────────────────────────────

def run_apply(conn: sqlite3.Connection) -> bool:
    _print_banner("APPLYING MIGRATION")

    for m in MIGRATIONS:
        print(f"\n[{m.table}]")

        # Step 1: ALTER (idempotent)
        if _column_exists(conn, m.table):
            print(f"  ALTER  : SKIP — data_source column already exists")
        else:
            print(f"  ALTER  : {m.alter_sql}")
            conn.execute(m.alter_sql)
            conn.commit()
            print(f"  ALTER  : done")

        # Step 2: Backfill immediately after ALTER (tight sequence)
        print(f"  BACKFILL ({m.backfill_label})")
        cursor = conn.execute(m.backfill_sql)
        conn.commit()
        rows_updated = cursor.rowcount
        print(f"  BACKFILL: {rows_updated:,} rows updated")

        if m.table == "trades" and rows_updated != 0:
            print(f"  WARNING: trades backfill expected 0 rows updated, got {rows_updated:,}")

    _print_banner("ALL ALTERs + BACKFILLs COMPLETE")
    return True


# ── Verification pass ─────────────────────────────────────────────────────────

def run_verify(conn: sqlite3.Connection) -> bool:
    _print_banner("VERIFICATION PASS")
    all_ok = True

    for m in MIGRATIONS:
        print(f"\n[{m.table}]")
        total = _row_count(conn, m.table)

        # Distribution
        rows = conn.execute(
            f"SELECT data_source, COUNT(*) FROM {m.table} GROUP BY data_source ORDER BY COUNT(*) DESC"
        ).fetchall()

        print(f"  Distribution ({total:,} total rows):")
        for val, cnt in rows:
            pct = cnt / total * 100 if total else 0
            print(f"    {val!r:<30} {cnt:>10,}  ({pct:.1f}%)")

        # Check 1: no NULLs
        null_count = conn.execute(
            f"SELECT COUNT(*) FROM {m.table} WHERE data_source IS NULL"
        ).fetchone()[0]
        null_ok = null_count == 0
        print(f"  NULL check  : {'OK (0 nulls)' if null_ok else f'FAIL — {null_count:,} NULLs found'}")
        if not null_ok:
            all_ok = False

        # Check 2: all values within frozenset
        actual_values = {r[0] for r in rows}
        invalid = actual_values - m.allowed
        values_ok = len(invalid) == 0
        print(f"  Value check : {'OK — all within allowed set' if values_ok else f'FAIL — invalid values: {invalid}'}")
        if not values_ok:
            all_ok = False

        # Check 3: distribution shape (bucket count)
        bucket_count = len(rows)
        shape_ok = bucket_count == m.expected_buckets
        shape_note = f"got {bucket_count}, expected {m.expected_buckets}"
        print(f"  Shape check : {'OK' if shape_ok else 'FAIL'} — {shape_note} buckets")
        if not shape_ok:
            all_ok = False

    _print_banner(f"VERIFICATION {'PASSED' if all_ok else 'FAILED'}")
    return all_ok


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Execute migration (default: dry run only)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Database : {DB_PATH}")
    print(f"Mode     : {'APPLY' if args.apply else 'DRY RUN'}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    try:
        if not args.apply:
            run_dry(conn)
        else:
            run_apply(conn)
            ok = run_verify(conn)
            if not ok:
                print("\nERROR: Verification failed — inspect output above.", file=sys.stderr)
                sys.exit(1)
            print("\nMigration complete and verified.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
