#!/usr/bin/env python3
"""
Verify Performance Baselines Pattern Fix

Quick verification that the lazy property pattern is correctly implemented.
This script just checks the code pattern - doesn't require dependencies.
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent

def check_performance_baselines():
    """Check that performance_baselines.py has the correct pattern."""

    print("=" * 70)
    print("PERFORMANCE BASELINES - PATTERN VERIFICATION")
    print("=" * 70)

    baselines_path = project_root / "monitoring" / "performance_baselines.py"

    if not baselines_path.exists():
        print(f"❌ File not found: {baselines_path}")
        return False

    content = baselines_path.read_text(encoding='utf-8')

    checks = []

    # Check 1: No self.conn in __init__
    print("\n[CHECK 1] No persistent self.conn in __init__")
    print("-" * 50)

    init_start = content.find("def __init__(")
    if init_start == -1:
        print("❌ __init__ method not found")
        checks.append(False)
    else:
        # Find the next method
        next_method = content.find("\n    def ", init_start + 1)
        init_section = content[init_start:next_method] if next_method != -1 else content[init_start:init_start+500]

        if "self.conn = sqlite3.connect" in init_section or "self._conn = sqlite3.connect" in init_section:
            print("❌ Found persistent connection in __init__")
            checks.append(False)
        else:
            print("✅ No persistent connection in __init__")
            checks.append(True)

    # Check 2: Has @property conn
    print("\n[CHECK 2] Has @property conn")
    print("-" * 50)

    if "@property" in content and "def conn(self):" in content:
        print("✅ @property conn found")
        checks.append(True)
    else:
        print("❌ @property conn not found")
        checks.append(False)

    # Check 3: Lazy connection creates with timeout and WAL
    print("\n[CHECK 3] Lazy connection uses timeout + WAL mode")
    print("-" * 50)

    property_start = content.find("@property")
    if property_start != -1:
        property_end = content.find("\n    def ", property_start + 50)
        property_section = content[property_start:property_end] if property_end != -1 else content[property_start:property_start+500]

        has_timeout = "timeout=" in property_section
        has_wal = "PRAGMA journal_mode=WAL" in property_section

        if has_timeout and has_wal:
            print("✅ Connection uses timeout and WAL mode")
            checks.append(True)
        else:
            if not has_timeout:
                print("❌ No timeout in connection")
            if not has_wal:
                print("❌ No WAL mode in connection")
            checks.append(False)
    else:
        print("❌ @property not found")
        checks.append(False)

    # Check 4: Has close() method
    print("\n[CHECK 4] Has close() method")
    print("-" * 50)

    if "def close(self):" in content:
        print("✅ close() method found")

        # Check it sets _conn to None
        close_start = content.find("def close(self):")
        close_end = content.find("\n    def ", close_start + 1)
        close_section = content[close_start:close_end] if close_end != -1 else content[close_start:close_start+300]

        if "self._conn = None" in close_section:
            print("✅ close() sets _conn to None")
            checks.append(True)
        else:
            print("⚠️  close() doesn't explicitly set _conn to None")
            checks.append(True)  # Still pass, just a warning
    else:
        print("❌ close() method not found")
        checks.append(False)

    # Check 5: Has __del__ for cleanup
    print("\n[CHECK 5] Has __del__() for automatic cleanup")
    print("-" * 50)

    if "def __del__(self):" in content:
        print("✅ __del__() method found")

        # Check it calls close()
        del_start = content.find("def __del__(self):")
        del_end = content.find("\n    def ", del_start + 1)
        if del_end == -1:
            del_end = len(content)
        del_section = content[del_start:del_end]

        if "self.close()" in del_section:
            print("✅ __del__() calls close()")
            checks.append(True)
        else:
            print("❌ __del__() doesn't call close()")
            checks.append(False)
    else:
        print("❌ __del__() method not found")
        checks.append(False)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(checks)
    total = len(checks)

    print(f"Checks passed: {passed}/{total}")

    if passed == total:
        print("\n✅ All pattern checks passed!")
        print("\nThe fix correctly implements:")
        print("  • No persistent connection in __init__")
        print("  • Lazy @property for connection")
        print("  • WAL mode + timeout on connections")
        print("  • Proper close() method")
        print("  • Automatic cleanup via __del__()")
        return True
    else:
        print(f"\n❌ {total - passed} check(s) failed")
        return False


if __name__ == "__main__":
    success = check_performance_baselines()
    sys.exit(0 if success else 1)
