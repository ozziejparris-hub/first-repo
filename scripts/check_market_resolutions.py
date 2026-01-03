#!/usr/bin/env python3
"""
Market Resolution Checker and Diagnostic Tool

Comprehensive system for checking and diagnosing market resolution status
on Polymarket using the UMA Optimistic Oracle process.

Uses official Polymarket Gamma API fields (docs.polymarket.com):
- umaResolutionStatus: "resolved" when market is resolved via UMA
- outcomes: JSON string like '["Yes", "No"]'
- outcomePrices: JSON string like '["1.00", "0.00"]' (winner has price "1")

UMA Resolution Process:
1. Someone proposes a resolution (posts $750 bond)
2. 2-hour challenge period begins
3. If challenged: 24-48 hour debate + UMA token holder vote
4. If not challenged: Resolution confirmed after 2 hours
5. Winning shares get $1, losing shares become worthless

Market States:
- Open/Active: trading ongoing
- Closed: end date reached, but not resolved yet
- Resolved: UMA process complete, outcome finalized
"""

import requests
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional
import argparse
import json


class MarketResolutionChecker:
    """Check and diagnose market resolution status."""

    def __init__(self, db_path: str = "data/polymarket_tracker.db", api_key: str = None):
        """
        Initialize resolution checker.

        Args:
            db_path: Path to SQLite database
            api_key: Polymarket API key (optional)
        """
        self.db_path = db_path
        self.base_url = "https://gamma-api.polymarket.com"

        # Setup session with headers
        self.session = requests.Session()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PolymarketTracker/1.0"
        }

        if api_key:
            headers.update({
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "APIKEY": api_key
            })

        self.session.headers.update(headers)

    def diagnose_market_status(self, market_id: str) -> Optional[Dict]:
        """
        Comprehensive diagnostics for a single market's resolution status.

        Returns detailed status information for debugging.

        Args:
            market_id: Market ID to diagnose

        Returns:
            dict with diagnostic information or None if error
        """
        print(f"\n{'='*70}")
        print(f"DIAGNOSING MARKET: {market_id}")
        print(f"{'='*70}\n")

        try:
            # Use Gamma API (has complete resolution data)
            url = f"{self.base_url}/markets/{market_id}"
            print(f"API Request (Gamma): {url}")
            response = self.session.get(url, timeout=10)
            print(f"Status Code: {response.status_code}")

            if response.status_code != 200:
                print(f"[ERROR] API returned error: {response.status_code}")
                print(f"Response text: {response.text[:200]}")
                return None

            data = response.json()

            # Print all relevant fields (safe encoding for unicode characters)
            def safe_str(s, max_len=60):
                """Safely encode string for console output."""
                if s is None or s == 'N/A':
                    return 'N/A'
                try:
                    return str(s)[:max_len].encode('ascii', 'replace').decode('ascii')
                except:
                    return str(s)[:max_len]

            print(f"\n[STATUS] MARKET STATUS FIELDS:")
            print(f"   Title: {safe_str(data.get('question', data.get('title', 'N/A')))}")
            print(f"   Market ID: {safe_str(data.get('id', 'N/A'))}")
            print(f"   Condition ID: {safe_str(data.get('conditionId', 'N/A'))}")
            print(f"   Closed: {data.get('closed', False)}")
            print(f"   Archived: {data.get('archived', False)}")
            print(f"   Active: {data.get('active', True)}")
            print(f"   Resolved: {data.get('resolved', 'N/A')}")
            print(f"   End Date: {safe_str(data.get('endDate', 'N/A'))}")
            print(f"   Resolved At: {safe_str(data.get('resolvedAt', 'N/A'))}")

            # Check resolution status (official field)
            uma_status = data.get('umaResolutionStatus', 'N/A')
            resolved_by = data.get('resolvedBy', 'N/A')

            print(f"\n[RESOLUTION STATUS]:")
            print(f"   UMA Resolution Status: {uma_status}")
            print(f"   Resolved By: {safe_str(resolved_by, max_len=42)}")

            # Check outcomes and prices
            outcomes_raw = data.get('outcomes', '[]')
            prices_raw = data.get('outcomePrices', '[]')

            print(f"\n[OUTCOMES]:")
            print(f"   Raw outcomes: {safe_str(str(outcomes_raw), max_len=100)}")
            print(f"   Raw prices: {safe_str(str(prices_raw), max_len=100)}")

            # Parse JSON strings
            try:
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                print(f"   Parsed outcomes: {outcomes}")
                print(f"   Parsed prices: {prices}")

                # Check for winner
                if uma_status.lower() == 'resolved' and outcomes and prices:
                    print(f"\n   [WINNER DETERMINATION]:")
                    for idx, (outcome, price) in enumerate(zip(outcomes, prices)):
                        price_float = float(price)
                        status = " <- WINNER!" if price_float == 1.0 else ""
                        print(f"      {outcome}: ${price}{status}")

            except (json.JSONDecodeError, ValueError) as e:
                print(f"   [ERROR] Could not parse outcomes/prices: {e}")

            # Check resolution source info
            print(f"\n[INFO] RESOLUTION INFO:")
            print(f"   Resolution Source: {safe_str(data.get('resolutionSource', 'N/A'))}")
            print(f"   Description: {safe_str(data.get('description', 'N/A'), max_len=100)}")

            # Final determination using official fields
            uma_status = data.get('umaResolutionStatus', '').lower()
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)

            print(f"\n[OK] RESOLUTION DETERMINATION:")
            print(f"   UMA Resolution Status: {uma_status}")
            print(f"   API says closed: {is_closed}")
            print(f"   API says archived: {is_archived}")

            if uma_status == 'resolved':
                # Parse outcomes and prices to find winner
                try:
                    outcomes_raw = data.get('outcomes', '[]')
                    prices_raw = data.get('outcomePrices', '[]')
                    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                    winning_outcome = None
                    for idx, price in enumerate(prices):
                        if float(price) == 1.0:
                            winning_outcome = outcomes[idx]
                            break

                    print(f"\n[RESOLVED] MARKET IS RESOLVED")
                    print(f"   Winning Outcome: {winning_outcome or 'Unknown'}")
                    return {
                        'resolved': True,
                        'winning_outcome': winning_outcome,
                        'data': data
                    }
                except Exception as e:
                    print(f"   [ERROR] Could not determine winner: {e}")
                    return {
                        'resolved': True,
                        'winning_outcome': 'unknown',
                        'data': data
                    }

            elif is_closed or is_archived:
                print(f"\n[PENDING] MARKET NOT YET RESOLVED")
                print(f"   Note: Market is closed but may still be in UMA challenge/dispute period")
                return {
                    'resolved': False,
                    'status': 'closed_pending',
                    'data': data
                }
            else:
                print(f"\n[PENDING] MARKET NOT YET RESOLVED")
                print(f"   Market is still active/trading")
                return {
                    'resolved': False,
                    'status': 'active',
                    'data': data
                }

        except Exception as e:
            print(f"\n[ERROR] Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_market_resolution(self, market_id: str, api_id: str = None) -> Optional[Dict]:
        """
        Get market resolution status using official Gamma API fields.

        Uses documented fields from docs.polymarket.com:
        - umaResolutionStatus: "resolved" when market is resolved
        - outcomes: JSON string like '["Yes", "No"]'
        - outcomePrices: JSON string like '["1.00", "0.00"]'

        Args:
            market_id: Market ID from database (may be conditionId)
            api_id: Numeric API ID (preferred if available)

        Returns:
            Dict with:
            - resolved: bool
            - winning_outcome: str (if resolved)
            - resolution_date: str (if resolved)
            - status: str ('resolved', 'closed_pending', 'active')
        """
        # Prefer api_id if provided, otherwise use market_id
        id_to_use = api_id if api_id else market_id

        try:
            # Use Gamma API (has complete resolution data)
            url = f"{self.base_url}/markets/{id_to_use}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return {
                    "resolved": False,
                    "status": "error",
                    "error_code": response.status_code
                }

            data = response.json()

            # Check official resolution status field
            uma_status = data.get('umaResolutionStatus', '').lower()
            is_resolved = uma_status == 'resolved'

            if is_resolved:
                # Parse outcomes and prices (both are JSON strings)
                outcomes_raw = data.get('outcomes', '[]')
                prices_raw = data.get('outcomePrices', '[]')

                try:
                    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                    # Find winning outcome (price = 1.0)
                    winning_outcome = None
                    for idx, price in enumerate(prices):
                        if float(price) == 1.0:
                            winning_outcome = outcomes[idx].lower()
                            break

                    if not winning_outcome and outcomes:
                        # Fallback: if no price is 1.0, something's wrong
                        # Log warning but still mark as resolved
                        print(f"[WARNING] Market {market_id} resolved but no winning price found")
                        print(f"Prices: {prices}, Outcomes: {outcomes}")
                        winning_outcome = "unknown"

                    return {
                        "resolved": True,
                        "winning_outcome": winning_outcome or "unknown",
                        "resolution_date": data.get('closedTime') or data.get('updatedAt'),
                        "status": "resolved",
                        "market_data": data
                    }

                except (json.JSONDecodeError, ValueError, IndexError) as e:
                    print(f"[ERROR] Failed to parse outcomes/prices for {market_id}: {e}")
                    return {
                        "resolved": True,  # Still mark as resolved
                        "winning_outcome": "unknown",
                        "resolution_date": data.get('closedTime'),
                        "status": "resolved",
                        "error": str(e)
                    }

            # Check if closed but not yet resolved
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)

            if is_closed or is_archived:
                return {
                    "resolved": False,
                    "status": "closed_pending",
                    "note": "Market closed but awaiting UMA resolution",
                    "closed": is_closed,
                    "archived": is_archived
                }

            # Market is still active
            return {
                "resolved": False,
                "status": "active"
            }

        except Exception as e:
            print(f"[ERROR] Exception fetching market {market_id}: {e}")
            import traceback
            traceback.print_exc()
            return {
                "resolved": False,
                "status": "error",
                "error": str(e)
            }

    def test_known_resolved_market(self):
        """
        Test resolution detection with known resolved markets.

        The 2024 US Presidential Election market should be resolved by now
        (election was Nov 5, 2024, current date is Dec 10, 2024).
        """
        print("\n" + "="*70)
        print("TESTING WITH KNOWN RESOLVED MARKETS")
        print("="*70)

        # Try to find presidential election market
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, title, resolved, winning_outcome
            FROM markets
            WHERE (title LIKE '%Presidential%'
            OR title LIKE '%Trump%Harris%'
            OR title LIKE '%2024%Election%'
            OR title LIKE '%President%')
            AND title NOT LIKE '%poll%'
            LIMIT 5
        """)

        markets = cursor.fetchall()
        conn.close()

        if markets:
            print(f"\nFound {len(markets)} potential presidential election markets in database:")
            for market_id, title, resolved, winning in markets:
                print(f"\n{'='*70}")
                # Safe print for market title
                safe_title = title[:60] if title else 'Unknown'
                try:
                    safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
                except:
                    pass
                print(f"Market: {safe_title}")
                print(f"ID: {market_id}")
                print(f"Current DB status: Resolved={resolved}, Winner={winning or 'None'}")

                # Diagnose this market
                result = self.diagnose_market_status(market_id)

                if result and result['resolved']:
                    print(f"\n   [OK] API confirms this market IS resolved")
                    safe_winner = result.get('winning_outcome', 'Unknown')
                    try:
                        safe_winner = safe_winner.encode('ascii', 'replace').decode('ascii')
                    except:
                        pass
                    print(f"   Winner: {safe_winner}")

                    if not resolved:
                        print(f"\n   [WARNING]  DATABASE OUT OF SYNC!")
                        print(f"   API shows resolved, but DB shows: Resolved={resolved}")
                else:
                    print(f"\n   [PENDING] API shows this market is NOT YET resolved")
        else:
            print("\n[WARNING]  No presidential election markets found in database")
            print("This suggests monitoring may not have picked up these markets")

    def check_database_schema(self):
        """Check if database schema supports resolution tracking."""
        print("\n" + "="*70)
        print("DATABASE SCHEMA CHECK")
        print("="*70 + "\n")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get table schema
        cursor.execute("PRAGMA table_info(markets)")
        columns = cursor.fetchall()

        print("Markets table columns:")
        for col in columns:
            col_id, name, type_, not_null, default, pk = col
            print(f"   {name}: {type_}")

        # Check if we have resolution fields
        column_names = [col[1] for col in columns]

        required_fields = ['resolved', 'winning_outcome', 'resolution_date', 'end_date', 'last_checked']

        print("\nRequired fields:")
        for field in required_fields:
            if field in column_names:
                print(f"   [OK] {field}")
            else:
                print(f"   [MISSING] {field}")

        # Count current state
        cursor.execute("SELECT COUNT(*) FROM markets")
        total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM markets
            WHERE resolved = 1
            AND winning_outcome IS NOT NULL
            AND winning_outcome != ''
        """)
        resolved_count = cursor.fetchone()[0]

        print(f"\n[STATUS] Current Database State:")
        print(f"   Total markets: {total}")
        print(f"   Resolved markets: {resolved_count} ({resolved_count/total*100 if total > 0 else 0:.1f}%)")

        conn.close()

    def check_sample_markets(self, sample_size: int = 5):
        """
        Check a random sample of unresolved markets.

        Args:
            sample_size: Number of markets to check
        """
        print("\n" + "="*70)
        print(f"CHECKING SAMPLE OF {sample_size} UNRESOLVED MARKETS")
        print("="*70)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT market_id, title
            FROM markets
            WHERE (resolved = 0 OR resolved IS NULL)
            ORDER BY RANDOM()
            LIMIT {sample_size}
        """)

        markets = cursor.fetchall()
        conn.close()

        if not markets:
            print("\n[WARNING]  No unresolved markets found in database")
            return

        for market_id, title in markets:
            print(f"\n{'='*70}")
            # Safe print for market title with unicode characters
            safe_title = title[:60] if title else 'Unknown'
            try:
                safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
            except:
                pass
            print(f"Sample Market: {safe_title}")
            result = self.diagnose_market_status(market_id)

            if result and result.get('resolved'):
                print(f"\n[WARNING]  This market appears to be resolved but wasn't in DB!")
                safe_winner = result.get('winning_outcome', 'Unknown')
                try:
                    safe_winner = safe_winner.encode('ascii', 'replace').decode('ascii')
                except:
                    pass
                print(f"Winner: {safe_winner}")

    def run_full_resolution_check(self, smart_mode: bool = True) -> int:
        """
        Run comprehensive resolution check on all unresolved markets.

        Args:
            smart_mode: If True, only check markets past their end date + 2 hours.
                       If False, check all unresolved markets (slower).

        Returns:
            int: Number of newly resolved markets found
        """
        print("\n" + "="*70)
        print("FULL RESOLUTION CHECK")
        print("="*70)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build query based on mode
        if smart_mode:
            print("\n[SMART MODE] Only checking markets past end date + 2 hours")
            query = """
                SELECT market_id, title, api_id, end_date
                FROM markets
                WHERE (resolved = 0 OR resolved IS NULL)
                  AND end_date IS NOT NULL
                  AND datetime(end_date) < datetime('now', '-2 hours')
                ORDER BY last_checked ASC
            """
        else:
            print("\n[FULL MODE] Checking all unresolved markets")
            query = """
                SELECT market_id, title, api_id, end_date
                FROM markets
                WHERE (resolved = 0 OR resolved IS NULL)
                ORDER BY last_checked ASC
            """

        cursor.execute(query)
        markets = cursor.fetchall()
        conn.close()

        if len(markets) == 0:
            print("\n[OK] No markets need checking!")
            return 0

        # Time estimation
        estimated_seconds = len(markets) * 0.2
        estimated_minutes = estimated_seconds / 60
        estimated_hours = estimated_minutes / 60

        print(f"\nFound {len(markets)} markets to check")
        if estimated_hours >= 1:
            print(f"Estimated time: {estimated_hours:.1f} hours")
        elif estimated_minutes >= 1:
            print(f"Estimated time: {estimated_minutes:.1f} minutes")
        else:
            print(f"Estimated time: {estimated_seconds:.0f} seconds")

        newly_resolved = 0
        closed_pending = 0
        still_active = 0
        errors = 0

        start_time = time.time()

        for idx, (market_id, title, api_id, end_date) in enumerate(markets, 1):
            if idx % 10 == 0 or idx == 1:
                # Calculate progress
                elapsed = time.time() - start_time
                if idx > 1:
                    rate = elapsed / (idx - 1)
                    remaining = (len(markets) - idx) * rate
                    eta_minutes = remaining / 60
                    eta_hours = eta_minutes / 60

                    if eta_hours >= 1:
                        eta_str = f"{eta_hours:.1f}h"
                    elif eta_minutes >= 1:
                        eta_str = f"{eta_minutes:.1f}m"
                    else:
                        eta_str = f"{remaining:.0f}s"

                    print(f"\nProgress: {idx}/{len(markets)} (ETA: {eta_str})")
                else:
                    print(f"\nProgress: {idx}/{len(markets)}")

            try:
                result = self.get_market_resolution(market_id, api_id)

                if result['status'] == 'resolved':
                    safe_title = title[:50] if title else 'Unknown'
                    try:
                        safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
                    except:
                        pass
                    print(f"\n[OK] RESOLVED: {safe_title}")

                    safe_winner = result.get('winning_outcome', 'Unknown')
                    try:
                        safe_winner = safe_winner.encode('ascii', 'replace').decode('ascii')
                    except:
                        pass
                    print(f"   Winner: {safe_winner}")

                    # Update database
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()

                    cursor.execute("""
                        UPDATE markets
                        SET resolved = 1,
                            winning_outcome = ?,
                            resolution_date = ?,
                            last_checked = ?
                        WHERE market_id = ?
                    """, (result['winning_outcome'], datetime.now(),
                          datetime.now(), market_id))

                    conn.commit()
                    conn.close()

                    newly_resolved += 1

                elif result['status'] == 'closed_pending':
                    closed_pending += 1
                    if idx <= 5:
                        safe_title = title[:50] if title else 'Unknown'
                        try:
                            safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
                        except:
                            pass
                        print(f"\n[PENDING] CLOSED (pending resolution): {safe_title}")

                elif result['status'] == 'active':
                    still_active += 1

                elif result['status'] == 'error':
                    errors += 1
                    if idx <= 5:
                        safe_title = title[:50] if title else 'Unknown'
                        try:
                            safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
                        except:
                            pass
                        print(f"\n[ERROR] ERROR: {safe_title}")

                # Rate limiting
                time.sleep(0.1)

            except Exception as e:
                print(f"\n[ERROR] Exception checking {market_id}: {e}")
                errors += 1

        elapsed_total = time.time() - start_time
        elapsed_minutes = elapsed_total / 60

        print(f"\n{'='*70}")
        print("RESOLUTION CHECK COMPLETE")
        print(f"{'='*70}")
        print(f"\n[STATUS] Results:")
        print(f"   Newly resolved: {newly_resolved}")
        print(f"   Closed (pending): {closed_pending}")
        print(f"   Still active: {still_active}")
        print(f"   Errors: {errors}")
        print(f"   Total checked: {len(markets)}")
        print(f"\n[TIME] Elapsed: {elapsed_minutes:.1f} minutes")

        return newly_resolved

    def run_diagnostics(self):
        """Run all diagnostic checks."""
        print("\n" + "="*70)
        print("MARKET RESOLUTION DIAGNOSTICS")
        print("="*70)

        # 1. Check database schema
        self.check_database_schema()

        # 2. Test with known resolved markets
        self.test_known_resolved_market()

        # 3. Check sample of markets
        self.check_sample_markets(sample_size=3)

        print("\n" + "="*70)
        print("DIAGNOSTICS COMPLETE")
        print("="*70 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Market Resolution Checker and Diagnostic Tool'
    )
    parser.add_argument(
        '--diagnose',
        action='store_true',
        help='Run diagnostic checks'
    )
    parser.add_argument(
        '--market-id',
        type=str,
        help='Diagnose specific market by ID'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Run full resolution check on all unresolved markets'
    )
    parser.add_argument(
        '--smart',
        action='store_true',
        default=True,
        help='Smart mode: only check markets past end date + 2 hours (default)'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Full mode: check ALL unresolved markets (overrides --smart)'
    )
    parser.add_argument(
        '--sample',
        type=int,
        default=5,
        help='Number of sample markets to check in diagnostic mode'
    )

    args = parser.parse_args()

    # Initialize checker
    checker = MarketResolutionChecker()

    if args.market_id:
        # Diagnose specific market
        checker.diagnose_market_status(args.market_id)

    elif args.diagnose:
        # Run full diagnostics
        checker.run_diagnostics()

    elif args.check:
        # Run full resolution check
        # Use smart mode by default, unless --full is specified
        smart_mode = not args.full
        checker.run_full_resolution_check(smart_mode=smart_mode)

    else:
        # Default: run diagnostics
        print("No action specified. Running diagnostics...")
        print("Use --help to see available options\n")
        checker.run_diagnostics()


if __name__ == "__main__":
    main()
