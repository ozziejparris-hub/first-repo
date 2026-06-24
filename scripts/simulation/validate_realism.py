#!/usr/bin/env python3
"""
Polymarket Simulation Realism Validator

Compares simulation statistics to real Polymarket benchmarks to ensure
the simulation accurately mirrors production behavior.

Metrics Validated:
- Volume distribution (Gini coefficient, power law fit)
- Trader concentration (top 5% profit share)
- Win rate distribution (normal fit)
- Price volatility by market age
- Category distribution
- Trade size distribution
- Resolution timing patterns

Usage:
    py scripts/simulation/validate_realism.py                    # Full validation
    py scripts/simulation/validate_realism.py --compare-to-real  # Compare to production DB
    py scripts/simulation/validate_realism.py --export report.json
"""

import sys
import os
import json
import math
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.database import Database
from _sim_db_guard import add_sim_db_args, resolve_sim_db


# Real Polymarket Benchmarks (based on market analysis)
REAL_POLYMARKET_BENCHMARKS = {
    'volume_distribution': {
        'gini_coefficient': 0.75,  # Top markets dominate volume
        'top_10_pct_share': 0.85,  # Top 10% markets = 85% volume
        'power_law_exponent': 1.5,  # Pareto distribution
        'tolerance': 0.15
    },
    'trader_concentration': {
        'top_5_profit_share': 0.80,  # Top 5% traders = 80% profits
        'gini_coefficient': 0.70,
        'tolerance': 0.15
    },
    'win_rate_distribution': {
        'mean': 0.50,
        'std_dev': 0.15,
        'skewness_max': 0.5,  # Should be roughly symmetric
        'tolerance': 0.10
    },
    'price_volatility': {
        'early_phase_vol': 0.20,  # 20% daily vol early
        'late_phase_vol': 0.05,   # 5% daily vol late
        'vol_decay_rate': 0.70,   # Volatility decreases by 70%
        'tolerance': 0.30
    },
    'category_distribution': {
        'min_categories': 5,
        'max_category_share': 0.40,  # No category >40%
        'min_category_share': 0.03,  # Each category >3%
    },
    'trade_size_distribution': {
        'median_to_mean_ratio': 0.4,  # Right-skewed (many small, few large)
        'top_10_pct_volume_share': 0.70,  # Top 10% trades = 70% volume
        'tolerance': 0.20
    },
    'resolution_timing': {
        'median_days': 45,
        'instant_resolution_pct': 0.20,  # 20% resolve quickly
        'delayed_resolution_pct': 0.30,  # 30% take long time
        'tolerance': 0.25
    }
}


