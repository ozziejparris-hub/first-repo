#!/usr/bin/env python3
"""
Test script to debug Polymarket API connectivity and market fetching.
"""

import os
import requests
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient

# Load environment variables
load_dotenv()

def test_raw_api_call_no_auth():
    """Test raw API call without authentication."""
    print("="*70)
    print("TEST 1: Raw API Call (No Authentication)")
    print("="*70)

    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "closed": False,
        "archived": False,
        "limit": 5
    }

    print(f"\nURL: {url}")
    print(f"Params: {params}\n")

    try:
        response = requests.get(url, params=params, timeout=30)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✅ Success without auth!")
            print(f"Response type: {type(data)}")

            if isinstance(data, list):
                print(f"Number of markets: {len(data)}")
            elif isinstance(data, dict):
                print(f"Response keys: {list(data.keys())}")
        else:
            print(f"❌ Status {response.status_code}: {response.text}")

    except Exception as e:
        print(f"❌ Exception: {e}")

    print("\n")


def test_with_api_key():
    """Test API call WITH API key."""
    print("="*70)
    print("TEST 2: API Call WITH API Key")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")

    if not api_key:
        print("⚠️ No POLYMARKET_API_KEY found in .env file")
        print("Please create a .env file with your API key:")
        print("  POLYMARKET_API_KEY=your_key_here")
        print("\n")
        return

    print(f"API Key loaded: {api_key[:8]}...{api_key[-4:]}\n")

    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "closed": False,
        "archived": False,
        "limit": 5
    }

    # Try multiple header approaches
    test_cases = [
        {"Authorization": f"Bearer {api_key}"},
        {"X-API-Key": api_key},
        {"APIKEY": api_key},
        {"api-key": api_key}
    ]

    for i, headers in enumerate(test_cases, 1):
        print(f"Try #{i}: Using header {list(headers.keys())[0]}")
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            print(f"  Status: {response.status_code}")

            if response.status_code == 200:
                print(f"  ✅ Success with this header format!")
                data = response.json()
                if isinstance(data, list):
                    print(f"  Got {len(data)} markets")
                return
        except Exception as e:
            print(f"  ❌ Error: {e}")

    print("\n")


def test_polymarket_client():
    """Test the updated PolymarketClient implementation."""
    print("="*70)
    print("TEST 3: Updated PolymarketClient")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")

    if not api_key:
        print("⚠️ Testing without API key (public access)\n")

    # Test with and without API key
    client = PolymarketClient(api_key)

    # First test connection
    print("Testing API connection...")
    connection_ok = client.test_connection()

    if not connection_ok:
        print("\n❌ API connection failed. Cannot proceed with further tests.")
        print("\nPossible reasons:")
        print("1. API requires authentication (need valid API key)")
        print("2. Network/proxy issues")
        print("3. API endpoint has changed")
        print("4. Rate limiting")
        return

    print("\nFetching all markets (no filter)...")
    all_markets = client.get_all_markets(limit=20)

    if len(all_markets) > 0:
        print(f"✅ Got {len(all_markets)} markets!")
        print("\nSample market:")
        market = all_markets[0]
        print(f"  Question: {market.get('question', 'N/A')}")
        print(f"  ID: {market.get('id', 'N/A')}")
        print(f"  Tags: {market.get('tags', [])}")

        # Show available tags
        all_tags = set()
        for m in all_markets[:10]:
            all_tags.update(m.get('tags', []))
        print(f"\n  Available tags (from first 10 markets): {sorted(all_tags)[:15]}")

    print("\n")

    # Now test geopolitics filter
    print("Fetching geopolitics markets...")
    geo_markets = client.get_markets(category="Geopolitics", limit=100)

    print(f"Geopolitics markets found: {len(geo_markets)}")

    if len(geo_markets) > 0:
        print("\n✅ Success! Sample geopolitics markets:")
        for i, market in enumerate(geo_markets[:3], 1):
            print(f"\n  {i}. {market.get('question', 'N/A')[:70]}")
            print(f"     Tags: {market.get('tags', [])}")
    else:
        print("⚠️ No geopolitics markets found")

    print("\n")


def main():
    """Run all tests."""
    print("\n🔍 Polymarket API Debugging Suite\n")

    # Check for .env file
    if not os.path.exists('.env'):
        print("⚠️" + "="*68)
        print("WARNING: No .env file found!")
        print("="*70)
        print("To use your API key, create a .env file with:")
        print("  POLYMARKET_API_KEY=your_key_here")
        print("="*70 + "\n")

    # Run all tests
    test_raw_api_call_no_auth()
    test_with_api_key()
    test_polymarket_client()

    print("="*70)
    print("Testing Complete!")
    print("="*70)
    print("\nSummary:")
    print("- If all tests failed with 403/Access denied: API requires authentication")
    print("- Create .env file with POLYMARKET_API_KEY to authenticate")
    print("- If still failing: API key may be invalid or API structure changed")
    print("="*70)


if __name__ == "__main__":
    main()
