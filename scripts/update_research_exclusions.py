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

LP focus ratio flagging (report only — no automatic exclusion):
  Traders with >20 resolved trades per distinct market are candidates for
  LP_ARTIFACT tagging, but require manual review before exclusion. Flagged
  traders are written to logs/focus_ratio_review.json for Oscar to approve.
  Do NOT set bot_type = 'LP_ARTIFACT' here — that triggers automatic exclusion.
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
LOGS_DIR = Path(__file__).parent.parent / "logs"
FOCUS_RATIO_REPORT = LOGS_DIR / "focus_ratio_review.json"

# Report-only query: identifies traders whose focus ratio exceeds 20× but does
# NOT update the DB. Results go to logs/focus_ratio_review.json for manual review.
# Traders must have >50 resolved trades to avoid thin-sample noise.
LP_FOCUS_RATIO_SELECT_SQL = """
SELECT
    t.address,
    t.resolved_trades_count,
    COUNT(DISTINCT p.market_id) AS distinct_markets,
    ROUND(t.resolved_trades_count * 1.0 / COUNT(DISTINCT p.market_id), 2) AS focus_ratio
FROM traders t
JOIN positions p ON p.trader_address = t.address
WHERE t.resolved_trades_count > 50
  AND t.bot_type IS NULL
  AND t.research_excluded = 0
GROUP BY t.address
HAVING COUNT(DISTINCT p.market_id) > 0
   AND t.resolved_trades_count * 1.0 / COUNT(DISTINCT p.market_id) > 20
ORDER BY focus_ratio DESC
"""

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
        # Identify focus-ratio candidates for review — NO DB write.
        focus_ratio_rows = conn.execute(LP_FOCUS_RATIO_SELECT_SQL).fetchall()
        lp_flagged = len(focus_ratio_rows)

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

    # Write focus-ratio candidates to review file (no DB changes made for these).
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "note": "Traders flagged by focus ratio > 20x. No DB exclusion applied — requires manual approval.",
        "count": lp_flagged,
        "traders": [
            {"address": r[0], "resolved_trades": r[1], "distinct_markets": r[2], "focus_ratio": r[3]}
            for r in focus_ratio_rows
        ],
    }
    FOCUS_RATIO_REPORT.write_text(json.dumps(report, indent=2))

    print("research_excluded update complete:")
    print(f"  LP focus ratio flagged (review only): {lp_flagged:,} traders → {FOCUS_RATIO_REPORT}")
    print(f"  Newly excluded        : {newly_excluded:,} traders")
    print(f"  Newly cleared         : {newly_cleared:,} traders")
    print(f"  Total clean pool      : {total_clean:,} traders")
    print(f"  Total excluded        : {total_excluded:,} traders")


if __name__ == "__main__":
    main()
