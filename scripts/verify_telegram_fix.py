#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify Telegram Bot Conflict Fix

Quick verification script to check that the Telegram bot conflict fixes are in place.

Usage:
    python scripts/verify_telegram_fix.py
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def check_file_content(file_path: str, search_text: str, description: str) -> bool:
    """Check if file contains expected text."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if search_text in content:
                print(f"✅ {description}")
                return True
            else:
                print(f"❌ {description}")
                return False
    except Exception as e:
        print(f"❌ {description} - Error reading file: {e}")
        return False


def main():
    """Run verification checks."""
    print("="*70)
    print("  TELEGRAM BOT CONFLICT FIX - VERIFICATION")
    print("="*70)
    print()

    all_passed = True

    # Check 1: telegram_elo_bot.py has send_only parameter
    print("1. Checking telegram_elo_bot.py for send-only mode support...")
    all_passed &= check_file_content(
        "monitoring/telegram_elo_bot.py",
        "async def initialize(self, send_only: bool = False):",
        "   Send-only parameter exists in initialize()"
    )
    all_passed &= check_file_content(
        "monitoring/telegram_elo_bot.py",
        "if send_only:",
        "   Send-only mode implementation exists"
    )
    all_passed &= check_file_content(
        "monitoring/telegram_elo_bot.py",
        "self.bot = Bot(token=self.token)",
        "   Simple Bot creation for send-only mode"
    )
    print()

    # Check 2: monitor.py initializes bot in send-only mode
    print("2. Checking monitor.py for send-only initialization...")
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "await self.elo_bot.initialize(send_only=True)",
        "   ELO bot initialized in send-only mode"
    )
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "# NOTE: Scheduler disabled - user ditching Task Scheduler",
        "   Scheduler disabled comment exists"
    )
    print()

    # Check 3: Scheduler code is commented out
    print("3. Checking monitor.py for disabled scheduler...")
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "# from .telegram_scheduler import TelegramScheduler",
        "   TelegramScheduler import commented out"
    )
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "# if self.elo_scheduler:",
        "   Scheduler start code commented out"
    )
    print()

    # Check 4: Error handling for missing APScheduler
    print("4. Checking monitor.py for APScheduler error handling...")
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "except ImportError as e:",
        "   ImportError exception handler exists"
    )
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "# APScheduler not installed - that's OK",
        "   APScheduler optional comment exists"
    )
    print()

    # Check 5: Cleanup handlers
    print("5. Checking cleanup handlers...")
    all_passed &= check_file_content(
        "monitoring/monitor.py",
        "await self.elo_bot.stop()",
        "   ELO bot cleanup call exists in monitor.py"
    )
    all_passed &= check_file_content(
        "monitoring/telegram_elo_bot.py",
        "async def stop(self):",
        "   Stop method exists in telegram_elo_bot.py"
    )
    print()

    # Summary
    print("="*70)
    if all_passed:
        print("✅ ALL CHECKS PASSED")
        print()
        print("The Telegram bot conflict fixes are in place.")
        print()
        print("Next steps:")
        print("  1. Kill all python processes: taskkill /F /IM python.exe")
        print("  2. Start monitoring once: python -m monitoring.main")
        print("  3. Verify no 'Conflict: terminated by other getUpdates request' errors")
        print()
        print("See TELEGRAM_FIX_TESTING.md for full testing guide")
        return 0
    else:
        print("❌ SOME CHECKS FAILED")
        print()
        print("The fixes may not be properly in place.")
        print("Please review the failed checks above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
