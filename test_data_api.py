#!/usr/bin/env python3
"""
Quick test to verify trades fetching works with Data API.
"""

import os
from dotenv import load_dotenv
from polymarket_client import PolymarketClient

load_dotenv()


def test_data_api_trades():
    """Test that we can fetch trades using the Data API."""
    print("="*70)
    print("TESTING DATA API TRADES FETCHING")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    client = PolymarketClient(api_key)

    print("\n📊 Test 1: Fetch recent trades (no market filter)")
    print("-"*70)

    trades = client.get_market_trades(market_id=None, limit=10)
    print(f"✅ Fetched {len(trades)} trades")

    if trades:
        print("\nSample trade structure:")
        trade = trades[0]
        for key in sorted(trade.keys()):
            value = str(trade[key])[:60]
            print(f"  {key:20} {value}")

        # Check for trader addresses
        maker = trade.get('makerAddress') or trade.get('maker') or trade.get('user')
        print(f"\nTrader address found: {maker[:16] if maker else 'None'}...")

    print("\n" + "="*70)
    print("Test 2: Fetch geopolitics markets and extract traders")
    print("="*70)

    geo_markets = client.get_markets(category="Geopolitics", limit=20)
    print(f"Found {len(geo_markets)} geopolitics markets")

    traders = client.get_active_traders_from_markets(geo_markets)
    print(f"\n✅ Found {len(traders)} unique traders")

    if traders:
        print("\nSample trader addresses:")
        for i, trader in enumerate(list(traders)[:5], 1):
            print(f"  {i}. {trader}")

    print("\n" + "="*70)
    print("✅ DATA API TEST COMPLETE")
    print("="*70)

    if len(trades) > 0 and len(traders) > 0:
        print("\n🎉 SUCCESS! Trades API is working!")
    else:
        print("\n⚠️ Some issues detected, but API is accessible")


if __name__ == "__main__":
    test_data_api_trades()
