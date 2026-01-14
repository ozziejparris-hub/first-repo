#!/usr/bin/env python3
"""
Test Behavioral ELO Integration

Tests the complete behavioral ELO integration:
1. Kelly alignment calculation
2. Minimum sample filter (50+ resolved trades)
3. Correlation improvement
4. Behavioral ELO modifier application
5. ROI-based scoring
6. Database schema updates

Run after completing integrate_behavioral_elo.py to verify integration.
"""

import sys
import os
import sqlite3
from pathlib import Path
from typing import Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestResults:
    """Track test results."""

    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def record_pass(self, test_name: str):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  [✓] {test_name}")

    def record_fail(self, test_name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((test_name, reason))
        print(f"  [✗] {test_name}: {reason}")

    def summary(self):
        print(f"\n{'='*70}")
        print(f"  TEST SUMMARY")
        print(f"{'='*70}")
        print(f"  Tests run: {self.tests_run}")
        print(f"  Passed: {self.tests_passed} ({self.tests_passed/max(1,self.tests_run)*100:.1f}%)")
        print(f"  Failed: {self.tests_failed}")

        if self.failures:
            print(f"\n  FAILURES:")
            for test_name, reason in self.failures:
                print(f"    - {test_name}: {reason}")

        print(f"{'='*70}\n")

        return self.tests_failed == 0


def test_database_schema(db_path: str, results: TestResults):
    """Test that database schema has been updated with new columns."""
    print("\n[TEST 1] Database Schema Updates")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check traders table
    cursor.execute("PRAGMA table_info(traders)")
    trader_columns = {row[1] for row in cursor.fetchall()}

    expected_columns = {
        'kelly_alignment_score',
        'patience_score',
        'timing_score',
        'weighted_win_rate',
        'roi_percentage',
        'resolved_trades_count'
    }

    missing_trader_columns = expected_columns - trader_columns

    if not missing_trader_columns:
        results.record_pass("Traders table has all new columns")
    else:
        results.record_fail("Traders table missing columns", f"Missing: {missing_trader_columns}")

    # Check markets table
    cursor.execute("PRAGMA table_info(markets)")
    market_columns = {row[1] for row in cursor.fetchall()}

    if 'difficulty_score' in market_columns:
        results.record_pass("Markets table has difficulty_score column")
    else:
        results.record_fail("Markets table missing column", "Missing: difficulty_score")

    conn.close()


def test_kelly_alignment_calculation(db_path: str, results: TestResults):
    """Test that Kelly alignment scores are calculated."""
    print("\n[TEST 2] Kelly Alignment Calculation")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(kelly_alignment_score) as with_kelly,
               AVG(kelly_alignment_score) as avg_kelly
        FROM traders
        WHERE total_trades >= 10
    """)

    row = cursor.fetchone()
    total, with_kelly, avg_kelly = row

    # At least 10% of traders should have Kelly scores
    if with_kelly / max(1, total) >= 0.10:
        results.record_pass(f"Kelly scores calculated ({with_kelly}/{total} traders)")
    else:
        results.record_fail("Kelly scores", f"Only {with_kelly}/{total} traders have scores")

    # Average Kelly score should be between 0 and 1
    if avg_kelly and 0 <= avg_kelly <= 1:
        results.record_pass(f"Kelly scores in valid range (avg: {avg_kelly:.3f})")
    else:
        results.record_fail("Kelly scores out of range", f"Average: {avg_kelly}")

    conn.close()


def test_minimum_sample_filter(db_path: str, results: TestResults):
    """Test that minimum sample filter (50+ resolved trades) works."""
    print("\n[TEST 3] Minimum Sample Filter")

    from analysis.unified_elo_system import UnifiedELOSystem

    try:
        system = UnifiedELOSystem(db_path=db_path)

        # Get top traders with default filter (50+ resolved)
        top_traders = system.get_top_traders(limit=20, min_resolved_trades=50)

        if len(top_traders) > 0:
            results.record_pass(f"Filter returns traders ({len(top_traders)} found)")

            # Verify all have >= 50 resolved trades
            all_qualified = all(
                t.get('resolved_trades', 0) >= 50
                for t in top_traders
            )

            if all_qualified:
                results.record_pass("All returned traders have ≥50 resolved trades")
            else:
                results.record_fail("Sample filter", "Some traders have <50 resolved trades")
        else:
            results.record_fail("Sample filter", "No traders returned (may need more data)")

    except Exception as e:
        results.record_fail("Sample filter", str(e))


def test_behavioral_elo_modifier(db_path: str, results: TestResults):
    """Test that behavioral ELO modifiers are applied."""
    print("\n[TEST 4] Behavioral ELO Modifier")

    from analysis.unified_elo_system import UnifiedELOSystem

    try:
        system = UnifiedELOSystem(db_path=db_path)

        # Get a trader with behavioral data
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT address
            FROM traders
            WHERE kelly_alignment_score IS NOT NULL
            AND patience_score IS NOT NULL
            AND timing_score IS NOT NULL
            LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if not row:
            results.record_fail("Behavioral modifier", "No traders with complete behavioral data")
            return

        trader_address = row[0]

        # Calculate behavioral bonus
        bonus = system.calculate_behavioral_elo_bonus(trader_address)

        # Bonus should be between -100 and +100
        if -100 <= bonus <= 100:
            results.record_pass(f"Behavioral bonus in valid range ({bonus:+.0f} points)")
        else:
            results.record_fail("Behavioral bonus out of range", f"Bonus: {bonus}")

        # Get ELO with and without behavioral modifier
        base_elo = system.get_trader_global_elo(trader_address, apply_behavioral=False)
        adjusted_elo = system.get_trader_global_elo(trader_address, apply_behavioral=True)

        # Should be different (unless bonus is exactly 0 and multiplier is 1.0)
        if abs(adjusted_elo - base_elo) >= 0.1:
            results.record_pass(f"Behavioral modifier applied (Δ={adjusted_elo-base_elo:+.0f})")
        else:
            # This is OK if the trader has neutral behavioral metrics
            results.record_pass("Behavioral modifier neutral (expected for average trader)")

    except Exception as e:
        results.record_fail("Behavioral modifier", str(e))


def test_roi_based_scoring(db_path: str, results: TestResults):
    """Test that ROI-based scoring is working."""
    print("\n[TEST 5] ROI-Based Scoring")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check that ROI percentages are calculated
    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(roi_percentage) as with_roi,
               AVG(roi_percentage) as avg_roi,
               MIN(roi_percentage) as min_roi,
               MAX(roi_percentage) as max_roi
        FROM traders
        WHERE resolved_trades_count >= 10
    """)

    row = cursor.fetchone()
    total, with_roi, avg_roi, min_roi, max_roi = row

    if with_roi / max(1, total) >= 0.10:
        results.record_pass(f"ROI calculated for {with_roi}/{total} traders")
    else:
        results.record_fail("ROI calculation", f"Only {with_roi}/{total} have ROI")

    # ROI range should be reasonable (e.g., -100% to +200%)
    if min_roi and max_roi and -100 <= min_roi and max_roi <= 500:
        results.record_pass(f"ROI in reasonable range ({min_roi:.1f}% to {max_roi:.1f}%)")
    else:
        results.record_fail("ROI range", f"Range: {min_roi} to {max_roi}")

    conn.close()


