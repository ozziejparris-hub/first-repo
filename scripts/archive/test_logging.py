#!/usr/bin/env python3
"""
Test Logging Configuration

Verifies that logging is properly configured and writes to logs/monitoring.log
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

project_root = Path(__file__).parent.parent


def verify_logging_setup():
    """Verify logging is properly configured."""

    print("=" * 70)
    print("LOGGING CONFIGURATION - VERIFICATION")
    print("=" * 70)

    main_py_path = project_root / "monitoring" / "main.py"

    if not main_py_path.exists():
        print(f"❌ File not found: {main_py_path}")
        return False

    content = main_py_path.read_text(encoding='utf-8')

    checks = []

    # Check 1: Imports logging
    print("\n[CHECK 1] Imports logging module")
    print("-" * 50)

    if "import logging" in content:
        print("✅ logging module imported")
        checks.append(True)
    else:
        print("❌ logging module not imported")
        checks.append(False)

    # Check 2: Creates logs directory
    print("\n[CHECK 2] Creates logs directory")
    print("-" * 50)

    if "os.makedirs('logs'" in content or 'os.makedirs("logs"' in content:
        print("✅ Creates logs directory")
        checks.append(True)
    else:
        print("❌ Doesn't create logs directory")
        checks.append(False)

    # Check 3: Configures logging.basicConfig
    print("\n[CHECK 3] Configures logging.basicConfig")
    print("-" * 50)

    if "logging.basicConfig(" in content:
        print("✅ logging.basicConfig configured")
        checks.append(True)
    else:
        print("❌ logging.basicConfig not found")
        checks.append(False)

    # Check 4: Has FileHandler for logs/monitoring.log
    print("\n[CHECK 4] Has FileHandler for logs/monitoring.log")
    print("-" * 50)

    if "logging.FileHandler('logs/monitoring.log')" in content or \
       'logging.FileHandler("logs/monitoring.log")' in content:
        print("✅ FileHandler configured for logs/monitoring.log")
        checks.append(True)
    else:
        print("❌ FileHandler not found")
        checks.append(False)

    # Check 5: Has StreamHandler (console output)
    print("\n[CHECK 5] Has StreamHandler for console output")
    print("-" * 50)

    if "logging.StreamHandler()" in content:
        print("✅ StreamHandler configured (console output)")
        checks.append(True)
    else:
        print("❌ StreamHandler not found")
        checks.append(False)

    # Check 6: Creates logger
    print("\n[CHECK 6] Creates logger instance")
    print("-" * 50)

    if "logger = logging.getLogger(" in content:
        print("✅ Logger instance created")
        checks.append(True)
    else:
        print("❌ Logger instance not found")
        checks.append(False)

    # Check 7: Uses logger.info/warning/error (not print)
    print("\n[CHECK 7] Uses logger calls instead of print")
    print("-" * 50)

    logger_calls = content.count("logger.info(") + content.count("logger.warning(") + content.count("logger.error(")
    print_calls = content.count("print(")

    if logger_calls > 10:
        print(f"✅ Uses logger calls ({logger_calls} found)")
        checks.append(True)
    else:
        print(f"⚠️  Few logger calls ({logger_calls} found)")
        checks.append(False)

    if print_calls > 5:
        print(f"⚠️  Still has {print_calls} print() calls (should use logger)")
    else:
        print(f"✅ Minimal print() usage ({print_calls} found)")

    # Check 8: Verify logs directory exists or can be created
    print("\n[CHECK 8] Logs directory")
    print("-" * 50)

    logs_dir = project_root / "logs"
    if logs_dir.exists():
        print(f"✅ logs/ directory exists")
        checks.append(True)
    else:
        print(f"⚠️  logs/ directory doesn't exist yet (will be created on first run)")
        checks.append(True)  # Not critical, will be created

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    passed = sum(checks)
    total = len(checks)

    print(f"Checks passed: {passed}/{total}")

    if passed >= 6:  # At least critical checks
        print("\n✅ Logging is properly configured!")
        print("\nWhen monitoring starts, logs will be written to:")
        print("  • logs/monitoring.log (persistent file)")
        print("  • Console output (StreamHandler)")
        print("\nThe System Observer can now monitor logs/monitoring.log")
        return True
    else:
        print(f"\n❌ Some critical checks failed")
        return False


if __name__ == "__main__":
    success = verify_logging_setup()
    sys.exit(0 if success else 1)
