#!/usr/bin/env python
"""
Direct entry point for monitoring system with atomic file locking.

This script provides single-instance enforcement using OS-level file locking
instead of fragile PID file checks. It prevents duplicate monitoring processes
through atomic lock acquisition.

Usage:
    python scripts/start_monitoring.py

Benefits:
    - Single process execution (no python -m launcher stub)
    - Atomic file locking (no race conditions)
    - Clean shutdown handling
    - Clear error messages
"""
import os
import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Change to project root for consistent paths
os.chdir(project_root)

# Acquire singleton lock FIRST (before any imports)
pid_file_path = Path('data/.monitoring.pid')
pid_lock_file = None

try:
    # Ensure data directory exists
    pid_file_path.parent.mkdir(exist_ok=True)

    # Open PID file for writing
    pid_lock_file = open(pid_file_path, 'w')

    # Try to acquire exclusive lock (cross-platform)
    try:
        import fcntl
        fcntl.flock(pid_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        import msvcrt
        try:
            msvcrt.locking(pid_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("\n" + "="*70)
            print("  [ERROR] Monitoring already running")
            print("="*70)
            print("\nAnother monitoring instance is currently running.")
            print("\nTo stop it, use:")
            print("  python scripts/kill_all.py")
            print("\nOr check running processes:")
            print("  python scripts/check_processes.py")
            print("\n" + "="*70 + "\n")
            sys.exit(1)
    except IOError:
        print("\n" + "="*70)
        print("  [ERROR] Monitoring already running")
        print("="*70)
        print("\nAnother monitoring instance is currently running.")
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

# Now import and run monitoring (after lock acquired)
print("[STARTUP] Loading monitoring modules...")

import asyncio
from monitoring.main_telegram_safe import main

print("[STARTUP] Starting monitoring system...\n")

# Run monitoring
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n[SHUTDOWN] Received interrupt signal")
except Exception as e:
    print(f"\n[ERROR] Monitoring failed: {e}")
    import traceback
    traceback.print_exc()
finally:
    # Release lock and cleanup
    print("\n[CLEANUP] Releasing singleton lock...")

    if pid_lock_file:
        try:
            # Release the lock (cross-platform)
            try:
                import fcntl
                fcntl.flock(pid_lock_file, fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                try:
                    msvcrt.locking(pid_lock_file.fileno(), msvcrt.LK_UNLCK, 1)
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

    print("[SHUTDOWN] Complete\n")
