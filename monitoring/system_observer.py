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
import logging
import signal
import sys
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
from pathlib import Path
import psutil

logger = logging.getLogger('observer')

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

        # Auto-restart state
        self.last_restart_attempt: Optional[datetime] = None
        self.monitoring_dead_since: Optional[datetime] = None

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
        print(f"[OBSERVER] Weekly reports: enabled (Sunday 20:00 UTC)")
        print(f"[OBSERVER] Analysis scheduler: enabled (daily 01:00 UTC)")
        print(f"[OBSERVER] Trend analysis: enabled (every 6 hours)")
        print(f"[OBSERVER] Comprehensive diagnostics: every 6h")
        print(f"[OBSERVER] Insider detection: enabled (every 15 minutes)")
        print(f"[OBSERVER] Pre-resolution intelligence: enabled (daily 08:00 UTC)")
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
            asyncio.create_task(self._comprehensive_diagnostic_loop()),
            asyncio.create_task(self._insider_detection_loop()),
            asyncio.create_task(self._pre_resolution_loop()),
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

    def _read_monitoring_pid_from_file(self) -> Optional[int]:
        """Read the current monitoring PID from data/.monitoring.pid."""
        pid_file = Path('data/.monitoring.pid')
        try:
            if pid_file.exists():
                pid = int(pid_file.read_text().strip())
                if psutil.pid_exists(pid):
                    return pid
        except Exception:
            pass
        return None

    def _was_monitoring_recently_stopped(self, within_seconds: int = 300) -> bool:
        """Return True if systemd reports monitoring stopped within the last N seconds."""
        try:
            result = subprocess.run(
                ['systemctl', 'show', 'polymarket-monitoring',
                 '--property=InactiveEnterTimestamp'],
                capture_output=True, text=True, timeout=5
            )
            line = result.stdout.strip()
            # Format: InactiveEnterTimestamp=Sat 2026-05-02 20:35:20 UTC
            if '=' not in line:
                return False
            ts_str = line.split('=', 1)[1].strip()
            if not ts_str or ts_str == 'n/a':
                return False
            # Strip day-of-week prefix (e.g. "Sat ")
            parts = ts_str.split(' ')
            if len(parts) >= 4 and parts[0][:3] in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'):
                ts_str = ' '.join(parts[1:])
            stopped_at = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S %Z').replace(tzinfo=None)
            age_seconds = (datetime.utcnow() - stopped_at).total_seconds()
            return age_seconds < within_seconds
        except Exception:
            return False

    async def _attempt_monitoring_restart(self) -> bool:
        """
        Restart polymarket-monitoring via systemctl.

        Returns True if the service came back up within 30 seconds.

        Requires passwordless sudo for this specific command:
            parison ALL=(ALL) NOPASSWD: /bin/systemctl restart polymarket-monitoring
        """
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

        print("[OBSERVER] Monitoring service dead — auto-restarting via systemctl")
        await self.telegram._send_message(
            f"🔄 MONITORING AUTO-RESTART\n"
            f"Observer detected monitoring was dead.\n"
            f"Automatically restarted via systemctl.\n"
            f"Time: {timestamp}"
        )

        self.last_restart_attempt = datetime.utcnow()

        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'polymarket-monitoring'],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            msg = f"[OBSERVER] CRITICAL — systemctl restart failed (code {result.returncode}): {result.stderr.strip()}"
            print(msg)
            await self.telegram._send_message(
                f"❌ MONITORING RESTART FAILED\n"
                f"systemctl exit code: {result.returncode}\n"
                f"stderr: {result.stderr.strip()[:200]}\n"
                f"Manual intervention needed."
            )
            return False

        # Give the service 30 seconds to come up
        await asyncio.sleep(30)

        new_pid = self._read_monitoring_pid_from_file()
        if new_pid:
            print(f"[OBSERVER] Monitoring successfully restarted (new PID {new_pid})")
            self.monitoring_pid = new_pid
            self.health_checker.monitoring_pid = new_pid
            self.monitoring_dead_since = None
            return True
        else:
            print("[OBSERVER] CRITICAL — restart failed, manual intervention needed")
            await self.telegram._send_message(
                "❌ MONITORING STILL DOWN\n"
                "Restart was attempted but service did not come back up.\n"
                "Manual intervention needed."
            )
            return False

    async def _health_check_loop(self):
        """
        Health check loop - runs every 60 seconds.
        Includes auto-restart of polymarket-monitoring when dead (once per hour).
        """
        print("[OBSERVER] Health check loop started")

        while self.running:
            try:
                # Refresh PID from file on every cycle so stale startup PID never blocks detection
                current_pid = self._read_monitoring_pid_from_file()
                if current_pid and current_pid != self.monitoring_pid:
                    print(f"[OBSERVER] PID updated from file: {self.monitoring_pid} → {current_pid}")
                    self.monitoring_pid = current_pid
                    self.health_checker.monitoring_pid = current_pid

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

                # Auto-restart logic when monitoring process is dead
                process_check = health.get('checks', {}).get('process', {})
                monitoring_is_dead = (
                    process_check.get('status') == 'critical' and
                    not process_check.get('alive', True)
                )

                if monitoring_is_dead:
                    if self.monitoring_dead_since is None:
                        # First detection — wait one more cycle to confirm
                        self.monitoring_dead_since = datetime.utcnow()
                        print("[OBSERVER] Monitoring appears dead — will confirm on next cycle in 60s")
                    else:
                        dead_for = (datetime.utcnow() - self.monitoring_dead_since).total_seconds()
                        print(f"[OBSERVER] Monitoring still dead (confirmed for {dead_for:.0f}s)")

                        # Enforce once-per-hour restart limit
                        if (self.last_restart_attempt is not None and
                                (datetime.utcnow() - self.last_restart_attempt).total_seconds() < 3600):
                            print("[OBSERVER] Skipping restart — already attempted within the last hour")
                        elif self._was_monitoring_recently_stopped(within_seconds=300):
                            print("[OBSERVER] Skipping restart — monitoring was deliberately stopped < 5 min ago")
                        else:
                            await self._attempt_monitoring_restart()
                else:
                    # Monitoring is alive — reset dead tracker
                    if self.monitoring_dead_since is not None:
                        print("[OBSERVER] Monitoring is alive again, clearing dead-since marker")
                    self.monitoring_dead_since = None

                # Wait 60 seconds before next check
                await asyncio.sleep(60)

            except Exception as e:
                import traceback
                print(f"[OBSERVER] Error in health check loop: {e}")
                traceback.print_exc()
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

                        if minutes_since > 45:
                            print(f"[OBSERVER] ⚠️ MONITORING FROZEN DETECTED: {minutes_since:.0f} minutes silence")

                            # Send dedicated freeze alert with diagnostics
                            freeze_diagnostics = {
                                'minutes_since_activity': minutes_since,
                                'last_activity': mon_activity.get('last_activity'),
                                'closed_positions': metrics.get('pnl_stats', {}).get('closed_positions_calculated', 0),
                                'traders_with_real_pnl': metrics.get('pnl_stats', {}).get('traders_with_real_pnl', 0),
                            }
                            await self.telegram.send_monitoring_freeze_alert(freeze_diagnostics)

                            if self.last_restart_attempt is None or \
                               (datetime.utcnow() - self.last_restart_attempt).total_seconds() > 3600:
                                print("[OBSERVER] Monitoring frozen — triggering auto-restart")
                                await self._attempt_monitoring_restart()

                    # DISABLED 2026-05-20 — pre-Phase 5, not actioning individual trade alerts
                    # await self._check_high_value_trades()

                    # DISABLED 2026-05-20 — pre-Phase 5, not actioning individual trade alerts
                    # await self._check_legendary_trades()

                    # Check for smart money consensus (runs every hour)
                    await self._check_consensus_positions()

                    # Check for consensus exits (runs every hour)
                    await self._check_consensus_exits()

                    # Log ELO staleness date alongside hourly report
                    await self._check_elo_staleness()

                    # Send report
                    await self.telegram.send_hourly_report(metrics)

                    self.last_hourly_report = now

                # Check every minute
                await asyncio.sleep(60)

            except Exception as e:
                import traceback
                print(f"[OBSERVER] Error in hourly report loop: {e}")
                traceback.print_exc()
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
                now = datetime.now(timezone.utc)

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
        Send comprehensive weekly report every Sunday at 20:00 UTC.

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
        print("[OBSERVER] Weekly report loop started (triggers Sunday 20:00 UTC)")

        while self.running:
            try:
                now = datetime.now(timezone.utc)

                # Check if it's Sunday (weekday 6) at 20:00 UTC (changed from 23:00 for better timing)
                if now.weekday() == 6 and now.hour == 20 and now.minute == 0:
                    print("[OBSERVER] Generating weekly performance summary...")

                    # Send simplified weekly summary focused on trader intelligence
                    await self._send_weekly_summary()

                    # Wait 7 days before next report
                    await asyncio.sleep(604800)  # 7 days
                else:
                    # Check every hour to catch the Sunday 20:00 window
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
        print("[OBSERVER] Analysis scheduler loop started (triggers at 01:00 UTC; correlation matrix at 03:00 UTC)")

        while self.running:
            try:
                now = datetime.now(timezone.utc)

                # Check if it's 03:00 UTC — run correlation matrix only
                if now.hour == 3 and now.minute == 0:
                    print("[OBSERVER] Triggering daily correlation matrix computation...")
                    loop = asyncio.get_event_loop()
                    try:
                        from analysis.analysis_scheduler import AnalysisScheduler
                        import sys, os as _os
                        scheduler = AnalysisScheduler(
                            db_path=self.db_path,
                            send_alerts=False
                        )
                        await loop.run_in_executor(
                            None,
                            lambda: scheduler.run_phase_1_independent(skip_correlation=False)
                        )
                        print("[OBSERVER] Correlation matrix computation complete")
                        if self.telegram:
                            await self.telegram._send_message(
                                "✅ **Correlation Matrix Updated** (03:00 UTC scheduled run)"
                            )
                    except Exception as e:
                        print(f"[OBSERVER] Correlation matrix run failed: {e}")
                    await asyncio.sleep(3600)  # Skip the rest of this hour

                # Check if it's 01:00 UTC (low activity time) — full analysis without correlation
                elif now.hour == 1 and now.minute == 0:
                    print("[OBSERVER] Triggering daily analysis (correlation matrix deferred to 03:00 UTC)...")

                    # Run analysis scheduler, skipping the expensive correlation matrix
                    results = await self._run_analysis_scheduler(skip_correlation=True)

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

                    # Sleep until after 03:00 UTC so both triggers fire in the same day
                    await asyncio.sleep(3600)  # wake at 02:00, then again at 03:00
                else:
                    # Check every hour to catch the trigger windows
                    await asyncio.sleep(3600)

            except Exception as e:
                print(f"[OBSERVER] Error in analysis report loop: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3600)  # Wait 1 hour on error

    async def _pre_resolution_loop(self):
        """
        Run pre-resolution intelligence daily, once per day after 08:00 UTC.

        Scans open markets resolving within 7 days, identifies divergence
        between smart money positioning and market price, and sends one
        Telegram message per high-conviction signal.
        """
        logger.info("[OBSERVER] Pre-resolution loop started — will trigger daily when hour >= 8")

        last_run_date = None  # date object; None means never run this session

        while self.running:
            try:
                now = datetime.now(timezone.utc)
                today = now.date()

                if now.hour >= 8 and last_run_date != today:
                    logger.info("[OBSERVER] Triggering pre-resolution intelligence scan...")
                    last_run_date = today

                    loop = asyncio.get_event_loop()
                    from scripts.pre_resolution_intelligence import run_pre_resolution_intelligence
                    result = await loop.run_in_executor(
                        None, run_pre_resolution_intelligence
                    )

                    logger.info(
                        "[OBSERVER] Pre-resolution scan complete — "
                        "%s markets checked, %s signal(s) sent",
                        result['markets_checked'],
                        result['signals_found']
                    )

                # Check every hour — date guard prevents re-firing on same day
                await asyncio.sleep(3600)

            except Exception as e:
                logger.error("[OBSERVER] Error in pre-resolution loop: %s", e, exc_info=True)
                await asyncio.sleep(3600)

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
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    roi_percentage,
                    total_pnl,
                    closed_positions
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                AND research_excluded = 0
                ORDER BY comprehensive_elo DESC
                LIMIT ?
            """, (limit,))

            traders = cursor.fetchall()
            conn.close()

            return [
                {
                    'address': addr,
                    'elo': elo,
                    'roi': roi if (roi and roi != 0) else None,  # None means "calculating"
                    'pnl': pnl,
                    'closed_positions': closed_pos
                }
                for addr, elo, roi, pnl, closed_pos in traders
            ]

        except Exception as e:
            print(f"[OBSERVER] Error getting top traders: {e}")
            return []

    def _get_monitoring_activity(self) -> Dict:
        """
        Get monitoring activity status.

        Primary signal: logs/monitoring.log last-modified time (written every
        cycle regardless of trade activity).
        Fallback: monitoring_status table (only updated when trades are found).

        Returns:
            dict: Activity status including last_activity timestamp
        """
        # --- Primary: log file mtime (reliable heartbeat) ---
        log_path = 'logs/monitoring.log'
        try:
            import os
            if os.path.exists(log_path):
                mtime = os.path.getmtime(log_path)
                last_activity = datetime.fromtimestamp(mtime)
                minutes_since = (datetime.now().timestamp() - mtime) / 60
                return {
                    'last_activity': last_activity,
                    'process_id': None,
                    'minutes_since_activity': minutes_since
                }
        except Exception as e:
            print(f"[OBSERVER] Could not read log mtime: {e}")

        # --- Fallback: monitoring_status table ---
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
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

        Returns three distinct, accurate metrics:
          - traders_with_real_pnl: traders that have at least one computed
            closed position (the only meaningful P&L figure)
          - closed_positions_calculated: total rows in the positions table
          - worker_backlog: traders the worker has never visited yet
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # Traders with at least one real computed closed position
            cursor.execute("""
                SELECT COUNT(DISTINCT trader_address)
                FROM positions
                WHERE status = 'closed'
            """)
            traders_with_real_pnl = cursor.fetchone()[0]

            # Total closed position records computed
            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE status = 'closed'
            """)
            closed_positions_calculated = cursor.fetchone()[0]

            # Worker backlog: traders never visited (pnl_last_updated IS NULL)
            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE pnl_last_updated IS NULL
            """)
            worker_backlog = cursor.fetchone()[0]

            # Synthetic closes: positions closed by resolution (not real SELLs)
            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE status = 'closed' AND COALESCE(is_synthetic_close, 0) = 1
            """)
            synthetic_closes = cursor.fetchone()[0]

            conn.close()

            return {
                'traders_with_real_pnl': traders_with_real_pnl,
                'closed_positions_calculated': closed_positions_calculated,
                'synthetic_closes': synthetic_closes,
                'worker_backlog': worker_backlog,
                # Keep legacy key so nothing else breaks
                'closed_positions': closed_positions_calculated,
            }

        except Exception as e:
            print(f"[OBSERVER] Error getting P&L stats: {e}")
            return {
                'traders_with_real_pnl': 0,
                'closed_positions_calculated': 0,
                'synthetic_closes': 0,
                'worker_backlog': 0,
                'closed_positions': 0,
            }

    def _check_background_worker_health(self) -> Dict:
        """
        Check health of background P&L worker.

        Returns:
            Dict with worker status and metrics
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
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

        trades_fetched = 0
        markets_checked = 0
        api_calls = 0
        cycle_count = 0

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

                        # Count actual monitoring activity
                        line_lower = line.lower()

                        # Count trades fetched/processed
                        if 'fetched' in line_lower and 'recent trades' in line_lower:
                            # Parse: "Fetched X recent trades"
                            import re
                            match = re.search(r'fetched (\d+) recent trades', line_lower)
                            if match:
                                trades_fetched += int(match.group(1))

                        # Count new trades
                        if 'new trades:' in line_lower:
                            # Parse: "New trades: X |"
                            import re
                            match = re.search(r'new trades: (\d+)', line_lower)
                            if match:
                                trades_fetched += int(match.group(1))

                        # Count monitoring cycles
                        if 'cycle complete' in line_lower or 'next check in' in line_lower:
                            cycle_count += 1

                        # Count API calls (Polymarket CLOB API)
                        if 'clob.polymarket.com' in line_lower or 'polymarket' in line_lower and 'api' in line_lower:
                            api_calls += 1

                    except ValueError:
                        # Not a valid timestamp line
                        continue

        except FileNotFoundError:
            pass

        elo_updates = (
            1
            if self.last_elo_update is not None
            and self.last_elo_update >= cutoff_time
            else 0
        )

        return {
            'trades_checked': trades_fetched,
            'markets_scanned': cycle_count,  # Each cycle scans markets
            'elo_updates': elo_updates,
            'api_calls': api_calls if api_calls > 0 else trades_fetched  # Estimate: ~1 API call per trade
        }

    async def _check_high_value_trades(self):
        """
        Monitor for high-value trades from top traders and send real-time alerts.

        Checks for:
        - Trades from traders with ELO >= 1550
        - Trade size >= $1,000
        - Within last 30 minutes (prevents duplicate alerts)
        """
        try:
            from datetime import timedelta

            # Get trades from last 30 minutes
            cutoff = datetime.now() - timedelta(minutes=30)

            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            query = """
            SELECT
                tr.trade_id,
                t.address,
                t.comprehensive_elo,
                t.roi_percentage,
                tr.market_id,
                tr.outcome,
                tr.shares,
                tr.price,
                tr.timestamp,
                m.title as market_title
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE
                t.comprehensive_elo >= 1550
                AND tr.timestamp >= ?
                AND tr.timestamp <= datetime('now')
                AND (tr.shares * tr.price) >= 1000
                AND (tr.notified = 0 OR tr.notified IS NULL)
            ORDER BY tr.timestamp DESC
            """

            cursor.execute(query, (cutoff.isoformat(),))
            trades = cursor.fetchall()
            conn.close()

            # Send alert for each high-value trade
            for trade in trades:
                trade_id, address, elo, roi, market_id, outcome, shares, price, timestamp, market_title = trade

                trade_size = shares * price
                roi_str = f"+{roi:.1f}%" if roi and roi > 0 else f"{roi:.1f}%" if roi else "Calculating..."

                # Format market title
                market_str = market_title if market_title else f"Market ID: {market_id}"

                message = f"""🎯 HIGH-VALUE TRADE ALERT

