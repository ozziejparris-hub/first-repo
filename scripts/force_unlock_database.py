#!/usr/bin/env python3
"""
Emergency Database Unlock Tool

Forces database unlock by removing lock files and checkpointing WAL.

⚠️ WARNING: Only use this if monitoring is STOPPED!
"""

import os
import sqlite3
import time
import sys

DB_PATH = 'data/polymarket_tracker.db'

print("🚨 EMERGENCY DATABASE UNLOCK")
print("="*70)
print()
print("⚠️ WARNING: This will forcefully unlock the database!")
print("⚠️ Make sure ALL monitoring/observer processes are stopped!")
print()

# Confirm
response = input("Are all processes stopped? (yes/no): ")
if response.lower() != 'yes':
    print("Aborted. Stop all processes first.")
    sys.exit(1)

# Step 1: Backup database
print("\n[1] Creating backup...")
backup_path = f"{DB_PATH}.backup_{int(time.time())}"
try:
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print(f"   ✓ Backup created: {backup_path}")
except Exception as e:
    print(f"   ⚠️ Backup failed: {e}")
    response = input("Continue anyway? (yes/no): ")
    if response.lower() != 'yes':
        sys.exit(1)

# Step 2: Remove lock files
print("\n[2] Removing lock files...")
lock_files = [
    DB_PATH + '-shm',
    DB_PATH + '-wal',
    DB_PATH + '-journal'
]

for lock_file in lock_files:
    if os.path.exists(lock_file):
        try:
            # Get size before removing
            size = os.path.getsize(lock_file)
            os.remove(lock_file)
            print(f"   ✓ Removed: {os.path.basename(lock_file)} ({size} bytes)")
        except Exception as e:
            print(f"   ✗ Could not remove {os.path.basename(lock_file)}: {e}")
    else:
        print(f"   - Not found: {os.path.basename(lock_file)}")

# Step 3: Force checkpoint and re-enable WAL
print("\n[3] Re-initializing WAL mode...")
try:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)

    # Force checkpoint
    print("   Checkpointing WAL...")
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    # Re-enable WAL mode
    print("   Enabling WAL mode...")
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL')
    mode = cursor.fetchone()[0]
    print(f"   Journal mode: {mode}")

    # Set busy timeout
    conn.execute('PRAGMA busy_timeout=30000')

    conn.close()
    print("   ✓ WAL mode re-initialized")

except Exception as e:
    print(f"   ✗ Re-initialization failed: {e}")
    sys.exit(1)

# Step 4: Verify database integrity
print("\n[4] Verifying database integrity...")
try:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cursor = conn.cursor()

    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()[0]

    if result == 'ok':
        print("   ✓ Database integrity: OK")
    else:
        print(f"   ✗ Database integrity check failed: {result}")

    # Quick count
    cursor.execute("SELECT COUNT(*) FROM trades")
    count = cursor.fetchone()[0]
    print(f"   ✓ Database accessible ({count} trades)")

    conn.close()

except Exception as e:
    print(f"   ✗ Verification failed: {e}")
    sys.exit(1)

# Step 5: Test write
print("\n[5] Testing write operations...")
try:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute('PRAGMA journal_mode=WAL')
    cursor = conn.cursor()

    # Try a write
    test_time = time.time()
    cursor.execute("CREATE TABLE IF NOT EXISTS unlock_test (id INTEGER, timestamp REAL)")
    cursor.execute("INSERT INTO unlock_test VALUES (?, ?)", (1, test_time))
    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM unlock_test WHERE timestamp=?", (test_time,))
    count = cursor.fetchone()[0]

    # Cleanup
    cursor.execute("DELETE FROM unlock_test WHERE timestamp=?", (test_time,))
    cursor.execute("DROP TABLE IF EXISTS unlock_test")
    conn.commit()
    conn.close()

    if count == 1:
        print("   ✓ Write operations working")
    else:
        print("   ✗ Write verification failed")

except Exception as e:
    print(f"   ✗ Write test failed: {e}")

print("\n" + "="*70)
print("✅ DATABASE UNLOCKED")
print("="*70)
print()
print("You can now start monitoring:")
print("  python -m monitoring.main")
print()
print(f"Backup saved to: {backup_path}")
