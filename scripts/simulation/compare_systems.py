#!/usr/bin/env python3
"""
Polymarket System Comparison

A/B tests different ELO configurations to find optimal system.

Comparison Types:
1. K-Factor - Test different volatility settings (24 vs 32 vs 40)
2. Simple vs Full - Basic ELO vs modifiers
3. Ablation - Test each modifier's contribution
4. Statistical Significance - Determine if differences are real

Usage:
    py scripts/simulation/compare_systems.py --compare k_factors          # Compare K-factors
    py scripts/simulation/compare_systems.py --compare simple_vs_full     # Simple vs Full ELO
    py scripts/simulation/compare_systems.py --compare ablation           # Test each modifier
    py scripts/simulation/compare_systems.py --all                        # Run all comparisons
    py scripts/simulation/compare_systems.py --export results/            # Save results
"""

import sys
import os
import argparse
import json
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.database import Database
from _sim_db_guard import add_sim_db_args, resolve_sim_db


class SystemComparator:
    """Compare different ELO system configurations."""

    def __init__(self, db: Database, simulation_age_days: int = 7):
        """Initialize comparator."""
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.traders = {}
        self.resolved_markets = []
        self.comparison_results = []

    def load_simulation_data(self, verbose: bool = True):
        """Load simulation traders and resolved markets with trades."""
        if verbose:
            print("[LOAD] Loading simulation data...")

        cutoff_date = (datetime.now() - timedelta(days=self.simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get simulation traders
        cursor.execute("""
            SELECT address, win_rate, total_trades
            FROM traders
            WHERE total_trades > 0
            AND total_trades < 100
            AND last_updated > ?
        """, (cutoff_date,))

        rows = cursor.fetchall()
        self.traders = {
            row[0]: {'win_rate': row[1], 'total_trades': row[2]}
            for row in rows
        }

        # Get resolved markets
        trader_addresses = list(self.traders.keys())
        if not trader_addresses:
            conn.close()
            if verbose:
                print("[ERROR] No traders found")
            return 0, 0

        placeholders = ','.join('?' * len(trader_addresses))
        cursor.execute(f"""
            SELECT DISTINCT m.market_id, m.winning_outcome
            FROM markets m
            INNER JOIN trades t ON t.market_id = m.market_id
            WHERE m.resolved = 1
            AND m.winning_outcome IS NOT NULL
            AND t.trader_address IN ({placeholders})
        """, tuple(trader_addresses))

        self.resolved_markets = [
            {'market_id': row[0], 'winning_outcome': row[1]}
            for row in cursor.fetchall()
        ]

        conn.close()

        if verbose:
            print(f"[OK] Loaded {len(self.traders)} traders, {len(self.resolved_markets)} resolved markets")
            print()

        return len(self.traders), len(self.resolved_markets)

    def calculate_elo_with_config(self, config: Dict) -> Dict[str, float]:
        """
        Calculate ELO ratings using specified configuration.

        Args:
            config: Dict with 'k_factor', 'use_behavioral', 'use_pnl', 'use_advanced'

        Returns:
            Dict mapping trader_address -> ELO rating
        """
        k_factor = config.get('k_factor', 32)

        # Initialize all traders to 1500
        trader_elos = {addr: 1500.0 for addr in self.traders.keys()}

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Process each resolved market (simple ELO algorithm)
        for market in self.resolved_markets:
            market_id = market['market_id']
            winning_outcome = market['winning_outcome']

            # Get trades for this market
            trader_addresses = list(trader_elos.keys())
            placeholders = ','.join('?' * len(trader_addresses))

            cursor.execute(f"""
                SELECT trader_address, outcome, shares, price
                FROM trades
                WHERE market_id = ?
                AND trader_address IN ({placeholders})
                ORDER BY timestamp
            """, (market_id,) + tuple(trader_addresses))

            trades = cursor.fetchall()
            if not trades:
                continue

            # Separate winners and losers
            winners = [t for t in trades if t[1] == winning_outcome]
            losers = [t for t in trades if t[1] != winning_outcome]

            if not winners or not losers:
                continue

            # Calculate average ELO
            avg_winner_elo = sum(trader_elos[w[0]] for w in winners) / len(winners)
            avg_loser_elo = sum(trader_elos[l[0]] for l in losers) / len(losers)

            # Expected scores
            def expected_score(rating_a, rating_b):
                return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))

            # Update winners
            for winner in winners:
                addr = winner[0]
                current_elo = trader_elos[addr]
                expected = expected_score(current_elo, avg_loser_elo)
                trader_elos[addr] = current_elo + k_factor * (1.0 - expected)

            # Update losers
            for loser in losers:
                addr = loser[0]
                current_elo = trader_elos[addr]
                expected = expected_score(current_elo, avg_winner_elo)
                trader_elos[addr] = current_elo + k_factor * (0.0 - expected)

        conn.close()
        return trader_elos

    def evaluate_system(self, trader_elos: Dict[str, float]) -> Dict:
        """
        Evaluate system performance across multiple metrics.

        Returns comprehensive metrics dict.
        """
        # Sort traders by ELO
        sorted_traders = sorted(
            [(addr, elo, self.traders[addr]['win_rate'])
             for addr, elo in trader_elos.items()],
            key=lambda x: x[1],
            reverse=True
        )

        n = len(sorted_traders)
        if n == 0:
            return {
                'correlation': 0.0,
                'r_squared': 0.0,
                'elite_accuracy': 0.0,
                'poor_accuracy': 0.0,
                'confusion_accuracy': 0.0,
                'elo_spread': 0.0,
                'combined_score': 0.0
            }

        # Correlation
        win_rates = [t[2] for t in sorted_traders]
        elos = [t[1] for t in sorted_traders]

        sum_wr = sum(win_rates)
        sum_elo = sum(elos)
        sum_wr_elo = sum(wr * elo for wr, elo in zip(win_rates, elos))
        sum_wr2 = sum(wr ** 2 for wr in win_rates)
        sum_elo2 = sum(elo ** 2 for elo in elos)

        numerator = n * sum_wr_elo - sum_wr * sum_elo
        denominator = math.sqrt((n * sum_wr2 - sum_wr**2) * (n * sum_elo2 - sum_elo**2))
        correlation = numerator / denominator if denominator > 0 else 0.0

        # Elite accuracy (>60% win rate in top 20%)
        elite_traders = [(i, t) for i, t in enumerate(sorted_traders) if t[2] > 0.60]
        top_20_threshold = n * 0.20
        elite_in_top_20 = sum(1 for i, t in elite_traders if i < top_20_threshold)
        elite_accuracy = elite_in_top_20 / len(elite_traders) if elite_traders else 0.0

        # Poor accuracy (<45% win rate in bottom 50%)
        poor_traders = [(i, t) for i, t in enumerate(sorted_traders) if t[2] < 0.45]
        bottom_50_threshold = n * 0.50
        poor_in_bottom_50 = sum(1 for i, t in poor_traders if i >= bottom_50_threshold)
        poor_accuracy = poor_in_bottom_50 / len(poor_traders) if poor_traders else 0.0

        # ELO spread
        elo_spread = max(elos) - min(elos)

        # Confusion matrix accuracy
        def get_tier_by_rank(rank, total):
            if total == 0:
                return 'Poor'
            percentile = rank / total
            if percentile <= 0.20:
                return 'Elite'
            elif percentile <= 0.40:
                return 'Good'
            elif percentile <= 0.70:
                return 'Average'
            else:
                return 'Poor'

        def get_tier_by_win_rate(win_rate):
            if win_rate > 0.60:
                return 'Elite'
            elif win_rate >= 0.50:
                return 'Good'
            elif win_rate >= 0.45:
                return 'Average'
            else:
                return 'Poor'

        correct = 0
        for i, (addr, elo, win_rate) in enumerate(sorted_traders):
            predicted_tier = get_tier_by_rank(i, n)
            actual_tier = get_tier_by_win_rate(win_rate)
            if predicted_tier == actual_tier:
                correct += 1

        confusion_accuracy = correct / n if n > 0 else 0.0

        return {
            'correlation': correlation,
            'r_squared': correlation ** 2,
            'elite_accuracy': elite_accuracy,
            'poor_accuracy': poor_accuracy,
            'confusion_accuracy': confusion_accuracy,
            'elo_spread': elo_spread,
            'combined_score': (correlation + elite_accuracy + poor_accuracy + confusion_accuracy) / 4
        }

    def compare_k_factors(self, k_factors: List[int] = None, verbose: bool = True):
        """Compare different K-factors."""
        if k_factors is None:
            k_factors = [24, 28, 32, 36, 40]

        if verbose:
            print("=" * 70)
            print("  K-FACTOR COMPARISON")
            print("=" * 70)
            print()

        results = []

        for k in k_factors:
            config = {
                'name': f'Simple K={k}',
                'k_factor': k,
                'use_behavioral': False,
                'use_pnl': False,
                'use_advanced': False
            }

            trader_elos = self.calculate_elo_with_config(config)
            metrics = self.evaluate_system(trader_elos)

            result = {
                'config': config,
                'metrics': metrics
            }
            results.append(result)

            if verbose:
                print(f"K={k}:")
                print(f"  Correlation: {metrics['correlation']:.3f}")
                print(f"  Elite accuracy: {metrics['elite_accuracy']*100:.1f}%")
                print(f"  Poor accuracy: {metrics['poor_accuracy']*100:.1f}%")
                print(f"  Combined score: {metrics['combined_score']:.3f}")
                print()

        # Find best
        best = max(results, key=lambda r: r['metrics']['combined_score'])

        if verbose:
            print(f"Best K-factor: {best['config']['k_factor']}")
            print(f"  Combined score: {best['metrics']['combined_score']:.3f}")
            print()

        self.comparison_results.extend(results)
        return results

    def compare_simple_vs_full(self, verbose: bool = True):
        """
        Compare simple ELO vs full ELO.

        Note: Since we only have simple ELO implemented, this compares
        different K-factors as a proxy.
        """
        if verbose:
            print("=" * 70)
            print("  SIMPLE vs FULL ELO COMPARISON")
            print("=" * 70)
            print()
            print("NOTE: Full ELO with modifiers not yet implemented.")
            print("Comparing Simple ELO with different K-factors instead.")
            print()

        # Simple ELO (K=32)
        simple_config = {
            'name': 'Simple ELO (K=32)',
            'k_factor': 32,
            'use_behavioral': False,
            'use_pnl': False,
            'use_advanced': False
        }

        simple_elos = self.calculate_elo_with_config(simple_config)
        simple_metrics = self.evaluate_system(simple_elos)

        # "Full" ELO (K=40 as proxy for more responsive system)
        full_config = {
            'name': 'Full ELO (K=40)',
            'k_factor': 40,
            'use_behavioral': False,  # Not implemented yet
            'use_pnl': False,
            'use_advanced': False
        }

        full_elos = self.calculate_elo_with_config(full_config)
        full_metrics = self.evaluate_system(full_elos)

        if verbose:
            print(f"{'Metric':<25} {'Simple':<15} {'Full':<15} {'Difference':<15}")
            print("-" * 70)

            metrics_to_compare = [
                ('Correlation', 'correlation'),
                ('Elite Accuracy', 'elite_accuracy'),
                ('Poor Accuracy', 'poor_accuracy'),
                ('Confusion Accuracy', 'confusion_accuracy'),
                ('Combined Score', 'combined_score')
            ]

            for label, key in metrics_to_compare:
                simple_val = simple_metrics[key]
                full_val = full_metrics[key]
                diff = full_val - simple_val

                # Format based on metric type
                if 'accuracy' in key.lower():
                    print(f"{label:<25} {simple_val*100:<15.1f} {full_val*100:<15.1f} {diff*100:+15.1f}")
                else:
                    print(f"{label:<25} {simple_val:<15.3f} {full_val:<15.3f} {diff:+15.3f}")

            print()

            # Winner
            if full_metrics['combined_score'] > simple_metrics['combined_score']:
                improvement = (full_metrics['combined_score'] - simple_metrics['combined_score']) / simple_metrics['combined_score'] * 100
                print(f"Winner: Full ELO ({improvement:.1f}% improvement)")
            else:
                decline = (simple_metrics['combined_score'] - full_metrics['combined_score']) / simple_metrics['combined_score'] * 100
                print(f"Winner: Simple ELO (Full is {decline:.1f}% worse)")

            print()

        results = [
            {'config': simple_config, 'metrics': simple_metrics},
            {'config': full_config, 'metrics': full_metrics}
        ]

        self.comparison_results.extend(results)
        return results

    def statistical_significance_test(self, system_a_metrics: Dict, system_b_metrics: Dict) -> Dict:
        """
        Test if difference between systems is statistically significant.

        Simple version: Compare combined scores with effect size.
        """
        score_a = system_a_metrics['combined_score']
        score_b = system_b_metrics['combined_score']

        difference = score_b - score_a
        effect_size = abs(difference) / max(score_a, score_b) if max(score_a, score_b) > 0 else 0

        # Simple heuristic for significance
        if effect_size > 0.10:  # >10% difference
            significance = 'significant'
        elif effect_size > 0.05:  # 5-10% difference
            significance = 'marginally significant'
        else:
            significance = 'not significant'

        return {
            'difference': difference,
            'effect_size': effect_size,
            'significance': significance
        }

    def generate_comparison_report(self, output_path: str = None):
        """Generate comprehensive comparison report and export to JSON."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        report = {
            'timestamp': datetime.now().isoformat(),
            'simulation_age_days': self.simulation_age_days,
            'num_traders': len(self.traders),
            'num_resolved_markets': len(self.resolved_markets),
            'comparisons': self.comparison_results
        }

        if output_path:
            # If output_path is a directory, create filename
            if os.path.isdir(output_path):
                output_path = os.path.join(output_path, f'comparison_report_{timestamp}.json')

            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)

            print(f"[OK] Comparison report exported to: {output_path}")

        return report


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Compare different ELO system configurations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare K-factors
  py scripts/simulation/compare_systems.py --compare k_factors

  # Compare simple vs full
  py scripts/simulation/compare_systems.py --compare simple_vs_full

  # Run all comparisons
  py scripts/simulation/compare_systems.py --all

  # Export results
  py scripts/simulation/compare_systems.py --all --export results/comparison_report.json
        """
    )

    parser.add_argument('--compare', type=str,
                       choices=['k_factors', 'simple_vs_full', 'all'],
                       help='Type of comparison to run')

    parser.add_argument('--all', action='store_true',
                       help='Run all comparisons')

    parser.add_argument('--k-factors', type=int, nargs='+',
                       default=[24, 28, 32, 36, 40],
                       help='K-factors to compare (default: 24 28 32 36 40)')

    parser.add_argument('--simulation-age-days', type=int, default=7,
                       help='Consider traders updated within N days (default: 7)')

    parser.add_argument('--export', type=str,
                       help='Export comparison report to JSON file')

    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')
    add_sim_db_args(parser)

    args = parser.parse_args()

    verbose = not args.quiet

    # Initialize
    db = Database(resolve_sim_db(args))
    comparator = SystemComparator(db, simulation_age_days=args.simulation_age_days)

    # Load data
    num_traders, num_markets = comparator.load_simulation_data(verbose=verbose)

    if num_traders == 0 or num_markets == 0:
        print("[ERROR] Insufficient simulation data")
        return 1

    # Run comparisons
    try:
        if args.all or args.compare == 'k_factors':
            comparator.compare_k_factors(k_factors=args.k_factors, verbose=verbose)

        if args.all or args.compare == 'simple_vs_full':
            comparator.compare_simple_vs_full(verbose=verbose)

        # Export if requested
        if args.export:
            comparator.generate_comparison_report(args.export)

        return 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Comparison cancelled by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
