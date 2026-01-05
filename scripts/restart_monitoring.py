#!/usr/bin/env python3
"""
Restart Monitoring System
Safely stops old monitoring process and restarts with fresh code.
"""

import os
import sys
import time
import subprocess
import psutil
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def find_monitoring_processes():
    """Find all running monitoring.main processes."""
    monitoring_pids = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and any('monitoring' in str(arg) for arg in cmdline):
                # Check if it's actually monitoring.main
                if any('monitoring.main' in str(arg) or 'monitoring\\main.py' in str(arg) for arg in cmdline):
                    create_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(proc.info['create_time']))
                    monitoring_pids.append({
                        'pid': proc.info['pid'],
                        'cmdline': ' '.join(cmdline) if cmdline else '',
                        'created': create_time
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return monitoring_pids


def stop_monitoring(pid):
    """Stop monitoring process by PID."""
    try:
        proc = psutil.Process(pid)
        print(f"  Terminating process {pid}...")
        proc.terminate()

        # Wait up to 10 seconds for graceful shutdown
        try:
            proc.wait(timeout=10)
            print(f"  ✅ Process {pid} stopped gracefully")
            return True
        except psutil.TimeoutExpired:
            print(f"  ⚠️  Process {pid} didn't stop, forcing...")
            proc.kill()
            proc.wait(timeout=5)
            print(f"  ✅ Process {pid} force stopped")
            return True

    except psutil.NoSuchProcess:
        print(f"  ℹ️  Process {pid} already stopped")
        return True
    except Exception as e:
        print(f"  ❌ Failed to stop process {pid}: {e}")
        return False


def clear_python_cache():
    """Clear Python bytecode cache."""
    print("\n🗑️  Clearing Python cache...")

    cache_cleared = 0
    for root, dirs, files in os.walk(project_root):
        # Remove __pycache__ directories
        if '__pycache__' in dirs:
            cache_dir = os.path.join(root, '__pycache__')
            try:
                import shutil
                shutil.rmtree(cache_dir)
                cache_cleared += 1
            except Exception as e:
                print(f"    Warning: Could not remove {cache_dir}: {e}")

        # Remove .pyc files
        for file in files:
            if file.endswith('.pyc'):
                try:
                    os.remove(os.path.join(root, file))
                    cache_cleared += 1
                except Exception as e:
                    print(f"    Warning: Could not remove {file}: {e}")

    print(f"  ✅ Cleared {cache_cleared} cache files/directories")


def start_monitoring():
    """Start monitoring system."""
    print("\n🚀 Starting monitoring system...")

    # Use Python module execution to ensure proper imports
    cmd = [sys.executable, '-m', 'monitoring.main']

    try:
        if sys.platform == 'win32':
            # Windows: Simple background start using CREATE_NO_WINDOW
            CREATE_NO_WINDOW = 0x08000000

            process = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
        else:
            # Unix: Use nohup
            process = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )

        print(f"  ✅ Monitoring started (PID: {process.pid})")

        # Wait a moment and verify it's still running
        time.sleep(3)

        try:
            # Check if process is still alive
            if process.poll() is None:  # None means still running
                print(f"  ✅ Monitoring is running successfully")
                return process.pid
            else:
                # Process died, get error output
                stdout, stderr = process.communicate()
                print(f"  ❌ Monitoring process died immediately after start")
                if stderr:
                    print(f"  Error output: {stderr.decode('utf-8', errors='replace')[:500]}")
                return None
        except Exception as e:
            print(f"  ⚠️  Could not verify process status: {e}")
            return process.pid  # Return anyway, might be running

    except Exception as e:
        print(f"  ❌ Failed to start monitoring: {e}")
        import traceback
        traceback.print_exc()
        return None


def verify_health():
    """Quick health check to verify fixes are applied."""
    print("\n🏥 Running health check...")

    try:
        from monitoring.health_checker import HealthChecker
        import asyncio

        checker = HealthChecker('data/polymarket_tracker.db')

        # Check position tracker
        result = asyncio.run(checker.check_position_tracker())
        status = result['status']

        if status == 'healthy':
            print(f"  ✅ Position tracker: {status}")
        else:
            print(f"  ⚠️  Position tracker: {status} - {result['message']}")

        # Check telegram
        result = asyncio.run(checker.check_telegram_bots())
        status = result['status']

        if status == 'healthy':
            print(f"  ✅ Telegram bots: {status}")
        else:
            print(f"  ⚠️  Telegram bots: {status} - {result['message']}")

        return True

    except Exception as e:
        print(f"  ❌ Health check failed: {e}")
        return False


def main():
    """Main restart procedure."""
    print("=" * 70)
    print("🔄 MONITORING SYSTEM RESTART")
    print("=" * 70)

    # Step 1: Find running monitoring processes
    print("\n🔍 Finding monitoring processes...")
    monitoring_pids = find_monitoring_processes()

    if monitoring_pids:
        print(f"  Found {len(monitoring_pids)} monitoring process(es):")
        for info in monitoring_pids:
            print(f"    PID {info['pid']}: Started {info['created']}")
    else:
        print("  ℹ️  No monitoring processes found")

    # Step 2: Stop old processes
    if monitoring_pids:
        print("\n🛑 Stopping old monitoring processes...")
        for info in monitoring_pids:
            stop_monitoring(info['pid'])

        # Wait for processes to fully stop
        time.sleep(2)

    # Step 3: Clear Python cache
    clear_python_cache()

    # Step 4: Verify health before starting
    if not verify_health():
        print("\n❌ Health check failed - fixes may not be applied correctly")
        print("   Please review the code changes before starting monitoring")
        return 1

    # Step 5: Start monitoring
    new_pid = start_monitoring()

    if new_pid:
        print("\n" + "=" * 70)
        print("✅ RESTART COMPLETE")
        print("=" * 70)
        print(f"\nMonitoring is now running with PID {new_pid}")
        print("The system should now report healthy status for all components.")
        print("\nTo check status, run:")
        print("  python scripts/check_elo_status.py")
        return 0
    else:
        print("\n" + "=" * 70)
        print("❌ RESTART FAILED")
        print("=" * 70)
        print("\nMonitoring failed to start. Check logs/monitoring.log for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
