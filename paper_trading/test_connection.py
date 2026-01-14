#!/usr/bin/env python3
"""
Test Polymarket API Connection

Verifies:
1. API connection works
2. Can fetch markets
3. Can get market prices
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trading.polymarket_client import PolymarketClient


def main():
    print("=" * 60)
    print("  POLYMARKET API CONNECTION TEST")
    print("=" * 60)
    print()

    try:
        print("[1/4] Initializing client...")
        client = PolymarketClient()
        print("      [OK] Client initialized\n")

        # Test fetching markets
        print("[2/4] Testing market fetch...")
        markets = client.get_active_markets(limit=10)

        if markets:
            print(f"      [OK] Fetched {len(markets)} active markets\n")

            # Show sample markets
            print("[3/4] Sample markets:")
            for i, m in enumerate(markets[:3], 1):
                title = m.get('question', m.get('title', 'Unknown'))[:55]
                category = m.get('category', 'Unknown')
                print(f"      {i}. {title}...")
                print(f"         Category: {category}")

                # Get price
                price_data = client.get_market_price(m)
                if price_data:
                    print(f"         YES: ${price_data['yes_price']:.3f}, NO: ${price_data['no_price']:.3f}")
                print()
        else:
            print("      [WARN] No markets returned\n")

        # Summary
        print("[4/4] Connection test results:")
        if markets:
            print("      [OK] API connection: WORKING")
            print("      [OK] Market data: AVAILABLE")
            print(f"      [OK] Markets found: {len(markets)}")
            print()
            print("      SUCCESS - Ready for paper trading!")
        else:
            print("      [!!] API connection: WORKING (but no markets)")
            print("      [!!] Check API status or try again later")

    except Exception as e:
        print(f"\n[ERROR] Connection test failed: {e}")
        import traceback
        traceback.print_exc()

        print("\nTroubleshooting:")
        print("  1. Check .env file has POLYMARKET_API_KEY set")
        print("  2. Verify API key is valid at polymarket.com")
        print("  3. Check internet connection")
        print("  4. Try: pip install requests python-dotenv")

    print()
    print("=" * 60)


if __name__ == '__main__':
    main()
