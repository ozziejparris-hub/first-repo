#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regret Analysis Tool for Polymarket Traders

Based on game theory concepts, this tool measures how much better traders
COULD HAVE done with perfect hindsight by comparing actual returns against
optimal returns.

Regret = (Best possible return) - (Actual return)

Lower regret = Better decision-making
Higher regret = More money left on the table
"""

import sys
import os
import sqlite3
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Configure console encoding for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data',
    'polymarket_tracker.db'
)


@dataclass
class TradeRecord:
    """Represents a single trade."""
    trade_id: str
    trader_address: str
    market_id: str
    outcome: str
    shares: float
    price: float
    side: str
    timestamp: datetime


@dataclass
class MarketResolution:
    """Represents a resolved market."""
    market_id: str
    title: str
    winning_outcome: str
    resolution_date: datetime


@dataclass
class RegretMetrics:
    """Comprehensive regret metrics for a trader."""
    trader_address: str
    resolved_markets_count: int
    actual_return: float
    optimal_return: float
    total_regret: float
    average_regret_per_trade: float
    regret_rate: float  # As percentage
    total_invested: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float


class RegretAnalyzer:
    """Main class for calculating and analyzing trader regret."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize the regret analyzer.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.conn = None

    def __enter__(self):
        """Context manager entry."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.conn:
            self.conn.close()

    def get_resolved_markets(self) -> List[MarketResolution]:
        """Get all resolved markets from database.

        Returns:
            List of MarketResolution objects
        """
        cursor = self.conn.cursor()

        query = """
            SELECT market_id, title, winning_outcome, resolution_date
            FROM markets
            WHERE resolved = 1
                AND winning_outcome IS NOT NULL
                AND winning_outcome != ''
            ORDER BY resolution_date DESC
        """

        cursor.execute(query)

        markets = []
        for row in cursor.fetchall():
            markets.append(MarketResolution(
                market_id=row['market_id'],
                title=row['title'],
                winning_outcome=row['winning_outcome'],
                resolution_date=datetime.fromisoformat(row['resolution_date'])
                    if row['resolution_date'] else None
            ))

        return markets

    def get_trader_trades_for_market(
        self,
        trader_address: str,
        market_id: str
    ) -> List[TradeRecord]:
        """Get all trades by a specific trader for a specific market.

        Args:
            trader_address: Trader's wallet address
            market_id: Market identifier

        Returns:
            List of TradeRecord objects
        """
        cursor = self.conn.cursor()

        query = """
            SELECT trade_id, trader_address, market_id, outcome, shares,
                   price, side, timestamp
            FROM trades
            WHERE trader_address = ? AND market_id = ?
            ORDER BY timestamp ASC
        """

        cursor.execute(query, (trader_address, market_id))

        trades = []
        for row in cursor.fetchall():
            trades.append(TradeRecord(
                trade_id=row['trade_id'],
                trader_address=row['trader_address'],
                market_id=row['market_id'],
                outcome=row['outcome'],
                shares=row['shares'],
                price=row['price'],
                side=row['side'],
                timestamp=datetime.fromisoformat(row['timestamp'])
                    if row['timestamp'] else None
            ))

        return trades

    def get_all_market_trades(self, market_id: str) -> List[TradeRecord]:
        """Get all trades for a specific market.

        Args:
            market_id: Market identifier

        Returns:
            List of TradeRecord objects
        """
        cursor = self.conn.cursor()

        query = """
            SELECT trade_id, trader_address, market_id, outcome, shares,
                   price, side, timestamp
            FROM trades
            WHERE market_id = ?
            ORDER BY timestamp ASC
        """

        cursor.execute(query, (market_id,))

        trades = []
        for row in cursor.fetchall():
            trades.append(TradeRecord(
                trade_id=row['trade_id'],
                trader_address=row['trader_address'],
                market_id=row['market_id'],
                outcome=row['outcome'],
                shares=row['shares'],
                price=row['price'],
                side=row['side'],
                timestamp=datetime.fromisoformat(row['timestamp'])
                    if row['timestamp'] else None
            ))

        return trades

    def calculate_actual_return(
        self,
        trades: List[TradeRecord],
        winning_outcome: str
    ) -> Tuple[float, float]:
        """Calculate actual return from a list of trades.

        Args:
            trades: List of trades to analyze
            winning_outcome: The outcome that won (e.g., "Yes" or "No")

        Returns:
            Tuple of (profit/loss, total_invested)
        """
        total_cost = 0.0
        total_payout = 0.0

        # Track net position for each outcome
        positions = defaultdict(float)  # outcome -> net shares

        for trade in trades:
            cost = trade.shares * trade.price

            if trade.side.upper() == 'BUY':
                # Buying shares
                total_cost += cost
                positions[trade.outcome] += trade.shares
            else:  # SELL
                # Selling shares (getting money back)
                total_cost -= cost
                positions[trade.outcome] -= trade.shares

        # Calculate payout based on final positions
        for outcome, shares in positions.items():
            if outcome == winning_outcome and shares > 0:
                # Each winning share pays out $1
                total_payout += shares

        profit = total_payout - total_cost

        return profit, abs(total_cost)

    def calculate_market_optimal_return(
        self,
        market_id: str,
        winning_outcome: str,
        initial_capital: float,
        before_timestamp: Optional[datetime] = None
    ) -> float:
        """Calculate the optimal return possible for a market.

        This finds the best price at which the winning outcome traded
        (before a given timestamp if specified) and calculates maximum profit.

        Args:
            market_id: Market identifier
            winning_outcome: The outcome that won
            initial_capital: Amount to invest
            before_timestamp: Only consider prices before this time

        Returns:
            Optimal profit possible with perfect foresight
        """
        all_trades = self.get_all_market_trades(market_id)

        if not all_trades:
            return 0.0

        # Filter trades for the winning outcome and before timestamp
        winning_trades = [
            t for t in all_trades
            if t.outcome == winning_outcome
            and t.side.upper() == 'BUY'
            and (before_timestamp is None or t.timestamp <= before_timestamp)
        ]

        if not winning_trades:
            return 0.0

        # Find the best (lowest) price for the winning outcome
        best_price = min(t.price for t in winning_trades)

        # With perfect foresight, buy at best price
        # Each share costs best_price and pays out $1
        shares_bought = initial_capital / best_price
        payout = shares_bought * 1.0  # Each share pays $1
        profit = payout - initial_capital

        return profit

    def calculate_trader_regret(
        self,
        trader_address: str
    ) -> Optional[RegretMetrics]:
        """Calculate comprehensive regret metrics for a trader.

        Args:
            trader_address: Trader's wallet address

        Returns:
            RegretMetrics object or None if no resolved markets
        """
        resolved_markets = self.get_resolved_markets()

        if not resolved_markets:
            logger.warning("No resolved markets found in database")
            return None

        total_actual_return = 0.0
        total_optimal_return = 0.0
        total_invested = 0.0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        markets_participated = 0

        for market in resolved_markets:
            trades = self.get_trader_trades_for_market(
                trader_address,
                market.market_id
            )

            if not trades:
                continue

            markets_participated += 1
            total_trades += len(trades)

            # Calculate actual return
            actual_profit, invested = self.calculate_actual_return(
                trades,
                market.winning_outcome
            )

            total_actual_return += actual_profit
            total_invested += invested

            if actual_profit > 0:
                winning_trades += 1
            elif actual_profit < 0:
                losing_trades += 1

            # Calculate optimal return (using capital actually invested)
            if invested > 0:
                # Use timestamp of trader's last trade as cutoff
                last_trade_time = max(t.timestamp for t in trades)

                optimal_profit = self.calculate_market_optimal_return(
                    market.market_id,
                    market.winning_outcome,
                    invested,
                    before_timestamp=last_trade_time
                )

                total_optimal_return += optimal_profit

        if markets_participated == 0:
            logger.warning(
                f"Trader {trader_address[:10]}... has no trades in resolved markets"
            )
            return None

        # Calculate regret metrics
        total_regret = total_optimal_return - total_actual_return
        avg_regret_per_trade = total_regret / total_trades if total_trades > 0 else 0

        # Regret rate as percentage of optimal return
        if total_optimal_return > 0:
            regret_rate = (total_regret / total_optimal_return) * 100
        else:
            regret_rate = 0.0

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        return RegretMetrics(
            trader_address=trader_address,
            resolved_markets_count=markets_participated,
            actual_return=total_actual_return,
            optimal_return=total_optimal_return,
            total_regret=total_regret,
            average_regret_per_trade=avg_regret_per_trade,
            regret_rate=regret_rate,
            total_invested=total_invested,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate
        )

    def analyze_all_traders(self) -> pd.DataFrame:
        """Analyze regret for all traders with trades in resolved markets.

        Returns:
            DataFrame with regret metrics for all traders
        """
        cursor = self.conn.cursor()

        # Get all unique traders who have trades
        cursor.execute("SELECT DISTINCT trader_address FROM trades")
        all_traders = [row[0] for row in cursor.fetchall()]

        logger.info(f"Analyzing regret for {len(all_traders)} traders...")

        results = []
        for i, trader in enumerate(all_traders, 1):
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(all_traders)} traders analyzed")

            metrics = self.calculate_trader_regret(trader)

            if metrics:
                results.append({
                    'trader_address': metrics.trader_address,
                    'resolved_markets': metrics.resolved_markets_count,
                    'actual_return': metrics.actual_return,
                    'optimal_return': metrics.optimal_return,
                    'total_regret': metrics.total_regret,
                    'avg_regret_per_trade': metrics.average_regret_per_trade,
                    'regret_rate': metrics.regret_rate,
                    'total_invested': metrics.total_invested,
                    'total_trades': metrics.total_trades,
                    'winning_trades': metrics.winning_trades,
                    'losing_trades': metrics.losing_trades,
                    'win_rate': metrics.win_rate
                })

        if not results:
            logger.warning("No traders found with trades in resolved markets")
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # Sort by lowest regret (best performers)
        df = df.sort_values('total_regret', ascending=True)
        df['rank'] = range(1, len(df) + 1)

        logger.info(f"Successfully analyzed {len(df)} traders")

        return df

    def get_all_traders(self) -> List[str]:
        """Get all trader addresses from database.

        Returns:
            List of trader addresses
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT trader_address FROM trades")
        return [row[0] for row in cursor.fetchall()]


