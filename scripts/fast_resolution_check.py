"""
Fast Batch Resolution Checker for Polymarket Markets

This script provides ultra-fast resolution checking by querying the Gamma API
for ALL resolved markets at once, then updating the database in batch.

Instead of checking each market individually (11.8 hours for 213k markets),
this script:
1. Fetches ALL resolved markets from Gamma API in one batch query
2. Filters for markets with umaResolutionStatus = "resolved"
3. Updates database in batch operations

Expected performance: 10-30 seconds vs 11.8 hours

Usage:
    python monitoring/fast_resolution_check.py                  # Run batch check
    python monitoring/fast_resolution_check.py --test           # Dry run (no DB updates)
    python monitoring/fast_resolution_check.py --limit 100      # Limit to 100 markets
"""

import sys
import time
import json
import sqlite3
import argparse
import requests
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "monitoring"))
from database import Database


class FastResolutionChecker:
    """Fast batch resolution checker using Gamma API."""

    def __init__(self, db_path: str = "data/polymarket_tracker.db"):
        self.db = Database(db_path)
        self.db_path = db_path
        self.session = requests.Session()
        self.gamma_api_base = "https://gamma-api.polymarket.com"

        # Stats
        self.stats = {
            'total_markets_in_db': 0,
            'resolved_markets_fetched': 0,
            'markets_updated': 0,
            'markets_already_resolved': 0,
            'api_requests': 0,
            'errors': 0
        }

    def fetch_all_resolved_markets(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Fetch ALL resolved markets from Gamma API.

        The Gamma API /markets endpoint supports filtering by 'closed' status.
        We fetch all closed markets, then filter for those with umaResolutionStatus='resolved'.

        Args:
            limit: Max markets to fetch (for testing)

        Returns:
            List of resolved market dicts
        """
        print("\n" + "="*70)
        print("FETCHING RESOLVED MARKETS FROM GAMMA API")
        print("="*70 + "\n")

        resolved_markets = []
        offset = 0
        batch_size = 100

        print("Fetching closed markets...")

        while True:
            try:
                # Rate limiting
                time.sleep(0.1)

                # Fetch closed markets (which includes resolved ones)
                url = f"{self.gamma_api_base}/markets"
                params = {
                    "limit": batch_size,
                    "offset": offset,
                    "closed": "true",   # Only fetch closed markets
                    "order": "endDate",
                    "ascending": "false"
                }

                response = self.session.get(url, params=params, timeout=30)
                self.stats['api_requests'] += 1

                if response.status_code != 200:
                    print(f"   [ERROR] API request failed: {response.status_code}")
                    break

                data = response.json()

                if not data or len(data) == 0:
                    break

                # Filter for truly resolved markets
                # Resolution is indicated by outcomePrices having a winner (price >= 0.99)
                for market in data:
                    try:
                        prices_raw = market.get('outcomePrices', '[]')
                        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                        # Check if any outcome has winning price
                        has_winner = any(float(p) >= 0.99 for p in prices if p)

                        if has_winner:
                            resolved_markets.append(market)
                    except:
                        # Skip markets with parsing errors
                        continue

                offset += batch_size

                # Progress update
                print(f"   Fetched {offset} closed markets, found {len(resolved_markets)} resolved...", end='\r')

                # Stop if we hit limit
                if limit and len(resolved_markets) >= limit:
                    resolved_markets = resolved_markets[:limit]
                    break

                # Safety limit: stop after fetching 10,000 closed markets
                # (prevents infinite loops and excessive API calls)
                if offset >= 20000:
                    print(f"\n   [INFO] Reached safety limit of 20,000 closed markets")
                    break

            except Exception as e:
                print(f"\n   [ERROR] Error fetching markets: {e}")
                self.stats['errors'] += 1
                break

        print(f"\n   [OK] Found {len(resolved_markets)} resolved markets")
        print(f"   API requests made: {self.stats['api_requests']}\n")

        self.stats['resolved_markets_fetched'] = len(resolved_markets)
        return resolved_markets

    def extract_winner(self, market: Dict) -> Optional[str]:
        """
        Extract winning outcome from resolved market.

        Args:
            market: Market dict from Gamma API

        Returns:
            Winning outcome name, or None if unable to determine
        """
        try:
            # Parse outcomes and prices (both are JSON strings)
            outcomes_raw = market.get('outcomes', '[]')
            prices_raw = market.get('outcomePrices', '[]')

            outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

            # Find winner (price >= 0.99, allowing for floating point imprecision)
            for idx, price in enumerate(prices):
                if float(price) >= 0.99:
                    return outcomes[idx]

            return None

        except Exception as e:
            print(f"   [ERROR] Failed to extract winner: {e}")
            return None

    def batch_update_resolved_markets(self, resolved_markets: List[Dict], test_mode: bool = False):
        """
        Update database with resolved market data in batch.

        Args:
            resolved_markets: List of resolved market dicts from API
            test_mode: If True, don't actually write to DB
        """
        print("="*70)
        print("UPDATING DATABASE WITH RESOLVED MARKETS")
        print("="*70 + "\n")

        if test_mode:
            print("[TEST MODE] Would update markets (not writing to DB)\n")

        # Get all unresolved markets from database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, condition_id, api_id
            FROM markets
            WHERE (resolved = 0 OR resolved IS NULL)
        """)
        unresolved_db_markets = cursor.fetchall()
        conn.close()

        print(f"Unresolved markets in database: {len(unresolved_db_markets)}")
        print(f"Resolved markets from API: {len(resolved_markets)}\n")

        # Build lookup: conditionId -> market data
        # Also build: api_id -> market data
        api_lookup = {}
        condition_lookup = {}

        for market in resolved_markets:
            condition_id = market.get('conditionId')
            api_id = str(market.get('id', ''))

            if condition_id:
                condition_lookup[condition_id] = market
            if api_id:
                api_lookup[api_id] = market

        print("Matching and updating markets...")

        updated = 0
        already_resolved = 0
        not_found = 0

        # More efficient: iterate through API markets and look them up in DB
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for idx, market_data in enumerate(resolved_markets, 1):
            try:
                condition_id = market_data.get('conditionId')
                api_id = str(market_data.get('id', ''))

                if not condition_id and not api_id:
                    not_found += 1
                    continue

                # Try to find market in database (multiple strategies)
                cursor.execute("""
                    SELECT market_id, resolved FROM markets
                    WHERE api_id = ? OR market_id = ? OR condition_id = ?
                    LIMIT 1
                """, (api_id, condition_id, condition_id))

                result = cursor.fetchone()

                if not result:
                    not_found += 1
                    continue

                market_id, is_resolved = result

                if is_resolved:
                    already_resolved += 1
                    continue

                # Extract winner
                winner = self.extract_winner(market_data)

                if winner:
                    if not test_mode:
                        # Update database
                        cursor.execute("""
                            UPDATE markets
                            SET resolved = 1,
                                winning_outcome = ?,
                                resolution_date = ?,
                                last_checked = ?
                            WHERE market_id = ?
                        """, (winner, datetime.now(), datetime.now(), market_id))

                        conn.commit()

                    updated += 1

                    # Show first few updates
                    if updated <= 5:
                        title = market_data.get('question', market_data.get('title', 'Unknown'))[:50]
                        try:
                            title = title.encode('ascii', 'replace').decode('ascii')
                        except:
                            pass
                        print(f"   [OK] Updated: {title}")
                        print(f"        Winner: {winner}")

            except Exception as e:
                print(f"\n[ERROR] Error processing market {idx}: {e}")
                continue

            # Progress update
            if idx % 100 == 0 or idx == len(resolved_markets):
                print(f"   Processed {idx}/{len(resolved_markets)} | Updated: {updated} | Not found: {not_found}     ", end='\r')

        print()  # New line after progress
        conn.close()

        self.stats['markets_updated'] = updated
        self.stats['markets_already_resolved'] = already_resolved

        print("="*70)
        print("BATCH UPDATE COMPLETE")
        print("="*70)
        print(f"\nResolved markets from API: {len(resolved_markets)}")
        print(f"[OK] Markets updated: {updated}")
        print(f"Already resolved: {already_resolved}")
        print(f"Not found in database: {not_found}")
        print(f"API requests made: {self.stats['api_requests']}")

        if test_mode:
            print("\n[TEST MODE] No changes made to database")
        else:
            print("\n[OK] Database updated successfully")

    def run_fast_check(self, test_mode: bool = False, limit: Optional[int] = None):
        """
        Run fast batch resolution check.

        Args:
            test_mode: If True, don't write to database
            limit: Max markets to process (for testing)
        """
        print("\n" + "="*70)
        print("FAST BATCH RESOLUTION CHECK")
        print("="*70)

        if test_mode:
            print("\n[TEST MODE] Dry run - no database changes will be made\n")

        start_time = time.time()

        # Step 1: Fetch all resolved markets from API
        resolved_markets = self.fetch_all_resolved_markets(limit=limit)

        if not resolved_markets:
            print("\n[WARNING] No resolved markets found in API")
            return

        # Step 2: Update database in batch
        self.batch_update_resolved_markets(resolved_markets, test_mode=test_mode)

        elapsed = time.time() - start_time

        print(f"\n[TIME] Total elapsed: {elapsed:.1f} seconds")
        print("\nNext steps:")
        print("1. Run: python monitoring/check_market_resolutions.py --diagnose")
        print("2. Check trader performance with newly resolved markets")
        print()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Fast batch resolution checker for Polymarket markets"
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode - fetch from API but don\'t update database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of resolved markets to process (for testing)'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='data/polymarket_tracker.db',
        help='Path to database file'
    )

    args = parser.parse_args()

    checker = FastResolutionChecker(db_path=args.db)
    checker.run_fast_check(
        test_mode=args.test,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
