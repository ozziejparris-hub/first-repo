#!/usr/bin/env python3
"""
Stage 0 schema migration for the canonical resolution write design
(brain/decisions/2026-08-19-canonical-resolution-write-design.md §D, §G).

Adds three nullable columns to `markets`:
  - resolution_recorded_at     TIMESTAMP
  - resolution_evidence_source TEXT, CHECK (IN the 4 evidence sources OR NULL)
  - resolution_evidence_detail TEXT

And one trigger (design §G, tested at c75a906 Q3):
  - trg_resolved_no_unresolve  BEFORE UPDATE OF resolved, aborts a 1->0
    transition. Verified to break no existing writer.

Explicitly NOT done here, per design D and this task's constraints:
  - No backfill of existing rows. NULL is the honest state for rows
    predating this migration -- see design §D.
  - trg_require_recorded_at is NOT created here -- design §G places it at
    Stage 5, after all 13 writers are migrated; creating it now would break
    every one of them (verified empirically, c75a906 Q3b).

Idempotent: safe to re-run -- checks for existing columns/trigger before
adding them.
"""

import argparse
import sqlite3
import sys

DEFAULT_DB = "data/polymarket_tracker.db"

NEW_COLUMNS = [
    ("resolution_recorded_at", "TIMESTAMP"),
    (
        "resolution_evidence_source",
        "TEXT CHECK (resolution_evidence_source IN "
        "('clob','gamma','manual_verified','hydration_fill') "
        "OR resolution_evidence_source IS NULL)",
    ),
    ("resolution_evidence_detail", "TEXT"),
]

TRIGGER_SQL = """
CREATE TRIGGER trg_resolved_no_unresolve
BEFORE UPDATE OF resolved ON markets
WHEN OLD.resolved = 1 AND NEW.resolved = 0
BEGIN
    SELECT RAISE(ABORT, 'resolved cannot transition from 1 to 0');
END;
"""


def existing_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}


def existing_triggers(conn):
    return {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'"
    ).fetchall()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true", help="report what would change, do not write")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cols = existing_columns(conn)
    triggers = existing_triggers(conn)

    to_add = [(name, ddl) for name, ddl in NEW_COLUMNS if name not in cols]
    need_trigger = "trg_resolved_no_unresolve" not in triggers

    print(f"Columns already present: {sorted(c for c, _ in NEW_COLUMNS if c in cols)}")
    print(f"Columns to add: {[c for c, _ in to_add]}")
    print(f"Trigger already present: {not need_trigger}")

    if args.dry_run:
        print("[DRY RUN] no changes made")
        return 0

    for name, ddl in to_add:
        stmt = f"ALTER TABLE markets ADD COLUMN {name} {ddl}"
        print(f"Executing: {stmt}")
        conn.execute(stmt)
        conn.commit()

    if need_trigger:
        print(f"Executing:\n{TRIGGER_SQL}")
        conn.executescript(TRIGGER_SQL)
        conn.commit()
    else:
        print("Trigger trg_resolved_no_unresolve already exists, skipping.")

    # Report final state.
    final_cols = existing_columns(conn)
    final_triggers = existing_triggers(conn)
    print(f"\nFinal check -- columns present: {[c for c, _ in NEW_COLUMNS if c in final_cols]}")
    print(f"Final check -- trigger present: {'trg_resolved_no_unresolve' in final_triggers}")

    missing_cols = [c for c, _ in NEW_COLUMNS if c not in final_cols]
    if missing_cols or "trg_resolved_no_unresolve" not in final_triggers:
        print(f"[ERROR] migration incomplete -- missing columns: {missing_cols}, "
              f"trigger present: {'trg_resolved_no_unresolve' in final_triggers}")
        return 1

    print("\n[OK] Stage 0 schema migration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
