#!/usr/bin/env python3
"""Optimize ELO system parameters by testing different K-factors.

This script:
1. Loads simulation traders (recent, low trade count)
2. Tests K-factors from specified range
3. Calculates correlation and accuracy metrics for each
4. Finds optimal K-factor based on target metric
5. Generates detailed optimization report
"""

import sqlite3
import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Any

sys.path.insert(0, str(Path(__file__).parent))
from _sim_db_guard import add_sim_db_args, resolve_sim_db, SIM_DB_DEFAULT


class ELOOptimizer:
    """Optimize ELO parameters for simulation data."""

    def __init__(self, db_path: str = SIM_DB_DEFAULT):
        self.db_path = db_path
        self.traders = []
        self.resolved_markets = []

    def load_simulation_traders(self, simulation_age_days: int = 7) -> int:
        """Load simulation traders (recent traders with low trade counts)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        # Get simulation traders
        cursor.execute('''
            SELECT address, win_rate, total_trades
            FROM traders
            WHERE last_updated > ?
            AND total_trades > 0
            AND total_trades < 100
            ORDER BY win_rate DESC
        ''', (cutoff,))

        rows = cursor.fetchall()
        self.traders = [
            {'address': row[0], 'win_rate': row[1], 'total_trades': row[2]}
            for row in rows
        ]

        conn.close()
        return len(self.traders)

    def load_resolved_markets(self, simulation_age_days: int = 7) -> int:
        """Load resolved markets with trades from simulation traders."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        # Get trader addresses
        trader_addresses = [t['address'] for t in self.traders]

        if not trader_addresses:
            conn.close()
            return 0

        # Get resolved markets with trades from these traders
        placeholders = ','.join(['?' for _ in trader_addresses])
        cursor.execute(f'''
            SELECT DISTINCT m.market_id, m.winning_outcome
            FROM markets m
            JOIN trades t ON t.market_id = m.market_id
            WHERE m.winning_outcome IS NOT NULL
            AND t.trader_address IN ({placeholders})
            AND t.timestamp > ?
        ''', tuple(trader_addresses) + (cutoff,))

        rows = cursor.fetchall()
        self.resolved_markets = [
            {'market_id': row[0], 'winning_outcome': row[1]}
            for row in rows
        ]

        conn.close()
        return len(self.resolved_markets)

    def calculate_elo_with_k_factor(self, k_factor: float) -> Dict[str, float]:
        """Calculate ELO ratings with specified K-factor."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Initialize all traders to 1500
        trader_elos = {t['address']: 1500.0 for t in self.traders}

        # Process each resolved market
        for market in self.resolved_markets:
            market_id = market['market_id']
            winning_outcome = market['winning_outcome']

            # Get all trades for this market from simulation traders
            trader_addresses = list(trader_elos.keys())
            placeholders = ','.join(['?' for _ in trader_addresses])

            cursor.execute(f'''
                SELECT trader_address, outcome, shares
                FROM trades
                WHERE market_id = ?
                AND trader_address IN ({placeholders})
                ORDER BY timestamp
            ''', (market_id,) + tuple(trader_addresses))

            trades = cursor.fetchall()

            if not trades:
                continue

            # Group into winners and losers
            winners = [t for t in trades if t[1] == winning_outcome]
            losers = [t for t in trades if t[1] != winning_outcome]

            if not winners or not losers:
                continue

            # Calculate average ELO for each group
            avg_winner_elo = sum(trader_elos[w[0]] for w in winners) / len(winners)
            avg_loser_elo = sum(trader_elos[l[0]] for l in losers) / len(losers)

            # Expected scores
            expected_winner = 1.0 / (1.0 + 10 ** ((avg_loser_elo - avg_winner_elo) / 400))
            expected_loser = 1.0 / (1.0 + 10 ** ((avg_winner_elo - avg_loser_elo) / 400))

            # Update ELO for winners
            for winner in winners:
                trader_addr = winner[0]
                current_elo = trader_elos[trader_addr]
                new_elo = current_elo + k_factor * (1.0 - expected_winner)
                trader_elos[trader_addr] = new_elo

            # Update ELO for losers
            for loser in losers:
                trader_addr = loser[0]
                current_elo = trader_elos[trader_addr]
                new_elo = current_elo + k_factor * (0.0 - expected_loser)
                trader_elos[trader_addr] = new_elo

        conn.close()
        return trader_elos

    def calculate_metrics(self, trader_elos: Dict[str, float]) -> Dict[str, Any]:
        """Calculate performance metrics for ELO ratings."""
        # Add ELO to trader data and sort by ELO
        traders_with_elo = []
        for trader in self.traders:
            if trader['address'] in trader_elos:
                traders_with_elo.append({
                    'address': trader['address'],
                    'win_rate': trader['win_rate'],
                    'elo': trader_elos[trader['address']]
                })

        traders_with_elo.sort(key=lambda t: t['elo'], reverse=True)

        # Add ranks
        for i, trader in enumerate(traders_with_elo, 1):
            trader['rank'] = i

        n = len(traders_with_elo)

        # Calculate correlation
        if n < 2:
            return {
                'correlation': 0.0,
                'elite_accuracy': 0.0,
                'poor_accuracy': 0.0,
                'elo_spread': 0.0,
                'combined_score': 0.0,
                'sample_size': n
            }

        sum_wr = sum(t['win_rate'] for t in traders_with_elo)
        sum_elo = sum(t['elo'] for t in traders_with_elo)
        sum_wr_elo = sum(t['win_rate'] * t['elo'] for t in traders_with_elo)
        sum_wr2 = sum(t['win_rate'] ** 2 for t in traders_with_elo)
        sum_elo2 = sum(t['elo'] ** 2 for t in traders_with_elo)

        numerator = n * sum_wr_elo - sum_wr * sum_elo
        denominator = math.sqrt((n * sum_wr2 - sum_wr**2) * (n * sum_elo2 - sum_elo**2))
        correlation = numerator / denominator if denominator > 0 else 0.0

        # Elite accuracy (>60% win rate in top 20%)
        elite_traders = [t for t in traders_with_elo if t['win_rate'] > 0.60]
        top_20_threshold = n * 0.20
        elite_in_top_20 = [t for t in elite_traders if t['rank'] <= top_20_threshold]
        elite_accuracy = len(elite_in_top_20) / len(elite_traders) if elite_traders else 0.0

        # Poor accuracy (<45% win rate in bottom 50%)
        poor_traders = [t for t in traders_with_elo if t['win_rate'] < 0.45]
        bottom_50_threshold = n * 0.50
        poor_in_bottom_50 = [t for t in poor_traders if t['rank'] > bottom_50_threshold]
        poor_accuracy = len(poor_in_bottom_50) / len(poor_traders) if poor_traders else 0.0

        # ELO spread
        elos = [t['elo'] for t in traders_with_elo]
        elo_spread = max(elos) - min(elos) if elos else 0.0

        # Combined score (weighted average)
        combined_score = (
            correlation * 0.40 +
            elite_accuracy * 0.30 +
            poor_accuracy * 0.20 +
            min(elo_spread / 400, 1.0) * 0.10  # Normalize spread to 0-1
        )

        return {
            'correlation': correlation,
            'elite_accuracy': elite_accuracy,
            'poor_accuracy': poor_accuracy,
            'elo_spread': elo_spread,
            'combined_score': combined_score,
            'sample_size': n
        }

    def optimize_k_factor(
        self,
        k_range: Tuple[int, int] = (16, 40),
        optimize_for: str = 'combined',
        verbose: bool = True
    ) -> Dict[str, Any]:
        """Optimize K-factor across specified range.

        Args:
            k_range: Tuple of (min_k, max_k)
            optimize_for: 'correlation', 'elite_accuracy', 'poor_accuracy', or 'combined'
            verbose: Print progress

        Returns:
            Dictionary with optimization results
        """
        results = []

        if verbose:
            print("=" * 70)
            print("  ELO PARAMETER OPTIMIZATION")
            print("=" * 70)
            print()
            print(f"Sample: {len(self.traders)} traders, {len(self.resolved_markets)} resolved markets")
            print(f"K-factor range: {k_range[0]} - {k_range[1]}")
            print(f"Optimizing for: {optimize_for}")
            print()
            print("Testing K-factors...")
            print()

        # Test each K-factor
        for k in range(k_range[0], k_range[1] + 1, 2):  # Step by 2
            trader_elos = self.calculate_elo_with_k_factor(k)
            metrics = self.calculate_metrics(trader_elos)

            result = {
                'k_factor': k,
                **metrics
            }
            results.append(result)

            if verbose:
                print(f"  K={k:2d}  ->  r={metrics['correlation']:.3f}  "
                      f"elite={metrics['elite_accuracy']:.2%}  "
                      f"poor={metrics['poor_accuracy']:.2%}  "
                      f"score={metrics['combined_score']:.3f}")

        # Find optimal K-factor
        metric_key = {
            'correlation': 'correlation',
            'elite_accuracy': 'elite_accuracy',
            'poor_accuracy': 'poor_accuracy',
            'combined': 'combined_score'
        }[optimize_for]

        best_result = max(results, key=lambda r: r[metric_key])

        if verbose:
            print()
            print("=" * 70)
            print(f"OPTIMAL K-FACTOR: {best_result['k_factor']}")
            print("=" * 70)
            print(f"  Correlation:     {best_result['correlation']:.3f}")
            print(f"  Elite accuracy:  {best_result['elite_accuracy']:.2%}")
            print(f"  Poor accuracy:   {best_result['poor_accuracy']:.2%}")
            print(f"  ELO spread:      {best_result['elo_spread']:.1f} points")
            print(f"  Combined score:  {best_result['combined_score']:.3f}")
            print()

        return {
            'optimal_k_factor': best_result['k_factor'],
            'best_metrics': best_result,
            'all_results': results,
            'optimization_settings': {
                'k_range': k_range,
                'optimize_for': optimize_for,
                'sample_size': len(self.traders),
                'resolved_markets': len(self.resolved_markets)
            }
        }

    def generate_report(self, optimization_results: Dict[str, Any], export_path: str = None):
        """Generate and optionally export optimization report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'optimal_k_factor': optimization_results['optimal_k_factor'],
            'best_metrics': optimization_results['best_metrics'],
            'all_results': optimization_results['all_results'],
            'settings': optimization_results['optimization_settings']
        }

        if export_path:
            with open(export_path, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"[OK] Optimization report exported to: {export_path}")

        return report


