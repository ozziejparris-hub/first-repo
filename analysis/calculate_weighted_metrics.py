#!/usr/bin/env python3
"""
Calculate Weighted Metrics Script

Calculates market difficulty and weighted performance metrics:
- Market difficulty score (volatility, liquidity, age)
- Weighted win rate by market difficulty
- Confidence-adjusted metrics

Reads from polymarket_tracker.db without modifying it.
"""

import sqlite3
import csv
import os
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


class WeightedMetricsCalculator:
    """Calculates market difficulty and weighted trader metrics."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default to data directory in parent folder
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def calculate_market_difficulty(self, market_id: str) -> Optional[float]:
        """
        Calculate difficulty score for a market.

        Factors:
        1. Price volatility (higher = harder to predict)
        2. Liquidity/volume (lower = harder)
        3. Market age (newer = less info)
        4. Number of participants

        Returns:
            float: Difficulty score 0-1 (higher = more difficult)
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get market data
        cursor.execute("""
            SELECT
                m.created_at,
                m.end_date,
                m.volume_usd,
                COUNT(DISTINCT t.trader_address) as num_traders,
                COUNT(t.trade_id) as num_trades,
                AVG(t.price) as avg_price,
                MIN(t.price) as min_price,
                MAX(t.price) as max_price
            FROM markets m
            LEFT JOIN trades t ON m.market_id = t.market_id
            WHERE m.market_id = ?
            GROUP BY m.market_id
        """, (market_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Extract data
        volume = float(row['volume_usd'] or 0)
        num_traders = int(row['num_traders'] or 0)
        num_trades = int(row['num_trades'] or 0)
        avg_price = float(row['avg_price'] or 0.5)
        min_price = float(row['min_price'] or 0)
        max_price = float(row['max_price'] or 1)

        # Factor 1: Price volatility (0-1)
        # Higher volatility = harder to predict = higher difficulty
        price_range = max_price - min_price
        volatility_score = min(price_range / 0.5, 1.0)  # Normalize: 0.5 range = max

        # Factor 2: Liquidity (0-1, inverted)
        # Lower liquidity = harder = higher difficulty
        # Volume thresholds: $10k = easy, $1k = hard
        if volume >= 10000:
            liquidity_difficulty = 0.2
        elif volume >= 5000:
            liquidity_difficulty = 0.4
        elif volume >= 1000:
            liquidity_difficulty = 0.6
        elif volume >= 500:
            liquidity_difficulty = 0.8
        else:
            liquidity_difficulty = 1.0

        # Factor 3: Market maturity (0-1)
        # Fewer trades = less info = harder
        if num_trades >= 100:
            maturity_difficulty = 0.2
        elif num_trades >= 50:
            maturity_difficulty = 0.4
        elif num_trades >= 20:
            maturity_difficulty = 0.6
        elif num_trades >= 10:
            maturity_difficulty = 0.8
        else:
            maturity_difficulty = 1.0

        # Factor 4: Outcome clarity (based on price extremity)
        # Markets close to 0.5 are harder than those near 0 or 1
        distance_from_50 = abs(avg_price - 0.5)
        clarity_difficulty = 1.0 - (distance_from_50 * 2)  # 0.5 = max difficulty (1.0)

        # Weighted combination
        difficulty = (
            volatility_score * 0.3 +
            liquidity_difficulty * 0.25 +
            maturity_difficulty * 0.25 +
            clarity_difficulty * 0.2
        )

        return min(max(difficulty, 0.0), 1.0)

    def calculate_all_market_difficulties(self) -> Dict[str, float]:
        """
        Calculate difficulty scores for all markets in database.

        Returns:
            Dict mapping market_id to difficulty score
        """
        print("📊 Calculating market difficulty scores...")

        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get all markets with trades
        cursor.execute("""
            SELECT DISTINCT market_id
            FROM trades
            WHERE market_id IS NOT NULL
        """)

        market_ids = [row['market_id'] for row in cursor.fetchall()]
        conn.close()

        print(f"Found {len(market_ids)} unique markets")

        difficulties = {}
        for i, market_id in enumerate(market_ids, 1):
            if i % 100 == 0 or i == len(market_ids):
                print(f"Progress: {i}/{len(market_ids)} markets analyzed", end='\r')

            difficulty = self.calculate_market_difficulty(market_id)
            if difficulty is not None:
                difficulties[market_id] = difficulty

        print(f"\nProgress: {len(market_ids)}/{len(market_ids)} markets analyzed ✓")
        print(f"Average difficulty: {statistics.mean(difficulties.values()):.3f}\n")

        return difficulties

    def calculate_weighted_win_rate(self, trader_address: str,
                                   market_difficulties: Dict[str, float]) -> Dict:
        """
        Calculate difficulty-weighted win rate for a trader.

        Wins on difficult markets count more than wins on easy markets.
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get trader's resolved trades
        cursor.execute("""
            SELECT
                t.market_id,
                t.outcome,
                t.side,
                t.price,
                t.shares,
                m.winning_outcome,
                m.resolved
            FROM trades t
            JOIN markets m ON t.market_id = m.market_id
            WHERE t.trader_address = ?
            AND m.resolved = 1
            AND m.winning_outcome IS NOT NULL
        """, (trader_address,))

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not trades:
            return {
                'weighted_win_rate': None,
                'unweighted_win_rate': None,
                'resolved_trades_count': 0,
                'avg_market_difficulty': None
            }

        # Calculate weighted and unweighted wins
        total_weight = 0.0
        weighted_wins = 0.0
        unweighted_wins = 0
        difficulties_faced = []

        for trade in trades:
            market_id = trade['market_id']
            winning_outcome = trade['winning_outcome']
            trade_outcome = str(trade['outcome']).lower()
            trade_side = str(trade['side']).lower()
            winning_outcome_lower = str(winning_outcome).lower()

            # Determine if trader won
            trader_won = False
            if trade_side == 'buy':
                trader_won = (trade_outcome == winning_outcome_lower)
            elif trade_side == 'sell':
                trader_won = (trade_outcome != winning_outcome_lower)

            # Get market difficulty (default 0.5 if not calculated)
            difficulty = market_difficulties.get(market_id, 0.5)
            difficulties_faced.append(difficulty)

            # Weight: harder markets count more
            # Weight = 1 + difficulty (range: 1.0 to 2.0)
            weight = 1.0 + difficulty

            total_weight += weight

            if trader_won:
                weighted_wins += weight
                unweighted_wins += 1

        # Calculate rates
        weighted_win_rate = (weighted_wins / total_weight) if total_weight > 0 else 0.0
        unweighted_win_rate = (unweighted_wins / len(trades)) if trades else 0.0
        avg_difficulty = statistics.mean(difficulties_faced) if difficulties_faced else None

        return {
            'weighted_win_rate': weighted_win_rate * 100,  # As percentage
            'unweighted_win_rate': unweighted_win_rate * 100,
            'resolved_trades_count': len(trades),
            'avg_market_difficulty': avg_difficulty,
            'difficulty_bonus': (weighted_win_rate - unweighted_win_rate) * 100
        }

    def calculate_confidence_adjusted_metrics(self, trader_address: str) -> Dict:
        """
        Calculate confidence-adjusted performance metrics.

        Traders who bet with appropriate confidence (larger bets when confident,
        smaller when uncertain) get higher scores.
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get trader's resolved trades with outcomes
        cursor.execute("""
            SELECT
                t.price,
                t.shares,
                t.outcome,
                t.side,
                m.winning_outcome
            FROM trades t
            JOIN markets m ON t.market_id = m.market_id
            WHERE t.trader_address = ?
            AND m.resolved = 1
            AND m.winning_outcome IS NOT NULL
        """, (trader_address,))

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if not trades or len(trades) < 5:
            return {
                'confidence_alignment_score': None,
                'avg_bet_on_wins': None,
                'avg_bet_on_losses': None,
                'confidence_quality': 'Insufficient Data'
            }

        # Separate winning and losing trades
        winning_bets = []
        losing_bets = []

        for trade in trades:
            bet_size = float(trade['price']) * float(trade['shares'])

            trade_outcome = str(trade['outcome']).lower()
            trade_side = str(trade['side']).lower()
            winning_outcome = str(trade['winning_outcome']).lower()

            # Determine if won
            trader_won = False
            if trade_side == 'buy':
                trader_won = (trade_outcome == winning_outcome)
            elif trade_side == 'sell':
                trader_won = (trade_outcome != winning_outcome)

            if trader_won:
                winning_bets.append(bet_size)
            else:
                losing_bets.append(bet_size)

        if not winning_bets or not losing_bets:
            return {
                'confidence_alignment_score': None,
                'avg_bet_on_wins': statistics.mean(winning_bets) if winning_bets else None,
                'avg_bet_on_losses': statistics.mean(losing_bets) if losing_bets else None,
                'confidence_quality': 'Insufficient Data'
            }

        # Good confidence: bet MORE on wins than losses
        avg_win_bet = statistics.mean(winning_bets)
        avg_loss_bet = statistics.mean(losing_bets)

        # Confidence ratio: wins/losses (> 1.0 = good)
        confidence_ratio = avg_win_bet / avg_loss_bet if avg_loss_bet > 0 else 1.0

        # Normalize to 0-1 score
        # Ratio of 1.5+ = excellent (score 1.0)
        # Ratio of 1.0 = neutral (score 0.5)
        # Ratio of 0.67 = poor (score 0.0)
        if confidence_ratio >= 1.5:
            score = 1.0
        elif confidence_ratio >= 1.0:
            score = 0.5 + (confidence_ratio - 1.0)  # 1.0-1.5 maps to 0.5-1.0
        else:
            score = confidence_ratio * 0.5 / 1.0  # 0-1.0 maps to 0-0.5

        # Quality classification
        if score >= 0.8:
            quality = "Excellent"
        elif score >= 0.6:
            quality = "Good"
        elif score >= 0.4:
            quality = "Fair"
        else:
            quality = "Poor"

        return {
            'confidence_alignment_score': score,
            'avg_bet_on_wins': avg_win_bet,
            'avg_bet_on_losses': avg_loss_bet,
            'confidence_ratio': confidence_ratio,
            'confidence_quality': quality
        }

    def analyze_all_traders(self) -> Dict:
        """
        Calculate weighted metrics for all traders.

        Returns dict with trader_address as key and metrics as value.
        """
        print(f"\n{'='*70}")
        print(f"WEIGHTED METRICS ANALYSIS")
        print(f"{'='*70}\n")

        # Calculate market difficulties first
        market_difficulties = self.calculate_all_market_difficulties()

        # Get all traders
        conn = self.get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT trader_address
            FROM trades
            WHERE trader_address IS NOT NULL
        """)

        trader_addresses = [row['trader_address'] for row in cursor.fetchall()]
        conn.close()

        print(f"Analyzing {len(trader_addresses)} traders...\n")

        # Analyze each trader
        trader_metrics = {}

        for idx, trader_address in enumerate(trader_addresses, 1):
            if idx % 50 == 0 or idx == len(trader_addresses):
                print(f"Progress: {idx}/{len(trader_addresses)} traders analyzed", end='\r')

            # Calculate weighted metrics
            weighted_wr = self.calculate_weighted_win_rate(trader_address, market_difficulties)
            confidence_metrics = self.calculate_confidence_adjusted_metrics(trader_address)

            trader_metrics[trader_address] = {
                'trader_address': trader_address,
                **weighted_wr,
                **confidence_metrics
            }

        print(f"\nProgress: {len(trader_addresses)}/{len(trader_addresses)} traders analyzed ✓\n")

        return trader_metrics

    def save_to_csv(self, trader_metrics: Dict, filename: str = "weighted_metrics_report.csv"):
        """Save weighted metrics to CSV file."""

        # Filter traders with enough data
        qualified_traders = {
            addr: metrics for addr, metrics in trader_metrics.items()
            if metrics.get('resolved_trades_count', 0) >= 10
        }

        # Sort by weighted win rate
        sorted_traders = sorted(
            qualified_traders.values(),
            key=lambda x: x.get('weighted_win_rate', 0),
            reverse=True
        )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(['Analysis Timestamp', timestamp])
            writer.writerow([])
            writer.writerow([
                'Rank',
                'Trader Address',
                'Resolved Trades',
                'Weighted Win Rate (%)',
                'Unweighted Win Rate (%)',
                'Difficulty Bonus (%)',
                'Avg Market Difficulty',
                'Confidence Alignment Score',
                'Avg Bet on Wins ($)',
                'Avg Bet on Losses ($)',
                'Confidence Ratio',
                'Confidence Quality'
            ])

            # Write data
            for i, trader in enumerate(sorted_traders, 1):
                writer.writerow([
                    i,
                    trader['trader_address'],
                    trader.get('resolved_trades_count', 0),
                    f"{trader.get('weighted_win_rate', 0):.2f}",
                    f"{trader.get('unweighted_win_rate', 0):.2f}",
                    f"{trader.get('difficulty_bonus', 0):+.2f}",
                    f"{trader.get('avg_market_difficulty', 0):.3f}" if trader.get('avg_market_difficulty') else 'N/A',
                    f"{trader.get('confidence_alignment_score', 0):.3f}" if trader.get('confidence_alignment_score') is not None else 'N/A',
                    f"{trader.get('avg_bet_on_wins', 0):.2f}" if trader.get('avg_bet_on_wins') is not None else 'N/A',
                    f"{trader.get('avg_bet_on_losses', 0):.2f}" if trader.get('avg_bet_on_losses') is not None else 'N/A',
                    f"{trader.get('confidence_ratio', 1.0):.2f}" if trader.get('confidence_ratio') else 'N/A',
                    trader.get('confidence_quality', 'N/A')
                ])

        print(f"✅ Report saved to: {filename}")
        print(f"   Qualified traders (≥10 resolved): {len(sorted_traders)}")
        print(f"   Timestamp: {timestamp}\n")


def main():
    """Main entry point."""

    # Initialize calculator
    calculator = WeightedMetricsCalculator()

    # Check if database exists
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
    if not os.path.exists(db_path):
        print("❌ Error: polymarket_tracker.db not found in /data/")
        print("   Make sure the monitoring script has run and collected trades")
        return

    # Ensure reports directory exists
    reports_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    # Run analysis
    metrics = calculator.analyze_all_traders()

    # Save to CSV
    csv_path = os.path.join(reports_dir, f"weighted_metrics_{datetime.now().strftime('%Y%m%d')}.csv")
    calculator.save_to_csv(metrics, csv_path)


if __name__ == "__main__":
    main()