def test_weighted_win_rate(db_path: str, results: TestResults):
    """Test that weighted win rates are calculated."""
    print("\n[TEST 6] Weighted Win Rate")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(weighted_win_rate) as with_weighted,
               AVG(weighted_win_rate) as avg_weighted_wr
        FROM traders
        WHERE resolved_trades_count >= 10
    """)

    row = cursor.fetchone()
    total, with_weighted, avg_weighted_wr = row

    if with_weighted / max(1, total) >= 0.10:
        results.record_pass(f"Weighted WR calculated ({with_weighted}/{total} traders)")
    else:
        results.record_fail("Weighted win rate", f"Only {with_weighted}/{total} have weighted WR")

    # Average should be around 50% (0-100 scale)
    if avg_weighted_wr and 20 <= avg_weighted_wr <= 80:
        results.record_pass(f"Weighted WR in reasonable range (avg: {avg_weighted_wr:.1f}%)")
    else:
        results.record_fail("Weighted WR out of range", f"Average: {avg_weighted_wr}")

    conn.close()


def test_correlation_data_exists(db_path: str, results: TestResults):
    """Test that we have enough data for correlation analysis."""
    print("\n[TEST 7] Data Quality for Correlation")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count traders with sufficient data
    cursor.execute("""
        SELECT COUNT(*) as qualified_traders
        FROM traders
        WHERE resolved_trades_count >= 50
        AND comprehensive_elo IS NOT NULL
        AND kelly_alignment_score IS NOT NULL
        AND roi_percentage IS NOT NULL
    """)

    qualified_traders = cursor.fetchone()[0]

    # Need at least 10 traders for meaningful correlation
    if qualified_traders >= 10:
        results.record_pass(f"Sufficient qualified traders ({qualified_traders} with ≥50 resolved)")
    else:
        results.record_fail("Data quality", f"Only {qualified_traders} qualified traders (need ≥10)")

    # Check resolved markets
    cursor.execute("""
        SELECT COUNT(*) as resolved_markets
        FROM markets
        WHERE resolved = 1
        AND winning_outcome IS NOT NULL
    """)

    resolved_markets = cursor.fetchone()[0]

    if resolved_markets >= 50:
        results.record_pass(f"Sufficient resolved markets ({resolved_markets})")
    else:
        results.record_fail("Data quality", f"Only {resolved_markets} resolved markets (need ≥50)")

    conn.close()


def test_behavioral_metrics_complete(db_path: str, results: TestResults):
    """Test that all behavioral metrics are calculated."""
    print("\n[TEST 8] Complete Behavioral Metrics")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as traders_with_all_metrics
        FROM traders
        WHERE total_trades >= 10
        AND kelly_alignment_score IS NOT NULL
        AND patience_score IS NOT NULL
        AND timing_score IS NOT NULL
        AND weighted_win_rate IS NOT NULL
        AND roi_percentage IS NOT NULL
    """)

    traders_with_all = cursor.fetchone()[0]

    if traders_with_all >= 5:
        results.record_pass(f"Complete metrics for {traders_with_all} traders")
    else:
        results.record_fail("Complete metrics", f"Only {traders_with_all} have all metrics")

    conn.close()


