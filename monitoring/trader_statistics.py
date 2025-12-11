"""
Trader Statistics Calculator - Updates trader win rates based on resolved trades.

This module bridges monitoring and analysis by calculating real win rates
from resolved trades and updating the database.
"""

from typing import Dict, List
from .database import Database


class TraderStatisticsCalculator:
    """Calculate and update trader statistics based on resolved trades."""

    def __init__(self, database: Database, min_resolved_trades: int = 5):
        """
        Initialize the statistics calculator.

        Args:
            database: Database instance
            min_resolved_trades: Minimum resolved trades required to calculate win rate
        """
        self.db = database
        self.min_resolved_trades = min_resolved_trades

    def calculate_trader_win_rate(self, trader_address: str) -> Dict:
        """
        Calculate win rate for a specific trader based on resolved trades.

        Args:
            trader_address: Trader's wallet address

        Returns:
            {
                'trader_address': str,
                'total_trades': int,
                'resolved_trades': int,
                'won_trades': int,
                'lost_trades': int,
                'win_rate': float,
                'has_minimum': bool
            }
        """
        # Get all resolved trades for this trader
        resolved_trades = self.db.get_resolved_trades_for_trader(trader_address)

        # Get total trade count from database
        trader_stats = self.db.get_trader_stats(trader_address)
        total_trades = trader_stats['total_trades'] if trader_stats else 0

        # Count wins and losses
        won_trades = sum(1 for t in resolved_trades if t.get('trade_result') == 'won')
        lost_trades = sum(1 for t in resolved_trades if t.get('trade_result') == 'lost')
        resolved_count = won_trades + lost_trades

        # Calculate win rate
        win_rate = (won_trades / resolved_count * 100) if resolved_count > 0 else 0.0

        # Check if trader meets minimum threshold
        has_minimum = resolved_count >= self.min_resolved_trades

        return {
            'trader_address': trader_address,
            'total_trades': total_trades,
            'resolved_trades': resolved_count,
            'won_trades': won_trades,
            'lost_trades': lost_trades,
            'win_rate': win_rate,
            'has_minimum': has_minimum
        }

    def update_trader_win_rate(self, trader_address: str, verbose: bool = False) -> bool:
        """
        Calculate and update win rate for a trader in the database.

        Args:
            trader_address: Trader's wallet address
            verbose: Print detailed logs

        Returns:
            True if update was performed, False if trader doesn't meet minimum
        """
        # Calculate current stats
        stats = self.calculate_trader_win_rate(trader_address)

        # Get existing trader data
        existing = self.db.get_trader_stats(trader_address)
        if not existing:
            if verbose:
                print(f"[STATS] Trader {trader_address[:10]}... not found in database")
            return False

        # Update database with new win rate
        # Use existing values for fields we're not recalculating
        self.db.add_or_update_trader(
            address=trader_address,
            total_trades=existing['total_trades'],
            successful_trades=stats['won_trades'],  # Update with actual wins
            win_rate=stats['win_rate'],  # Update with calculated win rate
            total_volume=existing['total_volume'],
            is_flagged=existing['is_flagged']
        )

        if verbose:
            status = "CALCULATED" if stats['has_minimum'] else "INSUFFICIENT DATA"
            print(f"[STATS] {status} - {trader_address[:10]}... | "
                  f"Win Rate: {stats['win_rate']:.1f}% | "
                  f"Resolved: {stats['resolved_trades']} "
                  f"(W: {stats['won_trades']}, L: {stats['lost_trades']})")

        return True

    def recalculate_all_flagged_traders(self, verbose: bool = True) -> Dict:
        """
        Recalculate win rates for all flagged traders.

        Args:
            verbose: Print progress and summary

        Returns:
            {
                'traders_processed': int,
                'traders_updated': int,
                'traders_with_minimum': int,
                'average_win_rate': float
            }
        """
        if verbose:
            print("\n" + "="*70)
            print("RECALCULATING TRADER STATISTICS")
            print("="*70)

        # Get all flagged traders
        flagged_traders = self.db.get_flagged_traders()

        if verbose:
            print(f"\nProcessing {len(flagged_traders)} flagged traders...")
            print(f"Minimum resolved trades threshold: {self.min_resolved_trades}\n")

        summary = {
            'traders_processed': 0,
            'traders_updated': 0,
            'traders_with_minimum': 0,
            'total_win_rate': 0.0,
            'average_win_rate': 0.0
        }

        for trader_address in flagged_traders:
            # Calculate stats
            stats = self.calculate_trader_win_rate(trader_address)

            # Update database
            if self.update_trader_win_rate(trader_address, verbose=False):
                summary['traders_updated'] += 1

            summary['traders_processed'] += 1

            # Track traders meeting minimum
            if stats['has_minimum']:
                summary['traders_with_minimum'] += 1
                summary['total_win_rate'] += stats['win_rate']

            # Show progress for larger batches
            if verbose and summary['traders_processed'] % 10 == 0:
                print(f"[PROGRESS] Processed {summary['traders_processed']}/{len(flagged_traders)} traders...")

        # Calculate average
        if summary['traders_with_minimum'] > 0:
            summary['average_win_rate'] = summary['total_win_rate'] / summary['traders_with_minimum']

        if verbose:
            print("\n" + "="*70)
            print("RECALCULATION COMPLETE")
            print("="*70)
            print(f"Traders processed: {summary['traders_processed']}")
            print(f"Traders updated: {summary['traders_updated']}")
            print(f"Traders with {self.min_resolved_trades}+ resolved trades: {summary['traders_with_minimum']}")
            if summary['traders_with_minimum'] > 0:
                print(f"Average win rate: {summary['average_win_rate']:.2f}%")
            print("="*70 + "\n")

        return summary

    def get_trader_performance_summary(self, trader_address: str) -> str:
        """
        Get formatted performance summary for a trader.

        Args:
            trader_address: Trader's wallet address

        Returns:
            Formatted string with trader performance
        """
        stats = self.calculate_trader_win_rate(trader_address)

        if stats['resolved_trades'] == 0:
            return (f"Trader {trader_address[:10]}...\n"
                   f"  No resolved trades yet\n"
                   f"  Total trades: {stats['total_trades']}")

        summary = f"Trader {trader_address[:10]}...\n"
        summary += f"  Win Rate: {stats['win_rate']:.1f}%\n"
        summary += f"  Resolved: {stats['resolved_trades']} (Won: {stats['won_trades']}, Lost: {stats['lost_trades']})\n"
        summary += f"  Total trades: {stats['total_trades']}\n"

        if not stats['has_minimum']:
            summary += f"  [Need {self.min_resolved_trades - stats['resolved_trades']} more resolved trades for reliable stats]\n"

        return summary
