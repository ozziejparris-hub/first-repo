#!/usr/bin/env python3
"""
Simple ELO Calculator for Simulation Data

Calculates basic ELO ratings from simulation data without expensive modifiers.
Designed for test data with few resolved markets.

Usage:
    py scripts/calculate_elo_simple.py                    # Standard calculation
    py scripts/calculate_elo_simple.py --verbose          # Detailed output
    py scripts/calculate_elo_simple.py --top 50           # Show top 50 traders
    py scripts/calculate_elo_simple.py --export results/  # Save rankings to file
"""

import sys
import os
import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

# Add project root and simulation dir to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.database import Database
from _sim_db_guard import add_sim_db_args, resolve_sim_db, assert_safe_to_write


class SimpleELOCalculator:
    """Simple ELO calculator for simulation data."""

    def __init__(self, db: Database, k_factor: int = 32, write_to_db: bool = False):
        """Initialize calculator."""
        self.db = db
        self.k_factor = k_factor
        self.write_to_db = write_to_db
        self.trader_elos = {}  # trader_address -> current ELO

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score for rating_a against rating_b."""
        return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))

    def update_rating(self, current_rating: float, expected: float, actual: float) -> float:
        """
        Update ELO rating based on match result.

        Args:
            current_rating: Current ELO rating
            expected: Expected score (0-1)
            actual: Actual score (1 for win, 0 for loss)

        Returns:
            New ELO rating
        """
        return current_rating + self.k_factor * (actual - expected)

    def calculate_ratings(self, verbose: bool = True):
        """
        Calculate ELO ratings for all traders based on resolved markets.

        Args:
            verbose: Print detailed progress

        Returns:
            Dict with calculation results
        """
        if verbose:
            print("=" * 70)
            print("  SIMPLE ELO CALCULATOR")
            print("=" * 70)
            print()
            print(f"K-factor: {self.k_factor}")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get all trades on resolved markets
        if verbose:
            print("[1/3] Loading trades on resolved markets...")

        cursor.execute("""
            SELECT
                t.trader_address,
                t.outcome,
                t.market_id,
                t.shares,
                m.winning_outcome
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 1
            AND m.winning_outcome IS NOT NULL
            ORDER BY t.timestamp
        """)

        trades = cursor.fetchall()

        if verbose:
            print(f"     Found {len(trades)} trades on resolved markets")
            print()

        # Group trades by market
        market_trades = defaultdict(list)
        for trade in trades:
            trader_address, outcome, market_id, shares, winning_outcome = trade
            market_trades[market_id].append({
                'trader_address': trader_address,
                'outcome': outcome,
                'shares': shares,
                'winning_outcome': winning_outcome
            })

        if verbose:
            print(f"[2/3] Calculating ELO ratings across {len(market_trades)} resolved markets...")
            print()

        # Initialize all traders to 1500
        all_traders = set()
        for trades_list in market_trades.values():
            for trade in trades_list:
                all_traders.add(trade['trader_address'])

        for trader in all_traders:
            self.trader_elos[trader] = 1500.0

        # Process each market
        updates_count = 0
        for market_id, trades_list in market_trades.items():
            if not trades_list:
                continue

            winning_outcome = trades_list[0]['winning_outcome']

            # Separate winners and losers
            winners = [t for t in trades_list if t['outcome'] == winning_outcome]
            losers = [t for t in trades_list if t['outcome'] != winning_outcome]

            if not winners or not losers:
                continue

            # Calculate average ELO for each group
            avg_winner_elo = sum(self.trader_elos[w['trader_address']] for w in winners) / len(winners)
            avg_loser_elo = sum(self.trader_elos[l['trader_address']] for l in losers) / len(losers)

            # Update winners
            for winner in winners:
                trader_address = winner['trader_address']
                current_elo = self.trader_elos[trader_address]
                expected = self.expected_score(current_elo, avg_loser_elo)
                new_elo = self.update_rating(current_elo, expected, 1.0)
                self.trader_elos[trader_address] = new_elo
                updates_count += 1

            # Update losers
            for loser in losers:
                trader_address = loser['trader_address']
                current_elo = self.trader_elos[trader_address]
                expected = self.expected_score(current_elo, avg_winner_elo)
                new_elo = self.update_rating(current_elo, expected, 0.0)
                self.trader_elos[trader_address] = new_elo
                updates_count += 1

        if verbose:
            print(f"     Processed {updates_count} rating updates")
            print()

        # Save to database only when write_to_db is explicitly enabled
        if self.write_to_db:
            if verbose:
                print("[3/3] Saving ELO ratings to database...")
            for trader_address, elo in self.trader_elos.items():
                cursor.execute("""
                    UPDATE traders
                    SET comprehensive_elo = ?,
                        base_category_elo = ?,
                        behavioral_modifier = 1.0,
                        advanced_modifier = 1.0,
                        pnl_modifier = 1.0,
                        elo_last_updated = ?
                    WHERE address = ?
                """, (elo, elo, datetime.now(), trader_address))
            conn.commit()
        else:
            if verbose:
                print("[3/3] Skipping DB write (read-only mode — pass --write-to-db to enable)")
        conn.close()

        if verbose:
            print(f"     Saved ratings for {len(self.trader_elos)} traders")
            print()

        # Get statistics
        elo_values = list(self.trader_elos.values())
        if elo_values:
            min_elo = min(elo_values)
            max_elo = max(elo_values)
            avg_elo = sum(elo_values) / len(elo_values)

            if verbose:
                print(f"[OK] ELO range: {min_elo:.1f} - {max_elo:.1f}")
                print(f"     Average ELO: {avg_elo:.1f}")
                print()

        return {
            'traders_updated': len(self.trader_elos),
            'updates_count': updates_count,
            'markets_processed': len(market_trades)
        }

    def display_rankings(self, n: int = 20, verbose: bool = True):
        """Display top N traders with ELO ratings."""
        if verbose:
            print(f"Top {n} traders by ELO:")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                total_trades,
                win_rate
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT ?
        """, (n,))

        traders = cursor.fetchall()

        print(f"{'Rank':<6} {'Address':<20} {'ELO':<10} {'Trades':<8} {'Win %':<8}")
        print("-" * 56)

        for i, trader in enumerate(traders, 1):
            address, comp_elo, _, total_trades, win_rate = trader
            addr_short = address[:10] + "..." + address[-6:]
            print(f"{i:<6} {addr_short:<20} {comp_elo:<10.1f} {total_trades:<8} {win_rate*100:<8.1f}")

        print()

        # Also show bottom traders
        if verbose:
            bottom_n = min(10, n//2)
            print(f"Bottom {bottom_n} traders by ELO:")
            print()

            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    total_trades,
                    win_rate
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                ORDER BY comprehensive_elo ASC
                LIMIT ?
            """, (bottom_n,))

            bottom_traders = cursor.fetchall()

            print(f"{'Rank':<6} {'Address':<20} {'ELO':<10} {'Trades':<8} {'Win %':<8}")
            print("-" * 56)

            for i, trader in enumerate(bottom_traders, 1):
                address, comp_elo, total_trades, win_rate = trader
                addr_short = address[:10] + "..." + address[-6:]
                print(f"{i:<6} {addr_short:<20} {comp_elo:<10.1f} {total_trades:<8} {win_rate*100:<8.1f}")

            print()

        conn.close()

    def analyze_correlation(self, verbose: bool = True):
        """Analyze correlation between win rate and achieved ELO."""
        if verbose:
            print("Analyzing skill -> ELO correlation...")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                win_rate,
                comprehensive_elo
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            AND total_trades > 0
            ORDER BY win_rate DESC
        """)

        data = cursor.fetchall()
        conn.close()

        if not data:
            print("[WARN] No traders with ELO ratings found")
            return

        # Calculate correlation coefficient (Pearson's r)
        n = len(data)
        sum_wr = sum(wr for wr, _ in data)
        sum_elo = sum(elo for _, elo in data)
        sum_wr_elo = sum(wr * elo for wr, elo in data)
        sum_wr2 = sum(wr * wr for wr, _ in data)
        sum_elo2 = sum(elo * elo for _, elo in data)

        numerator = n * sum_wr_elo - sum_wr * sum_elo
        denominator = math.sqrt((n * sum_wr2 - sum_wr**2) * (n * sum_elo2 - sum_elo**2))

        if denominator > 0:
            correlation = numerator / denominator
            print(f"Win Rate <-> ELO Correlation: r = {correlation:.3f}")
            print()

            if correlation > 0.7:
                print("[OK] Strong positive correlation - ELO accurately reflects skill!")
            elif correlation > 0.5:
                print("[WARN] Moderate correlation - ELO somewhat reflects skill")
            else:
                print("[FAIL] Weak correlation - ELO may not reflect skill accurately")
        else:
            print("[WARN] Unable to calculate correlation (insufficient variance)")

        print()

        # Show win rate buckets
        buckets = {
            'Elite (>60%)': [],
            'Good (50-60%)': [],
            'Average (45-50%)': [],
            'Poor (<45%)': []
        }

        for wr, elo in data:
            if wr > 0.60:
                buckets['Elite (>60%)'].append(elo)
            elif wr >= 0.50:
                buckets['Good (50-60%)'].append(elo)
            elif wr >= 0.45:
                buckets['Average (45-50%)'].append(elo)
            else:
                buckets['Poor (<45%)'].append(elo)

        print("Average ELO by Win Rate Bucket:")
        for bucket, elos in buckets.items():
            if elos:
                avg_elo = sum(elos) / len(elos)
                min_elo = min(elos)
                max_elo = max(elos)
                print(f"  {bucket:<20} {avg_elo:>8.1f}  (range: {min_elo:.1f}-{max_elo:.1f}, n={len(elos)})")

        print()

    def export_rankings(self, output_path: str):
        """Export rankings to CSV file."""
        output_dir = Path(output_path)
        output_dir.mkdir(exist_ok=True, parents=True)

        output_file = output_dir / f"elo_rankings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                total_trades,
                win_rate,
                total_pnl,
                avg_roi
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
        """)

        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['address', 'comprehensive_elo', 'base_elo', 'total_trades',
                            'win_rate', 'total_pnl', 'avg_roi'])
            writer.writerows(cursor.fetchall())

        conn.close()

        print(f"[OK] Rankings exported to: {output_file}")
        print()


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Simple ELO calculator for simulation data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/calculate_elo_simple.py                      # Full calculation with analysis
  py scripts/calculate_elo_simple.py --verbose            # Detailed output
  py scripts/calculate_elo_simple.py --top 50             # Show top 50 traders
  py scripts/calculate_elo_simple.py --export results/    # Save to file
  py scripts/calculate_elo_simple.py --quiet              # Minimal output
  py scripts/calculate_elo_simple.py --k-factor 24        # Custom K-factor
        """
    )

    parser.add_argument('--verbose', action='store_true',
                       help='Detailed output')
    parser.add_argument('--top', type=int, default=20,
                       help='Number of top traders to display (default: 20)')
    parser.add_argument('--export', type=str,
                       help='Export rankings to directory')
    parser.add_argument('--quiet', action='store_true',
                       help='Minimal output')
    parser.add_argument('--k-factor', type=int, default=32,
                       help='ELO K-factor (default: 32)')
    parser.add_argument('--write-to-db', action='store_true',
                       help=(
                           'Write ELO results back to the traders table. '
                           'Off by default (read-only). '
                           'Also requires --allow-production-write when targeting production.'
                       ))
    add_sim_db_args(parser)

    args = parser.parse_args()

    # Resolve DB path — default is simulation_test.db, NOT production
    db_path = resolve_sim_db(args)

    # Guard: refuse production writes unless explicitly unlocked
    if args.write_to_db:
        assert_safe_to_write(db_path, args.allow_production_write)

    db = Database(db_path)
    calculator = SimpleELOCalculator(db, k_factor=args.k_factor,
                                     write_to_db=args.write_to_db)

    # Calculate ratings
    try:
        calculator.calculate_ratings(verbose=not args.quiet)

        if not args.quiet:
            calculator.display_rankings(n=args.top, verbose=args.verbose or not args.quiet)
            calculator.analyze_correlation(verbose=not args.quiet)

        # Export if requested
        if args.export:
            calculator.export_rankings(args.export)

        if not args.quiet:
            print("=" * 70)
            print("  CALCULATION COMPLETE")
            print("=" * 70)
            print()

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Calculation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Calculation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
