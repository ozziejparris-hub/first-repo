"""
Check for running monitoring and system_observer processes.
"""
import psutil
import os
from pathlib import Path


def check_processes():
    """Check for monitoring and observer processes."""

    print("="*70)
    print("  PROCESS CHECK")
    print("="*70)

    # Check PID files
    monitoring_pid_file = Path('data/.monitoring.pid')
    observer_pid_file = Path('data/.system_observer.pid')

    print("\n[PID FILES]")

    # Monitoring PID
    if monitoring_pid_file.exists():
        try:
            pid = int(monitoring_pid_file.read_text().strip())

            if psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    print(f"  Monitoring: PID {pid} [OK] RUNNING")
                    print(f"    Memory: {proc.memory_info().rss / 1024**2:.1f} MB")
                    print(f"    CPU: {proc.cpu_percent(interval=0.1):.1f}%")
                except psutil.NoSuchProcess:
                    print(f"  Monitoring: PID {pid} [ERROR] NOT RUNNING (stale PID file)")
            else:
                print(f"  Monitoring: PID {pid} [ERROR] NOT RUNNING (stale PID file)")
        except Exception as e:
            print(f"  Monitoring: [ERROR] Corrupt PID file: {e}")
    else:
        print(f"  Monitoring: No PID file (not running)")

    # Observer PID
    if observer_pid_file.exists():
        try:
            pid = int(observer_pid_file.read_text().strip())

            if psutil.pid_exists(pid):
                try:
                    proc = psutil.Process(pid)
                    print(f"  Observer: PID {pid} [OK] RUNNING")
                    print(f"    Memory: {proc.memory_info().rss / 1024**2:.1f} MB")
                    print(f"    CPU: {proc.cpu_percent(interval=0.1):.1f}%")
                except psutil.NoSuchProcess:
                    print(f"  Observer: PID {pid} [ERROR] NOT RUNNING (stale PID file)")
            else:
                print(f"  Observer: PID {pid} [ERROR] NOT RUNNING (stale PID file)")
        except Exception as e:
            print(f"  Observer: [ERROR] Corrupt PID file: {e}")
    else:
        print(f"  Observer: No PID file (not running)")

    # Check all Python processes
    print("\n[ALL PYTHON PROCESSES]")

    found_any = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''

                if 'monitoring' in cmdline.lower() or 'system_observer' in cmdline.lower():
                    mem_mb = proc.memory_info().rss / 1024**2
                    print(f"  PID {proc.pid}: {mem_mb:.1f} MB")
                    print(f"    {cmdline[:100]}{'...' if len(cmdline) > 100 else ''}")
                    found_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not found_any:
        print("  No monitoring or observer processes found")

    # Summary
    print("\n[SUMMARY]")

    monitoring_running = monitoring_pid_file.exists() and psutil.pid_exists(
        int(monitoring_pid_file.read_text().strip())
    ) if monitoring_pid_file.exists() else False

    observer_running = observer_pid_file.exists() and psutil.pid_exists(
        int(observer_pid_file.read_text().strip())
    ) if observer_pid_file.exists() else False

    if monitoring_running and observer_running:
        print("  Status: [OK] Both monitoring and observer running")
    elif monitoring_running:
        print("  Status: [WARNING] Only monitoring running")
    elif observer_running:
        print("  Status: [WARNING] Only observer running")
    else:
        print("  Status: [ERROR] Neither monitoring nor observer running")

    print("\n" + "="*70)


if __name__ == "__main__":
    check_processes()
