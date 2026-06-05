#!/usr/bin/env python3
"""
Test Component-Specific Health Checks

Tests all 5 component health check methods:
1. ELO System
2. Position Tracker
3. Market Filter
4. Database Operations
5. Telegram Bots
"""

import sys
import asyncio
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from monitoring.health_checker import HealthChecker


async def test_individual_checks():
    """Test each component check individually."""
    print("=" * 70)
    print("COMPONENT HEALTH CHECKS - INDIVIDUAL TESTS")
    print("=" * 70)

    checker = HealthChecker()

    # Test 1: ELO System
    print("\n[TEST 1] ELO System")
    print("-" * 70)
    try:
        result = await checker.check_elo_system()
        print(f"Status: {result['status']}")
        print(f"Available: {result['available']}")
        print(f"Test Passed: {result['test_passed']}")
        print(f"Message: {result['message']}")
        if result.get('details'):
            print(f"Details:")
            for key, value in result['details'].items():
                print(f"  - {key}: {value}")
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")

    # Test 2: Position Tracker
    print("\n[TEST 2] Position Tracker")
    print("-" * 70)
    try:
        result = await checker.check_position_tracker()
        print(f"Status: {result['status']}")
        print(f"Available: {result['available']}")
        print(f"Test Passed: {result['test_passed']}")
        print(f"Message: {result['message']}")
        if result.get('details'):
            print(f"Details:")
            for key, value in result['details'].items():
                print(f"  - {key}: {value}")
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")

    # Test 3: Market Filter
    print("\n[TEST 3] Market Filter")
    print("-" * 70)
    try:
        result = await checker.check_market_filter()
        print(f"Status: {result['status']}")
        print(f"Available: {result['available']}")
        print(f"Test Passed: {result['test_passed']}")
        print(f"Message: {result['message']}")
        if result.get('details'):
            print(f"Details:")
            for key, value in result['details'].items():
                print(f"  - {key}: {value}")
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")

    # Test 4: Database Operations
    print("\n[TEST 4] Database Operations")
    print("-" * 70)
    try:
        result = await checker.check_database_operations()
        print(f"Status: {result['status']}")
        print(f"Available: {result['available']}")
        print(f"Test Passed: {result['test_passed']}")
        print(f"Message: {result['message']}")
        if result.get('details'):
            print(f"Details:")
            for key, value in result['details'].items():
                if key not in ['read_time_ms', 'write_time_ms']:
                    print(f"  - {key}: {value}")
                else:
                    print(f"  - {key}: {value:.2f}")
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")

    # Test 5: Telegram Bots
    print("\n[TEST 5] Telegram Bots")
    print("-" * 70)
    try:
        result = await checker.check_telegram_bots()
        print(f"Status: {result['status']}")
        print(f"Available: {result['available']}")
        print(f"Test Passed: {result['test_passed']}")
        print(f"Message: {result['message']}")
        if result.get('details'):
            print(f"Details:")
            for key, value in result['details'].items():
                print(f"  - {key}: {value}")
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")


async def test_check_all():
    """Test the comprehensive check_all() method."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE HEALTH CHECK - check_all()")
    print("=" * 70)

    checker = HealthChecker()

    try:
        result = await checker.check_all()

        print(f"\nOverall Status: {result['status']}")
        print(f"Summary: {result['summary']}")
        print(f"Timestamp: {result['timestamp']}")

        # Show component results
        if 'components' in result['checks']:
            print("\nComponent Health:")
            for comp_name, comp_result in result['checks']['components'].items():
                status_emoji = {
                    'healthy': '✅',
                    'warning': '⚠️ ',
                    'critical': '❌'
                }.get(comp_result['status'], '?')

                print(f"  {status_emoji} {comp_name}: {comp_result['message']}")

        # Show issues
        if result['issues']:
            print(f"\nIssues Detected ({len(result['issues'])}):")
            for issue in result['issues']:
                print(f"  • {issue}")
        else:
            print("\n✅ No issues detected!")

        # Show basic checks
        print("\nBasic Health Checks:")
        for check_name, check_result in result['checks'].items():
            if check_name != 'components':
                status_emoji = {
                    'healthy': '✅',
                    'warning': '⚠️ ',
                    'critical': '❌'
                }.get(check_result['status'], '?')
                print(f"  {status_emoji} {check_name}: {check_result['message']}")

    except Exception as e:
        print(f"❌ check_all() failed with exception: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run all tests."""
    print("\n🏥 COMPONENT HEALTH CHECKS TEST SUITE")
    print("=" * 70)

    # Test individual checks
    await test_individual_checks()

    # Test comprehensive check
    await test_check_all()

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUITE COMPLETE")
    print("=" * 70)
    print("\n✅ All component health check methods have been tested")
    print("\nNext steps:")
    print("  1. Review results above for any failures")
    print("  2. Fix any failing components")
    print("  3. Integrate with System Observer")
    print("  4. Test with monitoring running")

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
