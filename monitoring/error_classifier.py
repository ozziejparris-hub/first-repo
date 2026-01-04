#!/usr/bin/env python3
"""
Error Classifier - Pattern Matching and Known Issues

Classifies errors by:
- Component (ELO, Position, Filter, Database, etc.)
- Severity (critical, high, medium, low)
- Known issues database with suggested fixes
"""

import re
from typing import Dict, Optional, List
from dataclasses import dataclass
from .error_parser import ErrorDetail


@dataclass
class KnownIssue:
    """Definition of a known issue with fix information."""
    name: str
    pattern: re.Pattern
    component: str
    severity: str  # critical, high, medium, low
    description: str
    fix: str
    docs: str


# Known Issues Database
KNOWN_ISSUES = [
    KnownIssue(
        name='elo_method_not_found',
        pattern=re.compile(r"'.*Analyzer' object has no attribute '(\w+)'"),
        component='ELO System',
        severity='high',
        description='Method name mismatch in ELO analyzer',
        fix='Update method call to use correct API. Check analyzer class for available methods.',
        docs='docs/ELO_SYSTEM.md'
    ),
    KnownIssue(
        name='correlation_stuck',
        pattern=re.compile(r'Correlation matrix.*progress:.*99'),
        component='Network Analysis',
        severity='medium',
        description='Correlation matrix calculation stuck at 99%',
        fix='Restart with --skip-correlation flag or reduce trader count',
        docs='docs/ELO_SYSTEM.md#network-analysis'
    ),
    KnownIssue(
        name='database_locked',
        pattern=re.compile(r'database is locked', re.IGNORECASE),
        component='Database',
        severity='high',
        description='Database lock detected - multiple processes accessing database',
        fix='Run: python scripts/diagnose_database_locks.py for details',
        docs='docs/DATABASE_LOCK_DEEP_FIX.md'
    ),
    KnownIssue(
        name='position_matching_failed',
        pattern=re.compile(r'Position matching failed|FIFO.*error', re.IGNORECASE),
        component='Position Tracker',
        severity='high',
        description='FIFO position matching error',
        fix='Check trade data integrity. Run: python scripts/verify_positions.py',
        docs='docs/MONITORING.md#position-tracking'
    ),
    KnownIssue(
        name='ollama_not_running',
        pattern=re.compile(r'Ollama.*not (running|accessible)|Connection.*refused.*11434', re.IGNORECASE),
        component='Market Filter (AI)',
        severity='medium',
        description='Ollama/Mistral AI service not available',
        fix='Start Ollama: ollama serve (or continue with keyword filtering only)',
        docs='docs/SETUP.md#ollama-setup'
    ),
    KnownIssue(
        name='mistral_model_missing',
        pattern=re.compile(r'Mistral model not found', re.IGNORECASE),
        component='Market Filter (AI)',
        severity='medium',
        description='Mistral model not downloaded in Ollama',
        fix='Download model: ollama pull mistral',
        docs='docs/SETUP.md#ollama-setup'
    ),
    KnownIssue(
        name='telegram_unauthorized',
        pattern=re.compile(r'Telegram.*Unauthorized|bot.*token.*invalid', re.IGNORECASE),
        component='Telegram Bot',
        severity='critical',
        description='Invalid Telegram bot token',
        fix='Check TELEGRAM_BOT_TOKEN in .env file. Get token from @BotFather',
        docs='docs/SETUP.md#telegram-setup'
    ),
    KnownIssue(
        name='telegram_chat_id_missing',
        pattern=re.compile(r'TELEGRAM_CHAT_ID.*not.*configured', re.IGNORECASE),
        component='Telegram Bot',
        severity='medium',
        description='Telegram chat ID not configured',
        fix='Run: python scripts/get_telegram_chat_id.py',
        docs='docs/SETUP.md#telegram-setup'
    ),
    KnownIssue(
        name='market_resolution_not_found',
        pattern=re.compile(r'Market resolution.*not found|Resolution.*missing', re.IGNORECASE),
        component='Trade Evaluator',
        severity='low',
        description='Market resolution data not available (market may not be closed)',
        fix='This is normal for open markets. Resolution will be detected when market closes.',
        docs='docs/MONITORING.md#trade-evaluation'
    ),
    KnownIssue(
        name='calibration_no_data',
        pattern=re.compile(r'Calibration.*insufficient.*data|Not enough.*outcome.*data', re.IGNORECASE),
        component='ELO System (Calibration)',
        severity='low',
        description='Insufficient outcome data for calibration analysis',
        fix='Wait for more trades to resolve. Requires 10+ resolved trades.',
        docs='docs/ELO_SYSTEM.md#calibration-analysis'
    ),
    KnownIssue(
        name='api_rate_limit',
        pattern=re.compile(r'429.*Too Many Requests|Rate limit.*exceeded', re.IGNORECASE),
        component='Polymarket API',
        severity='medium',
        description='Polymarket API rate limit exceeded',
        fix='Reduce polling frequency. System will retry automatically.',
        docs='docs/MONITORING.md#api-rate-limits'
    ),
    KnownIssue(
        name='memory_high',
        pattern=re.compile(r'Memory.*high|MemoryError', re.IGNORECASE),
        component='System',
        severity='high',
        description='High memory usage detected',
        fix='Restart monitoring service. Check for memory leaks in long-running processes.',
        docs='docs/TROUBLESHOOTING.md#high-memory-usage'
    ),
]


