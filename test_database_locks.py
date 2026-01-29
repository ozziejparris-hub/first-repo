"""
Test for database locking issues with multiple processes.
"""
import sqlite3
from datetime import datetime
import time

print("Testing database write with potential locks...\n")

db_path = 'data/polymarket_tracker.db'

# Try to update 5 times and see if any fail
for i in range(5):
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()

        test_time = datetime.now().isoformat()

        cursor.execute("""
            UPDATE monitoring_status
            SET last_activity = ?
            WHERE id = 1
        """, (test_time,))

        conn.commit()

        # Verify it worked
        cursor.execute("SELECT last_activity FROM monitoring_status WHERE id = 1")
        result = cursor.fetchone()[0]

        conn.close()

        if result == test_time:
            print(f"  Attempt {i+1}: [OK] Updated successfully to {test_time[:19]}")
        else:
            print(f"  Attempt {i+1}: [WARNING] Update didn't persist")

        time.sleep(1)

    except sqlite3.OperationalError as e:
        print(f"  Attempt {i+1}: [ERROR] Database locked: {e}")
    except Exception as e:
        print(f"  Attempt {i+1}: [ERROR] {e}")

print("\nTest complete.")
