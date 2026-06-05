#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()

print("MARKETS TABLE SCHEMA:")
cursor.execute("PRAGMA table_info(markets);")
for row in cursor.fetchall():
    print(f"  {row[1]} ({row[2]})")

conn.close()
