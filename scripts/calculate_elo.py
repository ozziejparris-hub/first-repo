#!/usr/bin/env python3
"""
Polymarket ELO Calculator and Analyzer

Calculates ELO ratings for traders and analyzes results against known skill levels.

Features:
- Standard ELO calculation (base + modifiers)
- Parameter tuning (test different K-factors)
- Ranking analysis (verify skill -> ELO correlation)
- Export results for comparison

Usage:
    py scripts/calculate_elo.py                    # Standard calculation
    py scripts/calculate_elo.py --verbose          # Detailed output
    py scripts/calculate_elo.py --top 50           # Show top 50 traders
    py scripts/calculate_elo.py --export results/  # Save rankings to file
    py scripts/calculate_elo.py --quick            # Skip expensive modifiers
"""

import sys
import os
import argparse
import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


class ELOAnalyzer:
    """Calculate and analyze ELO ratings."""

    def __init__(self, db: Database):
        """Initialize analyzer."""
        self.db = db
        self.elo_bridge = UnifiedELOMonitoringBridge(db=db)

    def calculate_ratings(self, verbose: bool = True, quick: bool = False):
        """
        Calculate ELO ratings for all traders.

        Args:
            verbose: Print detailed progress
            quick: Skip expensive modifiers (network, contrarian)

        Returns:
            Dict with calculation results
        """
        if verbose:
            print("=" * 70)
            print("  POLYMARKET ELO CALCULATOR")
            print("=" * 70)
            print()

        # Use full recalculation (includes all 6 dimensions)
        if verbose:
            print("[1/3] Calculating ELO ratings...")
            if quick:
                print("        Mode: Quick (base + behavioral + advanced + P&L)")
            else:
                print("        Mode: Full (all 6 dimensions including network + contrarian)")
            print()

        if quick:
            # Get all flagged traders
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT address FROM traders")
            trader_addresses = [row[0] for row in cursor.fetchall()]
            conn.close()

            result = self.elo_bridge.quick_elo_update_for_traders(
                trader_addresses,
                verbose=verbose,
                force_refresh=True
            )
        else:
            result = self.elo_bridge.full_elo_recalculation(verbose=verbose)

        if verbose:
            print()
            print(f"[OK] Calculated ratings for {result['traders_updated']} traders")
            if result['traders_failed'] > 0:
                print(f"[WARN] Failed to calculate ratings for {result['traders_failed']} traders")

            # Get statistics
            conn = self.db.get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    MIN(comprehensive_elo) as min_elo,
                    MAX(comprehensive_elo) as max_elo,
                    AVG(comprehensive_elo) as avg_elo
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
            """)

            stats = cursor.fetchone()
            conn.close()

            if stats and stats[0] > 0:
                print(f"     ELO range: {stats[1]:.1f} - {stats[2]:.1f}")
                print(f"     Average ELO: {stats[3]:.1f}")
            print()

        return result

    def display_rankings(self, n: int = 20, verbose: bool = True):
        """
        Display top N traders with ELO ratings.

        Args:
            n: Number of top traders to display
            verbose: Also show bottom traders
        """
        if verbose:
            print(f"[2/3] Top {n} traders by Comprehensive ELO:")
            print()

        # Get top traders
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
                total_trades,
                win_rate
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT ?
        """, (n,))

        traders = cursor.fetchall()

        # Display in table format
        print(f"{'Rank':<6} {'Address':<20} {'Comp ELO':<10} {'Base ELO':<10} {'Trades':<8} {'Win %':<8}")
        print("-" * 72)

        for i, trader in enumerate(traders, 1):
            address, comp_elo, base_elo, _, _, _, total_trades, win_rate = trader

            # Truncate address for display
            addr_short = address[:10] + "..." + address[-6:]

            print(f"{i:<6} {addr_short:<20} {comp_elo:<10.1f} {base_elo:<10.1f} {total_trades:<8} {win_rate*100:<8.1f}")

        print()

        # Also show bottom traders
        if verbose:
            bottom_n = min(10, n//2)
            print(f"Bottom {bottom_n} traders by Comprehensive ELO:")
            print()

            cursor.execute("""
                SELECT
                    address,
                    comprehensive_elo,
                    base_category_elo,
                    total_trades,
                    win_rate
                FROM traders
                WHERE comprehensive_elo IS NOT NULL
                ORDER BY comprehensive_elo ASC
                LIMIT ?
            """, (bottom_n,))

            bottom_traders = cursor.fetchall()

            print(f"{'Rank':<6} {'Address':<20} {'Comp ELO':<10} {'Base ELO':<10} {'Trades':<8} {'Win %':<8}")
            print("-" * 72)

            for i, trader in enumerate(bottom_traders, 1):
                address, comp_elo, base_elo, total_trades, win_rate = trader
                addr_short = address[:10] + "..." + address[-6:]
                print(f"{i:<6} {addr_short:<20} {comp_elo:<10.1f} {base_elo:<10.1f} {total_trades:<8} {win_rate*100:<8.1f}")

            print()

        conn.close()

    def analyze_correlation(self, verbose: bool = True):
        """
        Analyze correlation between win rate and achieved ELO.

        Shows whether the ELO system accurately reflects trader skill.
        """
        if verbose:
            print("[3/3] Analyzing skill -> ELO correlation...")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get all traders with ELO
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
        """
        Export rankings to CSV file.

        Args:
            output_path: Directory to save CSV file
        """
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
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
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
            writer.writerow(['address', 'comprehensive_elo', 'base_elo', 'behavioral_mod',
                            'advanced_mod', 'pnl_mod', 'total_trades', 'win_rate',
                            'total_pnl', 'avg_roi'])
            writer.writerows(cursor.fetchall())

        conn.close()

        print(f"[OK] Rankings exported to: {output_file}")
        print()


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Calculate and analyze Polymarket ELO ratings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/calculate_elo.py                      # Full calculation with analysis
  py scripts/calculate_elo.py --verbose            # Detailed output
  py scripts/calculate_elo.py --quick              # Skip expensive modifiers
  py scripts/calculate_elo.py --top 50             # Show top 50 traders
  py scripts/calculate_elo.py --export results/    # Save to file
  py scripts/calculate_elo.py --quiet              # Minimal output
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
    parser.add_argument('--quick', action='store_true',
                       help='Quick mode - skip expensive modifiers (network, contrarian)')

    args = parser.parse_args()

    # Initialize
    db = Database()
    analyzer = ELOAnalyzer(db)

    # Calculate ratings
    try:
        analyzer.calculate_ratings(verbose=not args.quiet, quick=args.quick)

        if not args.quiet:
            analyzer.display_rankings(n=args.top, verbose=args.verbose or not args.quiet)
            analyzer.analyze_correlation(verbose=not args.quiet)

        # Export if requested
        if args.export:
            analyzer.export_rankings(args.export)

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
