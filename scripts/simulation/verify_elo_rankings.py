#!/usr/bin/env python3
"""
Polymarket ELO Rankings Verification

Validates that ELO system accurately ranks traders by skill level.

Tests:
1. Elite traders (>60% win rate) rank in top 20%
2. Poor traders (<45% win rate) rank in bottom 50%
3. ELO spread is reasonable (200-800 points)
4. Clear separation between skill tiers

Usage:
    py scripts/verify_elo_rankings.py                    # Run all tests
    py scripts/verify_elo_rankings.py --verbose          # Detailed output
    py scripts/verify_elo_rankings.py --export results/  # Save report
    py scripts/verify_elo_rankings.py --threshold 0.7    # Custom pass rate
"""

import sys
import os
import argparse
import math
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database


class ELORankingsValidator:
    """Validate ELO rankings against known skill levels."""

    def __init__(self, db: Database, simulation_age_days: int = 1):
        """
        Initialize validator.

        Args:
            db: Database instance
            simulation_age_days: Only analyze traders updated in last N days
        """
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.traders = []
        self.test_results = []

    def load_simulation_traders(self, verbose: bool = True):
        """Load simulation traders (recent updates, low trade counts)."""
        if verbose:
            print("[LOAD] Loading simulation traders...")

        cutoff_date = (datetime.now() - timedelta(days=self.simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                total_trades,
                successful_trades,
                win_rate,
                last_updated
            FROM traders
            WHERE total_trades > 0
            AND total_trades < 100
            AND last_updated > ?
            AND comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
        """, (cutoff_date,))

        rows = cursor.fetchall()
        conn.close()

        self.traders = [
            {
                'address': row[0],
                'elo': row[1],
                'base_elo': row[2],
                'total_trades': row[3],
                'successful_trades': row[4],
                'win_rate': row[5],
                'last_updated': row[6],
                'rank': i + 1,
                'percentile': (i + 1) / len(rows)
            }
            for i, row in enumerate(rows)
        ]

        if verbose:
            print(f"[OK] Loaded {len(self.traders)} simulation traders")
            if self.traders:
                print(f"     ELO range: {self.traders[-1]['elo']:.1f} - {self.traders[0]['elo']:.1f}")
            print()

        return len(self.traders)

    def test_elite_ranking(self, threshold: float = 0.70) -> bool:
        """Test that elite traders (>60% win rate) rank in top 20%."""
        print("[TEST 1] Elite traders in top 20%...")

        # Find elite traders (win rate > 60%)
        elite_traders = [t for t in self.traders if t['win_rate'] > 0.60]

        # Find how many are in top 20%
        top_20_threshold = len(self.traders) * 0.20
        elite_in_top_20 = [t for t in elite_traders if t['rank'] <= top_20_threshold]

        # Calculate pass rate
        if elite_traders:
            pass_rate = len(elite_in_top_20) / len(elite_traders)
        else:
            pass_rate = 0.0

        # Determine pass/fail
        passed = pass_rate >= threshold

        # Display results
        print(f"  Elite traders total: {len(elite_traders)}")
        print(f"  Elite in top 20%: {len(elite_in_top_20)} ({pass_rate*100:.1f}%)")

        if passed:
            print(f"  [OK] PASS (>={threshold*100:.0f}% of elite in top 20%)")
        else:
            print(f"  [X] FAIL (<{threshold*100:.0f}% of elite in top 20%)")
            # Show misranked elite traders
            elite_outside_top_20 = [t for t in elite_traders if t['rank'] > top_20_threshold]
            if elite_outside_top_20:
                print(f"  Misranked elite traders:")
                for t in elite_outside_top_20[:5]:
                    print(f"    - Rank {t['rank']}: {t['address'][:20]}... (win={t['win_rate']*100:.1f}%, ELO={t['elo']:.1f})")

        print()

        # Store result
        self.test_results.append({
            'test': 'Elite Ranking',
            'passed': passed,
            'pass_rate': pass_rate,
            'threshold': threshold,
            'details': f"{len(elite_in_top_20)}/{len(elite_traders)} elite in top 20%"
        })

        return passed

    def test_poor_ranking(self, threshold: float = 0.70) -> bool:
        """Test that poor traders (<45% win rate) rank in bottom 50%."""
        print("[TEST 2] Poor traders in bottom 50%...")

        # Find poor traders (win rate < 45%)
        poor_traders = [t for t in self.traders if t['win_rate'] < 0.45]

        # Find how many are in bottom 50%
        bottom_50_threshold = len(self.traders) * 0.50
        poor_in_bottom_50 = [t for t in poor_traders if t['rank'] > bottom_50_threshold]

        # Calculate pass rate
        if poor_traders:
            pass_rate = len(poor_in_bottom_50) / len(poor_traders)
        else:
            pass_rate = 0.0

        # Determine pass/fail
        passed = pass_rate >= threshold

        # Display results
        print(f"  Poor traders total: {len(poor_traders)}")
        print(f"  Poor in bottom 50%: {len(poor_in_bottom_50)} ({pass_rate*100:.1f}%)")

        if passed:
            print(f"  [OK] PASS (>={threshold*100:.0f}% of poor in bottom 50%)")
        else:
            print(f"  [X] FAIL (<{threshold*100:.0f}% of poor in bottom 50%)")
            # Show misranked poor traders
            poor_outside_bottom_50 = [t for t in poor_traders if t['rank'] <= bottom_50_threshold]
            if poor_outside_bottom_50:
                print(f"  Misranked poor traders:")
                for t in poor_outside_bottom_50[:5]:
                    print(f"    - Rank {t['rank']}: {t['address'][:20]}... (win={t['win_rate']*100:.1f}%, ELO={t['elo']:.1f})")

        print()

        # Store result
        self.test_results.append({
            'test': 'Poor Ranking',
            'passed': passed,
            'pass_rate': pass_rate,
            'threshold': threshold,
            'details': f"{len(poor_in_bottom_50)}/{len(poor_traders)} poor in bottom 50%"
        })

        return passed

    def test_elo_spread(self) -> bool:
        """Test that ELO spread is reasonable (200-800 points)."""
        print("[TEST 3] ELO rating spread...")

        if not self.traders:
            print("  [X] FAIL (no traders loaded)")
            return False

        highest_elo = self.traders[0]['elo']  # First (highest ranked)
        lowest_elo = self.traders[-1]['elo']  # Last (lowest ranked)
        elo_range = highest_elo - lowest_elo

        # Acceptable range: 200-800 points
        passed = 200 <= elo_range <= 800

        print(f"  Highest ELO: {highest_elo:.1f}")
        print(f"  Lowest ELO: {lowest_elo:.1f}")
        print(f"  ELO range: {elo_range:.1f} points")

        if passed:
            print(f"  [OK] PASS (range 200-800 points)")
        else:
            if elo_range < 200:
                print(f"  [X] FAIL (range too narrow - insufficient discrimination)")
            else:
                print(f"  [X] FAIL (range too wide - possible overfitting)")

        print()

        # Store result
        self.test_results.append({
            'test': 'ELO Spread',
            'passed': passed,
            'elo_range': elo_range,
            'details': f"{elo_range:.1f} points (target: 200-800)"
        })

        return passed

    def test_correlation(self, min_correlation: float = 0.5) -> bool:
        """Test that win rate <-> ELO correlation is strong."""
        print("[TEST 4] Win Rate <-> ELO correlation...")

        if len(self.traders) < 2:
            print("  [X] FAIL (insufficient traders)")
            return False

        # Calculate Pearson correlation coefficient
        n = len(self.traders)
        sum_wr = sum(t['win_rate'] for t in self.traders)
        sum_elo = sum(t['elo'] for t in self.traders)
        sum_wr_elo = sum(t['win_rate'] * t['elo'] for t in self.traders)
        sum_wr2 = sum(t['win_rate'] ** 2 for t in self.traders)
        sum_elo2 = sum(t['elo'] ** 2 for t in self.traders)

        numerator = n * sum_wr_elo - sum_wr * sum_elo
        denominator = math.sqrt((n * sum_wr2 - sum_wr**2) * (n * sum_elo2 - sum_elo**2))

        if denominator > 0:
            correlation = numerator / denominator
        else:
            correlation = 0.0

        passed = correlation >= min_correlation

        print(f"  Correlation: r = {correlation:.3f}")
        print(f"  R² (variance explained): {correlation**2:.3f}")

        if passed:
            if correlation > 0.7:
                print(f"  [OK] PASS (strong positive correlation)")
            else:
                print(f"  [OK] PASS (moderate positive correlation)")
        else:
            print(f"  [X] FAIL (correlation below {min_correlation})")

        print()

        # Store result
        self.test_results.append({
            'test': 'Correlation',
            'passed': passed,
            'correlation': correlation,
            'r_squared': correlation ** 2,
            'details': f"r = {correlation:.3f} (target: >={min_correlation})"
        })

        return passed

    def test_bucket_separation(self) -> bool:
        """Test that there's clear ELO separation between skill buckets."""
        print("[TEST 5] ELO bucket separation...")

        # Define buckets by win rate
        buckets = {
            'Elite (>60%)': [t for t in self.traders if t['win_rate'] > 0.60],
            'Good (50-60%)': [t for t in self.traders if 0.50 <= t['win_rate'] <= 0.60],
            'Average (45-50%)': [t for t in self.traders if 0.45 <= t['win_rate'] < 0.50],
            'Poor (<45%)': [t for t in self.traders if t['win_rate'] < 0.45]
        }

        # Calculate average ELO for each bucket
        bucket_avg_elos = {}
        for bucket_name, traders in buckets.items():
            if traders:
                bucket_avg_elos[bucket_name] = sum(t['elo'] for t in traders) / len(traders)
                print(f"  {bucket_name:<20} avg ELO: {bucket_avg_elos[bucket_name]:>7.1f} (n={len(traders)})")

        print()

        # Test monotonic decrease: Elite > Good > Average > Poor
        bucket_order = ['Elite (>60%)', 'Good (50-60%)', 'Average (45-50%)', 'Poor (<45%)']
        valid_buckets = [b for b in bucket_order if b in bucket_avg_elos]

        monotonic = True
        for i in range(len(valid_buckets) - 1):
            current_bucket = valid_buckets[i]
            next_bucket = valid_buckets[i + 1]

            if bucket_avg_elos[current_bucket] <= bucket_avg_elos[next_bucket]:
                monotonic = False
                print(f"  [X] Violation: {current_bucket} ({bucket_avg_elos[current_bucket]:.1f}) <= {next_bucket} ({bucket_avg_elos[next_bucket]:.1f})")

        if monotonic:
            print(f"  [OK] PASS (monotonic decrease: Elite > Good > Average > Poor)")
        else:
            print(f"  [X] FAIL (buckets not properly separated)")

        print()

        # Store result
        self.test_results.append({
            'test': 'Bucket Separation',
            'passed': monotonic,
            'bucket_elos': bucket_avg_elos,
            'details': 'Monotonic' if monotonic else 'Non-monotonic'
        })

        return monotonic

    def run_all_tests(self, verbose: bool = True, elite_threshold: float = 0.70,
                      poor_threshold: float = 0.70, min_correlation: float = 0.5):
        """Run all validation tests."""
        if verbose:
            print("=" * 70)
            print("  POLYMARKET ELO VALIDATION")
            print("=" * 70)
            print()

        # Load traders
        num_traders = self.load_simulation_traders(verbose=verbose)

        if num_traders == 0:
            print("[ERROR] No simulation traders found")
            return {'passed': False, 'error': 'No traders'}

        # Run all tests
        test1 = self.test_elite_ranking(threshold=elite_threshold)
        test2 = self.test_poor_ranking(threshold=poor_threshold)
        test3 = self.test_elo_spread()
        test4 = self.test_correlation(min_correlation=min_correlation)
        test5 = self.test_bucket_separation()

        # Calculate overall pass/fail
        all_passed = all([test1, test2, test3, test4, test5])
        num_passed = sum([test1, test2, test3, test4, test5])

        # Print summary
        if verbose:
            print("=" * 70)
            print("  VALIDATION SUMMARY")
            print("=" * 70)
            print()
            print(f"Tests passed: {num_passed}/5")
            print()

            for result in self.test_results:
                status = "[OK] PASS" if result['passed'] else "[X] FAIL"
                print(f"  {status} - {result['test']}: {result['details']}")

            print()

            if all_passed:
                print("SUCCESS - ALL TESTS PASSED - ELO system validated!")
            else:
                print("WARNING - SOME TESTS FAILED - Review results above")

            print()
            print("=" * 70)
            print()

        return {
            'passed': all_passed,
            'num_passed': num_passed,
            'num_tests': 5,
            'traders_analyzed': num_traders,
            'test_results': self.test_results
        }

    def generate_report(self, output_path: str = None):
        """Generate detailed validation report."""
        if output_path:
            output_dir = Path(output_path)
            output_dir.mkdir(exist_ok=True, parents=True)

            output_file = output_dir / f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            report = {
                'timestamp': datetime.now().isoformat(),
                'traders_analyzed': len(self.traders),
                'test_results': self.test_results,
                'summary': {
                    'total_tests': len(self.test_results),
                    'passed': sum(1 for r in self.test_results if r['passed']),
                    'failed': sum(1 for r in self.test_results if not r['passed'])
                }
            }

            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)

            print(f"[OK] Validation report exported to: {output_file}")
            print()


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Validate Polymarket ELO rankings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/verify_elo_rankings.py                      # Run all tests
  py scripts/verify_elo_rankings.py --verbose            # Detailed output
  py scripts/verify_elo_rankings.py --export results/    # Save report
  py scripts/verify_elo_rankings.py --threshold 0.6      # Custom pass rate (60%)
  py scripts/verify_elo_rankings.py --min-correlation 0.6
        """
    )

    parser.add_argument('--verbose', action='store_true',
                       help='Detailed output')
    parser.add_argument('--export', type=str,
                       help='Export report to directory')
    parser.add_argument('--threshold', type=float, default=0.70,
                       help='Pass rate threshold for elite/poor tests (default: 0.70)')
    parser.add_argument('--min-correlation', type=float, default=0.5,
                       help='Minimum correlation for pass (default: 0.5)')
    parser.add_argument('--simulation-age-days', type=int, default=1,
                       help='Only analyze traders updated in last N days (default: 1)')

    args = parser.parse_args()

    # Initialize
    db = Database()
    validator = ELORankingsValidator(db, simulation_age_days=args.simulation_age_days)

    # Run tests
    try:
        results = validator.run_all_tests(
            verbose=True,
            elite_threshold=args.threshold,
            poor_threshold=args.threshold,
            min_correlation=args.min_correlation
        )

        # Export if requested
        if args.export:
            validator.generate_report(args.export)

        # Exit code based on results
        sys.exit(0 if results['passed'] else 1)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Validation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