# Component mapping for error categorization
COMPONENT_KEYWORDS = {
    'ELO System': ['elo', 'unified_elo', 'calibration', 'behavioral', 'risk_adjusted', 'network', 'contrarian', 'composite'],
    'Position Tracker': ['position', 'fifo', 'pnl', 'p&l'],
    'Market Filter': ['market_filter', 'keyword', 'ai', 'mistral', 'ollama'],
    'Trade Evaluator': ['trade_evaluator', 'resolution', 'outcome'],
    'Database': ['database', 'sqlite', 'sql', 'wal'],
    'Telegram Bot': ['telegram', 'bot', 'notification'],
    'Polymarket API': ['polymarket', 'api', 'clob'],
    'System Observer': ['observer', 'health', 'monitoring'],
}


class ErrorClassifier:
    """Classify errors and match against known issues."""

    def __init__(self):
        """Initialize classifier."""
        self.known_issues = KNOWN_ISSUES

    def classify_error(self, error: ErrorDetail) -> Dict:
        """
        Classify an error and check for known issues.

        Args:
            error: Error to classify

        Returns:
            Classification dict with component, severity, known issue match
        """
        classification = {
            'component': error.component or self._detect_component(error),
            'severity': self._determine_severity(error),
            'known_issue': None,
            'suggested_fix': None,
            'relevant_docs': None
        }

        # Check against known issues
        known_issue = self._match_known_issue(error)
        if known_issue:
            classification['known_issue'] = known_issue.name
            classification['component'] = known_issue.component
            classification['severity'] = known_issue.severity
            classification['suggested_fix'] = known_issue.fix
            classification['relevant_docs'] = known_issue.docs

        return classification

    def _detect_component(self, error: ErrorDetail) -> str:
        """
        Detect component from error details.

        Args:
            error: Error to analyze

        Returns:
            Component name
        """
        # Check component field
        if error.component:
            for component, keywords in COMPONENT_KEYWORDS.items():
                if any(kw in error.component.lower() for kw in keywords):
                    return component

        # Check message
        message_lower = error.message.lower()
        for component, keywords in COMPONENT_KEYWORDS.items():
            if any(kw in message_lower for kw in keywords):
                return component

        # Check stack trace
        for trace_line in error.stack_trace:
            trace_lower = trace_line.lower()
            for component, keywords in COMPONENT_KEYWORDS.items():
                if any(kw in trace_lower for kw in keywords):
                    return component

        return 'Unknown'

    def _determine_severity(self, error: ErrorDetail) -> str:
        """
        Determine error severity.

        Args:
            error: Error to analyze

        Returns:
            Severity level: critical, high, medium, low
        """
        # CRITICAL level logs are always critical
        if error.level == 'CRITICAL':
            return 'critical'

        # Check for critical keywords
        critical_keywords = ['fatal', 'crash', 'shutdown', 'unauthorized', 'token']
        message_lower = error.message.lower()

        if any(kw in message_lower for kw in critical_keywords):
            return 'critical'

        # Database errors are usually high severity
        if 'database' in message_lower or 'sqlite' in message_lower:
            return 'high'

        # Telegram errors prevent notifications
        if 'telegram' in message_lower:
            return 'high'

        # ERROR level defaults to medium
        if error.level == 'ERROR':
            return 'medium'

        # WARNING level defaults to low
        return 'low'

    def _match_known_issue(self, error: ErrorDetail) -> Optional[KnownIssue]:
        """
        Match error against known issues database.

        Args:
            error: Error to match

        Returns:
            KnownIssue if matched, None otherwise
        """
        # Combine all searchable text
        searchable_text = ' '.join([
            error.message,
            error.component or '',
            ' '.join(error.stack_trace)
        ])

        # Check each known issue pattern
        for known_issue in self.known_issues:
            if known_issue.pattern.search(searchable_text):
                return known_issue

        return None

    def get_component_emoji(self, component: str) -> str:
        """
        Get emoji for component.

        Args:
            component: Component name

        Returns:
            Emoji string
        """
        emoji_map = {
            'ELO System': '🎯',
            'Position Tracker': '💰',
            'Market Filter': '🔍',
            'Trade Evaluator': '📊',
            'Database': '💾',
            'Telegram Bot': '📱',
            'Polymarket API': '🌐',
            'System Observer': '👁️',
            'Unknown': '❓',
        }
        return emoji_map.get(component, '⚙️')

    def get_severity_emoji(self, severity: str) -> str:
        """
        Get emoji for severity.

        Args:
            severity: Severity level

        Returns:
            Emoji string
        """
        emoji_map = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🟢',
        }
        return emoji_map.get(severity, '⚪')

    def format_error_alert(self, error: ErrorDetail, classification: Dict) -> str:
        """
        Format error as detailed alert message.

        Args:
            error: Error details
            classification: Classification results

        Returns:
            Formatted alert string
        """
        component = classification['component']
        severity = classification['severity']

        # Build alert message
        lines = []

        # Header with severity and component
        severity_emoji = self.get_severity_emoji(severity)
        component_emoji = self.get_component_emoji(component)

        if classification['known_issue']:
            lines.append(f"{severity_emoji} KNOWN ISSUE: {component} {component_emoji}")
        else:
            lines.append(f"{severity_emoji} COMPONENT ERROR: {component} {component_emoji}")

        lines.append("")

        # Component and function
        if error.component:
            lines.append(f"Component: {error.component}")
        if error.function:
            lines.append(f"Function: {error.function}()")

        # Trader/market context
        if error.context.get('trader_address'):
            lines.append(f"Trader: {error.context['trader_address'][:10]}...{error.context['trader_address'][-8:]}")
        if error.context.get('market_id'):
            lines.append(f"Market: {error.context['market_id']}")

        lines.append("")

        # Error details
        if error.error_type:
            lines.append(f"Error Type: {error.error_type}")

        # Message (truncate if too long)
        message = error.message
        if len(message) > 200:
            message = message[:200] + "..."
        lines.append(f"Message: {message}")

        # Stack trace (top 3 lines)
        if error.stack_trace:
            lines.append("")
            lines.append("Stack Trace:")
            for trace_line in error.stack_trace[:3]:
                lines.append(f"  {trace_line}")
            if len(error.stack_trace) > 3:
                lines.append(f"  ... and {len(error.stack_trace) - 3} more")

        lines.append("")

        # Occurrence info
        lines.append(f"First Occurrence: {error.first_seen.strftime('%H:%M:%S')}")
        if error.occurrences > 1:
            lines.append(f"Occurrences: {error.occurrences} times")

        # Suggested fix
        if classification['suggested_fix']:
            lines.append("")
            lines.append(f"💡 Suggested Fix:")
            lines.append(f"  {classification['suggested_fix']}")

        # Documentation link
        if classification['relevant_docs']:
            lines.append("")
            lines.append(f"📚 Docs: {classification['relevant_docs']}")

        return '\n'.join(lines)

    def get_all_known_issues(self) -> List[KnownIssue]:
        """Get list of all known issues."""
        return self.known_issues

    def get_known_issue_by_name(self, name: str) -> Optional[KnownIssue]:
        """Get known issue by name."""
        for issue in self.known_issues:
            if issue.name == name:
                return issue
        return None
