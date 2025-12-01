#!/usr/bin/env python3
"""Check market IDs in database"""
import sqlite3

conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()

print("="*70)
print("SAMPLE MARKET IDs FROM DATABASE")
print("="*70 + "\n")

cursor.execute('SELECT market_id, title FROM markets LIMIT 5')
rows = cursor.fetchall()

for i, (market_id, title) in enumerate(rows, 1):
    print(f"{i}. Market ID: {market_id}")
    print(f"   Title: {title}")
    print(f"   ID starts with: {market_id[:20]}...")
    print(f"   ID length: {len(market_id)}")
    print()

# Check trades to see what market_id format is used there
print("="*70)
print("SAMPLE MARKET IDs FROM TRADES")
print("="*70 + "\n")

cursor.execute('SELECT DISTINCT market_id FROM trades LIMIT 5')
rows = cursor.fetchall()

for i, (market_id,) in enumerate(rows, 1):
    print(f"{i}. Trade market_id: {market_id}")
    print(f"   ID starts with: {market_id[:20]}...")
    print(f"   ID length: {len(market_id)}")
    print()

conn.close()

print("\nCONCLUSION:")
print("If IDs start with '0x', they are conditionIds")
print("These may NOT work with /markets/{id} API endpoint")
print("We need to use a different ID field (like 'id' or 'slug')")
