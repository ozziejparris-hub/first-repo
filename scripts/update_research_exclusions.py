#!/usr/bin/env python3
"""
Maintain the research_excluded flag on the traders table.

Run this before any analysis pipeline step. It re-applies the exclusion
criteria so that traders added or updated since the last run are correctly
classified without requiring a full ELO recalculation.

Auto-tagging (applied each run, before exclusion pass):
  - Tier 1b LP_ARTIFACT: pos_count > 500, market_count < 3, ELO < 700
    Single-market LP bots. ELO < 700 is a clean natural break.
  - ARB_BOT: pos_count 500–1000, market_count < 3, ELO 1500–3500
    Coordinated arb bot farms exploiting single-market mispricing.
    Evidence: 111 wallets, Nov 2025 geopolitics market, $1.9M–$6.2M each.

Exclusion criteria (ANY of these → excluded):
  - resolved_trades_count < 20 or NULL
  - bot_suspect = 1
  - wash_trade_suspect = 1
  - bot_type IN ('LP_ARTIFACT', 'THIN_SAMPLE_ARTIFACT', 'ARB_BOT')

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

# --- Tier 1b LP_ARTIFACT auto-tagger ---
# High-position, single-market, low-ELO bots. Pattern identical to Tier 1
# (pos_count > 1000) but with slightly fewer positions. ELO < 700 is a clean
# natural break — nothing observed in the 649–1500 range.
LP_ARTIFACT_TIER1B_TAG_SQL = """
UPDATE traders
SET bot_type = 'LP_ARTIFACT'
WHERE bot_type IS NULL
  AND research_excluded = 0
  AND comprehensive_elo < 700
  AND address IN (
    SELECT trader_address
    FROM positions
    GROUP BY trader_address
    HAVING COUNT(position_id) > 500
       AND COUNT(DISTINCT market_id) < 3
  )
"""

# --- ARB_BOT auto-tagger ---
# Coordinated arbitrage bot farms that exploit single-market mispricing.
# Evidence basis: 111 wallets trading a single resolved geopolitics market
# ("Will Iran recognize Israel by June 2025?") in a 10-day Nov 2025 window,
# earning $1.9M–$6.2M each via automated arb, clustering at ELO 3308–3315
# (a measurement artifact, not prediction skill).
ARB_BOT_TAG_SQL = """
UPDATE traders
SET bot_type = 'ARB_BOT'
WHERE bot_type IS NULL
  AND research_excluded = 0
  AND comprehensive_elo BETWEEN 1500 AND 3500
  AND address IN (
    SELECT trader_address
    FROM positions
    GROUP BY trader_address
    HAVING COUNT(position_id) BETWEEN 500 AND 1000
       AND COUNT(DISTINCT market_id) < 3
  )
"""

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
    OR bot_type IN ('LP_ARTIFACT', 'THIN_SAMPLE_ARTIFACT', 'ARB_BOT')
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

# Sync is_flagged to match research_excluded state.
# Run after all exclusion logic so is_flagged is always consistent.
SYNC_IS_FLAGGED_CLEAN_SQL = """
UPDATE traders
SET is_flagged = 1
WHERE research_excluded = 0
  AND resolved_trades_count >= 20
  AND bot_type IS NULL
  AND wash_trade_suspect = 0
  AND bot_suspect = 0
"""

SYNC_IS_FLAGGED_EXCLUDED_SQL = """
UPDATE traders
SET is_flagged = 0
WHERE research_excluded = 1
  AND (watched = 0 OR watched IS NULL)
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
            # Auto-tag new bots before the exclusion pass.
            lp_artifact_tagged = conn.execute(LP_ARTIFACT_TIER1B_TAG_SQL).rowcount
            arb_bot_tagged     = conn.execute(ARB_BOT_TAG_SQL).rowcount

            newly_excluded = conn.execute(EXCLUDE_SQL).rowcount
            newly_cleared  = conn.execute(CLEAR_SQL).rowcount

        # Sync is_flagged after all exclusion logic is complete.
        with conn:
            synced_flagged   = conn.execute(SYNC_IS_FLAGGED_CLEAN_SQL).rowcount
            synced_unflagged = conn.execute(SYNC_IS_FLAGGED_EXCLUDED_SQL).rowcount
        watched_preserved = conn.execute(
            "SELECT COUNT(*) FROM traders WHERE research_excluded = 1 AND watched = 1"
        ).fetchone()[0]

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
    print(f"  LP_ARTIFACT (Tier 1b) auto-tagged   : {lp_artifact_tagged:,} traders")
    print(f"  ARB_BOT auto-tagged                 : {arb_bot_tagged:,} traders")
    print(f"  Newly excluded        : {newly_excluded:,} traders")
    print(f"  Newly cleared         : {newly_cleared:,} traders")
    print(f"  Total clean pool      : {total_clean:,} traders")
    print(f"  Total excluded        : {total_excluded:,} traders")
    print(f"  Synced is_flagged: {synced_flagged:,} traders flagged, {synced_unflagged:,} traders unflagged ({watched_preserved:,} watched traders preserved)")


if __name__ == "__main__":
    main()
