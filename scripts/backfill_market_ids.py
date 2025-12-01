#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill Market IDs Script

Updates existing markets that have conditionId in the market_id field
with the correct API-compatible ID format.

This fixes the 323 markets that were stored before the market ID fix was applied.
"""

import sys
import os
import sqlite3
import time
import argparse
from datetime import datetime

# Configure console encoding for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We'll use raw requests instead of importing monitoring modules to avoid dependency issues
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('POLYMARKET_API_KEY')

class MarketIDBackfill:
    """Backfills correct market IDs for existing markets."""

    def __init__(self, db_path: str = 'data/polymarket_tracker.db', api_key: str = None, dry_run: bool = False):
        self.db_path = db_path
        self.api_key = api_key
        self.dry_run = dry_run
        self.base_url = "https://gamma-api.polymarket.com"

        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PolymarketTracker/1.0"
        })

        if api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "APIKEY": api_key
            })

        # Statistics
        self.stats = {
            'total': 0,
            'updated': 0,
            'failed': 0,
            'skipped': 0,
            'already_correct': 0
        }

    def get_markets_needing_fix(self):
        """Get all markets where market_id looks like a conditionId."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Find markets where market_id starts with '0x' and is 66 characters (conditionId format)
        cursor.execute("""
            SELECT market_id, condition_id, title
            FROM markets
            WHERE market_id LIKE '0x%'
            AND LENGTH(market_id) = 66
            ORDER BY last_checked DESC
        """)

        markets = []
        for row in cursor.fetchall():
            markets.append({
                'old_market_id': row[0],
                'condition_id': row[1],
                'title': row[2]
            })

        conn.close()

        return markets

    def find_correct_market_id(self, market_data):
        """
        Try multiple strategies to find the correct market_id for a market.

        Returns: (correct_id, method_used) or (None, error_message)
        """
        title = market_data['title']
        condition_id = market_data['condition_id']

        # Strategy 1: Search by title in get_markets() results
        try:
            response = self.session.get(
                f"{self.base_url}/markets",
                params={"limit": 100, "closed": "false"},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()

                # Handle response format
                if isinstance(data, list):
                    markets = data
                elif isinstance(data, dict) and 'data' in data:
                    markets = data['data']
                else:
                    markets = []

                # Search for matching market
                for market in markets:
                    market_title = market.get('question', market.get('title', ''))
                    market_condition_id = market.get('conditionId', '')

                    # Match by title or condition_id
                    if market_title == title or market_condition_id == condition_id:
                        market_id = market.get('id')
                        if market_id:
                            return (market_id, "title_match")

        except Exception as e:
            pass  # Try next strategy

        # Strategy 2: Try direct API call with conditionId (sometimes works)
        try:
            response = self.session.get(
                f"{self.base_url}/markets/{condition_id}",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                market_id = data.get('id')
                if market_id:
                    return (market_id, "direct_condition_id")

        except Exception as e:
            pass

        # Strategy 3: Search closed markets
        try:
            response = self.session.get(
                f"{self.base_url}/markets",
                params={"limit": 100, "closed": "true"},
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

                for market in markets:
                    market_title = market.get('question', market.get('title', ''))
                    market_condition_id = market.get('conditionId', '')

                    if market_title == title or market_condition_id == condition_id:
                        market_id = market.get('id')
                        if market_id:
                            return (market_id, "closed_market_match")

        except Exception as e:
            pass

        return (None, "no_match_found")

    def update_market_id(self, old_id, new_id, condition_id):
        """Update the market_id in the database."""
        if self.dry_run:
            return True

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE markets
                SET market_id = ?
                WHERE condition_id = ?
            """, (new_id, condition_id))

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            print(f"[ERROR] Failed to update database: {e}")
            return False

    def verify_market_id(self, market_id):
        """Verify that the market_id works with the API."""
        try:
            response = self.session.get(
                f"{self.base_url}/markets/{market_id}",
                timeout=10
            )

            return response.status_code == 200

        except Exception as e:
            return False

    def run(self):
        """Run the backfill process."""
        print("="*80)
        print("MARKET ID BACKFILL SCRIPT")
        print("="*80 + "\n")

        if self.dry_run:
            print("[DRY RUN MODE] No changes will be made to the database\n")

        # Step 1: Get markets needing fix
        print("Step 1: Identifying markets that need fixing...")
        markets = self.get_markets_needing_fix()

        self.stats['total'] = len(markets)

        if not markets:
            print("\n[SUCCESS] No markets need fixing! All market_ids are already in correct format.\n")
            return

        print(f"Found {len(markets)} markets with conditionId in market_id field\n")

        # Step 2: Process each market
        print("Step 2: Finding correct market IDs from API...")
        print("-"*80)

        for idx, market_data in enumerate(markets, 1):
            old_id = market_data['old_market_id']
            condition_id = market_data['condition_id']
            title = market_data['title']

            print(f"\n[{idx}/{len(markets)}] Processing: {title[:60]}...")
            print(f"  Old ID: {old_id[:20]}... (conditionId)")

            # Check if already has correct format (skip if not 0x...)
            if not old_id.startswith('0x'):
                print(f"  [SKIP] Already has correct format")
                self.stats['already_correct'] += 1
                continue

            # Find correct market_id
            correct_id, method = self.find_correct_market_id(market_data)

            if correct_id:
                print(f"  [FOUND] Correct ID: {correct_id} (via {method})")

                # Verify it works
                if self.verify_market_id(correct_id):
                    print(f"  [VERIFIED] API returns data for this ID")

                    # Update database
                    if self.update_market_id(old_id, correct_id, condition_id):
                        action = "[WOULD UPDATE]" if self.dry_run else "[UPDATED]"
                        print(f"  {action} database: market_id = {correct_id}")
                        self.stats['updated'] += 1
                    else:
                        print(f"  [FAILED] Failed to update database")
                        self.stats['failed'] += 1
                else:
                    print(f"  [FAILED] Verification failed: API doesn't return data for this ID")
                    self.stats['failed'] += 1

            else:
                print(f"  [NOT FOUND] Could not find correct market_id ({method})")
                self.stats['failed'] += 1

            # Rate limiting
            time.sleep(0.2)

            # Show progress every 10 markets
            if idx % 10 == 0:
                print(f"\n--- Progress: {idx}/{len(markets)} markets processed ---")
                print(f"    Updated: {self.stats['updated']}")
                print(f"    Failed: {self.stats['failed']}")
                print(f"    Skipped: {self.stats['skipped']}")

        # Step 3: Summary
        print("\n" + "="*80)
        print("BACKFILL SUMMARY")
        print("="*80)
        print(f"Total markets processed: {self.stats['total']}")
        print(f"Successfully updated: {self.stats['updated']}")
        print(f"Failed to update: {self.stats['failed']}")
        print(f"Skipped (already correct): {self.stats['already_correct']}")
        print(f"Skipped (other): {self.stats['skipped']}")

        success_rate = (self.stats['updated'] / self.stats['total'] * 100) if self.stats['total'] > 0 else 0
        print(f"\nSuccess rate: {success_rate:.1f}%")

        if self.dry_run:
            print("\n[DRY RUN] Run without --dry-run to apply changes")
        else:
            print("\n[SUCCESS] Backfill complete! Resolution tracking should now work.")

        print("="*80 + "\n")

        return self.stats

    def test_sample_markets(self, sample_size=5):
        """Test resolution check on sample markets after backfill."""
        print("\n" + "="*80)
        print("TESTING SAMPLE MARKETS")
        print("="*80 + "\n")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get sample markets
        cursor.execute("""
            SELECT market_id, condition_id, title
            FROM markets
            WHERE market_id NOT LIKE '0x%'
            LIMIT ?
        """, (sample_size,))

        markets = cursor.fetchall()
        conn.close()

        if not markets:
            print("No markets with updated IDs found to test")
            return

        print(f"Testing {len(markets)} sample markets:\n")

        success_count = 0

        for idx, (market_id, condition_id, title) in enumerate(markets, 1):
            print(f"{idx}. Testing: {title[:60]}...")
            print(f"   Market ID: {market_id}")

            # Try to fetch market details
            try:
                response = self.session.get(
                    f"{self.base_url}/markets/{market_id}",
                    timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    print(f"   [SUCCESS] API returned data")
                    print(f"   Keys available: {list(data.keys())[:5]}...")
                    success_count += 1
                else:
                    print(f"   [FAILED] API returned status {response.status_code}")

            except Exception as e:
                print(f"   [ERROR] {e}")

            print()

        print("-"*80)
        print(f"Test Results: {success_count}/{len(markets)} markets returned data")
        print("="*80 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backfill correct market IDs for existing markets',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without updating database')
    parser.add_argument('--test', action='store_true',
                       help='Test sample markets after backfill')
    parser.add_argument('--db-path', type=str, default='data/polymarket_tracker.db',
                       help='Path to database file')

    args = parser.parse_args()

    # Check if API key is available
    if not API_KEY:
        print("ERROR: POLYMARKET_API_KEY not found in environment")
        print("Please set it in your .env file")
        return 1

    # Initialize backfill
    backfill = MarketIDBackfill(
        db_path=args.db_path,
        api_key=API_KEY,
        dry_run=args.dry_run
    )

    # Run backfill
    stats = backfill.run()

    # Test if requested
    if args.test and not args.dry_run:
        backfill.test_sample_markets()

    # Return exit code
    if stats['failed'] > 0:
        return 1 if not args.dry_run else 0
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
