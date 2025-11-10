#!/usr/bin/env python3
"""
Script to explore Polymarket market data structure and categorization.
This will help us understand how to properly filter for geopolitics markets.
"""

import os
import json
from collections import Counter
from dotenv import load_dotenv
from polymarket_client import PolymarketClient

load_dotenv()


def explore_market_structure():
    """Fetch markets and analyze their structure."""
    print("="*70)
    print("POLYMARKET MARKET STRUCTURE EXPLORER")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    if not api_key:
        print("❌ No POLYMARKET_API_KEY found in .env")
        return

    client = PolymarketClient(api_key)

    # Fetch a good sample of markets
    print("\n📊 Fetching 200 markets for analysis...\n")
    markets = client.get_all_markets(limit=200)

    if not markets:
        print("❌ No markets returned. Check API connection.")
        return

    print(f"✅ Fetched {len(markets)} markets\n")

    # Analyze structure of first market
    print("="*70)
    print("SAMPLE MARKET STRUCTURE")
    print("="*70)

    if markets:
        sample = markets[0]
        print("\nKeys available in market object:")
        for key in sorted(sample.keys()):
            value = sample[key]
            value_type = type(value).__name__

            # Show sample value (truncated if long)
            if isinstance(value, (list, dict)):
                value_preview = f"{value_type} with {len(value)} items"
            elif isinstance(value, str) and len(value) > 60:
                value_preview = f"{value[:60]}..."
            else:
                value_preview = str(value)

            print(f"  {key:25} ({value_type:10}): {value_preview}")

    # Analyze tags
    print("\n" + "="*70)
    print("TAGS ANALYSIS")
    print("="*70)

    all_tags = []
    markets_with_tags = 0
    markets_without_tags = 0

    for market in markets:
        tags = market.get('tags', [])
        if tags:
            markets_with_tags += 1
            all_tags.extend(tags)
        else:
            markets_without_tags += 1

    print(f"\nMarkets WITH tags: {markets_with_tags}/{len(markets)}")
    print(f"Markets WITHOUT tags: {markets_without_tags}/{len(markets)}")

    if all_tags:
        tag_counts = Counter(all_tags)
        print(f"\nTotal unique tags: {len(tag_counts)}")
        print("\nTop 30 most common tags:")
        for tag, count in tag_counts.most_common(30):
            print(f"  {tag:30} ({count} markets)")

        # Look for politics/geopolitics related tags
        print("\n🔍 Politics/Geopolitics related tags:")
        politics_tags = [tag for tag in tag_counts.keys()
                        if 'politic' in tag.lower() or 'geo' in tag.lower()
                        or 'election' in tag.lower() or 'war' in tag.lower()
                        or 'government' in tag.lower()]

        if politics_tags:
            for tag in sorted(politics_tags):
                print(f"  {tag:30} ({tag_counts[tag]} markets)")
        else:
            print("  No obvious politics/geopolitics tags found")

    # Check for 'category' field
    print("\n" + "="*70)
    print("CATEGORY FIELD ANALYSIS")
    print("="*70)

    categories = []
    for market in markets:
        cat = market.get('category')
        if cat:
            categories.append(cat)

    if categories:
        cat_counts = Counter(categories)
        print(f"\nMarkets with 'category' field: {len(categories)}/{len(markets)}")
        print("\nAll categories found:")
        for cat, count in cat_counts.most_common():
            print(f"  {cat:30} ({count} markets)")
    else:
        print("\n❌ No 'category' field found in markets")

    # Check other potential categorization fields
    print("\n" + "="*70)
    print("OTHER CATEGORIZATION FIELDS")
    print("="*70)

    potential_fields = ['marketType', 'type', 'groupType', 'events',
                       'description', 'topic', 'genre', 'eventSlug']

    for field in potential_fields:
        values = []
        for market in markets:
            val = market.get(field)
            if val:
                values.append(val)

        if values:
            print(f"\n'{field}' field found:")
            if isinstance(values[0], (str, int, float, bool)):
                unique_vals = Counter(values)
                for val, count in unique_vals.most_common(10):
                    print(f"  {str(val)[:40]:40} ({count} markets)")
            else:
                print(f"  Found in {len(values)} markets (complex type: {type(values[0]).__name__})")

    # Search for geopolitics in questions
    print("\n" + "="*70)
    print("SEARCHING FOR GEOPOLITICS IN QUESTIONS")
    print("="*70)

    geo_keywords = ['geopolitic', 'war', 'election', 'president', 'congress',
                    'senate', 'government', 'military', 'ukraine', 'russia',
                    'china', 'taiwan', 'israel', 'iran', 'politics', 'political']

    keyword_matches = Counter()
    geo_markets = []

    for market in markets:
        question = market.get('question', '').lower()
        description = market.get('description', '').lower()

        for keyword in geo_keywords:
            if keyword in question or keyword in description:
                keyword_matches[keyword] += 1
                if market not in geo_markets:
                    geo_markets.append(market)
                break

    print(f"\nMarkets matching geopolitical keywords: {len(geo_markets)}/{len(markets)}")
    print("\nKeyword match counts:")
    for keyword, count in keyword_matches.most_common():
        print(f"  {keyword:20} {count} markets")

    if geo_markets:
        print("\n📋 Sample geopolitical markets (by question text):")
        for i, market in enumerate(geo_markets[:10], 1):
            print(f"\n{i}. {market.get('question', 'N/A')[:70]}")
            print(f"   ID: {market.get('id', 'N/A')}")
            print(f"   Tags: {market.get('tags', [])}")
            print(f"   Category: {market.get('category', 'N/A')}")

    # Final recommendations
    print("\n" + "="*70)
    print("RECOMMENDATIONS FOR FILTERING")
    print("="*70)

    print("\nBased on the data analysis, here are the best ways to filter:")

    if all_tags and politics_tags:
        print("\n✅ Option 1: Filter by tags")
        print(f"   Use tags: {', '.join(politics_tags[:5])}")

    if categories:
        print("\n✅ Option 2: Filter by category field")
        print(f"   Available categories include: {', '.join(list(cat_counts.keys())[:5])}")

    if geo_markets:
        print("\n✅ Option 3: Filter by question/description keywords")
        print(f"   Search for keywords like: {', '.join(geo_keywords[:8])}")

    print("\n" + "="*70)


if __name__ == "__main__":
    explore_market_structure()
