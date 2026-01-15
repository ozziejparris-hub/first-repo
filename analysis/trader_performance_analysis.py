#!/usr/bin/env python3
"""
Trader Performance Analysis Script

Reads pre-calculated performance metrics from the database.
The monitoring system already tracks real-time P&L via position_tracker.py.
"""

import sqlite3
import csv
import os
from datetime import datetime
from typing import Dict, Optional


class TraderPerformanceAnalyzer:
    """Reads trader performance from database (already calculated by monitoring)."""

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def analyze_trader_performance(self, days_filter: Optional[int] = None) -> Dict:
        """
        Read trader performance from database.

        Returns dict with trader_address as key and metrics as value.
        """
        print(f"\n{'='*70}")
        print(f"TRADER PERFORMANCE ANALYSIS")
        print(f"Reading from database (real-time P&L tracking)")
        print(f"{'='*70}\n")

        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Read performance data directly from traders table
        cursor.execute("""
            SELECT
                address as trader_address,
                total_trades,
                successful_trades,
                win_rate,
                total_volume,
                realized_pnl,
                unrealized_pnl,
                total_pnl,
                avg_roi,
                total_invested,
                closed_positions,
                open_positions
            FROM traders
            WHERE total_trades >= 10
            ORDER BY total_pnl DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        print(f"Found {len(rows)} traders with 10+ trades\n")

        trader_metrics = {}

        for row in rows:
            # Calculate ROI percentage from total_pnl and total_invested
            total_invested = float(row['total_invested'] or 0)
            total_pnl = float(row['total_pnl'] or 0)

            if total_invested > 0:
                roi_pct = (total_pnl / total_invested) * 100
            else:
                roi_pct = 0.0

            # Use avg_roi from database if available, otherwise calculate
            avg_roi_db = row['avg_roi']
            if avg_roi_db is not None:
                roi_pct = float(avg_roi_db)

            trader_metrics[row['trader_address']] = {
                'trader_address': row['trader_address'],
                'total_trades': row['total_trades'],
                'successful_trades': row['successful_trades'] or 0,
                'win_rate': (row['win_rate'] or 0) * 100,  # Convert to percentage
                'total_volume': row['total_volume'] or 0,
                'realized_pnl': row['realized_pnl'] or 0,
                'unrealized_pnl': row['unrealized_pnl'] or 0,
                'total_pnl': total_pnl,
                'total_invested': total_invested,
                'roi': roi_pct,
                'closed_positions': row['closed_positions'] or 0,
                'open_positions': row['open_positions'] or 0,
                # For compatibility with old format
                'resolved_trades': row['closed_positions'] or 0,
                'winning_trades': row['successful_trades'] or 0,
                'losing_trades': (row['closed_positions'] or 0) - (row['successful_trades'] or 0),
                'combined_score': ((row['win_rate'] or 0) * 50 + (roi_pct if abs(roi_pct) < 100 else 0) * 0.5)
            }

        print(f"Loaded performance metrics for {len(trader_metrics)} traders\n")

        return trader_metrics

    def generate_report(self, trader_metrics: Dict, days_filter: Optional[int] = None):
        """Generate and display performance report."""

        print(f"\n{'='*70}")
        print(f"PERFORMANCE REPORT")
        print(f"{'='*70}\n")

        if not trader_metrics:
            print("No trader data to analyze")
            return

        # Calculate statistics
        all_win_rates = [m['win_rate'] for m in trader_metrics.values() if m['win_rate'] > 0]
        all_rois = [m['roi'] for m in trader_metrics.values()]
        all_pnls = [m['total_pnl'] for m in trader_metrics.values()]

        avg_win_rate = sum(all_win_rates) / len(all_win_rates) if all_win_rates else 0
        median_roi = sorted(all_rois)[len(all_rois) // 2] if all_rois else 0
        total_trades = sum(m['total_trades'] for m in trader_metrics.values())
        total_closed = sum(m['closed_positions'] for m in trader_metrics.values())

        print(f"[STATS] OVERALL STATISTICS:")
        print(f"   Total trades: {total_trades:,}")
        print(f"   Closed positions: {total_closed:,}")
        print(f"   Average win rate: {avg_win_rate:.2f}%")
        print(f"   Median ROI: {median_roi:.2f}%")
        print(f"   Total P&L: ${sum(all_pnls):,.2f}")

        # Top 10 by ROI
        print(f"\n{'='*70}")
        print(f"[TOP] TOP 10 TRADERS BY ROI")
        print(f"{'='*70}")

        top_roi = sorted(
            trader_metrics.values(),
            key=lambda x: x['roi'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<20}{'ROI':<12}{'P&L':<15}{'Win Rate':<12}")
        print(f"{'-'*70}")

        for i, trader in enumerate(top_roi, 1):
            addr_short = trader['trader_address'][:18] + "..."
            pnl = f"${trader['total_pnl']:,.2f}"
            print(f"{i:<6}{addr_short:<20}{trader['roi']:>6.2f}%{pnl:>13}{trader['win_rate']:>9.2f}%")

        print(f"\n{'='*70}\n")

    def save_to_csv(self, trader_metrics: Dict, filename: str = "trader_performance_report.csv"):
        """Save analysis results to CSV file."""

        sorted_traders = sorted(
            trader_metrics.values(),
            key=lambda x: x.get('roi', 0),
            reverse=True
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            writer.writerow(['Analysis Timestamp', timestamp])
            writer.writerow([])
            writer.writerow([
                'Rank',
                'Trader Address',
                'Total Trades',
                'Closed Positions',
                'Open Positions',
                'Win Rate (%)',
                'Realized P&L ($)',
                'Unrealized P&L ($)',
                'Total P&L ($)',
                'Total Invested ($)',
                'ROI (%)',
                'Combined Score'
            ])

            for i, trader in enumerate(sorted_traders, 1):
                writer.writerow([
                    i,
                    trader['trader_address'],
                    trader['total_trades'],
                    trader['closed_positions'],
                    trader['open_positions'],
                    f"{trader['win_rate']:.2f}",
                    f"{trader['realized_pnl']:.2f}",
                    f"{trader['unrealized_pnl']:.2f}",
                    f"{trader['total_pnl']:.2f}",
                    f"{trader['total_invested']:.2f}",
                    f"{trader['roi']:.2f}",
                    f"{trader['combined_score']:.2f}"
                ])

        print(f"[OK] Report saved to: {filename}")
        print(f"   Total traders: {len(sorted_traders)}")
        print(f"   Timestamp: {timestamp}\n")


def main():
    """Main entry point."""
    # Initialize analyzer (no API key needed - reads from database)
    analyzer = TraderPerformanceAnalyzer()

    # Check database
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
    if not os.path.exists(db_path):
        print("[X] Error: polymarket_tracker.db not found in /data/")
        return

    # Ensure reports directory
    reports_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    # Run analysis for different time periods
    print("\nSelect analysis period:")
    print("1. Last 7 days")
    print("2. Last 30 days")
    print("3. All time")

    choice = input("\nEnter choice (1-3) [default: 3]: ").strip() or "3"

    # Note: days_filter not used since we read from database
    # Database already has cumulative P&L
    metrics = analyzer.analyze_trader_performance(None)
    analyzer.generate_report(metrics, None)

    csv_path = os.path.join(reports_dir, f"trader_performance_alltime_{datetime.now().strftime('%Y%m%d')}.csv")
    analyzer.save_to_csv(metrics, csv_path)


if __name__ == "__main__":
    main()
