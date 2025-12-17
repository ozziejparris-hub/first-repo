#!/usr/bin/env python3
"""
Performance Baselines

Learn and track normal system behavior to detect anomalies.

Features:
- Record metric observations
- Calculate baseline statistics (mean, std)
- Detect anomalies (>2.5 std deviation)
- Adaptive baselines (update daily)
- Persistent storage (SQLite)
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import math


class PerformanceBaselines:
    """
    Learn and track system performance baselines.

    Metrics tracked:
    - trades_per_hour
    - api_calls_per_minute
    - db_query_time_ms
    - elo_update_duration_sec
    - memory_mb
    - error_rate_per_hour
    """

    def __init__(self, db_path: str = 'reports/baselines.db'):
        """
        Initialize performance baselines.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # Connect to database
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

        # Create tables
        self._create_tables()

    def _create_tables(self):
        """Create database tables for baselines."""
        cursor = self.conn.cursor()

        # Observations table (raw data points)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metric_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metric_observations_name_time
            ON metric_observations(metric_name, timestamp)
        """)

        # Baselines table (calculated statistics)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                metric_name TEXT PRIMARY KEY,
                mean REAL NOT NULL,
                std REAL NOT NULL,
                min REAL NOT NULL,
                max REAL NOT NULL,
                samples INTEGER NOT NULL,
                last_updated TEXT NOT NULL
            )
        """)

        self.conn.commit()

    def record_metric(self, metric_name: str, value: float, timestamp: Optional[datetime] = None):
        """
        Record a metric observation.

        Args:
            metric_name: Name of the metric
            value: Metric value
            timestamp: Timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.now()

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO metric_observations (metric_name, value, timestamp)
            VALUES (?, ?, ?)
        """, (metric_name, value, timestamp.isoformat()))

        self.conn.commit()

    def get_baseline(self, metric_name: str, window_hours: int = 24) -> Optional[Dict]:
        """
        Get baseline statistics for a metric.

        Args:
            metric_name: Name of the metric
            window_hours: Time window for baseline calculation (default: 24h)

        Returns:
            dict: Baseline stats or None if insufficient data
            {
                'mean': float,
                'std': float,
                'min': float,
                'max': float,
                'samples': int,
                'last_updated': datetime
            }
        """
        cursor = self.conn.cursor()

        # First check if we have a cached baseline
        cursor.execute("""
            SELECT mean, std, min, max, samples, last_updated
            FROM baselines
            WHERE metric_name = ?
        """, (metric_name,))

        row = cursor.fetchone()

        if row:
            last_updated = datetime.fromisoformat(row['last_updated'])
            age = (datetime.now() - last_updated).total_seconds() / 3600

            # If baseline is recent (< 24h), use it
            if age < 24:
                return {
                    'mean': row['mean'],
                    'std': row['std'],
                    'min': row['min'],
                    'max': row['max'],
                    'samples': row['samples'],
                    'last_updated': last_updated
                }

        # Calculate fresh baseline from observations
        cutoff = datetime.now() - timedelta(hours=window_hours)

        cursor.execute("""
            SELECT value
            FROM metric_observations
            WHERE metric_name = ? AND timestamp >= ?
            ORDER BY timestamp DESC
        """, (metric_name, cutoff.isoformat()))

        values = [row['value'] for row in cursor.fetchall()]

        if len(values) < 10:
            # Need at least 10 samples
            return None

        # Calculate statistics
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(variance)
        min_val = min(values)
        max_val = max(values)

        baseline = {
            'mean': mean,
            'std': std,
            'min': min_val,
            'max': max_val,
            'samples': len(values),
            'last_updated': datetime.now()
        }

        # Update cached baseline
        self._update_baseline_cache(metric_name, baseline)

        return baseline

    def _update_baseline_cache(self, metric_name: str, baseline: Dict):
        """
        Update cached baseline in database.

        Args:
            metric_name: Metric name
            baseline: Baseline dict
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO baselines
            (metric_name, mean, std, min, max, samples, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            metric_name,
            baseline['mean'],
            baseline['std'],
            baseline['min'],
            baseline['max'],
            baseline['samples'],
            baseline['last_updated'].isoformat()
        ))

        self.conn.commit()

    def is_anomaly(
        self,
        metric_name: str,
        value: float,
        std_threshold: float = 2.5,
        window_hours: int = 24
    ) -> bool:
        """
        Check if a value is anomalous.

        Args:
            metric_name: Metric name
            value: Value to check
            std_threshold: Standard deviation threshold (default: 2.5)
            window_hours: Time window for baseline

        Returns:
            bool: True if value is anomalous
        """
        baseline = self.get_baseline(metric_name, window_hours)

        if not baseline:
            # No baseline yet
            return False

        # Check if value is outside threshold
        deviation = abs(value - baseline['mean'])
        threshold = std_threshold * baseline['std']

        return deviation > threshold

    def get_deviation(
        self,
        metric_name: str,
        value: float,
        window_hours: int = 24
    ) -> Optional[Dict]:
        """
        Get deviation statistics for a value.

        Args:
            metric_name: Metric name
            value: Value to check
            window_hours: Time window for baseline

        Returns:
            dict: Deviation stats or None if no baseline
            {
                'value': float,
                'baseline_mean': float,
                'baseline_std': float,
                'deviation': float,
                'deviation_std': float,  # In standard deviations
                'deviation_pct': float,  # Percentage from mean
                'is_anomaly': bool
            }
        """
        baseline = self.get_baseline(metric_name, window_hours)

        if not baseline:
            return None

        deviation = value - baseline['mean']
        deviation_std = deviation / baseline['std'] if baseline['std'] > 0 else 0
        deviation_pct = (deviation / baseline['mean'] * 100) if baseline['mean'] != 0 else 0

        return {
            'value': value,
            'baseline_mean': baseline['mean'],
            'baseline_std': baseline['std'],
            'deviation': deviation,
            'deviation_std': deviation_std,
            'deviation_pct': deviation_pct,
            'is_anomaly': abs(deviation_std) > 2.5
        }

    def update_all_baselines(self, window_hours: int = 24):
        """
        Recalculate all baselines from observations.

        Should be run daily to adapt to changing patterns.

        Args:
            window_hours: Time window for calculations
        """
        cursor = self.conn.cursor()

        # Get all unique metrics
        cursor.execute("""
            SELECT DISTINCT metric_name
            FROM metric_observations
        """)

        metrics = [row['metric_name'] for row in cursor.fetchall()]

        for metric_name in metrics:
            # Force baseline recalculation
            baseline = self.get_baseline(metric_name, window_hours)
            if baseline:
                print(f"[BASELINES] Updated {metric_name}: mean={baseline['mean']:.2f}, std={baseline['std']:.2f}")

    def cleanup_old_observations(self, days_to_keep: int = 30):
        """
        Delete old observations to save space.

        Args:
            days_to_keep: Keep observations from last N days
        """
        cutoff = datetime.now() - timedelta(days=days_to_keep)

        cursor = self.conn.cursor()
        cursor.execute("""
            DELETE FROM metric_observations
            WHERE timestamp < ?
        """, (cutoff.isoformat(),))

        deleted = cursor.rowcount
        self.conn.commit()

        print(f"[BASELINES] Cleaned up {deleted} old observations (kept last {days_to_keep} days)")

    def get_all_baselines(self) -> Dict[str, Dict]:
        """
        Get all cached baselines.

        Returns:
            dict: {metric_name: baseline_dict}
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM baselines")

        baselines = {}
        for row in cursor.fetchall():
            baselines[row['metric_name']] = {
                'mean': row['mean'],
                'std': row['std'],
                'min': row['min'],
                'max': row['max'],
                'samples': row['samples'],
                'last_updated': datetime.fromisoformat(row['last_updated'])
            }

        return baselines

    def get_metric_history(
        self,
        metric_name: str,
        hours: int = 24,
        limit: int = 1000
    ) -> List[Tuple[datetime, float]]:
        """
        Get recent metric history.

        Args:
            metric_name: Metric name
            hours: Time window
            limit: Maximum number of points

        Returns:
            List of (timestamp, value) tuples
        """
        cutoff = datetime.now() - timedelta(hours=hours)

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timestamp, value
            FROM metric_observations
            WHERE metric_name = ? AND timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (metric_name, cutoff.isoformat(), limit))

        return [
            (datetime.fromisoformat(row['timestamp']), row['value'])
            for row in cursor.fetchall()
        ]

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
