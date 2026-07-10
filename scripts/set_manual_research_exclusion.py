#!/usr/bin/env python3
"""
Durably exclude a trader from the research pool.

Sets research_excluded=1 AND manual_override=1 (plus a recorded reason) so
update_research_exclusions.py's daily recompute (CLEAR_SQL / LEADERBOARD_CLEAR_SQL)
can never silently revert it — the state machine treats manual_override=1 as a hard
stop regardless of resolved_trades_count/bot_suspect/wash_trade_suspect/bot_type.

O-23 (Fable finding 2.5): before this script existed, manual exclusions were applied
as bare `UPDATE traders SET research_excluded=1 ...` with nothing durable behind
them, so the next daily run silently reverted any exclusion not backed by one of the
recomputed conditions. Use this script for every future manual exclusion instead.

Usage:
    python3 scripts/set_manual_research_exclusion.py <address> "<reason>"

To reverse a manual exclusion (clear the override so the state machine's normal
recompute applies again), use --clear:
    python3 scripts/set_manual_research_exclusion.py <address> --clear
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[1] == "--clear":
        address = args[0]
        clear = True
        reason = None
    elif len(args) == 2:
        address, reason = args
        clear = False
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    before = conn.execute(
        "SELECT research_excluded, manual_override, manual_exclusion_reason "
        "FROM traders WHERE address = ?",
        (address,),
    ).fetchone()
    if before is None:
        print(f"[ERROR] No trader found with address={address!r}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    if clear:
        conn.execute(
            "UPDATE traders SET manual_override = 0, manual_exclusion_reason = NULL "
            "WHERE address = ?",
            (address,),
        )
        conn.commit()
        print(f"[OK] {address}: manual_override cleared (research_excluded left at "
              f"{before[0]} — daily recompute now governs this trader again).")
    else:
        conn.execute(
            "UPDATE traders SET research_excluded = 1, manual_override = 1, "
            "manual_exclusion_reason = ? WHERE address = ?",
            (reason, address),
        )
        conn.commit()
        print(f"[OK] {address}: research_excluded {before[0]} -> 1, manual_override "
              f"{before[1]} -> 1. Reason: {reason}")

    conn.close()


if __name__ == "__main__":
    main()