def main():
    parser = argparse.ArgumentParser(
        description='Optimize ELO system parameters',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Test K-factors from 16 to 40, optimize for combined score
  py scripts/simulation/optimize_parameters.py --k-range 16 40

  # Optimize specifically for correlation
  py scripts/simulation/optimize_parameters.py --optimize-for correlation

  # Export results to JSON
  py scripts/simulation/optimize_parameters.py --export results/optimization.json
        '''
    )

    parser.add_argument(
        '--k-range',
        type=int,
        nargs=2,
        default=[16, 40],
        metavar=('MIN', 'MAX'),
        help='K-factor range to test (default: 16 40)'
    )

    parser.add_argument(
        '--optimize-for',
        choices=['correlation', 'elite_accuracy', 'poor_accuracy', 'combined'],
        default='combined',
        help='Metric to optimize (default: combined)'
    )

    parser.add_argument(
        '--simulation-age-days',
        type=int,
        default=7,
        help='Consider traders updated within N days as simulation data (default: 7)'
    )

    parser.add_argument(
        '--export',
        type=str,
        metavar='PATH',
        help='Export optimization report to JSON file'
    )

    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress progress output'
    )
    add_sim_db_args(parser)

    args = parser.parse_args()

    # Create optimizer
    db_path = resolve_sim_db(args)
    optimizer = ELOOptimizer(db_path=db_path)

    # Load data
    if not args.quiet:
        print("Loading simulation data...")

    num_traders = optimizer.load_simulation_traders(args.simulation_age_days)
    num_markets = optimizer.load_resolved_markets(args.simulation_age_days)

    if num_traders == 0:
        print("[ERROR] No simulation traders found!")
        print(f"Try increasing --simulation-age-days (current: {args.simulation_age_days})")
        return 1

    if num_markets == 0:
        print("[ERROR] No resolved markets found!")
        return 1

    # Optimize
    results = optimizer.optimize_k_factor(
        k_range=tuple(args.k_range),
        optimize_for=args.optimize_for,
        verbose=not args.quiet
    )

    # Generate report
    optimizer.generate_report(results, args.export)

    return 0


if __name__ == '__main__':
    exit(main())
