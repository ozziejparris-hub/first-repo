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
from typing import Optional, Dict
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
        print(f"[OBSERVER] Comprehensive diagnostics: every 6h")
        print(f"[OBSERVER] Auto ELO updates: enabled")
        print()

        # Send startup notification
        await self.telegram.send_startup_notification()

        # Start background tasks
        tasks = [
            asyncio.create_task(self._health_check_loop()),
            asyncio.create_task(self._log_monitor_loop()),
            asyncio.create_task(self._hourly_report_loop()),
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
        Run complete ELO integration pipeline.

        Returns:
            Dict with results: correlation, success status, etc.
        """
        print(f"\n{'='*70}")
        print(f"  RUNNING ELO INTEGRATION")
        print(f"{'='*70}\n")

        try:
            # Run integration script
            result = await asyncio.create_subprocess_exec(
                'python', 'scripts/integrate_behavioral_elo.py',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=600)

            if result.returncode == 0:
                print("[ELO] Integration complete")

                # Run verification
                result = await asyncio.create_subprocess_exec(
                    'python', 'scripts/simulation/verify_elo_rankings.py',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=300)

                if result.returncode == 0:
                    print("[ELO] Verification complete")

                    # Parse correlation from output
                    correlation = None
                    output_text = stdout.decode('utf-8', errors='ignore')
                    for line in output_text.split('\n'):
                        if 'Correlation:' in line and 'r =' in line:
                            # Extract r = 0.XXX
                            parts = line.split('r =')
                            if len(parts) > 1:
                                try:
                                    correlation = float(parts[1].strip().split()[0])
                                except:
                                    pass

                    # Update timestamp
                    self.last_elo_update = datetime.now()

                    return {
                        'success': True,
                        'correlation': correlation,
                        'timestamp': datetime.now()
                    }

            print(f"[ELO] Integration failed")
            return {'success': False, 'error': stderr.decode('utf-8', errors='ignore')}

        except asyncio.TimeoutError:
            print(f"[ELO] Timeout")
            return {'success': False, 'error': 'Timeout after 10 minutes'}
        except Exception as e:
            print(f"[ELO] Error: {e}")
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

            # Patterns for monitoring process (updated for standard entry point)
            patterns = [
                '-m monitoring',           # python -m monitoring (STANDARD)
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
