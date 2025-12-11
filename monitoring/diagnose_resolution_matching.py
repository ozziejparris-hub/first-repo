"""
Diagnose why resolved markets from API aren't matching database markets.

Checks:
1. Do API markets exist in database at all?
2. Are conditionId formats matching?
3. Are api_id values matching?
4. Are market categories filtered correctly?
"""

import sqlite3
import requests
import json
import time
from database import Database


def diagnose_matching():
    """Diagnose matching issues between API and database."""

    print("\n" + "="*70)
    print("RESOLUTION MATCHING DIAGNOSIS")
    print("="*70 + "\n")

    db = Database("data/polymarket_tracker.db")
    conn = db.get_connection()
    cursor = conn.cursor()

    # 1. Database stats
    print("="*70)
    print("DATABASE STATISTICS")
    print("="*70)

    cursor.execute("SELECT COUNT(*) FROM markets")
    total_markets = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
    resolved_in_db = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 0")
    unresolved_in_db = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM markets WHERE api_id IS NOT NULL")
    with_api_id = cursor.fetchone()[0]

    print(f"Total markets: {total_markets:,}")
    print(f"Resolved: {resolved_in_db:,} ({resolved_in_db/total_markets*100:.1f}%)")
    print(f"Unresolved: {unresolved_in_db:,} ({unresolved_in_db/total_markets*100:.1f}%)")
    print(f"With api_id: {with_api_id:,} ({with_api_id/total_markets*100:.1f}%)")
    print()

    # 2. Check market categories
    print("="*70)
    print("MARKET CATEGORIES IN DATABASE")
    print("="*70)

    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM markets
        WHERE category IS NOT NULL
        GROUP BY category
        ORDER BY count DESC
        LIMIT 20
    """)

    categories = cursor.fetchall()
    if categories:
        print("Top categories:")
        for cat, count in categories:
            print(f"  {cat}: {count:,}")
    else:
        print("[WARNING] No category data in database!")
    print()

    # 3. Sample API resolved market
    print("="*70)
    print("FETCHING SAMPLE RESOLVED MARKET FROM API")
    print("="*70)

    try:
        response = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 100, "closed": "true"},
            timeout=30
        )

        if response.status_code == 200:
            markets = response.json()
            resolved_markets = [
                m for m in markets
                if m.get('umaResolutionStatus', '').lower() == 'resolved'
            ]

            if resolved_markets:
                sample = resolved_markets[0]

                print("Sample resolved market from API:")
                print(f"  Title: {sample.get('question', 'N/A')}")
                print(f"  API ID: {sample.get('id')}")
                print(f"  Condition ID: {sample.get('conditionId', 'N/A')}")
                print(f"  Category: {sample.get('category', 'N/A')}")
                print(f"  Uma Status: {sample.get('umaResolutionStatus')}")
                print()

                # 4. Check if this market exists in database
                print("="*70)
                print("CHECKING IF SAMPLE MARKET EXISTS IN DATABASE")
                print("="*70)

                condition_id = sample.get('conditionId')
                api_id = str(sample.get('id'))

                # Check by condition_id
                cursor.execute("""
                    SELECT market_id, title, api_id, category, resolved
                    FROM markets
                    WHERE market_id = ? OR condition_id = ?
                """, (condition_id, condition_id))

                by_condition = cursor.fetchone()

                # Check by api_id
                cursor.execute("""
                    SELECT market_id, title, api_id, category, resolved
                    FROM markets
                    WHERE api_id = ?
                """, (api_id,))

                by_api_id = cursor.fetchone()

                if by_condition:
                    print("[OK] Market found by condition_id!")
                    print(f"  market_id: {by_condition[0]}")
                    print(f"  title: {by_condition[1]}")
                    print(f"  api_id: {by_condition[2]}")
                    print(f"  category: {by_condition[3]}")
                    print(f"  resolved: {by_condition[4]}")
                else:
                    print("[ERROR] Market NOT found by condition_id!")

                print()

                if by_api_id:
                    print("[OK] Market found by api_id!")
                    print(f"  market_id: {by_api_id[0]}")
                    print(f"  title: {by_api_id[1]}")
                    print(f"  api_id: {by_api_id[2]}")
                    print(f"  category: {by_api_id[3]}")
                    print(f"  resolved: {by_api_id[4]}")
                else:
                    print("[ERROR] Market NOT found by api_id!")

                print()

                # 5. If not found, check if category was filtered out
                if not by_condition and not by_api_id:
                    category = sample.get('category', 'unknown')
                    print(f"[ANALYSIS] Market category: '{category}'")
                    print(f"[ANALYSIS] This market may have been filtered out during refresh")
                    print(f"[ANALYSIS] Check if '{category}' is in your category filters")
            else:
                print("[WARNING] No resolved markets found in API response")

    except Exception as e:
        print(f"[ERROR] Failed to fetch from API: {e}")

    print()

    # 6. Check a few resolved markets from API
    print("="*70)
    print("CHECKING OVERLAP: API vs DATABASE")
    print("="*70)

    try:
        response = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 1000, "closed": "true"},
            timeout=30
        )

        if response.status_code == 200:
            markets = response.json()
            resolved_markets = [
                m for m in markets
                if m.get('umaResolutionStatus', '').lower() == 'resolved'
            ]

            print(f"Fetched {len(resolved_markets)} resolved markets from API")

            matches = 0
            not_in_db = 0
            wrong_category = 0

            for market in resolved_markets[:100]:  # Check first 100
                condition_id = market.get('conditionId')
                api_id = str(market.get('id'))
                category = market.get('category', 'unknown')

                cursor.execute("""
                    SELECT 1 FROM markets
                    WHERE market_id = ? OR condition_id = ? OR api_id = ?
                """, (condition_id, condition_id, api_id))

                if cursor.fetchone():
                    matches += 1
                else:
                    not_in_db += 1
                    if category.lower() in ['sports', 'nba', 'nfl', 'mlb', 'olympics']:
                        wrong_category += 1

            print(f"\nResults (first 100 resolved markets):")
            print(f"  Matched in database: {matches}")
            print(f"  Not in database: {not_in_db}")
            print(f"  Filtered out (sports/entertainment): {wrong_category}")
            print()

            if matches == 0:
                print("[CRITICAL] NO MATCHES FOUND!")
                print("This means either:")
                print("  1. Your database has different markets than API")
                print("  2. The matching logic is broken")
                print("  3. All resolved markets were filtered out")
            elif matches < 10:
                print("[WARNING] Very few matches!")
                print("Most resolved markets aren't in your database")
            else:
                print("[OK] Found matches - matching logic should work")

    except Exception as e:
        print(f"[ERROR] {e}")

    print()

    # 7. Final recommendations
    print("="*70)
    print("RECOMMENDATIONS")
    print("="*70)

    if resolved_in_db == 0:
        print("1. No resolved markets in database yet - this is expected")
        print("   Run: python monitoring/fast_resolution_check.py (LIVE mode)")
        print()

    cursor.execute("""
        SELECT COUNT(*) FROM markets
        WHERE category IN ('Sports', 'NBA', 'NFL', 'MLB', 'Olympics',
                          'Hockey', 'Soccer', 'Football', 'Baseball',
                          'NBA Playoffs', 'March Madness', 'Super Bowl')
    """)
    sports_count = cursor.fetchone()[0]

    if sports_count > 0:
        print(f"2. [WARNING] Found {sports_count:,} sports markets in database!")
        print("   Your filtering may not be working correctly")
        print("   Consider re-running market refresh with better filters")
        print()

    if with_api_id != total_markets:
        print(f"3. [WARNING] Not all markets have api_id!")
        print(f"   {total_markets - with_api_id:,} markets missing api_id")
        print("   This will prevent resolution checking")
        print()

    conn.close()
    print("="*70)
    print()


if __name__ == "__main__":
    diagnose_matching()
