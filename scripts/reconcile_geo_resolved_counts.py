#!/usr/bin/env python3
"""
reconcile_geo_resolved_counts.py — ONE-TIME fix for inflated geo_resolved_trades_count.

The field stored trade-count (len of qualifying trades) instead of distinct geo
markets, due to a bug in update_geo_elo.py (fixed in commit dac9b2b). This recomputes
the correct value: COUNT(DISTINCT market_id) for won/lost trades on Geopolitics/Elections
markets (no price filter — the count gates pool eligibility, not ELO scoring).

Reports before/after and the Pool C / LEGENDARY membership change.

Usage:
  python3 reconcile_geo_resolved_counts.py --dry-run   # report only
  python3 reconcile_geo_resolved_counts.py             # apply
"""
import sqlite3
import argparse
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")

CORRECT_COUNT_SQL = """
    SELECT COUNT(DISTINCT tr.market_id)
    FROM trades tr
    JOIN markets m ON m.market_id = tr.market_id
    WHERE tr.trader_address = traders.address
      AND tr.trade_result IN ('won', 'lost')
      AND m.category IN ('Geopolitics', 'Elections')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    cur = conn.cursor()

    # BEFORE: pool state
    cur.execute("""SELECT COUNT(*) FROM traders WHERE geo_accuracy_pool = 1
                   AND research_excluded = 0""")
    pool_c_before = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM traders WHERE geo_elo_active >= 2175
                   AND geo_accuracy_pool = 1 AND research_excluded = 0 AND bot_type IS NULL""")
    legendary_before = cur.fetchone()[0]

    print(f"BEFORE: Pool C = {pool_c_before}, LEGENDARY = {legendary_before}")

    # How many traders will have their count changed?
    cur.execute(f"""
        SELECT COUNT(*) FROM traders
        WHERE (geo_resolved_trades_count IS NOT NULL OR geo_elo IS NOT NULL)
        AND geo_resolved_trades_count != ({CORRECT_COUNT_SQL})
    """)
    will_change = cur.fetchone()[0]
    print(f"Traders whose geo_resolved_trades_count will change: {will_change}")

    if args.dry_run:
        # Show projected Pool C drop (traders going below 5 distinct markets)
        cur.execute(f"""
            SELECT COUNT(*) FROM traders
            WHERE geo_accuracy_pool = 1 AND research_excluded = 0
            AND ({CORRECT_COUNT_SQL}) < 5
        """)
        would_drop = cur.fetchone()[0]
        print(f"DRY RUN — Pool C traders that would drop (distinct < 5): {would_drop}")

        cur.execute(f"""
            SELECT COUNT(*) FROM traders
            WHERE geo_elo_active >= 2175 AND geo_accuracy_pool = 1
            AND research_excluded = 0 AND bot_type IS NULL
            AND ({CORRECT_COUNT_SQL}) < 5
        """)
        leg_would_drop = cur.fetchone()[0]
        print(f"DRY RUN — LEGENDARY that would drop: {leg_would_drop}")
        conn.close()
        return

    # APPLY: reconcile the counts
    cur.execute(f"""
        UPDATE traders
        SET geo_resolved_trades_count = ({CORRECT_COUNT_SQL})
        WHERE geo_resolved_trades_count IS NOT NULL OR geo_elo IS NOT NULL
    """)
    conn.commit()
    print(f"Reconciled geo_resolved_trades_count for affected traders")

    # Now recompute Pool C membership with corrected counts
    # (mirror the gate from update_geo_elo.py)
    cur.execute("""
        UPDATE traders SET geo_accuracy_pool = 0
        WHERE geo_resolved_trades_count < 5
    """)
    conn.commit()
    print("Recomputed geo_accuracy_pool (set 0 where distinct geo markets < 5)")

    # AFTER: pool state
    cur.execute("""SELECT COUNT(*) FROM traders WHERE geo_accuracy_pool = 1
                   AND research_excluded = 0""")
    pool_c_after = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM traders WHERE geo_elo_active >= 2175
                   AND geo_accuracy_pool = 1 AND research_excluded = 0 AND bot_type IS NULL""")
    legendary_after = cur.fetchone()[0]

    print(f"\nAFTER:  Pool C = {pool_c_after} (was {pool_c_before}, -{pool_c_before-pool_c_after})")
    print(f"AFTER:  LEGENDARY = {legendary_after} (was {legendary_before}, -{legendary_before-legendary_after})")

    conn.close()


if __name__ == '__main__':
    main()
