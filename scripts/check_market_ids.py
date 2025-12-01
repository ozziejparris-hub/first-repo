#!/usr/bin/env python3
"""
Check Market ID Format
Investigates what market ID format we're storing and what format the API expects.
"""

import sys
import os
import sqlite3

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.polymarket_client import PolymarketClient
from dotenv import load_dotenv

# Load environment
load_dotenv()
api_key = os.getenv('POLYMARKET_API_KEY')

def check_database_ids():
    """Check what market IDs are stored in the database."""
    print("="*70)
    print("CHECKING DATABASE MARKET IDs")
    print("="*70 + "\n")

    conn = sqlite3.connect('data/polymarket_tracker.db')
    cursor = conn.cursor()

    cursor.execute('SELECT market_id, title FROM markets LIMIT 5')
    rows = cursor.fetchall()

    print(f"Found {len(rows)} sample markets in database:\n")

    for i, (market_id, title) in enumerate(rows, 1):
        print(f"{i}. Market ID: {market_id}")
        print(f"   Title: {title[:70]}")
        print(f"   ID Length: {len(market_id)}")
        print(f"   ID Format: {'conditionId (0x...)' if market_id.startswith('0x') else 'Unknown'}")
        print()

    conn.close()
    return [row[0] for row in rows]

def test_market_api(client, market_ids):
    """Test if API returns data for these market IDs."""
    print("\n" + "="*70)
    print("TESTING API WITH DATABASE MARKET IDs")
    print("="*70 + "\n")

    for i, market_id in enumerate(market_ids[:3], 1):  # Test first 3
        print(f"\n{i}. Testing market_id: {market_id[:50]}...")

        result = client.get_market_details(market_id)

        if result:
            print(f"   [SUCCESS] API returned data!")
            print(f"   Available fields: {list(result.keys())}")

            # Show key fields
            for field in ['id', 'conditionId', 'questionId', 'slug', 'question']:
                if field in result:
                    value = str(result[field])
                    print(f"   {field}: {value[:60]}")
        else:
            print(f"   [FAILED] No data returned from API")

def get_fresh_market_data(client):
    """Get fresh markets from API to see what ID fields are available."""
    print("\n" + "="*70)
    print("GETTING FRESH MARKET DATA FROM API")
    print("="*70 + "\n")

    print("Fetching geopolitics markets from API...")
    markets = client.get_markets(category="Geopolitics")

    if markets:
        print(f"Found {len(markets)} markets\n")
        print("Sample market structure (first market):")
        print("-"*70)

        sample = markets[0]

        # Show all ID-related fields
        id_fields = [k for k in sample.keys() if 'id' in k.lower() or k == 'slug']

        print("\nID-related fields:")
        for field in id_fields:
            value = str(sample[field])
            print(f"  {field}: {value[:70]}")

        print("\nOther key fields:")
        for field in ['question', 'title', 'description']:
            if field in sample:
                value = str(sample[field])
                print(f"  {field}: {value[:70]}")

        return markets
    else:
        print("No markets returned from API")
        return []

def compare_id_fields(markets):
    """Compare different ID field formats."""
    print("\n" + "="*70)
    print("COMPARING ID FIELD FORMATS")
    print("="*70 + "\n")

    if not markets:
        print("No markets to compare")
        return

    print(f"Analyzing {min(3, len(markets))} sample markets:\n")

    for i, market in enumerate(markets[:3], 1):
        print(f"{i}. Market: {market.get('question', 'Unknown')[:60]}...")

        # Check all possible ID fields
        id_candidates = {
            'id': market.get('id'),
            'conditionId': market.get('conditionId'),
            'questionId': market.get('questionId'),
            'slug': market.get('slug'),
            'market_id': market.get('market_id'),
        }

        for field_name, field_value in id_candidates.items():
            if field_value:
                print(f"   {field_name}: {str(field_value)[:60]}")

        print()

def main():
    """Main entry point."""

    # Step 1: Check what's in the database
    stored_ids = check_database_ids()

    # Step 2: Initialize client
    print("\nInitializing Polymarket client...")
    client = PolymarketClient(api_key)

    # Step 3: Test if stored IDs work with API
    if stored_ids:
        test_market_api(client, stored_ids)

    # Step 4: Get fresh market data to see ID formats
    fresh_markets = get_fresh_market_data(client)

    # Step 5: Compare ID fields
    compare_id_fields(fresh_markets)

    # Summary
    print("\n" + "="*70)
    print("SUMMARY & RECOMMENDATION")
    print("="*70 + "\n")

    print("Based on the data above:")
    print("1. Check which ID field the API accepts in get_market_details()")
    print("2. Update store_market_dict() to use that ID field")
    print("3. Update store_market_from_trade() similarly")
    print("4. Backfill existing 310 markets with correct IDs")
    print()

if __name__ == "__main__":
    main()
