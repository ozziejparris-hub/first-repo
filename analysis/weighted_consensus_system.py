#!/usr/bin/env python3
"""
Weighted Consensus System for Polymarket Predictions

Combines:
1. ELO Rating System - Rates trader skill based on historical performance
2. Weighted Majority Algorithm - Aggregates predictions using ELO weights
3. Performance Tracking - Evaluates consensus accuracy over time

Generates market predictions with confidence scores and signal strength.
"""

import sqlite3
import requests
import csv
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
import time


class ELORatingSystem:
    """Implements ELO rating system for trader skill assessment."""

    def __init__(self, starting_elo: int = 1500, k_factor: int = 32):
        self.starting_elo = starting_elo
        self.k_factor = k_factor
        self.trader_elos = defaultdict(lambda: starting_elo)
        self.elo_history = defaultdict(list)  # Track ELO changes over time

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score for player A vs player B."""
        return 1 / (1 + math.pow(10, (rating_b - rating_a) / 400))

    def update_rating(self, trader_address: str, actual_score: float,
                     opponent_rating: float, bet_size: float = 1.0,
                     market_difficulty: float = 1.0, timestamp: datetime = None):
        """
        Update trader ELO rating based on outcome.

        Args:
            trader_address: Trader's address
            actual_score: 1.0 for win, 0.0 for loss
            opponent_rating: Average ELO of opposing traders
            bet_size: Relative bet size (larger = more confidence = bigger swings)
            market_difficulty: Market difficulty factor (low liquidity = harder)
            timestamp: When the update occurred
        """
        current_elo = self.trader_elos[trader_address]
        expected = self.expected_score(current_elo, opponent_rating)

        # Adjust K-factor based on bet size and market difficulty
        adjusted_k = self.k_factor * bet_size * market_difficulty

        # Calculate new rating
        new_elo = current_elo + adjusted_k * (actual_score - expected)

        # Update
        self.trader_elos[trader_address] = new_elo

        # Track history
        if timestamp:
            self.elo_history[trader_address].append({
                'timestamp': timestamp,
                'old_elo': current_elo,
                'new_elo': new_elo,
                'change': new_elo - current_elo,
                'actual_score': actual_score,
                'expected_score': expected
            })

        return new_elo

    def get_elo(self, trader_address: str) -> float:
        """Get current ELO rating for a trader."""
        return self.trader_elos[trader_address]

    def get_elo_change(self, trader_address: str, days: int = 7) -> float:
        """Get ELO change over last N days."""
        if trader_address not in self.elo_history:
            return 0.0

        cutoff = datetime.now() - timedelta(days=days)
        history = self.elo_history[trader_address]

        # Find earliest rating after cutoff
        recent_history = [h for h in history if h['timestamp'] >= cutoff]

        if not recent_history:
            return 0.0

        start_elo = recent_history[0]['old_elo']
        end_elo = recent_history[-1]['new_elo']

        return end_elo - start_elo

    def apply_time_decay(self, trader_address: str, days_since_last_trade: int) -> float:
        """Apply time decay to ELO (recent performance matters more)."""
        base_elo = self.get_elo(trader_address)
        decay_factor = math.pow(0.95, days_since_last_trade / 30)
        return base_elo * decay_factor


class WeightedConsensusSystem:
    """Weighted majority algorithm using ELO ratings as weights."""

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.api_key = api_key
        self.elo_system = ELORatingSystem()
        self.base_url = "https://gamma-api.polymarket.com"
        self.session = requests.Session()

        # Set up headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PolymarketTracker/1.0"
        }

        if api_key:
            headers.update({
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "APIKEY": api_key
            })

        self.session.headers.update(headers)

        # Cache for market resolutions
        self.market_resolutions = {}

        # Algorithm performance tracking
        self.consensus_predictions = []  # Historical predictions
        self.consensus_accuracy = []  # Win/loss record

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_trades(self) -> List[Dict]:
        """Get all trades from database."""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY timestamp ASC")
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return trades

    def get_market_resolution(self, market_id: str) -> Optional[Dict]:
        """Get market resolution status from Polymarket API."""
        if market_id in self.market_resolutions:
            return self.market_resolutions[market_id]

        try:
            url = f"{self.base_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                result = {"resolved": False}
                self.market_resolutions[market_id] = result
                return result

            data = response.json()
            closed = data.get('closed', False)
            archived = data.get('archived', False)

            if not (closed or archived):
                result = {"resolved": False, "active": True}
                self.market_resolutions[market_id] = result
                return result

            # Market is closed - determine winner
            outcomes = data.get('outcomes', [])
            winning_outcome = None

            for outcome in outcomes:
                if outcome.get('payoutNumerator') == 1000:
                    winning_outcome = outcome.get('name', '').lower()
                    break

            result = {
                "resolved": True,
                "active": False,
                "winning_outcome": winning_outcome,
                "resolution_date": data.get('endDate') or data.get('resolvedAt')
            }

            self.market_resolutions[market_id] = result
            return result

        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            result = {"resolved": False, "active": True}
            self.market_resolutions[market_id] = result
            return result

    def calculate_elo_ratings(self, verbose: bool = False):
        """Calculate ELO ratings for all traders based on historical trades."""
        print("\n📊 Calculating ELO ratings from historical trades...")

        trades = self.get_all_trades()
        print(f"Found {len(trades)} total trades")

        # Group trades by market
        market_trades = defaultdict(list)
        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        print(f"Checking resolution status for {len(market_trades)} markets...")

        # Get resolutions for all markets
        resolved_markets = 0
        for i, market_id in enumerate(market_trades.keys(), 1):
            if i % 10 == 0:
                print(f"Progress: {i}/{len(market_trades)} markets checked", end='\r')
            resolution = self.get_market_resolution(market_id)
            if resolution.get('resolved'):
                resolved_markets += 1
            time.sleep(0.1)  # Rate limiting

        print(f"\nFound {resolved_markets} resolved markets")

        # Process each resolved market to update ELO
        print("\nUpdating ELO ratings...")
        updates_count = 0

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)
            if not resolution or not resolution.get('resolved'):
                continue

            winning_outcome = resolution.get('winning_outcome')
            if not winning_outcome:
                continue

            # Separate winners and losers
            winners = []
            losers = []

            for trade in trades_list:
                trader = trade.get('trader_address')
                outcome = str(trade.get('outcome', '')).lower()
                shares = float(trade.get('shares', 0))
                price = float(trade.get('price', 0))
                timestamp_raw = trade.get('timestamp')

                # Parse timestamp
                try:
                    if isinstance(timestamp_raw, str):
                        timestamp = datetime.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
                    elif isinstance(timestamp_raw, (int, float)):
                        timestamp = datetime.fromtimestamp(timestamp_raw)
                    else:
                        timestamp = datetime.now()
                except:
                    timestamp = datetime.now()

                bet_size = shares * price

                if outcome == winning_outcome:
                    winners.append({'trader': trader, 'bet_size': bet_size, 'timestamp': timestamp})
                else:
                    losers.append({'trader': trader, 'bet_size': bet_size, 'timestamp': timestamp})

            # Calculate average ELO of winners and losers
            if winners and losers:
                avg_winner_elo = sum(self.elo_system.get_elo(w['trader']) for w in winners) / len(winners)
                avg_loser_elo = sum(self.elo_system.get_elo(l['trader']) for l in losers) / len(losers)

                # Update ELO for winners (beat losers)
                for winner in winners:
                    normalized_bet_size = min(winner['bet_size'] / 100, 2.0)  # Cap at 2x
                    market_difficulty = 1.0  # Could calculate based on liquidity

                    new_elo = self.elo_system.update_rating(
                        winner['trader'],
                        actual_score=1.0,
                        opponent_rating=avg_loser_elo,
                        bet_size=normalized_bet_size,
                        market_difficulty=market_difficulty,
                        timestamp=winner['timestamp']
                    )

                    if verbose:
                        change = new_elo - self.elo_system.starting_elo
                        print(f"  {winner['trader'][:12]}... ELO: {new_elo:.0f} (+{change:.0f})")

                    updates_count += 1

                # Update ELO for losers (lost to winners)
                for loser in losers:
                    normalized_bet_size = min(loser['bet_size'] / 100, 2.0)
                    market_difficulty = 1.0

                    new_elo = self.elo_system.update_rating(
                        loser['trader'],
                        actual_score=0.0,
                        opponent_rating=avg_winner_elo,
                        bet_size=normalized_bet_size,
                        market_difficulty=market_difficulty,
                        timestamp=loser['timestamp']
                    )

                    if verbose:
                        change = new_elo - self.elo_system.starting_elo
                        print(f"  {loser['trader'][:12]}... ELO: {new_elo:.0f} ({change:.0f})")

                    updates_count += 1

        print(f"✅ Updated {updates_count} trader ratings across {resolved_markets} resolved markets\n")

    def calculate_weighted_consensus(self) -> List[Dict]:
        """
        Calculate weighted consensus for all active markets.

        Returns list of predictions with confidence scores.
        """
        print("🎯 Calculating weighted consensus for active markets...")

        trades = self.get_all_trades()

        # Group trades by market
        market_trades = defaultdict(list)
        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        # Filter to active markets only
        active_market_predictions = []

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)

            # Skip resolved markets
            if resolution and resolution.get('resolved'):
                continue

            # This is an active market - calculate consensus
            outcome_weights = defaultdict(float)
            trader_positions = defaultdict(str)
            top_traders = []

            for trade in trades_list:
                trader = trade.get('trader_address')
                outcome = trade.get('outcome', 'Unknown')
                market_title = trade.get('market_title', 'Unknown Market')

                # Get trader's ELO rating
                elo = self.elo_system.get_elo(trader)

                # Weight this outcome by trader's ELO
                outcome_weights[outcome] += elo
                trader_positions[trader] = outcome

                # Track top traders
                top_traders.append((trader, elo, outcome))

            if not outcome_weights:
                continue

            # Sort outcomes by weight
            sorted_outcomes = sorted(outcome_weights.items(), key=lambda x: x[1], reverse=True)

            if len(sorted_outcomes) < 1:
                continue

            top_outcome = sorted_outcomes[0][0]
            top_weight = sorted_outcomes[0][1]
            second_weight = sorted_outcomes[1][1] if len(sorted_outcomes) > 1 else 0

            total_weight = sum(outcome_weights.values())

            # Calculate confidence score
            if total_weight > 0:
                confidence = ((top_weight - second_weight) / total_weight) * 100
            else:
                confidence = 0

            # Sort top traders by ELO
            top_traders_sorted = sorted(top_traders, key=lambda x: x[1], reverse=True)[:20]
            top_10_agree = sum(1 for _, _, outcome in top_traders_sorted[:10] if outcome == top_outcome)
            top_20_agree = sum(1 for _, _, outcome in top_traders_sorted[:20] if outcome == top_outcome)

            # Determine signal strength
            if confidence > 70 and top_10_agree >= 7:
                signal = "🔥 STRONG BUY"
            elif confidence > 50 and top_20_agree >= 12:
                signal = "✅ MODERATE BUY"
            elif confidence >= 30:
                signal = "⚠️ WEAK SIGNAL"
            else:
                signal = "❌ NO CONSENSUS"

            # Calculate expected probability
            expected_prob = (top_weight / total_weight) * 100

            active_market_predictions.append({
                'market_id': market_id,
                'market_title': market_title,
                'predicted_outcome': top_outcome,
                'confidence': confidence,
                'signal_strength': signal,
                'expected_probability': expected_prob,
                'top_10_agree': top_10_agree,
                'top_20_agree': top_20_agree,
                'total_traders': len(trader_positions),
                'outcome_weights': dict(outcome_weights)
            })

        print(f"Generated predictions for {len(active_market_predictions)} active markets")

        return active_market_predictions

    def evaluate_algorithm_performance(self) -> Dict:
        """
        Evaluate historical performance of weighted consensus.

        Compare weighted majority vs simple majority vs top trader.
        """
        print("\n📈 Evaluating algorithm performance...")

        trades = self.get_all_trades()
        market_trades = defaultdict(list)

        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        # For each resolved market, compare predictions
        weighted_correct = 0
        simple_correct = 0
        top_trader_correct = 0
        total_evaluated = 0

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)

            if not resolution or not resolution.get('resolved'):
                continue

            winning_outcome = resolution.get('winning_outcome')
            if not winning_outcome:
                continue

            # Calculate weighted majority prediction
            outcome_weights = defaultdict(float)
            outcome_counts = defaultdict(int)
            trader_elos = []

            for trade in trades_list:
                trader = trade.get('trader_address')
                outcome = str(trade.get('outcome', '')).lower()
                elo = self.elo_system.get_elo(trader)

                outcome_weights[outcome] += elo
                outcome_counts[outcome] += 1
                trader_elos.append((trader, elo, outcome))

            if not outcome_weights:
                continue

            # Weighted majority prediction
            weighted_pred = max(outcome_weights.items(), key=lambda x: x[1])[0]

            # Simple majority prediction
            simple_pred = max(outcome_counts.items(), key=lambda x: x[1])[0]

            # Top trader prediction
            top_trader = max(trader_elos, key=lambda x: x[1])
            top_trader_pred = top_trader[2]

            # Check accuracy
            if weighted_pred == winning_outcome:
                weighted_correct += 1

            if simple_pred == winning_outcome:
                simple_correct += 1

            if top_trader_pred == winning_outcome:
                top_trader_correct += 1

            total_evaluated += 1

        # Calculate accuracies
        if total_evaluated > 0:
            weighted_accuracy = (weighted_correct / total_evaluated) * 100
            simple_accuracy = (simple_correct / total_evaluated) * 100
            top_trader_accuracy = (top_trader_correct / total_evaluated) * 100
        else:
            weighted_accuracy = simple_accuracy = top_trader_accuracy = 0

        return {
            'total_markets': total_evaluated,
            'weighted_majority_correct': weighted_correct,
            'weighted_majority_accuracy': weighted_accuracy,
            'simple_majority_correct': simple_correct,
            'simple_majority_accuracy': simple_accuracy,
            'top_trader_correct': top_trader_correct,
            'top_trader_accuracy': top_trader_accuracy,
            'improvement_vs_simple': weighted_accuracy - simple_accuracy,
            'improvement_vs_top': weighted_accuracy - top_trader_accuracy
        }

    def generate_trader_rankings(self, output_path: str):
        """Generate CSV with trader ELO rankings."""
        print(f"\n💾 Generating trader rankings...")

        # Get all traders with their ELOs
        rankings = []

        for trader_address in self.elo_system.trader_elos.keys():
            current_elo = self.elo_system.get_elo(trader_address)
            elo_change_7d = self.elo_system.get_elo_change(trader_address, days=7)
            elo_change_30d = self.elo_system.get_elo_change(trader_address, days=30)

            # Count markets participated in
            history = self.elo_system.elo_history.get(trader_address, [])
            markets_participated = len(history)

            # Calculate win rate from history
            if history:
                wins = sum(1 for h in history if h['actual_score'] == 1.0)
                win_rate = (wins / len(history)) * 100
            else:
                win_rate = 0

            rankings.append({
                'trader_address': trader_address,
                'current_elo': current_elo,
                'elo_change_7d': elo_change_7d,
                'elo_change_30d': elo_change_30d,
                'markets_participated': markets_participated,
                'win_rate': win_rate
            })

        # Sort by ELO
        rankings.sort(key=lambda x: x['current_elo'], reverse=True)

        # Write to CSV
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Rank',
                'Trader Address',
                'Current ELO',
                'ELO Change (7d)',
                'ELO Change (30d)',
                'Markets Participated',
                'Win Rate (%)'
            ])

            for i, trader in enumerate(rankings, 1):
                writer.writerow([
                    i,
                    trader['trader_address'],
                    f"{trader['current_elo']:.2f}",
                    f"{trader['elo_change_7d']:.2f}",
                    f"{trader['elo_change_30d']:.2f}",
                    trader['markets_participated'],
                    f"{trader['win_rate']:.2f}"
                ])

        print(f"✅ Saved trader rankings to {output_path}")
        return rankings

    def generate_consensus_report(self, predictions: List[Dict], output_path: str):
        """Generate CSV with current market consensus predictions."""
        print(f"💾 Generating consensus predictions...")

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Market Title',
                'Predicted Outcome',
                'Confidence (%)',
                'Signal Strength',
                'Expected Probability (%)',
                'Top 10 Agree',
                'Top 20 Agree',
                'Total Traders'
            ])

            for pred in predictions:
                writer.writerow([
                    pred['market_title'],
                    pred['predicted_outcome'],
                    f"{pred['confidence']:.2f}",
                    pred['signal_strength'],
                    f"{pred['expected_probability']:.2f}",
                    pred['top_10_agree'],
                    pred['top_20_agree'],
                    pred['total_traders']
                ])

        print(f"✅ Saved consensus predictions to {output_path}")

    def generate_performance_report(self, performance: Dict, output_path: str):
        """Generate text report on algorithm performance."""
        print(f"💾 Generating performance report...")

        with open(output_path, 'w') as f:
            f.write("="*70 + "\n")
            f.write("WEIGHTED CONSENSUS ALGORITHM PERFORMANCE REPORT\n")
            f.write("="*70 + "\n\n")

            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("OVERALL PERFORMANCE:\n")
            f.write(f"  Total Markets Evaluated: {performance['total_markets']}\n\n")

            f.write("ACCURACY COMPARISON:\n")
            f.write(f"  Weighted Majority:  {performance['weighted_majority_correct']:3d} / {performance['total_markets']} = {performance['weighted_majority_accuracy']:.2f}%\n")
            f.write(f"  Simple Majority:    {performance['simple_majority_correct']:3d} / {performance['total_markets']} = {performance['simple_majority_accuracy']:.2f}%\n")
            f.write(f"  Top Trader:         {performance['top_trader_correct']:3d} / {performance['total_markets']} = {performance['top_trader_accuracy']:.2f}%\n\n")

            f.write("IMPROVEMENT:\n")
            f.write(f"  vs Simple Majority: {performance['improvement_vs_simple']:+.2f}%\n")
            f.write(f"  vs Top Trader:      {performance['improvement_vs_top']:+.2f}%\n\n")

            f.write("RECOMMENDATION:\n")
            if performance['weighted_majority_accuracy'] > 60:
                f.write(f"  ✅ FOLLOW weighted consensus signals with confidence >50%\n")
                f.write(f"  ✅ Algorithm shows strong predictive power ({performance['weighted_majority_accuracy']:.1f}% accuracy)\n")
            elif performance['weighted_majority_accuracy'] > 50:
                f.write(f"  ⚠️ Use weighted consensus cautiously - accuracy is {performance['weighted_majority_accuracy']:.1f}%\n")
                f.write(f"  ⚠️ Only follow STRONG signals (confidence >70%)\n")
            else:
                f.write(f"  ❌ Algorithm performance is weak ({performance['weighted_majority_accuracy']:.1f}%)\n")
                f.write(f"  ❌ Need more data or refinement before following signals\n")

            f.write("\n" + "="*70 + "\n")

        print(f"✅ Saved performance report to {output_path}")

    def display_terminal_report(self, rankings: List[Dict], predictions: List[Dict],
                               performance: Dict):
        """Display summary report in terminal."""
        print("\n" + "="*70)
        print("  WEIGHTED CONSENSUS SYSTEM - ANALYSIS REPORT")
        print("="*70 + "\n")

        # Top 10 traders by ELO
        print("🏆 TOP 10 TRADERS BY ELO RATING:")
        print("-"*70)
        print(f"{'Rank':<6}{'Address':<18}{'ELO':<10}{'Change (7d)':<13}{'Markets':<10}{'Win Rate'}")
        print("-"*70)

        for i, trader in enumerate(rankings[:10], 1):
            addr_short = trader['trader_address'][:15] + "..."
            elo_change = trader['elo_change_7d']
            change_indicator = "📈" if elo_change > 0 else "📉" if elo_change < 0 else "➖"

            print(f"{i:<6}{addr_short:<18}{trader['current_elo']:>7.0f}{change_indicator}  {elo_change:>+7.0f}{trader['markets_participated']:>10}{trader['win_rate']:>9.1f}%")

        # Strong signals
        strong_signals = [p for p in predictions if "STRONG" in p['signal_strength']]

        print("\n🔥 CURRENT STRONG BUY SIGNALS:")
        print("-"*70)

        if strong_signals:
            for pred in strong_signals:
                print(f"\nMarket: {pred['market_title'][:60]}")
                print(f"  → Predicted: {pred['predicted_outcome']}")
                print(f"  → Confidence: {pred['confidence']:.1f}%")
                print(f"  → Top 10 traders agree: {pred['top_10_agree']}/10")
                print(f"  → Expected probability: {pred['expected_probability']:.1f}%")
        else:
            print("  No strong signals at this time")

        # Algorithm performance
        print("\n📊 ALGORITHM PERFORMANCE:")
        print("-"*70)
        print(f"Markets Evaluated: {performance['total_markets']}")
        print(f"Weighted Majority Accuracy: {performance['weighted_majority_accuracy']:.2f}%")
        print(f"Simple Majority Accuracy: {performance['simple_majority_accuracy']:.2f}%")
        print(f"Top Trader Accuracy: {performance['top_trader_accuracy']:.2f}%")
        print(f"Improvement vs Simple: {performance['improvement_vs_simple']:+.2f}%")

        # Recommendation
        print("\n💡 RECOMMENDATION:")
        print("-"*70)
        if performance['weighted_majority_accuracy'] > 60:
            print("✅ Follow weighted consensus signals with confidence >50%")
            print(f"✅ Algorithm shows strong predictive power ({performance['weighted_majority_accuracy']:.1f}% accuracy)")
        elif performance['weighted_majority_accuracy'] > 50:
            print(f"⚠️ Use weighted consensus cautiously - accuracy is {performance['weighted_majority_accuracy']:.1f}%")
            print("⚠️ Only follow STRONG signals (confidence >70%)")
        else:
            print(f"❌ Algorithm performance is weak ({performance['weighted_majority_accuracy']:.1f}%)")
            print("❌ Need more data or refinement before following signals")

        print("\n" + "="*70 + "\n")


def main():
    """Main entry point."""

    # Load API key from .env
    api_key = None
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('POLYMARKET_API_KEY='):
                    api_key = line.strip().split('=', 1)[1].strip('"').strip("'")
                    break

    # Check if database exists
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
    if not os.path.exists(db_path):
        print("❌ Error: polymarket_tracker.db not found in /data/")
        print("   Make sure the monitoring script has run and collected trades")
        return

    # Ensure reports directory exists
    reports_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    # Initialize system
    print("="*70)
    print("  WEIGHTED CONSENSUS PREDICTION SYSTEM")
    print("="*70)

    system = WeightedConsensusSystem(api_key=api_key)

    # Step 1: Calculate ELO ratings
    system.calculate_elo_ratings(verbose=False)

    # Step 2: Generate consensus predictions for active markets
    predictions = system.calculate_weighted_consensus()

    # Step 3: Evaluate algorithm performance
    performance = system.evaluate_algorithm_performance()

    # Step 4: Generate reports
    timestamp = datetime.now().strftime('%Y%m%d')

    rankings = system.generate_trader_rankings(
        os.path.join(reports_dir, f'trader_elo_rankings_{timestamp}.csv')
    )

    system.generate_consensus_report(
        predictions,
        os.path.join(reports_dir, f'current_market_consensus_{timestamp}.csv')
    )

    system.generate_performance_report(
        performance,
        os.path.join(reports_dir, f'algorithm_performance_{timestamp}.txt')
    )

    # Step 5: Display terminal report
    system.display_terminal_report(rankings, predictions, performance)


if __name__ == "__main__":
    main()
