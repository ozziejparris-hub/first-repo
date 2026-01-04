#!/usr/bin/env python3
"""
Error Parser - Detailed Log Analysis

Parses log files to extract detailed error context including:
- Component name and function
- Error type and message
- Stack traces
- Trader/market context
- Error grouping and occurrence tracking
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class ErrorDetail:
    """Detailed error information extracted from logs."""
    timestamp: datetime
    level: str  # ERROR, WARNING, CRITICAL
    component: Optional[str] = None
    function: Optional[str] = None
    error_type: Optional[str] = None
    message: str = ""
    stack_trace: List[str] = field(default_factory=list)
    context: Dict = field(default_factory=dict)
    occurrences: int = 1
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    def __post_init__(self):
        """Set first_seen and last_seen if not provided."""
        if self.first_seen is None:
            self.first_seen = self.timestamp
        if self.last_seen is None:
            self.last_seen = self.timestamp

    @property
    def signature(self) -> str:
        """Generate unique signature for error deduplication."""
        parts = [
            self.component or 'unknown',
            self.function or 'unknown',
            self.error_type or 'unknown',
            # Use first 100 chars of message for signature
            self.message[:100] if self.message else ''
        ]
        return '|'.join(parts)


class ErrorParser:
    """Parse logs to extract detailed error information."""

    # Regex patterns for parsing
    TIMESTAMP_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
    LEVEL_PATTERN = re.compile(r'- (ERROR|WARNING|CRITICAL) -')
    COMPONENT_PATTERN = re.compile(r'\[([^\]]+)\]')

    # Python exception patterns
    EXCEPTION_TYPE_PATTERN = re.compile(r'(\w+Error|\w+Exception):')
    TRACEBACK_PATTERN = re.compile(r'Traceback \(most recent call last\):')
    STACK_LINE_PATTERN = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')

    # Context extraction patterns
    TRADER_ADDRESS_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
    MARKET_ID_PATTERN = re.compile(r'market[_\s]?id[:\s]+([a-zA-Z0-9\-]+)', re.IGNORECASE)
    TRADE_ID_PATTERN = re.compile(r'trade[_\s]?id[:\s]+(\d+)', re.IGNORECASE)

    def __init__(self):
        """Initialize error parser."""
        self.error_history: List[ErrorDetail] = []
        self.error_groups: Dict[str, List[ErrorDetail]] = defaultdict(list)

    def parse_log_line(self, line: str) -> Optional[ErrorDetail]:
        """
        Parse a single log line to extract error details.

        Args:
            line: Log line to parse

        Returns:
            ErrorDetail if line contains error, None otherwise
        """
        # Check if line has error/warning/critical level
        level_match = self.LEVEL_PATTERN.search(line)
        if not level_match:
            return None

        level = level_match.group(1)

        # Extract timestamp
        timestamp_match = self.TIMESTAMP_PATTERN.search(line)
        timestamp = None
        if timestamp_match:
            try:
                timestamp = datetime.strptime(timestamp_match.group(1), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        # Extract component (from [COMPONENT] tag)
        component = None
        component_match = self.COMPONENT_PATTERN.search(line)
        if component_match:
            component = component_match.group(1)

        # Extract error type
        error_type = None
        error_type_match = self.EXCEPTION_TYPE_PATTERN.search(line)
        if error_type_match:
            error_type = error_type_match.group(1)

        # Extract message (everything after level marker)
        message = ""
        if level_match:
            message_start = level_match.end()
            message = line[message_start:].strip()

        # Extract context (trader address, market ID, etc.)
        context = self._extract_context(line)

        error = ErrorDetail(
            timestamp=timestamp,
            level=level,
            component=component,
            error_type=error_type,
            message=message,
            context=context
        )

        return error

    def parse_multiline_error(self, lines: List[str]) -> Optional[ErrorDetail]:
        """
        Parse multi-line error including stack trace.

        Args:
            lines: List of consecutive log lines that form an error

        Returns:
            ErrorDetail with stack trace
        """
        if not lines:
            return None

        # Parse first line for basic info
        error = self.parse_log_line(lines[0])
        if not error:
            return None

        # Parse stack trace from subsequent lines
        stack_trace = []
        in_traceback = False

        for line in lines[1:]:
            # Check for traceback start
            if self.TRACEBACK_PATTERN.search(line):
                in_traceback = True
                continue

            # Parse stack trace lines
            if in_traceback:
                stack_match = self.STACK_LINE_PATTERN.search(line)
                if stack_match:
                    file_path, line_num, function = stack_match.groups()
                    stack_trace.append(f"{file_path}:{line_num} in {function}()")

                    # Update component/function from stack trace
                    if not error.component:
                        error.component = file_path
                    if not error.function:
                        error.function = function
                elif line.strip():
                    # Additional stack trace context
                    stack_trace.append(line.strip())

        error.stack_trace = stack_trace
        return error

    def _extract_context(self, text: str) -> Dict:
        """
        Extract contextual information from text.

        Args:
            text: Text to extract from

        Returns:
            Dict with extracted context
        """
        context = {}

        # Extract trader address
        trader_match = self.TRADER_ADDRESS_PATTERN.search(text)
        if trader_match:
            context['trader_address'] = trader_match.group(0)

        # Extract market ID
        market_match = self.MARKET_ID_PATTERN.search(text)
        if market_match:
            context['market_id'] = market_match.group(1)

        # Extract trade ID
        trade_match = self.TRADE_ID_PATTERN.search(text)
        if trade_match:
            context['trade_id'] = trade_match.group(1)

        return context

    def add_error(self, error: ErrorDetail):
        """
        Add error to history and group by signature.

        Args:
            error: Error to add
        """
        # Check if we've seen this error before
        signature = error.signature

        if signature in self.error_groups:
            # Update existing error group
            existing_errors = self.error_groups[signature]
            first_error = existing_errors[0]

            # Update occurrence count
            first_error.occurrences += 1
            first_error.last_seen = error.timestamp

            # Add to group
            existing_errors.append(error)
        else:
            # New error
            self.error_groups[signature] = [error]

        # Add to history
        self.error_history.append(error)

    def get_recent_errors(self, minutes: int = 60) -> List[ErrorDetail]:
        """
        Get errors from last N minutes.

        Args:
            minutes: Time window in minutes

        Returns:
            List of recent errors
        """
        cutoff = datetime.now()
        from datetime import timedelta
        cutoff = cutoff - timedelta(minutes=minutes)

        return [e for e in self.error_history if e.timestamp >= cutoff]

    def get_errors_by_component(self, minutes: int = 60) -> Dict[str, List[ErrorDetail]]:
        """
        Group recent errors by component.

        Args:
            minutes: Time window in minutes

        Returns:
            Dict mapping component name to errors
        """
        recent_errors = self.get_recent_errors(minutes)
        by_component = defaultdict(list)

        for error in recent_errors:
            component = error.component or 'Unknown'
            by_component[component].append(error)

        return dict(by_component)

    def get_top_errors(self, limit: int = 5, minutes: int = 60) -> List[Tuple[str, ErrorDetail]]:
        """
        Get top errors by occurrence count.

        Args:
            limit: Maximum number of errors to return
            minutes: Time window in minutes

        Returns:
            List of (signature, error) tuples sorted by occurrence
        """
        recent_errors = self.get_recent_errors(minutes)

        # Group by signature
        grouped = defaultdict(list)
        for error in recent_errors:
            grouped[error.signature].append(error)

        # Count occurrences
        error_counts = []
        for signature, errors in grouped.items():
            # Use first error as representative
            representative = errors[0]
            representative.occurrences = len(errors)
            error_counts.append((signature, representative))

        # Sort by occurrence count
        error_counts.sort(key=lambda x: x[1].occurrences, reverse=True)

        return error_counts[:limit]

    def get_error_summary(self, minutes: int = 60) -> Dict:
        """
        Get summary of errors in time window.

        Args:
            minutes: Time window in minutes

        Returns:
            Summary dict with counts and breakdowns
        """
        recent_errors = self.get_recent_errors(minutes)

        # Count by level
        level_counts = defaultdict(int)
        for error in recent_errors:
            level_counts[error.level] += 1

        # Count by component
        component_counts = defaultdict(int)
        for error in recent_errors:
            component = error.component or 'Unknown'
            component_counts[component] += 1

        # Get top errors
        top_errors = self.get_top_errors(limit=5, minutes=minutes)

        return {
            'total_errors': len(recent_errors),
            'errors_per_hour': len(recent_errors) * (60 / minutes) if minutes > 0 else 0,
            'by_level': dict(level_counts),
            'by_component': dict(component_counts),
            'top_errors': [(sig, {
                'component': err.component,
                'function': err.function,
                'error_type': err.error_type,
                'message': err.message[:100],
                'occurrences': err.occurrences,
                'first_seen': err.first_seen,
                'last_seen': err.last_seen
            }) for sig, err in top_errors]
        }

    def clear_old_errors(self, hours: int = 24):
        """
        Clear errors older than specified hours.

        Args:
            hours: Age threshold in hours
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)

        # Filter history
        self.error_history = [e for e in self.error_history if e.timestamp >= cutoff]

        # Rebuild groups from remaining history
        self.error_groups = defaultdict(list)
        for error in self.error_history:
            self.error_groups[error.signature].append(error)
