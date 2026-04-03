#!/usr/bin/env python
"""
Check whether monitoring processes are alive without restarting them.

Exit codes (for use in bat/Task Scheduler):
    0  = all processes running
    1  = one or more processes down

Usage:
    python scripts/check_monitoring.py           # full report
    python scripts/check_monitoring.py --quiet   # exit code only, no output
"""
import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).parent.parent
os.chdir(project_root)

QUIET = "--quiet" in sys.argv


def _is_running(pid_file: Path) -> tuple[bool, int | None]:
    """Return (alive, pid). alive=True if PID file is locked by a live process."""
    if not pid_file.exists():
        return False, None
    try:
        f = open(pid_file, 'r+')
        locked = False
        try:
            try:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Lock acquired → process is dead
                pid_str = f.read(32).strip()
                pid = int(pid_str) if pid_str.isdigit() else None
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
                return False, pid
            except ImportError:
                import msvcrt
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    # Lock acquired → process is dead, read stale PID for info
                    pid_str = f.read(32).strip()
                    pid = int(pid_str) if pid_str.isdigit() else None
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    f.close()
                    return False, pid
                except OSError:
                    locked = True
            except IOError:
                locked = True
        except Exception:
            locked = True
        if locked:
            # Locked → process alive; find PID via psutil by script name
            f.close()
            try:
                import psutil
                name_map = {
                    "data/.monitoring.pid": "start_monitoring.py",
                    "data/.system_observer.pid": "run_system_observer.py",
                }
                target = name_map.get(str(pid_file).replace("\\", "/").split("first-repo/")[-1], "")
                for proc in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        cmd = " ".join(proc.info['cmdline'] or [])
                        if target and target in cmd:
                            return True, proc.pid
                    except Exception:
                        pass
            except ImportError:
                pass
            return True, None
    except Exception:
        return False, None


def _last_heartbeat() -> str | None:
    """Return the timestamp of the last watchdog heartbeat from the log."""
    log = project_root / "logs" / "monitoring.log"
    if not log.exists():
        return None
    try:
        # Read last 200 lines efficiently
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-200:]):
            if "WATCHDOG" in line and "Heartbeat" in line:
                return line[:19]   # "YYYY-MM-DD HH:MM:SS"
    except Exception:
        pass
    return None


def _recent_trades() -> tuple[int, str | None]:
    """Return (count_last_24h, most_recent_timestamp)."""
    db = project_root / "data" / "polymarket_tracker.db"
    if not db.exists():
        return 0, None
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), MAX(timestamp) FROM trades
            WHERE timestamp >= datetime('now', '-1 day')
              AND timestamp <= datetime('now')
        """)
        count, last = cur.fetchone()
        conn.close()
        return count or 0, last
    except Exception:
        return 0, None


def _trader_count() -> int:
    db = project_root / "data" / "polymarket_tracker.db"
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM traders")
        n = cur.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def main():
    mon_alive, mon_pid  = _is_running(project_root / "data" / ".monitoring.pid")
    obs_alive, obs_pid  = _is_running(project_root / "data" / ".system_observer.pid")
    all_ok = mon_alive and obs_alive

    if QUIET:
        sys.exit(0 if all_ok else 1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Polymarket Monitor Status  —  {now}")
    print(f"{'='*60}")

    mon_str = f"RUNNING  (PID {mon_pid})" if mon_alive else "STOPPED"
    obs_str = f"RUNNING  (PID {obs_pid})" if obs_alive else "STOPPED"
    print(f"\n  Monitor  : {mon_str}")
    print(f"  Observer : {obs_str}")

    hb = _last_heartbeat()
    if hb:
        try:
            hb_dt   = datetime.strptime(hb, "%Y-%m-%d %H:%M:%S")
            age_min = int((datetime.now() - hb_dt).total_seconds() / 60)
            print(f"\n  Last heartbeat  : {hb}  ({age_min}m ago)")
            if age_min > 10:
                print("  [WARNING] Heartbeat is stale — monitor loop may be stuck")
        except Exception:
            print(f"\n  Last heartbeat  : {hb}")

    trade_count, last_trade = _recent_trades()
    print(f"  Trades (24h)    : {trade_count:,}")
    if last_trade:
        print(f"  Most recent     : {last_trade}")

    print(f"  Total traders   : {_trader_count():,}")

    print()
    if all_ok:
        print("  [OK] All processes healthy")
    else:
        print("  [!!] One or more processes are DOWN")
        print("       To restart: python scripts/start_detached.py")

    print(f"{'='*60}\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
