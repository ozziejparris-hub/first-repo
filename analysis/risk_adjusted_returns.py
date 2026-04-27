#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Risk-Adjusted Returns Analysis Tool for Polymarket Traders

Measures trader performance accounting for risk taken.
Separates skill from luck by analyzing return volatility and drawdowns.

Key Metrics:
- Sharpe Ratio: Return per unit of total risk
- Sortino Ratio: Return per unit of downside risk
- Calmar Ratio: Return per unit of maximum drawdown
- Maximum Drawdown: Largest peak-to-trough decline
- Value at Risk (VaR): Expected maximum loss at confidence level
"""

import sys
import os
import sqlite3
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# Configure console encoding for Windows
if sys.platform == 'win32':
    import codecs
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')

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

# Constants
RISK_FREE_RATE = 0.0  # Can adjust for treasury rate
MIN_TRADES_FOR_ANALYSIS = 20
SHARPE_EXCELLENT = 2.0
SHARPE_GOOD = 1.0
SORTINO_EXCELLENT = 2.5
SORTINO_GOOD = 1.5


@dataclass
class TradeReturn:
    """Represents a single trade with its return."""
    trader_address: str
    market_id: str
    timestamp: datetime
    capital_invested: float
    profit: float
    return_pct: float
    won: bool


@dataclass
class RiskMetrics:
    """Comprehensive risk-adjusted performance metrics."""
    trader_address: str
    analysis_start: datetime
    analysis_end: datetime
    total_trades: int
    resolved_markets: int

    # Returns
    total_return: float
    total_return_pct: float
    avg_return_per_trade: float
    avg_return_pct: float

    # Win/Loss
    win_rate: float
    wins: int
    losses: int
    avg_win: float
    avg_loss: float
    win_loss_ratio: float

    # Risk-Adjusted Metrics
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # Risk Metrics
    volatility: float
    downside_volatility: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    max_drawdown_start: Optional[datetime]
    max_drawdown_end: Optional[datetime]
    current_drawdown_pct: float

    # VaR
    var_95: float
    var_99: float

    # Distribution Stats
    median_return: float
    skewness: float
    kurtosis: float


class RiskAdjustedAnalyzer:
    """Main class for calculating risk-adjusted returns."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize the analyzer.

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

    def get_trader_returns(
        self,
        trader_address: str,
        window_days: Optional[int] = None
    ) -> List[TradeReturn]:
        """Get all trade returns for a trader.

        Args:
            trader_address: Trader's wallet address
            window_days: Optional window in days (e.g., 30, 90)

        Returns:
            List of TradeReturn objects
        """
        cursor = self.conn.cursor()

        # Build query with optional time window
        query = """
            SELECT
                t.trader_address,
                t.market_id,
                t.outcome,
                t.price,
                t.shares,
                t.timestamp,
                m.winning_outcome
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.condition_id
            WHERE t.trader_address = ?
                AND m.resolved = 1
                AND m.winning_outcome IS NOT NULL
                AND m.winning_outcome != ''
        """

        params = [trader_address]

        if window_days:
            cutoff_date = datetime.now() - timedelta(days=window_days)
            query += " AND t.timestamp >= ?"
            params.append(cutoff_date.isoformat())

        query += " ORDER BY t.timestamp ASC"

        cursor.execute(query, params)

        trade_returns = []
        for row in cursor.fetchall():
            # Calculate capital invested
            capital = row['shares'] * row['price']

            # Determine if trade won
            outcome = row['outcome']
            winning_outcome = row['winning_outcome']

            if outcome == winning_outcome:
                won = True
                # Profit = payout - cost
                # Payout for winning shares = shares * $1
                profit = row['shares'] * 1.0 - capital
            else:
                won = False
                # Lost entire investment
                profit = -capital

            # Calculate return percentage
            if capital > 0:
                return_pct = profit / capital
            else:
                continue  # Skip if no capital invested

            trade_returns.append(TradeReturn(
                trader_address=row['trader_address'],
                market_id=row['market_id'],
                timestamp=datetime.fromisoformat(row['timestamp'])
                    if row['timestamp'] else None,
                capital_invested=capital,
                profit=profit,
                return_pct=return_pct,
                won=won
            ))

        return trade_returns

    def calculate_sharpe_ratio(
        self,
        returns: List[float],
        risk_free_rate: float = RISK_FREE_RATE
    ) -> float:
        """Calculate Sharpe Ratio.

        Args:
            returns: List of return percentages
            risk_free_rate: Risk-free rate (default 0)

        Returns:
            Sharpe ratio
        """
        if not returns or len(returns) < 2:
            return 0.0

        avg_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        if std_return == 0:
            return 0.0

        sharpe = (avg_return - risk_free_rate) / std_return

        return sharpe

    def calculate_sortino_ratio(
        self,
        returns: List[float],
        risk_free_rate: float = RISK_FREE_RATE
    ) -> float:
        """Calculate Sortino Ratio.

        Only penalizes downside volatility.

        Args:
            returns: List of return percentages
            risk_free_rate: Risk-free rate (default 0)

        Returns:
            Sortino ratio
        """
        if not returns or len(returns) < 2:
            return 0.0

        avg_return = np.mean(returns)

        # Downside deviation (only negative returns)
        downside_returns = [r for r in returns if r < risk_free_rate]

        if not downside_returns:
            # No losses - return high value
            return 999.0

        downside_std = np.std(downside_returns, ddof=1)

        if downside_std == 0:
            return 0.0

        sortino = (avg_return - risk_free_rate) / downside_std

        return sortino

    def calculate_maximum_drawdown(
        self,
        trade_returns: List[TradeReturn]
    ) -> Tuple[float, int, Optional[datetime], Optional[datetime], float]:
        """Calculate maximum drawdown.

        Args:
            trade_returns: List of TradeReturn objects

        Returns:
            Tuple of (max_dd_pct, duration_days, start_date, end_date, current_dd_pct)
        """
        if not trade_returns:
            return 0.0, 0, None, None, 0.0

        # Build cumulative return curve
        initial_capital = 1000.0  # Arbitrary starting value
        cumulative = [initial_capital]
        timestamps = [trade_returns[0].timestamp]

        for trade in trade_returns:
            new_value = cumulative[-1] * (1 + trade.return_pct)
            cumulative.append(new_value)
            timestamps.append(trade.timestamp)

        # Find maximum drawdown
        peak = cumulative[0]
        peak_idx = 0
        max_dd = 0.0
        max_dd_start_idx = 0
        max_dd_end_idx = 0

        for i, value in enumerate(cumulative):
            if value > peak:
                peak = value
                peak_idx = i

            dd = (peak - value) / peak if peak > 0 else 0

            if dd > max_dd:
                max_dd = dd
                max_dd_start_idx = peak_idx
                max_dd_end_idx = i

        # Calculate duration
        if max_dd_start_idx < len(timestamps) and max_dd_end_idx < len(timestamps):
            start_date = timestamps[max_dd_start_idx]
            end_date = timestamps[max_dd_end_idx]
            duration = (end_date - start_date).days if end_date and start_date else 0
        else:
            start_date = None
            end_date = None
            duration = 0

        # Current drawdown
        current_peak = max(cumulative)
        current_value = cumulative[-1]
        current_dd = (current_peak - current_value) / current_peak if current_peak > 0 else 0

        return max_dd * 100, duration, start_date, end_date, current_dd * 100

    def calculate_calmar_ratio(
        self,
        avg_return: float,
        max_drawdown_pct: float
    ) -> float:
        """Calculate Calmar Ratio.

        Args:
            avg_return: Average return percentage
            max_drawdown_pct: Maximum drawdown percentage

        Returns:
            Calmar ratio
        """
        if max_drawdown_pct == 0:
            return 0.0

        # Annualize return (assuming trades are independent)
        calmar = avg_return / (max_drawdown_pct / 100)

        return calmar

    def calculate_value_at_risk(
        self,
        returns: List[float],
        confidence: float = 0.95
    ) -> Tuple[float, float]:
        """Calculate Value at Risk.

        Args:
            returns: List of return percentages
            confidence: Confidence level (0.95 = 95%, 0.99 = 99%)

        Returns:
            Tuple of (VaR_historical, VaR_parametric)
        """
        if not returns:
            return 0.0, 0.0

        # Historical VaR
        var_historical = np.percentile(returns, (1 - confidence) * 100)

        # Parametric VaR (assume normal distribution)
        avg_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        # Z-score for confidence level
        if confidence == 0.95:
            z_score = 1.645
        elif confidence == 0.99:
            z_score = 2.326
        else:
            z_score = stats.norm.ppf(confidence)

        var_parametric = avg_return - z_score * std_return

        return var_historical, var_parametric

    def calculate_risk_metrics(
        self,
        trader_address: str,
        window_days: Optional[int] = None
    ) -> Optional[RiskMetrics]:
        """Calculate comprehensive risk metrics for a trader.

        Args:
            trader_address: Trader's wallet address
            window_days: Optional analysis window in days

        Returns:
            RiskMetrics object or None if insufficient data
        """
        trade_returns = self.get_trader_returns(trader_address, window_days)

        if len(trade_returns) < MIN_TRADES_FOR_ANALYSIS:
            logger.warning(
                f"Trader {trader_address[:10]}... has insufficient trades "
                f"({len(trade_returns)}) for risk analysis"
            )
            return None

        # Extract return percentages
        returns = [t.return_pct for t in trade_returns]

        # Basic stats
        total_return = sum(t.profit for t in trade_returns)
        total_capital = sum(t.capital_invested for t in trade_returns)
        total_return_pct = (total_return / total_capital * 100) if total_capital > 0 else 0

        avg_return = np.mean([t.profit for t in trade_returns])
        avg_return_pct = np.mean(returns) * 100

        # Win/Loss
        wins = [t for t in trade_returns if t.won]
        losses = [t for t in trade_returns if not t.won]

        win_rate = len(wins) / len(trade_returns) * 100 if trade_returns else 0
        avg_win = np.mean([t.profit for t in wins]) if wins else 0
        avg_loss = np.mean([t.profit for t in losses]) if losses else 0
        win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # Risk-adjusted metrics
        sharpe = self.calculate_sharpe_ratio(returns)
        sortino = self.calculate_sortino_ratio(returns)

        # Volatility
        volatility = np.std(returns, ddof=1) * 100
        downside_returns = [r for r in returns if r < 0]
        downside_volatility = np.std(downside_returns, ddof=1) * 100 if downside_returns else 0

        # Maximum drawdown
        max_dd_pct, dd_duration, dd_start, dd_end, current_dd = \
            self.calculate_maximum_drawdown(trade_returns)

        # Calmar ratio
        calmar = self.calculate_calmar_ratio(avg_return_pct, max_dd_pct)

        # VaR
        var_95_hist, var_95_param = self.calculate_value_at_risk(returns, 0.95)
        var_99_hist, var_99_param = self.calculate_value_at_risk(returns, 0.99)

        # Use historical VaR (more conservative)
        var_95 = var_95_hist * 100
        var_99 = var_99_hist * 100

        # Distribution stats
        median_return = np.median(returns) * 100
        skewness = stats.skew(returns) if len(returns) > 2 else 0
        kurtosis = stats.kurtosis(returns) if len(returns) > 3 else 0

        # Analysis period
        analysis_start = trade_returns[0].timestamp
        analysis_end = trade_returns[-1].timestamp

        # Unique markets
        unique_markets = len(set(t.market_id for t in trade_returns))

        return RiskMetrics(
            trader_address=trader_address,
            analysis_start=analysis_start,
            analysis_end=analysis_end,
            total_trades=len(trade_returns),
            resolved_markets=unique_markets,
            total_return=total_return,
            total_return_pct=total_return_pct,
            avg_return_per_trade=avg_return,
            avg_return_pct=avg_return_pct,
            win_rate=win_rate,
            wins=len(wins),
            losses=len(losses),
            avg_win=avg_win,
            avg_loss=avg_loss,
            win_loss_ratio=win_loss_ratio,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            volatility=volatility,
            downside_volatility=downside_volatility,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_duration_days=dd_duration,
            max_drawdown_start=dd_start,
            max_drawdown_end=dd_end,
            current_drawdown_pct=current_dd,
            var_95=var_95,
            var_99=var_99,
            median_return=median_return,
            skewness=skewness,
            kurtosis=kurtosis
        )

    def compare_all_traders(self) -> pd.DataFrame:
        """Analyze risk-adjusted returns for all traders.

        Returns:
            DataFrame with risk metrics for all traders
        """
        cursor = self.conn.cursor()

        # Get all unique traders with trades in resolved markets
        cursor.execute("""
            SELECT DISTINCT t.trader_address
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.condition_id
            WHERE m.resolved = 1
                AND m.winning_outcome IS NOT NULL
                AND m.winning_outcome != ''
        """)

        all_traders = [row[0] for row in cursor.fetchall()]

        logger.info(f"Analyzing risk-adjusted returns for {len(all_traders)} traders...")

        results = []
        for i, trader in enumerate(all_traders, 1):
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(all_traders)} traders analyzed")

            metrics = self.calculate_risk_metrics(trader)

            if metrics:
                results.append({
                    'trader_address': metrics.trader_address,
                    'total_trades': metrics.total_trades,
                    'total_return': metrics.total_return,
                    'total_return_pct': metrics.total_return_pct,
                    'avg_return_pct': metrics.avg_return_pct,
                    'win_rate': metrics.win_rate,
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'sortino_ratio': metrics.sortino_ratio,
                    'calmar_ratio': metrics.calmar_ratio,
                    'volatility': metrics.volatility,
                    'max_drawdown_pct': metrics.max_drawdown_pct,
                    'var_95': metrics.var_95,
                    'win_loss_ratio': metrics.win_loss_ratio
                })

        if not results:
            logger.warning("No traders found with sufficient data")
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # Sort by Sharpe ratio (descending - higher is better)
        df = df.sort_values('sharpe_ratio', ascending=False)
        df['rank'] = range(1, len(df) + 1)

        logger.info(f"Successfully analyzed {len(df)} traders")

        return df

    def analyze_all_traders(self) -> dict:
        """Return risk metrics as a dict keyed by trader address.

        Adapter for unified_elo_system.py which expects
        {trader_address: {total_trades, sharpe_ratio, ...}}.
        """
        df = self.compare_all_traders()
        if df.empty:
            return {}
        result = {}
        for _, row in df.iterrows():
            result[row['trader_address']] = {
                'total_trades': row.get('total_trades', 0),
                'sharpe_ratio': row.get('sharpe_ratio', 0.0),
                'sortino_ratio': row.get('sortino_ratio', 0.0),
                'win_rate': row.get('win_rate', 0.0),
                'total_return_pct': row.get('total_return_pct', 0.0),
            }
        return result


