#!/usr/bin/env python3
"""
Database Lock Diagnostic Tool

Identifies the source of database lock issues.
"""

import sqlite3
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB_PATH = 'data/polymarket_tracker.db'

print("="*70)
print("DATABASE LOCK DIAGNOSTIC")
print("="*70)

# Check 1: Database file exists and accessible
print("\n[1] Database File Check:")
if os.path.exists(DB_PATH):
    print(f"   ✓ Database exists: {DB_PATH}")
    size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"   Size: {size_mb:.2f} MB")
else:
    print(f"   ✗ Database NOT found: {DB_PATH}")
    sys.exit(1)

# Check 2: Journal mode
print("\n[2] Journal Mode Check:")
try:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    print(f"   Current mode: {mode}")
    if mode != 'wal':
        print(f"   ⚠️ WARNING: Not in WAL mode! Attempting to enable...")
        cursor.execute("PRAGMA journal_mode=WAL")
        new_mode = cursor.fetchone()[0]
        print(f"   New mode: {new_mode}")
    else:
        print("   ✓ WAL mode is enabled")
    conn.close()
except Exception as e:
    print(f"   ✗ Error: {e}")

# Check 3: Open file handles
print("\n[3] Open File Handles:")
try:
    import psutil
    found_handles = False
    for proc in psutil.process_iter(['pid', 'name', 'open_files']):
        try:
            if proc.info['open_files']:
                for file in proc.info['open_files']:
                    if 'polymarket_tracker' in file.path.lower():
                        print(f"   Process: {proc.info['name']} (PID: {proc.info['pid']})")
                        print(f"   File: {file.path}")
                        found_handles = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass
    if not found_handles:
        print("   No open handles found (or psutil not available)")
except ImportError:
    print("   ⚠️ psutil not installed - skipping handle check")
    print("   Install: pip install psutil")

# Check 4: Lock files
print("\n[4] Lock Files Check:")
lock_files = [
    (DB_PATH + '-shm', 'Shared memory'),
    (DB_PATH + '-wal', 'Write-ahead log'),
    (DB_PATH + '-journal', 'Rollback journal')
]
for lock_file, description in lock_files:
    if os.path.exists(lock_file):
        size = os.path.getsize(lock_file)
        size_kb = size / 1024
        print(f"   Found: {os.path.basename(lock_file)} - {description} ({size_kb:.2f} KB)")
    else:
        print(f"   Not found: {os.path.basename(lock_file)}")

# Check 5: Test concurrent connections
print("\n[5] Concurrent Connection Test:")
try:
    conns = []
    for i in range(3):
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=5000')
        conns.append(conn)
        print(f"   Connection {i+1}: ✓")

    # Try simultaneous reads
    for i, conn in enumerate(conns):
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM trades")
            count = cursor.fetchone()[0]
            print(f"   Read {i+1}: {count} trades")
        except Exception as e:
            print(f"   Read {i+1}: ✗ {e}")

    # Close all
    for conn in conns:
        conn.close()
    print("   ✓ Concurrent access working")

except Exception as e:
    print(f"   ✗ Concurrent test failed: {e}")

# Check 6: Database integrity
print("\n[6] Database Integrity Check:")
try:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()

    # Check integrity
    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()[0]
    if result == 'ok':
        print("   ✓ Database integrity: OK")
    else:
        print(f"   ✗ Database integrity: {result}")

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"   Tables found: {', '.join(tables)}")

    # Check row counts
    for table in ['traders', 'trades', 'markets']:
        if table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"   {table}: {count} rows")

    conn.close()

except Exception as e:
    print(f"   ✗ Error: {e}")

# Check 7: Write test
print("\n[7] Write Operation Test:")
try:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL')
    cursor = conn.cursor()

    # Try a write
    test_time = time.time()
    cursor.execute("CREATE TABLE IF NOT EXISTS lock_test (id INTEGER, timestamp REAL)")
    cursor.execute("INSERT INTO lock_test VALUES (?, ?)", (1, test_time))
    conn.commit()

    # Verify write
    cursor.execute("SELECT COUNT(*) FROM lock_test WHERE timestamp=?", (test_time,))
    count = cursor.fetchone()[0]

    # Cleanup
    cursor.execute("DELETE FROM lock_test WHERE timestamp=?", (test_time,))
    conn.commit()
    conn.close()

    if count == 1:
        print("   ✓ Write operations working")
    else:
        print("   ✗ Write verification failed")

except Exception as e:
    print(f"   ✗ Write test failed: {e}")

print("\n" + "="*70)
print("DIAGNOSTIC COMPLETE")
print("="*70)

# Recommendations
print("\nRECOMMENDATIONS:")
if mode != 'wal':
    print("❌ Enable WAL mode (should be automatic in new code)")
else:
    print("✅ WAL mode enabled")

print("\nIf 'database is locked' errors persist:")
print("1. Kill all Python processes: taskkill /F /IM python.exe")
print("2. Run: python scripts/force_unlock_database.py")
print("3. Restart monitoring")
