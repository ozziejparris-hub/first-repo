"""
Quick script to investigate the 242 closed markets.
Shows which are truly closed and waiting for resolution.
"""

import sqlite3
import requests
import json
from typing import Dict, Optional

def check_closed_markets(limit: int = 10):
    """Check closed markets to understand their status."""
    
    print("\n" + "="*70)
    print("INVESTIGATING CLOSED MARKETS")
    print("="*70 + "\n")
    
    conn = sqlite3.connect('data/polymarket_tracker.db')
    cursor = conn.cursor()
    
    # Get all unresolved markets
    cursor.execute('''
        SELECT market_id, title, condition_id, end_date 
        FROM markets 
        WHERE resolved = 0 
        ORDER BY RANDOM()
        LIMIT ?
    ''', (limit * 5,))  # Get 5x limit since many might not be closed
    
    markets = cursor.fetchall()
    conn.close()
    
    session = requests.Session()
    closed_count = 0
    checked = 0
    
    print(f"Checking {len(markets)} markets for closed status...\n")
    
    for market_id, title, condition_id, end_date in markets:
        if closed_count >= limit:
            break
            
        checked += 1
        
        # Prefer numeric ID for Gamma API if available
        # Otherwise use condition_id
        api_id = market_id
        
        try:
            # Try Gamma API (has better data)
            url = f"https://gamma-api.polymarket.com/markets/{api_id}"
            response = session.get(url, timeout=10)
            
            if response.status_code == 404 and condition_id:
                # Not a numeric ID, skip
                continue
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            
            # Check if closed
            is_closed = data.get('closed', False)
            is_archived = data.get('archived', False)
            
            if not (is_closed or is_archived):
                continue  # Skip active markets
            
            # Found a closed market!
            closed_count += 1
            
            print(f"\n{'='*70}")
            print(f"CLOSED MARKET #{closed_count}")
            print(f"{'='*70}")
            print(f"Title: {title[:65]}")
            print(f"Market ID: {api_id}")
            print(f"Condition ID: {condition_id or 'N/A'}")
            print(f"End Date: {end_date or 'Unknown'}")
            print(f"Closed: {is_closed}")
            print(f"Archived: {is_archived}")
            
            # Parse outcomes properly
            outcomes_raw = data.get('outcomes', [])
            
            # Handle string outcomes (need to parse JSON string)
            if isinstance(outcomes_raw, str):
                try:
                    outcomes = json.loads(outcomes_raw)
                except:
                    outcomes = []
                    print(f"[WARNING] Could not parse outcomes: {outcomes_raw}")
            else:
                outcomes = outcomes_raw
            
            print(f"\nOutcomes: {outcomes}")
            
            # Check for winner
            has_winner = False
            winner_name = None
            
            # Look for payout info in tokens or other fields
            tokens = data.get('tokens', [])
            for token in tokens:
                if isinstance(token, dict):
                    payout = token.get('payoutNumerator')
                    if payout == 1000:
                        has_winner = True
                        winner_name = token.get('outcome', 'Unknown')
                        print(f"\n[WINNER FOUND] {winner_name} (payoutNumerator: 1000)")
            
            if not has_winner:
                print("\n[PENDING RESOLUTION]")
                print("Market is closed but no winner declared yet.")
                print("Possible reasons:")
                print("  - Waiting for someone to propose resolution on UMA")
                print("  - In UMA's 2-hour challenge period")
                print("  - In dispute resolution (24-48 hours)")
                print("  - Resolution source data not available yet")
            
            # Show resolution info
            resolution_source = data.get('resolutionSource', 'Unknown')
            print(f"\nResolution Source: {resolution_source}")
            
        except Exception as e:
            print(f"[ERROR] {api_id}: {e}")
            continue
    
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Markets checked: {checked}")
    print(f"Closed markets found: {closed_count}")
    print(f"\n")

if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    check_closed_markets(limit)