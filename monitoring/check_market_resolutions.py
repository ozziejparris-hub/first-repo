#!/usr/bin/env python3
"""
Market Resolution Checker and Diagnostic Tool

Comprehensive system for checking and diagnosing market resolution status
on Polymarket using the UMA Optimistic Oracle process.

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
            # Try CLOB API first (accepts conditionId)
            clob_url = f"https://clob.polymarket.com/markets/{market_id}"
            print(f"API Request (CLOB): {clob_url}")
            response = self.session.get(clob_url, timeout=10)
            print(f"Status Code: {response.status_code}")

            # If CLOB fails, try Gamma API (accepts numeric ID)
            if response.status_code != 200:
                url = f"{self.base_url}/markets/{market_id}"
                print(f"[INFO] CLOB failed, trying Gamma API: {url}")
                response = self.session.get(url, timeout=10)
                print(f"Status Code: {response.status_code}")

                if response.status_code != 200:
                    print(f"[ERROR] Error: Both APIs returned errors")
                    print(f"Response text: {response.text[:200]}")
                    return None
            else:
                print(f"[OK] CLOB API succeeded")

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

            # Check outcomes
            outcomes = data.get('outcomes', [])
            print(f"\n[OUTCOMES] OUTCOMES ({len(outcomes)} total):")

            for idx, outcome in enumerate(outcomes):
                print(f"\n   Outcome {idx + 1}:")

                # Handle both dict and string outcomes
                if isinstance(outcome, dict):
                    print(f"      Name: {safe_str(outcome.get('name', 'N/A'))}")
                    print(f"      Payout Numerator: {outcome.get('payoutNumerator', 'N/A')}")
                    print(f"      Index: {outcome.get('index', 'N/A')}")

                    # Check if this is winning outcome
                    if outcome.get('payoutNumerator') == 1000:
                        print(f"      [WINNER] WINNING OUTCOME")
                else:
                    # Outcome is a string or other type
                    print(f"      Value: {safe_str(outcome)}")

            # Check resolution source info
            print(f"\n[INFO] RESOLUTION INFO:")
            print(f"   Resolution Source: {safe_str(data.get('resolutionSource', 'N/A'))}")
            print(f"   Description: {safe_str(data.get('description', 'N/A'), max_len=100)}")

            # Determine actual resolution status
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)
            is_resolved = data.get('resolved', False)

            has_winner = any(isinstance(o, dict) and o.get('payoutNumerator') == 1000 for o in outcomes)

            print(f"\n[OK] RESOLUTION DETERMINATION:")
            print(f"   API says closed: {is_closed}")
            print(f"   API says archived: {is_archived}")
            print(f"   API says resolved: {is_resolved}")
            print(f"   Has winning outcome (payoutNumerator=1000): {has_winner}")

            # Final determination
            if has_winner and (is_closed or is_archived or is_resolved):
                winning_outcome = next((o for o in outcomes if isinstance(o, dict) and o.get('payoutNumerator') == 1000), None)
                print(f"\n[RESOLVED] MARKET IS RESOLVED")
                if winning_outcome:
                    print(f"   Winning Outcome: {safe_str(winning_outcome.get('name', 'Unknown'))}")
                    return {
                        'resolved': True,
                        'winning_outcome': winning_outcome.get('name', 'Unknown'),
                        'resolution_date': data.get('resolvedAt') or data.get('endDate'),
                        'data': data
                    }
                else:
                    return {
                        'resolved': True,
                        'winning_outcome': 'Unknown',
                        'resolution_date': data.get('resolvedAt') or data.get('endDate'),
                        'data': data
                    }
            else:
                print(f"\n[PENDING] MARKET NOT YET RESOLVED")
                if is_closed:
                    print(f"   Note: Market is closed but may still be in UMA challenge/dispute period")
                return {
                    'resolved': False,
                    'closed': is_closed,
                    'archived': is_archived,
                    'data': data
                }

        except Exception as e:
            print(f"\n[ERROR] Error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_market_resolution(self, market_id: str) -> Optional[Dict]:
        """
        Get market resolution status from Polymarket API.

        Uses improved logic that checks multiple indicators.
        Handles both conditionId (hex string) and numeric ID.

        Args:
            market_id: Market ID to check (conditionId or numeric ID)

        Returns:
            dict with:
            - resolved: bool (True if market has finalized outcome)
            - winning_outcome: str (if resolved)
            - resolution_date: datetime (if resolved)
            - status: str (open/closed/resolved)
        """
        try:
            # Try CLOB API first (accepts conditionId)
            clob_url = f"https://clob.polymarket.com/markets/{market_id}"
            response = self.session.get(clob_url, timeout=10)

            # If CLOB fails, try Gamma API (accepts numeric ID)
            if response.status_code != 200:
                url = f"{self.base_url}/markets/{market_id}"
                response = self.session.get(url, timeout=10)

                if response.status_code != 200:
                    return {"resolved": False, "status": "error", "error_code": response.status_code}

            data = response.json()

            # Check multiple indicators of resolution
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)
            is_resolved = data.get('resolved', False)  # Some APIs have this field

            # Most reliable: check if any outcome has payoutNumerator = 1000
            outcomes = data.get('outcomes', [])
            winning_outcome = None

            for outcome in outcomes:
                # Handle both dict and string outcomes
                if isinstance(outcome, dict):
                    if outcome.get('payoutNumerator') == 1000:
                        winning_outcome = outcome.get('name', '').lower()
                        break

            # Market is resolved if:
            # 1. Has winning outcome (payoutNumerator = 1000), AND
            # 2. Is closed OR archived OR marked as resolved
            if winning_outcome and (is_closed or is_archived or is_resolved):
                return {
                    "resolved": True,
                    "winning_outcome": winning_outcome,
                    "resolution_date": data.get('resolvedAt') or data.get('endDate'),
                    "status": "resolved",
                    "market_data": data
                }

            # Market is closed but not yet resolved (might be in UMA challenge period)
            elif is_closed:
                return {
                    "resolved": False,
                    "status": "closed_pending",
                    "note": "Market closed but may be in UMA challenge/dispute period",
                    "market_data": data
                }

            # Market is still active
            else:
                return {
                    "resolved": False,
                    "status": "active",
                    "market_data": data
                }

        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            return {"resolved": False, "status": "error", "error": str(e)}

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

    def run_full_resolution_check(self) -> int:
        """
        Run comprehensive resolution check on all unresolved markets.

        Returns:
            int: Number of newly resolved markets found
        """
        print("\n" + "="*70)
        print("FULL RESOLUTION CHECK")
        print("="*70)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, title
            FROM markets
            WHERE (resolved = 0 OR resolved IS NULL)
            ORDER BY last_checked ASC
        """)

        markets = cursor.fetchall()
        conn.close()

        print(f"\nChecking {len(markets)} unresolved markets...")

        newly_resolved = 0
        closed_pending = 0
        still_active = 0
        errors = 0

        for idx, (market_id, title) in enumerate(markets, 1):
            if idx % 10 == 0 or idx == 1:
                print(f"\nProgress: {idx}/{len(markets)}")

            try:
                result = self.get_market_resolution(market_id)

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

        print(f"\n{'='*70}")
        print("RESOLUTION CHECK COMPLETE")
        print(f"{'='*70}")
        print(f"\n[STATUS] Results:")
        print(f"   Newly resolved: {newly_resolved}")
        print(f"   Closed (pending): {closed_pending}")
        print(f"   Still active: {still_active}")
        print(f"   Errors: {errors}")
        print(f"   Total checked: {len(markets)}")

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
        checker.run_full_resolution_check()

    else:
        # Default: run diagnostics
        print("No action specified. Running diagnostics...")
        print("Use --help to see available options\n")
        checker.run_diagnostics()


if __name__ == "__main__":
    main()
