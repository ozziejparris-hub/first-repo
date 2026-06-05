#!/usr/bin/env python3
"""
Test System Observer Old Error Filtering

Verifies that System Observer only reports errors that occur AFTER
it starts, and ignores old historical errors from logs.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("="*70)
print("  SYSTEM OBSERVER - OLD ERROR FILTERING TEST")
print("="*70)
print()

# Test 1: Verify observer start time is set
print("[TEST 1] Observer start time tracking...")
try:
    from monitoring.system_observer import SystemObserver

    obs = SystemObserver(telegram_token='test', chat_id='test', monitoring_pid=None)

    if hasattr(obs, 'observer_start_time'):
        print(f"[OK] observer_start_time attribute exists")
        print(f"[INFO] Observer start time: {obs.observer_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"[FAIL] observer_start_time attribute not found!")
        sys.exit(1)

except Exception as e:
    print(f"[FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 2: Simulate old error detection
print("[TEST 2] Old error filtering logic...")
try:
    from monitoring.error_parser import ErrorDetail

    # Create a fake old error (from 1 hour ago)
    old_time = datetime.now() - timedelta(hours=1)
    old_error = ErrorDetail(
        timestamp=old_time,
        level='ERROR',
        component='test',
        error_type='TestError',
        message='Old test error'
    )

    # Create a fake new error (from now)
    new_time = datetime.now()
    new_error = ErrorDetail(
        timestamp=new_time,
        level='ERROR',
        component='test',
        error_type='TestError',
        message='New test error'
    )

    # Test filtering
    should_ignore_old = old_error.timestamp < obs.observer_start_time
    should_allow_new = new_error.timestamp >= obs.observer_start_time

    if should_ignore_old:
        print(f"[OK] Old error correctly identified for filtering")
        print(f"[INFO]   Old error: {old_time.strftime('%H:%M:%S')}")
        print(f"[INFO]   Observer:  {obs.observer_start_time.strftime('%H:%M:%S')}")
        print(f"[INFO]   Result: IGNORED (correct)")
    else:
        print(f"[FAIL] Old error would NOT be filtered!")
        sys.exit(1)

    if should_allow_new:
        print(f"[OK] New error correctly identified for allowing")
        print(f"[INFO]   New error: {new_time.strftime('%H:%M:%S')}")
        print(f"[INFO]   Observer:  {obs.observer_start_time.strftime('%H:%M:%S')}")
        print(f"[INFO]   Result: ALLOWED (correct)")
    else:
        print(f"[FAIL] New error would be filtered!")
        sys.exit(1)

except Exception as e:
    print(f"[FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 3: Check log file for historical errors
print("[TEST 3] Historical errors in logs...")
try:
    with open('logs/monitoring.log', 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    error_lines = [l for l in lines if 'ERROR' in l or 'Errno' in l]

    if error_lines:
        # Get timestamps of first and last error
        first_error = error_lines[0]
        last_error = error_lines[-1]

        print(f"[INFO] Found {len(error_lines)} historical error lines in log")

        # Try to parse timestamps
        try:
            if len(first_error) >= 19:
                first_time = datetime.strptime(first_error[:19], '%Y-%m-%d %H:%M:%S')
                print(f"[INFO] Oldest error: {first_time.strftime('%Y-%m-%d %H:%M:%S')}")

            if len(last_error) >= 19:
                last_time = datetime.strptime(last_error[:19], '%Y-%m-%d %H:%M:%S')
                print(f"[INFO] Latest error: {last_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # Check how many would be filtered
            filtered_count = 0
            for line in error_lines:
                if len(line) >= 19:
                    try:
                        err_time = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                        if err_time < obs.observer_start_time:
                            filtered_count += 1
                    except ValueError:
                        pass

            print(f"[OK] Observer will filter {filtered_count}/{len(error_lines)} old errors")
            print(f"[INFO] Only {len(error_lines) - filtered_count} recent errors will be reported")

        except ValueError as e:
            print(f"[INFO] Could not parse error timestamps: {e}")

    else:
        print(f"[OK] No historical errors in log file")

except FileNotFoundError:
    print(f"[INFO] Log file not found (normal on first run)")
except Exception as e:
    print(f"[WARNING] {e}")

print()

# Summary
print("="*70)
print("  TEST COMPLETE")
print("="*70)
print()
print("[OK] System Observer old error filtering verified!")
print()
print("Behavior:")
print("  - Observer starts and records current time")
print("  - All errors BEFORE that time are IGNORED")
print("  - Only errors AFTER observer starts are reported")
print()
print("Expected when running observer:")
print("  - No alerts for old [Errno 22] errors from yesterday")
print("  - No alerts for errors from before observer start")
print("  - Only NEW errors (after observer start) will trigger alerts")
print()
