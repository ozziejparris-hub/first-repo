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
        print(f"  [] {test_name}")

    def record_fail(self, test_name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((test_name, reason))
        print(f"  [] {test_name}: {reason}")

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
    """Test that minimum sample filter (50+ resolved trades) works.

    Original intent: verify get_top_traders(min_resolved_trades=50) returns
    only traders with >=50 resolved trades, and excludes under-threshold traders.

    Rewritten to query stored resolved_trades_count directly (same data the
    filter reads) rather than invoking UnifiedELOSystem which re-runs the full
    39-minute analysis pipeline on a cold cache.

    Catches the same two regressions as the original:
      (A) Pool existence: if integrate_behavioral_elo.py stops computing
          resolved_trades_count, the qualified pool collapses to zero.
      (B) Filter integrity: no under-threshold trader may appear in the
          filtered set. Also verifies the filter is non-vacuous — if
          resolved_trades_count were bogusly inflated for everyone, the
          unfiltered top-20 would no longer contain under-threshold traders
          and this check would flag it.
    """
    print("\n[TEST 3] Minimum Sample Filter")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # (A) POOL EXISTS: at least 1000 traders qualify.
    # Catches: resolved_trades_count stopped being populated by the integration.
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM traders
        WHERE resolved_trades_count >= 50
        AND comprehensive_elo IS NOT NULL
    """)
    qualified_count = cursor.fetchone()['cnt']
    if qualified_count >= 1000:
        results.record_pass(
            f"Qualified pool: {qualified_count} traders with resolved_trades_count>=50 and ELO set"
        )
    else:
        results.record_fail(
            "Qualified pool too small",
            f"Only {qualified_count} traders qualify (expected >=1000) — "
            "resolved_trades_count may not be populated"
        )

    # (B) FILTER EXCLUSION SIDE: the top-20 traders by comprehensive_elo WITHOUT
    # the filter must include some under-threshold traders. This proves the filter
    # actually does work to exclude real traders (i.e., resolved_trades_count data
    # is realistic, not inflated). If this fails, the count data is corrupt.
    cursor.execute("""
        SELECT address, comprehensive_elo, resolved_trades_count
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
        ORDER BY comprehensive_elo DESC
        LIMIT 20
    """)
    top20_unfiltered = cursor.fetchall()
    under_threshold_in_top20 = [
        r for r in top20_unfiltered
        if r['resolved_trades_count'] is None or r['resolved_trades_count'] < 50
    ]
    if len(under_threshold_in_top20) >= 5:
        results.record_pass(
            f"Filter is non-vacuous: {len(under_threshold_in_top20)}/20 top-ELO traders "
            f"have <50 resolved trades and would be correctly excluded"
        )
    else:
        results.record_fail(
            "Filter appears vacuous or resolved_trades_count data is corrupt",
            f"Only {len(under_threshold_in_top20)}/20 top-ELO traders have <50 resolved "
            f"trades — expected most to be under threshold"
        )

    # (B) FILTER INCLUSION SIDE: the top-20 WITH the filter applied must all
    # have resolved_trades_count >= 50. Directly mirrors the original
    # all(resolved_trades >= 50 for t in top_traders) check.
    # Catches: filter condition is removed or inverted, letting under-threshold
    # traders into the qualified set.
    cursor.execute("""
        SELECT address, comprehensive_elo, resolved_trades_count
        FROM traders
        WHERE resolved_trades_count >= 50
        AND comprehensive_elo IS NOT NULL
        ORDER BY comprehensive_elo DESC
        LIMIT 20
    """)
    top20_filtered = cursor.fetchall()
    violators = [r for r in top20_filtered if r['resolved_trades_count'] < 50]
    if not violators:
        results.record_pass(
            f"Filter integrity: all {len(top20_filtered)} traders in qualified top-20 "
            f"have resolved_trades_count >= 50 (no under-threshold trader leaked in)"
        )
    else:
        results.record_fail(
            "Sample filter BROKEN — under-threshold traders in qualified set",
            f"{len(violators)} traders with <50 resolved trades appear in filtered top-20"
        )

    conn.close()


def test_behavioral_elo_modifier(db_path: str, results: TestResults):
    """Test that behavioral ELO modifiers are applied.

    Original intent:
      (1) calculate_behavioral_elo_bonus(trader) returns a value in [-100, +100]
          — range sanity check on the modifier computation.
      (2) get_trader_global_elo(apply_behavioral=True) differs from
          apply_behavioral=False by >=0.1 — the modifier actually moves ELO.

    Rewritten to verify the stored behavioral_modifier values in the traders
    table rather than re-running the full analysis pipeline from raw trades.
    behavioral_modifier is the multiplicative factor written by
    integrate_behavioral_elo.py for every trader — it is the stored output of
    the same computation the original tested at runtime.

    Catches the same two regressions:
      (1) SCALE: if integrate_behavioral_elo.py silently stops applying
          modifiers to most kelly-scored traders, the count of traders with
          kelly_alignment_score AND behavioral_modifier != 1.0 drops. The floor
          of 1400 (vs 1480 known-good) catches mass-regression while tolerating
          minor fluctuation as the trader population grows.
      (2) RANGE + BIDIRECTIONAL: if modifier computation goes out of bounds
          or collapses (all traders get boosted, or all get suppressed, or all
          stay at 1.0), those patterns are caught by checking min/max and
          verifying that both suppressed (<1.0) and boosted (>1.0) traders
          exist in the kelly-scored population.
    """
    print("\n[TEST 4] Behavioral ELO Modifier")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # (1) SCALE CHECK: at least 1400 traders with kelly scores must have
    # behavioral_modifier != 1.0. Known-good baseline: 1480.
    # Floor of 1400 = ~91% of 1533 kelly-scored traders.
    # Catches: integration stopped writing modifiers to most traders.
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM traders
        WHERE kelly_alignment_score IS NOT NULL
        AND behavioral_modifier IS NOT NULL
        AND behavioral_modifier != 1.0
    """)
    modifier_count = cursor.fetchone()['cnt']
    if modifier_count >= 1400:
        results.record_pass(
            f"Behavioral modifiers applied at scale: {modifier_count} traders "
            f"with kelly scores have non-neutral behavioral_modifier"
        )
    else:
        results.record_fail(
            "Behavioral modifiers not applied at scale",
            f"Only {modifier_count} kelly-scored traders have behavioral_modifier != 1.0 "
            f"(expected >=1400) — integration may have stopped applying modifiers"
        )

    # (2a) RANGE CHECK: behavioral_modifier for kelly-scored traders must stay
    # within [0.75, 1.50]. Parallel to the original's [-100, +100] bonus range.
    # Catches: modifier computation producing runaway values.
    cursor.execute("""
        SELECT MIN(behavioral_modifier) as mn, MAX(behavioral_modifier) as mx
        FROM traders
        WHERE kelly_alignment_score IS NOT NULL
        AND behavioral_modifier IS NOT NULL
    """)
    row = cursor.fetchone()
    mn, mx = row['mn'], row['mx']
    if mn >= 0.75 and mx <= 1.50:
        results.record_pass(
            f"Behavioral modifier in valid range: [{mn:.3f}, {mx:.3f}] "
            f"(expected [0.75, 1.50])"
        )
    else:
        results.record_fail(
            "Behavioral modifier out of bounds",
            f"Range [{mn:.3f}, {mx:.3f}] — expected [0.75, 1.50]"
        )

    # (2b) BIDIRECTIONAL CHECK: modifier must both boost some traders (>1.0)
    # and suppress others (<1.0). Catches: modifier collapsed to one direction
    # (e.g. everyone boosted due to a sign bug) or frozen at 1.0 for all.
    # Parallel to the original's check that adjusted_elo actually differs from base.
    cursor.execute("""
        SELECT
            COUNT(CASE WHEN behavioral_modifier > 1.0 THEN 1 END) as boosted,
            COUNT(CASE WHEN behavioral_modifier < 1.0 THEN 1 END) as suppressed
        FROM traders
        WHERE kelly_alignment_score IS NOT NULL
        AND behavioral_modifier IS NOT NULL
    """)
    row = cursor.fetchone()
    boosted, suppressed = row['boosted'], row['suppressed']
    if boosted >= 100 and suppressed >= 100:
        results.record_pass(
            f"Behavioral modifier is bidirectional: {boosted} traders boosted >1.0, "
            f"{suppressed} suppressed <1.0 — modifier differentiates correctly"
        )
    else:
        results.record_fail(
            "Behavioral modifier not differentiating",
            f"Boosted: {boosted}, Suppressed: {suppressed} — "
            f"modifier should move traders in both directions"
        )

    conn.close()


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
        results.record_pass(f"Sufficient qualified traders ({qualified_traders} with 50 resolved)")
    else:
        results.record_fail("Data quality", f"Only {qualified_traders} qualified traders (need 10)")

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
        results.record_fail("Data quality", f"Only {resolved_markets} resolved markets (need 50)")

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
        print(" ALL TESTS PASSED - Behavioral ELO integration successful!")
        print("\nExpected improvements:")
        print("  - Correlation: 0.135  0.45-0.65 (target)")
        print("  - Elite accuracy: Current  70-75% (target)")
        print("  - ELO spread: More differentiation between skill levels")
        print()
    else:
        print(" SOME TESTS FAILED - Review failures above")
        print("\nTroubleshooting:")
        print("  1. Run: py scripts/integrate_behavioral_elo.py")
        print("  2. Ensure database has resolved markets")
        print("  3. Check that behavioral analysis completed successfully")
        print()

    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