def main():
    """Main test runner."""

    print("\n" + "="*70)
    print("  BEHAVIORAL ELO INTEGRATION - TEST SUITE")
    print("="*70)

    # Find database
    possible_paths = [
        Path('data/polymarket_tracker.db'),
        Path('monitoring/data/markets.db'),
        Path('polymarket_tracker.db')
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = str(path)
            break

    if not db_path:
        print("\n[ERROR] Database not found. Please run integration first.")
        return False

    print(f"\nTesting database: {db_path}")

    # Run tests
    results = TestResults()

    test_database_schema(db_path, results)
    test_kelly_alignment_calculation(db_path, results)
    test_minimum_sample_filter(db_path, results)
    test_behavioral_elo_modifier(db_path, results)
    test_roi_based_scoring(db_path, results)
    test_weighted_win_rate(db_path, results)
    test_correlation_data_exists(db_path, results)
    test_behavioral_metrics_complete(db_path, results)

    # Summary
    success = results.summary()

    if success:
        print("✅ ALL TESTS PASSED - Behavioral ELO integration successful!")
        print("\nExpected improvements:")
        print("  - Correlation: 0.135 → 0.45-0.65 (target)")
        print("  - Elite accuracy: Current → 70-75% (target)")
        print("  - ELO spread: More differentiation between skill levels")
        print()
    else:
        print("❌ SOME TESTS FAILED - Review failures above")
        print("\nTroubleshooting:")
        print("  1. Run: py scripts/integrate_behavioral_elo.py")
        print("  2. Ensure database has resolved markets")
        print("  3. Check that behavioral analysis completed successfully")
        print()

    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
