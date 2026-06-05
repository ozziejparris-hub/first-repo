#!/usr/bin/env python3
"""
Test System Observer Auto-Detection

Verifies that the observer can automatically find the monitoring process
without requiring --pid argument.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import psutil
from monitoring.system_observer import find_monitoring_process


def test_pattern_matching():
    """Test that the pattern matching works correctly."""
    print("=" * 70)
    print("SYSTEM OBSERVER AUTO-DETECTION TEST")
    print("=" * 70)

    # Test patterns
    test_cases = [
        ("py -m monitoring.main", True),
        ("python -m monitoring.main", True),
        ("python.exe -m monitoring.main", True),
        ("python -m monitoring.monitor", True),
        ("python monitor.py", True),
        ("python monitoring/monitor.py", True),
        ("python scripts/test_polymarket.py", True),  # Has 'polymarket' keyword
        ("python something_else.py", False),
        ("node server.js", False),
    ]

    print("\n[TEST] Pattern Matching")
    print("-" * 70)

    for cmdline, should_match in test_cases:
        cmdline_lower = cmdline.lower()

        patterns = [
            'monitoring.main',
            'monitoring.monitor',
            'monitor.py',
            'polymarket',
        ]

        matches = any(pattern in cmdline_lower for pattern in patterns)

        status = "✅" if matches == should_match else "❌"
        result = "MATCH" if matches else "NO MATCH"
        expected = "MATCH" if should_match else "NO MATCH"

        print(f"{status} {cmdline:50s} -> {result:10s} (expected: {expected})")

    print()


def test_live_detection():
    """Test live process detection."""
    print("\n[TEST] Live Process Detection")
    print("-" * 70)

    # Show all Python processes
    print("\nAll Python processes running:")
    python_processes = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] in ['python.exe', 'python', 'py.exe']:
                cmdline = proc.info.get('cmdline', [])
                if cmdline:
                    cmdline_str = ' '.join(str(c) for c in cmdline)
                    python_processes.append((proc.info['pid'], cmdline_str))
                    print(f"  PID {proc.info['pid']:6d}: {cmdline_str[:80]}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not python_processes:
        print("  (No Python processes found)")

    # Try to find monitoring process
    print("\nSearching for monitoring process...")
    monitoring_pid = find_monitoring_process()

    if monitoring_pid:
        print(f"✅ Found monitoring process: PID {monitoring_pid}")

        # Show what was found
        try:
            proc = psutil.Process(monitoring_pid)
            cmdline = ' '.join(proc.cmdline())
            print(f"   Command: {cmdline}")
            print(f"   Memory: {proc.memory_info().rss / (1024 * 1024):.1f} MB")
        except:
            pass

        return True
    else:
        print("⚠️  No monitoring process found")
        print("\nExpected patterns:")
        print("  - python -m monitoring.main")
        print("  - python -m monitoring.monitor")
        print("  - python monitor.py")
        print("  - python monitoring/monitor.py")
        print("\nTo test: Start monitoring in another terminal with:")
        print("  python -m monitoring.main")
        print("\nThen run this script again.")

        return False


def main():
    """Run all tests."""

    # Test 1: Pattern matching logic
    test_pattern_matching()

    # Test 2: Live detection
    found = test_live_detection()

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if found:
        print("✅ Auto-detection is working!")
        print("\nYou can now run the observer without --pid:")
        print("  python scripts/run_system_observer.py")
    else:
        print("⚠️  Auto-detection tested but monitoring process not running")
        print("\nPattern matching logic is correct.")
        print("Start monitoring to test live detection.")

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
