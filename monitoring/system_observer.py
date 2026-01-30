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
import sqlite3
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
import psutil

from .health_checker import HealthChecker
from .log_monitor import LogMonitor
from .telegram_health_bot import TelegramHealthBot
from .diagnostics import ELOSystemDiagnostics, PerformanceMonitor, FixSuggestionEngine


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
        # NOTE: Single instance enforcement is handled by the entry point script
        # (scripts/run_system_observer.py) using OS-level file locking

        import os

        self.observer_pid = os.getpid()
        print(f"[OBSERVER] Started with PID {self.observer_pid}")

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
        self.observer_start_time = datetime.now()  # Track when observer started
        self.last_hourly_report = None
        self.last_elo_update = None  # Track last ELO update
        self.last_full_diagnostic = None  # Track last comprehensive diagnostic
        self.check_count = 0
        self.error_count = 0

        # Database path
        self.db_path = 'data/polymarket_tracker.db'

        # Initialize diagnostic engines
        self.diagnostics = ELOSystemDiagnostics(db_path=self.db_path)
        self.performance_monitor = PerformanceMonitor(db_path=self.db_path)
        self.fix_engine = FixSuggestionEngine()

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
        print(f"[OBSERVER] Daily reports: enabled (23:00 UTC)")
        print(f"[OBSERVER] Weekly reports: enabled (Sunday 23:00 UTC)")
        print(f"[OBSERVER] Analysis scheduler: enabled (daily 01:00 UTC)")
        print(f"[OBSERVER] Trend analysis: enabled (every 6 hours)")
        print(f"[OBSERVER] Comprehensive diagnostics: every 6h")
        print(f"[OBSERVER] Auto ELO updates: enabled (direct call, no subprocess)")
        print()

        # Send startup notification
        await self.telegram.send_startup_notification()

        # Start background tasks
        tasks = [
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._log_monitor_loop()),
            asyncio.create_task(self._hourly_report_loop()),
            asyncio.create_task(self._daily_report_loop()),
            asyncio.create_task(self._weekly_report_loop()),
            asyncio.create_task(self._analysis_report_loop()),
            asyncio.create_task(self._trend_analysis_loop()),
            asyncio.create_task(self._elo_update_loop()),
            asyncio.create_task(self._comprehensive_diagnostic_loop())
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
        Log monitoring loop - continuous monitoring with enhanced error detection.
        """
        print("[OBSERVER] Log monitor loop started")

        # Buffer for collecting multi-line errors
        error_buffer = []
        buffer_timeout = None

        while self.running:
            try:
                # Monitor logs for errors
                for line in self.log_monitor.tail_logs(follow=False):
                    if not self.running:
                        break

                    # Try to parse detailed error
                    detailed_error = self.log_monitor.parse_detailed_error(line)
                    if detailed_error:
                        # Skip errors from before observer started (old cached errors)
                        if detailed_error.timestamp < self.observer_start_time:
                            continue  # Ignore old errors

                        self.error_count += 1
                        print(f"[OBSERVER] Detailed error detected: {detailed_error.error_type or 'Unknown'}")

                        # Send detailed alert for all errors
                        await self.telegram.send_detailed_error_alert(detailed_error)

                        # Keep track of [Errno 22] specifically
                        if '[Errno 22]' in detailed_error.message:
                            print(f"[OBSERVER] ⚠️ [Errno 22] detected - Console encoding error")

                    else:
                        # Fallback to old error detection
                        error = self.log_monitor.detect_errors(line)
                        if error:
                            # Skip errors from before observer started
                            if error.get('timestamp') and error['timestamp'] < self.observer_start_time:
                                continue  # Ignore old errors

                            self.error_count += 1
                            print(f"[OBSERVER] Error detected: {error['type']}")

                            # Send alert for critical errors
                            if error['severity'] == 'critical':
                                await self.telegram.send_error_alert(error)

                    # Check for known issues
                    issue = self.log_monitor.detect_known_issues(line)
                    if issue:
                        # Check if issue is from after observer start
                        if len(line) >= 19:
                            try:
                                timestamp = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                                if timestamp < self.observer_start_time:
                                    continue  # Ignore old issues
                            except ValueError:
                                pass  # Can't parse timestamp, allow through

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

                    # Check for monitoring freeze and send dedicated alert
                    if 'monitoring_activity' in metrics:
                        mon_activity = metrics['monitoring_activity']
                        minutes_since = mon_activity.get('minutes_since_activity', 0)

                        if minutes_since > 30:
                            print(f"[OBSERVER] ⚠️ MONITORING FROZEN DETECTED: {minutes_since:.0f} minutes silence")

                            # Send dedicated freeze alert with diagnostics
                            freeze_diagnostics = {
                                'minutes_since_activity': minutes_since,
                                'last_activity': mon_activity.get('last_activity'),
                                'closed_positions': metrics.get('pnl_stats', {}).get('closed_positions', 0),
                                'traders_with_roi': metrics.get('pnl_stats', {}).get('traders_with_roi', 0)
                            }
                            await self.telegram.send_monitoring_freeze_alert(freeze_diagnostics)

                    # Send report
                    await self.telegram.send_hourly_report(metrics)

                    self.last_hourly_report = now

                # Check every minute
                await asyncio.sleep(60)

            except Exception as e:
                print(f"[OBSERVER] Error in hourly report loop: {e}")
                await asyncio.sleep(60)

    async def _daily_report_loop(self):
        """
        Send comprehensive daily report at 23:00 UTC.

        Report includes:
        - Top 10 traders leaderboard
        - Biggest winners/losers (24h)
        - Best trade of the day
        - Market resolutions
        - System statistics
        """
        print("[OBSERVER] Daily report loop started (triggers at 23:00 UTC)")

        while self.running:
            try:
                now = datetime.now()

                # Check if it's 23:00 UTC
                if now.hour == 23 and now.minute == 0:
                    print("[OBSERVER] Generating daily report...")

                    # Collect daily metrics
                    metrics = await self._collect_daily_metrics()

                    # Send report via Telegram
                    if self.telegram:
                        await self.telegram.send_daily_report(metrics)
                        print("[OBSERVER] Daily report sent successfully")
                    else:
                        print("[OBSERVER] [WARNING] Telegram not configured, skipping report")

                    # Wait 24 hours before next report
                    await asyncio.sleep(86400)  # 24 hours
                else:
                    # Check every minute to catch the 23:00 window
                    await asyncio.sleep(60)

            except Exception as e:
                print(f"[OBSERVER] Error in daily report loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(300)  # Wait 5 minutes on error

    async def _weekly_report_loop(self):
        """
        Send comprehensive weekly report every Sunday at 23:00 UTC.

        Report includes:
        - Top 20 traders leaderboard
        - Most active traders (7 days)
        - Best trades of the week
        - P&L leaders
        - Win rate leaders
        - Most active markets
        - Markets resolved
        - System performance
        """
        print("[OBSERVER] Weekly report loop started (triggers Sunday 23:00 UTC)")

        while self.running:
            try:
                now = datetime.now()

                # Check if it's Sunday (weekday 6) at 23:00 UTC
                if now.weekday() == 6 and now.hour == 23 and now.minute == 0:
                    print("[OBSERVER] Generating weekly report...")

                    # Collect weekly metrics
                    metrics = await self._collect_weekly_metrics()

                    # Send report via Telegram
                    if self.telegram:
                        await self.telegram.send_weekly_report(metrics)
                        print("[OBSERVER] Weekly report sent successfully")
                    else:
                        print("[OBSERVER] [WARNING] Telegram not configured, skipping report")

                    # Wait 7 days before next report
                    await asyncio.sleep(604800)  # 7 days
                else:
                    # Check every hour to catch the Sunday 23:00 window
                    await asyncio.sleep(3600)

            except Exception as e:
                print(f"[OBSERVER] Error in weekly report loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3600)  # Wait 1 hour on error

    async def _analysis_report_loop(self):
        """
        Run comprehensive analysis daily at 01:00 UTC.

        The analysis scheduler:
        - Checks data sufficiency
        - Runs 8 analysis tools in phases
        - Generates unified reports
        - Sends summary to Telegram
        """
        print("[OBSERVER] Analysis scheduler loop started (triggers at 01:00 UTC)")

        while self.running:
            try:
                now = datetime.now()

                # Check if it's 01:00 UTC (low activity time)
                if now.hour == 1 and now.minute == 0:
                    print("[OBSERVER] Triggering daily analysis...")

                    # Run analysis scheduler
                    results = await self._run_analysis_scheduler()

                    # Send results via Telegram
                    if self.telegram:
                        if results['success']:
                            await self.telegram.send_analysis_summary(results)
                            print("[OBSERVER] Analysis summary sent to Telegram")
                        else:
                            # Send status update about insufficient data
                            message = (
                                "⏳ **Daily Analysis Postponed**\n\n"
                                f"Reason: {results.get('error', 'Unknown')}\n\n"
                                "Analysis requires:\n"
                                "• 10+ resolved markets\n"
                                "• 20+ active traders\n"
                                "• 100+ total trades\n"
                                "• 5+ markets with multiple traders"
                            )
                            await self.telegram._send_message(message)
                            print("[OBSERVER] Analysis postponed - insufficient data")
                    else:
                        print("[OBSERVER] [WARNING] Telegram not configured, skipping report")

                    # Wait 24 hours before next analysis
                    await asyncio.sleep(86400)  # 24 hours
                else:
                    # Check every hour to catch the 01:00 window
                    await asyncio.sleep(3600)

            except Exception as e:
                print(f"[OBSERVER] Error in analysis report loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3600)  # Wait 1 hour on error

    async def _trend_analysis_loop(self):
        """
        Analyze market trends every 6 hours and send alerts.

        Detects:
        - Strong momentum shifts (>20% consensus change)
        - Elite trader convergence (70%+ agreement)
        - High-confidence trend signals
        - Volume spikes (3x+ normal activity)
        """
        print("[OBSERVER] Trend analysis loop started (runs every 6 hours)")

        while self.running:
            try:
                print("[OBSERVER] Running trend analysis...")

                # Detect trends
                trends = await self._detect_market_trends()

                print(f"[OBSERVER] Detected {len(trends)} active trends")

                # Send alerts for high-confidence trends
                if self.telegram and trends:
                    # Filter for high confidence (elite agreement >= 70% OR volume spike)
                    high_confidence_trends = [
                        t for t in trends
                        if t['elite_agreement'] >= 70 or t['volume_spike']
                    ]

                    if high_confidence_trends:
                        print(f"[OBSERVER] Sending {len(high_confidence_trends)} trend alerts...")

                        for trend in high_confidence_trends[:5]:  # Max 5 alerts per run
                            await self.telegram.send_trend_alert(trend)

                        print("[OBSERVER] Trend alerts sent")
                    else:
                        print("[OBSERVER] No high-confidence trends to alert")
                else:
                    if not self.telegram:
                        print("[OBSERVER] Telegram not configured, skipping alerts")

                # Wait 6 hours
                await asyncio.sleep(21600)  # 6 hours

            except Exception as e:
                print(f"[OBSERVER] Error in trend analysis loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3600)  # Wait 1 hour on error

    def _get_top_traders(self, limit: int = 5) -> list:
        """
        Get top traders by ELO for mini leaderboard.

        Args:
            limit: Number of top traders to return

        Returns:
            list: Top traders with ELO, ROI, address
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT address, comprehensive_elo, roi_percentage
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                ORDER BY comprehensive_elo DESC
                LIMIT ?
            """, (limit,))

            traders = cursor.fetchall()
            conn.close()

            return [
                {
                    'address': addr,
                    'elo': elo,
                    'roi': roi
                }
                for addr, elo, roi in traders
            ]

        except Exception as e:
            print(f"[OBSERVER] Error getting top traders: {e}")
            return []

    def _get_monitoring_activity(self) -> Dict:
        """
        Get monitoring activity status from database.

        Returns:
            dict: Activity status including last_activity timestamp
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check if monitoring_status table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='monitoring_status'
            """)

            if not cursor.fetchone():
                conn.close()
                return {
                    'last_activity': None,
                    'process_id': None,
                    'minutes_since_activity': 999
                }

            # Get last activity
            cursor.execute("""
                SELECT last_activity, process_id
                FROM monitoring_status
                WHERE id = 1
            """)

            row = cursor.fetchone()
            conn.close()

            if row and row[0]:
                last_activity = datetime.fromisoformat(row[0].replace(' ', 'T'))
                process_id = row[1]

                minutes_since = (datetime.now() - last_activity).total_seconds() / 60

                return {
                    'last_activity': last_activity,
                    'process_id': process_id,
                    'minutes_since_activity': minutes_since
                }

            return {
                'last_activity': None,
                'process_id': None,
                'minutes_since_activity': 999
            }

        except Exception as e:
            print(f"[OBSERVER] Error getting monitoring activity: {e}")
            return {
                'last_activity': None,
                'process_id': None,
                'minutes_since_activity': 999
            }

    def _get_pnl_stats(self) -> Dict:
        """
        Get P&L coverage statistics.

        Returns:
            dict: P&L stats including coverage percentage
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE roi_percentage IS NOT NULL
                AND total_trades >= 10
            """)
            traders_with_roi = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE status = 'closed'
            """)
            closed_positions = cursor.fetchone()[0]

            conn.close()

            return {
                'traders_with_roi': traders_with_roi,
                'closed_positions': closed_positions
            }

        except Exception as e:
            print(f"[OBSERVER] Error getting P&L stats: {e}")
            return {'traders_with_roi': 0, 'closed_positions': 0}

    def _check_background_worker_health(self) -> Dict:
        """
        Check health of background P&L worker.

        Returns:
            Dict with worker status and metrics
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get P&L worker statistics
            cursor.execute("""
                SELECT
                    COUNT(DISTINCT t.trader_address) as total_active,
                    COUNT(DISTINCT CASE
                        WHEN tr.pnl_last_updated IS NULL THEN t.trader_address
                    END) as never_updated,
                    COUNT(DISTINCT CASE
                        WHEN tr.pnl_last_updated < datetime('now', '-24 hours')
                        THEN t.trader_address
                    END) as stale_pnl,
                    COUNT(DISTINCT CASE
                        WHEN tr.pnl_last_updated > datetime('now', '-1 hour')
                        THEN t.trader_address
                    END) as recently_updated
                FROM trades t
                LEFT JOIN traders tr ON t.trader_address = tr.address
                WHERE t.timestamp > datetime('now', '-30 days')
            """)

            result = cursor.fetchone()

            total_active = result[0] if result else 0
            never_updated = result[1] if result else 0
            stale_pnl = result[2] if result else 0
            recently_updated = result[3] if result else 0

            # Calculate coverage
            if total_active > 0:
                coverage = ((total_active - never_updated) / total_active) * 100
            else:
                coverage = 0

            # Determine health status
            if coverage >= 90:
                status = "HEALTHY"
            elif coverage >= 50:
                status = "WORKING"
            elif coverage >= 10:
                status = "STARTING"
            else:
                status = "UNHEALTHY"

            conn.close()

            return {
                'status': status,
                'total_active_traders': total_active,
                'never_updated': never_updated,
                'stale_pnl': stale_pnl,
                'recently_updated': recently_updated,
                'coverage_percent': round(coverage, 1)
            }

        except Exception as e:
            print(f"[OBSERVER] Error checking worker health: {e}")
            return {
                'status': 'ERROR',
                'total_active_traders': 0,
                'never_updated': 0,
                'stale_pnl': 0,
                'recently_updated': 0,
                'coverage_percent': 0
            }

    def _count_activity_from_logs(self, hours: float = 1.0) -> Dict:
        """
        Count actual monitoring activity from log files.

        Args:
            hours: Time window in hours

        Returns:
            dict: Activity metrics
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)

        telegram_calls = 0
        ollama_calls = 0
        polymarket_calls = 0

        try:
            with open('logs/monitoring.log', 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    # Skip lines without timestamps
                    if len(line) < 19:
                        continue

                    # Try to parse timestamp
                    try:
                        timestamp_str = line[:19]
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                        # Only process recent lines
                        if timestamp < cutoff_time:
                            continue

                        # Count API calls
                        line_lower = line.lower()

                        if 'telegram.org' in line_lower or ('telegram' in line_lower and 'http' in line_lower):
                            telegram_calls += 1

                        if '11434' in line or 'ollama' in line_lower or 'mistral' in line_lower:
                            ollama_calls += 1

                        if 'polymarket' in line_lower or 'clob' in line_lower:
                            polymarket_calls += 1

                    except ValueError:
                        # Not a valid timestamp line
                        continue

        except FileNotFoundError:
            pass

        return {
            'trades_checked': telegram_calls,  # Each Telegram call = 1 trade notification
            'markets_scanned': ollama_calls,  # Each Ollama call = 1 market filtered by AI
            'elo_updates': 0,  # Not tracked in logs
            'api_calls': telegram_calls + ollama_calls + polymarket_calls
        }

    async def _collect_metrics(self) -> Dict:
        """
        Collect system metrics for reporting with detailed error breakdown.

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

        # Get detailed error summary from log monitor
        error_summary = self.log_monitor.get_detailed_error_summary(minutes=60)
        basic_error_summary = self.log_monitor.get_error_summary(minutes=60)

        # Count [Errno 22] occurrences specifically
        errno_22_count = 0
        recent_errors = self.log_monitor.error_parser.get_recent_errors(minutes=60)
        for error in recent_errors:
            if '[Errno 22]' in error.message or 'Invalid argument' in error.message:
                errno_22_count += 1

        # Get latest error
        latest_error = None
        if recent_errors:
            latest = recent_errors[-1]
            latest_error = {
                'error_type': latest.error_type or 'Unknown',
                'timestamp': latest.timestamp.strftime('%H:%M:%S'),
                'message': latest.message[:100]
            }

        # Build error details dict
        error_details = {
            'by_type': basic_error_summary.get('by_type', {}),
            'by_component': error_summary.get('by_component', {}),
            'latest_error': latest_error,
            'errno_22_count': errno_22_count
        }

        # Determine performance status
        error_rate = basic_error_summary['errors_per_hour']
        if error_rate < 10:
            performance = 'good'
        elif error_rate < 30:
            performance = 'moderate'
        else:
            performance = 'poor'

        # Get REAL activity from logs (last hour)
        activity = self._count_activity_from_logs(hours=1.0)

        # Get top 5 traders for mini leaderboard
        top_traders = self._get_top_traders(limit=5)

        # Get P&L coverage stats
        pnl_stats = self._get_pnl_stats()

        # Get background worker health
        worker_health = self._check_background_worker_health()

        # Get monitoring activity from database (for freeze detection)
        monitoring_activity = self._get_monitoring_activity()

        return {
            'health_status': health['status'],
            'uptime_hours': uptime_hours,
            'memory_mb': memory_mb,
            'error_count': error_summary.get('total_errors', 0),
            'error_details': error_details,
            'performance': performance,
            'activity': activity,
            'top_traders': top_traders,
            'pnl_stats': pnl_stats,
            'worker_health': worker_health,
            'monitoring_activity': monitoring_activity
        }

    async def _collect_daily_metrics(self) -> Dict:
        """
        Collect comprehensive 24-hour metrics for daily report.

        Returns:
            Dict with daily metrics including top traders, winners, losers, best trade, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        metrics = {}

        try:
            # Check if positions table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='positions'
            """)
            has_positions = cursor.fetchone() is not None
            # 1. Top 10 traders by composite ELO
            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    roi_percentage,
                    total_trades,
                    realized_pnl,
                    win_rate
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                ORDER BY comprehensive_elo DESC
                LIMIT 10
            """)

            metrics['top_10_traders'] = []
            for row in cursor.fetchall():
                metrics['top_10_traders'].append({
                    'address': row[0],
                    'elo': row[1] or 0,
                    'roi': row[2] or 0,
                    'total_trades': row[3] or 0,
                    'pnl': row[4] or 0,
                    'win_rate': row[5] or 0
                })

            # 2. Biggest winners (24h) - traders with highest P&L change
            metrics['daily_winners'] = []
            if has_positions:
                cursor.execute("""
                    SELECT
                        t.address,
                        t.comprehensive_elo,
                        SUM(CASE
                            WHEN p.realized_pnl IS NOT NULL
                            AND p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-24 hours')
                            THEN p.realized_pnl
                            ELSE 0
                        END) as pnl_24h
                    FROM traders t
                    LEFT JOIN positions p ON t.address = p.trader_address
                    GROUP BY t.address
                    HAVING pnl_24h > 0
                    ORDER BY pnl_24h DESC
                    LIMIT 5
                """)

                for row in cursor.fetchall():
                    metrics['daily_winners'].append({
                        'address': row[0],
                        'elo': row[1] or 0,
                        'pnl_24h': row[2] or 0
                    })

            # 3. Biggest losers (24h)
            metrics['daily_losers'] = []
            if has_positions:
                cursor.execute("""
                    SELECT
                        t.address,
                        t.comprehensive_elo,
                        SUM(CASE
                            WHEN p.realized_pnl IS NOT NULL
                            AND p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-24 hours')
                            THEN p.realized_pnl
                            ELSE 0
                        END) as pnl_24h
                    FROM traders t
                    LEFT JOIN positions p ON t.address = p.trader_address
                    GROUP BY t.address
                    HAVING pnl_24h < 0
                    ORDER BY pnl_24h ASC
                    LIMIT 5
                """)

                for row in cursor.fetchall():
                    metrics['daily_losers'].append({
                        'address': row[0],
                        'elo': row[1] or 0,
                        'pnl_24h': row[2] or 0
                    })

            # 4. Best single trade (24h) - highest ROI
            metrics['best_trade'] = None
            if has_positions:
                cursor.execute("""
                    SELECT
                        p.trader_address,
                        p.market_id,
                        p.outcome,
                        p.roi_percent,
                        p.realized_pnl,
                        p.exit_timestamp,
                        m.title
                    FROM positions p
                    LEFT JOIN markets m ON p.market_id = m.market_id
                    WHERE p.status = 'closed'
                      AND datetime(p.exit_timestamp) > datetime('now', '-24 hours')
                      AND p.roi_percent IS NOT NULL
                    ORDER BY p.roi_percent DESC
                    LIMIT 1
                """)

                result = cursor.fetchone()
                if result:
                    metrics['best_trade'] = {
                        'trader': result[0],
                        'market_id': result[1],
                        'outcome': result[2],
                        'roi': result[3] or 0,
                        'pnl': result[4] or 0,
                        'timestamp': result[5],
                        'market_title': result[6] or 'Unknown'
                    }

            # 5. Markets resolved (24h)
            cursor.execute("""
                SELECT COUNT(*)
                FROM markets
                WHERE resolved = 1
                  AND resolution_date IS NOT NULL
                  AND datetime(resolution_date) > datetime('now', '-24 hours')
            """)
            metrics['markets_resolved_24h'] = cursor.fetchone()[0]

            # 6. Total P&L change (24h)
            metrics['total_pnl_24h'] = 0
            if has_positions:
                cursor.execute("""
                    SELECT
                        SUM(CASE
                            WHEN p.realized_pnl IS NOT NULL
                            AND p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-24 hours')
                            THEN p.realized_pnl
                            ELSE 0
                        END) as total_pnl_24h
                    FROM positions p
                """)
                result = cursor.fetchone()
                metrics['total_pnl_24h'] = result[0] or 0

            # 7. System stats (24h)
            cursor.execute("""
                SELECT COUNT(*)
                FROM trades
                WHERE timestamp > datetime('now', '-24 hours')
            """)
            metrics['trades_24h'] = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(DISTINCT trader_address)
                FROM trades
                WHERE timestamp > datetime('now', '-24 hours')
            """)
            metrics['active_traders_24h'] = cursor.fetchone()[0]

            # 8. Background worker coverage
            worker_health = self._check_background_worker_health()
            metrics['worker_coverage'] = worker_health.get('coverage_percent', 0)

        except Exception as e:
            print(f"[OBSERVER] Error collecting daily metrics: {e}")
            import traceback
            traceback.print_exc()
            metrics['error'] = str(e)

        finally:
            conn.close()

        return metrics

    async def _collect_weekly_metrics(self) -> Dict:
        """
        Collect comprehensive 7-day metrics for weekly report.

        Returns:
            Dict with weekly metrics including top traders, movers, trends, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        metrics = {}

        try:
            # Check if positions table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='positions'
            """)
            has_positions = cursor.fetchone() is not None

            # 1. Top 20 traders by comprehensive ELO (extended leaderboard)
            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    roi_percentage,
                    total_trades,
                    realized_pnl,
                    win_rate
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                ORDER BY comprehensive_elo DESC
                LIMIT 20
            """)

            metrics['top_20_traders'] = []
            for row in cursor.fetchall():
                metrics['top_20_traders'].append({
                    'address': row[0],
                    'elo': row[1] or 0,
                    'roi': row[2] or 0,
                    'total_trades': row[3] or 0,
                    'pnl': row[4] or 0,
                    'win_rate': row[5] or 0
                })

            # 2. Most active traders (7 days) - traders with most trades
            cursor.execute("""
                SELECT
                    t.address,
                    t.comprehensive_elo,
                    COUNT(tr.trade_id) as trades_7d,
                    t.total_trades
                FROM traders t
                LEFT JOIN trades tr ON t.address = tr.trader_address
                    AND datetime(tr.timestamp) > datetime('now', '-7 days')
                WHERE t.comprehensive_elo IS NOT NULL
                GROUP BY t.address
                HAVING trades_7d > 0
                ORDER BY trades_7d DESC
                LIMIT 10
            """)

            metrics['most_active_7d'] = []
            for row in cursor.fetchall():
                metrics['most_active_7d'].append({
                    'address': row[0],
                    'elo': row[1] or 0,
                    'trades_7d': row[2] or 0,
                    'total_trades': row[3] or 0
                })

            # 3. Best trades of the week (top 10 by ROI)
            metrics['best_trades_7d'] = []
            if has_positions:
                cursor.execute("""
                    SELECT
                        p.trader_address,
                        p.market_id,
                        p.outcome,
                        p.roi_percent,
                        p.realized_pnl,
                        p.exit_timestamp,
                        m.title,
                        t.comprehensive_elo
                    FROM positions p
                    LEFT JOIN markets m ON p.market_id = m.market_id
                    LEFT JOIN traders t ON p.trader_address = t.address
                    WHERE p.status = 'closed'
                      AND datetime(p.exit_timestamp) > datetime('now', '-7 days')
                      AND p.roi_percent IS NOT NULL
                    ORDER BY p.roi_percent DESC
                    LIMIT 10
                """)

                for row in cursor.fetchall():
                    metrics['best_trades_7d'].append({
                        'trader': row[0],
                        'market_id': row[1],
                        'outcome': row[2],
                        'roi': row[3] or 0,
                        'pnl': row[4] or 0,
                        'timestamp': row[5],
                        'market_title': row[6] or 'Unknown',
                        'trader_elo': row[7] or 0
                    })

            # 4. P&L leaders (7 days) - most profitable traders
            metrics['pnl_leaders_7d'] = []
            if has_positions:
                cursor.execute("""
                    SELECT
                        t.address,
                        t.comprehensive_elo,
                        SUM(CASE
                            WHEN p.realized_pnl IS NOT NULL
                            AND p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-7 days')
                            THEN p.realized_pnl
                            ELSE 0
                        END) as pnl_7d,
                        COUNT(CASE
                            WHEN p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-7 days')
                            THEN 1
                        END) as trades_closed_7d
                    FROM traders t
                    LEFT JOIN positions p ON t.address = p.trader_address
                    GROUP BY t.address
                    HAVING pnl_7d > 0
                    ORDER BY pnl_7d DESC
                    LIMIT 10
                """)

                for row in cursor.fetchall():
                    metrics['pnl_leaders_7d'].append({
                        'address': row[0],
                        'elo': row[1] or 0,
                        'pnl_7d': row[2] or 0,
                        'trades_closed': row[3] or 0
                    })

            # 5. Win rate leaders (7 days) - best accuracy
            metrics['win_rate_leaders_7d'] = []
            if has_positions:
                cursor.execute("""
                    SELECT
                        p.trader_address,
                        t.comprehensive_elo,
                        COUNT(CASE WHEN p.realized_pnl > 0 THEN 1 END) as wins,
                        COUNT(*) as total,
                        CAST(COUNT(CASE WHEN p.realized_pnl > 0 THEN 1 END) AS FLOAT) /
                            COUNT(*) * 100 as win_rate_7d
                    FROM positions p
                    LEFT JOIN traders t ON p.trader_address = t.address
                    WHERE p.status = 'closed'
                      AND datetime(p.exit_timestamp) > datetime('now', '-7 days')
                      AND p.realized_pnl IS NOT NULL
                    GROUP BY p.trader_address
                    HAVING total >= 5
                    ORDER BY win_rate_7d DESC, total DESC
                    LIMIT 10
                """)

                for row in cursor.fetchall():
                    metrics['win_rate_leaders_7d'].append({
                        'address': row[0],
                        'elo': row[1] or 0,
                        'wins': row[2] or 0,
                        'total': row[3] or 0,
                        'win_rate': row[4] or 0
                    })

            # 6. Most active markets (7 days)
            cursor.execute("""
                SELECT
                    m.market_id,
                    m.title,
                    m.category,
                    COUNT(DISTINCT tr.trader_address) as unique_traders,
                    COUNT(tr.trade_id) as total_trades,
                    AVG(tr.price) as avg_price
                FROM markets m
                LEFT JOIN trades tr ON m.market_id = tr.market_id
                    AND datetime(tr.timestamp) > datetime('now', '-7 days')
                WHERE tr.trade_id IS NOT NULL
                GROUP BY m.market_id
                ORDER BY total_trades DESC
                LIMIT 10
            """)

            metrics['active_markets_7d'] = []
            for row in cursor.fetchall():
                metrics['active_markets_7d'].append({
                    'market_id': row[0],
                    'title': row[1] or 'Unknown',
                    'category': row[2] or 'Unknown',
                    'unique_traders': row[3] or 0,
                    'total_trades': row[4] or 0,
                    'avg_price': row[5] or 0
                })

            # 7. Markets resolved (7 days)
            cursor.execute("""
                SELECT
                    market_id,
                    title,
                    winning_outcome,
                    resolution_date
                FROM markets
                WHERE resolved = 1
                  AND resolution_date IS NOT NULL
                  AND datetime(resolution_date) > datetime('now', '-7 days')
                ORDER BY resolution_date DESC
                LIMIT 10
            """)

            metrics['markets_resolved_7d'] = []
            for row in cursor.fetchall():
                metrics['markets_resolved_7d'].append({
                    'market_id': row[0],
                    'title': row[1] or 'Unknown',
                    'outcome': row[2] or 'Unknown',
                    'resolved_at': row[3]
                })

            # 8. System statistics (7 days)
            cursor.execute("""
                SELECT COUNT(*)
                FROM trades
                WHERE datetime(timestamp) > datetime('now', '-7 days')
            """)
            metrics['trades_7d'] = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(DISTINCT trader_address)
                FROM trades
                WHERE datetime(timestamp) > datetime('now', '-7 days')
            """)
            metrics['active_traders_7d'] = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*)
                FROM markets
                WHERE resolved = 1
                  AND resolution_date IS NOT NULL
                  AND datetime(resolution_date) > datetime('now', '-7 days')
            """)
            metrics['markets_resolved_count'] = cursor.fetchone()[0]

            # Total P&L (7 days)
            metrics['total_pnl_7d'] = 0
            if has_positions:
                cursor.execute("""
                    SELECT
                        SUM(CASE
                            WHEN p.realized_pnl IS NOT NULL
                            AND p.status = 'closed'
                            AND datetime(p.exit_timestamp) > datetime('now', '-7 days')
                            THEN p.realized_pnl
                            ELSE 0
                        END) as total_pnl_7d
                    FROM positions p
                """)
                result = cursor.fetchone()
                metrics['total_pnl_7d'] = result[0] or 0

            # 9. Background worker coverage
            worker_health = self._check_background_worker_health()
            metrics['worker_coverage'] = worker_health.get('coverage_percent', 0)
            metrics['worker_status'] = worker_health.get('status', 'UNKNOWN')

            # 10. Total traders tracked
            cursor.execute("""
                SELECT COUNT(*)
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
            """)
            metrics['total_traders'] = cursor.fetchone()[0]

        except Exception as e:
            print(f"[OBSERVER] Error collecting weekly metrics: {e}")
            import traceback
            traceback.print_exc()
            metrics['error'] = str(e)

        finally:
            conn.close()

        return metrics

    async def _run_analysis_scheduler(self) -> Dict:
        """
        Run the comprehensive analysis scheduler.

        Returns:
            Dict with analysis results and summary
        """
        import os

        results = {
            'success': False,
            'error': None,
            'reports_generated': [],
            'data_sufficient': False,
            'summary': None
        }

        try:
            print("[OBSERVER] Running comprehensive analysis scheduler...")

            # Import scheduler (dynamic import to avoid circular dependencies)
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from analysis.analysis_scheduler import AnalysisScheduler

            # Initialize scheduler
            scheduler = AnalysisScheduler(
                db_path=self.db_path,
                send_alerts=False  # We'll handle Telegram via System Observer
            )

            # Step 1: Check data sufficiency
            print("[OBSERVER] Checking data sufficiency...")
            sufficiency = scheduler.check_data_sufficiency()

            results['data_sufficient'] = sufficiency.get('sufficient', False)

            if not results['data_sufficient']:
                print("[OBSERVER] Insufficient data for analysis")
                missing = sufficiency.get('missing_requirements', [])
                results['error'] = missing[0] if missing else 'Insufficient data'
                return results

            print("[OBSERVER] Data sufficient, proceeding with analysis...")

            # Step 2: Run full analysis
            print("[OBSERVER] Running full analysis (this may take 5-10 minutes)...")
            scheduler.run_full_analysis()

            # Step 3: Get generated reports
            reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
            if os.path.exists(reports_dir):
                # Find most recent reports
                from datetime import datetime
                today = datetime.now().strftime('%Y%m%d')

                report_files = [
                    f'unified_analysis_{today}*.txt',
                    f'top_opportunities_{today}*.txt',
                    f'trader_rankings_{today}*.txt'
                ]

                import glob
                for pattern in report_files:
                    report_pattern = os.path.join(reports_dir, pattern)
                    matching_files = glob.glob(report_pattern)
                    if matching_files:
                        # Get most recent file
                        most_recent = max(matching_files, key=os.path.getmtime)
                        results['reports_generated'].append(most_recent)

            # Step 4: Extract summary from unified report
            if results['reports_generated']:
                unified_report_path = [r for r in results['reports_generated']
                                      if 'unified_analysis' in r]

                if unified_report_path:
                    try:
                        with open(unified_report_path[0], 'r', encoding='utf-8') as f:
                            content = f.read()

                            # Extract key insights (first 2000 characters)
                            results['summary'] = content[:2000]
                    except Exception as e:
                        print(f"[OBSERVER] Could not read unified report: {e}")

            results['success'] = True
            print(f"[OBSERVER] Analysis complete! Generated {len(results['reports_generated'])} reports")

        except Exception as e:
            print(f"[OBSERVER] Error running analysis scheduler: {e}")
            import traceback
            traceback.print_exc()
            results['error'] = str(e)

        return results

    async def _detect_market_trends(self) -> List[Dict]:
        """
        Detect significant market trends based on:
        - Consensus shifts (>20% change in average position)
        - Elite trader agreement (>70% of top traders agree)
        - Volume spikes (>3x normal volume)

        Returns list of trend alerts.
        """
        trends = []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get markets with recent activity (last 24 hours)
            cursor.execute("""
                SELECT DISTINCT m.market_id, m.title
                FROM markets m
                JOIN trades t ON m.market_id = t.market_id
                WHERE t.timestamp >= datetime('now', '-1 day')
                AND m.resolved = 0
            """)
            active_markets = cursor.fetchall()

            for market_id, title in active_markets:
                # Get consensus shift data (compare last 6h vs previous 18h)
                cursor.execute("""
                    SELECT
                        AVG(CASE WHEN outcome = 'YES' THEN shares ELSE -shares END) as recent_consensus
                    FROM trades
                    WHERE market_id = ?
                    AND timestamp >= datetime('now', '-6 hours')
                """, (market_id,))
                recent_result = cursor.fetchone()
                recent_consensus = recent_result[0] if recent_result[0] else 0

                cursor.execute("""
                    SELECT
                        AVG(CASE WHEN outcome = 'YES' THEN shares ELSE -shares END) as previous_consensus
                    FROM trades
                    WHERE market_id = ?
                    AND timestamp >= datetime('now', '-24 hours')
                    AND timestamp < datetime('now', '-6 hours')
                """, (market_id,))
                previous_result = cursor.fetchone()
                previous_consensus = previous_result[0] if previous_result[0] else 0

                # Calculate consensus shift percentage
                if abs(previous_consensus) > 0.01:
                    shift_pct = ((recent_consensus - previous_consensus) / abs(previous_consensus)) * 100

                    # Check if shift is significant (>20%)
                    if abs(shift_pct) > 20:
                        # Get elite trader positions (top 10 by ELO)
                        cursor.execute("""
                            SELECT t.trader_address, t.outcome, SUM(t.shares) as total_shares
                            FROM trades t
                            JOIN traders tr ON t.trader_address = tr.address
                            WHERE t.market_id = ?
                            AND t.timestamp >= datetime('now', '-6 hours')
                            AND tr.comprehensive_elo IS NOT NULL
                            AND tr.comprehensive_elo >= (
                                SELECT comprehensive_elo
                                FROM traders
                                WHERE comprehensive_elo IS NOT NULL
                                ORDER BY comprehensive_elo DESC
                                LIMIT 1 OFFSET 9
                            )
                            GROUP BY t.trader_address, t.outcome
                        """, (market_id,))
                        elite_positions = cursor.fetchall()

                        # Calculate elite agreement
                        yes_shares = sum(shares for _, outcome, shares in elite_positions if outcome == 'YES')
                        no_shares = sum(shares for _, outcome, shares in elite_positions if outcome == 'NO')
                        total_elite_shares = yes_shares + no_shares

                        if total_elite_shares > 0:
                            yes_agreement = (yes_shares / total_elite_shares) * 100
                            elite_consensus = 'YES' if yes_agreement > 50 else 'NO'
                            agreement_pct = max(yes_agreement, 100 - yes_agreement)

                            # Check volume spike
                            cursor.execute("""
                                SELECT COUNT(*) as recent_trades
                                FROM trades
                                WHERE market_id = ?
                                AND timestamp >= datetime('now', '-6 hours')
                            """, (market_id,))
                            recent_trades = cursor.fetchone()[0]

                            cursor.execute("""
                                SELECT COUNT(*) / 3.0 as avg_trades
                                FROM trades
                                WHERE market_id = ?
                                AND timestamp >= datetime('now', '-24 hours')
                                AND timestamp < datetime('now', '-6 hours')
                            """, (market_id,))
                            avg_trades_result = cursor.fetchone()
                            avg_trades = avg_trades_result[0] if avg_trades_result[0] else 0

                            volume_spike = False
                            volume_multiplier = 0
                            if avg_trades > 0:
                                volume_multiplier = recent_trades / avg_trades
                                volume_spike = volume_multiplier >= 3.0

                            # Create trend alert
                            trend = {
                                'market_id': market_id,
                                'title': title,
                                'consensus_shift': shift_pct,
                                'direction': 'YES' if shift_pct > 0 else 'NO',
                                'elite_consensus': elite_consensus,
                                'elite_agreement': agreement_pct,
                                'volume_spike': volume_spike,
                                'volume_multiplier': volume_multiplier,
                                'recent_trades': recent_trades,
                                'elite_trader_count': len(set(addr for addr, _, _ in elite_positions))
                            }

                            # Add to trends if meets criteria
                            if agreement_pct >= 70 or volume_spike:
                                trends.append(trend)

        except Exception as e:
            print(f"[OBSERVER] Error detecting trends: {e}")
            import traceback
            traceback.print_exc()

        finally:
            conn.close()

        # Sort by consensus shift magnitude
        trends.sort(key=lambda x: abs(x['consensus_shift']), reverse=True)

        return trends

    async def _elo_update_loop(self):
        """
        ELO update loop - checks every 10 minutes if ELO update is needed.
        """
        print("[OBSERVER] ELO update loop started")

        while self.running:
            try:
                # Check if update needed
                if self._check_elo_update_needed():
                    print("[OBSERVER] ELO update triggered")

                    # Run ELO integration
                    elo_results = await self._run_elo_integration()

                    # Generate leaderboard
                    leaderboard = self._generate_leaderboard(top_n=20)

                    # Send notification
                    await self._send_elo_update_notification(elo_results, leaderboard)

                # Check every 10 minutes
                await asyncio.sleep(600)

            except Exception as e:
                print(f"[OBSERVER] Error in ELO update loop: {e}")
                await asyncio.sleep(600)

    def _check_elo_update_needed(self) -> bool:
        """
        Determine if ELO system needs updating.

        Triggers update if:
        - P&L coverage reached 20%+ (first time)
        - 100+ new closed positions since last update
        - 24 hours since last update

        Returns:
            bool: True if update needed
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check P&L coverage
            cursor.execute("SELECT COUNT(*) FROM traders WHERE total_trades >= 10")
            total_qualified = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE total_trades >= 10
                AND roi_percentage IS NOT NULL
            """)
            with_roi = cursor.fetchone()[0]

            coverage = with_roi / max(1, total_qualified)

            # Check hours since last update
            if self.last_elo_update is None:
                hours_since = 999  # Force first update
            else:
                hours_since = (datetime.now() - self.last_elo_update).total_seconds() / 3600

            # Get closed positions count
            cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'closed'")
            closed_positions = cursor.fetchone()[0]

            conn.close()

            # Decision logic
            reasons = []

            if coverage >= 0.20 and self.last_elo_update is None:
                reasons.append(f"P&L coverage reached {coverage*100:.1f}% (first time)")

            if hours_since >= 24:
                reasons.append(f"{hours_since:.1f} hours since last update")

            if closed_positions >= 100 and self.last_elo_update is None:
                reasons.append(f"{closed_positions} closed positions available")

            if reasons:
                print(f"\n[ELO UPDATE] Triggering update:")
                for reason in reasons:
                    print(f"  - {reason}")
                return True

            return False

        except Exception as e:
            print(f"[OBSERVER] Error checking ELO update: {e}")
            return False

    async def _run_elo_integration(self) -> Dict:
        """
        Run complete ELO integration pipeline (direct import, no subprocess).

        Returns:
            Dict with results: success status, timestamp
        """
        print(f"\n{'='*70}")
        print(f"  RUNNING ELO INTEGRATION (Direct Call)")
        print(f"{'='*70}\n")

        try:
            # Import using importlib to handle path issues robustly
            import importlib.util
            import sys
            from pathlib import Path

            # Get the script path
            scripts_dir = Path(__file__).parent.parent / 'scripts'
            script_path = scripts_dir / 'integrate_behavioral_elo.py'

            if not script_path.exists():
                raise FileNotFoundError(f"ELO integration script not found: {script_path}")

            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(
                "integrate_behavioral_elo",
                str(script_path)
            )

            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load spec for {script_path}")

            elo_module = importlib.util.module_from_spec(spec)

            # Add to sys.modules to handle internal imports
            sys.modules['integrate_behavioral_elo'] = elo_module

            # Execute the module
            spec.loader.exec_module(elo_module)

            # Get the main function
            if not hasattr(elo_module, 'main'):
                raise AttributeError("integrate_behavioral_elo.py has no main() function")

            integrate_elo_main = elo_module.main

            print("[ELO] Starting integration (direct function call)...")

            # Run in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, integrate_elo_main)

            print("[ELO] Integration complete")

            # Update timestamp
            self.last_elo_update = datetime.now()

            return {
                'success': True,
                'timestamp': datetime.now()
            }

        except Exception as e:
            print(f"[ELO] Error: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e)}

    def _generate_leaderboard(self, top_n: int = 20) -> str:
        """
        Generate formatted leaderboard for Telegram.

        Returns:
            str: Formatted leaderboard message
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    roi_percentage,
                    total_trades,
                    win_rate
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                AND total_trades >= 30
                ORDER BY comprehensive_elo DESC
                LIMIT ?
            """, (top_n,))

            traders = cursor.fetchall()
            conn.close()

            if not traders:
                return "⚠️ No traders with ELO ratings yet"

            # Format leaderboard
            message = f"🏆 **TOP {top_n} TRADERS** (ELO Rankings)\n\n"

            for i, (address, elo, roi, trades, win_rate) in enumerate(traders, 1):
                addr_short = address[:8] + "..." + address[-4:]
                roi_str = f"{roi:+.1f}%" if roi is not None else "N/A"
                wr_str = f"{win_rate*100:.1f}%" if win_rate else "N/A"

                # Medal for top 3
                medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."

                message += f"{medal} `{addr_short}`\n"
                message += f"   ELO: **{elo:.0f}** | ROI: {roi_str} | WR: {wr_str}\n"
                message += f"   Trades: {trades:,}\n\n"

            # Add footer
            message += f"_Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"

            return message

        except Exception as e:
            print(f"[OBSERVER] Error generating leaderboard: {e}")
            return f"⚠️ Error generating leaderboard: {e}"

    async def _send_elo_update_notification(self, elo_results: Dict, leaderboard: str):
        """Send ELO update notification to Telegram."""

        if not elo_results.get('success'):
            msg = "❌ **ELO Update Failed**\n\n"
            msg += f"Error: {elo_results.get('error', 'Unknown')}"
            await self.telegram.send_message(msg)
            return

        # Success notification
        correlation = elo_results.get('correlation')
        corr_str = f"r = {correlation:.3f}" if correlation else "N/A"

        msg = "✅ **ELO System Updated**\n\n"
        msg += f"📊 Correlation: {corr_str}\n"
        msg += f"⏰ Updated: {datetime.now().strftime('%H:%M')}\n\n"
        msg += leaderboard

        await self.telegram.send_message(msg)

    async def _comprehensive_diagnostic_loop(self):
        """
        Comprehensive diagnostic loop - runs every 6 hours.

        Performs deep system health checks:
        - ELO calculation pipeline
        - Analysis tools integrity
        - Database health
        - Data quality
        - Performance metrics
        """
        print("[OBSERVER] Comprehensive diagnostic loop started")

        while self.running:
            try:
                # Check if we should run full diagnostic (every 6 hours)
                should_run = False

                if self.last_full_diagnostic is None:
                    # First diagnostic after 1 hour of startup
                    if (datetime.now() - self.start_time).total_seconds() >= 3600:
                        should_run = True
                else:
                    # Check if 6 hours have passed
                    hours_since = (datetime.now() - self.last_full_diagnostic).total_seconds() / 3600
                    if hours_since >= 6:
                        should_run = True

                if should_run:
                    print("\n[DIAGNOSTIC] Running comprehensive health check...")

                    # Run full diagnostic
                    report = self.diagnostics.run_full_diagnostic()

                    # Update timestamp
                    self.last_full_diagnostic = datetime.now()

                    # Send diagnostic report to Telegram
                    await self._send_diagnostic_report(report)

                    # If critical issues found, send additional alert
                    if report['overall_status'] == 'CRITICAL':
                        critical_msg = "🚨 CRITICAL SYSTEM ISSUES DETECTED\n\nCheck diagnostic report above for details and fixes!"
                        await self.telegram._send_message(critical_msg)

                    # Collect performance metrics
                    perf_metrics = self.performance_monitor.collect_metrics()
                    perf_issues = self.performance_monitor.detect_performance_issues()

                    if perf_issues:
                        print(f"[DIAGNOSTIC] Performance issues detected: {len(perf_issues)}")
                        for issue in perf_issues:
                            print(f"  - {issue}")

                # Check every 30 minutes
                await asyncio.sleep(1800)

            except Exception as e:
                print(f"[OBSERVER] Error in diagnostic loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1800)

    async def _send_diagnostic_report(self, report: Dict):
        """
        Send comprehensive diagnostic report to Telegram.

        Args:
            report: Diagnostic report from diagnostics engine
        """
        status_emoji = {
            'HEALTHY': '✅',
            'WARNING': '⚠️',
            'CRITICAL': '🚨'
        }

        overall = report['overall_status']
        emoji = status_emoji.get(overall, '❓')

        msg_parts = [
            f"{emoji} **SYSTEM DIAGNOSTIC REPORT**",
            "",
            f"**Overall Status:** {overall}",
            f"**Time:** {report['timestamp'].strftime('%Y-%m-%d %H:%M')}",
            ""
        ]

        # Critical issues (if any)
        if report['issues']:
            msg_parts.append(f"**🚨 CRITICAL ISSUES ({len(report['issues'])}):**")
            for issue in report['issues'][:5]:  # First 5
                msg_parts.append(f"  • {issue}")

            if len(report['issues']) > 5:
                msg_parts.append(f"  • ...and {len(report['issues']) - 5} more")
            msg_parts.append("")

        # Warnings (if any)
        if report['warnings']:
            msg_parts.append(f"**⚠️ WARNINGS ({len(report['warnings'])}):**")
            for warning in report['warnings'][:5]:  # First 5
                msg_parts.append(f"  • {warning}")

            if len(report['warnings']) > 5:
                msg_parts.append(f"  • ...and {len(report['warnings']) - 5} more")
            msg_parts.append("")

        # Component status breakdown
        msg_parts.append("**📊 Component Health:**")
        for component, result in report['details'].items():
            comp_status = result['status']
            comp_emoji = status_emoji.get(comp_status, '❓')
            comp_name = component.replace('_', ' ').title()
            msg_parts.append(f"{comp_emoji} {comp_name}")

        # Key metrics
        msg_parts.append("")
        msg_parts.append("**📈 Key Metrics:**")

        elo_metrics = report['details']['elo_system'].get('metrics', {})
        msg_parts.append(f"  • ELO coverage: {elo_metrics.get('elo_coverage', 0)*100:.1f}%")
        msg_parts.append(f"  • ROI coverage: {elo_metrics.get('roi_coverage', 0)*100:.1f}%")

        db_metrics = report['details']['database'].get('metrics', {})
        msg_parts.append(f"  • DB size: {db_metrics.get('db_size_mb', 0):.0f} MB")

        data_metrics = report['details']['data_quality'].get('metrics', {})
        msg_parts.append(f"  • Last trade: {data_metrics.get('hours_since_last_trade', 0):.1f}h ago")

        # Fix recommendations (if issues exist)
        if report['issues']:
            msg_parts.append("")
            fix_report = self.fix_engine.generate_fix_report(report['issues'][:3])  # Top 3 issues
            msg_parts.append(fix_report)

        msg = '\n'.join(msg_parts)

        await self.telegram._send_message(msg)

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

        # NOTE: PID file cleanup is handled by the entry point script
        # (scripts/run_system_observer.py) using OS-level file locking

        print("[OBSERVER] Stopped")


def find_monitoring_process() -> Optional[int]:
    """
    Try to find the monitoring process PID.

    First tries reading PID from file (fast and reliable),
    then falls back to process search.

    Looks for processes running:
    - python -m monitoring (standard entry point)
    - python -m monitoring.main
    - python monitoring/main_telegram_safe.py
    - python monitor.py

    Returns:
        int: PID if found, None otherwise
    """
    # Try PID file first (most reliable method)
    pid_file = Path('data/.monitoring.pid')
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())

            # Verify process exists and is running
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if proc.is_running():
                    print(f"[OBSERVER] Found monitoring process via PID file: PID={pid}")
                    return pid
                else:
                    print(f"[OBSERVER] PID file exists but process not running (stale PID)")
            else:
                print(f"[OBSERVER] PID in file ({pid}) does not exist (stale PID)")

            # Clean up stale PID file
            pid_file.unlink()

        except PermissionError:
            # File is locked by running monitoring process - this is expected!
            # Fall through to process search
            print(f"[OBSERVER] PID file is locked (monitoring is running), using process search...")
        except (ValueError, IOError) as e:
            print(f"[OBSERVER] Error reading PID file: {e}")

    # Fallback: Search for process by command line
    print("[OBSERVER] PID file not found, searching for monitoring process...")

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

            # Patterns for monitoring process (updated for new entry point)
            patterns = [
                'start_monitoring.py',     # python scripts/start_monitoring.py (NEW STANDARD)
                '-m monitoring',           # python -m monitoring (old method)
                'monitoring.main',         # python -m monitoring.main
                'main_telegram_safe.py',   # python monitoring/main_telegram_safe.py
                'monitoring.__main__',     # python -m monitoring (module form)
                'monitor.py',              # python monitor.py
            ]

            if any(pattern in cmdline_str for pattern in patterns):
                # Avoid matching the observer itself
                if 'observer' not in cmdline_str:
                    print(f"[OBSERVER] Found monitoring process: PID={proc.info['pid']}, cmd={' '.join(cmdline[:3])}")
                    return proc.info['pid']

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return None
