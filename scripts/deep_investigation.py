"""
Deep System Investigation Script

This script performs comprehensive analysis of the monitoring system
to identify root causes of duplicate processes and activity detection issues.
"""
import subprocess
import time
import sqlite3
from datetime import datetime
from pathlib import Path
import json

def log(message):
    """Log with timestamp."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {message}")

def get_process_list():
    """Get all python processes with full command lines."""
    try:
        result = subprocess.run(
            ['wmic', 'process', 'where', "name='python.exe'", 'get', 'ProcessId,CommandLine', '/format:list'],
            capture_output=True,
            text=True,
            timeout=5
        )

        processes = []
        current = {}
        for line in result.stdout.split('\n'):
            line = line.strip()
            if not line:
                if current:
                    processes.append(current)
                    current = {}
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                current[key.strip()] = value.strip()

        return processes
    except Exception as e:
        log(f"Error getting process list: {e}")
        return []

def check_database_activity():
    """Check database activity status."""
    db_path = 'data/polymarket_tracker.db'

    if not Path(db_path).exists():
        return {'error': 'Database does not exist'}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT last_activity, process_id FROM monitoring_status WHERE id = 1")
        result = cursor.fetchone()

        if not result:
            return {'error': 'No monitoring_status record'}

        last_activity_str, process_id = result

        if last_activity_str:
            last_activity = datetime.fromisoformat(last_activity_str)
            now = datetime.now()
            diff_seconds = (now - last_activity).total_seconds()
            diff_minutes = diff_seconds / 60

            return {
                'last_activity': last_activity_str,
                'process_id': process_id,
                'minutes_ago': diff_minutes,
                'status': 'HEALTHY' if diff_minutes < 15 else 'STALE'
            }
        else:
            return {'error': 'No last_activity timestamp'}

    except Exception as e:
        return {'error': str(e)}
    finally:
        if 'conn' in locals():
            conn.close()

def check_pid_files():
    """Check PID file status."""
    monitoring_pid_file = Path('data/.monitoring.pid')
    observer_pid_file = Path('data/.system_observer.pid')

    result = {}

    # Check monitoring PID
    if monitoring_pid_file.exists():
        try:
            pid = int(monitoring_pid_file.read_text().strip())
            result['monitoring_pid'] = pid
            result['monitoring_pid_file_exists'] = True
        except:
            result['monitoring_pid'] = None
            result['monitoring_pid_file_corrupt'] = True
    else:
        result['monitoring_pid_file_exists'] = False

    # Check observer PID
    if observer_pid_file.exists():
        try:
            pid = int(observer_pid_file.read_text().strip())
            result['observer_pid'] = pid
            result['observer_pid_file_exists'] = True
        except:
            result['observer_pid'] = None
            result['observer_pid_file_corrupt'] = True
    else:
        result['observer_pid_file_exists'] = False

    return result

def snapshot():
    """Take a complete snapshot of system state."""
    snapshot_data = {
        'timestamp': datetime.now().isoformat(),
        'processes': get_process_list(),
        'pid_files': check_pid_files(),
        'database': check_database_activity()
    }

    return snapshot_data

def analyze_snapshots(snapshots):
    """Analyze snapshots to identify issues."""
    issues = []

    # Count unique processes in latest snapshot
    if snapshots:
        latest = snapshots[-1]
        python_procs = latest['processes']

        # Categorize processes
        monitoring_procs = []
        observer_procs = []
        unknown_procs = []

        for proc in python_procs:
            cmdline = proc.get('CommandLine', '').lower()
            pid = proc.get('ProcessId', '')

            if 'monitoring' in cmdline and 'observer' not in cmdline:
                monitoring_procs.append({'pid': pid, 'cmdline': cmdline})
            elif 'observer' in cmdline:
                observer_procs.append({'pid': pid, 'cmdline': cmdline})
            elif pid:  # Has a PID but unknown purpose
                unknown_procs.append({'pid': pid, 'cmdline': cmdline})

        # Check for duplicates
        if len(monitoring_procs) > 1:
            issues.append({
                'type': 'DUPLICATE_MONITORING',
                'count': len(monitoring_procs),
                'processes': monitoring_procs,
                'severity': 'CRITICAL'
            })

        if len(observer_procs) > 1:
            issues.append({
                'type': 'DUPLICATE_OBSERVER',
                'count': len(observer_procs),
                'processes': observer_procs,
                'severity': 'CRITICAL'
            })

        if unknown_procs:
            issues.append({
                'type': 'UNKNOWN_PROCESSES',
                'count': len(unknown_procs),
                'processes': unknown_procs,
                'severity': 'WARNING'
            })

        # Check PID file consistency
        pid_files = latest['pid_files']

        if pid_files.get('monitoring_pid_file_exists'):
            expected_pid = pid_files.get('monitoring_pid')
            actual_pids = [p['pid'] for p in monitoring_procs]

            if str(expected_pid) not in actual_pids:
                issues.append({
                    'type': 'PID_FILE_MISMATCH',
                    'file': 'monitoring',
                    'expected_pid': expected_pid,
                    'actual_pids': actual_pids,
                    'severity': 'HIGH'
                })

        # Check database activity
        db_status = latest['database']

        if 'error' in db_status:
            issues.append({
                'type': 'DATABASE_ERROR',
                'error': db_status['error'],
                'severity': 'HIGH'
            })
        elif db_status.get('status') == 'STALE':
            issues.append({
                'type': 'STALE_ACTIVITY',
                'minutes_ago': db_status['minutes_ago'],
                'severity': 'HIGH'
            })

    return issues

def main():
    """Run deep investigation."""
    log("="*70)
    log("DEEP SYSTEM INVESTIGATION")
    log("="*70)
    log("")

    log("Taking initial snapshot...")
    snapshots = []

    # Take snapshot every 5 seconds for 30 seconds
    for i in range(6):
        log(f"Snapshot {i+1}/6...")
        snap = snapshot()
        snapshots.append(snap)

        # Print current state
        log(f"  Processes: {len(snap['processes'])} Python processes")
        log(f"  PID files: M={snap['pid_files'].get('monitoring_pid_file_exists', False)}, O={snap['pid_files'].get('observer_pid_file_exists', False)}")
        log(f"  Database: {snap['database'].get('status', 'ERROR')}")
        log("")

        if i < 5:
            time.sleep(5)

    log("="*70)
    log("ANALYSIS")
    log("="*70)
    log("")

    # Analyze
    issues = analyze_snapshots(snapshots)

    if not issues:
        log("[OK] No issues detected")
    else:
        log(f"[WARNING] Found {len(issues)} issues:")
        log("")

        for i, issue in enumerate(issues, 1):
            log(f"{i}. {issue['type']} (Severity: {issue['severity']})")
            log(f"   Details: {json.dumps(issue, indent=4, default=str)}")
            log("")

    # Save detailed report
    report_path = 'logs/investigation_report.json'
    Path('logs').mkdir(exist_ok=True)

    with open(report_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'snapshots': snapshots,
            'issues': issues
        }, f, indent=2, default=str)

    log(f"Detailed report saved to: {report_path}")
    log("")
    log("="*70)

if __name__ == "__main__":
    main()
