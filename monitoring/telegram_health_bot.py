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

# Import error parsing for detailed alerts
try:
    from .error_parser import ErrorDetail
    from .error_classifier import ErrorClassifier
except ImportError:
    # Fallback if imports fail
    ErrorDetail = None
    ErrorClassifier = None


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

        # Initialize error classifier for detailed alerts
        self.error_classifier = ErrorClassifier() if ErrorClassifier else None

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
        Send hourly status report with detailed error summary.

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

        # Enhanced error summary with details
        error_count = metrics.get('error_count', 0)
        error_details = metrics.get('error_details', {})

        if error_count > 0:
            message_parts.append(f"⚠️ Errors: {error_count} in last hour")

            # Show error breakdown by type if available
            if error_details.get('by_type'):
                message_parts.append("  By type:")
                for error_type, count in list(error_details['by_type'].items())[:3]:
                    message_parts.append(f"    • {error_type}: {count}")

            # Show top error if available
            if error_details.get('latest_error'):
                latest = error_details['latest_error']
                message_parts.append(f"  Latest: {latest.get('error_type', 'Unknown')} at {latest.get('timestamp', 'N/A')}")

            # Show if [Errno 22] detected
            if error_details.get('errno_22_count', 0) > 0:
                message_parts.append(f"  🔴 [Errno 22]: {error_details['errno_22_count']} occurrences")
                message_parts.append("    (Console encoding errors - check logs)")

        else:
            message_parts.append("Errors: None ✅")

        message_parts.append("")

        # Monitoring Activity Status (FREEZE DETECTION)
        if 'monitoring_activity' in metrics:
            mon_activity = metrics['monitoring_activity']
            minutes_since = mon_activity.get('minutes_since_activity', 999)

            # Detect if monitoring is frozen (> 240 min = 4 hours silence)
            if minutes_since > 240:
                message_parts.append("🔴 MONITORING FROZEN DETECTED")
                message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
                if mon_activity.get('last_activity'):
                    message_parts.append(f"  • Time: {mon_activity['last_activity'].strftime('%H:%M:%S')}")
                message_parts.append("  • ACTION: Restart monitoring system")
                message_parts.append("")
            elif minutes_since > 180:
                # Warning: approaching freeze threshold
                message_parts.append("⚠️ Monitoring Delayed")
                message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
                message_parts.append("")
            else:
                # Healthy
                message_parts.append(f"✅ Monitoring Active ({minutes_since:.0f}m ago)")
                message_parts.append("")

        # Background Worker Health
        if 'worker_health' in metrics:
            worker = metrics['worker_health']
            status = worker.get('status', 'UNKNOWN')
            coverage = worker.get('coverage_percent', 0)
            never_updated = worker.get('never_updated', 0)

            if status == 'HEALTHY':
                status_emoji = '✅'
            elif status == 'WORKING' or status == 'STARTING':
                status_emoji = '⚙️'
            else:
                status_emoji = '⚠️'

            message_parts.append(f"🔧 Background P&L Worker: {status_emoji}")
            message_parts.append(f"  • Status: {status}")
            message_parts.append(f"  • Coverage: {coverage:.1f}%")

            if never_updated > 0:
                message_parts.append(f"  • Pending: {never_updated} traders")
            else:
                message_parts.append(f"  • All traders up-to-date!")

            message_parts.append("")

        # P&L Stats
        if 'pnl_stats' in metrics:
            pnl_stats = metrics['pnl_stats']
            traders_with_real_pnl = pnl_stats.get('traders_with_real_pnl', 0)
            closed_positions_calculated = pnl_stats.get('closed_positions_calculated', 0)
            synthetic_closes = pnl_stats.get('synthetic_closes', 0)
            worker_backlog = pnl_stats.get('worker_backlog', 0)

            message_parts.append(f"💰 P&L Coverage:")
            message_parts.append(f"  • Traders with real closed P&L: {traders_with_real_pnl}")
            message_parts.append(f"  • Closed positions calculated: {closed_positions_calculated}")
            message_parts.append(f"  • Of which synthetic (resolution): {synthetic_closes}")
            message_parts.append(f"  • Worker backlog (unvisited): {worker_backlog}")
            message_parts.append("")

        # Top 5 Traders Mini Leaderboard
        if 'top_traders' in metrics and metrics['top_traders']:
            message_parts.append("🏆 Top 5 Traders:")
            for i, trader in enumerate(metrics['top_traders'], 1):
                addr = trader['address']
                addr_short = addr[:6] + "..." + addr[-4:]
                elo = trader['elo']
                roi = trader.get('roi')
                roi_str = f"{roi:+.1f}%" if roi is not None else "Calculating..."

                message_parts.append(f"{i}. `{addr_short}` ELO: {elo:.0f} ROI: {roi_str}")
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

    async def send_daily_report(self, metrics: Dict) -> bool:
        """
        Send comprehensive end-of-day report.

        Args:
            metrics: Daily metrics dict from system_observer

        Returns:
            bool: True if sent successfully
        """
        from datetime import datetime

        # Header
        today = datetime.now().strftime("%Y-%m-%d")
        message_parts = [
            f"📊 **DAILY REPORT** - {today}",
            "=" * 50,
            ""
        ]

        # Check for errors
        if 'error' in metrics:
            message_parts.append(f"❌ Error generating report: {metrics['error']}")
            return await self._send_message('\n'.join(message_parts))

        # 1. Top 10 Traders
        message_parts.append("🏆 **TOP 10 TRADERS**")
        message_parts.append("-" * 50)

        if metrics.get('top_10_traders'):
            for i, trader in enumerate(metrics['top_10_traders'], 1):
                message_parts.append(
                    f"{i:2d}. `{trader['address'][:10]}...` "
                    f"ELO: {trader['elo']:.0f} | "
                    f"ROI: {trader['roi']:+.1f}% | "
                    f"Trades: {trader['total_trades']}"
                )
        else:
            message_parts.append("  No data available")

        # 2. Biggest Winners (24h)
        message_parts.append("")
        message_parts.append("🎉 **BIGGEST WINNERS (24h)**")
        message_parts.append("-" * 50)

        if metrics.get('daily_winners'):
            for winner in metrics['daily_winners']:
                message_parts.append(
                    f"• `{winner['address'][:10]}...` "
                    f"P&L: ${winner['pnl_24h']:+.2f} | "
                    f"ELO: {winner['elo']:.0f}"
                )
        else:
            message_parts.append("  No profitable positions closed today")

        # 3. Biggest Losers (24h)
        message_parts.append("")
        message_parts.append("📉 **BIGGEST LOSERS (24h)**")
        message_parts.append("-" * 50)

        if metrics.get('daily_losers'):
            for loser in metrics['daily_losers']:
                message_parts.append(
                    f"• `{loser['address'][:10]}...` "
                    f"P&L: ${loser['pnl_24h']:+.2f} | "
                    f"ELO: {loser['elo']:.0f}"
                )
        else:
            message_parts.append("  No losing positions closed today")

        # 4. Best Trade of the Day
        message_parts.append("")
        message_parts.append("⭐ **BEST TRADE OF THE DAY**")
        message_parts.append("-" * 50)

        if metrics.get('best_trade'):
            best = metrics['best_trade']
            message_parts.append(f"Trader: `{best['trader'][:10]}...`")
            market_title = best['market_title'][:50]
            if len(best['market_title']) > 50:
                market_title += "..."
            message_parts.append(f"Market: \"{market_title}\"")
            message_parts.append(f"Outcome: {best['outcome']}")
            message_parts.append(
                f"ROI: {best['roi']:.1f}% | P&L: ${best['pnl']:+.2f}"
            )
        else:
            message_parts.append("  No closed positions today")

        # 5. System Statistics (24h)
        message_parts.append("")
        message_parts.append("📊 **SYSTEM STATISTICS (24h)**")
        message_parts.append("-" * 50)
        message_parts.append(f"• Trades processed: {metrics.get('trades_24h', 0):,}")
        message_parts.append(f"• Active traders: {metrics.get('active_traders_24h', 0):,}")
        message_parts.append(f"• Markets resolved: {metrics.get('markets_resolved_24h', 0)}")
        message_parts.append(f"• Total P&L change: ${metrics.get('total_pnl_24h', 0):+,.2f}")
        message_parts.append(f"• Worker coverage: {metrics.get('worker_coverage', 0):.1f}%")

        # Footer
        message_parts.append("")
        message_parts.append("=" * 50)
        message_parts.append("📈 See you tomorrow with another daily report!")

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_weekly_report(self, metrics: Dict) -> bool:
        """
        Send comprehensive weekly performance summary.

        Args:
            metrics: Weekly metrics dict from system_observer

        Returns:
            bool: True if sent successfully
        """
        from datetime import datetime, timedelta

        # Header
        today = datetime.now()
        week_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        week_end = today.strftime("%Y-%m-%d")

        message_parts = [
            f"📊 **WEEKLY PERFORMANCE SUMMARY**",
            f"Week: {week_start} to {week_end}",
            "=" * 50,
            ""
        ]

        # Check for errors
        if 'error' in metrics:
            message_parts.append(f"❌ Error generating report: {metrics['error']}")
            return await self._send_message('\n'.join(message_parts))

        # 1. Top 20 Traders (Extended Leaderboard)
        message_parts.append("🏆 **TOP 20 TRADERS**")
        message_parts.append("-" * 50)

        if metrics.get('top_20_traders'):
            for i, trader in enumerate(metrics['top_20_traders'], 1):
                message_parts.append(
                    f"{i:2d}. `{trader['address'][:10]}...` "
                    f"ELO: {trader['elo']:.0f} | "
                    f"ROI: {trader['roi']:+.1f}%"
                )

                # Add separator every 5 for readability
                if i % 5 == 0 and i < 20:
                    message_parts.append("")
        else:
            message_parts.append("  No data available")

        # 2. Most Active Traders (7 days)
        message_parts.append("")
        message_parts.append("🔥 **MOST ACTIVE TRADERS (7 days)**")
        message_parts.append("-" * 50)

        if metrics.get('most_active_7d'):
            for trader in metrics['most_active_7d'][:5]:
                message_parts.append(
                    f"• `{trader['address'][:10]}...` "
                    f"{trader['trades_7d']} trades | "
                    f"ELO: {trader['elo']:.0f}"
                )
        else:
            message_parts.append("  No active traders this week")

        # 3. Best Trades of the Week (Top 5)
        message_parts.append("")
        message_parts.append("⭐ **BEST TRADES OF THE WEEK**")
        message_parts.append("-" * 50)

        if metrics.get('best_trades_7d'):
            for i, trade in enumerate(metrics['best_trades_7d'][:5], 1):
                message_parts.append(f"{i}. `{trade['trader'][:10]}...` (ELO: {trade['trader_elo']:.0f})")
                market_title = trade['market_title'][:45]
                if len(trade['market_title']) > 45:
                    market_title += "..."
                message_parts.append(f"   Market: \"{market_title}\"")
                message_parts.append(f"   ROI: {trade['roi']:.1f}% | P&L: ${trade['pnl']:+.2f}")
                message_parts.append("")
        else:
            message_parts.append("  No closed positions this week")

        # 4. P&L Leaders (7 days)
        message_parts.append("💰 **P&L LEADERS (7 days)**")
        message_parts.append("-" * 50)

        if metrics.get('pnl_leaders_7d'):
            for leader in metrics['pnl_leaders_7d'][:5]:
                message_parts.append(
                    f"• `{leader['address'][:10]}...` "
                    f"${leader['pnl_7d']:+.2f} "
                    f"({leader['trades_closed']} positions)"
                )
        else:
            message_parts.append("  No profitable positions this week")

        # 5. Win Rate Leaders (7 days)
        message_parts.append("")
        message_parts.append("🎯 **WIN RATE LEADERS (7 days)**")
        message_parts.append("-" * 50)

        if metrics.get('win_rate_leaders_7d'):
            for leader in metrics['win_rate_leaders_7d'][:5]:
                message_parts.append(
                    f"• `{leader['address'][:10]}...` "
                    f"{leader['win_rate']:.1f}% "
                    f"({leader['wins']}/{leader['total']} wins)"
                )
        else:
            message_parts.append("  Insufficient data (need 5+ trades)")

        # 6. Most Active Markets (7 days)
        message_parts.append("")
        message_parts.append("📈 **MOST ACTIVE MARKETS (7 days)**")
        message_parts.append("-" * 50)

        if metrics.get('active_markets_7d'):
            for i, market in enumerate(metrics['active_markets_7d'][:5], 1):
                market_title = market['title'][:40]
                if len(market['title']) > 40:
                    market_title += "..."
                message_parts.append(f"{i}. \"{market_title}\"")
                message_parts.append(
                    f"   {market['total_trades']} trades | "
                    f"{market['unique_traders']} traders | "
                    f"Avg: ${market['avg_price']:.3f}"
                )
                message_parts.append("")
        else:
            message_parts.append("  No active markets this week")

        # 7. Markets Resolved (7 days)
        message_parts.append("✅ **MARKETS RESOLVED (7 days)**")
        message_parts.append("-" * 50)

        if metrics.get('markets_resolved_7d'):
            message_parts.append(f"Total resolved: {len(metrics['markets_resolved_7d'])}")
            message_parts.append("")
            for market in metrics['markets_resolved_7d'][:3]:
                market_title = market['title'][:40]
                if len(market['title']) > 40:
                    market_title += "..."
                message_parts.append(f"• \"{market_title}\"")
                message_parts.append(f"  Outcome: {market['outcome']}")
                message_parts.append("")
        else:
            message_parts.append("  No markets resolved this week")

        # 8. System Performance (7 days)
        message_parts.append("📊 **SYSTEM PERFORMANCE (7 days)**")
        message_parts.append("-" * 50)
        message_parts.append(f"• Trades processed: {metrics.get('trades_7d', 0):,}")
        message_parts.append(f"• Active traders: {metrics.get('active_traders_7d', 0):,}")
        message_parts.append(f"• Markets resolved: {metrics.get('markets_resolved_count', 0)}")
        message_parts.append(f"• Total P&L: ${metrics.get('total_pnl_7d', 0):+,.2f}")
        message_parts.append(f"• Worker coverage: {metrics.get('worker_coverage', 0):.1f}%")
        message_parts.append(f"• Total traders tracked: {metrics.get('total_traders', 0):,}")

        # Footer
        message_parts.append("")
        message_parts.append("=" * 50)
        message_parts.append("📈 Outstanding work this week!")
        message_parts.append("See you next Sunday for another weekly summary.")

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_analysis_summary(self, results: Dict) -> bool:
        """
        Send comprehensive analysis summary.

        Args:
            results: Analysis results dict from system_observer

        Returns:
            bool: True if sent successfully
        """
        from datetime import datetime
        import os

        # Header
        today = datetime.now().strftime("%Y-%m-%d")
        message_parts = [
            "🔬 **COMPREHENSIVE ANALYSIS REPORT**",
            f"Date: {today}",
            "=" * 50,
            ""
        ]

        # Check if analysis succeeded
        if not results.get('success'):
            message_parts.append("❌ Analysis failed")
            message_parts.append("")
            message_parts.append(f"Error: {results.get('error', 'Unknown error')}")
            return await self._send_message('\n'.join(message_parts))

        # Reports generated
        reports = results.get('reports_generated', [])
        message_parts.append(f"📊 **Reports Generated:** {len(reports)}")
        message_parts.append("")

        if reports:
            for report_path in reports:
                report_name = os.path.basename(report_path)
                message_parts.append(f"• {report_name}")
            message_parts.append("")

        # Extract key insights from summary
        summary = results.get('summary', '')

        if summary:
            message_parts.append("📈 **KEY INSIGHTS**")
            message_parts.append("-" * 50)
            message_parts.append("")

            # Parse summary for key sections
            lines = summary.split('\n')

            # Look for section headers and important lines
            in_key_section = False
            key_insights = []

            for line in lines[:50]:  # First 50 lines
                line = line.strip()

                # Detect section headers
                if any(keyword in line.upper() for keyword in [
                    'DATA STATUS', 'ANALYSIS TOOLS', 'KEY FINDINGS',
                    'SUMMARY', 'HIGHLIGHTS', 'TOP TRADERS',
                    'BEST OPPORTUNITIES', 'INSIGHTS', 'PHASE'
                ]):
                    in_key_section = True
                    if line and len(line) < 80:
                        key_insights.append(f"**{line}**")
                    continue

                # Add important lines
                if in_key_section and line:
                    if line.startswith('-') or line.startswith('•') or line.startswith('✓'):
                        key_insights.append(line)
                    elif ':' in line and len(line) < 100:
                        key_insights.append(line)

                # Stop after collecting enough insights
                if len(key_insights) >= 15:
                    break

            if key_insights:
                message_parts.extend(key_insights[:15])
            else:
                # Fallback: show first 500 characters
                message_parts.append(summary[:500])
                if len(summary) > 500:
                    message_parts.append("...")
                    message_parts.append("")
                    message_parts.append("[See full report in /reports directory]")
        else:
            message_parts.append("ℹ️ No summary available")

        # Analysis tools run
        message_parts.append("")
        message_parts.append("🛠️ **ANALYSIS TOOLS**")
        message_parts.append("-" * 50)
        message_parts.append("The following tools were executed:")
        message_parts.append("")
        message_parts.append("1. Trading Behavior Analysis")
        message_parts.append("2. Correlation Matrix")
        message_parts.append("3. Trader Performance Analysis")
        message_parts.append("4. Weighted Consensus System")
        message_parts.append("5. Trader Specialization Analysis")
        message_parts.append("6. Copy Trade Detector")
        message_parts.append("7. Market Confidence Meter")
        message_parts.append("8. Consensus Divergence Detector")

        # Footer
        message_parts.append("")
        message_parts.append("=" * 50)
        message_parts.append("📁 Full reports saved to: `/reports/`")
        message_parts.append("🔄 Next analysis: Tomorrow at 01:00 UTC")

        message = '\n'.join(message_parts)

        return await self._send_message(message)

    async def send_trend_alert(self, trend: Dict) -> bool:
        """
        Send market trend alert.

        Args:
            trend: Trend data dict from system_observer

        Returns:
            bool: True if sent successfully
        """
        shift = trend['consensus_shift']
        direction = "BULLISH" if shift > 0 else "BEARISH"
        emoji = "[UP]" if shift > 0 else "[DOWN]"

        message_parts = []

        # Header
        message_parts.append(f"{emoji} **MARKET TREND ALERT**")
        message_parts.append("=" * 50)
        message_parts.append("")

        # Market info
        title = trend['title']
        if len(title) > 60:
            title = title[:57] + "..."

        message_parts.append(f"**Market:** \"{title}\"")
        message_parts.append("")

        # Trend details
        message_parts.append(f"[FIRE] **STRONG {direction} MOMENTUM**")
        message_parts.append("-" * 50)
        message_parts.append(f"- Consensus shift: {shift:+.1%} (recent)")
        message_parts.append(f"- Direction: {trend['direction']}")
        message_parts.append("")

        # Elite trader consensus
        message_parts.append("[CROWN] **ELITE TRADER CONSENSUS**")
        message_parts.append("-" * 50)
        message_parts.append(f"- Position: {trend['elite_consensus']}")
        message_parts.append(f"- Agreement: {trend['elite_agreement']:.1%}")
        message_parts.append(f"- Elite traders involved: {trend['elite_trader_count']}")

        # Interpretation
        if trend['elite_agreement'] >= 0.70:
            message_parts.append("")
            message_parts.append("[OK] **High elite agreement** - Top traders strongly unified")
        elif trend['elite_agreement'] >= 0.50:
            message_parts.append("")
            message_parts.append("[WARNING] **Moderate agreement** - Some elite trader divergence")

        # Volume spike
        if trend['volume_spike']:
            message_parts.append("")
            message_parts.append("[CHART] **VOLUME SPIKE DETECTED**")
            message_parts.append("-" * 50)
            message_parts.append(f"- Volume multiplier: {trend['volume_multiplier']:.1f}x normal")
            message_parts.append(f"- Recent trades (6h): {trend['recent_trades']:,}")

        # Activity metrics
        message_parts.append("")
        message_parts.append("[STATS] **ACTIVITY METRICS**")
        message_parts.append("-" * 50)
        message_parts.append(f"- Recent trades: {trend['recent_trades']:,}")
        message_parts.append(f"- Elite traders: {trend['elite_trader_count']}")

        # Insight
        message_parts.append("")
        message_parts.append("[LIGHT] **INSIGHT:**")

        if trend['elite_agreement'] >= 0.70 and abs(shift) > 0.25:
            message_parts.append("Strong trend with elite trader convergence. High-confidence signal.")
        elif trend['elite_agreement'] >= 0.70:
            message_parts.append("Elite traders agree, but momentum is moderate. Monitor for further movement.")
        elif abs(shift) > 0.25:
            message_parts.append("Strong momentum but elite traders divided. Trend may be retail-driven.")
        elif trend['volume_spike']:
            message_parts.append("Significant volume spike detected. Market attention increasing.")
        else:
            message_parts.append("Moderate trend with mixed signals. Exercise caution.")

        # Footer
        message_parts.append("")
        message_parts.append("=" * 50)
        message_parts.append(f"Market ID: `{trend['market_id']}`")

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

    async def send_detailed_error_alert(self, error: 'ErrorDetail') -> bool:
        """
        Send detailed error alert with full context and diagnostic info.

        Args:
            error: ErrorDetail object from error parser

        Returns:
            bool: True if sent successfully
        """
        # Rate limit: One detailed error alert per error signature per 10 minutes
        alert_key = f"detailed_{error.signature[:50]}"
        if not self._should_send_alert(alert_key, minutes=10):
            return False

        # Use error classifier to format comprehensive alert
        if self.error_classifier and ErrorDetail:
            classification = self.error_classifier.classify_error(error)
            message = self.error_classifier.format_error_alert(error, classification)
        else:
            # Fallback to basic formatting
            message = self._format_basic_error_alert(error)

        return await self._send_message(message)

    def _format_basic_error_alert(self, error: 'ErrorDetail') -> str:
        """
        Fallback formatting for detailed errors when classifier not available.

        Args:
            error: ErrorDetail object

        Returns:
            Formatted alert string
        """
        message_parts = [
            "🔴 DETAILED ERROR ALERT",
            ""
        ]

        if error.component:
            message_parts.append(f"Component: {error.component}")
        if error.function:
            message_parts.append(f"Function: {error.function}()")
        if error.error_type:
            message_parts.append(f"Error Type: {error.error_type}")

        message_parts.append("")
        message_parts.append(f"Message: {error.message[:300]}")

        if error.stack_trace:
            message_parts.append("")
            message_parts.append("Stack Trace (top 3):")
            for line in error.stack_trace[:3]:
                message_parts.append(f"  {line}")

        message_parts.append("")
        message_parts.append(f"Time: {error.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        if error.occurrences > 1:
            message_parts.append(f"Occurrences: {error.occurrences}")

        return '\n'.join(message_parts)

    async def send_monitoring_freeze_alert(self, diagnostics: Dict) -> bool:
        """
        Send detailed alert when monitoring system is frozen.

        Args:
            diagnostics: Diagnostic data about the freeze

        Returns:
            bool: True if sent successfully
        """
        # Rate limit: One freeze alert per 20 minutes
        if not self._should_send_alert('monitoring_freeze', minutes=20):
            return False

        minutes_since = diagnostics.get('minutes_since_activity', 0)
        last_activity = diagnostics.get('last_activity')
        closed_positions = diagnostics.get('closed_positions', 0)
        traders_with_real_pnl = diagnostics.get('traders_with_real_pnl', 0)

        message_parts = [
            "🔴 MONITORING SYSTEM FROZEN",
            "",
            f"⏰ Last Activity: {minutes_since:.0f} minutes ago"
        ]

        if last_activity:
            message_parts.append(f"   Time: {last_activity.strftime('%Y-%m-%d %H:%M:%S')}")

        message_parts.extend([
            "",
            "📊 Current State:",
            f"  • Closed positions calculated: {closed_positions}",
            f"  • Traders with real closed P&L: {traders_with_real_pnl}"
        ])

        # Likely cause
        message_parts.extend([
            "",
            "🔍 Likely Cause:",
            "  Telegram rate limit causing hang",
            "  (System waits indefinitely on blocked send)"
        ])

        # Recommended fix
        message_parts.extend([
            "",
            "✅ FIX:",
            "  1. Run: scripts\\restart_monitoring_telegram_safe.bat",
            "  2. This version sends NO Telegram messages",
            "  3. System Observer handles all notifications",
            "",
            "💡 Or manually:",
            "  taskkill /F /IM python.exe",
            "  py monitoring/main_telegram_safe.py"
        ])

        message_parts.append("")
        message_parts.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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
