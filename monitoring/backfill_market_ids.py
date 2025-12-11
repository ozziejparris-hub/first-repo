"""
Backfill numeric API IDs for all markets in database.

Problem: Markets stored with conditionId can't be checked with Gamma API.
Solution: Query Gamma API to map conditionId → numeric ID.

Usage:
    python monitoring/backfill_market_ids.py                    # Backfill all (optimized)
    python monitoring/backfill_market_ids.py --limit 100        # Backfill 100
    python monitoring/backfill_market_ids.py --test             # Test mode (no DB writes)
    python monitoring/backfill_market_ids.py --batch-size 100   # Custom batch size
"""

import sys
import time
import argparse
from typing import Optional, Dict
import requests
from database import Database


class MarketIDBackfiller:
    """Backfills numeric API IDs for markets stored with conditionId."""

    def __init__(self, db_path: str = "data/polymarket_tracker.db"):
        self.db = Database(db_path)
        self.session = requests.Session()
        self.gamma_api_base = "https://gamma-api.polymarket.com"

        # Rate limiting
        self.requests_made = 0
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests

    def build_complete_mapping(self) -> Dict[str, str]:
        """
        Build complete conditionId → numeric ID mapping by fetching all markets.

        Since Gamma API doesn't support filtering by conditionId, we need to:
        1. Fetch ALL markets from /markets endpoint (paginated)
        2. Build lookup table of conditionId → numeric ID
        3. Use this mapping to update our database

        Returns:
            Dict mapping conditionId → numeric API ID
        """
        print("\nBuilding complete conditionId -> ID mapping from Gamma API...")
        print("This will fetch all markets (may take 1-2 minutes)...\n")

        mapping = {}
        offset = 0
        limit = 100  # Fetch 100 markets per request
        total_fetched = 0

        while True:
            try:
                # Rate limiting
                elapsed = time.time() - self.last_request_time
                if elapsed < self.min_request_interval:
                    time.sleep(self.min_request_interval - elapsed)

                url = f"{self.gamma_api_base}/markets"
                params = {
                    "limit": limit,
                    "offset": offset
                }

                response = self.session.get(url, params=params, timeout=30)
                self.requests_made += 1
                self.last_request_time = time.time()

                if response.status_code != 200:
                    print(f"   [ERROR] API request failed: {response.status_code}")
                    break

                data = response.json()

                if not data or len(data) == 0:
                    # No more markets
                    break

                # Build mapping from this batch
                for market in data:
                    condition_id = market.get('conditionId')
                    api_id = market.get('id')

                    if condition_id and api_id:
                        mapping[condition_id] = str(api_id)

                total_fetched += len(data)
                offset += limit

                # Progress update
                print(f"   Fetched {total_fetched} markets... (mapping: {len(mapping)})", end='\r')

                # Safety limit - stop after fetching 10,000 markets
                if total_fetched >= 10000:
                    break

            except Exception as e:
                print(f"\n   [ERROR] Error fetching markets: {e}")
                break

        print(f"\n   [OK] Built mapping with {len(mapping)} markets")
        print(f"   API requests made: {self.requests_made}\n")

        return mapping

    def backfill_all_optimized(self, batch_size: int = 50, limit: int = None,
                              test_mode: bool = False):
        """
        Optimized backfill by building complete ID mapping first.

        Strategy:
        1. Fetch all markets from Gamma API to build conditionId → numeric ID mapping
        2. Use mapping to update all database markets at once
        """
        print("\n" + "="*70)
        print("MARKET API ID BACKFILL")
        print("="*70 + "\n")

        markets = self.db.get_markets_needing_api_id(limit=limit)
        total = len(markets)

        if total == 0:
            print("[OK] No markets need backfilling!")
            return

        print(f"Found {total} markets needing API IDs")
        if test_mode:
            print("[TEST MODE] Will not write to database\n")
        else:
            print("[LIVE MODE] Will update database\n")

        # Build complete mapping from Gamma API
        mapping = self.build_complete_mapping()

        if not mapping:
            print("[ERROR] Failed to build mapping - no markets fetched from API")
            return

        # Update database using mapping
        print("Updating database with API IDs...")
        success_count = 0
        fail_count = 0
        numeric_id_count = 0

        for market_id, title, condition_id in markets:
            # If market_id is already numeric, use it directly
            if market_id.isdigit():
                if not test_mode:
                    self.db.update_market_api_id(market_id, market_id)
                success_count += 1
                numeric_id_count += 1
                continue

            # Otherwise try to map conditionId
            search_id = condition_id if condition_id else market_id

            if search_id in mapping:
                api_id = mapping[search_id]

                if not test_mode:
                    self.db.update_market_api_id(market_id, api_id)

                success_count += 1
            else:
                fail_count += 1

            # Progress update
            if (success_count + fail_count) % 100 == 0:
                print(f"   Processed {success_count + fail_count}/{total}...", end='\r')

        print(f"   Processed {total}/{total}...             ")

        if numeric_id_count > 0:
            print(f"\n   Note: {numeric_id_count} markets already had numeric IDs")

        # Final summary
        print("\n" + "="*70)
        print("BACKFILL COMPLETE")
        print("="*70)
        print(f"Total markets in DB: {total}")
        print(f"[OK] Success: {success_count} ({success_count/total*100:.1f}%)")
        print(f"[ERROR] Failed: {fail_count} ({fail_count/total*100:.1f}%)")
        print(f"API requests made: {self.requests_made}")
        print()

        if test_mode:
            print("[TEST MODE] No changes made to database")
        else:
            print("[OK] Database updated successfully")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill numeric API IDs for Polymarket markets"
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Maximum number of markets to process (default: all)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode - query API but don\'t update database'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='data/polymarket_tracker.db',
        help='Path to database file'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of markets to query per API request (default: 50)'
    )

    args = parser.parse_args()

    backfiller = MarketIDBackfiller(db_path=args.db)
    backfiller.backfill_all_optimized(
        batch_size=args.batch_size,
        limit=args.limit,
        test_mode=args.test
    )


if __name__ == "__main__":
    main()
