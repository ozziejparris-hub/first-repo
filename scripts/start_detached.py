#!/usr/bin/env python
"""
Detached process launcher for Polymarket monitoring.

Starts two fully detached Windows processes so they survive VSCode restarts,
terminal closes, and PC reboots:

  1. start_monitoring.py   — trade poller + background P&L worker (one process)
  2. run_system_observer.py — health checks, Telegram alerts, hourly reports

The P&L worker runs as an asyncio task inside the monitoring process,
so there is no separate third script to launch.

Both processes use cwd=project_root and PYTHONIOENCODING=utf-8.

Usage:
    python scripts/start_detached.py          # start if not already running
    python scripts/start_detached.py --force  # kill existing, then start fresh
"""
import os
import sys
import subprocess
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

PYTHON = sys.executable          # same interpreter running this script
LOGS   = project_root / "logs"
LOGS.mkdir(exist_ok=True)

# Fully detached: no console window, not a child of calling process
DETACH_FLAGS = (
    subprocess.DETACHED_PROCESS    # own process group
    | subprocess.CREATE_NO_WINDOW  # no console window
    | subprocess.CREATE_NEW_PROCESS_GROUP
)


def _is_running(pid_file: Path) -> bool:
    """Return True if the PID file is locked (process alive)."""
    if not pid_file.exists():
        return False
    try:
        # Try to open for exclusive write — will fail if already locked
        import msvcrt
        f = open(pid_file, 'r+')
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            # Acquired the lock → process is dead, file was stale
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            f.close()
            return False
        except OSError:
            # Could not acquire → locked by running process
            f.close()
            return True
    except Exception:
        return False


def _launch(script: str, log_name: str, extra_args: list = None) -> int:
    """Launch script as a fully detached process. Returns PID."""
    log_path = LOGS / log_name
    log_file = open(log_path, 'a', encoding='utf-8')
    # Inherit environment but force UTF-8 stdout so non-ASCII market titles
    # don't crash the process when writing to the log file.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    cmd = [PYTHON, "-u", str(project_root / "scripts" / script)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.Popen(
        cmd,
        cwd=str(project_root),          # always run from project root
        stdout=log_file,
        stderr=log_file,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=DETACH_FLAGS,
        close_fds=True,
    )
    # Don't close log_file here — the child process owns the handle on Windows
    return proc.pid


def _read_monitor_pid() -> int | None:
    """Find the running monitor's PID via process search (PID file is locked)."""
    try:
        import psutil
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
            try:
                if 'python' not in p.info.get('name', '').lower():
                    continue
                cmd = ' '.join(p.info.get('cmdline') or [])
                if 'start_monitoring.py' not in cmd:
                    continue
                mem_mb = p.info['memory_info'].rss / 1024 / 1024
                if mem_mb < 10:
                    continue   # skip launcher stub
                return p.info['pid']
            except Exception:
                continue
    except Exception:
        pass
    return None


def main():
    force = "--force" in sys.argv

    mon_pid  = project_root / "data" / ".monitoring.pid"
    obs_pid  = project_root / "data" / ".system_observer.pid"

    mon_running = _is_running(mon_pid)
    obs_running = _is_running(obs_pid)

    if mon_running and obs_running and not force:
        print("[OK] Both processes already running - nothing to do.")
        print("     Run: python scripts/check_monitoring.py  to see status")
        return

    if force:
        print("[FORCE] Killing existing processes...")
        subprocess.run([PYTHON, str(project_root / "scripts" / "kill_all.py")],
                       cwd=str(project_root))
        time.sleep(2)
        mon_running = obs_running = False

    if not mon_running:
        pid = _launch("start_monitoring.py", "monitoring_detached.log")
        print(f"[OK] Monitoring started  (PID {pid})")
        # Give monitor time to acquire its lock and write PID before observer starts
        print("     Waiting 8s for monitor to initialise...")
        time.sleep(8)
    else:
        print("[--] Monitoring already running - skipping")

    if not obs_running:
        # Pass --pid so the observer skips auto-detect (avoids the input() prompt
        # that raises EOFError when stdin is DEVNULL in detached mode).
        mon_pid_val = _read_monitor_pid()
        obs_args = ["--pid", str(mon_pid_val)] if mon_pid_val else []
        if mon_pid_val:
            print(f"[OK] Passing --pid {mon_pid_val} to observer")
        pid = _launch("run_system_observer.py", "observer_detached.log", obs_args)
        print(f"[OK] Observer started    (PID {pid})")
    else:
        print("[--] Observer already running - skipping")

    print("\n[OK] Done. Both processes are now fully detached from this terminal.")
    print("     They will keep running after VSCode closes or restarts.")
    print("     Check status: python scripts/check_monitoring.py")


if __name__ == "__main__":
    main()
