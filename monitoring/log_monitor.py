#!/usr/bin/env python3
"""
Real-time Log Monitor

Monitors log files in real-time (like tail -f) and detects:
- Error patterns
- Stuck processes
- Performance issues
- Known issues (correlation matrix, ELO failures, etc.)

Provides error detection and analysis capabilities with detailed context parsing.
"""

import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Generator
from collections import deque, defaultdict

# Import our enhanced error analysis modules
from .error_parser import ErrorParser, ErrorDetail
from .error_classifier import ErrorClassifier


class LogMonitor:
    """
    Real-time log file monitor with error pattern detection.

    Features:
    - Tail log files (like tail -f)
    - Detect error patterns
    - Track error rates
    - Identify known issues (stuck processes, etc.)
    """

    def __init__(self, log_path: str = 'logs/monitoring.log'):
        """
        Initialize log monitor.

        Args:
            log_path: Path to log file to monitor
        """
        self.log_path = log_path
        self.last_position = 0
        # Start at end of existing log so startup doesn't replay old ERROR lines
        if os.path.exists(self.log_path):
            self.last_position = os.path.getsize(self.log_path)
        self.error_history = deque(maxlen=1000)  # Last 1000 errors
        self.pattern_counts = defaultdict(int)

        # Initialize enhanced error analysis
        self.error_parser = ErrorParser()
        self.error_classifier = ErrorClassifier()

        # Error patterns to detect
        self.error_patterns = {
            'generic_error': re.compile(r'ERROR.*', re.IGNORECASE),
            'critical': re.compile(r'CRITICAL.*', re.IGNORECASE),
            'traceback': re.compile(r'Traceback.*'),
            'stuck_process': re.compile(r'stuck.*', re.IGNORECASE),
            'timeout': re.compile(r'timeout.*', re.IGNORECASE),
            'database_locked': re.compile(r'database is locked', re.IGNORECASE),
            'api_error': re.compile(r'API.*error', re.IGNORECASE),
        }

        # Known issue patterns
        self.known_issues = {
            'correlation_stuck': {
                'pattern': re.compile(r'CORRELATION MATRIX Progress: (\d+)/(\d+) pairs'),
                'description': 'Correlation matrix calculation stuck',
                'action': 'Consider restarting with --skip-correlation'
            },
            'no_resolutions': {
                'pattern': re.compile(r'Found 0 resolved markets'),
                'description': 'No market resolutions found',
                'action': 'Check Polymarket API availability'
            },
            'elo_attribute_error': {
                'pattern': re.compile(r"'RiskAdjustedAnalyzer' object has no attribute"),
                'description': 'ELO calculation attribute error',
                'action': 'Check ELO system implementation'
            },
            'elo_error': {
                'pattern': re.compile(r'ERROR.*ELO.*', re.IGNORECASE),
                'description': 'ELO calculation error',
                'action': 'Review ELO system logs'
            }
        }

        # Track stuck process detection
        self.stuck_detection = {}

    def tail_logs(self, follow: bool = True) -> Generator[str, None, None]:
        """
        Tail log file like 'tail -f'.

        Args:
            follow: If True, continuously follow file (like -f flag)

        Yields:
            str: New log lines as they appear
        """
        if not os.path.exists(self.log_path):
            return

        with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Seek to last known position
            if self.last_position > 0:
                f.seek(self.last_position)

            while True:
                line = f.readline()

                if line:
                    self.last_position = f.tell()
                    yield line.rstrip('\n')
                else:
                    if not follow:
                        break
                    # Wait for new content
                    time.sleep(0.5)

    def detect_errors(self, line: str) -> Optional[Dict]:
        """
        Detect if log line contains an error.

        Args:
            line: Log line to analyze

        Returns:
            dict if error detected, None otherwise:
            {
                'timestamp': datetime,
                'line': str,
                'type': str,
                'message': str,
                'severity': 'error' | 'critical'
            }
        """
        # Check error patterns
        for pattern_name, pattern in self.error_patterns.items():
            if pattern.search(line):
                # Extract timestamp if present
                timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                timestamp = None
                if timestamp_match:
                    try:
                        timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
                    except:
                        timestamp = datetime.now()
                else:
                    timestamp = datetime.now()

                # Determine severity
                severity = 'critical' if 'CRITICAL' in line or pattern_name == 'critical' else 'error'

                error_info = {
                    'timestamp': timestamp,
                    'line': line,
                    'type': pattern_name,
                    'message': line,
                    'severity': severity
                }

                # Add to history
                self.error_history.append(error_info)
                self.pattern_counts[pattern_name] += 1

                return error_info

        return None

    def detect_known_issues(self, line: str) -> Optional[Dict]:
        """
        Detect known issues in log line.

        Args:
            line: Log line to analyze

        Returns:
            dict if known issue detected:
            {
                'issue_type': str,
                'description': str,
                'action': str,
                'details': dict,
                'timestamp': datetime
            }
        """
        for issue_name, issue_config in self.known_issues.items():
            match = issue_config['pattern'].search(line)

            if match:
                # Handle special cases
                details = {}

                if issue_name == 'correlation_stuck':
                    # Extract progress
                    current = int(match.group(1))
                    total = int(match.group(2))
                    progress_pct = (current / total * 100) if total > 0 else 0

                    # Check if stuck (same progress repeated)
                    key = f'correlation_{current}'
                    if key not in self.stuck_detection:
                        self.stuck_detection[key] = {
                            'first_seen': datetime.now(),
                            'count': 1
                        }
                    else:
                        self.stuck_detection[key]['count'] += 1

                    # If seen 3+ times, it's stuck
                    if self.stuck_detection[key]['count'] >= 3:
                        details = {
                            'progress': f'{current}/{total}',
                            'progress_pct': f'{progress_pct:.1f}%',
                            'stuck_count': self.stuck_detection[key]['count']
                        }
                    else:
                        # Not stuck yet
                        return None

                return {
                    'issue_type': issue_name,
                    'description': issue_config['description'],
                    'action': issue_config['action'],
                    'details': details,
                    'timestamp': datetime.now()
                }

        return None

    def count_error_rate(self, minutes: int = 10) -> int:
        """
        Count errors in last N minutes.

        Args:
            minutes: Time window

        Returns:
            int: Number of errors
        """
        if not self.error_history:
            return 0

        cutoff = datetime.now() - timedelta(minutes=minutes)
        count = 0

        for error in self.error_history:
            if error['timestamp'] >= cutoff:
                count += 1

        return count

    def get_error_summary(self, minutes: int = 60) -> Dict:
        """
        Get error summary for last N minutes.

        Args:
            minutes: Time window

        Returns:
            dict: {
                'total_errors': int,
                'by_type': dict,
                'recent_errors': List[dict],
                'errors_per_hour': float
            }
        """
        if not self.error_history:
            return {
                'total_errors': 0,
                'by_type': {},
                'recent_errors': [],
                'errors_per_hour': 0
            }

        cutoff = datetime.now() - timedelta(minutes=minutes)
        recent_errors = []
        by_type = defaultdict(int)

        for error in self.error_history:
            if error['timestamp'] >= cutoff:
                recent_errors.append(error)
                by_type[error['type']] += 1

        errors_per_hour = (len(recent_errors) / minutes) * 60

        return {
            'total_errors': len(recent_errors),
            'by_type': dict(by_type),
            'recent_errors': recent_errors[-10:],  # Last 10 errors
            'errors_per_hour': errors_per_hour
        }

    def get_last_errors(self, count: int = 5) -> List[Dict]:
        """
        Get last N errors.

        Args:
            count: Number of errors to return

        Returns:
            List of error dicts
        """
        if not self.error_history:
            return []

        return list(self.error_history)[-count:]

    def analyze_log_health(self) -> Dict:
        """
        Analyze overall log health.

        Returns:
            dict: {
                'status': 'healthy' | 'warning' | 'critical',
                'error_rate': float,
                'recent_errors': int,
                'known_issues': List[dict],
                'message': str
            }
        """
        recent_errors = self.count_error_rate(minutes=10)
        error_rate = (recent_errors / 10) * 60  # errors per hour

        # Check for known issues in recent errors
        known_issues_found = []
        for error in self.get_last_errors(20):
            issue = self.detect_known_issues(error['line'])
            if issue and issue not in known_issues_found:
                known_issues_found.append(issue)

        # Determine status
        if recent_errors == 0:
            status = 'healthy'
            message = 'No recent errors'
        elif recent_errors < 5:
            status = 'healthy'
            message = f'{recent_errors} errors in last 10m (normal)'
        elif recent_errors < 15:
            status = 'warning'
            message = f'{recent_errors} errors in last 10m (elevated)'
        else:
            status = 'critical'
            message = f'{recent_errors} errors in last 10m (high rate)'

        # Critical if known issues detected
        if known_issues_found:
            status = 'critical'
            message = f'Known issues detected: {len(known_issues_found)}'

        return {
            'status': status,
            'error_rate': error_rate,
            'recent_errors': recent_errors,
            'known_issues': known_issues_found,
            'message': message
        }

    def parse_detailed_error(self, line: str) -> Optional[ErrorDetail]:
        """
        Parse log line with full context extraction.

        Args:
            line: Log line to parse

        Returns:
            ErrorDetail if error found, None otherwise
        """
        error = self.error_parser.parse_log_line(line)
        if error:
            # Add to parser's history for grouping
            self.error_parser.add_error(error)
        return error

    def get_detailed_error_summary(self, minutes: int = 60) -> Dict:
        """
        Get detailed error summary with component breakdown.

        Args:
            minutes: Time window in minutes

        Returns:
            Detailed summary dict
        """
        # Get summary from error parser
        summary = self.error_parser.get_error_summary(minutes)

        # Add classification for top errors
        classified_errors = []
        for sig, error_data in summary.get('top_errors', []):
            # Reconstruct ErrorDetail for classification
            error = ErrorDetail(
                timestamp=error_data['first_seen'],
                level='ERROR',
                component=error_data['component'],
                function=error_data['function'],
                error_type=error_data['error_type'],
                message=error_data['message']
            )

            classification = self.error_classifier.classify_error(error)
            classified_errors.append({
                'error': error_data,
                'classification': classification
            })

        summary['classified_errors'] = classified_errors
        return summary

    def get_component_health(self, minutes: int = 60) -> Dict:
        """
        Get health status by component.

        Args:
            minutes: Time window in minutes

        Returns:
            Dict mapping component to health status
        """
        errors_by_component = self.error_parser.get_errors_by_component(minutes)

        component_health = {}
        for component, errors in errors_by_component.items():
            error_count = len(errors)

            # Determine health status
            if error_count == 0:
                status = 'healthy'
            elif error_count < 3:
                status = 'warning'
            else:
                status = 'critical'

            component_health[component] = {
                'status': status,
                'error_count': error_count,
                'errors': errors[:5]  # Top 5 errors
            }

        return component_health

    def get_formatted_error_alerts(self, minutes: int = 10) -> List[str]:
        """
        Get formatted error alerts for recent errors.

        Args:
            minutes: Time window in minutes

        Returns:
            List of formatted alert strings
        """
        recent_errors = self.error_parser.get_recent_errors(minutes)
        alerts = []

        # Group by signature to avoid duplicate alerts
        seen_signatures = set()

        for error in recent_errors:
            signature = error.signature

            # Skip if we've already alerted on this error
            if signature in seen_signatures:
                continue

            seen_signatures.add(signature)

            # Classify error
            classification = self.error_classifier.classify_error(error)

            # Format alert
            alert = self.error_classifier.format_error_alert(error, classification)
            alerts.append(alert)

        return alerts

    def clear_old_errors(self, hours: int = 24):
        """
        Clear old errors from history.

        Args:
            hours: Age threshold in hours
        """
        # Clear from error parser
        self.error_parser.clear_old_errors(hours)

        # Clear from old error_history
        cutoff = datetime.now() - timedelta(hours=hours)
        self.error_history = deque(
            (e for e in self.error_history if e['timestamp'] >= cutoff),
            maxlen=1000
        )
