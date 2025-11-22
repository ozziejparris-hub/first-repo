#!/usr/bin/env python3
"""
Analyze what market types we're actually getting to improve filtering.
"""

import os
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient
from collections import Counter

load_dotenv()


def analyze_market_categories():
    """Analyze actual market content to improve filtering."""
    print("="*70)
    print("MARKET CATEGORY ANALYSIS")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    client = PolymarketClient(api_key)

    # Fetch a good sample
    print("\nFetching 200 markets for analysis...")
    markets = client.get_all_markets(limit=200)
    print(f"✅ Got {len(markets)} markets\n")

    # Categorize by question content
    categories = {
        'crypto_price': [],
        'sports': [],
        'politics_elections': [],
        'wars_conflicts': [],
        'government_policy': [],
        'international_relations': [],
        'entertainment': [],
        'other': []
    }

    crypto_keywords = ['bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'price', 'above', 'below']
    sports_keywords = ['nfl', 'nba', 'mlb', 'nhl', 'team', 'win', 'championship', 'game', 'match']
    election_keywords = ['election', 'vote', 'ballot', 'win presidency', 'elected']
    war_keywords = ['war', 'military', 'invasion', 'ceasefire', 'ukraine', 'russia', 'gaza']
    gov_keywords = ['congress', 'senate', 'bill', 'law', 'policy', 'cabinet', 'nominee']
    intl_keywords = ['nato', 'treaty', 'ambassador', 'foreign']
    entertainment_keywords = ['elon', 'musk', 'tweet', 'movie', 'album', 'taylor swift']

    for market in markets:
        question = market.get('question', '').lower()
        title = market.get('title', '').lower()
        text = f"{question} {title}"

        categorized = False

        if any(kw in text for kw in crypto_keywords):
            categories['crypto_price'].append(market)
            categorized = True
        elif any(kw in text for kw in sports_keywords):
            categories['sports'].append(market)
            categorized = True
        elif any(kw in text for kw in election_keywords):
            categories['politics_elections'].append(market)
            categorized = True
        elif any(kw in text for kw in war_keywords):
            categories['wars_conflicts'].append(market)
            categorized = True
        elif any(kw in text for kw in gov_keywords):
            categories['government_policy'].append(market)
            categorized = True
        elif any(kw in text for kw in intl_keywords):
            categories['international_relations'].append(market)
            categorized = True
        elif any(kw in text for kw in entertainment_keywords):
            categories['entertainment'].append(market)
            categorized = True

        if not categorized:
            categories['other'].append(market)

    # Print results
    print("CATEGORY BREAKDOWN:")
    print("-"*70)
    for cat, markets_list in categories.items():
        if markets_list:
            print(f"\n{cat.upper().replace('_', ' ')}: {len(markets_list)} markets")
            print("Sample questions:")
            for i, m in enumerate(markets_list[:3], 1):
                print(f"  {i}. {m.get('question', 'N/A')[:70]}")

    print("\n" + "="*70)
    print("RECOMMENDATIONS:")
    print("="*70)

    true_geopolitics = (len(categories['politics_elections']) +
                       len(categories['wars_conflicts']) +
                       len(categories['government_policy']) +
                       len(categories['international_relations']))

    noise = (len(categories['crypto_price']) +
            len(categories['sports']) +
            len(categories['entertainment']))

    print(f"\n✅ True Geopolitics: {true_geopolitics} markets")
    print(f"❌ Noise (crypto/sports/entertainment): {noise} markets")
    print(f"❓ Other: {len(categories['other'])} markets")

    print("\nFILTERING STRATEGY:")
    print("1. INCLUDE: election, war, ceasefire, congress, senate, nato, ambassador")
    print("2. EXCLUDE: bitcoin, eth, crypto, price above/below, team, nfl, elon")


if __name__ == "__main__":
    analyze_market_categories()
