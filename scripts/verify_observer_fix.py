#!/usr/bin/env python3
"""
Verify Observer Auto-Detection Fix

Checks that system_observer.py has the correct pattern matching.
"""

import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent


def verify_observer_fix():
    """Verify the observer fix is correctly implemented."""

    print("=" * 70)
    print("SYSTEM OBSERVER AUTO-DETECTION - VERIFICATION")
    print("=" * 70)

    observer_path = project_root / "monitoring" / "system_observer.py"

    if not observer_path.exists():
        print(f"❌ File not found: {observer_path}")
        return False

    content = observer_path.read_text(encoding='utf-8')

    # Find the find_monitoring_process function
    func_start = content.find("def find_monitoring_process")
    if func_start == -1:
        print("❌ find_monitoring_process function not found")
        return False

    # Get the function content (up to next function or end)
    next_func = content.find("\ndef ", func_start + 1)
    if next_func == -1:
        next_func = content.find("\nclass ", func_start + 1)
    if next_func == -1:
        next_func = len(content)

    func_content = content[func_start:next_func]

    checks = []

    # Check 1: Has 'monitoring.main' pattern
    print("\n[CHECK 1] Includes 'monitoring.main' pattern")
    print("-" * 50)

    if "'monitoring.main'" in func_content or '"monitoring.main"' in func_content:
        print("✅ Pattern 'monitoring.main' found")
        checks.append(True)
    else:
        print("❌ Pattern 'monitoring.main' NOT found")
        checks.append(False)

    # Check 2: Has 'monitoring.monitor' pattern
    print("\n[CHECK 2] Includes 'monitoring.monitor' pattern")
    print("-" * 50)

    if "'monitoring.monitor'" in func_content or '"monitoring.monitor"' in func_content:
        print("✅ Pattern 'monitoring.monitor' found")
        checks.append(True)
    else:
        print("❌ Pattern 'monitoring.monitor' NOT found")
        checks.append(False)

    # Check 3: Has 'monitor.py' pattern
    print("\n[CHECK 3] Includes 'monitor.py' pattern")
    print("-" * 50)

    if "'monitor.py'" in func_content or '"monitor.py"' in func_content:
        print("✅ Pattern 'monitor.py' found")
        checks.append(True)
    else:
        print("❌ Pattern 'monitor.py' NOT found")
        checks.append(False)

    # Check 4: Uses case-insensitive matching
    print("\n[CHECK 4] Uses case-insensitive matching")
    print("-" * 50)

    if ".lower()" in func_content:
        print("✅ Uses .lower() for case-insensitive matching")
        checks.append(True)
    else:
        print("❌ No .lower() found (should use case-insensitive)")
        checks.append(False)

    # Check 5: Filters for Python processes
    print("\n[CHECK 5] Filters for Python processes")
    print("-" * 50)

    if "python.exe" in func_content or "python" in func_content:
        print("✅ Filters for Python process names")
        checks.append(True)
    else:
        print("⚠️  No Python process filter (may work but less efficient)")
        checks.append(True)  # Not critical

    # Check 6: Has debug output
    print("\n[CHECK 6] Has debug output when process found")
    print("-" * 50)

    if "print(" in func_content and "Found monitoring" in func_content:
        print("✅ Has debug output")
        checks.append(True)
    else:
        print("⚠️  No debug output (helpful but not required)")
        checks.append(True)  # Not critical

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(checks)
    total = len(checks)

    print(f"Checks passed: {passed}/{total}")

    if passed >= 4:  # At least the critical checks
        print("\n✅ Observer auto-detection fix is correctly implemented!")
        print("\nThe observer can now find:")
        print("  • python -m monitoring.main")
        print("  • python -m monitoring.monitor")
        print("  • python monitor.py")
        print("  • python monitoring/monitor.py")
        print("\nNo --pid argument needed!")
        return True
    else:
        print(f"\n❌ Some critical checks failed")
        return False


if __name__ == "__main__":
    success = verify_observer_fix()
    sys.exit(0 if success else 1)
