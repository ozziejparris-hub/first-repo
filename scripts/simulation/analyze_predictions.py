#!/usr/bin/env python3
"""
Polymarket Prediction Analysis

Analyzes ELO system errors to identify improvement opportunities.

Analysis Types:
1. False Positives - High ELO, low actual performance
2. False Negatives - Low ELO, high actual performance
3. Market Difficulty - Which markets hardest to predict
4. Confusion Matrix - Predicted vs actual skill tiers
5. Error Patterns - Common failure modes

Usage:
    py scripts/simulation/analyze_predictions.py                     # Full analysis
    py scripts/simulation/analyze_predictions.py --focus false_positives
    py scripts/simulation/analyze_predictions.py --show-top 20       # Show top 20 errors
    py scripts/simulation/analyze_predictions.py --export results/   # Save report
"""

import sys
import os
import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from monitoring.database import Database


class PredictionAnalyzer:
    """Analyze ELO prediction errors and patterns."""

    def __init__(self, db: Database, simulation_age_days: int = 7):
        """Initialize analyzer."""
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.traders = []
        self.analysis_results = {}

    def load_simulation_traders(self, verbose: bool = True):
        """Load simulation traders with ELO and performance metrics."""
        if verbose:
            print("[LOAD] Loading simulation data...")

        cutoff_date = (datetime.now() - timedelta(days=self.simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                win_rate,
                total_trades,
                successful_trades,
                total_volume
            FROM traders
            WHERE total_trades > 0
            AND total_trades < 100
            AND last_updated > ?
            AND comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
        """, (cutoff_date,))

        rows = cursor.fetchall()

        self.traders = [
            {
                'address': row[0],
                'elo': row[1],
                'win_rate': row[2],
                'total_trades': row[3],
                'successful_trades': row[4],
                'total_volume': row[5],
                'rank': i + 1,
                'percentile': (i + 1) / len(rows) if rows else 0
            }
            for i, row in enumerate(rows)
        ]

        conn.close()

        if verbose:
            print(f"[OK] Loaded {len(self.traders)} traders")
            print()

        return len(self.traders)

    def analyze_false_positives(self, threshold: float = 0.10, verbose: bool = True):
        """
        Find traders with high ELO but low actual win rate.

        False positive = Ranked in top 30% but win rate < 50%

        Args:
            threshold: How far below expected (0.10 = 10 percentage points)
        """
        if verbose:
            print("[ANALYSIS] False Positives (Overrated Traders)")
            print()

        # Define "high ELO" as top 30%
        top_30_threshold = len(self.traders) * 0.30

        false_positives = []

        for trader in self.traders:
            # Is trader in top 30% by ELO?
            if trader['rank'] > top_30_threshold:
                continue

            # Expected win rate for top 30% should be > 50%
            expected_win_rate = 0.50

            # Is actual win rate significantly lower?
            if trader['win_rate'] < (expected_win_rate - threshold):
                error = expected_win_rate - trader['win_rate']

                false_positives.append({
                    'address': trader['address'],
                    'rank': trader['rank'],
                    'elo': trader['elo'],
                    'win_rate': trader['win_rate'],
                    'expected_win_rate': expected_win_rate,
                    'error': error,
                    'total_trades': trader['total_trades']
                })

        # Sort by error magnitude
        false_positives.sort(key=lambda x: x['error'], reverse=True)

        if verbose:
            print(f"  Found {len(false_positives)} false positives")
            print()

            if false_positives:
                print(f"  {'Rank':<6} {'ELO':<10} {'Win Rate':<12} {'Expected':<12} {'Error':<10} {'Trades':<8}")
                print("  " + "-" * 68)

                for fp in false_positives[:10]:
                    print(f"  {fp['rank']:<6} {fp['elo']:<10.1f} {fp['win_rate']*100:<12.1f} "
                          f"{fp['expected_win_rate']*100:<12.1f} {fp['error']*100:<10.1f} {fp['total_trades']:<8}")

                print()

                # Analyze patterns
                avg_trades = sum(fp['total_trades'] for fp in false_positives) / len(false_positives)
                print(f"  Pattern Analysis:")
                print(f"    - Average trades: {avg_trades:.1f}")
                print(f"    - Likely cause: Small sample size / early luck")
                print()

        self.analysis_results['false_positives'] = false_positives
        return false_positives

    def analyze_false_negatives(self, threshold: float = 0.10, verbose: bool = True):
        """
        Find traders with low ELO but high actual win rate.

        False negative = Ranked in bottom 50% but win rate > 55%

        Args:
            threshold: How far above expected (0.10 = 10 percentage points)
        """
        if verbose:
            print("[ANALYSIS] False Negatives (Underrated Traders)")
            print()

        # Define "low ELO" as bottom 50%
        bottom_50_threshold = len(self.traders) * 0.50

        false_negatives = []

        for trader in self.traders:
            # Is trader in bottom 50% by ELO?
            if trader['rank'] <= bottom_50_threshold:
                continue

            # Expected win rate for bottom 50% should be < 50%
            expected_win_rate = 0.45

            # Is actual win rate significantly higher?
            if trader['win_rate'] > (expected_win_rate + threshold):
                error = trader['win_rate'] - expected_win_rate

                false_negatives.append({
                    'address': trader['address'],
                    'rank': trader['rank'],
                    'elo': trader['elo'],
                    'win_rate': trader['win_rate'],
                    'expected_win_rate': expected_win_rate,
                    'error': error,
                    'total_trades': trader['total_trades']
                })

        # Sort by error magnitude
        false_negatives.sort(key=lambda x: x['error'], reverse=True)

        if verbose:
            print(f"  Found {len(false_negatives)} false negatives")
            print()

            if false_negatives:
                print(f"  {'Rank':<6} {'ELO':<10} {'Win Rate':<12} {'Expected':<12} {'Error':<10} {'Trades':<8}")
                print("  " + "-" * 68)

                for fn in false_negatives[:10]:
                    print(f"  {fn['rank']:<6} {fn['elo']:<10.1f} {fn['win_rate']*100:<12.1f} "
                          f"{fn['expected_win_rate']*100:<12.1f} {fn['error']*100:<10.1f} {fn['total_trades']:<8}")

                print()

                # Analyze patterns
                avg_trades = sum(fn['total_trades'] for fn in false_negatives) / len(false_negatives)
                print(f"  Pattern Analysis:")
                print(f"    - Average trades: {avg_trades:.1f}")
                print(f"    - Likely cause: Late bloomers / unlucky early")
                print()

        self.analysis_results['false_negatives'] = false_negatives
        return false_negatives

    def analyze_market_difficulty(self, verbose: bool = True):
        """
        Identify which markets were hardest to predict.

        Difficulty = % of high-ELO traders who got it wrong
        """
        if verbose:
            print("[ANALYSIS] Market Difficulty")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get resolved markets
        trader_addresses = [t['address'] for t in self.traders]
        if not trader_addresses:
            if verbose:
                print("  No traders to analyze")
            conn.close()
            return []

        placeholders = ','.join('?' * len(trader_addresses))

        cursor.execute(f"""
            SELECT DISTINCT
                m.market_id,
                m.title,
                m.winning_outcome
            FROM markets m
            INNER JOIN trades t ON t.market_id = m.market_id
            WHERE m.resolved = 1
            AND m.winning_outcome IS NOT NULL
            AND t.trader_address IN ({placeholders})
        """, tuple(trader_addresses))

        resolved_markets = cursor.fetchall()

        # Get top 20% traders (elite)
        top_20_threshold = len(self.traders) * 0.20
        elite_addresses = [t['address'] for t in self.traders if t['rank'] <= top_20_threshold]

        if not elite_addresses:
            if verbose:
                print("  No elite traders to analyze")
            conn.close()
            return []

        market_difficulty = []

        for market_id, title, winning_outcome in resolved_markets:
            # Get elite trader trades on this market
            elite_placeholders = ','.join('?' * len(elite_addresses))
            cursor.execute(f"""
                SELECT outcome
                FROM trades
                WHERE market_id = ?
                AND trader_address IN ({elite_placeholders})
            """, (market_id,) + tuple(elite_addresses))

            elite_trades = cursor.fetchall()

            if not elite_trades:
                continue

            # Calculate elite success rate
            correct = sum(1 for trade in elite_trades if trade[0] == winning_outcome)
            total = len(elite_trades)
            elite_success_rate = correct / total

            # Difficulty = 1 - success rate (higher = harder)
            difficulty = 1 - elite_success_rate

            market_difficulty.append({
                'market_id': market_id,
                'title': title,
                'winning_outcome': winning_outcome,
                'elite_success_rate': elite_success_rate,
                'difficulty': difficulty,
                'elite_trades': total
            })

        # Sort by difficulty
        market_difficulty.sort(key=lambda x: x['difficulty'], reverse=True)

        conn.close()

        if verbose:
            print(f"  Analyzed {len(market_difficulty)} markets")
            print()
            print(f"  Hardest Markets (Elite Success Rate):")
            print(f"  {'Title':<50} {'Success%':<12} {'Difficulty':<12}")
            print("  " + "-" * 74)

            for m in market_difficulty[:10]:
                title_short = m['title'][:47] + "..." if len(m['title']) > 50 else m['title']
                print(f"  {title_short:<50} {m['elite_success_rate']*100:<12.1f} {m['difficulty']*100:<12.1f}")

            print()

            # Average difficulty
            if market_difficulty:
                avg_difficulty = sum(m['difficulty'] for m in market_difficulty) / len(market_difficulty)
                print(f"  Average difficulty: {avg_difficulty*100:.1f}%")
                print(f"  Average elite success rate: {(1-avg_difficulty)*100:.1f}%")
                print()

        self.analysis_results['market_difficulty'] = market_difficulty
        return market_difficulty

    def generate_confusion_matrix(self, verbose: bool = True):
        """
        Generate confusion matrix of predicted vs actual skill tiers.

        Tiers based on win rate:
        - Elite: >60%
        - Good: 50-60%
        - Average: 45-50%
        - Poor: <45%
        """
        if verbose:
            print("[ANALYSIS] Confusion Matrix (Predicted vs Actual)")
            print()

        # Define tiers
        def get_tier_by_elo(rank, total):
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

        # Build confusion matrix
        matrix = {
            'Elite': {'Elite': 0, 'Good': 0, 'Average': 0, 'Poor': 0},
            'Good': {'Elite': 0, 'Good': 0, 'Average': 0, 'Poor': 0},
            'Average': {'Elite': 0, 'Good': 0, 'Average': 0, 'Poor': 0},
            'Poor': {'Elite': 0, 'Good': 0, 'Average': 0, 'Poor': 0}
        }

        total_traders = len(self.traders)

        for trader in self.traders:
            predicted_tier = get_tier_by_elo(trader['rank'], total_traders)
            actual_tier = get_tier_by_win_rate(trader['win_rate'])

            matrix[predicted_tier][actual_tier] += 1

        # Calculate accuracy
        correct = sum(matrix[tier][tier] for tier in ['Elite', 'Good', 'Average', 'Poor'])
        total = sum(sum(counts.values()) for counts in matrix.values())
        accuracy = correct / total if total > 0 else 0

        # Display matrix
        if verbose:
            print("                     Actual Performance")
            print("               Elite    Good  Average    Poor")
            print("  Predicted:")

            for pred_tier in ['Elite', 'Good', 'Average', 'Poor']:
                counts = matrix[pred_tier]
                print(f"  {pred_tier:<10} {counts['Elite']:>6} {counts['Good']:>7} "
                      f"{counts['Average']:>8} {counts['Poor']:>7}")

            print()
            print(f"  Overall Accuracy: {accuracy*100:.1f}% ({correct}/{total} correct)")
            print()

        self.analysis_results['confusion_matrix'] = matrix
        self.analysis_results['confusion_matrix_accuracy'] = {
            'correct': correct,
            'total': total,
            'accuracy': accuracy
        }
        return matrix

    def generate_report(self, output_path: str = None):
        """Generate comprehensive analysis report and export to JSON."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        report = {
            'timestamp': datetime.now().isoformat(),
            'simulation_age_days': self.simulation_age_days,
            'num_traders': len(self.traders),
            'analysis': self.analysis_results
        }

        if output_path:
            # If output_path is a directory, create filename
            if os.path.isdir(output_path):
                output_path = os.path.join(output_path, f'analysis_report_{timestamp}.json')

            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)

            print(f"[OK] Analysis report exported to: {output_path}")

        return report


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Analyze ELO prediction errors and patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full analysis
  py scripts/simulation/analyze_predictions.py

  # Focus on specific analysis
  py scripts/simulation/analyze_predictions.py --focus false_positives
  py scripts/simulation/analyze_predictions.py --focus market_difficulty

  # Show more results
  py scripts/simulation/analyze_predictions.py --show-top 20

  # Export report
  py scripts/simulation/analyze_predictions.py --export results/analysis_report.json
        """
    )

    parser.add_argument('--focus', type=str,
                       choices=['false_positives', 'false_negatives', 'market_difficulty', 'confusion_matrix', 'all'],
                       default='all',
                       help='Focus on specific analysis')

    parser.add_argument('--show-top', type=int, default=10,
                       help='Number of top errors to show (default: 10)')

    parser.add_argument('--threshold', type=float, default=0.10,
                       help='Error threshold for false pos/neg (default: 0.10)')

    parser.add_argument('--simulation-age-days', type=int, default=7,
                       help='Consider traders updated within N days (default: 7)')

    parser.add_argument('--export', type=str,
                       help='Export analysis report to JSON file')

    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')

    args = parser.parse_args()

    verbose = not args.quiet

    # Initialize
    db = Database()
    analyzer = PredictionAnalyzer(db, simulation_age_days=args.simulation_age_days)

    # Load data
    num_traders = analyzer.load_simulation_traders(verbose=verbose)

    if num_traders == 0:
        print("[ERROR] No simulation traders found")
        return 1

    # Run analysis
    try:
        if verbose:
            print("=" * 70)
            print("  PREDICTION ERROR ANALYSIS")
            print("=" * 70)
            print()

        if args.focus == 'all' or args.focus == 'false_positives':
            analyzer.analyze_false_positives(threshold=args.threshold, verbose=verbose)

        if args.focus == 'all' or args.focus == 'false_negatives':
            analyzer.analyze_false_negatives(threshold=args.threshold, verbose=verbose)

        if args.focus == 'all' or args.focus == 'market_difficulty':
            analyzer.analyze_market_difficulty(verbose=verbose)

        if args.focus == 'all' or args.focus == 'confusion_matrix':
            analyzer.generate_confusion_matrix(verbose=verbose)

        # Export if requested
        if args.export:
            analyzer.generate_report(args.export)

        return 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Analysis cancelled by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
