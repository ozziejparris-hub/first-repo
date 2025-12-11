#!/usr/bin/env python3
"""
Backfill trade results for all resolved markets.

This script evaluates all trades in resolved markets to determine
which trades won/lost based on the market outcomes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.polymarket_client import PolymarketClient
from monitoring.trade_evaluator import TradeEvaluator
from dotenv import load_dotenv

load_dotenv()


def main():
    """Run backfill of trade results."""
    print("="*70)
    print("TRADE RESULTS BACKFILL")
    print("="*70)

    # Initialize components
    api_key = os.getenv("POLYMARKET_API_KEY")
    db = Database()
    client = PolymarketClient(api_key)
    evaluator = TradeEvaluator(db, client)

    # Show current state
    print("\nCurrent database state:")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
    resolved_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'pending'")
    pending_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'won'")
    won_trades = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'lost'")
    lost_trades = cursor.fetchone()[0]

    conn.close()

    print(f"  Resolved markets: {resolved_count}")
    print(f"  Total trades: {total_trades}")
    print(f"  Pending evaluation: {pending_trades}")
    print(f"  Already won: {won_trades}")
    print(f"  Already lost: {lost_trades}")

    # Confirm before proceeding
    print(f"\nThis will evaluate trades for {resolved_count} resolved markets.")
    proceed = input("Proceed? (yes/no): ").strip().lower()

    if proceed != 'yes':
        print("Cancelled.")
        return

    # Run batch evaluation
    results = evaluator.batch_evaluate_resolved_markets(verbose=True)

    # Show final state
    print("\nFinal database state:")

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'won'")
    final_won = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'lost'")
    final_lost = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE trade_result = 'pending'")
    final_pending = cursor.fetchone()[0]

    conn.close()

    print(f"  Won: {final_won} (+{final_won - won_trades})")
    print(f"  Lost: {final_lost} (+{final_lost - lost_trades})")
    print(f"  Still pending: {final_pending}")

    print("\n[SUCCESS] Backfill complete!")


if __name__ == "__main__":
    main()