class RegretVisualizer:
    """Handles visualization of regret analysis results."""

    def __init__(self, output_dir: str = "analysis/output"):
        """Initialize visualizer.

        Args:
            output_dir: Directory to save plots
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # Set style
        sns.set_style("whitegrid")
        plt.rcParams['figure.figsize'] = (12, 8)

    def plot_regret_distribution(self, df: pd.DataFrame, save: bool = True):
        """Plot histogram of regret distribution.

        Args:
            df: DataFrame with regret metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.hist(df['total_regret'], bins=50, edgecolor='black', alpha=0.7)
        ax.set_xlabel('Total Regret ($)', fontsize=12)
        ax.set_ylabel('Number of Traders', fontsize=12)
        ax.set_title('Distribution of Trader Regret', fontsize=14, fontweight='bold')
        ax.axvline(df['total_regret'].median(), color='red', linestyle='--',
                   label=f'Median: ${df["total_regret"].median():.2f}')
        ax.legend()

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'regret_distribution.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_actual_vs_optimal(self, df: pd.DataFrame, save: bool = True):
        """Plot scatter of actual vs optimal returns.

        Args:
            df: DataFrame with regret metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 8))

        scatter = ax.scatter(
            df['optimal_return'],
            df['actual_return'],
            c=df['regret_rate'],
            cmap='RdYlGn_r',
            s=100,
            alpha=0.6,
            edgecolors='black'
        )

        # Add diagonal line (perfect performance)
        max_val = max(df['optimal_return'].max(), df['actual_return'].max())
        min_val = min(df['optimal_return'].min(), df['actual_return'].min())
        ax.plot([min_val, max_val], [min_val, max_val], 'k--',
                label='Perfect Performance (0% Regret)', linewidth=2)

        ax.set_xlabel('Optimal Return ($)', fontsize=12)
        ax.set_ylabel('Actual Return ($)', fontsize=12)
        ax.set_title('Actual Returns vs Optimal Returns', fontsize=14, fontweight='bold')

        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('Regret Rate (%)', fontsize=12)

        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'actual_vs_optimal.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_top_traders(self, df: pd.DataFrame, top_n: int = 20, save: bool = True):
        """Plot top traders by lowest regret.

        Args:
            df: DataFrame with regret metrics
            top_n: Number of top traders to show
            save: Whether to save the plot
        """
        top_traders = df.nsmallest(top_n, 'total_regret')

        fig, ax = plt.subplots(figsize=(14, 10))

        # Create labels with truncated addresses
        labels = [f"{addr[:6]}...{addr[-4:]}" for addr in top_traders['trader_address']]

        bars = ax.barh(labels, top_traders['total_regret'], color='steelblue',
                       edgecolor='black')

        ax.set_xlabel('Total Regret ($)', fontsize=12)
        ax.set_ylabel('Trader Address', fontsize=12)
        ax.set_title(f'Top {top_n} Traders by Lowest Regret (Best Performers)',
                     fontsize=14, fontweight='bold')
        ax.invert_yaxis()

        # Add value labels
        for i, (bar, val) in enumerate(zip(bars, top_traders['total_regret'])):
            ax.text(val + 0.01 * ax.get_xlim()[1], bar.get_y() + bar.get_height()/2,
                   f'${val:.2f}', va='center', fontsize=9)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'top_traders_by_regret.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_regret_rate_distribution(self, df: pd.DataFrame, save: bool = True):
        """Plot distribution of regret rates.

        Args:
            df: DataFrame with regret metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.hist(df['regret_rate'], bins=50, edgecolor='black', alpha=0.7, color='coral')
        ax.set_xlabel('Regret Rate (%)', fontsize=12)
        ax.set_ylabel('Number of Traders', fontsize=12)
        ax.set_title('Distribution of Regret Rates', fontsize=14, fontweight='bold')
        ax.axvline(df['regret_rate'].median(), color='red', linestyle='--',
                   label=f'Median: {df["regret_rate"].median():.1f}%')
        ax.legend()

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'regret_rate_distribution.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()


