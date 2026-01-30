#!/usr/bin/env python3
"""
Run System Health Observer

Entry point for starting the system health observer with atomic file locking.

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

# CRITICAL: Acquire singleton lock BEFORE any imports
# This prevents duplicate System Observer processes using OS-level file locking
import sys
import os
from pathlib import Path

# Add project root to path early
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Change to project root for consistent paths
os.chdir(project_root)

# Acquire singleton lock
pid_file_path = Path('data/.system_observer.pid')
pid_lock_file = None

try:
    # Ensure data directory exists
    pid_file_path.parent.mkdir(exist_ok=True)

    # Open PID file for writing
    pid_lock_file = open(pid_file_path, 'w')

    # Try to acquire exclusive lock
    if os.name == 'nt':
        # Windows
        import msvcrt
        try:
            # LK_NBLCK = non-blocking exclusive lock
            msvcrt.locking(pid_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("\n" + "="*70)
            print("  [ERROR] System Observer already running")
            print("="*70)
            print("\nAnother System Observer instance is currently running.")
            print("\nTo stop it, use:")
            print("  python scripts/kill_all.py")
            print("\nOr check running processes:")
            print("  python scripts/check_processes.py")
            print("\n" + "="*70 + "\n")
            sys.exit(1)
    else:
        # Unix-like systems
        import fcntl
        try:
            fcntl.flock(pid_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            print("\n" + "="*70)
            print("  [ERROR] System Observer already running")
            print("="*70)
            print("\nAnother System Observer instance is currently running.")
            print("\nTo stop it, use:")
            print("  python scripts/kill_all.py")
            print("\n" + "="*70 + "\n")
            sys.exit(1)

    # Write our PID to the locked file
    pid_lock_file.write(str(os.getpid()))
    pid_lock_file.flush()

    print(f"\n[OK] Acquired singleton lock (PID: {os.getpid()})")
    print(f"[OK] PID file: {pid_file_path}\n")

except Exception as e:
    print(f"\n[ERROR] Could not acquire lock: {e}\n")
    if pid_lock_file:
        pid_lock_file.close()
    sys.exit(1)

# Now continue with normal imports after lock acquired
import asyncio
import argparse

from monitoring.system_observer import SystemObserver, find_monitoring_process
from dotenv import load_dotenv


async def main():
    """
    Main entry point for system observer.
    """
    # Access module-level variables for cleanup
    global pid_lock_file, pid_file_path

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

        # Use find_monitoring_process() which handles PID file reading with proper error handling
        monitoring_pid = find_monitoring_process()

        # If still no PID found, warn user
        if not monitoring_pid:
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
        raise
    finally:
        # Release lock and cleanup
        print("\n[CLEANUP] Releasing singleton lock...")

        if pid_lock_file:
            try:
                # Release the lock
                if os.name == 'nt':
                    import msvcrt
                    try:
                        # LK_UNLCK = unlock
                        msvcrt.locking(pid_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    except:
                        pass  # Lock may already be released
                else:
                    import fcntl
                    try:
                        fcntl.flock(pid_lock_file, fcntl.LOCK_UN)
                    except:
                        pass

                # Close file
                pid_lock_file.close()

                # Remove PID file
                if pid_file_path.exists():
                    pid_file_path.unlink()
                    print(f"[CLEANUP] Removed PID file: {pid_file_path}")
            except Exception as e:
                print(f"[WARNING] Cleanup error: {e}")


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 7):
        print("ERROR: Python 3.7+ required")
        sys.exit(1)

    # Run async main
    try:
        asyncio.run(main())
    except Exception:
        sys.exit(1)
