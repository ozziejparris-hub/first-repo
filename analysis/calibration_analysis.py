#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Calibration Analysis Tool for Polymarket Traders

Measures how accurately traders' probability estimates match reality.
Perfect calibration means predicted probabilities exactly match actual win rates.

Key Metrics:
- Brier Score: Overall forecasting accuracy (0 = perfect, 2 = worst)
- Expected Calibration Error (ECE): Average deviation from perfect calibration
- Confidence Bias: Tendency to over/under-estimate probabilities
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
from scipy import stats

# Configure console encoding for Windows
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
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

# Constants
PROBABILITY_BINS = [(i/10, (i+1)/10) for i in range(10)]  # 0-10%, 10-20%, ..., 90-100%
MIN_PREDICTIONS_PER_BIN = 10  # Minimum for statistical validity
BRIER_EXCELLENT = 0.15
BRIER_GOOD = 0.25


@dataclass
class Prediction:
    """Represents a single probability prediction."""
    trader_address: str
    market_id: str
    market_title: str
    market_category: str
    predicted_probability: float
    actual_outcome: int  # 0 or 1
    timestamp: datetime


@dataclass
class CalibrationMetrics:
    """Comprehensive calibration metrics for a trader."""
    trader_address: str
    total_predictions: int
    resolved_markets: int
    brier_score: float
    expected_calibration_error: float  # ECE
    max_calibration_error: float  # MCE
    confidence_bias: float  # Over/under-confident %
    avg_predicted_prob: float
    actual_win_rate: float
    calibration_curve: List[Tuple[float, float, int]]  # (predicted, actual, count)
    category_scores: Dict[str, float]  # category -> Brier score