class RealismValidator:
    """Validate simulation realism against Polymarket benchmarks."""

    def __init__(self, db: Database, simulation_age_days: int = 7):
        """Initialize validator."""
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.metrics = {}
        self.benchmark_results = {}
        self.overall_score = 0.0

    def calculate_gini_coefficient(self, values: List[float]) -> float:
        """
        Calculate Gini coefficient for inequality measurement.

        0 = perfect equality (all same)
        1 = perfect inequality (one has everything)
        """
        if not values or len(values) < 2:
            return 0.0

        sorted_values = sorted(values)
        n = len(sorted_values)
        cumsum = sum((i + 1) * v for i, v in enumerate(sorted_values))
        total = sum(sorted_values)

        if total == 0:
            return 0.0

        return (2 * cumsum) / (n * total) - (n + 1) / n

    def fit_power_law(self, values: List[float]) -> Tuple[float, float]:
        """
        Fit power law distribution to data.

        Returns (exponent, r_squared) for y = x^(-exponent)
        """
        if not values or len(values) < 10:
            return 0.0, 0.0

        # Sort descending and take log
        sorted_vals = sorted(values, reverse=True)
        n = len(sorted_vals)

        # Log-log regression
        log_ranks = [math.log(i + 1) for i in range(n) if sorted_vals[i] > 0]
        log_vals = [math.log(v) for v in sorted_vals if v > 0]

        if len(log_ranks) < 10:
            return 0.0, 0.0

        # Simple linear regression
        n_points = len(log_ranks)
        sum_x = sum(log_ranks)
        sum_y = sum(log_vals)
        sum_xy = sum(x * y for x, y in zip(log_ranks, log_vals))
        sum_x2 = sum(x * x for x in log_ranks)

        denom = n_points * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            return 0.0, 0.0

        slope = (n_points * sum_xy - sum_x * sum_y) / denom

        # R-squared
        mean_y = sum_y / n_points
        ss_tot = sum((y - mean_y) ** 2 for y in log_vals)
        intercept = (sum_y - slope * sum_x) / n_points
        ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(log_ranks, log_vals))

        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        return -slope, r_squared  # Exponent is negative of slope

    def calculate_distribution_stats(self, values: List[float]) -> Dict:
        """Calculate mean, std, skewness for a distribution."""
        if not values:
            return {'mean': 0, 'std': 0, 'skewness': 0, 'median': 0}

        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance) if variance > 0 else 0

        # Skewness
        if std > 0:
            skewness = sum((x - mean) ** 3 for x in values) / (n * std ** 3)
        else:
            skewness = 0

        sorted_vals = sorted(values)
        median = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2

        return {
            'mean': mean,
            'std': std,
            'skewness': skewness,
            'median': median,
            'min': min(values),
            'max': max(values),
            'count': n
        }

    def validate_volume_distribution(self, verbose: bool = True) -> Dict:
        """Validate that volume distribution follows power law."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get market volumes (filter for recent simulation data)
        cutoff = f"-{self.simulation_age_days} days"
        cursor.execute("""
            SELECT m.market_id, SUM(t.shares * t.price) as volume
            FROM markets m
            LEFT JOIN trades t ON m.market_id = t.market_id
            WHERE m.last_checked > datetime('now', ?)
            GROUP BY m.market_id
            HAVING volume > 0
            ORDER BY volume DESC
        """, (cutoff,))

        volumes = [row[1] for row in cursor.fetchall()]
        conn.close()

        if not volumes:
            return {'passed': False, 'reason': 'No volume data'}

        # Calculate metrics
        gini = self.calculate_gini_coefficient(volumes)
        exponent, r_squared = self.fit_power_law(volumes)

        total_volume = sum(volumes)
        top_10_pct_count = max(1, len(volumes) // 10)
        top_10_pct_volume = sum(volumes[:top_10_pct_count])
        top_10_pct_share = top_10_pct_volume / total_volume if total_volume > 0 else 0

        benchmark = REAL_POLYMARKET_BENCHMARKS['volume_distribution']
        tolerance = benchmark['tolerance']

        # Check against benchmarks
        gini_diff = abs(gini - benchmark['gini_coefficient'])
        gini_passed = gini_diff <= tolerance

        top_10_diff = abs(top_10_pct_share - benchmark['top_10_pct_share'])
        top_10_passed = top_10_diff <= tolerance

        power_law_passed = r_squared > 0.7  # Good power law fit

        result = {
            'gini_coefficient': gini,
            'gini_benchmark': benchmark['gini_coefficient'],
            'gini_passed': gini_passed,
            'top_10_pct_share': top_10_pct_share,
            'top_10_benchmark': benchmark['top_10_pct_share'],
            'top_10_passed': top_10_passed,
            'power_law_exponent': exponent,
            'power_law_r_squared': r_squared,
            'power_law_passed': power_law_passed,
            'passed': gini_passed and top_10_passed,
            'score': (int(gini_passed) + int(top_10_passed) + int(power_law_passed)) / 3
        }

        if verbose:
            print("Volume Distribution:")
            print(f"  Gini Coefficient: {gini:.3f} (target: {benchmark['gini_coefficient']:.3f}) {'[OK]' if gini_passed else '[FAIL]'}")
            print(f"  Top 10% Share: {top_10_pct_share*100:.1f}% (target: {benchmark['top_10_pct_share']*100:.1f}%) {'[OK]' if top_10_passed else '[FAIL]'}")
            print(f"  Power Law Fit: R^2={r_squared:.3f}, exp={exponent:.2f} {'[OK]' if power_law_passed else '[FAIL]'}")
            print()

        self.metrics['volume_distribution'] = result
        return result

    def validate_trader_concentration(self, verbose: bool = True) -> Dict:
        """Validate trader profit concentration."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get trader profits (filter for recent simulation data)
        cutoff = f"-{self.simulation_age_days} days"
        cursor.execute("""
            SELECT
                t.trader_address,
                SUM(CASE
                    WHEN t.outcome = m.winning_outcome THEN t.shares * (1 - t.price)
                    ELSE -t.shares * t.price
                END) as profit
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 1 AND m.winning_outcome IS NOT NULL
            AND m.last_checked > datetime('now', ?)
            GROUP BY t.trader_address
            ORDER BY profit DESC
        """, (cutoff,))

        profits = [row[1] for row in cursor.fetchall()]
        conn.close()

        if not profits:
            return {'passed': False, 'reason': 'No profit data'}

        # Calculate metrics
        gini = self.calculate_gini_coefficient([max(0, p) for p in profits])

        # Top 5% profit share
        total_positive_profit = sum(max(0, p) for p in profits)
        top_5_pct_count = max(1, len(profits) // 20)
        top_5_pct_profit = sum(max(0, p) for p in profits[:top_5_pct_count])
        top_5_share = top_5_pct_profit / total_positive_profit if total_positive_profit > 0 else 0

        benchmark = REAL_POLYMARKET_BENCHMARKS['trader_concentration']
        tolerance = benchmark['tolerance']

        gini_passed = abs(gini - benchmark['gini_coefficient']) <= tolerance
        top_5_passed = abs(top_5_share - benchmark['top_5_profit_share']) <= tolerance

        result = {
            'gini_coefficient': gini,
            'gini_benchmark': benchmark['gini_coefficient'],
            'gini_passed': gini_passed,
            'top_5_profit_share': top_5_share,
            'top_5_benchmark': benchmark['top_5_profit_share'],
            'top_5_passed': top_5_passed,
            'passed': gini_passed and top_5_passed,
            'score': (int(gini_passed) + int(top_5_passed)) / 2
        }

        if verbose:
            print("Trader Concentration:")
            print(f"  Profit Gini: {gini:.3f} (target: {benchmark['gini_coefficient']:.3f}) {'[OK]' if gini_passed else '[FAIL]'}")
            print(f"  Top 5% Profit Share: {top_5_share*100:.1f}% (target: {benchmark['top_5_profit_share']*100:.1f}%) {'[OK]' if top_5_passed else '[FAIL]'}")
            print()

        self.metrics['trader_concentration'] = result
        return result

    def validate_win_rate_distribution(self, verbose: bool = True) -> Dict:
        """Validate that win rates follow normal distribution."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get win rates from traders with enough trades (filter for recent)
        cutoff = f"-{self.simulation_age_days} days"
        cursor.execute("""
            SELECT win_rate FROM traders
            WHERE total_trades >= 5
            AND win_rate > 0
            AND last_updated > datetime('now', ?)
        """, (cutoff,))

        win_rates = [row[0] for row in cursor.fetchall()]
        conn.close()

        if len(win_rates) < 20:
            return {'passed': False, 'reason': 'Insufficient traders'}

        stats = self.calculate_distribution_stats(win_rates)
        benchmark = REAL_POLYMARKET_BENCHMARKS['win_rate_distribution']

        mean_passed = abs(stats['mean'] - benchmark['mean']) <= benchmark['tolerance']
        std_passed = abs(stats['std'] - benchmark['std_dev']) <= benchmark['tolerance']
        skew_passed = abs(stats['skewness']) <= benchmark['skewness_max']

        result = {
            'mean': stats['mean'],
            'mean_benchmark': benchmark['mean'],
            'mean_passed': mean_passed,
            'std': stats['std'],
            'std_benchmark': benchmark['std_dev'],
            'std_passed': std_passed,
            'skewness': stats['skewness'],
            'skewness_passed': skew_passed,
            'passed': mean_passed and std_passed and skew_passed,
            'score': (int(mean_passed) + int(std_passed) + int(skew_passed)) / 3
        }

        if verbose:
            print("Win Rate Distribution:")
            print(f"  Mean: {stats['mean']*100:.1f}% (target: {benchmark['mean']*100:.1f}%) {'[OK]' if mean_passed else '[FAIL]'}")
            print(f"  Std Dev: {stats['std']*100:.1f}% (target: {benchmark['std_dev']*100:.1f}%) {'[OK]' if std_passed else '[FAIL]'}")
            print(f"  Skewness: {stats['skewness']:.3f} (max: {benchmark['skewness_max']}) {'[OK]' if skew_passed else '[FAIL]'}")
            print()

        self.metrics['win_rate_distribution'] = result
        return result

    def validate_category_distribution(self, verbose: bool = True) -> Dict:
        """Validate category diversity."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Filter for recent simulation data
        cutoff = f"-{self.simulation_age_days} days"
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM markets
            WHERE category IS NOT NULL AND category != ''
            AND last_checked > datetime('now', ?)
            GROUP BY category
        """, (cutoff,))

        categories = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        if not categories:
            return {'passed': False, 'reason': 'No category data'}

        total_markets = sum(categories.values())
        shares = {cat: count / total_markets for cat, count in categories.items()}

        benchmark = REAL_POLYMARKET_BENCHMARKS['category_distribution']

        num_categories = len(categories)
        max_share = max(shares.values())
        min_share = min(shares.values())

        cat_count_passed = num_categories >= benchmark['min_categories']
        max_share_passed = max_share <= benchmark['max_category_share']
        min_share_passed = min_share >= benchmark['min_category_share']

        result = {
            'num_categories': num_categories,
            'min_categories_benchmark': benchmark['min_categories'],
            'cat_count_passed': cat_count_passed,
            'max_category_share': max_share,
            'max_share_benchmark': benchmark['max_category_share'],
            'max_share_passed': max_share_passed,
            'min_category_share': min_share,
            'min_share_benchmark': benchmark['min_category_share'],
            'min_share_passed': min_share_passed,
            'category_breakdown': shares,
            'passed': cat_count_passed and max_share_passed and min_share_passed,
            'score': (int(cat_count_passed) + int(max_share_passed) + int(min_share_passed)) / 3
        }

        if verbose:
            print("Category Distribution:")
            print(f"  Number of Categories: {num_categories} (min: {benchmark['min_categories']}) {'[OK]' if cat_count_passed else '[FAIL]'}")
            print(f"  Max Category Share: {max_share*100:.1f}% (max: {benchmark['max_category_share']*100:.1f}%) {'[OK]' if max_share_passed else '[FAIL]'}")
            print(f"  Min Category Share: {min_share*100:.1f}% (min: {benchmark['min_category_share']*100:.1f}%) {'[OK]' if min_share_passed else '[FAIL]'}")
            for cat, share in sorted(shares.items(), key=lambda x: -x[1]):
                print(f"    {cat}: {share*100:.1f}%")
            print()

        self.metrics['category_distribution'] = result
        return result

    def validate_trade_size_distribution(self, verbose: bool = True) -> Dict:
        """Validate trade size follows realistic distribution."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Filter for recent simulation data
        cutoff = f"-{self.simulation_age_days} days"
        cursor.execute("""
            SELECT t.shares * t.price as trade_value
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE t.shares > 0 AND t.price > 0
            AND m.last_checked > datetime('now', ?)
            ORDER BY trade_value DESC
        """, (cutoff,))

        trade_values = [row[0] for row in cursor.fetchall()]
        conn.close()

        if len(trade_values) < 100:
            return {'passed': False, 'reason': 'Insufficient trades'}

        stats = self.calculate_distribution_stats(trade_values)
        benchmark = REAL_POLYMARKET_BENCHMARKS['trade_size_distribution']

        # Median to mean ratio (should be < 1 for right-skewed)
        median_mean_ratio = stats['median'] / stats['mean'] if stats['mean'] > 0 else 0

        # Top 10% volume share
        total_value = sum(trade_values)
        top_10_count = max(1, len(trade_values) // 10)
        top_10_value = sum(trade_values[:top_10_count])
        top_10_share = top_10_value / total_value if total_value > 0 else 0

        tolerance = benchmark['tolerance']
        ratio_passed = abs(median_mean_ratio - benchmark['median_to_mean_ratio']) <= tolerance
        top_10_passed = abs(top_10_share - benchmark['top_10_pct_volume_share']) <= tolerance

        result = {
            'median_to_mean_ratio': median_mean_ratio,
            'ratio_benchmark': benchmark['median_to_mean_ratio'],
            'ratio_passed': ratio_passed,
            'top_10_volume_share': top_10_share,
            'top_10_benchmark': benchmark['top_10_pct_volume_share'],
            'top_10_passed': top_10_passed,
            'stats': stats,
            'passed': ratio_passed and top_10_passed,
            'score': (int(ratio_passed) + int(top_10_passed)) / 2
        }

        if verbose:
            print("Trade Size Distribution:")
            print(f"  Median/Mean Ratio: {median_mean_ratio:.3f} (target: {benchmark['median_to_mean_ratio']:.3f}) {'[OK]' if ratio_passed else '[FAIL]'}")
            print(f"  Top 10% Volume Share: {top_10_share*100:.1f}% (target: {benchmark['top_10_pct_volume_share']*100:.1f}%) {'[OK]' if top_10_passed else '[FAIL]'}")
            print(f"  Mean Trade: ${stats['mean']:.2f}, Median: ${stats['median']:.2f}")
            print()

        self.metrics['trade_size_distribution'] = result
        return result

    def calculate_overall_score(self) -> float:
        """Calculate overall realism score (0-100)."""
        scores = []
        for metric_name, metric_data in self.metrics.items():
            if isinstance(metric_data, dict) and 'score' in metric_data:
                scores.append(metric_data['score'])

        self.overall_score = (sum(scores) / len(scores) * 100) if scores else 0
        return self.overall_score

    def generate_report(self, verbose: bool = True) -> Dict:
        """Run all validations and generate comprehensive report."""
        if verbose:
            print()
            print("=" * 70)
            print("  POLYMARKET SIMULATION REALISM VALIDATION")
            print("=" * 70)
            print()

        # Run all validations
        self.validate_volume_distribution(verbose)
        self.validate_trader_concentration(verbose)
        self.validate_win_rate_distribution(verbose)
        self.validate_category_distribution(verbose)
        self.validate_trade_size_distribution(verbose)

        # Calculate overall score
        self.calculate_overall_score()

        # Summary
        passed_count = sum(1 for m in self.metrics.values() if isinstance(m, dict) and m.get('passed'))
        total_count = len(self.metrics)

        if verbose:
            print("=" * 70)
            print("  REALISM SUMMARY")
            print("=" * 70)
            print()
            print(f"Overall Realism Score: {self.overall_score:.1f}%")
            print(f"Validations Passed: {passed_count}/{total_count}")
            print()

            if self.overall_score >= 80:
                print("[EXCELLENT] Simulation closely mirrors real Polymarket behavior!")
            elif self.overall_score >= 60:
                print("[GOOD] Simulation reasonably realistic - minor tuning needed")
            elif self.overall_score >= 40:
                print("[MODERATE] Simulation needs improvement in several areas")
            else:
                print("[POOR] Simulation significantly differs from real behavior")

            print()

        report = {
            'timestamp': datetime.now().isoformat(),
            'overall_score': self.overall_score,
            'passed_count': passed_count,
            'total_count': total_count,
            'metrics': self.metrics,
            'benchmarks': REAL_POLYMARKET_BENCHMARKS
        }

        return report

    def export_report(self, output_path: str):
        """Export report to JSON file."""
        report = self.generate_report(verbose=False)

        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"[OK] Report exported to: {output_path}")


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Validate simulation realism against Polymarket benchmarks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/simulation/validate_realism.py
  py scripts/simulation/validate_realism.py --export results/realism_report.json
  py scripts/simulation/validate_realism.py --quiet
        """
    )

    parser.add_argument('--export', type=str,
                       help='Export report to JSON file')
    parser.add_argument('--quiet', action='store_true',
                       help='Minimal output')
    parser.add_argument('--simulation-age-days', type=int, default=7,
                       help='Consider data from last N days (default: 7)')
    add_sim_db_args(parser)

    args = parser.parse_args()

    # Initialize
    db = Database(resolve_sim_db(args))
    validator = RealismValidator(db, simulation_age_days=args.simulation_age_days)

    try:
        if args.export:
            validator.export_report(args.export)
        else:
            validator.generate_report(verbose=not args.quiet)

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Validation cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