class RiskVisualizer:
    """Handles visualization of risk-adjusted returns."""

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

    def plot_equity_curve_with_drawdown(
        self,
        trade_returns: List[TradeReturn],
        trader_address: str,
        save: bool = True
    ):
        """Plot equity curve with drawdown overlay.

        Args:
            trade_returns: List of TradeReturn objects
            trader_address: Trader's address for title
            save: Whether to save the plot
        """
        if not trade_returns:
            logger.warning("No trade data to plot")
            return

        # Build cumulative returns
        initial_capital = 1000.0
        equity = [initial_capital]
        dates = [trade_returns[0].timestamp]

        for trade in trade_returns:
            new_equity = equity[-1] * (1 + trade.return_pct)
            equity.append(new_equity)
            dates.append(trade.timestamp)

        # Calculate drawdown
        peak = [equity[0]]
        drawdown = [0]

        for i in range(1, len(equity)):
            peak.append(max(peak[-1], equity[i]))
            dd = (peak[i] - equity[i]) / peak[i] * 100 if peak[i] > 0 else 0
            drawdown.append(dd)

        # Create figure with two subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True,
                                        gridspec_kw={'height_ratios': [3, 1]})

        # Plot equity curve
        ax1.plot(dates, equity, linewidth=2, label='Portfolio Value')
        ax1.fill_between(dates, equity, initial_capital, alpha=0.3)
        ax1.axhline(y=initial_capital, color='gray', linestyle='--',
                    label='Initial Capital', alpha=0.5)
        ax1.set_ylabel('Portfolio Value ($)', fontsize=12, fontweight='bold')
        ax1.set_title(
            f'Equity Curve with Drawdown\nTrader: {trader_address[:10]}...',
            fontsize=14,
            fontweight='bold'
        )
        ax1.legend(loc='upper left')
        ax1.grid(True, alpha=0.3)

        # Plot drawdown
        ax2.fill_between(dates, 0, drawdown, color='red', alpha=0.3)
        ax2.plot(dates, drawdown, color='darkred', linewidth=2)
        ax2.set_ylabel('Drawdown (%)', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Date', fontsize=12, fontweight='bold')
        ax2.invert_yaxis()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(
                self.output_dir,
                f'equity_curve_{trader_address[:10]}.png'
            )
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_return_distribution(
        self,
        returns: List[float],
        var_95: float,
        var_99: float,
        trader_address: str,
        save: bool = True
    ):
        """Plot return distribution with VaR levels.

        Args:
            returns: List of return percentages
            var_95: 95% VaR
            var_99: 99% VaR
            trader_address: Trader's address
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot histogram
        ax.hist(returns, bins=30, density=True, alpha=0.7, edgecolor='black',
                label='Actual Returns')

        # Overlay normal distribution
        mu, sigma = np.mean(returns), np.std(returns)
        x = np.linspace(min(returns), max(returns), 100)
        ax.plot(x, stats.norm.pdf(x, mu, sigma), 'r-', linewidth=2,
                label='Normal Distribution')

        # Mark mean and median
        ax.axvline(np.mean(returns), color='green', linestyle='--',
                   linewidth=2, label=f'Mean: {np.mean(returns)*100:.1f}%')
        ax.axvline(np.median(returns), color='blue', linestyle='--',
                   linewidth=2, label=f'Median: {np.median(returns)*100:.1f}%')

        # Mark VaR levels
        ax.axvline(var_95/100, color='orange', linestyle=':',
                   linewidth=2, label=f'95% VaR: {var_95:.1f}%')
        ax.axvline(var_99/100, color='red', linestyle=':',
                   linewidth=2, label=f'99% VaR: {var_99:.1f}%')

        ax.set_xlabel('Return (%)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Density', fontsize=12, fontweight='bold')
        ax.set_title(
            f'Return Distribution\nTrader: {trader_address[:10]}...',
            fontsize=14,
            fontweight='bold'
        )
        ax.legend(loc='upper right')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(
                self.output_dir,
                f'return_dist_{trader_address[:10]}.png'
            )
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_risk_return_scatter(self, df: pd.DataFrame, save: bool = True):
        """Plot risk-return scatter for all traders.

        Args:
            df: DataFrame with trader metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 8))

        scatter = ax.scatter(
            df['volatility'],
            df['avg_return_pct'],
            c=df['sharpe_ratio'],
            cmap='RdYlGn',
            s=df['total_trades'] * 2,
            alpha=0.6,
            edgecolors='black'
        )

        # Add diagonal lines for constant Sharpe ratios
        x = np.linspace(0, df['volatility'].max(), 100)
        for sharpe in [0.5, 1.0, 1.5, 2.0, 2.5]:
            ax.plot(x, sharpe * x, 'k--', alpha=0.3, linewidth=1)
            ax.text(x[-1], sharpe * x[-1], f'Sharpe={sharpe}',
                   fontsize=8, alpha=0.5)

        ax.set_xlabel('Volatility (Standard Deviation %)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Average Return (%)', fontsize=12, fontweight='bold')
        ax.set_title('Risk-Return Profile\nPoint Size = Number of Trades',
                     fontsize=14, fontweight='bold')

        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('Sharpe Ratio', fontsize=12)

        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'risk_return_scatter.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_top_traders(self, df: pd.DataFrame, top_n: int = 20, save: bool = True):
        """Plot top traders by Sharpe ratio.

        Args:
            df: DataFrame with trader metrics
            top_n: Number of top traders to show
            save: Whether to save the plot
        """
        top_traders = df.nsmallest(top_n, 'rank')

        fig, ax = plt.subplots(figsize=(14, 10))

        # Create labels
        labels = [f"{addr[:6]}...{addr[-4:]}" for addr in top_traders['trader_address']]

        # Color code
        colors = []
        for sharpe in top_traders['sharpe_ratio']:
            if sharpe >= SHARPE_EXCELLENT:
                colors.append('green')
            elif sharpe >= SHARPE_GOOD:
                colors.append('yellow')
            else:
                colors.append('orange')

        bars = ax.barh(labels, top_traders['sharpe_ratio'], color=colors,
                       edgecolor='black')

        ax.set_xlabel('Sharpe Ratio', fontsize=12, fontweight='bold')
        ax.set_ylabel('Trader Address', fontsize=12, fontweight='bold')
        ax.set_title(f'Top {top_n} Traders by Sharpe Ratio',
                     fontsize=14, fontweight='bold')
        ax.invert_yaxis()

        # Add value labels
        for i, (bar, val) in enumerate(zip(bars, top_traders['sharpe_ratio'])):
            ax.text(val + 0.05, bar.get_y() + bar.get_height()/2,
                   f'{val:.2f}', va='center', fontsize=9)

        # Add threshold lines
        ax.axvline(SHARPE_GOOD, color='orange', linestyle='--',
                   linewidth=2, alpha=0.5, label=f'Good ({SHARPE_GOOD})')
        ax.axvline(SHARPE_EXCELLENT, color='green', linestyle='--',
                   linewidth=2, alpha=0.5, label=f'Excellent ({SHARPE_EXCELLENT})')

        ax.legend()

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'top_traders_sharpe.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()