class CalibrationAnalyzer:
    """Main class for calculating and analyzing trader calibration."""

    def __init__(self, db_path: str = DB_PATH):
        """Initialize the calibration analyzer.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self.conn = None

    def __enter__(self):
        """Context manager entry."""
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.conn:
            self.conn.close()

    def get_trader_predictions(
        self,
        trader_address: str
    ) -> List[Prediction]:
        """Get all predictions by a trader in resolved markets.

        Args:
            trader_address: Trader's wallet address

        Returns:
            List of Prediction objects
        """
        cursor = self.conn.cursor()

        query = """
            SELECT
                t.trader_address,
                t.market_id,
                t.market_title,
                t.market_category,
                t.outcome,
                t.price,
                t.timestamp,
                m.winning_outcome
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE t.trader_address = ?
                AND m.resolved = 1
                AND m.winning_outcome IS NOT NULL
                AND m.winning_outcome != ''
            ORDER BY t.timestamp ASC
        """

        cursor.execute(query, (trader_address,))

        predictions = []
        for row in cursor.fetchall():
            # Extract implied probability from trade
            outcome = row['outcome']
            price = row['price']

            # For YES trades: predicted_prob = price
            # For NO trades: predicted_prob = 1 - price
            if outcome == 'Yes':
                predicted_prob = price
                actual_outcome = 1 if row['winning_outcome'] == 'Yes' else 0
            else:  # No
                predicted_prob = 1 - price
                actual_outcome = 1 if row['winning_outcome'] == 'No' else 0

            # Skip extreme probabilities that are likely data errors
            if not (0.01 <= predicted_prob <= 0.99):
                continue

            predictions.append(Prediction(
                trader_address=row['trader_address'],
                market_id=row['market_id'],
                market_title=row['market_title'],
                market_category=row['market_category'] or 'Unknown',
                predicted_probability=predicted_prob,
                actual_outcome=actual_outcome,
                timestamp=datetime.fromisoformat(row['timestamp'])
                    if row['timestamp'] else None
            ))

        return predictions

    def calculate_brier_score(
        self,
        predictions: List[Prediction]
    ) -> float:
        """Calculate Brier score for a set of predictions.

        Brier Score = (1/N) × Σ(predicted - actual)²
        Range: 0 (perfect) to 2 (worst possible)

        Args:
            predictions: List of Prediction objects

        Returns:
            Brier score (lower is better)
        """
        if not predictions:
            return float('inf')

        squared_errors = [
            (p.predicted_probability - p.actual_outcome) ** 2
            for p in predictions
        ]

        return np.mean(squared_errors)

    def calculate_calibration_curve(
        self,
        predictions: List[Prediction],
        n_bins: int = 10
    ) -> List[Tuple[float, float, int]]:
        """Calculate calibration curve by binning predictions.

        Args:
            predictions: List of Prediction objects
            n_bins: Number of probability bins

        Returns:
            List of (avg_predicted, actual_rate, count) tuples
        """
        if not predictions:
            return []

        # Create bins
        bins = [(i/n_bins, (i+1)/n_bins) for i in range(n_bins)]

        calibration_data = []

        for bin_start, bin_end in bins:
            # Get predictions in this bin
            bin_predictions = [
                p for p in predictions
                if bin_start <= p.predicted_probability < bin_end
            ]

            if not bin_predictions:
                continue

            # Calculate average predicted probability
            avg_predicted = np.mean([p.predicted_probability for p in bin_predictions])

            # Calculate actual win rate
            actual_rate = np.mean([p.actual_outcome for p in bin_predictions])

            calibration_data.append((avg_predicted, actual_rate, len(bin_predictions)))

        return calibration_data

    def calculate_expected_calibration_error(
        self,
        calibration_curve: List[Tuple[float, float, int]],
        total_predictions: int
    ) -> float:
        """Calculate Expected Calibration Error (ECE).

        ECE = Σ (|predicted - actual| × (count / total))

        Args:
            calibration_curve: Output from calculate_calibration_curve
            total_predictions: Total number of predictions

        Returns:
            Expected Calibration Error
        """
        if not calibration_curve or total_predictions == 0:
            return 0.0

        ece = 0.0
        for predicted, actual, count in calibration_curve:
            ece += abs(predicted - actual) * (count / total_predictions)

        return ece

    def calculate_max_calibration_error(
        self,
        calibration_curve: List[Tuple[float, float, int]]
    ) -> float:
        """Calculate Maximum Calibration Error (MCE).

        MCE = max(|predicted - actual|) across all bins

        Args:
            calibration_curve: Output from calculate_calibration_curve

        Returns:
            Maximum Calibration Error
        """
        if not calibration_curve:
            return 0.0

        errors = [abs(predicted - actual) for predicted, actual, _ in calibration_curve]
        return max(errors) if errors else 0.0

    def detect_confidence_bias(
        self,
        predictions: List[Prediction]
    ) -> Tuple[float, str]:
        """Detect if trader is over-confident or under-confident.

        Args:
            predictions: List of Prediction objects

        Returns:
            Tuple of (bias_percentage, description)
        """
        if not predictions:
            return 0.0, "Insufficient data"

        avg_predicted = np.mean([p.predicted_probability for p in predictions])
        actual_win_rate = np.mean([p.actual_outcome for p in predictions])

        bias = (avg_predicted - actual_win_rate) * 100

        if abs(bias) < 2:
            description = "Well-Calibrated"
        elif bias > 5:
            description = "Over-Confident"
        elif bias > 2:
            description = "Slightly Over-Confident"
        elif bias < -5:
            description = "Under-Confident"
        else:
            description = "Slightly Under-Confident"

        return bias, description

    def analyze_calibration_by_category(
        self,
        predictions: List[Prediction]
    ) -> Dict[str, Dict[str, float]]:
        """Break down calibration by market category.

        Args:
            predictions: List of Prediction objects

        Returns:
            Dict mapping category to metrics dict
        """
        category_predictions = defaultdict(list)

        for pred in predictions:
            category_predictions[pred.market_category].append(pred)

        category_metrics = {}

        for category, cat_predictions in category_predictions.items():
            if len(cat_predictions) < 5:  # Skip categories with too few predictions
                continue

            brier = self.calculate_brier_score(cat_predictions)
            avg_predicted = np.mean([p.predicted_probability for p in cat_predictions])
            actual_rate = np.mean([p.actual_outcome for p in cat_predictions])

            category_metrics[category] = {
                'brier_score': brier,
                'count': len(cat_predictions),
                'avg_predicted': avg_predicted,
                'actual_rate': actual_rate,
                'bias': (avg_predicted - actual_rate) * 100
            }

        return category_metrics

    def calculate_trader_calibration(
        self,
        trader_address: str
    ) -> Optional[CalibrationMetrics]:
        """Calculate comprehensive calibration metrics for a trader.

        Args:
            trader_address: Trader's wallet address

        Returns:
            CalibrationMetrics object or None if insufficient data
        """
        predictions = self.get_trader_predictions(trader_address)

        if len(predictions) < 10:
            logger.warning(
                f"Trader {trader_address[:10]}... has insufficient predictions "
                f"({len(predictions)}) for calibration analysis"
            )
            return None

        # Count unique markets
        unique_markets = len(set(p.market_id for p in predictions))

        # Calculate Brier score
        brier_score = self.calculate_brier_score(predictions)

        # Calculate calibration curve
        calibration_curve = self.calculate_calibration_curve(predictions)

        # Calculate ECE and MCE
        ece = self.calculate_expected_calibration_error(
            calibration_curve,
            len(predictions)
        )
        mce = self.calculate_max_calibration_error(calibration_curve)

        # Detect confidence bias
        confidence_bias, _ = self.detect_confidence_bias(predictions)

        # Calculate averages
        avg_predicted = np.mean([p.predicted_probability for p in predictions])
        actual_win_rate = np.mean([p.actual_outcome for p in predictions])

        # Analyze by category
        category_metrics = self.analyze_calibration_by_category(predictions)
        category_scores = {
            cat: metrics['brier_score']
            for cat, metrics in category_metrics.items()
        }

        return CalibrationMetrics(
            trader_address=trader_address,
            total_predictions=len(predictions),
            resolved_markets=unique_markets,
            brier_score=brier_score,
            expected_calibration_error=ece,
            max_calibration_error=mce,
            confidence_bias=confidence_bias,
            avg_predicted_prob=avg_predicted,
            actual_win_rate=actual_win_rate,
            calibration_curve=calibration_curve,
            category_scores=category_scores
        )

    def compare_traders_calibration(self) -> pd.DataFrame:
        """Analyze calibration for all traders.

        Returns:
            DataFrame with calibration metrics for all traders
        """
        cursor = self.conn.cursor()

        # Get all unique traders who have trades in resolved markets
        cursor.execute("""
            SELECT DISTINCT t.trader_address
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 1
                AND m.winning_outcome IS NOT NULL
                AND m.winning_outcome != ''
        """)

        all_traders = [row[0] for row in cursor.fetchall()]

        logger.info(f"Analyzing calibration for {len(all_traders)} traders...")

        results = []
        for i, trader in enumerate(all_traders, 1):
            if i % 50 == 0:
                logger.info(f"Progress: {i}/{len(all_traders)} traders analyzed")

            metrics = self.calculate_trader_calibration(trader)

            if metrics:
                results.append({
                    'trader_address': metrics.trader_address,
                    'total_predictions': metrics.total_predictions,
                    'resolved_markets': metrics.resolved_markets,
                    'brier_score': metrics.brier_score,
                    'ece': metrics.expected_calibration_error,
                    'mce': metrics.max_calibration_error,
                    'confidence_bias': metrics.confidence_bias,
                    'avg_predicted': metrics.avg_predicted_prob,
                    'actual_win_rate': metrics.actual_win_rate
                })

        if not results:
            logger.warning("No traders found with sufficient predictions")
            return pd.DataFrame()

        df = pd.DataFrame(results)

        # Sort by Brier score (lower is better)
        df = df.sort_values('brier_score', ascending=True)
        df['rank'] = range(1, len(df) + 1)

        logger.info(f"Successfully analyzed {len(df)} traders")

        return df

    def analyze_all_traders(self) -> Dict[str, Dict]:
        """
        Analyze calibration for all traders.

        Returns dict mapping trader addresses to their calibration metrics.
        Used by unified ELO system for Advanced Metrics dimension.

        Returns:
            Dict[str, Dict]: Maps trader_address -> {
                'brier_score': float,
                'expected_calibration_error': float,
                'num_predictions': int,
                'confidence_bias': float
            }
        """
        # Ensure connection is established
        if self.conn is None:
            self.conn = sqlite3.connect(self.db_path, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")

        cursor = self.conn.cursor()

        # Get all traders with resolved trades
        cursor.execute("""
            SELECT DISTINCT t.trader_address
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 1
                AND m.winning_outcome IS NOT NULL
                AND m.winning_outcome != ''
        """)

        all_traders = [row[0] for row in cursor.fetchall()]

        results = {}
        for trader in all_traders:
            metrics = self.calculate_trader_calibration(trader)
            if metrics:
                results[trader] = {
                    'brier_score': metrics.brier_score,
                    'expected_calibration_error': metrics.expected_calibration_error,
                    'num_predictions': metrics.total_predictions,
                    'confidence_bias': metrics.confidence_bias,
                    'avg_predicted_prob': metrics.avg_predicted_prob,
                    'avg_actual_prob': metrics.actual_win_rate
                }

        logger.info(f"Analyzed calibration for {len(results)} traders")
        return results


class CalibrationVisualizer:
    """Handles visualization of calibration analysis results."""

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

    def plot_calibration_curve(
        self,
        metrics: CalibrationMetrics,
        save: bool = True
    ):
        """Plot calibration curve (reliability diagram).

        Args:
            metrics: CalibrationMetrics object
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(10, 10))

        # Extract data
        calibration_data = metrics.calibration_curve

        if not calibration_data:
            logger.warning("No calibration data to plot")
            return

        predicted = [d[0] for d in calibration_data]
        actual = [d[1] for d in calibration_data]
        counts = [d[2] for d in calibration_data]

        # Plot perfect calibration line
        ax.plot([0, 1], [0, 1], 'k--', linewidth=2, label='Perfect Calibration', alpha=0.7)

        # Plot trader's calibration
        scatter = ax.scatter(
            predicted,
            actual,
            s=[c * 10 for c in counts],  # Size by count
            c=counts,
            cmap='viridis',
            alpha=0.6,
            edgecolors='black',
            linewidth=1.5
        )

        # Connect points with line
        if len(predicted) > 1:
            ax.plot(predicted, actual, 'b-', linewidth=2, alpha=0.5, label='Trader Calibration')

        # Add confidence intervals (simplified)
        for p, a, c in zip(predicted, actual, counts):
            if c >= MIN_PREDICTIONS_PER_BIN:
                # Binomial confidence interval
                se = np.sqrt(a * (1 - a) / c)
                ci = 1.96 * se  # 95% CI
                ax.errorbar(p, a, yerr=ci, fmt='none', color='blue', alpha=0.3, capsize=5)

        ax.set_xlabel('Predicted Probability', fontsize=14, fontweight='bold')
        ax.set_ylabel('Actual Win Rate', fontsize=14, fontweight='bold')
        ax.set_title(
            f'Calibration Curve\n'
            f'Trader: {metrics.trader_address[:10]}...\n'
            f'Brier Score: {metrics.brier_score:.3f} | ECE: {metrics.expected_calibration_error:.3f}',
            fontsize=14,
            fontweight='bold'
        )

        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='upper left', fontsize=12)

        # Add colorbar for count
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('Number of Predictions', fontsize=12)

        # Add text annotations for bins with few predictions
        for p, a, c in zip(predicted, actual, counts):
            if c < MIN_PREDICTIONS_PER_BIN:
                ax.annotate(
                    f'n={c}',
                    (p, a),
                    xytext=(5, 5),
                    textcoords='offset points',
                    fontsize=8,
                    alpha=0.7
                )

        plt.tight_layout()

        if save:
            filepath = os.path.join(
                self.output_dir,
                f'calibration_curve_{metrics.trader_address[:10]}.png'
            )
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_brier_distribution(self, df: pd.DataFrame, save: bool = True):
        """Plot distribution of Brier scores.

        Args:
            df: DataFrame with calibration metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 6))

        # Create histogram with color coding
        colors = []
        for score in df['brier_score']:
            if score < BRIER_EXCELLENT:
                colors.append('green')
            elif score < BRIER_GOOD:
                colors.append('yellow')
            else:
                colors.append('red')

        ax.hist(df['brier_score'], bins=30, edgecolor='black', alpha=0.7)

        # Add threshold lines
        ax.axvline(BRIER_EXCELLENT, color='green', linestyle='--',
                   linewidth=2, label=f'Excellent (<{BRIER_EXCELLENT})')
        ax.axvline(BRIER_GOOD, color='orange', linestyle='--',
                   linewidth=2, label=f'Good (<{BRIER_GOOD})')

        ax.set_xlabel('Brier Score', fontsize=12, fontweight='bold')
        ax.set_ylabel('Number of Traders', fontsize=12, fontweight='bold')
        ax.set_title('Distribution of Brier Scores Across All Traders',
                     fontsize=14, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'brier_distribution.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_confidence_bias_scatter(
        self,
        df: pd.DataFrame,
        save: bool = True
    ):
        """Plot confidence bias scatter.

        Args:
            df: DataFrame with calibration metrics
            save: Whether to save the plot
        """
        fig, ax = plt.subplots(figsize=(12, 8))

        scatter = ax.scatter(
            df['avg_predicted'],
            df['actual_win_rate'],
            c=df['confidence_bias'],
            cmap='RdYlGn_r',
            s=df['total_predictions'] * 2,
            alpha=0.6,
            edgecolors='black'
        )

        # Add perfect calibration line
        ax.plot([0, 1], [0, 1], 'k--', linewidth=2, label='Perfect Calibration')

        ax.set_xlabel('Average Predicted Probability', fontsize=12, fontweight='bold')
        ax.set_ylabel('Actual Win Rate', fontsize=12, fontweight='bold')
        ax.set_title('Confidence Bias Analysis\n'
                     'Point Size = Number of Predictions',
                     fontsize=14, fontweight='bold')

        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('Confidence Bias (%)', fontsize=12)

        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'confidence_bias_scatter.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()

    def plot_top_traders(self, df: pd.DataFrame, top_n: int = 20, save: bool = True):
        """Plot top traders by calibration quality.

        Args:
            df: DataFrame with calibration metrics
            top_n: Number of top traders to show
            save: Whether to save the plot
        """
        top_traders = df.nsmallest(top_n, 'brier_score')

        fig, ax = plt.subplots(figsize=(14, 10))

        # Create labels with truncated addresses
        labels = [f"{addr[:6]}...{addr[-4:]}" for addr in top_traders['trader_address']]

        # Color code by performance
        colors = []
        for score in top_traders['brier_score']:
            if score < BRIER_EXCELLENT:
                colors.append('green')
            elif score < BRIER_GOOD:
                colors.append('yellow')
            else:
                colors.append('orange')

        bars = ax.barh(labels, top_traders['brier_score'], color=colors,
                       edgecolor='black')

        ax.set_xlabel('Brier Score (Lower is Better)', fontsize=12, fontweight='bold')
        ax.set_ylabel('Trader Address', fontsize=12, fontweight='bold')
        ax.set_title(f'Top {top_n} Best Calibrated Traders',
                     fontsize=14, fontweight='bold')
        ax.invert_yaxis()

        # Add value labels
        for i, (bar, val) in enumerate(zip(bars, top_traders['brier_score'])):
            ax.text(val + 0.005, bar.get_y() + bar.get_height()/2,
                   f'{val:.3f}', va='center', fontsize=9)

        # Add threshold line
        ax.axvline(BRIER_GOOD, color='red', linestyle='--',
                   linewidth=2, alpha=0.5, label=f'Good threshold ({BRIER_GOOD})')

        ax.legend()

        plt.tight_layout()

        if save:
            filepath = os.path.join(self.output_dir, 'top_calibrated_traders.png')
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            logger.info(f"Saved plot to {filepath}")

        plt.show()


def print_calibration_report(
    metrics: CalibrationMetrics,
    rank: Optional[int] = None,
    total_traders: Optional[int] = None
):
    """Print a formatted calibration report for a single trader.

    Args:
        metrics: CalibrationMetrics object
        rank: Trader's rank (optional)
        total_traders: Total number of traders analyzed (optional)
    """
    print("\n" + "="*80)
    print(f"CALIBRATION ANALYSIS FOR TRADER: {metrics.trader_address}")
    print("="*80)

    print(f"\n📊 PREDICTION SUMMARY:")
    print(f"  Resolved Markets Participated: {metrics.resolved_markets}")
    print(f"  Total Predictions Analyzed: {metrics.total_predictions}")

    print(f"\n🎯 BRIER SCORE: {metrics.brier_score:.3f}", end="")
    if metrics.brier_score < BRIER_EXCELLENT:
        print(" (Excellent - Top tier forecaster!)")
    elif metrics.brier_score < BRIER_GOOD:
        print(f" (Good - Below {BRIER_GOOD} threshold)")
    else:
        print(f" (Fair - Above {BRIER_GOOD} threshold)")

    if rank and total_traders:
        print(f"  Rank: #{rank} out of {total_traders} traders (lower is better)")

    print(f"\n📈 CALIBRATION QUALITY:")
    print(f"  Expected Calibration Error (ECE): {metrics.expected_calibration_error:.3f}")
    print(f"  Maximum Calibration Error (MCE): {metrics.max_calibration_error:.3f}")

    bias, bias_desc = metrics.confidence_bias, ""
    if abs(bias) < 2:
        bias_desc = "Well-Calibrated ✓"
    elif bias > 5:
        bias_desc = "Over-Confident ⚠"
    elif bias > 2:
        bias_desc = "Slightly Over-Confident"
    elif bias < -5:
        bias_desc = "Under-Confident ⚠"
    else:
        bias_desc = "Slightly Under-Confident"

    print(f"\n🧠 CONFIDENCE BIAS: {bias_desc}")
    print(f"  Predicted probability: {metrics.avg_predicted_prob*100:.1f}% (average)")
    print(f"  Actual win rate: {metrics.actual_win_rate*100:.1f}%")
    print(f"  Confidence bias: {bias:+.1f}%", end="")
    if bias > 0:
        print(" (predicting too high)")
    elif bias < 0:
        print(" (predicting too low)")
    else:
        print(" (perfectly calibrated)")

    print(f"\n📊 CALIBRATION BY PROBABILITY BUCKET:")
    print(f"{'Bucket':<12} {'Predicted':<12} {'Actual':<12} {'Count':<8} {'Error':<10} {'Status'}")
    print("-" * 70)

    for predicted, actual, count in metrics.calibration_curve:
        error = abs(predicted - actual)
        bucket_start = int(predicted * 10) * 10
        bucket_end = bucket_start + 10

        status = "✓ Good" if error < 0.05 else "⚠ Check" if error < 0.10 else "✗ Poor"

        print(f"{bucket_start:>2}-{bucket_end:>2}%     "
              f"{predicted*100:>6.1f}%      "
              f"{actual*100:>6.1f}%      "
              f"{count:>4}     "
              f"{error*100:>5.1f}%     {status}")

    print(f"\n💡 INTERPRETATION:")
    if metrics.brier_score < BRIER_EXCELLENT:
        print("  This trader is an excellent forecaster with outstanding calibration.")
    elif metrics.brier_score < BRIER_GOOD:
        print("  This trader shows good calibration with reliable probability estimates.")
    else:
        print("  This trader's calibration could be improved. Consider analyzing patterns.")

    if abs(bias) > 5:
        if bias > 0:
            print("  Tendency to over-estimate probabilities. Consider being more cautious.")
        else:
            print("  Tendency to under-estimate probabilities. May be too conservative.")

    if metrics.category_scores:
        print(f"\n🏆 CALIBRATION BY CATEGORY:")
        sorted_cats = sorted(
            metrics.category_scores.items(),
            key=lambda x: x[1]
        )

        for category, score in sorted_cats[:5]:  # Top 5 categories
            status = "✓" if score < BRIER_GOOD else "⚠"
            quality = "Excellent" if score < BRIER_EXCELLENT else "Good" if score < BRIER_GOOD else "Fair"
            print(f"  {category:<20} Brier = {score:.3f} ({quality}) {status}")

        if len(sorted_cats) > 0:
            best_cat = sorted_cats[0][0]
            print(f"\n  💡 RECOMMENDATION: Focus on {best_cat} markets where calibration is strongest.")

    print("\n" + "="*80 + "\n")


def generate_comparison_report(df: pd.DataFrame, output_file: str = None):
    """Generate comprehensive comparison report.

    Args:
        df: DataFrame with calibration metrics
        output_file: Optional path to save report
    """
    report = []
    report.append("="*80)
    report.append("COMPREHENSIVE CALIBRATION ANALYSIS REPORT")
    report.append("="*80)
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Total Traders Analyzed: {len(df)}")

    report.append("\n" + "-"*80)
    report.append("AGGREGATE STATISTICS")
    report.append("-"*80)

    report.append(f"\nAverage Brier Score: {df['brier_score'].mean():.3f}")
    report.append(f"Median Brier Score: {df['brier_score'].median():.3f}")
    report.append(f"Best Brier Score: {df['brier_score'].min():.3f}")
    report.append(f"Worst Brier Score: {df['brier_score'].max():.3f}")

    excellent = len(df[df['brier_score'] < BRIER_EXCELLENT])
    good = len(df[df['brier_score'] < BRIER_GOOD]) - excellent
    fair = len(df) - excellent - good

    report.append(f"\nCalibration Quality Distribution:")
    report.append(f"  Excellent (<{BRIER_EXCELLENT}): {excellent} traders ({excellent/len(df)*100:.1f}%)")
    report.append(f"  Good (<{BRIER_GOOD}): {good} traders ({good/len(df)*100:.1f}%)")
    report.append(f"  Fair: {fair} traders ({fair/len(df)*100:.1f}%)")

    over_confident = len(df[df['confidence_bias'] > 5])
    under_confident = len(df[df['confidence_bias'] < -5])
    well_calibrated = len(df) - over_confident - under_confident

    report.append(f"\nConfidence Bias Distribution:")
    report.append(f"  Over-Confident: {over_confident} traders")
    report.append(f"  Under-Confident: {under_confident} traders")
    report.append(f"  Well-Calibrated: {well_calibrated} traders")

    report.append("\n" + "-"*80)
    report.append("TOP 10 BEST CALIBRATED TRADERS")
    report.append("-"*80)

    top_10 = df.nsmallest(10, 'brier_score')
    for i, row in top_10.iterrows():
        report.append(f"\n#{row['rank']}. {row['trader_address']}")
        report.append(f"   Brier Score: {row['brier_score']:.3f}")
        report.append(f"   ECE: {row['ece']:.3f} | Bias: {row['confidence_bias']:+.1f}%")
        report.append(f"   Predictions: {row['total_predictions']} | Markets: {row['resolved_markets']}")

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
        description="Calibration Analysis Tool for Polymarket Traders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a specific trader
  python calibration_analysis.py --trader 0x1234567890abcdef...

  # Analyze all traders
  python calibration_analysis.py --all

  # Generate comprehensive report
  python calibration_analysis.py --report

  # Show top 20 calibrated traders
  python calibration_analysis.py --top 20

  # Full analysis with visualizations
  python calibration_analysis.py --all --visualize
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
        help='Show top N calibrated traders'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='analysis/output/calibration_report.txt',
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

    # Check if database exists
    if not os.path.exists(args.db):
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    try:
        with CalibrationAnalyzer(args.db) as analyzer:

            # Check if there are resolved markets
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
                logger.error(
                    "No resolved markets found in database. "
                    "Calibration analysis requires markets with known outcomes."
                )
                print("\n⚠️  No resolved markets available yet.")
                print("Calibration analysis will be possible once markets start resolving.")
                print("Check back after the monitoring system has tracked some market resolutions.\n")
                sys.exit(0)

            logger.info(f"Found {resolved_count} resolved markets")

            # Analyze specific trader
            if args.trader:
                logger.info(f"Analyzing trader: {args.trader}")
                metrics = analyzer.calculate_trader_calibration(args.trader)

                if metrics:
                    # Get rank if analyzing all
                    if args.all:
                        df = analyzer.compare_traders_calibration()
                        if not df.empty:
                            rank_row = df[df['trader_address'] == args.trader]
                            if not rank_row.empty:
                                rank = rank_row['rank'].values[0]
                                print_calibration_report(metrics, rank, len(df))
                            else:
                                print_calibration_report(metrics)
                    else:
                        print_calibration_report(metrics)

                    # Generate visualizations
                    if args.visualize:
                        viz = CalibrationVisualizer()
                        viz.plot_calibration_curve(metrics)
                else:
                    logger.warning(
                        f"No data found for trader {args.trader} in resolved markets"
                    )

            # Analyze all traders
            if args.all or args.report or args.top:
                logger.info("Analyzing all traders...")
                df = analyzer.compare_traders_calibration()

                if df.empty:
                    logger.error("No trader data found")
                    sys.exit(1)

                # Generate report
                if args.report:
                    generate_comparison_report(df, args.output)

                # Show top N traders
                if args.top:
                    top_n = args.top
                    print(f"\n{'='*80}")
                    print(f"TOP {top_n} BEST CALIBRATED TRADERS")
                    print(f"{'='*80}\n")

                    top_traders = df.nsmallest(top_n, 'brier_score')

                    for _, row in top_traders.iterrows():
                        print(f"#{row['rank']}. {row['trader_address'][:10]}...")
                        print(f"   Brier: {row['brier_score']:.3f} | "
                              f"ECE: {row['ece']:.3f} | "
                              f"Bias: {row['confidence_bias']:+.1f}%")
                        print(f"   Predictions: {row['total_predictions']} | "
                              f"Markets: {row['resolved_markets']}\n")

                # Generate visualizations
                if args.visualize and not df.empty:
                    logger.info("Generating visualizations...")
                    viz = CalibrationVisualizer()

                    viz.plot_brier_distribution(df)
                    viz.plot_confidence_bias_scatter(df)
                    viz.plot_top_traders(df, top_n=min(20, len(df)))

                    logger.info("All visualizations generated successfully")

                # Print summary if not already printed
                if not args.report and not args.top:
                    print(f"\n✅ Analyzed {len(df)} traders")
                    print(f"Average Brier Score: {df['brier_score'].mean():.3f}")
                    print(f"Median Brier Score: {df['brier_score'].median():.3f}")
                    print(f"\nTop 5 Best Calibrated:")
                    for _, row in df.head(5).iterrows():
                        print(f"  #{row['rank']}. {row['trader_address'][:10]}... - "
                              f"Brier: {row['brier_score']:.3f}")

    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Analysis complete!")


if __name__ == "__main__":
    main()
