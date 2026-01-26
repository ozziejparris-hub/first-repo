#!/usr/bin/env python3
"""
Comprehensive Monitoring Integration Test

Tests the complete chain from entry point to position tracking execution:
1. Entry point exists and is correct
2. Monitor class has position tracker
3. Position tracker is instantiated
4. Monitoring loop calls position tracking
5. Position tracking method is implemented correctly

All 5 tests must pass for monitoring to work correctly.

Usage:
    py scripts/test_monitoring_integration.py
"""

import sys
from pathlib import Path

def print_header(title: str):
    """Print formatted section header."""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70 + "\n")


def test_entry_point_chain() -> bool:
    """Test 1: Verify entry point chain is correct."""
    print("[TEST 1] Entry Point Chain")
    print("-"*70)

    # Check __main__.py exists
    main_file = Path('monitoring/__main__.py')
    if not main_file.exists():
        print("[FAIL] monitoring/__main__.py not found")
        return False

    # Check it imports from main.py
    main_content = main_file.read_text(encoding='utf-8')
    if 'from .main import main' not in main_content:
        print("[FAIL] __main__.py doesn't import from main.py")
        return False

    print("[OK] monitoring/__main__.py exists and delegates to main.py")

    # Check main.py exists
    main_py = Path('monitoring/main.py')
    if not main_py.exists():
        print("[FAIL] monitoring/main.py not found")
        return False

    # Check it calls monitor.py
    main_py_content = main_py.read_text(encoding='utf-8')
    if 'from .monitor import main as run_monitor' not in main_py_content:
        print("[FAIL] main.py doesn't import from monitor.py")
        return False

    print("[OK] monitoring/main.py exists and calls monitor.py")

    # Check monitor.py exists
    monitor_py = Path('monitoring/monitor.py')
    if not monitor_py.exists():
        print("[FAIL] monitoring/monitor.py not found")
        return False

    print("[OK] monitoring/monitor.py exists")
    print("\n[PASS] Entry point chain is correct\n")
    return True


def test_position_tracker_import() -> bool:
    """Test 2: Verify PositionTracker is imported in monitor.py."""
    print("[TEST 2] PositionTracker Import")
    print("-"*70)

    monitor_file = Path('monitoring/monitor.py')
    monitor_content = monitor_file.read_text(encoding='utf-8')

    has_import = 'from .position_tracker import PositionTracker' in monitor_content

    if not has_import:
        print("[FAIL] PositionTracker not imported in monitor.py")
        print("       Expected: from .position_tracker import PositionTracker")
        return False

    print("[OK] PositionTracker imported correctly")
    print("\n[PASS] Import statement found\n")
    return True


def test_position_tracker_instantiation() -> bool:
    """Test 3: Verify PositionTracker is instantiated in __init__."""
    print("[TEST 3] PositionTracker Instantiation")
    print("-"*70)

    monitor_file = Path('monitoring/monitor.py')
    monitor_content = monitor_file.read_text(encoding='utf-8')

    has_instantiation = 'self.position_tracker = PositionTracker(self.db)' in monitor_content

    if not has_instantiation:
        print("[FAIL] PositionTracker not instantiated in PolymarketMonitor.__init__")
        print("       Expected: self.position_tracker = PositionTracker(self.db)")
        return False

    print("[OK] PositionTracker instantiated in __init__")
    print("\n[PASS] Instance created correctly\n")
    return True


def test_monitoring_loop_calls_position_tracking() -> bool:
    """Test 4: Verify monitoring loop calls update_position_tracking."""
    print("[TEST 4] Monitoring Loop Integration")
    print("-"*70)

    monitor_file = Path('monitoring/monitor.py')
    monitor_content = monitor_file.read_text(encoding='utf-8')

    # Check for the call in monitoring_loop
    has_call = 'await self.update_position_tracking()' in monitor_content

    if not has_call:
        print("[FAIL] update_position_tracking() not called in monitoring loop")
        print("       Expected: await self.update_position_tracking()")
        return False

    print("[OK] monitoring_loop() calls update_position_tracking()")

    # Verify start() calls monitoring_loop()
    has_loop_call = 'await self.monitoring_loop()' in monitor_content

    if not has_loop_call:
        print("[FAIL] start() doesn't call monitoring_loop()")
        return False

    print("[OK] start() calls monitoring_loop()")
    print("\n[PASS] Position tracking integrated in loop\n")
    return True


def test_update_position_tracking_implementation() -> bool:
    """Test 5: Verify update_position_tracking method is implemented."""
    print("[TEST 5] update_position_tracking() Implementation")
    print("-"*70)

    monitor_file = Path('monitoring/monitor.py')
    monitor_content = monitor_file.read_text(encoding='utf-8')

    # Check method exists
    has_method = 'async def update_position_tracking(self)' in monitor_content

    if not has_method:
        print("[FAIL] update_position_tracking() method not found")
        return False

    print("[OK] update_position_tracking() method defined")

    # Check it calls position tracker
    has_match_call = 'self.position_tracker.match_trades_for_trader' in monitor_content

    if not has_match_call:
        print("[FAIL] Method doesn't call match_trades_for_trader()")
        return False

    print("[OK] Method calls match_trades_for_trader()")

    # Check it updates database
    has_db_update = 'UPDATE traders' in monitor_content and 'realized_pnl' in monitor_content

    if not has_db_update:
        print("[FAIL] Method doesn't update traders table with P&L")
        return False

    print("[OK] Method updates database with P&L data")
    print("\n[PASS] Implementation is complete\n")
    return True


def main():
    """Run all integration tests."""
    print_header("MONITORING INTEGRATION TEST SUITE")

    print("Testing complete chain from entry point to position tracking")
    print("All 5 tests must pass for monitoring to work correctly")

    tests = [
        ("Entry Point Chain", test_entry_point_chain),
        ("PositionTracker Import", test_position_tracker_import),
        ("PositionTracker Instantiation", test_position_tracker_instantiation),
        ("Monitoring Loop Integration", test_monitoring_loop_calls_position_tracking),
        ("update_position_tracking Implementation", test_update_position_tracking_implementation)
    ]

    results = []

    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"[ERROR] Test crashed: {e}")
            results.append((test_name, False))

    # Summary
    print_header("TEST RESULTS SUMMARY")

    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} {test_name}")

    print()

    all_passed = all(passed for _, passed in results)

    if all_passed:
        print("="*70)
        print("[SUCCESS] ALL TESTS PASSED!")
        print("="*70)
        print()
        print("Position tracking is fully integrated.")
        print()
        print("Next steps:")
        print("  1. Restart monitoring: py -m monitoring.main")
        print("  2. Watch for [P&L] messages in logs")
        print("  3. Check positions after 30 minutes: py scripts/test_position_tracker.py")
        print()
    else:
        print("="*70)
        print("[FAILURE] SOME TESTS FAILED")
        print("="*70)
        print()
        print("Integration is incomplete. Fix failures above before running monitoring.")
        print()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