def print_risk_report(metrics: RiskMetrics, rank: Optional[int] = None,
                     total_traders: Optional[int] = None):
    """Print comprehensive risk analysis report.

    Args:
        metrics: RiskMetrics object
        rank: Trader's rank (optional)
        total_traders: Total traders analyzed (optional)
    """
    print("\n" + "="*80)
    print(f"RISK-ADJUSTED RETURNS ANALYSIS: {metrics.trader_address}")
    print("="*80)

    # Analysis period
    duration_days = (metrics.analysis_end - metrics.analysis_start).days
    print(f"\n📅 ANALYSIS PERIOD:")
    print(f"  {metrics.analysis_start.strftime('%Y-%m-%d')} to "
          f"{metrics.analysis_end.strftime('%Y-%m-%d')} ({duration_days} days)")
    print(f"  Total Trades: {metrics.total_trades} | "
          f"Resolved Markets: {metrics.resolved_markets}")

    # Returns summary
    print(f"\n💰 RETURNS SUMMARY:")
    print(f"  Total Return: ${metrics.total_return:,.2f} "
          f"({metrics.total_return_pct:+.1f}%)")
    print(f"  Average Return per Trade: ${metrics.avg_return_per_trade:,.2f} "
          f"({metrics.avg_return_pct:.2f}%)")
    print(f"  Win Rate: {metrics.win_rate:.1f}% "
          f"({metrics.wins} wins, {metrics.losses} losses)")
    print(f"  Avg Win: ${metrics.avg_win:,.2f} | "
          f"Avg Loss: ${metrics.avg_loss:,.2f}")
    print(f"  Win/Loss Ratio: {metrics.win_loss_ratio:.2f}")

    # Risk-adjusted performance
    print(f"\n📊 RISK-ADJUSTED PERFORMANCE:")
    print("━" * 80)

    sharpe_rating = (
        "🏆 EXCEPTIONAL (Top 1%)" if metrics.sharpe_ratio >= 3.0 else
        "🏆 EXCELLENT (Top 5%)" if metrics.sharpe_ratio >= SHARPE_EXCELLENT else
        "✓ GOOD" if metrics.sharpe_ratio >= SHARPE_GOOD else
        "⚠ FAIR" if metrics.sharpe_ratio >= 0 else
        "✗ POOR"
    )

    sortino_rating = (
        "🏆 EXCELLENT" if metrics.sortino_ratio >= SORTINO_EXCELLENT else
        "✓ GOOD" if metrics.sortino_ratio >= SORTINO_GOOD else
        "⚠ FAIR" if metrics.sortino_ratio >= 0 else
        "✗ POOR"
    )

    calmar_rating = (
        "✓ GOOD" if metrics.calmar_ratio >= 1.0 else
        "⚠ FAIR" if metrics.calmar_ratio >= 0.5 else
        "✗ POOR"
    )

    print(f"  Sharpe Ratio:        {metrics.sharpe_ratio:>6.2f}  {sharpe_rating}")
    print(f"  Sortino Ratio:       {metrics.sortino_ratio:>6.2f}  {sortino_rating}")
    print(f"  Calmar Ratio:        {metrics.calmar_ratio:>6.2f}  {calmar_rating}")
    print("━" * 80)

    if rank and total_traders:
        percentile = (1 - rank / total_traders) * 100
        print(f"  Rank by Sharpe: #{rank} out of {total_traders} traders "
              f"({percentile:.1f}th percentile)")

    # Interpretation
    print(f"\n💡 INTERPRETATION:")
    if metrics.sharpe_ratio >= SHARPE_EXCELLENT:
        print(f"  This trader generates {metrics.sharpe_ratio:.2f} units of return for "
              f"every unit of risk taken.")
        print(f"  This is EXCELLENT performance - better than 95% of tracked traders.")
    elif metrics.sharpe_ratio >= SHARPE_GOOD:
        print(f"  This trader shows GOOD risk-adjusted returns with Sharpe of "
              f"{metrics.sharpe_ratio:.2f}.")
    else:
        print(f"  Sharpe ratio of {metrics.sharpe_ratio:.2f} suggests performance needs "
              f"improvement.")

    if metrics.sortino_ratio > metrics.sharpe_ratio * 1.3:
        print(f"  High Sortino ratio ({metrics.sortino_ratio:.2f}) indicates minimal "
              f"downside volatility.")

    # Risk metrics
    print(f"\n⚠️  RISK METRICS:")
    print(f"  Return Volatility: {metrics.volatility:.1f}% (std dev)")
    print(f"  Downside Volatility: {metrics.downside_volatility:.1f}% (only losses)")
    print(f"  Maximum Drawdown: {metrics.max_drawdown_pct:.1f}%", end="")

    if metrics.max_drawdown_start and metrics.max_drawdown_end:
        print(f" (occurred {metrics.max_drawdown_start.strftime('%b %d')} - "
              f"{metrics.max_drawdown_end.strftime('%b %d, %Y')})")
        print(f"    Duration: {metrics.max_drawdown_duration_days} days")
    else:
        print()

    print(f"  Current drawdown: {metrics.current_drawdown_pct:.1f}%", end="")
    if metrics.current_drawdown_pct < 5:
        print(" (minimal)")
    elif metrics.current_drawdown_pct < 10:
        print(" (minor)")
    else:
        print(" (⚠ significant)")

    print(f"\n📉 VALUE AT RISK (VaR):")
    print(f"  95% confidence: {metrics.var_95:.1f}% "
          f"(only 5% chance of losing more per trade)")
    print(f"  99% confidence: {metrics.var_99:.1f}%")

    # Distribution
    print(f"\n📊 RETURN DISTRIBUTION:")
    print(f"  Mean Return:     {metrics.avg_return_pct:.2f}%")
    print(f"  Median Return:   {metrics.median_return:.2f}%")
    print(f"  Skewness:        {metrics.skewness:+.2f} ", end="")
    if metrics.skewness > 0.5:
        print("(right-skewed - good! larger wins)")
    elif metrics.skewness < -0.5:
        print("(left-skewed - caution! larger losses)")
    else:
        print("(symmetric)")

    print(f"  Kurtosis:        {metrics.kurtosis:.1f} ", end="")
    if metrics.kurtosis > 3:
        print("(high tail risk - extreme events common)")
    elif metrics.kurtosis < 1:
        print("(low tail risk)")
    else:
        print("(moderate tail risk)")

    # Risk profile
    print(f"\n🎯 RISK PROFILE: ", end="")
    if metrics.max_drawdown_pct < 15:
        print("CONSERVATIVE")
        print("  This trader takes low risk with stable returns.")
    elif metrics.max_drawdown_pct < 25:
        print("MODERATE")
        print("  This trader balances risk and return appropriately.")
    elif metrics.max_drawdown_pct < 40:
        print("AGGRESSIVE")
        print("  This trader accepts higher risk for potential higher returns.")
    else:
        print("VERY AGGRESSIVE")
        print("  ⚠ This trader takes significant risk. Max drawdown exceeds 40%.")

    # Final verdict
    print(f"\n⭐ VERDICT:")
    if metrics.sharpe_ratio >= SHARPE_EXCELLENT and metrics.max_drawdown_pct < 30:
        print("  ★ Elite risk-adjusted performer")
        print("  ★ Strong returns with controlled risk")
        print("  ★ Pattern suggests skill rather than luck")
    elif metrics.sharpe_ratio >= SHARPE_GOOD:
        print("  ✓ Good risk-adjusted returns")
        print("  ✓ Reliable performer worth following")
    else:
        print("  ⚠ Risk-adjusted returns need improvement")
        print("  ⚠ Consider reducing position sizes or improving selection")

    print("\n" + "="*80 + "\n")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Risk-Adjusted Returns Analysis for Polymarket Traders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a specific trader
  python risk_adjusted_returns.py --trader 0x1234567890abcdef...

  # Analyze all traders
  python risk_adjusted_returns.py --all

  # Show top 20 by Sharpe ratio
  python risk_adjusted_returns.py --top 20

  # Generate report with visualizations
  python risk_adjusted_returns.py --report --visualize

  # Analyze with time window
  python risk_adjusted_returns.py --trader 0xABC --window 90
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
        help='Generate comprehensive comparison report'
    )

    parser.add_argument(
        '--visualize',
        action='store_true',
        help='Generate visualization plots'
    )

    parser.add_argument(
        '--top',
        type=int,
        metavar='N',
        help='Show top N traders by Sharpe ratio'
    )

    parser.add_argument(
        '--window',
        type=int,
        metavar='DAYS',
        help='Analysis window in days (e.g., 30, 90, 180)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='analysis/output/risk_report.txt',
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
    if not any([args.trader, args.all, args.report, args.top]):
        parser.print_help()
        sys.exit(1)

    # Check database
    if not os.path.exists(args.db):
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    try:
        with RiskAdjustedAnalyzer(args.db) as analyzer:

            # Check for resolved markets
            cursor = analyzer.conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT m.market_id)
                FROM markets m
                WHERE m.resolved = 1
                    AND m.winning_outcome IS NOT NULL
                    AND m.winning_outcome != ''
            """)
            resolved_count = cursor.fetchone()[0]

            if resolved_count == 0:
                logger.error("No resolved markets found")
                print("\n⚠️  No resolved markets available yet.")
                print("Risk analysis requires markets with known outcomes.\n")
                sys.exit(0)

            logger.info(f"Found {resolved_count} resolved markets")

            # Analyze specific trader
            if args.trader:
                logger.info(f"Analyzing trader: {args.trader}")
                metrics = analyzer.calculate_risk_metrics(args.trader, args.window)

                if metrics:
                    # Get rank if analyzing all
                    if args.all:
                        df = analyzer.compare_all_traders()
                        if not df.empty:
                            rank_row = df[df['trader_address'] == args.trader]
                            if not rank_row.empty:
                                rank = rank_row['rank'].values[0]
                                print_risk_report(metrics, rank, len(df))
                            else:
                                print_risk_report(metrics)
                    else:
                        print_risk_report(metrics)

                    # Generate visualizations
                    if args.visualize:
                        viz = RiskVisualizer()
                        trade_returns = analyzer.get_trader_returns(args.trader, args.window)
                        returns = [t.return_pct for t in trade_returns]

                        viz.plot_equity_curve_with_drawdown(
                            trade_returns,
                            args.trader
                        )
                        viz.plot_return_distribution(
                            returns,
                            metrics.var_95,
                            metrics.var_99,
                            args.trader
                        )
                else:
                    logger.warning(f"Insufficient data for trader {args.trader}")

            # Analyze all traders
            if args.all or args.report or args.top:
                logger.info("Analyzing all traders...")
                df = analyzer.compare_all_traders()

                if df.empty:
                    logger.error("No trader data found")
                    sys.exit(1)

                # Show top N
                if args.top:
                    print(f"\n{'='*80}")
                    print(f"TOP {args.top} TRADERS BY SHARPE RATIO")
                    print(f"{'='*80}\n")

                    top_traders = df.head(args.top)

                    for _, row in top_traders.iterrows():
                        print(f"#{row['rank']}. {row['trader_address'][:10]}...")
                        print(f"   Sharpe: {row['sharpe_ratio']:.2f} | "
                              f"Sortino: {row['sortino_ratio']:.2f} | "
                              f"Return: {row['avg_return_pct']:+.2f}%")
                        print(f"   Trades: {row['total_trades']} | "
                              f"Win Rate: {row['win_rate']:.1f}% | "
                              f"Max DD: {row['max_drawdown_pct']:.1f}%\n")

                # Generate visualizations
                if args.visualize:
                    logger.info("Generating visualizations...")
                    viz = RiskVisualizer()

                    viz.plot_risk_return_scatter(df)
                    viz.plot_top_traders(df, top_n=min(20, len(df)))

                    logger.info("Visualizations complete")

                # Summary
                if not args.top:
                    print(f"\n✅ Analyzed {len(df)} traders")
                    print(f"Average Sharpe Ratio: {df['sharpe_ratio'].mean():.2f}")
                    print(f"Top 5 Traders:")
                    for _, row in df.head(5).iterrows():
                        print(f"  #{row['rank']}. {row['trader_address'][:10]}... - "
                              f"Sharpe: {row['sharpe_ratio']:.2f}")

    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Analysis complete!")


if __name__ == "__main__":
    main()
