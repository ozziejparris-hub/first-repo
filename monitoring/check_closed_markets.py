"""
Investigation tool for closed markets using official Polymarket API fields.

Uses documented fields from docs.polymarket.com:
- umaResolutionStatus: "resolved" when complete
- outcomes: JSON string of outcome names
- outcomePrices: JSON string of prices (winner = "1.00")
"""

import sqlite3
import requests
import json
import sys


def check_closed_markets(limit: int = 10):
    """Find and investigate closed markets."""

    print("\n" + "="*70)
    print("INVESTIGATING CLOSED MARKETS (Official API Fields)")
    print("="*70 + "\n")

    conn = sqlite3.connect('data/polymarket_tracker.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT market_id, title
        FROM markets
        WHERE resolved = 0
        ORDER BY RANDOM()
        LIMIT ?
    ''', (limit * 10,))

    markets = cursor.fetchall()
    conn.close()

    session = requests.Session()
    closed_count = 0
    resolved_count = 0
    checked = 0

    print(f"Checking {len(markets)} markets...\n")

    for market_id, title in markets:
        if closed_count >= limit:
            break

        checked += 1

        try:
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            response = session.get(url, timeout=10)

            if response.status_code != 200:
                continue

            data = response.json()

            # Check official resolution status
            uma_status = data.get('umaResolutionStatus', '').lower()
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)

            if not (is_closed or is_archived or uma_status == 'resolved'):
                continue

            closed_count += 1

            # Safe title encoding
            safe_title = title[:65] if title else 'Unknown'
            try:
                safe_title = safe_title.encode('ascii', 'replace').decode('ascii')
            except:
                pass

            print(f"\n{'='*70}")
            print(f"CLOSED MARKET #{closed_count}")
            print(f"{'='*70}")
            print(f"Title: {safe_title}")
            print(f"Market ID: {market_id}")
            print(f"UMA Resolution Status: {uma_status.upper()}")
            print(f"Closed: {is_closed}")
            print(f"Archived: {is_archived}")

            # If resolved, show winner
            if uma_status == 'resolved':
                resolved_count += 1

                outcomes_raw = data.get('outcomes', '[]')
                prices_raw = data.get('outcomePrices', '[]')

                try:
                    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

                    print(f"\n[RESOLVED]:")
                    for outcome, price in zip(outcomes, prices):
                        marker = " <- WINNER" if float(price) == 1.0 else ""
                        print(f"   {outcome}: ${price}{marker}")

                except Exception as e:
                    print(f"   [ERROR] Could not parse winner: {e}")
            else:
                print(f"\n[PENDING RESOLUTION]")
                print(f"   Market closed but awaiting UMA resolution")

        except Exception as e:
            continue

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Markets checked: {checked}")
    print(f"Closed markets found: {closed_count}")
    print(f"Actually resolved: {resolved_count}")
    print()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    check_closed_markets(limit)
