#!/usr/bin/env python3
"""
Polymarket Strategy Backtesting

Tests trading strategies on simulation data with resolved outcomes.

Strategies:
1. Follow Top N ELO - Copy trades from highest-rated traders
2. Weighted Consensus - Combine predictions weighted by ELO
3. Contrarian - Bet against consensus when extreme
4. Specialist Following - Follow category experts
5. Kelly Criterion - Optimize bet sizing

Usage:
    py scripts/simulation/backtest_strategy.py --strategy follow_top_n --top-n 10
    py scripts/simulation/backtest_strategy.py --strategy weighted_consensus --min-elo 1550
    py scripts/simulation/backtest_strategy.py --strategy contrarian --threshold 0.7
    py scripts/simulation/backtest_strategy.py --all-strategies  # Test all
    py scripts/simulation/backtest_strategy.py --export results/  # Save results
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

from monitoring.database import Database


class StrategyBacktester:
    """Backtest trading strategies on simulation data."""

    def __init__(self, db: Database, simulation_age_days: int = 7):
        """Initialize backtester."""
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.traders = {}
        self.resolved_markets = []
        self.trader_elos = {}

    def load_simulation_data(self, verbose: bool = True):
        """Load traders, their ELOs, and resolved markets with trades."""
        if verbose:
            print("[LOAD] Loading simulation data...")

        cutoff_date = (datetime.now() - timedelta(days=self.simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get simulation traders with ELO
        cursor.execute("""
            SELECT address, comprehensive_elo, win_rate, total_trades
            FROM traders
            WHERE total_trades > 0
            AND total_trades < 100
            AND last_updated > ?
            AND comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
        """, (cutoff_date,))

        rows = cursor.fetchall()
        self.traders = {
            row[0]: {
                'elo': row[1],
                'win_rate': row[2],
                'total_trades': row[3],
                'rank': i + 1
            }
            for i, row in enumerate(rows)
        }

        self.trader_elos = {addr: data['elo'] for addr, data in self.traders.items()}

        # Get resolved markets
        trader_addresses = list(self.traders.keys())
        if not trader_addresses:
            if verbose:
                print("[ERROR] No simulation traders found!")
            return

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

        self.resolved_markets = [
            {'market_id': row[0], 'title': row[1], 'winning_outcome': row[2]}
            for row in cursor.fetchall()
        ]

        conn.close()

        if verbose:
            print(f"[OK] Loaded {len(self.traders)} traders, {len(self.resolved_markets)} resolved markets")
            if self.trader_elos:
                print(f"     ELO range: {min(self.trader_elos.values()):.1f} - {max(self.trader_elos.values()):.1f}")
            print()

    def strategy_follow_top_n(self, top_n: int = 10, min_confidence: float = 0.6, verbose: bool = True):
        """
        Follow trades from top N ELO traders.

        Strategy: Copy every trade from top N ranked traders where their bet price
        indicates confidence >= min_confidence.

        Args:
            top_n: Number of top traders to follow
            min_confidence: Only follow trades with price >= this (0.6 = 60% confident)

        Returns:
            Dict with strategy results
        """
        if verbose:
            print(f"[STRATEGY] Follow Top {top_n} (confidence >= {min_confidence})")

        # Get top N traders
        sorted_traders = sorted(
            self.traders.items(),
            key=lambda x: x[1]['elo'],
            reverse=True
        )[:top_n]

        top_trader_addresses = [addr for addr, _ in sorted_traders]

        if verbose:
            print(f"  Following: {len(top_trader_addresses)} traders")
            for addr, data in sorted_traders[:3]:
                print(f"    - Rank {data['rank']}: ELO {data['elo']:.1f}")
            print()

        # Get their trades on resolved markets
        conn = self.db.get_connection()
        cursor = conn.cursor()

        strategy_trades = []

        for market in self.resolved_markets:
            market_id = market['market_id']
            winning_outcome = market['winning_outcome']

            placeholders = ','.join('?' * len(top_trader_addresses))
            cursor.execute(f"""
                SELECT trader_address, outcome, price, shares, side
                FROM trades
                WHERE market_id = ?
                AND trader_address IN ({placeholders})
            """, (market_id,) + tuple(top_trader_addresses))

            trades = cursor.fetchall()

            for trade in trades:
                trader_addr, outcome, price, shares, side = trade

                # Check confidence (price >= threshold for BUY)
                confidence = price if side == 'BUY' else (1 - price)

                if confidence < min_confidence:
                    continue  # Skip low-confidence trades

                # Did this trade win?
                won = (outcome == winning_outcome)

                # Calculate P&L
                if won:
                    pnl = shares * (1 - price)  # Win: get $1 per share
                else:
                    pnl = -shares * price  # Lose: lose entry cost

                roi = (pnl / (shares * price)) if (shares * price) > 0 else 0

                strategy_trades.append({
                    'market_id': market_id,
                    'trader_address': trader_addr,
                    'outcome': outcome,
                    'price': price,
                    'shares': shares,
                    'won': won,
                    'pnl': pnl,
                    'roi': roi,
                    'invested': shares * price
                })

        conn.close()

        # Calculate metrics
        metrics = self.calculate_performance_metrics(strategy_trades)
        metrics['strategy'] = 'follow_top_n'
        metrics['params'] = {'top_n': top_n, 'min_confidence': min_confidence}

        if verbose:
            print(f"  Trades taken: {metrics['num_trades']}")
            print(f"  Win rate: {metrics['win_rate']*100:.1f}%")
            print(f"  ROI: {metrics['roi']*100:.1f}%")
            print(f"  Total P&L: ${metrics['total_pnl']:.2f}")
            print()

        return metrics

    def calculate_performance_metrics(self, trades: List[Dict]) -> Dict:
        """
        Calculate comprehensive performance metrics.

        Args:
            trades: List of trade dicts with 'won', 'pnl', 'roi', 'invested'

        Returns:
            Dict with all performance metrics
        """
        if not trades:
            return {
                'num_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'roi': 0.0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'total_invested': 0.0,
                'avg_trade_size': 0.0
            }

        num_trades = len(trades)
        num_wins = sum(1 for t in trades if t['won'])
        win_rate = num_wins / num_trades

        total_pnl = sum(t['pnl'] for t in trades)
        total_invested = sum(t['invested'] for t in trades)
        roi = (total_pnl / total_invested) if total_invested > 0 else 0.0

        # Sharpe ratio (risk-adjusted returns)
        returns = [t['roi'] for t in trades]
        avg_return = sum(returns) / len(returns)

        if len(returns) > 1:
            variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
            std_dev = math.sqrt(variance)
            sharpe_ratio = (avg_return / std_dev) if std_dev > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # Max drawdown (largest cumulative loss)
        cumulative_pnl = 0
        peak = 0
        max_drawdown = 0

        for trade in trades:
            cumulative_pnl += trade['pnl']
            peak = max(peak, cumulative_pnl)
            drawdown = peak - cumulative_pnl
            max_drawdown = max(max_drawdown, drawdown)

        return {
            'num_trades': num_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'roi': roi,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'total_invested': total_invested,
            'avg_trade_size': total_invested / num_trades
        }

    def backtest_all_strategies(self, verbose: bool = True):
        """Run all strategies and compare performance."""
        if verbose:
            print("=" * 70)
            print("  STRATEGY BACKTEST - ALL STRATEGIES")
            print("=" * 70)
            print()

        results = []

        # Strategy 1: Follow Top 10
        results.append(self.strategy_follow_top_n(top_n=10, min_confidence=0.6, verbose=verbose))

        # Strategy 2: Follow Top 20
        results.append(self.strategy_follow_top_n(top_n=20, min_confidence=0.6, verbose=verbose))

        # Strategy 3: Follow Top 10 (high confidence)
        results.append(self.strategy_follow_top_n(top_n=10, min_confidence=0.7, verbose=verbose))

        # Strategy 4: Follow Top 5 (very high confidence)
        results.append(self.strategy_follow_top_n(top_n=5, min_confidence=0.8, verbose=verbose))

        # Compare results
        if verbose:
            print("=" * 70)
            print("  STRATEGY COMPARISON")
            print("=" * 70)
            print()
            print(f"{'Strategy':<30} {'Trades':<8} {'Win%':<8} {'ROI':<10} {'Sharpe':<8}")
            print("-" * 70)

            for r in results:
                params_str = f"top={r['params']['top_n']}, conf={r['params']['min_confidence']}"
                strategy_name = f"{r['strategy']} ({params_str})"[:29]
                print(f"{strategy_name:<30} {r['num_trades']:<8} "
                      f"{r['win_rate']*100:<8.1f} {r['roi']*100:<10.1f} "
                      f"{r['sharpe_ratio']:<8.2f}")

            print()

            # Find best strategy
            best_roi = max(results, key=lambda r: r['roi'])
            best_sharpe = max(results, key=lambda r: r['sharpe_ratio'])
            most_trades = max(results, key=lambda r: r['num_trades'])

            print("Key Findings:")
            print(f"  Best ROI: {best_roi['strategy']} ({best_roi['params']}) - {best_roi['roi']*100:.1f}% ROI")
            print(f"  Best Sharpe: {best_sharpe['strategy']} ({best_sharpe['params']}) - {best_sharpe['sharpe_ratio']:.2f}")
            print(f"  Most Trades: {most_trades['strategy']} ({most_trades['params']}) - {most_trades['num_trades']} trades")
            print()

            # Recommendation
            if best_roi['sharpe_ratio'] > 0.3:
                print(f"Recommendation: {best_roi['strategy']} with {best_roi['params']}")
            else:
                print("Recommendation: All strategies show weak risk-adjusted returns")
            print()

        return results

    def generate_report(self, results: List[Dict], output_path: str = None):
        """Generate backtest report and export to JSON."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        report = {
            'timestamp': datetime.now().isoformat(),
            'simulation_age_days': self.simulation_age_days,
            'num_traders': len(self.traders),
            'num_resolved_markets': len(self.resolved_markets),
            'elo_range': {
                'min': min(self.trader_elos.values()) if self.trader_elos else 0,
                'max': max(self.trader_elos.values()) if self.trader_elos else 0
            },
            'strategies': results
        }

        if output_path:
            # If output_path is a directory, create filename
            if os.path.isdir(output_path):
                output_path = os.path.join(output_path, f'backtest_report_{timestamp}.json')

            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)

            print(f"[OK] Backtest report exported to: {output_path}")

        return report


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Backtest trading strategies on simulation data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single strategy
  py scripts/simulation/backtest_strategy.py --strategy follow_top_n --top-n 10

  # Test with different confidence
  py scripts/simulation/backtest_strategy.py --strategy follow_top_n --top-n 10 --min-confidence 0.7

  # Test all strategies
  py scripts/simulation/backtest_strategy.py --all-strategies

  # Export results
  py scripts/simulation/backtest_strategy.py --all-strategies --export results/backtest_report.json
        """
    )

    parser.add_argument('--strategy', type=str,
                       choices=['follow_top_n', 'weighted_consensus', 'contrarian', 'all'],
                       default='follow_top_n',
                       help='Strategy to test')

    parser.add_argument('--top-n', type=int, default=10,
                       help='Number of top traders to follow (default: 10)')

    parser.add_argument('--min-confidence', type=float, default=0.6,
                       help='Minimum confidence to follow trade (default: 0.6)')

    parser.add_argument('--all-strategies', action='store_true',
                       help='Test all strategies')

    parser.add_argument('--export', type=str,
                       help='Export results to JSON file')

    parser.add_argument('--simulation-age-days', type=int, default=7,
                       help='Consider traders updated within N days (default: 7)')

    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')

    args = parser.parse_args()

    verbose = not args.quiet

    # Initialize
    db = Database()
    backtester = StrategyBacktester(db, simulation_age_days=args.simulation_age_days)

    # Load data
    backtester.load_simulation_data(verbose=verbose)

    if not backtester.traders or not backtester.resolved_markets:
        print("[ERROR] Insufficient data for backtesting")
        return 1

    # Run strategy
    try:
        if args.all_strategies or args.strategy == 'all':
            results = backtester.backtest_all_strategies(verbose=verbose)
        elif args.strategy == 'follow_top_n':
            results = [backtester.strategy_follow_top_n(
                top_n=args.top_n,
                min_confidence=args.min_confidence,
                verbose=verbose
            )]
        else:
            print(f"[ERROR] Strategy '{args.strategy}' not yet implemented")
            return 1

        # Export if requested
        if args.export:
            backtester.generate_report(results, args.export)

        return 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Backtest cancelled by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
