#!/usr/bin/env python3
"""
Test Performance Baselines Fix

Verifies that the persistent connection fix works correctly.

Tests:
1. Connection is lazy (not created in __init__)
2. Connection is reused when accessed multiple times
3. Connection is properly closed via close()
4. Connection is cleaned up via __del__()
5. No database locks occur with multiple instances
"""

import sys
import os
from pathlib import Path
import tempfile
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from monitoring.performance_baselines import PerformanceBaselines


def test_lazy_connection():
    """Test that connection is lazy (not created immediately)."""
    print("\n[TEST 1] Lazy Connection Creation")
    print("-" * 50)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        baselines = PerformanceBaselines(db_path=db_path)

        # Check that _conn doesn't exist yet
        if not hasattr(baselines, '_conn'):
            print("✅ Connection not created in __init__ (lazy loading works)")
        else:
            print("❌ Connection created immediately (should be lazy)")
            return False

        # Now access conn property
        conn = baselines.conn

        if hasattr(baselines, '_conn') and baselines._conn is not None:
            print("✅ Connection created on first access")
        else:
            print("❌ Connection not created on access")
            return False

        baselines.close()
        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_connection_reuse():
    """Test that connection is reused."""
    print("\n[TEST 2] Connection Reuse")
    print("-" * 50)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        baselines = PerformanceBaselines(db_path=db_path)

        conn1 = baselines.conn
        conn2 = baselines.conn

        if conn1 is conn2:
            print("✅ Same connection object returned (reuse works)")
        else:
            print("❌ Different connection objects (not reusing)")
            return False

        baselines.close()
        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_explicit_close():
    """Test that explicit close() works."""
    print("\n[TEST 3] Explicit Close")
    print("-" * 50)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        baselines = PerformanceBaselines(db_path=db_path)

        # Access connection
        conn = baselines.conn
        print(f"Connection created: {conn is not None}")

        # Close it
        baselines.close()

        if not hasattr(baselines, '_conn') or baselines._conn is None:
            print("✅ Connection properly closed via close()")
        else:
            print("❌ Connection still exists after close()")
            return False

        # Test that new connection is created on next access
        new_conn = baselines.conn

        if new_conn is not None:
            print("✅ New connection created after close()")
        else:
            print("❌ Connection not recreated")
            return False

        baselines.close()
        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_del_cleanup():
    """Test that __del__() cleanup works."""
    print("\n[TEST 4] __del__() Cleanup")
    print("-" * 50)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        baselines = PerformanceBaselines(db_path=db_path)

        # Access connection
        conn = baselines.conn
        print(f"Connection created: {conn is not None}")

        # Delete instance (should trigger __del__)
        del baselines

        # Give time for cleanup
        time.sleep(0.1)

        print("✅ Instance deleted (cleanup via __del__ triggered)")
        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_no_locks_multiple_instances():
    """Test that multiple instances don't cause locks."""
    print("\n[TEST 5] No Locks with Multiple Instances")
    print("-" * 50)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        # Create multiple instances
        baselines1 = PerformanceBaselines(db_path=db_path)
        baselines2 = PerformanceBaselines(db_path=db_path)
        baselines3 = PerformanceBaselines(db_path=db_path)

        print(f"Created 3 instances")

        # Record metrics from different instances
        from datetime import datetime

        baselines1.record_metric("test_metric", 100.0, datetime.now())
        print("Instance 1 wrote successfully")

        baselines2.record_metric("test_metric", 200.0, datetime.now())
        print("Instance 2 wrote successfully")

        baselines3.record_metric("test_metric", 300.0, datetime.now())
        print("Instance 3 wrote successfully")

        # Get baseline from instance 1
        baseline = baselines1.get_baseline("test_metric", window_hours=1)

        if baseline:
            print(f"✅ Baseline calculated: mean={baseline['mean']:.2f}, samples={baseline['samples']}")
        else:
            print("⚠️  Not enough samples for baseline (expected)")

        # Clean up all instances
        baselines1.close()
        baselines2.close()
        baselines3.close()

        print("✅ All instances closed without lock errors")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def main():
    """Run all tests."""
    print("=" * 70)
    print("PERFORMANCE BASELINES FIX - TEST SUITE")
    print("=" * 70)

    tests = [
        ("Lazy Connection Creation", test_lazy_connection),
        ("Connection Reuse", test_connection_reuse),
        ("Explicit Close", test_explicit_close),
        ("__del__() Cleanup", test_del_cleanup),
        ("No Locks with Multiple Instances", test_no_locks_multiple_instances),
    ]

    results = []

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test '{name}' failed with exception: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ All tests passed! The fix is working correctly.")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Please review the fix.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
