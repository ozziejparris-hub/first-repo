#!/usr/bin/env python3
"""Quick database schema inspector."""

import sqlite3
from pathlib import Path

db_path = Path('data/polymarket_tracker.db')

if not db_path.exists():
    print(f"❌ Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 70)
print("  DATABASE SCHEMA INSPECTION")
print("=" * 70)

# 1. Markets table columns
print("\n[1] MARKETS TABLE COLUMNS:")
print("-" * 70)
cursor.execute("PRAGMA table_info(markets)")
for row in cursor.fetchall():
    col_id, name, type_, notnull, default, pk = row
    print(f"  {col_id:2d}. {name:30s} {type_:15s} {'NOT NULL' if notnull else ''}")

# 2. Traders table columns  
print("\n[2] TRADERS TABLE COLUMNS:")
print("-" * 70)
cursor.execute("PRAGMA table_info(traders)")
for row in cursor.fetchall():
    col_id, name, type_, notnull, default, pk = row
    print(f"  {col_id:2d}. {name:30s} {type_:15s} {'NOT NULL' if notnull else ''}")

# 3. Sample market row
print("\n[3] SAMPLE MARKET ROW:")
print("-" * 70)
cursor.execute("SELECT * FROM markets LIMIT 1")
columns = [desc[0] for desc in cursor.description]
row = cursor.fetchone()
if row:
    for col, val in zip(columns, row):
        print(f"  {col:30s} = {val}")
else:
    print("  (no data)")

# 4. Resolved markets count
print("\n[4] RESOLVED MARKETS COUNT:")
print("-" * 70)
cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
resolved_count = cursor.fetchone()[0]
print(f"  Resolved markets: {resolved_count}")

cursor.execute("SELECT COUNT(*) FROM markets")
total_count = cursor.fetchone()[0]
print(f"  Total markets: {total_count}")
print(f"  Resolution rate: {resolved_count/total_count*100:.1f}%")

# 5. Check for problematic columns
print("\n[5] CHECKING FOR EXPECTED COLUMNS:")
print("-" * 70)

cursor.execute("PRAGMA table_info(markets)")
market_cols = {row[1] for row in cursor.fetchall()}

expected = ['created_at', 'end_date', 'resolved_at']
for col in expected:
    if col in market_cols:
        print(f"  ✓ {col:30s} EXISTS")
    else:
        print(f"  ✗ {col:30s} MISSING")
        # Try to find similar columns
        similar = [c for c in market_cols if 'creat' in c.lower() or 'date' in c.lower() or 'time' in c.lower()]
        if similar:
            print(f"    → Similar columns found: {', '.join(similar)}")

conn.close()

print("\n" + "=" * 70)
print("  SCHEMA INSPECTION COMPLETE")
print("=" * 70)