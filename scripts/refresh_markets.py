"""
Refresh Polymarket markets database with current active markets.

This script safely replaces old/archived markets with fresh data from Gamma API while:
- Preserving all trader data
- Preserving all trade history
- Backing up existing markets before clearing
- Storing both conditionId and numeric ID for each market
- Applying category filters (geopolitics, crypto, economics)

Usage:
    python monitoring/refresh_markets.py --backup-only    # Just backup, don't refresh
    python monitoring/refresh_markets.py --test           # Dry run (no DB writes)
    python monitoring/refresh_markets.py                  # Full refresh
    python monitoring/refresh_markets.py --limit 100      # Fetch only 100 markets (testing)
"""

import sqlite3
import requests
import json
import time
import os
import argparse
from datetime import datetime
from typing import Dict, List, Optional
from database import Database


class MarketRefresher:
    """Safely refresh markets database with current active markets."""

    def __init__(self, db_path: str = "data/polymarket_tracker.db"):
        self.db_path = db_path
        self.db = Database(db_path)
        self.session = requests.Session()
        self.gamma_api_base = "https://gamma-api.polymarket.com"

        # Category filters
        # Explicitly exclude sports/entertainment, include everything else
        self.excluded_categories = {
            'Sports', 'Pop Culture', 'Entertainment', 'Pop-Culture',
            'Olympics', 'NBA Playoffs', 'NFL', 'MLB', 'NHL', 'Soccer',
            'Boxing', 'MMA', 'Tennis', 'Golf', 'Formula 1', 'NASCAR'
        }

        # Included categories (for logging only - we include Unknown too)
        self.relevant_categories = {
            'Politics', 'Crypto', 'Business', 'Economics',
            'Science', 'Technology', 'New Listings', 'US-current-affairs',
            'Coronavirus', 'Tech', 'NFTs'
        }

        # Stats tracking
        self.stats = {
            'markets_backed_up': 0,
            'markets_fetched': 0,
            'markets_filtered': 0,
            'markets_stored': 0,
            'trades_preserved': 0,
            'trades_orphaned': 0,
            'api_requests': 0
        }

    def backup_markets_table(self, backup_dir: str = "data/backups") -> str:
        """
        Backup existing markets table to JSON file.

        Returns:
            Path to backup file
        """
        print("\n" + "="*70)
        print("BACKING UP MARKETS TABLE")
        print("="*70 + "\n")

        # Create backup directory
        os.makedirs(backup_dir, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"markets_backup_{timestamp}.json")

        # Export markets to JSON
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, title, category, end_date, resolved,
                   winning_outcome, condition_id, api_id, last_checked, resolution_date
            FROM markets
        """)

        markets = []
        for row in cursor.fetchall():
            markets.append({
                'market_id': row[0],
                'title': row[1],
                'category': row[2],
                'end_date': row[3],
                'resolved': row[4],
                'winning_outcome': row[5],
                'condition_id': row[6],
                'api_id': row[7],
                'last_checked': row[8],
                'resolution_date': row[9]
            })

        conn.close()

        # Write to file
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(markets, f, indent=2, ensure_ascii=False)

        self.stats['markets_backed_up'] = len(markets)

        print(f"[OK] Backed up {len(markets)} markets")
        print(f"[OK] Backup file: {backup_file}")
        print(f"     Size: {os.path.getsize(backup_file) / 1024:.1f} KB\n")

        return backup_file

    def fetch_all_markets(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Fetch all current active markets from Gamma API.

        Args:
            limit: Max markets to fetch (None = all)

        Returns:
            List of market dicts
        """
        print("\n" + "="*70)
        print("FETCHING CURRENT MARKETS FROM GAMMA API")
        print("="*70 + "\n")

        markets = []
        offset = 0
        batch_size = 100

        while True:
            try:
                # Rate limiting
                time.sleep(0.1)

                url = f"{self.gamma_api_base}/markets"
                params = {
                    "limit": batch_size,
                    "offset": offset
                }

                response = self.session.get(url, params=params, timeout=30)
                self.stats['api_requests'] += 1

                if response.status_code != 200:
                    print(f"   [ERROR] API request failed: {response.status_code}")
                    break

                data = response.json()

                if not data or len(data) == 0:
                    break

                markets.extend(data)
                offset += batch_size

                # Progress update
                print(f"   Fetched {len(markets)} markets...", end='\r')

                # Stop if we hit limit
                if limit and len(markets) >= limit:
                    markets = markets[:limit]
                    break

            except Exception as e:
                print(f"\n   [ERROR] Error fetching markets: {e}")
                break

        print(f"   Fetched {len(markets)} markets total")
        self.stats['markets_fetched'] = len(markets)
        print(f"   API requests made: {self.stats['api_requests']}\n")

        return markets

    def filter_markets(self, markets: List[Dict]) -> List[Dict]:
        """
        Filter markets by category (exclude sports/entertainment).

        Args:
            markets: List of market dicts from API

        Returns:
            Filtered list
        """
        print("Filtering markets by category...")

        filtered = []
        category_counts = {}

        for market in markets:
            category = market.get('category', 'Unknown')

            # Track category counts
            category_counts[category] = category_counts.get(category, 0) + 1

            # Apply filters - exclude only sports/entertainment
            if category in self.excluded_categories:
                continue

            # Include everything else (relevant categories + Unknown)
            filtered.append(market)

        self.stats['markets_filtered'] = len(filtered)

        print(f"\n   Category breakdown:")
        for category, count in sorted(category_counts.items(), key=lambda x: -x[1])[:10]:
            included = "[INCLUDED]" if category not in self.excluded_categories else "[EXCLUDED]"
            print(f"      {included} {category}: {count}")

        print(f"\n   [OK] Filtered to {len(filtered)} markets (from {len(markets)})")
        print(f"        Excluded {len(markets) - len(filtered)} sports/entertainment markets\n")

        return filtered

    def clear_markets_table(self):
        """Clear all markets from database (backup should exist first!)."""
        print("Clearing markets table...")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM markets")
        conn.commit()
        conn.close()

        print("   [OK] Markets table cleared\n")

    def store_markets(self, markets: List[Dict], test_mode: bool = False):
        """
        Store markets in database with both IDs.

        Args:
            markets: List of market dicts from API
            test_mode: If True, don't actually write to DB
        """
        print("\n" + "="*70)
        print("STORING MARKETS IN DATABASE")
        print("="*70 + "\n")

        if test_mode:
            print("[TEST MODE] Would store markets (not writing to DB)\n")

        stored_count = 0
        error_count = 0

        for idx, market in enumerate(markets, 1):
            try:
                # Extract both IDs
                numeric_id = market.get('id')  # Numeric ID
                condition_id = market.get('conditionId')  # Hex string

                if not numeric_id or not condition_id:
                    print(f"   [WARNING] Market missing ID: {market.get('question', 'Unknown')[:50]}")
                    error_count += 1
                    continue

                if not test_mode:
                    # Store in database using conditionId as primary key
                    # but also store numeric ID in api_id column
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()

                    cursor.execute("""
                        INSERT INTO markets
                            (market_id, title, category, end_date, resolved,
                             winning_outcome, condition_id, api_id, last_checked,
                             data_source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'api_refresh')
                        ON CONFLICT(market_id) DO UPDATE SET
                            title        = excluded.title,
                            category     = excluded.category,
                            end_date     = excluded.end_date,
                            condition_id = excluded.condition_id,
                            api_id       = excluded.api_id,
                            last_checked = excluded.last_checked
                    """, (
                        condition_id,  # market_id = conditionId
                        market.get('question', market.get('title', 'Unknown')),
                        market.get('category', 'Unknown'),
                        market.get('endDate'),
                        0,    # only used for brand-new rows
                        None, # only used for brand-new rows
                        condition_id,  # condition_id column
                        str(numeric_id),  # api_id column (IMPORTANT!)
                        datetime.now()
                    ))

                    conn.commit()
                    conn.close()

                stored_count += 1

                # Progress update
                if idx % 100 == 0:
                    print(f"   Stored {stored_count}/{len(markets)} markets...", end='\r')

            except Exception as e:
                print(f"\n   [ERROR] Failed to store market: {e}")
                error_count += 1

        print(f"   Stored {stored_count}/{len(markets)} markets              ")

        if error_count > 0:
            print(f"   [WARNING] {error_count} markets had errors")

        self.stats['markets_stored'] = stored_count
        print()

    def analyze_trade_linkage(self):
        """
        Analyze which trades can still be linked to markets after refresh.
        """
        print("\n" + "="*70)
        print("ANALYZING TRADE LINKAGE")
        print("="*70 + "\n")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count total trades
        cursor.execute("SELECT COUNT(*) FROM trades")
        total_trades = cursor.fetchone()[0]

        # Count trades with matching markets
        cursor.execute("""
            SELECT COUNT(*)
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
        """)
        linked_trades = cursor.fetchone()[0]

        orphaned_trades = total_trades - linked_trades

        self.stats['trades_preserved'] = linked_trades
        self.stats['trades_orphaned'] = orphaned_trades

        print(f"   Total trades in database: {total_trades}")
        print(f"   [OK] Trades linked to markets: {linked_trades} ({linked_trades/total_trades*100:.1f}%)")

        if orphaned_trades > 0:
            print(f"   [WARNING] Orphaned trades: {orphaned_trades} ({orphaned_trades/total_trades*100:.1f}%)")
            print(f"            These trades reference markets no longer in the database")

        conn.close()
        print()

    def verify_refresh(self):
        """
        Verify the refresh was successful.
        """
        print("\n" + "="*70)
        print("VERIFYING REFRESH")
        print("="*70 + "\n")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Count markets
        cursor.execute("SELECT COUNT(*) FROM markets")
        total_markets = cursor.fetchone()[0]

        # Count markets with both IDs
        cursor.execute("SELECT COUNT(*) FROM markets WHERE api_id IS NOT NULL AND api_id != ''")
        markets_with_api_id = cursor.fetchone()[0]

        # Sample a market to test resolution checking
        cursor.execute("""
            SELECT market_id, api_id, title
            FROM markets
            WHERE api_id IS NOT NULL
            LIMIT 1
        """)
        sample = cursor.fetchone()

        conn.close()

        print(f"   Total markets: {total_markets}")
        print(f"   [OK] Markets with api_id: {markets_with_api_id} ({markets_with_api_id/total_markets*100:.1f}%)")

        if sample:
            market_id, api_id, title = sample
            print(f"\n   Sample market:")
            print(f"      Title: {title[:60]}")
            print(f"      market_id: {market_id[:50]}")
            print(f"      api_id: {api_id}")

            # Test API call
            print(f"\n   Testing resolution API call...")
            try:
                url = f"{self.gamma_api_base}/markets/{api_id}"
                response = self.session.get(url, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    print(f"   [OK] API call successful!")
                    print(f"        umaResolutionStatus: {data.get('umaResolutionStatus', 'N/A')}")
                    print(f"        closed: {data.get('closed', 'N/A')}")
                else:
                    print(f"   [ERROR] API call failed: {response.status_code}")

            except Exception as e:
                print(f"   [ERROR] API test failed: {e}")

        print()

    def print_summary(self):
        """Print final summary of refresh operation."""
        print("\n" + "="*70)
        print("REFRESH SUMMARY")
        print("="*70)
        print(f"Markets backed up: {self.stats['markets_backed_up']}")
        print(f"Markets fetched from API: {self.stats['markets_fetched']}")
        print(f"Markets after filtering: {self.stats['markets_filtered']}")
        print(f"Markets stored: {self.stats['markets_stored']}")
        print(f"API requests made: {self.stats['api_requests']}")
        print()
        print(f"Trade linkage:")
        print(f"  [OK] Preserved: {self.stats['trades_preserved']}")
        if self.stats['trades_orphaned'] > 0:
            print(f"  [WARNING] Orphaned: {self.stats['trades_orphaned']}")
        print("="*70)
        print()

    def run_refresh(self, backup_only: bool = False, test_mode: bool = False,
                   limit: Optional[int] = None):
        """
        Run the complete refresh process.

        Args:
            backup_only: Only backup, don't refresh
            test_mode: Dry run (no DB writes)
            limit: Max markets to fetch (for testing)
        """
        print("\n" + "="*70)
        print("MARKET DATABASE REFRESH")
        print("="*70)

        if test_mode:
            print("\n[TEST MODE] Dry run - no database changes will be made\n")

        # Step 1: Backup
        backup_file = self.backup_markets_table()

        if backup_only:
            print("[BACKUP ONLY] Exiting without refresh")
            return

        # Step 2: Fetch current markets
        markets = self.fetch_all_markets(limit=limit)

        if not markets:
            print("[ERROR] No markets fetched - aborting refresh")
            return

        # Step 3: Filter markets
        filtered_markets = self.filter_markets(markets)

        if not filtered_markets:
            print("[ERROR] No markets after filtering - aborting refresh")
            return

        # Step 4: Clear old markets (unless test mode)
        if not test_mode:
            # Confirm before clearing
            print("\n" + "="*70)
            print("READY TO CLEAR OLD MARKETS")
            print("="*70)
            print(f"\nBackup saved to: {backup_file}")
            print(f"Will replace {self.stats['markets_backed_up']} old markets")
            print(f"with {len(filtered_markets)} new markets")
            print("\nPress Ctrl+C to cancel, or wait 5 seconds to continue...")

            try:
                time.sleep(5)
                self.clear_markets_table()
            except KeyboardInterrupt:
                print("\n\n[CANCELLED] Refresh aborted by user")
                return

        # Step 5: Store new markets
        self.store_markets(filtered_markets, test_mode=test_mode)

        # Step 6: Analyze trade linkage
        if not test_mode:
            self.analyze_trade_linkage()

        # Step 7: Verify
        if not test_mode:
            self.verify_refresh()

        # Step 8: Summary
        self.print_summary()

        if test_mode:
            print("[TEST MODE] No changes were made to the database")
        else:
            print("[OK] Refresh complete!")
            print(f"\nBackup file: {backup_file}")
            print("\nNext steps:")
            print("1. Run: python monitoring/check_market_resolutions.py --check")
            print("2. Monitor for newly resolved markets")
        print()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Refresh Polymarket markets database with current active markets"
    )
    parser.add_argument(
        '--backup-only',
        action='store_true',
        help='Only backup existing markets, don\'t refresh'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode - fetch and filter but don\'t modify database'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of markets to fetch (for testing)'
    )
    parser.add_argument(
        '--db',
        type=str,
        default='data/polymarket_tracker.db',
        help='Path to database file'
    )

    args = parser.parse_args()

    refresher = MarketRefresher(db_path=args.db)
    refresher.run_refresh(
        backup_only=args.backup_only,
        test_mode=args.test,
        limit=args.limit
    )


if __name__ == "__main__":
    main()
