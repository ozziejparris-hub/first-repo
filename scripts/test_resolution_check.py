#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test resolution check with updated market IDs"""

import sys
import os

# Configure console encoding for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.database import Database

def test_unresolved_markets():
    """Test that get_unresolved_markets returns correct market_id format."""

    db = Database()
    markets = db.get_unresolved_markets()

    print("="*70)
    print("TESTING UNRESOLVED MARKETS QUERY")
    print("="*70)

    print(f"\nTotal unresolved markets: {len(markets)}")

    # Separate markets by ID format
    correct_format = [m for m in markets if not m['market_id'].startswith('0x')]
    old_format = [m for m in markets if m['market_id'].startswith('0x')]

    print(f"\nMarkets with CORRECT API-compatible IDs: {len(correct_format)}")
    print(f"Markets with OLD conditionId format: {len(old_format)}")

    print("\n" + "="*70)
    print("MARKETS THAT WILL WORK WITH RESOLUTION CHECK:")
    print("="*70)

    for idx, market in enumerate(correct_format[:10], 1):
        print(f"{idx}. {market['market_id']}: {market['title'][:60]}")

    print("\n" + "="*70)
    print("EXPECTED RESULTS:")
    print("="*70)
    print(f"✓ {len(correct_format)} markets will successfully call API")
    print(f"✗ {len(old_format)} markets will fail (old/closed markets)")
    print(f"\nSuccess rate: {len(correct_format)/len(markets)*100:.1f}%")

if __name__ == "__main__":
    test_unresolved_markets()
