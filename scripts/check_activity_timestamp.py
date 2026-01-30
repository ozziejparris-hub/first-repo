#!/usr/bin/env python3
"""
Check Activity Timestamp Diagnostic Script

This script checks if the monitoring system is properly updating
the activity timestamp in the database.
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def main():
    print("=" * 70)
    print("  ACTIVITY TIMESTAMP DIAGNOSTIC")
    print("=" * 70)
    print()

    db_path = project_root / 'data' / 'polymarket_tracker.db'

    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='monitoring_status'
    """)

    if not cursor.fetchone():
        print("[ERROR] monitoring_status table does not exist!")
        print()
        print("This table should be created by PolymarketMonitor._update_activity_timestamp()")
        print()
        print("Possible causes:")
        print("  1. Monitoring has never run successfully")
        print("  2. _update_activity_timestamp() is not being called")
        print("  3. Table creation is failing silently")
        conn.close()
        return

    print("[OK] monitoring_status table exists")
    print()

    # Check table structure
    cursor.execute("PRAGMA table_info(monitoring_status)")
    columns = cursor.fetchall()

    print("Table structure:")
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    print()

    # Check for records
    cursor.execute("SELECT COUNT(*) FROM monitoring_status")
    count = cursor.fetchone()[0]

    if count == 0:
        print("[ERROR] No records in monitoring_status table!")
        print()
        print("This means _update_activity_timestamp() has NEVER been called successfully.")
        print()
        print("Check:")
        print("  1. Is monitoring actually running?")
        print("  2. Check monitoring logs for errors")
        print("  3. Look for '[WARNING] Failed to update activity timestamp' in output")
        conn.close()
        return

    print(f"[OK] Found {count} record(s) in monitoring_status")
    print()

    # Get the activity record
    cursor.execute("""
        SELECT id, last_activity, process_id, last_cycle_count
        FROM monitoring_status WHERE id = 1
    """)

    result = cursor.fetchone()

    if not result:
        print("[ERROR] No record with id=1 found")
        conn.close()
        return

    record_id, last_activity_str, process_id, last_cycle_count = result

    print("Activity Record:")
    print(f"  ID: {record_id}")
    print(f"  Last Activity: {last_activity_str}")
    print(f"  Process ID: {process_id}")
    print(f"  Last Cycle Count: {last_cycle_count}")
    print()

    # Parse timestamp
    if not last_activity_str:
        print("[ERROR] last_activity is NULL!")
        conn.close()
        return

    try:
        # Try ISO format first (Python datetime)
        last_activity = datetime.fromisoformat(last_activity_str)
    except:
        try:
            # Try SQLite format
            last_activity = datetime.strptime(last_activity_str, '%Y-%m-%d %H:%M:%S')
        except:
            print(f"[ERROR] Cannot parse timestamp format: {last_activity_str}")
            conn.close()
            return

    # Calculate time difference
    now = datetime.now()
    diff_seconds = (now - last_activity).total_seconds()
    diff_minutes = diff_seconds / 60
    diff_hours = diff_minutes / 60

    print("Time Since Last Activity:")
    print(f"  Seconds: {diff_seconds:.1f}s")
    print(f"  Minutes: {diff_minutes:.1f}m")
    print(f"  Hours: {diff_hours:.2f}h")
    print()

    # Status assessment
    if diff_minutes < 20:
        status = "HEALTHY"
        color = "OK"
    elif diff_minutes < 60:
        status = "WARNING"
        color = "WARN"
    else:
        status = "CRITICAL"
        color = "ERROR"

    print(f"[{color}] Status: {status}")
    print()

    if status == "HEALTHY":
        print("System is operating normally.")
        print(f"Next update expected within {15 - diff_minutes:.1f} minutes.")
    elif status == "WARNING":
        print("Monitoring may be delayed or stuck.")
        print("Check if monitoring process is running and processing trades.")
    else:
        print("CRITICAL: Monitoring has not updated in over an hour!")
        print()
        print("Actions:")
        print("  1. Check if monitoring process is running:")
        print("     python scripts/check_processes.py")
        print()
        print("  2. Check monitoring logs:")
        print("     tail logs/monitoring.log")
        print()
        print("  3. Restart monitoring:")
        print("     python scripts/kill_all.py")
        print("     python scripts/start_monitoring.py")

    print()

    # Check if process is actually running
    if process_id:
        try:
            import psutil
            if psutil.pid_exists(process_id):
                proc = psutil.Process(process_id)
                if proc.is_running():
                    print(f"[OK] Process {process_id} is running")
                    print(f"     Command: {' '.join(proc.cmdline()[:3])}")
                else:
                    print(f"[ERROR] Process {process_id} exists but not running")
            else:
                print(f"[ERROR] Process {process_id} does not exist (stale PID)")
                print("     The monitoring process crashed or was killed.")
        except ImportError:
            print("[INFO] psutil not available, cannot check process")
        except Exception as e:
            print(f"[ERROR] Error checking process: {e}")

    conn.close()

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
