#!/usr/bin/env python3
"""
Debug script to test trade detection for flagged traders.
"""

import os
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient
from monitoring.database import Database

load_dotenv()


def debug_trade_detection():
    """Debug why new trades aren't being detected."""
    print("="*70)
    print("DEBUGGING TRADE DETECTION")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    client = PolymarketClient(api_key)
    db = Database()

    # Get flagged traders
    flagged_traders = db.get_flagged_traders()
    print(f"\n✅ Found {len(flagged_traders)} flagged traders in database")

    if not flagged_traders:
        print("❌ No flagged traders! Run the tracker first to flag some traders.")
        return

    # Test the first 3 traders
    print("\n" + "="*70)
    print("TESTING TRADER HISTORY FETCHING")
    print("="*70)

    for i, trader in enumerate(flagged_traders[:3], 1):
        print(f"\n{i}. Testing trader: {trader}")
        print("-"*70)

        # Try to get their trade history
        print("Calling get_trader_history()...")
        trades = client.get_trader_history(trader, limit=10)

        print(f"Result: {len(trades)} trades returned")

        if trades:
            print("\n✅ Trades found! Sample trade:")
            trade = trades[0]
            print(f"  Trade ID: {trade.get('id') or trade.get('transactionHash', 'N/A')}")
            print(f"  Trader (proxyWallet): {trade.get('proxyWallet', 'N/A')}")
            print(f"  Size: {trade.get('size', 0)}")
            print(f"  Price: {trade.get('price', 0)}")
            print(f"  Timestamp: {trade.get('timestamp', 'N/A')}")
            print(f"  Market: {trade.get('conditionId', 'N/A')[:20]}...")
        else:
            print("❌ No trades returned!")
            print("\nPossible reasons:")
            print("  1. Data API 'user' parameter doesn't work with proxyWallet")
            print("  2. API error (check for error messages above)")
            print("  3. Trader has no recent trades")

    # Test alternative: fetch all recent trades and filter
    print("\n" + "="*70)
    print("ALTERNATIVE APPROACH: Fetch all trades and filter")
    print("="*70)

    print("\nFetching 500 recent trades globally...")
    all_trades = client.get_market_trades(market_id=None, limit=500)
    print(f"✅ Got {len(all_trades)} trades")

    # Filter for our flagged traders
    flagged_set = set(flagged_traders)
    relevant_trades = []

    for trade in all_trades:
        trader = trade.get('proxyWallet')
        if trader in flagged_set:
            relevant_trades.append(trade)

    print(f"\n✅ Found {len(relevant_trades)} trades from flagged traders")

    if relevant_trades:
        print("\nSample relevant trade:")
        trade = relevant_trades[0]
        print(f"  Trader: {trade.get('proxyWallet')}")
        print(f"  Market: {trade.get('title', 'N/A')[:50]}")
        print(f"  Size: {trade.get('size', 0)}")
        print(f"  Price: {trade.get('price', 0)}")
        print(f"  Timestamp: {trade.get('timestamp', 'N/A')}")

    # Check database
    print("\n" + "="*70)
    print("CHECKING DATABASE")
    print("="*70)

    # See how many trades are already in the database
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades")
    trade_count = cursor.fetchone()[0]
    conn.close()

    print(f"\nTrades in database: {trade_count}")

    if trade_count == 0:
        print("❌ No trades in database!")
        print("This explains why check_for_new_trades() finds 0 new trades.")
        print("The initial scan doesn't add trades to the database.")

    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)

    if len(trades) == 0:
        print("\n1. Data API 'user' parameter doesn't work with proxyWallet addresses")
        print("   SOLUTION: Change strategy to fetch all recent trades and filter locally")

    if len(relevant_trades) > 0:
        print("\n2. Alternative approach (fetch all + filter) WORKS!")
        print(f"   Found {len(relevant_trades)} relevant trades this way")
        print("   SOLUTION: Update check_for_new_trades() to use this approach")

    print("\n3. Consider storing initial trades in database during scan")
    print("   This would establish a baseline for detecting 'new' trades")


if __name__ == "__main__":
    debug_trade_detection()
