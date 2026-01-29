"""
Comprehensive diagnostic for activity tracking issue.
"""
import sqlite3
import os
from datetime import datetime

print("="*70)
print("  ACTIVITY TRACKING DIAGNOSTIC")
print("="*70)

# Check 1: Database file exists
db_path = 'data/polymarket_tracker.db'
print(f"\n[1] Database file check:")
print(f"    Path: {db_path}")
if os.path.exists(db_path):
    size = os.path.getsize(db_path) / (1024**2)
    print(f"    [OK] EXISTS ({size:.1f} MB)")
else:
    print(f"    [ERROR] NOT FOUND")
    exit(1)

# Check 2: monitoring_status table exists
print(f"\n[2] monitoring_status table:")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='monitoring_status'")
    if cursor.fetchone():
        print(f"    [OK] Table exists")
    else:
        print(f"    [ERROR] Table NOT FOUND")
        exit(1)
except Exception as e:
    print(f"    [ERROR] Error: {e}")
    exit(1)

# Check 3: Read current status
print(f"\n[3] Current monitoring status:")
try:
    cursor.execute("SELECT * FROM monitoring_status WHERE id = 1")
    result = cursor.fetchone()

    if result:
        last_activity_str = result[1]
        last_cycle_count = result[2]
        process_id = result[3]

        print(f"    Last activity: {last_activity_str}")
        print(f"    Last cycle count: {last_cycle_count}")
        print(f"    Process ID: {process_id}")

        # Calculate time difference
        last_activity = datetime.fromisoformat(last_activity_str)
        now = datetime.now()
        diff_seconds = (now - last_activity).total_seconds()
        diff_minutes = diff_seconds / 60

        print(f"    Current time: {now}")
        print(f"    Time difference: {diff_minutes:.1f} minutes")

        if diff_minutes > 30:
            print(f"    [ERROR] STALE (>30 minutes)")
        elif diff_minutes > 15:
            print(f"    [WARNING] OLD (>15 minutes)")
        else:
            print(f"    [OK] RECENT (<15 minutes)")
    else:
        print(f"    [ERROR] No record found (id=1)")

except Exception as e:
    print(f"    [ERROR] Error: {e}")

# Check 4: Check if process is running
print(f"\n[4] Process check:")
import psutil

if result:
    try:
        process = psutil.Process(process_id)
        print(f"    Process {process_id}: [OK] RUNNING")
        print(f"    Name: {process.name()}")
        cmdline = process.cmdline()
        if len(cmdline) > 3:
            print(f"    Command: {' '.join(cmdline[:3])}...")
        else:
            print(f"    Command: {' '.join(cmdline)}")
    except psutil.NoSuchProcess:
        print(f"    Process {process_id}: [ERROR] NOT RUNNING")

# Check 5: Test System Observer's reading method
print(f"\n[5] Simulate System Observer read:")
try:
    # This mimics what System Observer does
    cursor.execute("""
        SELECT last_activity, process_id
        FROM monitoring_status
        WHERE id = 1
    """)

    row = cursor.fetchone()

    if row and row[0]:
        print(f"    Raw data from SELECT: {row}")

        # Parse exactly as System Observer does
        last_activity = datetime.fromisoformat(row[0].replace(' ', 'T'))
        process_id = row[1]
        minutes_since = (datetime.now() - last_activity).total_seconds() / 60

        print(f"    Parsed last_activity: {last_activity}")
        print(f"    Parsed process_id: {process_id}")
        print(f"    Calculated minutes_since: {minutes_since:.1f}")

        if minutes_since > 30:
            print(f"    [ERROR] System Observer would report: STALE")
        elif minutes_since > 15:
            print(f"    [WARNING] System Observer would report: OLD")
        else:
            print(f"    [OK] System Observer would report: HEALTHY")
    else:
        print(f"    [ERROR] No data returned")

except Exception as e:
    print(f"    [ERROR] Error: {e}")
    import traceback
    traceback.print_exc()

# Check 6: Manually update to test write access
print(f"\n[6] Test manual update:")
try:
    test_time = datetime.now().isoformat()
    cursor.execute("""
        UPDATE monitoring_status
        SET last_activity = ?
        WHERE id = 1
    """, (test_time,))
    conn.commit()

    print(f"    Updated to: {test_time}")
    print(f"    Rows affected: {cursor.rowcount}")

    if cursor.rowcount > 0:
        print(f"    [OK] Update successful")
    else:
        print(f"    [ERROR] Update failed (0 rows)")

except Exception as e:
    print(f"    [ERROR] Error: {e}")

# Check 7: Verify update worked
print(f"\n[7] Verify update:")
try:
    cursor.execute("SELECT last_activity FROM monitoring_status WHERE id = 1")
    new_time = cursor.fetchone()[0]
    print(f"    Database now shows: {new_time}")

    if new_time == test_time:
        print(f"    [OK] Update verified")
    else:
        print(f"    [WARNING] Update did not persist exactly")
        print(f"    Expected: {test_time}")
        print(f"    Got: {new_time}")
except Exception as e:
    print(f"    [ERROR] Error: {e}")

# Check 8: Check table schema
print(f"\n[8] Table schema check:")
try:
    cursor.execute("PRAGMA table_info(monitoring_status)")
    schema = cursor.fetchall()
    print(f"    Columns:")
    for col in schema:
        print(f"      - {col[1]} ({col[2]})")
except Exception as e:
    print(f"    [ERROR] Error: {e}")

conn.close()

print("\n" + "="*70)
print("  DIAGNOSTIC COMPLETE")
print("="*70)
