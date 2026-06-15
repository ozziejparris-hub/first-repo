#!/usr/bin/env python3
"""
normalize_market_dates.py — ONE-TIME data fix + reusable normalizer.

Normalizes all date columns in the markets table to SQLite canonical format
(YYYY-MM-DD HH:MM:SS). Fixes the format inconsistency (Z-suffix, T-separator,
+00:00 offset) that broke string-based datetime comparisons in resolution
queries — markets stored as '2026-06-15T00:00:00Z' compared as GREATER than
datetime('now') because 'T' (0x54) > ' ' (0x20), making them invisible to
resolution passes on their resolution day.

All markets are UTC, so stripping Z / converting T / dropping +00:00 is lossless.

Idempotent: re-running on already-normalized data is a no-op.

Usage:
  python3 normalize_market_dates.py --dry-run   # show what would change
  python3 normalize_market_dates.py             # apply
"""
import sqlite3
import argparse
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")

# Columns to normalize in markets table
DATE_COLUMNS = ['resolution_date', 'end_date', 'start_date', 'last_checked']


def normalize_datetime_sql(col):
    """SQL expression that normalizes a date column to canonical format.
    Returns NULL-safe expression."""
    return f"datetime(replace(replace({col},'Z',''),'T',' '))"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    cur = conn.cursor()

    # Check which columns actually exist
    cur.execute("PRAGMA table_info(markets)")
    existing_cols = {r[1] for r in cur.fetchall()}
    cols_to_fix = [c for c in DATE_COLUMNS if c in existing_cols]
    print(f"Columns to normalize: {cols_to_fix}")

    total_changed = 0
    for col in cols_to_fix:
        norm = normalize_datetime_sql(col)
        # Count rows where normalized differs from current (would change)
        cur.execute(f"""
            SELECT COUNT(*) FROM markets
            WHERE {col} IS NOT NULL
            AND {col} != {norm}
        """)
        changed = cur.fetchone()[0]
        print(f"  {col}: {changed} rows differ from canonical")

        if not args.dry_run and changed > 0:
            cur.execute(f"""
                UPDATE markets
                SET {col} = {norm}
                WHERE {col} IS NOT NULL
                AND {col} != {norm}
            """)
            conn.commit()
            print(f"    -> normalized {changed} rows")
        total_changed += changed

    if args.dry_run:
        print(f"\nDRY RUN — would normalize {total_changed} values total")
    else:
        print(f"\nNormalized {total_changed} values total")

        # Verify no Z/T remnants in resolution_date or end_date
        for col in ['resolution_date', 'end_date']:
            if col in existing_cols:
                cur.execute(f"SELECT COUNT(*) FROM markets WHERE {col} LIKE '%Z' OR {col} LIKE '%T%'")
                remaining = cur.fetchone()[0]
                print(f"  {col}: {remaining} rows still have Z/T (should be 0)")

    conn.close()


if __name__ == '__main__':
    main()
