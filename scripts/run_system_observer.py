#!/usr/bin/env python3
"""
Run System Health Observer

Entry point for starting the system health observer.

Usage:
    python scripts/run_system_observer.py [--pid PID]

The observer will:
- Monitor monitoring system health
- Send Telegram alerts for issues
- Provide hourly status reports
- Detect errors in real-time

Requires:
- Telegram bot token in .env (telegram_alerts_token)
- Telegram chat ID in .env (telegram_chat_id)
"""

# CRITICAL: Single instance check BEFORE any imports
# This prevents duplicate System Observer processes
import sys
import os
from pathlib import Path

pid_file = Path('data/.system_observer.pid')

if pid_file.exists():
    try:
        old_pid = int(pid_file.read_text().strip())

        # Lightweight check using subprocess (before importing psutil)
        import subprocess

        # Windows check
        try:
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {old_pid}', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if str(old_pid) in result.stdout:
                print(f"\n[ERROR] System Observer already running (PID {old_pid})")
                print(f"[ERROR] Stop it first:")
                print(f"[ERROR]   python scripts/kill_all.py")
                print(f"[ERROR]   OR: taskkill /PID {old_pid} /F\n")
                sys.exit(1)
            else:
                # Stale PID file
                print(f"[CLEANUP] Removing stale System Observer PID file")
                pid_file.unlink()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # tasklist not available (Linux?) or timed out, skip for now
            pass

    except (ValueError, FileNotFoundError):
        pass  # Corrupt PID file

# Now continue with normal imports
import asyncio
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from monitoring.system_observer import SystemObserver, find_monitoring_process
from dotenv import load_dotenv


async def main():
    """
    Main entry point for system observer.
    """
    # Parse arguments
    parser = argparse.ArgumentParser(
        description='System Health Observer - Monitor monitoring system health'
    )
    parser.add_argument(
        '--pid',
        type=int,
        default=None,
        help='PID of monitoring process to watch (auto-detects if not provided)'
    )
    parser.add_argument(
        '--no-telegram',
        action='store_true',
        help='Disable Telegram notifications (for testing)'
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Get Telegram credentials
    telegram_token = os.getenv('telegram_alerts_token')
    telegram_chat_id = os.getenv('telegram_chat_id')

    if not args.no_telegram:
        if not telegram_token or not telegram_chat_id:
            print("ERROR: Telegram credentials not found in .env")
            print("Required:")
            print("  telegram_alerts_token=<your_bot_token>")
            print("  telegram_chat_id=<your_chat_id>")
            print()
            print("Or run with --no-telegram for testing without notifications")
            sys.exit(1)

    # Get monitoring PID
    monitoring_pid = args.pid

    if monitoring_pid is None:
        print("[OBSERVER] No PID provided, attempting auto-detection...")
        monitoring_pid = find_monitoring_process()

        if monitoring_pid:
            print(f"[OBSERVER] Found monitoring process: PID {monitoring_pid}")
        else:
            print("[OBSERVER] Warning: Could not find monitoring process")
            print("[OBSERVER] Health checks will be limited")
            print()

            response = input("Continue anyway? (y/n): ")
            if response.lower() != 'y':
                print("Exiting...")
                sys.exit(0)

    # Create and run observer
    print()
    print("="*70)
    print("  SYSTEM HEALTH OBSERVER")
    print("="*70)
    print()

    if args.no_telegram:
        print("[OBSERVER] Running in test mode (no Telegram notifications)")
        # Create dummy bot for testing
        telegram_token = "test_token"
        telegram_chat_id = "test_chat"

    observer = SystemObserver(
        telegram_token=telegram_token,
        chat_id=telegram_chat_id,
        monitoring_pid=monitoring_pid
    )

    try:
        await observer.run()
    except KeyboardInterrupt:
        print("\n[OBSERVER] Interrupted by user")
    except Exception as e:
        print(f"\n[OBSERVER] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 7):
        print("ERROR: Python 3.7+ required")
        sys.exit(1)

    # Run async main
    asyncio.run(main())
