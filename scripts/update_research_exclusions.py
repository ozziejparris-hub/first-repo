#!/usr/bin/env python3
"""
Maintain the research_excluded flag on the traders table.

Run this before any analysis pipeline step. It re-applies the exclusion
criteria so that traders added or updated since the last run are correctly
classified without requiring a full ELO recalculation.

Exclusion criteria (ANY of these → excluded):
  - resolved_trades_count < 20 or NULL
  - bot_suspect = 1
  - wash_trade_suspect = 1
  - bot_type IN ('LP_ARTIFACT', 'THIN_SAMPLE_ARTIFACT')

Clear criteria (ALL must hold → cleared):
  - resolved_trades_count >= 20
  - bot_suspect = 0 or NULL
  - wash_trade_suspect = 0 or NULL
  - bot_type IS NULL
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"

EXCLUDE_SQL = """
UPDATE traders
SET research_excluded = 1
WHERE research_excluded = 0
  AND (
    resolved_trades_count < 20
    OR resolved_trades_count IS NULL
    OR bot_suspect = 1
    OR wash_trade_suspect = 1
    OR bot_type IN ('LP_ARTIFACT', 'THIN_SAMPLE_ARTIFACT')
  )
"""

CLEAR_SQL = """
UPDATE traders
SET research_excluded = 0
WHERE research_excluded = 1
  AND resolved_trades_count >= 20
  AND (bot_suspect = 0 OR bot_suspect IS NULL)
  AND (wash_trade_suspect = 0 OR wash_trade_suspect IS NULL)
  AND bot_type IS NULL
"""

SUMMARY_SQL = """
SELECT research_excluded, COUNT(*) as n
FROM traders
GROUP BY research_excluded
"""


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    try:
        with conn:
            newly_excluded = conn.execute(EXCLUDE_SQL).rowcount
            newly_cleared  = conn.execute(CLEAR_SQL).rowcount

        rows = {r[0]: r[1] for r in conn.execute(SUMMARY_SQL)}
        total_clean    = rows.get(0, 0)
        total_excluded = rows.get(1, 0)

    except Exception as e:
        print(f"[ERROR] research_excluded update failed, rolled back: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()

    print("research_excluded update complete:")
    print(f"  Newly excluded : {newly_excluded:,} traders")
    print(f"  Newly cleared  : {newly_cleared:,} traders")
    print(f"  Total clean pool  : {total_clean:,} traders")
    print(f"  Total excluded    : {total_excluded:,} traders")


if __name__ == "__main__":
    main()