def print_trader_report(metrics: RegretMetrics, rank: Optional[int] = None,
                       total_traders: Optional[int] = None):
    """Print a formatted report for a single trader.

    Args:
        metrics: RegretMetrics object
        rank: Trader's rank (optional)
        total_traders: Total number of traders analyzed (optional)
    """
    print("\n" + "="*80)
    print(f"REGRET ANALYSIS FOR TRADER: {metrics.trader_address}")
    print("="*80)

    print(f"\n📊 PERFORMANCE SUMMARY:")
    print(f"  Resolved Markets Participated: {metrics.resolved_markets_count}")
    print(f"  Total Trades: {metrics.total_trades}")
    print(f"  Total Invested: ${metrics.total_invested:,.2f}")

    print(f"\n💰 RETURNS:")
    print(f"  Actual Total Return: ${metrics.actual_return:,.2f}")
    print(f"  Optimal Total Return: ${metrics.optimal_return:,.2f}")
    print(f"  Actual ROI: {(metrics.actual_return/metrics.total_invested*100):.2f}%"
          if metrics.total_invested > 0 else "  Actual ROI: N/A")
    print(f"  Optimal ROI: {(metrics.optimal_return/metrics.total_invested*100):.2f}%"
          if metrics.total_invested > 0 else "  Optimal ROI: N/A")

    print(f"\n😔 REGRET METRICS:")
    print(f"  Total Regret: ${metrics.total_regret:,.2f}")
    print(f"  Average Regret per Trade: ${metrics.average_regret_per_trade:.2f}")
    print(f"  Regret Rate: {metrics.regret_rate:.1f}%")

    print(f"\n🎯 WIN/LOSS RECORD:")
    print(f"  Winning Trades: {metrics.winning_trades}")
    print(f"  Losing Trades: {metrics.losing_trades}")
    print(f"  Win Rate: {metrics.win_rate:.1f}%")

    print(f"\n📈 INTERPRETATION:")
    if metrics.regret_rate < 20:
        interpretation = "EXCELLENT - Near-optimal decision making!"
    elif metrics.regret_rate < 40:
        interpretation = "GOOD - Above average performance"
    elif metrics.regret_rate < 60:
        interpretation = "AVERAGE - Moderate room for improvement"
    elif metrics.regret_rate < 80:
        interpretation = "BELOW AVERAGE - Significant regret"
    else:
        interpretation = "POOR - Substantial opportunity cost"

    print(f"  This trader left {metrics.regret_rate:.1f}% of potential profits on the table.")
    print(f"  Performance Rating: {interpretation}")

    if rank and total_traders:
        print(f"\n🏆 RANKING:")
        print(f"  Rank: #{rank} out of {total_traders} traders")
        print(f"  (Lower regret is better)")

    print("\n" + "="*80 + "\n")


