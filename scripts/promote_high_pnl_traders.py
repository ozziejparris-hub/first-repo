#!/usr/bin/env python3
"""
Promotes traders with realized_pnl > $50K into the monitored pool.
Runs daily as a non-blocking step in daily_maintenance.py.
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"


def main():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    try:
        cur = con.execute("""
            UPDATE traders
            SET is_flagged = 1,
                research_excluded = 0
            WHERE realized_pnl > 50000
              AND bot_type IS NULL
              AND wash_trade_suspect = 0
              AND bot_suspect = 0
              AND (is_flagged = 0 OR research_excluded = 1)
        """)
        n = cur.rowcount
        con.commit()
    finally:
        con.close()

    print(f"Promoted {n} high-P&L traders to monitored pool (realized_pnl > $50K, no bot flags)")


if __name__ == "__main__":
    main()
