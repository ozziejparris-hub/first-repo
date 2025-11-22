#!/usr/bin/env python3
"""
Script to explore the 'events' field structure in Polymarket markets.
Events are likely how Polymarket categorizes markets.
"""

import os
import json
from collections import Counter
from dotenv import load_dotenv
from monitoring.polymarket_client import PolymarketClient

load_dotenv()


def explore_events_structure():
    """Analyze the events field in markets."""
    print("="*70)
    print("POLYMARKET EVENTS STRUCTURE EXPLORER")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    if not api_key:
        print("❌ No POLYMARKET_API_KEY found in .env")
        return

    client = PolymarketClient(api_key)

    print("\n📊 Fetching 200 markets for events analysis...\n")
    markets = client.get_all_markets(limit=200)

    if not markets:
        print("❌ No markets returned.")
        return

    print(f"✅ Fetched {len(markets)} markets\n")

    # Analyze events structure
    print("="*70)
    print("EVENTS FIELD STRUCTURE")
    print("="*70)

    # Get a sample event
    sample_market = markets[0]
    events = sample_market.get('events', [])

    if events:
        print(f"\nSample market has {len(events)} event(s)")
        print("\nEvent object structure:")
        event = events[0]

        for key in sorted(event.keys()):
            value = event[key]
            value_type = type(value).__name__

            if isinstance(value, (list, dict)):
                value_preview = f"{value_type} with {len(value)} items"
            elif isinstance(value, str) and len(value) > 60:
                value_preview = f"{value[:60]}..."
            else:
                value_preview = str(value)

            print(f"  {key:25} ({value_type:10}): {value_preview}")
    else:
        print("\n❌ No events found in sample market")

    # Collect all event data
    print("\n" + "="*70)
    print("EVENT ANALYSIS ACROSS ALL MARKETS")
    print("="*70)

    event_titles = []
    event_slugs = []
    event_tags = []
    all_events = []

    for market in markets:
        events = market.get('events', [])
        for event in events:
            all_events.append(event)

            title = event.get('title')
            if title:
                event_titles.append(title)

            slug = event.get('slug')
            if slug:
                event_slugs.append(slug)

            tags = event.get('tags', [])
            if tags:
                event_tags.extend(tags)

    print(f"\nTotal events found: {len(all_events)}")
    print(f"Unique event titles: {len(set(event_titles))}")
    print(f"Unique event slugs: {len(set(event_slugs))}")

    # Show top event titles
    if event_titles:
        title_counts = Counter(event_titles)
        print(f"\nTop 30 most common event titles:")
        for title, count in title_counts.most_common(30):
            print(f"  {title:50} ({count} markets)")

    # Look for geopolitics in event titles
    print("\n" + "="*70)
    print("GEOPOLITICS IN EVENT TITLES")
    print("="*70)

    geo_keywords = ['geopolitic', 'politics', 'election', 'war', 'government',
                    'military', 'world', 'international', 'global']

    geo_events = []
    for title in set(event_titles):
        if any(keyword in title.lower() for keyword in geo_keywords):
            geo_events.append(title)

    if geo_events:
        print(f"\n✅ Found {len(geo_events)} geopolitics-related event titles:")
        for title in sorted(geo_events)[:20]:
            count = event_titles.count(title)
            print(f"  {title:50} ({count} markets)")
    else:
        print("\n❌ No obvious geopolitics events found in titles")
        print("\nShowing all unique event titles for reference:")
        for title in sorted(set(event_titles))[:30]:
            count = event_titles.count(title)
            print(f"  {title:50} ({count} markets)")

    # Check event tags
    if event_tags:
        print("\n" + "="*70)
        print("EVENT TAGS")
        print("="*70)

        tag_counts = Counter(event_tags)
        print(f"\nTotal event tags: {len(event_tags)}")
        print(f"Unique event tags: {len(set(event_tags))}")
        print("\nTop 20 event tags:")
        for tag, count in tag_counts.most_common(20):
            print(f"  {tag:30} ({count} occurrences)")

    # Find markets with geopolitics events
    print("\n" + "="*70)
    print("MARKETS IN GEOPOLITICS EVENTS")
    print("="*70)

    geo_markets = []
    for market in markets:
        events = market.get('events', [])
        for event in events:
            title = event.get('title', '').lower()
            slug = event.get('slug', '').lower()

            if any(keyword in title or keyword in slug for keyword in geo_keywords):
                geo_markets.append({
                    'market': market,
                    'event_title': event.get('title'),
                    'event_slug': event.get('slug')
                })
                break

    print(f"\nMarkets in geopolitics-related events: {len(geo_markets)}/{len(markets)}")

    if geo_markets:
        print("\n📋 Sample geopolitical markets (via events):")
        for i, item in enumerate(geo_markets[:10], 1):
            market = item['market']
            print(f"\n{i}. {market.get('question', 'N/A')[:70]}")
            print(f"   Event: {item['event_title']}")
            print(f"   Slug: {item['event_slug']}")
            print(f"   Market ID: {market.get('id')}")

    # Recommendations
    print("\n" + "="*70)
    print("FILTERING RECOMMENDATIONS")
    print("="*70)

    if geo_events:
        print("\n✅ BEST METHOD: Filter by event title/slug")
        print(f"   Look for events containing: {', '.join(geo_keywords[:5])}")
        print(f"   Found {len(geo_events)} relevant event categories")
    else:
        print("\n⚠️ Event-based filtering may not work well")
        print("   Recommendation: Use keyword matching on market questions/descriptions")

    if event_tags:
        print("\n✅ ALTERNATIVE: Filter by event tags")
        print("   Event-level tags are available")

    print("\n" + "="*70)


if __name__ == "__main__":
    explore_events_structure()
