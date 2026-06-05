#!/usr/bin/env python3
"""Test trade evaluation with known resolved markets."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.polymarket_client import PolymarketClient
from monitoring.trade_evaluator import TradeEvaluator
from dotenv import load_dotenv

load_dotenv()


def test_trade_evaluation():
    """Test evaluation on first 5 resolved markets."""
    print("="*70)
    print("TESTING TRADE EVALUATION")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    db = Database()
    client = PolymarketClient(api_key)
    evaluator = TradeEvaluator(db, client)

    # Get first 5 resolved markets
    resolved = db.get_resolved_markets()[:5]

    print(f"\nTesting with {len(resolved)} resolved markets...\n")

    for market in resolved:
        market_id = market['market_id']
        title = market['title']
        winning_outcome = market['winning_outcome']

        print(f"\nMarket: {title[:60]}")
        print(f"Winner: {winning_outcome}")

        # Get trades for this market
        trades = db.get_trades_for_market(market_id)
        print(f"Trades: {len(trades)}")

        if trades:
            # Evaluate
            result = evaluator.evaluate_market_trades(market_id, winning_outcome, verbose=True)
            print(f"Results: {result['won']} won, {result['lost']} lost, {result['invalid']} invalid")

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    test_trade_evaluation()
