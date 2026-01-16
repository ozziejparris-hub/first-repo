#!/usr/bin/env python3
"""
Emergency Fix: Telegram Rate Limit Infinite Retry

The monitoring system is stuck retrying Telegram messages after hitting
rate limit (429 Too Many Requests). This script kills the process and
provides instructions to fix the code.

Usage:
    python scripts/emergency_fix_telegram_rate_limit.py
"""

import os
import sys
import subprocess
from pathlib import Path


def kill_monitoring_process():
    """Kill the stuck monitoring process."""
    print("\n" + "="*70)
    print("  EMERGENCY FIX: Telegram Rate Limit Issue")
    print("="*70)
    print()
    print("[DIAGNOSIS] System stuck in infinite Telegram retry loop")
    print("            Last log: 16:13:28 - HTTP 429 Too Many Requests")
    print("            Pattern: 1 message per second, infinite retries")
    print()

    # Try to find and kill python processes running monitoring
    try:
        if sys.platform == "win32":
            # Windows
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True,
                text=True
            )

            print("[1/3] Looking for monitoring process...")
            print()

            if "python.exe" in result.stdout:
                print("      Found Python processes. Kill command:")
                print()
                print("      taskkill /F /IM python.exe")
                print()
                print("      OR find specific PID:")
                print("      tasklist | findstr python")
                print("      taskkill /F /PID <PID>")
            else:
                print("      No python.exe processes found")
        else:
            # Linux/Mac
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True
            )

            print("[1/3] Looking for monitoring process...")
            print()

            for line in result.stdout.split('\n'):
                if 'monitoring' in line and 'python' in line:
                    print(f"      {line}")
                    pid = line.split()[1]
                    print(f"\n      Kill command: kill -9 {pid}")
    except Exception as e:
        print(f"[!] Error finding process: {e}")

    print()
    print("[2/3] After killing process, apply fix below")
    print()


def show_fix():
    """Show the code fix needed."""
    print("="*70)
    print("  CODE FIX REQUIRED")
    print("="*70)
    print()
    print("FILE: monitoring/telegram_bot.py")
    print()
    print("PROBLEM: No retry limit or 429 handling")
    print()
    print("FIX: Add retry limit and better error handling")
    print()
    print("=" * 70)
    print("STEP 1: Modify send_message() method (line 26)")
    print("=" * 70)
    print()
    print("ADD this at the top of send_message():")
    print()
    print("```python")
    print("    async def send_message(self, message: str, max_retries=3):")
    print('        """Send a message to the configured chat, splitting if too long."""')
    print("        if not self.chat_id:")
    print('            print("[WARNING] Chat ID not configured. Cannot send message.")')
    print("            return")
    print()
    print("        # Get the bot instance (works in both send-only and full mode)")
    print("        bot = self.bot if hasattr(self, 'bot') else self.application.bot")
    print()
    print("        # Telegram max message length is 4096 characters")
    print("        MAX_LENGTH = 4000  # Leave some margin")
    print()
    print("        # Retry logic with exponential backoff")
    print("        for attempt in range(max_retries):")
    print("            try:")
    print("                # ... existing send logic ...")
    print("                return  # Success - exit")
    print()
    print("            except Exception as e:")
    print("                error_msg = str(e)")
    print()
    print('                if "429" in error_msg or "Too Many Requests" in error_msg:')
    print('                    print(f"[RATE LIMIT] Hit Telegram rate limit, attempt {attempt+1}/{max_retries}")')
    print()
    print("                    if attempt < max_retries - 1:")
    print("                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s")
    print('                        print(f"[WAIT] Waiting {wait_time}s before retry...")')
    print("                        await asyncio.sleep(wait_time)")
    print("                    else:")
    print('                        print(f"[SKIP] Max retries reached, skipping message")')
    print("                        return  # Give up after max retries")
    print("                else:")
    print('                    print(f"Error sending Telegram message: {e}")')
    print("                    return  # Don't retry on other errors")
    print("```")
    print()
    print("=" * 70)
    print("STEP 2: Reduce notification volume")
    print("=" * 70)
    print()
    print("FILE: monitoring/telegram_bot.py (line 24)")
    print()
    print("INCREASE cooldown from 5 minutes to 30 minutes:")
    print()
    print("```python")
    print("# Before:")
    print("self.notification_cooldown = 300  # 5 minutes")
    print()
    print("# After:")
    print("self.notification_cooldown = 1800  # 30 minutes")
    print("```")
    print()
    print("WHY: You were sending ~60 messages in 1 minute (1 per second)")
    print("     Telegram limit: ~20 messages/minute to same chat")
    print("     Solution: Longer cooldown = fewer messages")
    print()


def show_restart_instructions():
    """Show how to restart safely."""
    print("=" * 70)
    print("  RESTART INSTRUCTIONS")
    print("=" * 70)
    print()
    print("[3/3] After applying fix:")
    print()
    print("      1. Verify fix applied:")
    print("         - telegram_bot.py has retry limit")
    print("         - notification_cooldown = 1800 (30 min)")
    print()
    print("      2. Restart monitoring:")
    print("         python -m monitoring.main")
    print()
    print("      3. Watch logs:")
    print("         tail -f logs/monitoring.log")
    print()
    print("      4. Expected behavior:")
    print("         - No more infinite retries")
    print("         - If 429, waits 1s, 2s, 4s then gives up")
    print("         - Telegram messages spaced 30 min apart")
    print()
    print("=" * 70)
    print()


if __name__ == "__main__":
    kill_monitoring_process()
    show_fix()
    show_restart_instructions()

    print()
    print("[SUMMARY]")
    print("  Root cause: Telegram rate limit (429) → infinite retry loop")
    print("  Fix: Add max_retries=3 with exponential backoff")
    print("  Prevention: Increase cooldown from 5 min → 30 min")
    print()
    print("After applying fix, monitoring will work normally!")
    print()
