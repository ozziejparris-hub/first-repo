#!/usr/bin/env python
"""
Requeue traders affected by newly resolved markets.

For each market that resolved since the last run, finds all traders who still
have open positions in that market (in the positions table) and resets their
pnl_last_updated to NULL. This forces the background P&L worker to re-process
them on its next cycle, where it will apply synthetic resolution closes.

Intended to run daily alongside apply_full_elo_modifiers.py, e.g.:
    python scripts/requeue_resolved_market_traders.py
    python scripts/apply_full_elo_modifiers.py

A timestamp file (data/.last_requeue_run) tracks when this last ran so only
genuinely new resolutions are acted on.  Use --force to ignore the timestamp.

Safe to run multiple times — resetting pnl_last_updated is idempotent.
"""
import os
import sys
import sqlite3
import argparse
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent
DB_PATH = project_root / "data" / "polymarket_tracker.db"
TIMESTAMP_FILE = project_root / "data" / ".last_requeue_run"


def _read_last_run() -> str:
    """Return ISO timestamp of last run, or a far-past date if never run."""
    if TIMESTAMP_FILE.exists():
        ts = TIMESTAMP_FILE.read_text().strip()
        if ts:
            return ts
    return "2000-01-01T00:00:00"


def _write_last_run():
    TIMESTAMP_FILE.write_text(datetime.now(timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser(description="Requeue traders in newly resolved markets")
    parser.add_argument("--force", action="store_true",
                        help="Ignore last-run timestamp and process all resolved markets")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing to DB")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    args = parser.parse_args()

    last_run = "2000-01-01T00:00:00" if args.force else _read_last_run()

    print("=" * 60)
    print("  REQUEUE TRADERS FOR NEWLY RESOLVED MARKETS")
    print("=" * 60)
    print(f"  Database  : {args.db}")
    print(f"  Since     : {last_run}" + (" (FORCED — all markets)" if args.force else ""))
    if args.dry_run:
        print("  *** DRY RUN — no changes will be written ***")
    print()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    cur = conn.cursor()

    # Find markets that resolved since last run
    cur.execute("""
        SELECT condition_id, winning_outcome, resolution_date, title
        FROM markets
        WHERE resolved = 1
          AND winning_outcome IS NOT NULL
          AND winning_outcome NOT IN ('', 'unknown')
          AND condition_id IS NOT NULL
          AND datetime(resolution_date) > datetime(?)
        ORDER BY resolution_date ASC
    """, (last_run,))
    newly_resolved = cur.fetchall()

    print(f"Markets resolved since last run: {len(newly_resolved)}")
    if not newly_resolved:
        print("  Nothing to do.")
        if not args.dry_run:
            _write_last_run()
        conn.close()
        return

    for cid, winning, res_date, title in newly_resolved:
        safe_title = (title or 'Unknown')[:60].encode('ascii', 'replace').decode('ascii')
        try:
            print(f"  [{res_date}] {safe_title}  winner: {winning}")
        except (OSError, UnicodeEncodeError):
            pass

    print()

    # For each newly resolved market, find traders with open positions
    condition_ids = [row[0] for row in newly_resolved]
    placeholders = ",".join("?" * len(condition_ids))

    cur.execute(f"""
        SELECT DISTINCT trader_address
        FROM positions
        WHERE status = 'open'
          AND market_id IN ({placeholders})
    """, condition_ids)
    traders_to_requeue = [row[0] for row in cur.fetchall()]

    print(f"Traders with open positions in these markets: {len(traders_to_requeue)}")

    if not traders_to_requeue:
        print("  No open positions found — all positions may already be closed.")
        if not args.dry_run:
            _write_last_run()
        conn.close()
        return

    if args.dry_run:
        for addr in traders_to_requeue[:20]:
            print(f"  Would requeue: {addr[:10]}...")
        if len(traders_to_requeue) > 20:
            print(f"  ... and {len(traders_to_requeue) - 20} more")
        print("\n  DRY RUN — no changes written.")
        conn.close()
        return

    # Reset pnl_last_updated to NULL → worker treats them as never-updated (highest priority)
    trader_placeholders = ",".join("?" * len(traders_to_requeue))
    cur.execute(f"""
        UPDATE traders
        SET pnl_last_updated = NULL
        WHERE address IN ({trader_placeholders})
    """, traders_to_requeue)
    updated = cur.rowcount
    conn.commit()
    conn.close()

    _write_last_run()

    print(f"Requeued {updated} traders (pnl_last_updated reset to NULL)")
    print("The background P&L worker will re-process them on its next cycle")
    print("and apply synthetic resolution closes for the newly resolved markets.")
    print()
    print("=" * 60)
    print("  COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
