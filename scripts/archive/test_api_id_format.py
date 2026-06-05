#!/usr/bin/env python3
"""
Test Polymarket API ID format
Tests what ID format the /markets/{id} endpoint expects
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('POLYMARKET_API_KEY')

# Test with a conditionId from our database
condition_id = "0x9bacdaac65cbe257e96e58daf343c56879ea9003bdaed7cdb8cfcd1a82121d3a"

print("="*70)
print("TESTING POLYMARKET API ID FORMATS")
print("="*70 + "\n")

print(f"Test 1: Using conditionId with /markets/ endpoint")
print(f"URL: https://gamma-api.polymarket.com/markets/{condition_id}")
print()

response = requests.get(
    f"https://gamma-api.polymarket.com/markets/{condition_id}",
    headers={"User-Agent": "PolymarketTracker/1.0"},
    timeout=10
)

print(f"Status Code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print(f"SUCCESS! API returned data")
    print(f"Available keys: {list(data.keys())}")
else:
    print(f"FAILED! Response: {response.text[:200]}")

print("\n" + "="*70)
print("Test 2: Get fresh markets to see ID structure")
print("="*70 + "\n")

response = requests.get(
    "https://gamma-api.polymarket.com/markets",
    params={"limit": 1, "closed": "false"},
    headers={"User-Agent": "PolymarketTracker/1.0"},
    timeout=10
)

if response.status_code == 200:
    data = response.json()

    if isinstance(data, list):
        markets = data
    elif isinstance(data, dict) and 'data' in data:
        markets = data['data']
    else:
        markets = []

    if markets:
        print("Sample market from API:")
        market = markets[0]

        print("\nAll ID-related fields:")
        for key in market.keys():
            if 'id' in key.lower() or key == 'slug':
                print(f"  {key}: {market[key]}")

        print("\n" + "="*70)
        print("Test 3: Try fetching this market with its 'id' field")
        print("="*70 + "\n")

        market_id = market.get('id')

        if market_id:
            print(f"Using 'id' field: {market_id}")
            print(f"URL: https://gamma-api.polymarket.com/markets/{market_id}")

            response2 = requests.get(
                f"https://gamma-api.polymarket.com/markets/{market_id}",
                headers={"User-Agent": "PolymarketTracker/1.0"},
                timeout=10
            )

            print(f"Status Code: {response2.status_code}")

            if response2.status_code == 200:
                print("SUCCESS! 'id' field works with /markets/{id} endpoint")
            else:
                print(f"FAILED with 'id' field: {response2.text[:200]}")

print("\n" + "="*70)
print("CONCLUSION")
print("="*70)
print("\nThe /markets/{id} endpoint expects:")
print("  - NOT conditionId (0x...)")
print("  - Likely the 'id' field from market responses")
print("\nFIX REQUIRED:")
print("  1. Update store_market_dict() to store 'id' field")
print("  2. Keep conditionId in a separate column")
print("  3. Use 'id' for API calls, conditionId for trade matching")
