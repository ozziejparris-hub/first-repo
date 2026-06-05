#!/usr/bin/env python3
"""
Test the updated keyword-based filtering for geopolitics markets.
"""

import os
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient

load_dotenv()


def test_geopolitics_filtering():
    """Test the geopolitics market filtering."""
    print("="*70)
    print("TESTING GEOPOLITICS MARKET FILTERING")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    if not api_key:
        print("❌ No POLYMARKET_API_KEY found in .env")
        return

    client = PolymarketClient(api_key)

    print("\n📊 Test 1: Fetch geopolitics markets with default limit (100)")
    print("-"*70)

    geo_markets = client.get_markets(category="Geopolitics", limit=100)

    print(f"\n✅ Found {len(geo_markets)} geopolitics markets")

    if geo_markets:
        print("\n📋 Sample geopolitics markets:")
        for i, market in enumerate(geo_markets[:10], 1):
            question = market.get('question', 'N/A')
            print(f"\n{i}. {question[:70]}")
            print(f"   ID: {market.get('id')}")

            # Show which keywords matched
            q_lower = question.lower()
            desc_lower = str(market.get('description', '')).lower()

            keywords = ['war', 'election', 'president', 'government',
                       'military', 'ukraine', 'russia', 'china', 'politics']

            matched = [kw for kw in keywords if kw in q_lower or kw in desc_lower]
            if matched:
                print(f"   Matched keywords: {', '.join(matched[:5])}")
    else:
        print("\n❌ No geopolitics markets found!")
        print("This might mean:")
        print("  - Keywords need adjustment")
        print("  - Need to fetch more markets (increase limit)")
        print("  - API returned different market types")

    # Test with larger limit
    print("\n" + "="*70)
    print("📊 Test 2: Fetch with larger limit (200)")
    print("-"*70)

    geo_markets_large = client.get_markets(category="Geopolitics", limit=200)
    print(f"\n✅ Found {len(geo_markets_large)} geopolitics markets (200 total fetched)")

    # Test other categories
    print("\n" + "="*70)
    print("📊 Test 3: Test other category filters")
    print("-"*70)

    categories_to_test = ["Politics", "Crypto", "Sports"]

    for cat in categories_to_test:
        markets = client.get_markets(category=cat, limit=100)
        print(f"\n{cat}: {len(markets)} markets found")
        if markets:
            print(f"  Sample: {markets[0].get('question', 'N/A')[:60]}...")

    # Statistics
    print("\n" + "="*70)
    print("STATISTICS")
    print("="*70)

    all_markets = client.get_all_markets(limit=200)

    if all_markets:
        print(f"\nTotal markets fetched: {len(all_markets)}")
        print(f"Geopolitics markets: {len(geo_markets_large)} ({len(geo_markets_large)/len(all_markets)*100:.1f}%)")

        # Show breakdown by keyword
        from collections import Counter

        keyword_counts = Counter()
        for market in geo_markets_large:
            question = market.get('question', '').lower()
            desc = market.get('description', '').lower()
            text = f"{question} {desc}"

            keywords = ['war', 'election', 'president', 'government',
                       'military', 'ukraine', 'russia', 'china', 'politics',
                       'congress', 'senate', 'iran', 'israel', 'nato']

            for kw in keywords:
                if kw in text:
                    keyword_counts[kw] += 1

        if keyword_counts:
            print("\nKeyword frequency in geopolitics markets:")
            for kw, count in keyword_counts.most_common(10):
                print(f"  {kw:15} {count} markets")

    print("\n" + "="*70)
    print("✅ FILTERING TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    test_geopolitics_filtering()
