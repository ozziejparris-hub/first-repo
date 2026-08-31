#!/usr/bin/env python3
"""
Schema migration for the relevance-classifier provenance
(brain/decisions/2026-08-31-relevance-classifier-design.md, e601648, §2.7;
 record: brain/decisions/2026-08-31-classifier-schema-migration.md).

Adds, to data/polymarket_tracker.db:

  1. markets.category_source  TEXT, nullable,
     CHECK (category_source IN
            ('llm_relevance_v1','deterministic_slug_v1','gamma_event','legacy')
            OR category_source IS NULL)
     -- CHECK references only the new column, mirroring the
     -- resolution_evidence_source precedent added by
     -- migrate_stage0_resolution_columns.py.

  2. TABLE category_classification_log
     (market_id, decided_category, method, model_version, confidence,
      inputs_hash, run_id, classified_at)
     append-only, PRIMARY KEY (market_id, run_id).
     Types follow the DB's snapshot/log-table convention
     (elo_snapshots / backtest_population_snapshots / event_cluster_labels):
     identity + timestamp columns TEXT NOT NULL, no CHECKs, composite PK.

  3. Backfill: category_source = 'legacy' for every row where
     category IN ('Geopolitics','Elections') (~11,967 pre-classifier rows).
     SET touches category_source ONLY — 'resolved' is not in the SET list,
     so trg_resolved_no_unresolve does not fire.

Explicitly NOT done here (per the design and the migration task's constraints):
  - No category value is written or changed.
  - No resolved / winning_outcome / resolution_date / resolution_* column
    is touched.
  - No new trigger. audit_invariants.py may later assert
    "every category IN ('Geopolitics','Elections') row has a non-NULL
    category_source" -- that assertion is added separately, not here.

Idempotent: safe to re-run -- checks for the existing column / table /
backfilled rows before acting.

Revert:  python3 scripts/migrate_add_category_source.py --revert
  Drops the table and the column (SQLite >= 3.35 supports DROP COLUMN;
  this box is 3.45.1). The 'legacy' backfill values vanish with the column.
  --revert is itself idempotent.
"""

import argparse
import sqlite3
import sys

DEFAULT_DB = "data/polymarket_tracker.db"

CATEGORY_SOURCE_DDL = (
    "TEXT CHECK (category_source IN "
    "('llm_relevance_v1','deterministic_slug_v1','gamma_event','legacy') "
    "OR category_source IS NULL)"
)

LOG_TABLE_SQL = """
CREATE TABLE category_classification_log (
    market_id         TEXT NOT NULL,
    decided_category  TEXT NOT NULL,
    method            TEXT NOT NULL,
    model_version     TEXT,
    confidence        TEXT,
    inputs_hash       TEXT,
    run_id            TEXT NOT NULL,
    classified_at     TEXT NOT NULL,
    PRIMARY KEY (market_id, run_id)
);
"""

BACKFILL_SQL = (
    "UPDATE markets SET category_source = 'legacy' "
    "WHERE category IN ('Geopolitics','Elections')"
)


def markets_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}


def has_table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def legacy_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM markets WHERE category_source = 'legacy'"
    ).fetchone()[0]


def geo_elec_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM markets WHERE category IN ('Geopolitics','Elections')"
    ).fetchone()[0]


def do_migrate(conn, dry_run):
    cols = markets_columns(conn)
    have_col = "category_source" in cols
    have_tbl = has_table(conn, "category_classification_log")
    target = geo_elec_count(conn)
    have_backfill = have_col and legacy_count(conn) == target and target > 0

    print(f"markets.category_source present : {have_col}")
    print(f"category_classification_log tbl : {have_tbl}")
    print(f"geo/elec rows (backfill target) : {target}")
    if have_col:
        print(f"rows already category_source='legacy' : {legacy_count(conn)}")

    if dry_run:
        print("[DRY RUN] no changes made")
        return 0

    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if not have_col:
            stmt = f"ALTER TABLE markets ADD COLUMN category_source {CATEGORY_SOURCE_DDL}"
            print(f"Executing: {stmt}")
            conn.execute(stmt)
        else:
            print("category_source column already present, skipping ALTER.")

        if not have_tbl:
            print("Executing: CREATE TABLE category_classification_log ...")
            conn.execute(LOG_TABLE_SQL.strip())
        else:
            print("category_classification_log already present, skipping CREATE.")

        if not have_backfill:
            print(f"Executing: {BACKFILL_SQL}")
            n = conn.execute(BACKFILL_SQL).rowcount
            print(f"  rows set to 'legacy': {n}")
        else:
            print("legacy backfill already complete, skipping UPDATE.")

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # final check
    cols = markets_columns(conn)
    ok = (
        "category_source" in cols
        and has_table(conn, "category_classification_log")
        and legacy_count(conn) == geo_elec_count(conn)
        and geo_elec_count(conn) > 0
    )
    print(f"\nFinal: column={('category_source' in cols)} "
          f"table={has_table(conn, 'category_classification_log')} "
          f"legacy_rows={legacy_count(conn)} geo_elec={geo_elec_count(conn)}")
    if not ok:
        print("[ERROR] migration incomplete")
        return 1
    print("[OK] classifier-provenance schema migration complete.")
    return 0


def do_revert(conn, dry_run):
    cols = markets_columns(conn)
    have_col = "category_source" in cols
    have_tbl = has_table(conn, "category_classification_log")
    print(f"markets.category_source present : {have_col}")
    print(f"category_classification_log tbl : {have_tbl}")
    if have_tbl:
        rows = conn.execute("SELECT COUNT(*) FROM category_classification_log").fetchone()[0]
        print(f"  log rows that WILL BE DROPPED : {rows}")

    if dry_run:
        print("[DRY RUN] no changes made")
        return 0

    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if have_tbl:
            print("Executing: DROP TABLE category_classification_log")
            conn.execute("DROP TABLE category_classification_log")
        if have_col:
            print("Executing: ALTER TABLE markets DROP COLUMN category_source")
            conn.execute("ALTER TABLE markets DROP COLUMN category_source")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    cols = markets_columns(conn)
    ok = "category_source" not in cols and not has_table(conn, "category_classification_log")
    print(f"\nFinal: column_present={('category_source' in cols)} "
          f"table_present={has_table(conn, 'category_classification_log')}")
    print("[OK] revert complete." if ok else "[ERROR] revert incomplete")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change, do not write")
    ap.add_argument("--revert", action="store_true",
                    help="drop the column and the sidecar table")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        if args.revert:
            return do_revert(conn, args.dry_run)
        return do_migrate(conn, args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
