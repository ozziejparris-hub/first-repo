#!/usr/bin/env python3
"""
System Health Observer

Main orchestrator for monitoring system health.

Runs alongside the monitoring system and provides:
- Continuous health checks (every 60s)
- Real-time log monitoring
- Error detection and alerting
- Performance metrics
- Telegram notifications

This is an independent watchdog process that monitors the main monitoring system.
"""

import asyncio
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict
import psutil

from .health_checker import HealthChecker
from .log_monitor import LogMonitor
from .telegram_health_bot import TelegramHealthBot


class SystemObserver:
    """
    Main system health observer.

    Features:
    - Health checks every 60 seconds
    - Real-time log monitoring
    - Error detection
    - Telegram alerts
    - Hourly status reports
    - Graceful shutdown
    """

    def __init__(self, telegram_token: str, chat_id: str, monitoring_pid: Optional[int] = None):
        """
        Initialize system observer.

        Args:
            telegram_token: Telegram bot token
            chat_id: Telegram chat ID
            monitoring_pid: PID of monitoring process (optional - will auto-detect)
        """
        self.telegram_token = telegram_token
        self.chat_id = chat_id
        self.monitoring_pid = monitoring_pid

        # Initialize components
        self.health_checker = HealthChecker(monitoring_pid=monitoring_pid)
        self.log_monitor = LogMonitor()
        self.telegram = TelegramHealthBot(token=telegram_token, chat_id=chat_id)

        # State
        self.running = False
        self.start_time = None
        self.last_hourly_report = None
        self.check_count = 0
        self.error_count = 0

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print("\n[OBSERVER] Received shutdown signal, stopping...")
        self.running = False

    async def run(self):
        """
        Main run loop.

        Performs:
        - Health checks every 60 seconds
        - Log monitoring continuously
        - Hourly status reports
        - Error alerting
        """
        self.running = True
        self.start_time = datetime.now()

        print("[OBSERVER] System Health Observer starting...")
        print(f"[OBSERVER] Monitoring PID: {self.monitoring_pid or 'auto-detect'}")
        print(f"[OBSERVER] Telegram alerts: enabled")
        print(f"[OBSERVER] Health check interval: 60s")
        print(f"[OBSERVER] Hourly reports: enabled")
        print()

        # Send startup notification
        await self.telegram.send_startup_notification()

        # Start background tasks
        tasks = [
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._log_monitor_loop()),
            asyncio.create_task(self._hourly_report_loop())
        ]

        try:
            # Wait for all tasks
            await asyncio.gather(*tasks)

        except asyncio.CancelledError:
            print("[OBSERVER] Tasks cancelled")

        except Exception as e:
            print(f"[OBSERVER] Error in main loop: {e}")

        finally:
            # Cleanup
            await self._shutdown()

    async def _health_check_loop(self):
        """
        Health check loop - runs every 60 seconds.
        """
        print("[OBSERVER] Health check loop started")

        while self.running:
            try:
                # Run comprehensive health check
                health = await self.health_checker.check_all()
                self.check_count += 1

                # Log result
                status_emoji = {
                    'healthy': '✅',
                    'warning': '⚠️',
                    'critical': '❌'
                }.get(health['status'], '?')

                print(f"[OBSERVER] Health check #{self.check_count}: {health['status'].upper()} {status_emoji}")

                if health['issues']:
                    for issue in health['issues']:
                        print(f"  • {issue}")

                # Send alert if not healthy
                if health['status'] != 'healthy':
                    await self.telegram.send_health_alert(health)

                # Wait 60 seconds before next check
                await asyncio.sleep(60)

            except Exception as e:
                print(f"[OBSERVER] Error in health check loop: {e}")
                await asyncio.sleep(60)

    async def _log_monitor_loop(self):
        """
        Log monitoring loop - continuous monitoring.
        """
        print("[OBSERVER] Log monitor loop started")

        while self.running:
            try:
                # Monitor logs for errors
                for line in self.log_monitor.tail_logs(follow=False):
                    if not self.running:
                        break

                    # Check for errors
                    error = self.log_monitor.detect_errors(line)
                    if error:
                        self.error_count += 1
                        print(f"[OBSERVER] Error detected: {error['type']}")

                        # Send alert for critical errors
                        if error['severity'] == 'critical':
                            await self.telegram.send_error_alert(error)

                    # Check for known issues
                    issue = self.log_monitor.detect_known_issues(line)
                    if issue:
                        print(f"[OBSERVER] Known issue detected: {issue['issue_type']}")
                        await self.telegram.send_known_issue_alert(issue)

                # Small delay before next tail cycle
                await asyncio.sleep(2)

            except Exception as e:
                print(f"[OBSERVER] Error in log monitor loop: {e}")
                await asyncio.sleep(5)

    async def _hourly_report_loop(self):
        """
        Hourly status report loop.
        """
        print("[OBSERVER] Hourly report loop started")

        while self.running:
            try:
                now = datetime.now()

                # Check if it's time for hourly report
                should_send = False

                if self.last_hourly_report is None:
                    # First report after startup (wait 1 hour)
                    if (now - self.start_time).total_seconds() >= 3600:
                        should_send = True
                else:
                    # Check if an hour has passed
                    if (now - self.last_hourly_report).total_seconds() >= 3600:
                        should_send = True

                if should_send:
                    print("[OBSERVER] Sending hourly status report...")

                    # Collect metrics
                    metrics = await self._collect_metrics()

                    # Send report
                    await self.telegram.send_hourly_report(metrics)

                    self.last_hourly_report = now

                # Check every minute
                await asyncio.sleep(60)

            except Exception as e:
                print(f"[OBSERVER] Error in hourly report loop: {e}")
                await asyncio.sleep(60)

    async def _collect_metrics(self) -> Dict:
        """
        Collect system metrics for reporting.

        Returns:
            dict: Metrics data
        """
        # Get latest health check
        health = await self.health_checker.check_all()

        # Calculate uptime
        uptime_hours = (datetime.now() - self.start_time).total_seconds() / 3600

        # Get memory usage
        memory_mb = 0
        if self.monitoring_pid:
            try:
                process = psutil.Process(self.monitoring_pid)
                memory_mb = process.memory_info().rss / (1024 * 1024)
            except:
                pass

        # Get error summary from log monitor
        error_summary = self.log_monitor.get_error_summary(minutes=60)

        # Determine performance status
        error_rate = error_summary['errors_per_hour']
        if error_rate < 10:
            performance = 'good'
        elif error_rate < 30:
            performance = 'moderate'
        else:
            performance = 'poor'

        return {
            'health_status': health['status'],
            'uptime_hours': uptime_hours,
            'memory_mb': memory_mb,
            'error_count': error_summary['total_errors'],
            'performance': performance,
            'activity': {
                # These would be populated from actual monitoring data
                # For now, placeholder values
                'trades_checked': 0,
                'markets_scanned': 0,
                'elo_updates': 0,
                'api_calls': 0
            }
        }

    async def _shutdown(self):
        """
        Graceful shutdown.
        """
        print("[OBSERVER] Shutting down...")

        # Send shutdown notification
        try:
            await self.telegram.send_shutdown_notification()
        except:
            pass

        # Log statistics
        uptime = (datetime.now() - self.start_time).total_seconds() / 3600 if self.start_time else 0

        print(f"[OBSERVER] Statistics:")
        print(f"  Uptime: {uptime:.1f} hours")
        print(f"  Health checks: {self.check_count}")
        print(f"  Errors detected: {self.error_count}")
        print("[OBSERVER] Stopped")


def find_monitoring_process() -> Optional[int]:
    """
    Try to find the monitoring process PID.

    Looks for processes running:
    - python -m monitoring.main
    - python -m monitoring.monitor
    - python monitor.py
    - python monitoring/monitor.py

    Returns:
        int: PID if found, None otherwise
    """
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Skip non-Python processes
            if proc.info['name'] not in ['python.exe', 'python', 'py.exe']:
                continue

            cmdline = proc.info.get('cmdline', [])
            if not cmdline:
                continue

            # Join and check patterns (case-insensitive for Windows compatibility)
            cmdline_str = ' '.join(str(c) for c in cmdline).lower()

            # Patterns for monitoring process
            patterns = [
                'monitoring.main',      # python -m monitoring.main (most common)
                'monitoring.monitor',   # python -m monitoring.monitor
                'monitor.py',           # python monitor.py or monitoring/monitor.py
                'polymarket',           # any polymarket monitoring script
            ]

            if any(pattern in cmdline_str for pattern in patterns):
                print(f"[OBSERVER] Found monitoring process: PID={proc.info['pid']}, cmd={' '.join(cmdline[:3])}")
                return proc.info['pid']

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return None
