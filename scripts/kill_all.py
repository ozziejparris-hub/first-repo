"""
Kill all monitoring and system_observer processes.

This script will:
1. Find all Python processes running monitoring or system_observer
2. Terminate them gracefully
3. Clean up PID files
"""
import psutil
import os
from pathlib import Path
import sys


def kill_all():
    """Kill all monitoring and observer processes."""

    print("="*70)
    print("  KILL ALL MONITORING PROCESSES")
    print("="*70)
    print()

    print("Searching for monitoring and observer processes...")

    killed = []
    errors = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''

                if 'monitoring' in cmdline.lower() or 'system_observer' in cmdline.lower():
                    # Don't kill ourselves
                    if proc.pid == os.getpid():
                        continue

                    print(f"Killing PID {proc.pid}:")
                    print(f"  {cmdline[:80]}{'...' if len(cmdline) > 80 else ''}")

                    try:
                        proc.terminate()
                        killed.append(proc.pid)
                        print(f"  [OK] Terminated")
                    except psutil.AccessDenied:
                        print(f"  [ERROR] Access denied - try running as administrator")
                        errors.append(proc.pid)
                    except Exception as e:
                        print(f"  [ERROR] Failed: {e}")
                        errors.append(proc.pid)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    print()

    # Wait for processes to terminate
    if killed:
        print(f"Waiting for {len(killed)} processes to terminate...")
        import time
        time.sleep(2)

        # Check if they're really dead
        still_running = []
        for pid in killed:
            if psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    if proc.is_running():
                        still_running.append(pid)
                except psutil.NoSuchProcess:
                    pass

        if still_running:
            print(f"\n[WARNING] {len(still_running)} processes still running, forcing kill...")
            for pid in still_running:
                try:
                    proc = psutil.Process(pid)
                    proc.kill()
                    print(f"  [OK] Force killed PID {pid}")
                except Exception as e:
                    print(f"  [ERROR] Could not kill PID {pid}: {e}")

    # Clean up PID files
    print("\nCleaning up PID files...")

    for pid_file in [Path('data/.monitoring.pid'), Path('data/.system_observer.pid')]:
        if pid_file.exists():
            try:
                pid_file.unlink()
                print(f"  [OK] Removed {pid_file}")
            except Exception as e:
                print(f"  [ERROR] Could not remove {pid_file}: {e}")
        else:
            print(f"  No {pid_file.name} found")

    # Summary
    print()
    print("="*70)
    print("  SUMMARY")
    print("="*70)

    if killed:
        print(f"  Killed {len(killed)} processes: {killed}")
    else:
        print(f"  No processes were running")

    if errors:
        print(f"  [WARNING] {len(errors)} processes could not be killed: {errors}")
        print(f"  Try running as administrator")

    print("="*70)


if __name__ == "__main__":
    try:
        kill_all()
    except KeyboardInterrupt:
        print("\n\n[CANCELLED] Interrupted by user")
        sys.exit(1)
