#!/usr/bin/env python3
"""
Quick check to see how many markets need fixing
"""
import sqlite3

conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()

print("="*70)
print("MARKETS NEEDING ID FIX")
print("="*70 + "\n")

# Count markets with conditionId format in market_id
cursor.execute("""
    SELECT COUNT(*)
    FROM markets
    WHERE market_id LIKE '0x%'
    AND LENGTH(market_id) = 66
""")

needs_fix = cursor.fetchone()[0]

# Count markets with correct format
cursor.execute("""
    SELECT COUNT(*)
    FROM markets
    WHERE market_id NOT LIKE '0x%'
    OR LENGTH(market_id) != 66
""")

already_correct = cursor.fetchone()[0]

# Sample of markets needing fix
cursor.execute("""
    SELECT market_id, title
    FROM markets
    WHERE market_id LIKE '0x%'
    AND LENGTH(market_id) = 66
    LIMIT 5
""")

print("Sample markets needing fix:")
for market_id, title in cursor.fetchall():
    print(f"  - {title[:60]}")
    print(f"    Current ID: {market_id[:20]}...")
    print()

print("-"*70)
print(f"Markets needing fix: {needs_fix}")
print(f"Markets already correct: {already_correct}")
print(f"Total markets: {needs_fix + already_correct}")
print("="*70 + "\n")

if needs_fix > 0:
    print(f"Run: python scripts/backfill_market_ids.py --dry-run")
    print(f"To preview the backfill without making changes")
else:
    print("All markets already have correct format!")

conn.close()