def generate_summary_report(df: pd.DataFrame, output_file: str = None):
    """Generate and save a comprehensive summary report.

    Args:
        df: DataFrame with regret metrics
        output_file: Optional path to save report
    """
    report = []
    report.append("="*80)
    report.append("COMPREHENSIVE REGRET ANALYSIS REPORT")
    report.append("="*80)
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Total Traders Analyzed: {len(df)}")

    report.append("\n" + "-"*80)
    report.append("AGGREGATE STATISTICS")
    report.append("-"*80)

    report.append(f"\nTotal Regret Across All Traders: ${df['total_regret'].sum():,.2f}")
    report.append(f"Average Regret per Trader: ${df['total_regret'].mean():,.2f}")
    report.append(f"Median Regret: ${df['total_regret'].median():,.2f}")
    report.append(f"\nAverage Regret Rate: {df['regret_rate'].mean():.1f}%")
    report.append(f"Median Regret Rate: {df['regret_rate'].median():.1f}%")

    report.append(f"\nTotal Actual Returns: ${df['actual_return'].sum():,.2f}")
    report.append(f"Total Optimal Returns: ${df['optimal_return'].sum():,.2f}")
    report.append(f"Total Money Left on Table: ${(df['optimal_return'].sum() - df['actual_return'].sum()):,.2f}")

    report.append("\n" + "-"*80)
    report.append("TOP 10 TRADERS (Lowest Regret)")
    report.append("-"*80)

    top_10 = df.nsmallest(10, 'total_regret')
    for i, row in top_10.iterrows():
        report.append(f"\n#{row['rank']}. {row['trader_address']}")
        report.append(f"   Regret: ${row['total_regret']:,.2f} ({row['regret_rate']:.1f}%)")
        report.append(f"   Actual Return: ${row['actual_return']:,.2f} | Optimal: ${row['optimal_return']:,.2f}")
        report.append(f"   Markets: {row['resolved_markets']} | Trades: {row['total_trades']}")

    report.append("\n" + "-"*80)
    report.append("BOTTOM 10 TRADERS (Highest Regret)")
    report.append("-"*80)

    bottom_10 = df.nlargest(10, 'total_regret')
    for i, row in bottom_10.iterrows():
        report.append(f"\n#{row['rank']}. {row['trader_address']}")
        report.append(f"   Regret: ${row['total_regret']:,.2f} ({row['regret_rate']:.1f}%)")
        report.append(f"   Actual Return: ${row['actual_return']:,.2f} | Optimal: ${row['optimal_return']:,.2f}")
        report.append(f"   Markets: {row['resolved_markets']} | Trades: {row['total_trades']}")

    report.append("\n" + "="*80)

    report_text = "\n".join(report)
    print(report_text)

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        logger.info(f"Report saved to {output_file}")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Regret Analysis Tool for Polymarket Traders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a specific trader
  python regret_analysis.py --trader 0x1234567890abcdef...

  # Analyze all traders
  python regret_analysis.py --all

  # Generate comprehensive report
  python regret_analysis.py --report

  # Analyze all and save visualizations
  python regret_analysis.py --all --visualize
        """
    )

    parser.add_argument(
        '--trader',
        type=str,
        help='Analyze a specific trader address'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='Analyze all traders'
    )

    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate comprehensive summary report'
    )

    parser.add_argument(
        '--visualize',
        action='store_true',
        help='Generate visualization plots'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='analysis/output/regret_report.txt',
        help='Output file path for report'
    )

    parser.add_argument(
        '--db',
        type=str,
        default=DB_PATH,
        help='Path to database file'
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.trader, args.all, args.report]):
        parser.print_help()
        sys.exit(1)

    # Check if database exists
    if not os.path.exists(args.db):
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    try:
        with RegretAnalyzer(args.db) as analyzer:

            # Check if there are resolved markets
            resolved_markets = analyzer.get_resolved_markets()
            if not resolved_markets:
                logger.error(
                    "No resolved markets found in database. "
                    "Regret analysis requires markets with known outcomes."
                )
                print("\n⚠️  No resolved markets available yet.")
                print("Regret analysis will be possible once markets start resolving.")
                print("Check back after the monitoring system has tracked some market resolutions.\n")
                sys.exit(0)

            logger.info(f"Found {len(resolved_markets)} resolved markets")

            # Analyze specific trader
            if args.trader:
                logger.info(f"Analyzing trader: {args.trader}")
                metrics = analyzer.calculate_trader_regret(args.trader)

                if metrics:
                    # Get rank if analyzing all
                    if args.all:
                        df = analyzer.analyze_all_traders()
                        rank = df[df['trader_address'] == args.trader]['rank'].values[0]
                        print_trader_report(metrics, rank, len(df))
                    else:
                        print_trader_report(metrics)
                else:
                    logger.warning(
                        f"No data found for trader {args.trader} in resolved markets"
                    )

            # Analyze all traders
            if args.all or args.report:
                logger.info("Analyzing all traders...")
                df = analyzer.analyze_all_traders()

                if df.empty:
                    logger.error("No trader data found")
                    sys.exit(1)

                # Generate report
                if args.report:
                    generate_summary_report(df, args.output)

                # Generate visualizations
                if args.visualize and not df.empty:
                    logger.info("Generating visualizations...")
                    viz = RegretVisualizer()

                    viz.plot_regret_distribution(df)
                    viz.plot_actual_vs_optimal(df)
                    viz.plot_top_traders(df)
                    viz.plot_regret_rate_distribution(df)

                    logger.info("All visualizations generated successfully")

                # Print summary if not already printed
                if not args.report:
                    print(f"\n✅ Analyzed {len(df)} traders")
                    print(f"Average Regret: ${df['total_regret'].mean():.2f}")
                    print(f"Average Regret Rate: {df['regret_rate'].mean():.1f}%")
                    print(f"\nTop 5 Traders (Lowest Regret):")
                    for i, row in df.head(5).iterrows():
                        print(f"  #{row['rank']}. {row['trader_address'][:10]}... - "
                              f"Regret: ${row['total_regret']:.2f} ({row['regret_rate']:.1f}%)")

    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Analysis complete!")


if __name__ == "__main__":
    main()
