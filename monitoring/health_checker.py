#!/usr/bin/env python3
"""
System Health Checker

Performs comprehensive health checks on the monitoring system:
- Process alive check
- Database accessibility
- Last activity tracking
- Error rate monitoring
- Memory usage tracking

Returns health status: healthy, warning, or critical
"""

import os
import sys
import psutil
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re


class HealthChecker:
    """
    Performs health checks on the monitoring system.

    Checks:
    1. Process alive (PID exists)
    2. Database accessible (query test)
    3. Last activity (<20 min)
    4. Error rate (from logs)
    5. Memory usage (<500MB warning)
    """

    def __init__(self, monitoring_pid: Optional[int] = None, db_path: str = 'data/polymarket_tracker.db'):
        """
        Initialize health checker.

        Args:
            monitoring_pid: PID of monitoring process (optional - will auto-detect)
            db_path: Path to database
        """
        self.monitoring_pid = monitoring_pid
        self.db_path = db_path
        self.last_check_time = None
        self.check_history = []

    def check_process_alive(self, pid: Optional[int] = None) -> Dict:
        """
        Check if monitoring process is alive.

        Args:
            pid: Process ID to check (uses self.monitoring_pid if not provided)

        Returns:
            dict: {
                'status': 'healthy' | 'critical',
                'alive': bool,
                'pid': int,
                'message': str
            }
        """
        target_pid = pid or self.monitoring_pid

        if target_pid is None:
            return {
                'status': 'warning',
                'alive': False,
                'pid': None,
                'message': 'No monitoring PID provided - cannot check process'
            }

        try:
            process = psutil.Process(target_pid)
            if process.is_running():
                return {
                    'status': 'healthy',
                    'alive': True,
                    'pid': target_pid,
                    'name': process.name(),
                    'message': f'Process {target_pid} is running ({process.name()})'
                }
            else:
                return {
                    'status': 'critical',
                    'alive': False,
                    'pid': target_pid,
                    'message': f'Process {target_pid} is not running'
                }
        except psutil.NoSuchProcess:
            return {
                'status': 'critical',
                'alive': False,
                'pid': target_pid,
                'message': f'Process {target_pid} does not exist'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'alive': False,
                'pid': target_pid,
                'message': f'Error checking process: {str(e)}'
            }

    def check_database_accessible(self) -> Dict:
        """
        Check if database is accessible.

        Returns:
            dict: {
                'status': 'healthy' | 'critical',
                'accessible': bool,
                'message': str,
                'query_time_ms': float (optional)
            }
        """
        if not os.path.exists(self.db_path):
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database file not found: {self.db_path}'
            }

        try:
            start = datetime.now()
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()

            # Simple query test
            cursor.execute("SELECT COUNT(*) FROM trades LIMIT 1")
            result = cursor.fetchone()

            conn.close()

            query_time = (datetime.now() - start).total_seconds() * 1000

            return {
                'status': 'healthy',
                'accessible': True,
                'message': f'Database accessible (query: {query_time:.1f}ms)',
                'query_time_ms': query_time
            }

        except sqlite3.OperationalError as e:
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database locked or inaccessible: {str(e)}'
            }
        except Exception as e:
            return {
                'status': 'critical',
                'accessible': False,
                'message': f'Database error: {str(e)}'
            }

    def check_last_activity(self) -> Dict:
        """
        Check when monitoring system last had activity.

        Looks at:
        - Log file modification time
        - Recent database writes

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'last_activity': datetime,
                'age_minutes': int,
                'message': str
            }
        """
        log_path = 'logs/monitoring.log'

        # Check log file modification
        if os.path.exists(log_path):
            log_mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
            age = datetime.now() - log_mtime
            age_minutes = int(age.total_seconds() / 60)

            if age_minutes < 20:
                status = 'healthy'
                message = f'Recent activity {age_minutes}m ago'
            elif age_minutes < 30:
                status = 'warning'
                message = f'Last activity {age_minutes}m ago (>20m, may have missed cycle)'
            else:
                status = 'critical'
                message = f'No activity for {age_minutes}m  (>30m, likely stuck)'

            return {
                'status': status,
                'last_activity': log_mtime,
                'age_minutes': age_minutes,
                'message': message
            }
        else:
            return {
                'status': 'warning',
                'last_activity': None,
                'age_minutes': None,
                'message': 'Log file not found - cannot determine activity'
            }

    def check_memory_usage(self, pid: Optional[int] = None) -> Dict:
        """
        Check memory usage of monitoring process.

        Args:
            pid: Process ID (uses self.monitoring_pid if not provided)

        Returns:
            dict: {
                'status': 'healthy' | 'warning',
                'memory_mb': float,
                'message': str
            }
        """
        target_pid = pid or self.monitoring_pid

        if target_pid is None:
            return {
                'status': 'warning',
                'memory_mb': None,
                'message': 'No PID provided'
            }

        try:
            process = psutil.Process(target_pid)
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / (1024 * 1024)

            if memory_mb < 500:
                status = 'healthy'
                message = f'Memory usage: {memory_mb:.1f} MB'
            elif memory_mb < 1000:
                status = 'warning'
                message = f'Memory usage high: {memory_mb:.1f} MB (>500MB)'
            else:
                status = 'critical'
                message = f'Memory usage critical: {memory_mb:.1f} MB (>1GB)'

            return {
                'status': status,
                'memory_mb': memory_mb,
                'message': message
            }

        except psutil.NoSuchProcess:
            return {
                'status': 'critical',
                'memory_mb': None,
                'message': f'Process {target_pid} not found'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'memory_mb': None,
                'message': f'Error checking memory: {str(e)}'
            }

    def check_error_rate(self, log_path: str = 'logs/monitoring.log', minutes: int = 10) -> Dict:
        """
        Check error rate in recent logs.

        Args:
            log_path: Path to log file
            minutes: Time window to check

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'error_count': int,
                'time_window_minutes': int,
                'errors_per_hour': float,
                'message': str
            }
        """
        if not os.path.exists(log_path):
            return {
                'status': 'warning',
                'error_count': None,
                'time_window_minutes': minutes,
                'errors_per_hour': None,
                'message': 'Log file not found'
            }

        try:
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            error_count = 0

            # Read last N lines (approximate time window)
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Read last 1000 lines
                lines = f.readlines()[-1000:]

                for line in lines:
                    # Check if line has timestamp and is within window
                    if 'ERROR' in line or 'CRITICAL' in line:
                        # Try to extract timestamp
                        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if match:
                            try:
                                log_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
                                if log_time >= cutoff_time:
                                    error_count += 1
                            except:
                                # If timestamp parsing fails, count it anyway
                                error_count += 1
                        else:
                            # No timestamp, count it
                            error_count += 1

            errors_per_hour = (error_count / minutes) * 60

            if error_count == 0:
                status = 'healthy'
                message = f'No errors in last {minutes}m'
            elif error_count < 5:
                status = 'healthy'
                message = f'{error_count} errors in last {minutes}m'
            elif error_count < 15:
                status = 'warning'
                message = f'{error_count} errors in last {minutes}m (elevated)'
            else:
                status = 'critical'
                message = f'{error_count} errors in last {minutes}m (high rate)'

            return {
                'status': status,
                'error_count': error_count,
                'time_window_minutes': minutes,
                'errors_per_hour': errors_per_hour,
                'message': message
            }

        except Exception as e:
            return {
                'status': 'warning',
                'error_count': None,
                'time_window_minutes': minutes,
                'errors_per_hour': None,
                'message': f'Error reading logs: {str(e)}'
            }

    async def check_all(self) -> Dict:
        """
        Run all health checks and return comprehensive report.

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'timestamp': datetime,
                'checks': {
                    'process': dict,
                    'database': dict,
                    'activity': dict,
                    'memory': dict,
                    'errors': dict
                },
                'issues': List[str],
                'summary': str
            }
        """
        timestamp = datetime.now()

        # Run all checks
        checks = {
            'process': self.check_process_alive(),
            'database': self.check_database_accessible(),
            'activity': self.check_last_activity(),
            'memory': self.check_memory_usage(),
            'errors': self.check_error_rate()
        }

        # Determine overall status
        statuses = [check['status'] for check in checks.values()]

        if 'critical' in statuses:
            overall_status = 'critical'
        elif 'warning' in statuses:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'

        # Collect issues
        issues = []
        for check_name, check_result in checks.items():
            if check_result['status'] != 'healthy':
                issues.append(f"{check_name}: {check_result['message']}")

        # Generate summary
        if overall_status == 'healthy':
            summary = 'All systems healthy'
        elif overall_status == 'warning':
            summary = f'{len(issues)} warning(s) detected'
        else:
            summary = f'{len(issues)} critical issue(s) detected'

        report = {
            'status': overall_status,
            'timestamp': timestamp,
            'checks': checks,
            'issues': issues,
            'summary': summary
        }

        # Store in history
        self.check_history.append(report)
        if len(self.check_history) > 100:
            self.check_history = self.check_history[-100:]

        self.last_check_time = timestamp

        return report
