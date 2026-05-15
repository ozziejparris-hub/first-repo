#!/usr/bin/env python3
"""
Evaluate pending trade results for flagged, non-excluded traders only.

Targets: is_flagged=1, research_excluded=0, trade_result='pending',
         in a market where resolved=1 and winning_outcome is set.

After evaluation, updates resolved_trades_count for those traders.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlite3
from monitoring.database import Database
from monitoring.polymarket_client import PolymarketClient
from monitoring.trade_evaluator import TradeEvaluator
from dotenv import load_dotenv

load_dotenv()


def main():
    db = Database()
    api_key = os.getenv("POLYMARKET_API_KEY")
    client = PolymarketClient(api_key)
    evaluator = TradeEvaluator(db, client)

    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.trade_id,
            t.trader_address,
            t.outcome_bet,
            t.outcome,
            t.side,
            m.condition_id,
            m.winning_outcome
        FROM trades t
        JOIN markets m ON m.condition_id = t.market_id
        JOIN traders tr ON tr.address = t.trader_address
        WHERE t.trade_result = 'pending'
          AND m.resolved = 1
          AND m.winning_outcome IS NOT NULL
          AND m.winning_outcome != ''
          AND tr.is_flagged = 1
          AND tr.research_excluded = 0
    """)
    pending = [dict(row) for row in cursor.fetchall()]
    conn.close()

    traders_seen = set()
    evaluated = 0
    for trade in pending:
        result = evaluator.evaluate_trade(trade, trade['winning_outcome'])
        db.update_trade_result(trade['trade_id'], result)
        traders_seen.add(trade['trader_address'])
        evaluated += 1

    conn2 = db.get_connection()
    cursor2 = conn2.cursor()
    cursor2.execute("""
        UPDATE traders
        SET resolved_trades_count = (
            SELECT COUNT(DISTINCT t.market_id)
            FROM trades t
            JOIN markets m ON m.condition_id = t.market_id
            WHERE t.trader_address = traders.address
              AND m.resolved = 1
              AND t.trade_result IN ('won', 'lost')
        )
        WHERE is_flagged = 1
          AND research_excluded = 0
    """)
    conn2.commit()
    conn2.close()

    print(f"Evaluated {evaluated} trades for {len(traders_seen)} traders. resolved_trades_count updated.")


if __name__ == "__main__":
    main()
