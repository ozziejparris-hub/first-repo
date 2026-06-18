"""
Trader Statistics Calculator - Updates trader win rates based on resolved trades.

This module bridges monitoring and analysis by calculating real win rates
from resolved trades and updating the database.

UPDATED: Now also calculates P&L from position matching (early exits).
Combines BOTH resolution-based (prediction accuracy) AND P&L-based (trading skill) metrics.
"""

from typing import Dict, List
from .database import Database
from .position_tracker import PositionTracker


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
        self.position_tracker = PositionTracker(database)

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
            # DISABLED 2026-06-18: win_rate is now owned by
            # reconcile_trader_aggregates.py (single-writer pattern).
            # This writer used percentage scale (won/resolved * 100) while the
            # reconciler uses fraction scale (won/resolved, capped at 1.0) —
            # they also differ on denominator (trade count vs distinct markets).
            # Omitting win_rate triggers the preserve-existing path in the UPSERT.
            # win_rate=stats['win_rate'],
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

    def calculate_comprehensive_stats(self, trader_address: str) -> Dict:
        """
        Calculate BOTH resolution-based AND P&L-based statistics.

        This gives a holistic view combining:
        1. Predictive accuracy (holds to resolution, correct outcome)
        2. Trading skill (exits early, captures profit)

        Returns:
            {
                'resolution_based': {...},  # Win rate from resolved trades
                'pnl_based': {...},         # P&L from position matching
                'combined': {...}           # Combined metrics
            }
        """
        # Resolution-based stats (prediction accuracy)
        resolution_stats = self.calculate_trader_win_rate(trader_address)

        # P&L-based stats (trading skill)
        pnl_stats = self.position_tracker.calculate_trader_pnl(trader_address)

        return {
            # Resolution-based (prediction accuracy)
            'resolution_based': {
                'win_rate': resolution_stats.get('win_rate', 0),
                'resolved_trades': resolution_stats.get('resolved_trades', 0),
                'won_trades': resolution_stats.get('won_trades', 0),
                'lost_trades': resolution_stats.get('lost_trades', 0),
                'has_minimum': resolution_stats.get('has_minimum', False)
            },

            # P&L-based (trading skill)
            'pnl_based': {
                'realized_pnl': pnl_stats['realized_pnl'],
                'avg_roi': pnl_stats['avg_roi'],
                'closed_positions': pnl_stats['closed_positions'],
                'open_positions': pnl_stats['open_positions'],
                'total_invested': pnl_stats['total_invested'],
                'profitable_rate': pnl_stats['profitable_rate']
            },

            # Combined metrics
            'combined': {
                'total_profit': pnl_stats['realized_pnl'],
                'avg_return': pnl_stats['avg_roi'],
                'prediction_accuracy': resolution_stats.get('win_rate', 0),
                'sample_size': {
                    'resolved_trades': resolution_stats.get('resolved_trades', 0),
                    'closed_positions': pnl_stats['closed_positions']
                }
            }
        }

    def update_trader_comprehensive_stats(self, trader_address: str, verbose: bool = False):
        """
        Update database with BOTH resolution and P&L stats.

        This replaces update_trader_win_rate() with a comprehensive version
        that includes position-based P&L metrics.

        Args:
            trader_address: Trader's wallet address
            verbose: Print detailed logs

        Returns:
            True if update was performed
        """
        stats = self.calculate_comprehensive_stats(trader_address)

        # Get existing trader data
        existing = self.db.get_trader_stats(trader_address)
        if not existing:
            if verbose:
                print(f"[STATS] Trader {trader_address[:10]}... not found in database")
            return False

        # Update database with both resolution and P&L stats
        self.db.add_or_update_trader(
            address=trader_address,
            total_trades=existing['total_trades'],
            successful_trades=stats['resolution_based']['won_trades'],
            # DISABLED 2026-06-18: win_rate is now owned by
            # reconcile_trader_aggregates.py (single-writer pattern).
            # Same scale/denominator mismatch as update_trader_win_rate above.
            # Omitting win_rate triggers the preserve-existing path in the UPSERT.
            # win_rate=stats['resolution_based']['win_rate'],
            total_volume=existing['total_volume'],
            is_flagged=existing['is_flagged']
        )

        # Update P&L fields separately
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE traders
            SET
                realized_pnl = ?,
                avg_roi = ?,
                total_invested = ?,
                closed_positions = ?,
                open_positions = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE address = ?
        """, (
            stats['pnl_based']['realized_pnl'],
            stats['pnl_based']['avg_roi'],
            stats['pnl_based']['total_invested'],
            stats['pnl_based']['closed_positions'],
            stats['pnl_based']['open_positions'],
            trader_address
        ))

        conn.commit()
        conn.close()

        if verbose:
            print(f"[STATS] {trader_address[:10]}...")
            print(f"  Resolution: Win Rate: {stats['resolution_based']['win_rate']:.1f}% | "
                  f"Resolved: {stats['resolution_based']['resolved_trades']}")
            print(f"  P&L: ${stats['pnl_based']['realized_pnl']:,.2f} | "
                  f"ROI: {stats['pnl_based']['avg_roi']:.1f}% | "
                  f"Positions: {stats['pnl_based']['closed_positions']} closed")

        return True
