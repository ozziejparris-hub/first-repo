#!/usr/bin/env python3
"""
Comprehensive System Diagnostics

Provides deep health checking across all system components:
- ELO calculation pipeline
- Analysis tools
- Database integrity
- Data quality
- Performance monitoring
"""

import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from pathlib import Path


class ELOSystemDiagnostics:
    """Comprehensive ELO system health checker."""

    def __init__(self, db_path: str):
        """
        Initialize ELO diagnostics.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path

    def check_elo_calculation_health(self) -> Dict:
        """
        Check if ELO calculation pipeline is working.

        Returns:
            Dict with status and any issues found
        """
        issues = []
        warnings = []

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # 1. Check if ELO ratings exist
            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE comprehensive_elo IS NOT NULL
            """)
            traders_with_elo = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM traders WHERE total_trades >= 30")
            qualified_traders = cursor.fetchone()[0]

            elo_coverage = traders_with_elo / max(1, qualified_traders)

            if elo_coverage < 0.5:
                issues.append(f"Low ELO coverage: {elo_coverage*100:.1f}% (expected >50%)")
            elif elo_coverage < 0.8:
                warnings.append(f"Moderate ELO coverage: {elo_coverage*100:.1f}%")

            # 2. Check behavioral metrics coverage
            # Denominator: traders with >=30 local trade rows (behavioral analyzer
            # can only score traders with rows in the trades table, not just
            # traders.total_trades which counts API-fetched trades not stored locally)
            cursor.execute("""
                SELECT COUNT(*) FROM traders t
                WHERE (SELECT COUNT(*) FROM trades tr WHERE tr.trader_address = t.address) >= 30
            """)
            qualified_behavioral = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM traders t
                WHERE (SELECT COUNT(*) FROM trades tr WHERE tr.trader_address = t.address) >= 30
                AND kelly_alignment_score IS NOT NULL
                AND patience_score IS NOT NULL
                AND timing_score IS NOT NULL
            """)
            with_behavioral = cursor.fetchone()[0]

            behavioral_coverage = with_behavioral / max(1, qualified_behavioral)

            if behavioral_coverage < 0.20:
                warnings.append(f"Low behavioral coverage: {behavioral_coverage*100:.1f}% ({with_behavioral}/{qualified_behavioral} traders with local trade data)")

            # 3. Check ROI data quality — use avg_roi, which is populated by the
            # background P&L worker (roi_percentage is the old market-scanner column
            # and is only populated for ~40 traders; avg_roi has full coverage).
            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE avg_roi IS NOT NULL
                AND total_trades >= 10
            """)
            with_roi = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM traders WHERE total_trades >= 10")
            active_traders = cursor.fetchone()[0]

            roi_coverage = with_roi / max(1, active_traders)

            if roi_coverage < 0.05:
                issues.append(f"ROI data CRITICAL: {roi_coverage*100:.1f}% coverage (need 5%+)")
            elif roi_coverage < 0.20:
                warnings.append(f"ROI data low: {roi_coverage*100:.1f}% (target 20%+)")

            # 4. Check ELO distribution (sanity check)
            cursor.execute("""
                SELECT
                    MIN(comprehensive_elo) as min_elo,
                    MAX(comprehensive_elo) as max_elo,
                    AVG(comprehensive_elo) as avg_elo
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
            """)
            row = cursor.fetchone()

            if row and row[0] is not None:
                min_elo, max_elo, avg_elo = row
                elo_range = max_elo - min_elo

                # Sanity checks
                if elo_range < 100:
                    issues.append(f"ELO range too narrow: {elo_range:.0f} points (expected 500+)")

                if avg_elo < 1000 or avg_elo > 2000:
                    warnings.append(f"Unusual average ELO: {avg_elo:.0f} (expected 1300-1600)")

            # 5. Check correlation (if verification file exists)
            last_verification = Path('data/.last_elo_verification')
            if last_verification.exists():
                try:
                    with open(last_verification, 'r') as f:
                        correlation = float(f.read().strip())

                    if correlation < 0.30:
                        issues.append(f"ELO correlation POOR: r={correlation:.3f} (target >0.40)")
                    elif correlation < 0.35:
                        warnings.append(f"ELO correlation low: r={correlation:.3f}")
                except:
                    pass

            conn.close()

        except Exception as e:
            issues.append(f"Database error: {str(e)[:100]}")
            traders_with_elo = 0
            qualified_traders = 0
            elo_coverage = 0
            behavioral_coverage = 0
            roi_coverage = 0

        # Determine status
        if issues:
            status = "CRITICAL"
        elif warnings:
            status = "WARNING"
        else:
            status = "HEALTHY"

        return {
            'status': status,
            'issues': issues,
            'warnings': warnings,
            'metrics': {
                'elo_coverage': elo_coverage,
                'behavioral_coverage': behavioral_coverage,
                'roi_coverage': roi_coverage,
                'traders_with_elo': traders_with_elo,
                'qualified_traders': qualified_traders
            }
        }


    def check_analysis_tools(self) -> Dict:
        """
        Check if all analysis tools can run.

        Tests each analysis script without actually running it.
        """
        issues = []
        tools = []

        # Check if analysis scripts exist and are importable
        analysis_scripts = {
            'Behavioral Analysis': 'analysis/trading_behavior_analysis.py',
            'Weighted Metrics': 'analysis/calculate_weighted_metrics.py',
            'Performance Analysis': 'analysis/trader_performance_analysis.py',
            'ELO Integration': 'scripts/integrate_behavioral_elo.py',
            'ELO Verification': 'scripts/simulation/verify_elo_rankings.py'
        }

        for name, path in analysis_scripts.items():
            file_path = Path(path)

            if not file_path.exists():
                issues.append(f"{name}: File missing at {path}")
                tools.append({'name': name, 'status': 'MISSING'})
            else:
                # Try to parse (basic syntax check)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        code = f.read()
                        compile(code, path, 'exec')

                    tools.append({'name': name, 'status': 'OK'})

                except SyntaxError as e:
                    issues.append(f"{name}: Syntax error at line {e.lineno}")
                    tools.append({'name': name, 'status': 'SYNTAX_ERROR'})

                except Exception as e:
                    issues.append(f"{name}: Error - {str(e)[:50]}")
                    tools.append({'name': name, 'status': 'ERROR'})

        status = "CRITICAL" if issues else "HEALTHY"

        return {
            'status': status,
            'issues': issues,
            'tools': tools
        }


    def check_database_integrity(self) -> Dict:
        """
        Check database health and integrity.
        """
        issues = []
        warnings = []

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # 1. Check required tables exist
            required_tables = [
                'traders', 'trades', 'markets', 'positions', 'monitoring_status'
            ]

            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
            """)
            existing_tables = [row[0] for row in cursor.fetchall()]

            for table in required_tables:
                if table not in existing_tables:
                    issues.append(f"Missing table: {table}")

            # 2. Check for data consistency

            # Trades should reference existing traders
            cursor.execute("""
                SELECT COUNT(*) FROM trades t
                LEFT JOIN traders tr ON t.trader_address = tr.address
                WHERE tr.address IS NULL
            """)
            orphaned_trades = cursor.fetchone()[0]

            if orphaned_trades > 0:
                warnings.append(f"{orphaned_trades:,} trades reference non-existent traders")

            # Positions should reference existing traders
            cursor.execute("""
                SELECT COUNT(*) FROM positions p
                LEFT JOIN traders tr ON p.trader_address = tr.address
                WHERE tr.address IS NULL
            """)
            orphaned_positions = cursor.fetchone()[0]

            if orphaned_positions > 0:
                warnings.append(f"{orphaned_positions:,} positions reference non-existent traders")

            # 3. Check for NULL/invalid data in critical columns
            cursor.execute("""
                SELECT COUNT(*) FROM traders
                WHERE address IS NULL OR address = ''
            """)
            traders_no_address = cursor.fetchone()[0]

            if traders_no_address > 0:
                issues.append(f"{traders_no_address} traders have NULL/empty address")

            # 4. Check database size
            cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
            db_size_bytes = cursor.fetchone()[0]
            db_size_mb = db_size_bytes / (1024 * 1024)

            if db_size_mb > 10000:  # 10 GB
                warnings.append(f"Database very large: {db_size_mb:.0f} MB")

            # 5. Check for database locks
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("ROLLBACK")
                db_locked = False
            except sqlite3.OperationalError:
                db_locked = True
                issues.append("Database is LOCKED (another process accessing it)")

            conn.close()

        except Exception as e:
            issues.append(f"Database error: {str(e)[:100]}")
            db_size_mb = 0
            db_locked = True

        status = "CRITICAL" if issues else ("WARNING" if warnings else "HEALTHY")

        return {
            'status': status,
            'issues': issues,
            'warnings': warnings,
            'metrics': {
                'db_size_mb': db_size_mb,
                'db_locked': db_locked,
                'tables_ok': len(required_tables) - len([i for i in issues if 'Missing table' in i])
            }
        }


    def check_data_quality(self) -> Dict:
        """
        Check quality of data being collected.
        """
        issues = []
        warnings = []
        hours_since = 0
        resolution_rate = 0
        close_rate = 0

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # 1. Check trade data freshness
            # Filter out future-dated rows (Polymarket sometimes stores settlement/expiry
            # dates in the timestamp field, producing timestamps months in the future
            # which corrupt MAX() and make the staleness calculation wildly negative).
            cursor.execute("""
                SELECT MAX(timestamp) FROM trades
                WHERE timestamp <= datetime('now')
            """)
            last_trade = cursor.fetchone()[0]

            if last_trade:
                last_trade_dt = datetime.fromisoformat(last_trade)
                hours_since = (datetime.now() - last_trade_dt).total_seconds() / 3600

                if hours_since > 3.0:
                    issues.append(f"No trades in {hours_since:.1f} hours (monitoring may be stopped)")
                elif hours_since > 1.5:
                    warnings.append(f"Last trade {hours_since:.1f}h ago")

            # 2. Check market resolution rate
            cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
            resolved = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM markets")
            total_markets = cursor.fetchone()[0]

            resolution_rate = resolved / max(1, total_markets)

            if resolution_rate < 0.001:
                warnings.append(f"Low market resolution: {resolution_rate*100:.2f}% (expected 1-2%)")

            # 3. Check position closing rate
            cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'closed'")
            closed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'open'")
            open_pos = cursor.fetchone()[0]

            total_pos = closed + open_pos
            close_rate = closed / max(1, total_pos)

            # Position close rate is intentionally low — most monitored markets
            # remain open until resolution.  This check produced false CRITICALs
            # and has been removed.

            # 4. Check for duplicate trades
            cursor.execute("""
                SELECT COUNT(*) - COUNT(DISTINCT trade_id) FROM trades
            """)
            duplicates = cursor.fetchone()[0]

            if duplicates > 100:
                warnings.append(f"{duplicates:,} duplicate trades detected")

            # 5. Check ROI reasonableness
            cursor.execute("""
                SELECT
                    MIN(roi_percentage) as min_roi,
                    MAX(roi_percentage) as max_roi,
                    AVG(roi_percentage) as avg_roi
                FROM traders
                WHERE roi_percentage IS NOT NULL
                AND roi_percentage != 0
            """)
            row = cursor.fetchone()

            if row and row[0] is not None:
                min_roi, max_roi, avg_roi = row

                # Only flag ROI below -100% — that is genuinely impossible on a prediction market
                # and indicates a data error. There is no upper bound: high ROI is expected
                # (e.g. a 1-cent position on a correct outcome pays ~100x).
                if min_roi < -100:
                    issues.append(f"ROI below -100%: {min_roi:.1f}% (impossible on prediction markets — data error)")

                if abs(avg_roi) > 50:
                    warnings.append(f"Unusual average ROI: {avg_roi:.1f}% (expected -10% to +20%)")

            conn.close()

        except Exception as e:
            issues.append(f"Data quality check error: {str(e)[:100]}")

        status = "CRITICAL" if issues else ("WARNING" if warnings else "HEALTHY")

        return {
            'status': status,
            'issues': issues,
            'warnings': warnings,
            'metrics': {
                'hours_since_last_trade': hours_since,
                'resolution_rate': resolution_rate,
                'position_close_rate': close_rate
            }
        }


    def run_full_diagnostic(self) -> Dict:
        """
        Run all diagnostic checks and compile report.
        """

        results = {
            'elo_system': self.check_elo_calculation_health(),
            'analysis_tools': self.check_analysis_tools(),
            'database': self.check_database_integrity(),
            'data_quality': self.check_data_quality()
        }

        # Determine overall status
        statuses = [r['status'] for r in results.values()]

        if 'CRITICAL' in statuses:
            overall_status = 'CRITICAL'
        elif 'WARNING' in statuses:
            overall_status = 'WARNING'
        else:
            overall_status = 'HEALTHY'

        # Compile all issues
        all_issues = []
        all_warnings = []

        for category, result in results.items():
            for issue in result.get('issues', []):
                all_issues.append(f"[{category.upper()}] {issue}")
            for warning in result.get('warnings', []):
                all_warnings.append(f"[{category.upper()}] {warning}")

        return {
            'overall_status': overall_status,
            'issues': all_issues,
            'warnings': all_warnings,
            'details': results,
            'timestamp': datetime.now()
        }


class PerformanceMonitor:
    """Track system performance over time."""

    def __init__(self, db_path: str):
        """
        Initialize performance monitor.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.metrics_history = []

    def collect_metrics(self) -> Dict:
        """Collect current performance metrics."""

        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()

            # Query performance
            start = time.time()
            cursor.execute("SELECT COUNT(*) FROM trades")
            query_time = time.time() - start

            # Database size
            cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
            db_size = cursor.fetchone()[0]

            # Recent activity
            cursor.execute("""
                SELECT COUNT(*) FROM trades
                WHERE timestamp > datetime('now', '-1 hour')
            """)
            trades_last_hour = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM positions
                WHERE last_updated > datetime('now', '-1 hour')
            """)
            positions_updated_last_hour = cursor.fetchone()[0]

            conn.close()

            metrics = {
                'timestamp': datetime.now(),
                'query_time_ms': query_time * 1000,
                'db_size_mb': db_size / (1024 * 1024),
                'trades_per_hour': trades_last_hour,
                'positions_updated_per_hour': positions_updated_last_hour
            }

        except Exception as e:
            # Return default metrics on error
            metrics = {
                'timestamp': datetime.now(),
                'query_time_ms': 0,
                'db_size_mb': 0,
                'trades_per_hour': 0,
                'positions_updated_per_hour': 0,
                'error': str(e)[:100]
            }

        self.metrics_history.append(metrics)

        # Keep last 24 hours only
        cutoff = datetime.now() - timedelta(hours=24)
        self.metrics_history = [m for m in self.metrics_history if m['timestamp'] > cutoff]

        return metrics

    def detect_performance_issues(self) -> List[str]:
        """Detect performance degradation."""

        if len(self.metrics_history) < 6:  # Need 1 hour of data
            return []

        issues = []

        recent = self.metrics_history[-6:]  # Last hour

        # Check query time
        avg_query_time = sum(m.get('query_time_ms', 0) for m in recent) / len(recent)
        if avg_query_time > 1000:  # >1 second
            issues.append(f"Slow database queries: {avg_query_time:.0f}ms avg")

        # Check activity decline
        avg_trades = sum(m.get('trades_per_hour', 0) for m in recent) / len(recent)
        if avg_trades < 10 and len(self.metrics_history) > 12:  # After 2 hours
            issues.append(f"Low trade activity: {avg_trades:.0f} trades/hour")

        # Check database growth
        if len(self.metrics_history) > 36:  # 6 hours of data
            old_size = self.metrics_history[-36].get('db_size_mb', 0)
            new_size = self.metrics_history[-1].get('db_size_mb', 0)
            growth = new_size - old_size

            if growth < 0.1:  # Less than 100KB growth in 6 hours
                issues.append(f"Database not growing: {growth*1000:.0f} KB in 6h")

        return issues


class FixSuggestionEngine:
    """Provide specific fix suggestions for detected issues."""

    @staticmethod
    def get_fix_for_issue(issue: str) -> str:
        """Return specific fix suggestion for an issue."""

        fixes = {
            # Monitoring issues
            'No activity for': "Restart monitoring: `scripts/start_server.sh`",
            'No trades in': "1. Check if Polymarket API is down\n2. Restart monitoring if API is up",
            'monitoring may be stopped': "Restart monitoring system immediately",

            # Position tracking
            'positions not closing': "Check market resolution detection in position_tracker.py",
            'Low position close rate': "Verify markets are resolving (check markets.resolved column)",

            # ROI/P&L
            'ROI data CRITICAL': "Wait 24-48h for monitoring to collect P&L data",
            'ROI data low': "Check if position_tracker.update_position_tracking() is running",

            # ELO system
            'Low ELO coverage': "Run: `py scripts/integrate_behavioral_elo.py`",
            'Low behavioral coverage': "Run: `py analysis/trading_behavior_analysis.py` to populate kelly/patience/timing scores",
            'ELO correlation POOR': "Check behavioral metrics quality, may need more data",

            # Database
            'Missing table': "Run database migration script to create missing tables",
            'Database is LOCKED': "1. Close DB Browser\n2. Stop duplicate monitoring processes",
            'reference non-existent': "Run: `py scripts/quick_fixes/clean_orphaned_records.py`",

            # Analysis tools
            'File missing': "Restore missing file from repository",
            'Syntax error': "Fix Python syntax error in indicated file",

            # Performance
            'Slow database queries': "1. Add indexes\n2. Vacuum database\n3. Consider WAL mode",
            'Database not growing': "Check if monitoring is actually collecting new trades",
        }

        # Find matching fix
        for keyword, fix in fixes.items():
            if keyword in issue:
                return fix

        return "No specific fix available - investigate manually"


    @staticmethod
    def generate_fix_report(issues: List[str]) -> str:
        """Generate comprehensive fix report."""

        if not issues:
            return ""

        msg_parts = ["**🔧 FIX RECOMMENDATIONS:**", ""]

        for i, issue in enumerate(issues, 1):
            msg_parts.append(f"**Issue {i}:** {issue}")

            fix = FixSuggestionEngine.get_fix_for_issue(issue)
            msg_parts.append(f"**Fix:** {fix}")
            msg_parts.append("")

        msg_parts.append("_Copy/paste these commands to fix issues_")

        return '\n'.join(msg_parts)
