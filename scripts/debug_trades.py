#!/usr/bin/env python3
"""
Debug script to test different approaches for fetching trades from Polymarket.
"""

import os
import requests
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient

load_dotenv()


def test_clob_trades_endpoint():
    """Test the CLOB trades endpoint with different approaches."""
    print("="*70)
    print("DEBUGGING POLYMARKET TRADES ENDPOINTS")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    client = PolymarketClient(api_key)

    # First, get a sample market
    print("\n📊 Fetching sample markets...")
    markets = client.get_all_markets(limit=5)

    if not markets:
        print("❌ No markets fetched")
        return

    sample_market = markets[0]
    print(f"\n✅ Sample market: {sample_market.get('question', 'N/A')[:60]}")
    print(f"   Market ID: {sample_market.get('id')}")
    print(f"   Condition ID: {sample_market.get('conditionId', 'N/A')}")

    # Extract useful IDs
    market_id = sample_market.get('id')
    condition_id = sample_market.get('conditionId')

    print("\n" + "="*70)
    print("TEST 1: CLOB API - /trades endpoint")
    print("="*70)

    # Test different parameter combinations
    test_cases = [
        {"name": "With market ID", "params": {"market": market_id}},
        {"name": "With condition ID", "params": {"condition_id": condition_id}},
        {"name": "With asset_id", "params": {"asset_id": market_id}},
        {"name": "No parameters", "params": {}},
    ]

    clob_url = "https://clob.polymarket.com/trades"

    for test in test_cases:
        print(f"\n{test['name']}:")
        print(f"  URL: {clob_url}")
        print(f"  Params: {test['params']}")

        try:
            response = requests.get(clob_url, params=test['params'], timeout=10)
            print(f"  Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    print(f"  ✅ Success! Got {len(data)} trades")
                    if data:
                        print(f"  Sample trade keys: {list(data[0].keys())[:10]}")
                elif isinstance(data, dict):
                    print(f"  ✅ Success! Response keys: {list(data.keys())}")
            else:
                print(f"  ❌ Error: {response.text[:100]}")

        except Exception as e:
            print(f"  ❌ Exception: {e}")

    print("\n" + "="*70)
    print("TEST 2: Data API - Different endpoint")
    print("="*70)

    # Try the data API instead
    data_api_url = "https://data-api.polymarket.com/trades"

    test_cases_data = [
        {"name": "Data API with market", "params": {"market": condition_id}},
        {"name": "Data API no params", "params": {"limit": 10}},
    ]

    for test in test_cases_data:
        print(f"\n{test['name']}:")
        print(f"  URL: {data_api_url}")
        print(f"  Params: {test['params']}")

        try:
            response = requests.get(data_api_url, params=test['params'], timeout=10)
            print(f"  Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    print(f"  ✅ Success! Got {len(data)} trades")
                elif isinstance(data, dict):
                    print(f"  ✅ Success! Response keys: {list(data.keys())}")
            else:
                print(f"  ❌ Error: {response.text[:100]}")

        except Exception as e:
            print(f"  ❌ Exception: {e}")

    print("\n" + "="*70)
    print("TEST 3: Check market structure for trade-related fields")
    print("="*70)

    # Look for any trade-related URLs or endpoints in the market data
    print("\nChecking market object for trade-related fields:")
    trade_related_fields = ['trades', 'trade', 'clob', 'orderbook', 'book']

    for key, value in sample_market.items():
        key_lower = key.lower()
        if any(field in key_lower for field in trade_related_fields):
            value_str = str(value)[:100] if len(str(value)) > 100 else str(value)
            print(f"  {key}: {value_str}")

    # Check if there's a clobTokenIds field
    clob_token_ids = sample_market.get('clobTokenIds')
    if clob_token_ids:
        print(f"\n  clobTokenIds found: {clob_token_ids}")

    print("\n" + "="*70)
    print("TEST 4: Try fetching with token IDs")
    print("="*70)

    # Try using token IDs if available
    if clob_token_ids:
        try:
            import json
            token_ids = json.loads(clob_token_ids) if isinstance(clob_token_ids, str) else clob_token_ids
            print(f"\nToken IDs: {token_ids}")

            if token_ids and len(token_ids) > 0:
                first_token = token_ids[0]
                print(f"\nTrying with first token ID: {first_token}")

                response = requests.get(
                    clob_url,
                    params={"token_id": first_token, "limit": 10},
                    timeout=10
                )

                print(f"Status: {response.status_code}")
                if response.status_code == 200:
                    print("✅ Success with token ID!")
                else:
                    print(f"❌ Error: {response.text[:100]}")

        except Exception as e:
            print(f"Error with token IDs: {e}")

    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)

    print("\nBased on the tests above, we need to:")
    print("1. Identify which endpoint and parameters work")
    print("2. Update polymarket_client.py to use the correct approach")
    print("3. Consider if we need to use conditionId or token IDs instead")


if __name__ == "__main__":
    test_clob_trades_endpoint()
