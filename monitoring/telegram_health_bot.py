#!/usr/bin/env python3
"""
Telegram Health Bot

Sends health alerts and status reports via Telegram.
Uses existing PredictionAlerts_bot infrastructure.

Alert Types:
- Health warnings (degraded system)
- Error alerts (critical errors)
- Hourly status reports
- Performance issues
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Bot
from telegram.error import TelegramError


class TelegramHealthBot:
    """
    Telegram bot for system health notifications.

    Features:
    - Health warnings
    - Error alerts
    - Hourly status reports
    - Formatted messages with emojis
    """

    def __init__(self, token: str, chat_id: str):
        """
        Initialize Telegram health bot.

        Args:
            token: Telegram bot token
            chat_id: Chat ID to send messages to
        """
        self.bot = Bot(token=token)
        self.chat_id = chat_id
        self.last_alert_time = {}  # Rate limiting

    async def send_health_alert(self, health: Dict) -> bool:
        """
        Send health alert for system degradation.

        Args:
            health: Health report dict from HealthChecker

        Returns:
            bool: True if sent successfully
        """
        status = health['status']
        issues = health['issues']
        checks = health['checks']

        # Skip if healthy
        if status == 'healthy':
            return False

        # Rate limit: Don't send same alert type more than once per 10 minutes
        alert_key = f"health_{status}"
        if not self._should_send_alert(alert_key, minutes=10):
            return False

        # Format message
        if status == 'warning':
            emoji = '⚠️'
            title = 'SYSTEM HEALTH WARNING'
        else:
            emoji = '❌'
            title = 'SYSTEM HEALTH CRITICAL'

        message_parts = [
            f"{emoji} {title}",
            ""
        ]

        # Add issues
        if issues:
            message_parts.append("Issues detected:")
            for issue in issues:
                message_parts.append(f"  • {issue}")
            message_parts.append("")

        # Add key metrics
        if checks.get('process', {}).get('pid'):
            message_parts.append(f"Process: {checks['process']['pid']} ({checks['process'].get('name', 'unknown')})")

        if checks.get('memory', {}).get('memory_mb'):
            message_parts.append(f"Memory: {checks['memory']['memory_mb']:.1f} MB")

        if checks.get('activity', {}).get('age_minutes') is not None:
            message_parts.append(f"Last activity: {checks['activity']['age_minutes']}m ago")

        if checks.get('errors', {}).get('error_count') is not None:
            message_parts.append(f"Recent errors: {checks['errors']['error_count']} in last {checks['errors']['time_window_minutes']}m")

        message_parts.append("")
        message_parts.append(f"Status: {status.upper()}")
        message_parts.append(f"Time: {health['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")

        # Add recommended action
        if status == 'critical':
            message_parts.append("")
            message_parts.append("⚠️ Recommended: Check system immediately")

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_error_alert(self, error: Dict) -> bool:
        """
        Send alert for detected error.

        Args:
            error: Error dict from LogMonitor

        Returns:
            bool: True if sent successfully
        """
        # Rate limit: One error alert per 5 minutes
        if not self._should_send_alert('error', minutes=5):
            return False

        error_type = error.get('type', 'unknown')
        severity = error.get('severity', 'error')
        message_text = error.get('message', 'No message')
        timestamp = error.get('timestamp', datetime.now())

        emoji = '❌' if severity == 'critical' else '⚠️'

        message_parts = [
            f"{emoji} ERROR DETECTED",
            "",
            f"Type: {error_type}",
            f"Severity: {severity.upper()}",
            "",
            f"Message:",
            f"{message_text[:500]}...",  # Truncate long messages
            "",
            f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        ]

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_known_issue_alert(self, issue: Dict) -> bool:
        """
        Send alert for known issue detection.

        Args:
            issue: Issue dict from LogMonitor

        Returns:
            bool: True if sent successfully
        """
        issue_type = issue['issue_type']

        # Rate limit: One alert per issue type per 15 minutes
        alert_key = f"issue_{issue_type}"
        if not self._should_send_alert(alert_key, minutes=15):
            return False

        description = issue['description']
        action = issue['action']
        details = issue.get('details', {})
        timestamp = issue.get('timestamp', datetime.now())

        message_parts = [
            "🔧 KNOWN ISSUE DETECTED",
            "",
            f"Issue: {description}",
            f"Type: {issue_type}",
            ""
        ]

        # Add details if present
        if details:
            message_parts.append("Details:")
            for key, value in details.items():
                message_parts.append(f"  • {key}: {value}")
            message_parts.append("")

        message_parts.extend([
            f"Suggested action:",
            f"  {action}",
            "",
            f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        ])

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_hourly_report(self, metrics: Dict) -> bool:
        """
        Send hourly status report.

        Args:
            metrics: Metrics dict with system stats

        Returns:
            bool: True if sent successfully
        """
        health_status = metrics.get('health_status', 'unknown')
        uptime_hours = metrics.get('uptime_hours', 0)
        memory_mb = metrics.get('memory_mb', 0)

        # System status emoji
        if health_status == 'healthy':
            status_emoji = '✅'
            status_text = 'HEALTHY'
        elif health_status == 'warning':
            status_emoji = '⚠️'
            status_text = 'WARNING'
        else:
            status_emoji = '❌'
            status_text = 'CRITICAL'

        message_parts = [
            "📊 HOURLY STATUS REPORT",
            "",
            f"System: {status_text} {status_emoji}",
            f"Uptime: {uptime_hours:.1f}h",
            f"Memory: {memory_mb:.0f} MB",
            ""
        ]

        # Activity metrics
        if 'activity' in metrics:
            activity = metrics['activity']
            message_parts.append("Activity (last hour):")
            if 'trades_checked' in activity:
                message_parts.append(f"  • Trades checked: {activity['trades_checked']}")
            if 'markets_scanned' in activity:
                message_parts.append(f"  • Markets scanned: {activity['markets_scanned']}")
            if 'elo_updates' in activity:
                message_parts.append(f"  • ELO updates: {activity['elo_updates']}")
            if 'api_calls' in activity:
                message_parts.append(f"  • API calls: {activity['api_calls']}")
            message_parts.append("")

        # Error summary
        error_count = metrics.get('error_count', 0)
        if error_count > 0:
            message_parts.append(f"Errors: {error_count} (review logs)")
        else:
            message_parts.append("Errors: None ✅")

        message_parts.append("")

        # Performance
        performance = metrics.get('performance', 'unknown')
        perf_emoji = '✅' if performance == 'good' else '⚠️'
        message_parts.append(f"Performance: {performance.upper()} {perf_emoji}")

        # Next report time
        next_hour = (datetime.now().hour + 1) % 24
        message_parts.append(f"Next report: {next_hour:02d}:00")

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_startup_notification(self) -> bool:
        """
        Send notification when observer starts.

        Returns:
            bool: True if sent successfully
        """
        message_parts = [
            "🚀 SYSTEM OBSERVER STARTED",
            "",
            "Health monitoring is now active.",
            "Will send alerts for:",
            "  • System health issues",
            "  • Critical errors",
            "  • Known problems",
            "  • Hourly status reports",
            "",
            f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ]

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_shutdown_notification(self) -> bool:
        """
        Send notification when observer stops.

        Returns:
            bool: True if sent successfully
        """
        message_parts = [
            "🛑 SYSTEM OBSERVER STOPPED",
            "",
            "Health monitoring has been stopped.",
            "",
            f"Stopped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ]

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    def _should_send_alert(self, alert_key: str, minutes: int = 10) -> bool:
        """
        Check if alert should be sent (rate limiting).

        Args:
            alert_key: Unique key for this alert type
            minutes: Minimum minutes between alerts of this type

        Returns:
            bool: True if should send
        """
        now = datetime.now()

        if alert_key in self.last_alert_time:
            time_since_last = (now - self.last_alert_time[alert_key]).total_seconds() / 60
            if time_since_last < minutes:
                return False

        self.last_alert_time[alert_key] = now
        return True

    async def _send_message(self, message: str) -> bool:
        """
        Send message via Telegram.

        Args:
            message: Message text

        Returns:
            bool: True if sent successfully
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=None  # Plain text, emojis work fine
            )
            return True

        except TelegramError as e:
            print(f"[TELEGRAM] Error sending message: {e}")
            return False

        except Exception as e:
            print(f"[TELEGRAM] Unexpected error: {e}")
            return False