Trader: `{address}`
ELO: {elo:.0f} | ROI: {roi_str}

Market: {market_str}
Position: {outcome} @ ${price:.4f}
Size: ${trade_size:,.0f}

Time: {timestamp}

Polymarket Profile:
https://polymarket.com/profile/{address}
"""

                await self.telegram._send_message(message)
                print(f"[OBSERVER] Sent high-value trade alert for {address[:10]}... (${trade_size:,.0f})")

                # Mark as notified so it is never resent
                mark_conn = sqlite3.connect(self.db_path, timeout=30)
                mark_conn.execute(
                    "UPDATE trades SET notified = 1 WHERE trade_id = ?",
                    (trade_id,)
                )
                mark_conn.commit()
                mark_conn.close()

        except Exception as e:
            print(f"[OBSERVER] Error checking high-value trades: {e}")
            import traceback
            traceback.print_exc()

    async def _check_legendary_trades(self):
        """
        Priority alerts for high-tier traders:
          - ELO >= 2500  =>  Legendary (trophy badge)
          - ELO 2000-2499 =>  Elite    (star badge)
          - watched = 1  =>  Watched Trader (eye badge), regardless of ELO

        Runs every hour with a 48-hour lookback window so no trades are
        missed between observer restarts.  Deduplicates by trade_id.
        """
        try:
            from datetime import timedelta

            cutoff = datetime.now() - timedelta(hours=48)

            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            query = """
            SELECT
                t.address,
                t.comprehensive_elo,
                t.avg_roi,
                t.realized_pnl,
                t.closed_positions,
                COALESCE(t.watched, 0) AS watched,
                COALESCE(t.username, '') AS username,
                tr.trade_id,
                tr.outcome,
                tr.shares,
                tr.price,
                tr.side,
                tr.timestamp,
                COALESCE(m.title, tr.market_title) AS market_title
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE
                (
                    t.comprehensive_elo >= 2000
                    OR COALESCE(t.watched, 0) = 1
                    OR (t.discovery_source = 'leaderboard' AND t.comprehensive_elo >= 1500)
                )
                AND tr.timestamp >= ?
                AND tr.shares > 0
            ORDER BY COALESCE(t.watched, 0) DESC, t.comprehensive_elo DESC, tr.timestamp DESC
            """

            cursor.execute(query, (cutoff.isoformat(),))
            trades = cursor.fetchall()
            conn.close()

            for trade in trades:
                (address, elo, avg_roi, realized_pnl, closed_positions,
                 watched, username, trade_id, outcome, shares, price,
                 side, timestamp, market_title) = trade

                # Deduplicate by trade_id
                if self._already_alerted_legendary(trade_id):
                    continue

                # Determine tier: watched traders below ELO threshold get WATCHED badge
                is_watched = bool(watched)
                if is_watched and (elo is None or elo < 2000):
                    tier_badge = "WATCHED"
                    tier_icon  = "👁"
                elif elo is not None and elo >= 2500:
                    tier_badge = "LEGENDARY"
                    tier_icon  = "🏆"
                else:
                    tier_badge = "ELITE"
                    tier_icon  = "⭐"

                # Format trader identity
                addr_short = f"{address[:6]}...{address[-4:]}"
                if username:
                    trader_display = f"{username} ({addr_short})"
                else:
                    trader_display = addr_short

                # Format ELO
                elo_str = f"{elo:.0f}" if elo is not None else "N/A"

                # ELO source line
                if is_watched and (elo is None or elo < 2000):
                    elo_line = f"ELO: {elo_str}  |  Source: Manual watchlist"
                else:
                    elo_line = f"ELO: {elo_str}  |  Tier: {tier_badge}"

                # Format trader stats
                n_closed = int(closed_positions) if closed_positions else 0

                if avg_roi is not None:
                    roi_val = avg_roi if avg_roi > 1 else avg_roi * 100
                    roi_str = f"+{roi_val:.1f}%" if roi_val >= 0 else f"{roi_val:.1f}%"
                else:
                    roi_str = "No data"

                if realized_pnl is not None:
                    pnl_str = f"+${realized_pnl:,.2f}" if realized_pnl >= 0 else f"-${abs(realized_pnl):,.2f}"
                else:
                    pnl_str = "No data"

                # Format trade details
                size = shares * price
                market_str = market_title if market_title else "Unknown market"

                message = (
                    f"{tier_icon} {tier_badge} TRADER — NEW POSITION\n\n"
                    f"Trader: {trader_display}\n"
                    f"{elo_line}\n\n"
                    f"📊 Track Record\n"
                    f"   Closed Positions: {n_closed}\n"
                    f"   Avg ROI: {roi_str}\n"
                    f"   Realized P&L: {pnl_str}\n\n"
                    f"🎯 New Trade\n"
                    f"   Market: {market_str}\n"
                    f"   Outcome: {outcome}\n"
                    f"   Price: ${price:.4f}\n"
                    f"   Shares: {shares:,.0f}\n"
                    f"   Size: ${size:,.2f}\n\n"
                    f"⏰ {timestamp}\n\n"
                    f"🔗 https://polymarket.com/profile/{address}"
                )

                await self.telegram._send_message(message)
                self._mark_legendary_alerted(trade_id)
                print(f"[OBSERVER] [{tier_badge}] Alert sent for {addr_short} (ELO {elo_str})")

        except Exception as e:
            print(f"[OBSERVER] Error checking legendary trades: {e}")
            import traceback
            traceback.print_exc()

    def _already_alerted_legendary(self, trade_id: str) -> bool:
        """Check if we already sent a legendary/elite alert for this trade."""
        if not hasattr(self, '_alerted_legendary_trades'):
            self._alerted_legendary_trades = set()
        return trade_id in self._alerted_legendary_trades

    def _mark_legendary_alerted(self, trade_id: str):
        """Mark trade as alerted to prevent duplicate sends."""
        if not hasattr(self, '_alerted_legendary_trades'):
            self._alerted_legendary_trades = set()
        self._alerted_legendary_trades.add(trade_id)

    async def _send_weekly_summary(self):
        """
        Send weekly performance summary every Sunday at 20:00 (8 PM).

        Includes:
        - Best trader by profit (last 7 days)
        - Biggest ELO mover (overall)
        - Hottest market (most skilled traders)
        - Low-volume opportunities (<$10k volume, 5+ high-ELO traders)
        """
        try:
            from datetime import timedelta

            # Get data from last 7 days
            week_ago = datetime.now() - timedelta(days=7)

            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # Best trader by ELO with ROI
            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    roi_percentage,
                    total_pnl
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                AND research_excluded = 0
                ORDER BY comprehensive_elo DESC
                LIMIT 1
            """)
            best_trader = cursor.fetchone()

            # Hottest markets (most skilled traders trading)
            cursor.execute("""
                SELECT
                    m.title,
                    m.market_id,
                    COUNT(DISTINCT t.address) as skilled_traders,
                    SUM(tr.shares * tr.price) as total_volume
                FROM trades tr
                JOIN traders t ON tr.trader_address = t.address
                LEFT JOIN markets m ON tr.market_id = m.market_id
                WHERE
                    t.comprehensive_elo >= 1550
                    AND tr.timestamp >= ?
                GROUP BY m.market_id, m.title
                HAVING skilled_traders >= 3
                ORDER BY skilled_traders DESC
                LIMIT 3
            """, (week_ago.isoformat(),))
            hot_markets = cursor.fetchall()

            # Low-volume opportunities
            cursor.execute("""
                SELECT
                    m.title,
                    m.market_id,
                    m.volume,
                    COUNT(DISTINCT t.address) as skilled_traders
                FROM markets m
                JOIN trades tr ON m.market_id = tr.market_id
                JOIN traders t ON tr.trader_address = t.address
                WHERE
                    m.volume < 10000
                    AND t.comprehensive_elo >= 1550
                    AND tr.timestamp >= ?
                GROUP BY m.market_id, m.title, m.volume
                HAVING skilled_traders >= 5
                ORDER BY skilled_traders DESC
                LIMIT 3
            """, (week_ago.isoformat(),))
            opportunities = cursor.fetchall()

            # Strongest consensuses this week
            cursor.execute("""
                SELECT
                    m.title,
                    m.market_id,
                    tr.outcome,
                    COUNT(DISTINCT t.address) as trader_count,
                    SUM(tr.shares * tr.price) as volume
                FROM trades tr
                JOIN traders t ON tr.trader_address = t.address
                LEFT JOIN markets m ON tr.market_id = m.market_id
                WHERE
                    t.comprehensive_elo >= 1550
                    AND tr.timestamp >= ?
                    AND tr.shares > 0
                GROUP BY m.market_id, m.title, tr.outcome
                HAVING trader_count >= 3
                ORDER BY trader_count DESC, volume DESC
                LIMIT 3
            """, (week_ago.isoformat(),))
            consensuses = cursor.fetchall()

            conn.close()

            # Format message
            message_parts = ["📈 WEEKLY PERFORMANCE SUMMARY", ""]

            if best_trader:
                address, elo, roi, pnl = best_trader
                roi_str = f"+{roi:.1f}%" if roi and roi > 0 else f"{roi:.1f}%" if roi else "Calculating..."
                pnl_str = f"${pnl:,.0f}" if pnl else "N/A"

                message_parts.append(f"🏆 Top Trader:")
                message_parts.append(f"  • `{address}`")
                message_parts.append(f"  • ELO: {elo:.0f}")
                message_parts.append(f"  • ROI: {roi_str}")
                message_parts.append(f"  • P&L: {pnl_str}")
                message_parts.append("")

            if hot_markets:
                message_parts.append("🔥 Hottest Markets (Last 7 Days):")
                for i, (title, market_id, traders, volume) in enumerate(hot_markets, 1):
                    market_str = title if title else f"Market {market_id}"
                    message_parts.append(f"{i}. {market_str}")
                    message_parts.append(f"   {traders} skilled traders | ${volume:,.0f} volume")
                message_parts.append("")

            if opportunities:
                message_parts.append("💎 Your Opportunities:")
                message_parts.append("(Low volume markets with high skilled trader interest)")
                for i, (title, market_id, volume, traders) in enumerate(opportunities, 1):
                    market_str = title if title else f"Market {market_id}"
                    message_parts.append(f"{i}. {market_str}")
                    message_parts.append(f"   ${volume:,.0f} vol | {traders} skilled traders")
                message_parts.append("")

            if consensuses:
                message_parts.append("🎯 Strongest Consensuses This Week:")
                for i, (title, market_id, outcome, count, volume) in enumerate(consensuses, 1):
                    market_str = title if title else f"Market {market_id}"
                    message_parts.append(f"{i}. {market_str}")
                    message_parts.append(f"   {outcome} - {count} elite traders | ${volume:,.0f} volume")
                message_parts.append("")

            message = "\n".join(message_parts)
            await self.telegram._send_message(message)

            print("[OBSERVER] Sent weekly performance summary")

        except Exception as e:
            print(f"[OBSERVER] Error sending weekly summary: {e}")
            import traceback
            traceback.print_exc()

    def _compute_consensus_weights(self, trader_rows: list) -> dict:
        """
        Compute price-convergence, time-clustering, and recency weights for a
        consensus group.  Each element of trader_rows is a tuple:
            (address, elo, price, timestamp_str)

        Returns a dict with keys:
            price_mult      – price-convergence multiplier
            time_mult       – time-clustering multiplier
            weighted_count  – recency-weighted trader count
            avg_price       – mean entry price across all traders (or None)
            price_stddev    – price std-dev in dollars (or None)
            spread_days     – days between earliest and latest entry (or None)
            most_recent_str – human-readable time-since for the most recent trade
            earliest_ts     – earliest entry datetime (or None)
            latest_ts       – latest entry datetime (or None)
            price_label     – "tight ✅" / "wide ⚠️" / "N/A"
            time_label      – human-readable clustering label
        """
        import math
        from datetime import timezone

        now = datetime.now()

        # ── Parse timestamps ────────────────────────────────────────────────
        parsed = []
        for addr, elo, price, ts_str in trader_rows:
            ts = None
            if ts_str:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        ts = datetime.strptime(ts_str, fmt)
                        break
                    except ValueError:
                        continue
            parsed.append((addr, float(elo) if elo else 1500.0,
                           float(price) if price is not None else None, ts))

        # ── Price convergence ───────────────────────────────────────────────
        prices = [p for _, _, p, _ in parsed if p is not None]
        if len(prices) >= 2:
            avg_price = sum(prices) / len(prices)
            variance = sum((p - avg_price) ** 2 for p in prices) / len(prices)
            price_stddev = math.sqrt(variance)
            if price_stddev < 0.10:
                price_mult = 1.3
                price_label = "tight ✅"
            elif price_stddev > 0.20:
                price_mult = 0.8
                price_label = "wide ⚠️"
            else:
                price_mult = 1.0
                price_label = "moderate"
        else:
            avg_price = prices[0] if prices else None
            price_stddev = None
            price_mult = 1.0
            price_label = "N/A"

        # ── Time clustering ─────────────────────────────────────────────────
        timestamps = [ts for _, _, _, ts in parsed if ts is not None]
        if len(timestamps) >= 2:
            earliest_ts = min(timestamps)
            latest_ts = max(timestamps)
            spread_days = (latest_ts - earliest_ts).total_seconds() / 86400
            if spread_days <= 2:
                time_mult = 1.4
                time_label = f"{spread_days:.1f}d (strong convergence ✅)"
            elif spread_days <= 7:
                time_mult = 1.0
                time_label = f"{spread_days:.1f}d (within 1 week)"
            elif spread_days <= 30:
                time_mult = 0.85
                time_label = f"{spread_days:.1f}d (spread out ⚠️)"
            else:
                time_mult = 0.7
                time_label = f"{spread_days:.1f}d (stale ❌)"
        else:
            # Only one timestamp or none — neutral
            earliest_ts = timestamps[0] if timestamps else None
            latest_ts = timestamps[0] if timestamps else None
            spread_days = None
            time_mult = 1.0
            time_label = "N/A"

        # ── Recency weighting ───────────────────────────────────────────────
        weighted_count = 0.0
        most_recent_ts = None
        for _, elo, _, ts in parsed:
            if ts is not None:
                age_hours = (now - ts).total_seconds() / 3600
                if most_recent_ts is None or ts > most_recent_ts:
                    most_recent_ts = ts
                if age_hours <= 24:
                    w = 2.0
                elif age_hours <= 168:   # 7 days
                    w = 1.5
                elif age_hours <= 720:   # 30 days
                    w = 1.0
                else:
                    w = 0.6
            else:
                w = 1.0  # no timestamp → neutral weight
            weighted_count += w

        # Human-readable most-recent label
        if most_recent_ts is not None:
            age_secs = (now - most_recent_ts).total_seconds()
            if age_secs < 3600:
                most_recent_str = f"{int(age_secs / 60)} minutes ago"
            elif age_secs < 86400:
                most_recent_str = f"{age_secs / 3600:.1f} hours ago"
            else:
                most_recent_str = f"{age_secs / 86400:.1f} days ago"
        else:
            most_recent_str = "unknown"

        return {
            'price_mult': price_mult,
            'time_mult': time_mult,
            'weighted_count': weighted_count,
            'avg_price': avg_price,
            'price_stddev': price_stddev,
            'spread_days': spread_days,
            'most_recent_str': most_recent_str,
            'earliest_ts': earliest_ts,
            'latest_ts': latest_ts,
            'price_label': price_label,
            'time_label': time_label,
        }

    async def _check_consensus_positions(self):
        """
        Detect when multiple elite traders take the same position (smart money consensus).

        Triggers alert when:
        - 3+ traders with ELO >= 1550
        - All take same position (YES or NO)
        - At least one trade within last 24 hours

        Conviction scoring (base × price multiplier × time multiplier):
        - Base: elite_count × (avg_elo / 1500)
        - Price convergence: std-dev < $0.10 → 1.3x | > $0.20 → 0.8x | else 1.0x
        - Time clustering: ≤2d → 1.4x | ≤7d → 1.0x | ≤30d → 0.85x | >30d → 0.7x
        - Weighted count uses per-trader recency weights (last 24h → 2.0, etc.)
        """
        try:
            from datetime import timedelta

            # Broad window: fetch all trades for candidate groups (any age).
            # We look for groups with at least one trade in the last 24h to stay
            # current, but gather ALL their trades for scoring.
            cutoff_recent = datetime.now() - timedelta(hours=24)

            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # Step 1: Find candidate groups — markets where 3+ elite traders
            # are on the same outcome AND at least one trade is within 24h.
            candidate_query = """
            SELECT
                tr.market_id,
                COALESCE(m.title, tr.market_title) AS market_question,
                tr.outcome,
                COUNT(DISTINCT tr.trader_address) AS trader_count,
                SUM(tr.shares * tr.price) AS total_volume
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE
                t.comprehensive_elo >= 1550
                AND tr.shares > 0
                AND tr.market_category IN ('Geopolitics', 'Elections')
            GROUP BY tr.market_id, tr.outcome
            HAVING
                trader_count >= 3
                AND MAX(tr.timestamp) >= ?
                AND AVG(tr.price) BETWEEN 0.10 AND 0.90
                AND MAX(tr.timestamp) >= datetime('now', '-30 days')
            ORDER BY trader_count DESC, total_volume DESC
            LIMIT 10
            """

            cursor.execute(candidate_query, (cutoff_recent.isoformat(),))
            candidates = cursor.fetchall()

            if not candidates:
                conn.close()
                return

            # Step 2: For each candidate group, fetch per-trader detail rows
            # (address, elo, price, timestamp) across ALL time so we can score.
            detail_query = """
            SELECT
                t.address,
                t.comprehensive_elo,
                tr.price,
                tr.timestamp
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            WHERE
                t.comprehensive_elo >= 1550
                AND tr.market_id = ?
                AND tr.outcome = ?
                AND tr.shares > 0
            ORDER BY tr.timestamp DESC
            """

            results = []
            for market_id, question, outcome, count, volume in candidates:
                cursor.execute(detail_query, (market_id, outcome))
                detail_rows = cursor.fetchall()

                # Collapse to one row per trader (most recent trade wins)
                seen = {}
                for addr, elo, price, ts in detail_rows:
                    if addr not in seen:
                        seen[addr] = (addr, elo, price, ts)
                per_trader = list(seen.values())

                weights = self._compute_consensus_weights(per_trader)

                # Conviction scores
                avg_elo = sum(float(r[1]) for r in per_trader if r[1]) / max(len(per_trader), 1)
                base_conviction = count * (avg_elo / 1500)
                weighted_conviction = (
                    weights['weighted_count'] * (avg_elo / 1500)
                    * weights['price_mult']
                    * weights['time_mult']
                )

                results.append({
                    'market_id': market_id,
                    'question': question,
                    'outcome': outcome,
                    'count': count,
                    'volume': volume,
                    'avg_elo': avg_elo,
                    'per_trader': per_trader,
                    'base_conviction': base_conviction,
                    'weighted_conviction': weighted_conviction,
                    'weights': weights,
                })

            conn.close()

            # Sort by weighted conviction descending
            results.sort(key=lambda x: x['weighted_conviction'], reverse=True)

            # Send alerts for new consensuses
            for r in results[:5]:
                market_id = r['market_id']
                outcome = r['outcome']

                if self._already_alerted_consensus(market_id, outcome):
                    continue

                count = r['count']
                w = r['weights']
                question = r['question'] or f"Market ID: {market_id}"
                volume = r['volume']
                avg_elo = r['avg_elo']
                base_conv = r['base_conviction']
                wt_conv = r['weighted_conviction']

                # Format trader list (sorted by ELO desc, show up to 5)
                sorted_traders = sorted(r['per_trader'], key=lambda x: float(x[1]) if x[1] else 0, reverse=True)
                trader_lines = []
                for addr, elo, price, ts in sorted_traders[:5]:
                    short = f"{addr[:6]}...{addr[-4:]}"
                    elo_s = f"ELO {float(elo):.0f}" if elo else "ELO ?"
                    price_s = f" @ ${float(price):.3f}" if price is not None else ""
                    trader_lines.append(f"  • {short} ({elo_s}{price_s})")
                if len(sorted_traders) > 5:
                    trader_lines.append(f"  • ...and {len(sorted_traders) - 5} more")
                traders_text = "\n".join(trader_lines)

                # Price analysis line
                if w['avg_price'] is not None:
                    price_line = f"  Avg price: ${w['avg_price']:.3f}"
                    if w['price_stddev'] is not None:
                        price_line += f" | Spread: ±${w['price_stddev']:.3f} ({w['price_label']})"
                    else:
                        price_line += f" ({w['price_label']})"
                else:
                    price_line = "  Avg price: N/A"

                # Time window line
                time_line = f"  Time window: {w['time_label']}"

                # Most recent
                recent_line = f"  Most recent: {w['most_recent_str']}"

                # Signal strength label (based on weighted conviction)
                if wt_conv >= 5.0:
                    signal_label = "VERY STRONG"
                elif wt_conv >= 3.5:
                    signal_label = "STRONG"
                elif wt_conv >= 2.0:
                    signal_label = "MODERATE"
                else:
                    signal_label = "WEAK"

                message = (
                    f"📊 CONSENSUS SIGNAL — {count} ELITE TRADERS\n\n"
                    f"Market: {question}\n"
                    f"Outcome: {outcome}\n"
                    f"Avg ELO: {avg_elo:.0f} | Conviction: {wt_conv:.2f} (weighted)\n"
                    f"(Base conviction: {base_conv:.2f} | Volume: ${volume:,.0f})\n\n"
                    f"Entry Analysis:\n"
                    f"{price_line}\n"
                    f"{time_line}\n"
                    f"{recent_line}\n\n"
                    f"Traders:\n"
                    f"{traders_text}\n\n"
                    f"Signal: {signal_label}\n"
                    f"🔗 https://polymarket.com/event/{market_id}"
                )

                await self.telegram._send_message(message)
                self._mark_consensus_alerted(market_id, outcome)
                print(
                    f"[OBSERVER] Sent consensus alert: {market_id} {outcome} "
                    f"({count} traders, conviction {wt_conv:.2f})"
                )

        except Exception as e:
            print(f"[OBSERVER] Error checking consensus positions: {e}")
            import traceback
            traceback.print_exc()

    def _already_alerted_consensus(self, market_id: str, outcome: str) -> bool:
        """Check if we already sent alert for this consensus."""
        if not hasattr(self, '_alerted_consensuses'):
            self._alerted_consensuses = set()

        key = f"{market_id}_{outcome}"
        return key in self._alerted_consensuses

    def _mark_consensus_alerted(self, market_id: str, outcome: str):
        """Mark consensus as alerted to prevent duplicates."""
        if not hasattr(self, '_alerted_consensuses'):
            self._alerted_consensuses = set()

        key = f"{market_id}_{outcome}"
        self._alerted_consensuses.add(key)

    async def _check_consensus_exits(self):
        """
        Detect when elite traders exit consensus positions (selling/unwinding).

        Triggers alert when:
        - 2+ traders with ELO >= 1550
        - All selling positions (negative shares)
        - Within last 6 hours

        This signals profit-taking or loss-cutting by smart money.
        """
        try:
            from datetime import timedelta

            # Look for sells in last 6 hours
            recent = datetime.now() - timedelta(hours=6)

            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # Find markets where elite traders are SELLING positions
            query = """
            SELECT
                tr.market_id,
                m.title as market_question,
                tr.outcome,
                COUNT(DISTINCT tr.trader_address) as sellers,
                SUM(ABS(tr.shares)) as shares_sold,
                GROUP_CONCAT(t.address || '|' || CAST(t.comprehensive_elo AS TEXT)) as traders
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE
                t.comprehensive_elo >= 1550
                AND tr.timestamp >= ?
                AND tr.shares < 0
                AND tr.market_category IN ('Geopolitics', 'Elections')
            GROUP BY tr.market_id, tr.outcome
            HAVING sellers >= 2
            ORDER BY sellers DESC
            LIMIT 5
            """

            cursor.execute(query, (recent.isoformat(),))
            exits = cursor.fetchall()
            conn.close()

            if not exits:
                return

            # Send alerts for new exits
            for exit_data in exits:
                market_id, question, outcome, count, shares, traders_str = exit_data

                # Check if already alerted
                if self._already_alerted_exit(market_id, outcome):
                    continue

                # Parse trader details
                traders_list = traders_str.split(',')
                trader_details = []
                for t in traders_list[:3]:  # Show top 3 for exits
                    parts = t.split('|')
                    if len(parts) == 2:
                        addr, elo = parts
                        short_addr = addr[:6] + "..." + addr[-4:]
                        try:
                            elo_float = float(elo)
                            trader_details.append(f"  • {short_addr} (ELO: {elo_float:.0f})")
                        except ValueError:
                            trader_details.append(f"  • {short_addr}")

                traders_text = "\n".join(trader_details)
                if len(traders_list) > 3:
                    traders_text += f"\n  • ...and {len(traders_list) - 3} more"

                # Format market title
                market_str = question if question else f"Market ID: {market_id}"

                message = f"""🚨 SMART MONEY EXIT DETECTED

📊 Market: {market_str}
🎲 Position: {outcome}
👥 Elite Traders Exiting: {count}
📉 Shares Sold: {shares:,.0f}

Sellers:
{traders_text}

⚠️ Signal: Elite traders taking profits or cutting losses

🔗 Market: https://polymarket.com/event/{market_id}
"""

                await self.telegram._send_message(message)
                self._mark_exit_alerted(market_id, outcome)
                print(f"[OBSERVER] Sent exit alert: {market_id} {outcome} ({count} traders)")

        except Exception as e:
            print(f"[OBSERVER] Error checking consensus exits: {e}")
            import traceback
            traceback.print_exc()

    def _already_alerted_exit(self, market_id: str, outcome: str) -> bool:
        """Check if we already alerted this exit."""
        if not hasattr(self, '_alerted_exits'):
            self._alerted_exits = set()

        key = f"{market_id}_{outcome}"
        return key in self._alerted_exits

    def _mark_exit_alerted(self, market_id: str, outcome: str):
        """Mark exit as alerted to prevent duplicates."""
        if not hasattr(self, '_alerted_exits'):
            self._alerted_exits = set()

        key = f"{market_id}_{outcome}"
        self._alerted_exits.add(key)

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
            # ROI and realized_pnl come from the positions table (same source as
            # the hourly report and ELO modifier), not traders.roi_percentage which
            # is initialised to 0.0 and not reliably updated.
            cursor.execute("""
                SELECT
                    t.address,
                    t.comprehensive_elo,
                    COALESCE(p.avg_roi, 0)       AS roi,
                    t.total_trades,
                    COALESCE(p.realized_pnl, 0)  AS realized_pnl,
                    t.win_rate
                FROM traders t
                LEFT JOIN (
                    SELECT
                        trader_address,
                        AVG(roi_percent)  AS avg_roi,
                        SUM(realized_pnl) AS realized_pnl
                    FROM positions
                    WHERE status = 'closed'
                    GROUP BY trader_address
                ) p ON t.address = p.trader_address
                WHERE t.comprehensive_elo IS NOT NULL
                AND t.research_excluded = 0
                ORDER BY t.comprehensive_elo DESC
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
            # ROI and realized_pnl sourced from positions table (not traders.roi_percentage).
            cursor.execute("""
                SELECT
                    t.address,
                    t.comprehensive_elo,
                    COALESCE(p.avg_roi, 0)       AS roi,
                    t.total_trades,
                    COALESCE(p.realized_pnl, 0)  AS realized_pnl,
                    t.win_rate
                FROM traders t
                LEFT JOIN (
                    SELECT
                        trader_address,
                        AVG(roi_percent)  AS avg_roi,
                        SUM(realized_pnl) AS realized_pnl
                    FROM positions
                    WHERE status = 'closed'
                    GROUP BY trader_address
                ) p ON t.address = p.trader_address
                WHERE t.comprehensive_elo IS NOT NULL
                AND t.research_excluded = 0
                ORDER BY t.comprehensive_elo DESC
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

    async def _run_analysis_scheduler(self, skip_correlation=False) -> Dict:
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
            # IMPORTANT: run_full_analysis() calls correlation_matrix.build_correlation_matrix()
            # which is a synchronous O(n²) computation over 70M+ pairs.  Calling it directly
            # on the event loop freezes ALL other tasks (hourly reports, health checks, Telegram)
            # for the duration.  Offload to a thread pool executor so the event loop stays free.
            print("[OBSERVER] Running full analysis in thread executor (non-blocking)...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: scheduler.run_full_analysis(skip_correlation=skip_correlation))

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
                                AND research_excluded = 0
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
        ELO staleness monitor - checks every 10 minutes and alerts if overdue.

        ELO recalculation is owned exclusively by daily_maintenance.py (cron 06:00 UTC):
          - Daily: apply_full_elo_modifiers.py
          - Sunday: recalculate_comprehensive_elo.py + apply_full_elo_modifiers.py
        This loop only monitors staleness and sends Telegram alerts; it does not
        trigger recalculation itself.
        """
        print("[OBSERVER] ELO update loop started (staleness monitoring only)")

        while self.running:
            try:
                # Check ELO recalculation staleness and alert if overdue
                await self._check_elo_staleness()

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
            conn = sqlite3.connect(self.db_path, timeout=30)
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

    async def _check_elo_staleness(self) -> Dict:
        """
        Check how long since the last full ELO recalculation.

        Sends CRITICAL alert if > 14 days, WARNING if > 7 days.
        Rate-limited to one alert per 6 hours per severity level.
        Always logs the staleness state for hourly report visibility.

        Returns:
            dict: {'last_recalc': str|None, 'days_stale': int|None}
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    MAX(elo_last_updated) as last_recalc,
                    CAST(julianday('now') - julianday(MAX(elo_last_updated)) AS INTEGER)
                        as days_stale
                FROM traders
                WHERE elo_last_updated IS NOT NULL
            """)
            row = cursor.fetchone()
            conn.close()

            if not row or row[0] is None:
                print("[OBSERVER] ELO staleness: no elo_last_updated data found")
                return {'last_recalc': None, 'days_stale': None}

            last_recalc_str, days_stale = row[0], row[1]
            last_recalc_date = last_recalc_str[:10] if last_recalc_str else 'unknown'

            print(f"[OBSERVER] ELO staleness: last recalc {last_recalc_date} ({days_stale} day(s) ago)")

            if days_stale is not None and days_stale > 14:
                if self.telegram._should_send_alert('elo_staleness_critical', minutes=360):
                    message = (
                        f"❌ ELO STALENESS CRITICAL\n\n"
                        f"Last full ELO recalculation: {last_recalc_date} ({days_stale} days ago)\n\n"
                        f"Action: run python3 scripts/recalculate_comprehensive_elo.py\n"
                        f"or wait for Sunday automatic run."
                    )
                    await self.telegram._send_message(message)
                    print(f"[OBSERVER] CRITICAL ELO staleness alert sent ({days_stale} days)")

            elif days_stale is not None and days_stale > 7:
                if self.telegram._should_send_alert('elo_staleness_warning', minutes=360):
                    message = (
                        f"⚠️ ELO STALENESS WARNING\n\n"
                        f"Last full ELO recalculation: {last_recalc_date} ({days_stale} days ago)\n\n"
                        f"Action: run python3 scripts/recalculate_comprehensive_elo.py\n"
                        f"or wait for Sunday automatic run."
                    )
                    await self.telegram._send_message(message)
                    print(f"[OBSERVER] WARNING ELO staleness alert sent ({days_stale} days)")

            return {'last_recalc': last_recalc_str, 'days_stale': days_stale}

        except Exception as e:
            print(f"[OBSERVER] Error checking ELO staleness: {e}")
            return {'last_recalc': None, 'days_stale': None}

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

            # DISABLED 2026-06-05: behavioral_modifier is written here but silently discarded by
            # apply_full_elo_modifiers.py which overwrites comprehensive_elo without reading it.
            # Intentionally disabled until comprehensive_elo formula is redesigned (RQ-CONTESTED-001,
            # July 2026). Re-enable when apply_full_elo_modifiers.py is updated to include
            # behavioral_modifier in its calculation.
            #
            # script_path = scripts_dir / 'integrate_behavioral_elo.py'
            # if not script_path.exists():
            #     raise FileNotFoundError(f"ELO integration script not found: {script_path}")
            # spec = importlib.util.spec_from_file_location("integrate_behavioral_elo", str(script_path))
            # if spec is None or spec.loader is None:
            #     raise ImportError(f"Could not load spec for {script_path}")
            # elo_module = importlib.util.module_from_spec(spec)
            # sys.modules['integrate_behavioral_elo'] = elo_module
            # spec.loader.exec_module(elo_module)
            # if not hasattr(elo_module, 'main'):
            #     raise AttributeError("integrate_behavioral_elo.py has no main() function")
            # integrate_elo_main = elo_module.main
            # print("[ELO] Starting integration (direct function call)...")
            # loop = asyncio.get_event_loop()
            # await loop.run_in_executor(None, integrate_elo_main)
            # print("[ELO] Integration complete")

            loop = asyncio.get_event_loop()

            # --- P&L modifier pass ---
            # integrate_behavioral_elo writes comprehensive_elo without P&L
            # modifiers (apply_pnl=False).  Immediately re-apply the P&L
            # multiplier on top so the leaderboard always reflects real P&L data.
            print("[ELO] Applying P&L modifiers (second pass)...")
            pnl_script_path = scripts_dir / 'apply_full_elo_modifiers.py'
            if pnl_script_path.exists():
                pnl_spec = importlib.util.spec_from_file_location(
                    "apply_full_elo_modifiers",
                    str(pnl_script_path)
                )
                if pnl_spec and pnl_spec.loader:
                    pnl_module = importlib.util.module_from_spec(pnl_spec)
                    sys.modules['apply_full_elo_modifiers'] = pnl_module
                    pnl_spec.loader.exec_module(pnl_module)
                    if hasattr(pnl_module, 'main'):
                        # main() uses argparse; patch sys.argv so it sees no flags
                        import sys as _sys
                        _saved_argv = _sys.argv
                        _sys.argv = ['apply_full_elo_modifiers.py']
                        try:
                            await loop.run_in_executor(None, pnl_module.main)
                        finally:
                            _sys.argv = _saved_argv
                        print("[ELO] P&L modifier pass complete")
                    else:
                        print("[ELO] WARNING: apply_full_elo_modifiers.py has no main() — skipping P&L pass")
                else:
                    print("[ELO] WARNING: could not load apply_full_elo_modifiers spec — skipping P&L pass")
            else:
                print(f"[ELO] WARNING: {pnl_script_path} not found — skipping P&L pass")

            # Update timestamp
            self.last_elo_update = datetime.now()

            print(f"[ELO] ELO integration completed successfully at {self.last_elo_update.strftime('%Y-%m-%d %H:%M:%S')}")
            return {
                'success': True,
                'timestamp': self.last_elo_update
            }

        except Exception as e:
            print(f"[ELO] ELO integration failed: {e}")
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
            conn = sqlite3.connect(self.db_path, timeout=30)
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
                AND research_excluded = 0
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
            await self.telegram._send_message(msg)
            return

        # Success notification
        correlation = elo_results.get('correlation')
        corr_str = f"r = {correlation:.3f}" if correlation else "N/A"

        msg = "✅ **ELO System Updated**\n\n"
        msg += f"📊 Correlation: {corr_str}\n"
        msg += f"⏰ Updated: {datetime.now().strftime('%H:%M')}\n\n"
        msg += leaderboard

        await self.telegram._send_message(msg)

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

                    # Run full diagnostic in executor to avoid blocking the event loop
                    loop = asyncio.get_event_loop()
                    report = await loop.run_in_executor(None, self.diagnostics.run_full_diagnostic)

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

    async def _insider_detection_loop(self):
        """
        Scan for insider trading patterns every 15 minutes.

        Two patterns detected:
          - Individual: fresh wallet + large bet + low-odds entry + single market
          - Cluster: 3+ fresh wallets same outcome same market within 6h

        Results stored in insider_signals / insider_clusters tables and sent
        via Telegram immediately.  Runs a 2-hour lookback on each cycle so
        short windows (the Feb 28 Iran pattern had a 71-minute window) are
        never missed between restarts.
        """
        from scripts.detect_insider_activity import (
            _connect as _ins_connect,
            _ensure_tables as _ins_ensure_tables,
            detect_individual_signals,
            detect_cluster_signals,
            save_signals,
            format_signal_alert,
            format_cluster_alert,
        )
        from datetime import timedelta

        print("[OBSERVER] Insider detection loop started (every 15 min, 2h lookback)")
        CHECK_INTERVAL = 900  # 15 minutes

        # Track alerted IDs in memory to avoid re-sending on restart
        alerted_signals:  set = set()
        alerted_clusters: set = set()

        # Seed from DB on startup so we don't re-alert old signals
        try:
            conn = _ins_connect(self.db_path)
            _ins_ensure_tables(conn)
            cur = conn.cursor()
            cur.execute("SELECT market_id, trader_address, trade_timestamp FROM insider_signals WHERE alerted = 1")
            for mid, addr, ts in cur.fetchall():
                alerted_signals.add((mid, addr, ts))
            cur.execute("SELECT market_id, outcome, window_start FROM insider_clusters WHERE alerted = 1")
            for mid, out, ws in cur.fetchall():
                alerted_clusters.add((mid, out, ws))

            # Catch-up: send any signals/clusters that were stored but never alerted
            # (e.g. observer was restarted before the send completed)
            cur.execute("""
                SELECT trader_address, username, market_id, market_title, outcome,
                       position_size, entry_price, wallet_age_days, markets_count,
                       trade_timestamp, pattern
                FROM insider_signals WHERE alerted = 0
                ORDER BY detected_at ASC
            """)
            pending_signals = cur.fetchall()
            cur.execute("""
                SELECT market_id, market_title, outcome, wallet_count, combined_size,
                       window_start, window_end
                FROM insider_clusters WHERE alerted = 0
                ORDER BY detected_at ASC
            """)
            pending_clusters = cur.fetchall()
            conn.close()
        except Exception as e:
            print(f"[INSIDER] Seed error: {e}")
            pending_signals = []
            pending_clusters = []

        # Fire catch-up alerts before entering the regular loop
        if pending_signals or pending_clusters:
            print(f"[INSIDER] Catch-up: {len(pending_signals)} signal(s) and "
                  f"{len(pending_clusters)} cluster(s) pending from previous run")
        for row in pending_signals:
            (addr, username, mid, title, outcome,
             pos_size, price, age, mkts, ts, pattern) = row
            sig = {
                "trader_address": addr, "username": username,
                "market_id": mid, "market_title": title, "outcome": outcome,
                "position_size": pos_size, "entry_price": price,
                "wallet_age_days": age, "markets_count": mkts,
                "trade_timestamp": ts, "pattern": pattern,
            }
            key = (mid, addr, ts)
            if key in alerted_signals:
                continue
            alerted_signals.add(key)
            try:
                msg = format_signal_alert(sig)
                await self.telegram._send_message(msg)
                conn2 = _ins_connect(self.db_path)
                conn2.execute(
                    "UPDATE insider_signals SET alerted = 1 WHERE trader_address = ? AND market_id = ? AND trade_timestamp = ?",
                    (addr, mid, ts)
                )
                conn2.commit()
                conn2.close()
                print(f"[INSIDER] Catch-up alert sent: {addr[:10]}... ${pos_size:,.0f} on {title[:40]}")
            except Exception as e:
                print(f"[INSIDER] Catch-up send error: {e}")

        for row in pending_clusters:
            (mid, title, outcome, wcount, csize, ws, we) = row
            cl = {
                "market_id": mid, "market_title": title, "outcome": outcome,
                "wallet_count": wcount, "combined_size": csize,
                "window_start": ws, "window_end": we,
            }
            key = (mid, outcome, ws)
            if key in alerted_clusters:
                continue
            alerted_clusters.add(key)
            try:
                msg = format_cluster_alert(cl)
                await self.telegram._send_message(msg)
                conn2 = _ins_connect(self.db_path)
                conn2.execute(
                    "UPDATE insider_clusters SET alerted = 1 WHERE market_id = ? AND outcome = ? AND window_start = ?",
                    (mid, outcome, ws)
                )
                conn2.commit()
                conn2.close()
                print(f"[INSIDER] Catch-up cluster sent: {wcount} wallets ${csize:,.0f} on {title[:40]}")
            except Exception as e:
                print(f"[INSIDER] Catch-up cluster send error: {e}")

        while self.running:
            try:
                since = datetime.now() - timedelta(hours=2)
                conn  = _ins_connect(self.db_path)
                _ins_ensure_tables(conn)

                signals  = detect_individual_signals(conn, since)
                clusters = detect_cluster_signals(conn, since)
                save_signals(conn, signals, clusters, dry_run=False)

                # Fire Telegram alerts for genuinely new signals
                for sig in signals:
                    key = (sig["market_id"], sig["trader_address"], sig["trade_timestamp"])
                    if key in alerted_signals:
                        continue
                    alerted_signals.add(key)
                    try:
                        msg = format_signal_alert(sig)
                        await self.telegram._send_message(msg)
                        conn.execute("""
                            UPDATE insider_signals SET alerted = 1
                            WHERE trader_address = ? AND market_id = ? AND trade_timestamp = ?
                        """, (sig["trader_address"], sig["market_id"], sig["trade_timestamp"]))
                        conn.commit()
                        print(f"[INSIDER] Signal alerted: {sig['trader_address'][:10]}... "
                              f"${sig['position_size']:,.0f} on {sig['market_title'][:40]}")
                    except Exception as e:
                        print(f"[INSIDER] Alert send error: {e}")

                for cl in clusters:
                    key = (cl["market_id"], cl["outcome"], cl["window_start"])
                    if key in alerted_clusters:
                        continue
                    alerted_clusters.add(key)
                    try:
                        msg = format_cluster_alert(cl)
                        await self.telegram._send_message(msg)
                        conn.execute("""
                            UPDATE insider_clusters SET alerted = 1
                            WHERE market_id = ? AND outcome = ? AND window_start = ?
                        """, (cl["market_id"], cl["outcome"], cl["window_start"]))
                        conn.commit()
                        print(f"[INSIDER] Cluster alerted: {cl['wallet_count']} wallets "
                              f"${cl['combined_size']:,.0f} on {cl['market_title'][:40]}")
                    except Exception as e:
                        print(f"[INSIDER] Cluster alert send error: {e}")

                conn.close()

                if signals or clusters:
                    print(f"[INSIDER] Scan complete: {len(signals)} individual, {len(clusters)} cluster")

            except Exception as e:
                print(f"[INSIDER] Error in detection loop: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(CHECK_INTERVAL)

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
                    # Filter out launcher stubs by checking memory usage
                    # Real monitoring process: 60+ MB, Launcher stub: 3-4 MB
                    try:
                        memory_mb = proc.memory_info().rss / (1024 * 1024)

                        # Skip launcher stubs (< 10 MB)
                        if memory_mb < 10:
                            print(f"[OBSERVER] Skipping launcher stub: PID={proc.info['pid']} ({memory_mb:.1f} MB)")
                            continue

                        # This is the real monitoring process
                        print(f"[OBSERVER] Found monitoring process: PID={proc.info['pid']} ({memory_mb:.1f} MB)")
                        return proc.info['pid']

                    except Exception:
                        # If can't get memory info, accept the process anyway
                        print(f"[OBSERVER] Found monitoring process: PID={proc.info['pid']}, cmd={' '.join(cmdline[:3])}")
                        return proc.info['pid']

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return None
