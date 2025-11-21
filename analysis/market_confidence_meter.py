#!/usr/bin/env python3
"""
Market Confidence Meter - Integration Analysis System

Combines insights from all analysis tools into actionable confidence scores.
Aggregates weighted consensus, specialist analysis, trader performance, and
behavior patterns to generate a single 0-100 confidence score per market.

Integration of:
- Weighted Consensus System (ELO-based predictions)
- Trader Specialization Analysis (category experts)
- Trader Performance Analysis (win rates, ROI)
- Trading Behavior Analysis (volume, activity patterns)
"""

import sqlite3
import csv
import os
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import statistics

# Import our analysis systems
import sys
sys.path.insert(0, os.path.dirname(__file__))

from weighted_consensus_system import WeightedConsensusSystem, ELORatingSystem
from trader_specialization_analysis import TraderSpecializationAnalyzer, CategorySpecificELO


class MarketConfidenceMeter:
    """
    Integration system that combines all analysis tools into actionable confidence scores.
    """

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.api_key = api_key

        # Initialize analysis systems
        print("🔄 Initializing analysis systems...")
        self.consensus_system = WeightedConsensusSystem(db_path, api_key)
        self.specialization_system = TraderSpecializationAnalyzer(db_path, api_key)

        # Storage for analysis results
        self.consensus_predictions = []
        self.specialist_classifications = {}
        self.specialist_predictions = []

        # Market confidence scores
        self.market_confidence_scores = {}

        # Historical accuracy per category
        self.category_accuracy = {}

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def run_all_analyses(self):
        """Run all underlying analysis systems."""
        print("\n" + "="*70)
        print("  MARKET CONFIDENCE METER - RUNNING ANALYSES")
        print("="*70)

        # 1. Calculate ELO ratings
        print("\n[1/3] Running Weighted Consensus System...")
        self.consensus_system.calculate_elo_ratings(verbose=False)
        self.consensus_predictions = self.consensus_system.calculate_weighted_consensus()

        # 2. Calculate specialization
        print("\n[2/3] Running Trader Specialization Analysis...")
        self.specialization_system.calculate_category_elos(verbose=False)
        self.specialist_classifications = self.specialization_system.identify_specialists()
        self.specialist_predictions = self.specialization_system.generate_context_aware_predictions(
            self.specialist_classifications
        )

        # 3. Calculate historical accuracy
        print("\n[3/3] Calculating Historical Accuracy...")
        self._calculate_category_accuracy()

        print("\n✅ All analyses complete!\n")

    def _calculate_category_accuracy(self):
        """Calculate historical prediction accuracy per category."""
        # Get performance from consensus system
        performance = self.consensus_system.evaluate_algorithm_performance()

        # For now, use overall accuracy for all categories
        # In production, would track per-category
        base_accuracy = performance.get('weighted_majority_accuracy', 65.0)

        # Assign to categories (could be refined with actual category tracking)
        self.category_accuracy = {
            'Elections': base_accuracy + 5,  # Typically more predictable
            'Geopolitics': base_accuracy - 5,  # More uncertain
            'Economics': base_accuracy,
            'Crypto': base_accuracy - 10,  # Very volatile
            'Sports': base_accuracy - 5,
            'Entertainment': base_accuracy,
            'Other': base_accuracy - 10
        }

    def calculate_confidence_score(self, market_id: str, market_title: str) -> Dict:
        """
        Calculate composite confidence score for a market.

        Returns dict with:
        - confidence_score (0-100)
        - classification
        - component_scores
        - flags
        - recommendation
        """
        # Find predictions for this market
        consensus_pred = None
        for pred in self.consensus_predictions:
            if pred['market_id'] == market_id:
                consensus_pred = pred
                break

        specialist_pred = None
        for pred in self.specialist_predictions:
            if pred['market_id'] == market_id:
                specialist_pred = pred
                break

        # If no predictions, return low confidence
        if not consensus_pred and not specialist_pred:
            return {
                'market_id': market_id,
                'market_title': market_title,
                'confidence_score': 0,
                'classification': '🔴 INSUFFICIENT DATA',
                'component_scores': {},
                'flags': ['❌ NO ANALYSIS DATA'],
                'recommendation': 'AVOID - Insufficient data'
            }

        # Extract data
        if consensus_pred:
            category = 'Other'
            predicted_outcome = consensus_pred.get('predicted_outcome', 'Unknown')
            consensus_confidence = consensus_pred.get('confidence', 0)
        elif specialist_pred:
            category = specialist_pred.get('category', 'Other')
            predicted_outcome = specialist_pred.get('predicted_outcome', 'Unknown')
            consensus_confidence = 0
        else:
            category = 'Other'
            predicted_outcome = 'Unknown'
            consensus_confidence = 0

        # Component 1: Weighted Consensus Confidence (30%)
        if consensus_confidence > 70:
            consensus_score = 90 + (consensus_confidence - 70) / 3
        elif consensus_confidence > 50:
            consensus_score = 60 + (consensus_confidence - 50) * 1.5
        elif consensus_confidence > 30:
            consensus_score = 30 + (consensus_confidence - 30) * 1.5
        else:
            consensus_score = consensus_confidence

        # Component 2: Specialist Agreement Score (25%)
        specialist_score = 25  # Default
        specialist_consensus = False

        if specialist_pred:
            specialists_agree = specialist_pred.get('specialists_agree', 0)
            total_specialists = specialist_pred.get('total_specialists', 0)

            if specialists_agree >= 8:
                specialist_score = 100
            elif specialists_agree >= 5:
                specialist_score = 75
            elif specialists_agree >= 3:
                specialist_score = 50
            else:
                specialist_score = 25

            # Bonus for specialist consensus flag
            if specialist_pred.get('specialist_consensus', False):
                specialist_score = min(100, specialist_score + 10)
                specialist_consensus = True

        # Component 3: Trader Quality Score (20%)
        # Calculate average ELO of traders on winning side
        trader_quality_score = 50  # Default

        if consensus_pred:
            # Get ELO of traders betting on predicted outcome
            outcome_weights = consensus_pred.get('outcome_weights', {})
            if outcome_weights and predicted_outcome in outcome_weights:
                # Rough estimate: high weight = high ELO traders
                top_weight = outcome_weights[predicted_outcome]
                total_weight = sum(outcome_weights.values())

                if total_weight > 0:
                    weight_ratio = top_weight / total_weight
                    # Convert to ELO-like score
                    implied_elo = 1500 + (weight_ratio - 0.5) * 500

                    if implied_elo > 1750:
                        trader_quality_score = 100
                    elif implied_elo > 1650:
                        trader_quality_score = 75
                    elif implied_elo > 1550:
                        trader_quality_score = 50
                    else:
                        trader_quality_score = 25

        # Component 4: Volume/Liquidity Score (15%)
        volume_score = 25  # Default
        total_volume = 0
        total_traders = 0

        # Calculate from database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(shares * price) as volume, COUNT(DISTINCT trader_address) as traders
            FROM trades
            WHERE market_id = ?
        """, (market_id,))

        row = cursor.fetchone()
        if row:
            total_volume = float(row['volume'] or 0)
            total_traders = int(row['traders'] or 0)
        conn.close()

        if total_volume > 50000:
            volume_score = 100
        elif total_volume > 20000:
            volume_score = 75
        elif total_volume > 5000:
            volume_score = 50
        else:
            volume_score = 25

        # Component 5: Historical Accuracy Score (10%)
        historical_score = self.category_accuracy.get(category, 60)

        if historical_score > 75:
            hist_score = 100
        elif historical_score > 65:
            hist_score = 75
        elif historical_score > 55:
            hist_score = 50
        else:
            hist_score = 25

        # Calculate composite score
        confidence_score = (
            consensus_score * 0.30 +
            specialist_score * 0.25 +
            trader_quality_score * 0.20 +
            volume_score * 0.15 +
            hist_score * 0.10
        )

        # Classification
        if confidence_score >= 80:
            classification = '🟢 STRONG BUY'
            recommendation = 'STRONG BUY - High confidence signal'
        elif confidence_score >= 70:
            classification = '🟢 MODERATE BUY'
            recommendation = 'MODERATE BUY - Good signal quality'
        elif confidence_score >= 60:
            classification = '🟡 WEAK BUY'
            recommendation = 'WEAK BUY - Proceed with caution'
        elif confidence_score >= 50:
            classification = '🟡 UNCERTAIN'
            recommendation = 'UNCERTAIN - High risk, consider passing'
        elif confidence_score >= 40:
            classification = '🟠 WEAK SIGNAL'
            recommendation = 'WEAK SIGNAL - Likely pass'
        else:
            classification = '🔴 AVOID'
            recommendation = 'AVOID - Low confidence'

        # Quality flags
        flags = []

        if specialist_consensus:
            flags.append('🔥 SPECIALIST CONSENSUS')

        if total_volume > 50000:
            flags.append('⭐ HIGH VOLUME')

        if consensus_pred and consensus_confidence > 75:
            flags.append('🎯 STRONG CONSENSUS')

        if total_volume < 5000:
            flags.append('⚠️ LOW LIQUIDITY')

        if total_traders < 5:
            flags.append('🆕 LIMITED PARTICIPATION')

        # Check for disagreement between tools
        disagreement = False
        if consensus_pred and specialist_pred:
            consensus_conf = consensus_pred.get('confidence', 0)
            specialist_conf = specialist_pred.get('confidence', 0)

            if abs(consensus_conf - specialist_conf) > 30:
                flags.append('❌ TOOL DISAGREEMENT')
                disagreement = True

        # Get top traders (from specialist predictions if available)
        top_traders = []
        if specialist_pred and 'top_specialists' in specialist_pred:
            top_traders = specialist_pred['top_specialists'][:3]

        return {
            'market_id': market_id,
            'market_title': market_title,
            'category': category,
            'predicted_outcome': predicted_outcome,
            'confidence_score': round(confidence_score, 1),
            'classification': classification,
            'component_scores': {
                'consensus': round(consensus_score, 1),
                'specialist': round(specialist_score, 1),
                'trader_quality': round(trader_quality_score, 1),
                'volume': round(volume_score, 1),
                'historical': round(hist_score, 1)
            },
            'raw_data': {
                'consensus_confidence': consensus_confidence,
                'specialists_agree': specialist_pred.get('specialists_agree', 0) if specialist_pred else 0,
                'total_specialists': specialist_pred.get('total_specialists', 0) if specialist_pred else 0,
                'total_volume': total_volume,
                'total_traders': total_traders,
                'category_accuracy': historical_score
            },
            'flags': flags,
            'recommendation': recommendation,
            'disagreement': disagreement,
            'top_traders': top_traders
        }

    def calculate_all_confidence_scores(self):
        """Calculate confidence scores for all active markets."""
        print("\n📊 Calculating confidence scores for all markets...")

        # Get all unique markets from predictions
        all_market_ids = set()

        for pred in self.consensus_predictions:
            all_market_ids.add((pred['market_id'], pred['market_title']))

        for pred in self.specialist_predictions:
            all_market_ids.add((pred['market_id'], pred['market_title']))

        print(f"Found {len(all_market_ids)} markets to analyze")

        for market_id, market_title in all_market_ids:
            score_data = self.calculate_confidence_score(market_id, market_title)
            self.market_confidence_scores[market_id] = score_data

        print(f"✅ Calculated confidence scores for {len(self.market_confidence_scores)} markets\n")

    def generate_reports(self, output_dir: str):
        """Generate all confidence meter reports."""
        print("💾 Generating confidence meter reports...")

        timestamp = datetime.now().strftime('%Y%m%d')

        # Sort markets by confidence
        sorted_markets = sorted(
            self.market_confidence_scores.values(),
            key=lambda x: x['confidence_score'],
            reverse=True
        )

        # 1. Market Confidence Scores CSV
        self._generate_confidence_csv(
            sorted_markets,
            os.path.join(output_dir, f'market_confidence_scores_{timestamp}.csv')
        )

        # 2. High Confidence Signals CSV
        high_confidence = [m for m in sorted_markets if m['confidence_score'] >= 70]
        self._generate_high_confidence_csv(
            high_confidence,
            os.path.join(output_dir, f'high_confidence_signals_{timestamp}.csv')
        )

        # 3. Confidence Summary TXT
        self._generate_summary_txt(
            sorted_markets,
            os.path.join(output_dir, f'confidence_summary_{timestamp}.txt')
        )

        # 4. Signal Quality Report CSV
        self._generate_quality_csv(
            sorted_markets,
            os.path.join(output_dir, f'signal_quality_report_{timestamp}.csv')
        )

        print("✅ All reports generated\n")

    def _generate_confidence_csv(self, markets: List[Dict], output_path: str):
        """Generate main confidence scores CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Market Title',
                'Category',
                'Predicted Outcome',
                'Confidence Score',
                'Classification',
                'Consensus Score',
                'Specialist Score',
                'Trader Quality Score',
                'Volume Score',
                'Historical Score',
                'Total Volume ($)',
                'Total Traders',
                'Flags',
                'Recommendation'
            ])

            for market in markets:
                flags_str = '; '.join(market['flags']) if market['flags'] else 'None'

                writer.writerow([
                    market['market_title'],
                    market['category'],
                    market['predicted_outcome'],
                    market['confidence_score'],
                    market['classification'],
                    market['component_scores']['consensus'],
                    market['component_scores']['specialist'],
                    market['component_scores']['trader_quality'],
                    market['component_scores']['volume'],
                    market['component_scores']['historical'],
                    f"{market['raw_data']['total_volume']:.2f}",
                    market['raw_data']['total_traders'],
                    flags_str,
                    market['recommendation']
                ])

        print(f"  → {output_path}")

    def _generate_high_confidence_csv(self, markets: List[Dict], output_path: str):
        """Generate high confidence signals CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Rank',
                'Market Title',
                'Category',
                'Predicted Outcome',
                'Confidence Score',
                'Flags',
                'Top Traders',
                'Recommendation'
            ])

            for i, market in enumerate(markets, 1):
                flags_str = '; '.join(market['flags']) if market['flags'] else 'None'

                top_traders_str = '; '.join(
                    f"{addr[:12]}... (ELO: {elo:.0f})"
                    for addr, elo, _ in market['top_traders']
                ) if market['top_traders'] else 'N/A'

                writer.writerow([
                    i,
                    market['market_title'],
                    market['category'],
                    market['predicted_outcome'],
                    market['confidence_score'],
                    flags_str,
                    top_traders_str,
                    market['recommendation']
                ])

        print(f"  → {output_path}")

    def _generate_summary_txt(self, markets: List[Dict], output_path: str):
        """Generate confidence summary text report."""
        with open(output_path, 'w') as f:
            f.write("="*70 + "\n")
            f.write("MARKET CONFIDENCE METER - SUMMARY REPORT\n")
            f.write("="*70 + "\n\n")

            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Markets Analyzed: {len(markets)}\n\n")

            # Calculate statistics
            if markets:
                avg_confidence = statistics.mean(m['confidence_score'] for m in markets)

                strong_buy = sum(1 for m in markets if m['confidence_score'] >= 80)
                moderate_buy = sum(1 for m in markets if 70 <= m['confidence_score'] < 80)
                weak_buy = sum(1 for m in markets if 60 <= m['confidence_score'] < 70)
                uncertain = sum(1 for m in markets if 50 <= m['confidence_score'] < 60)
                avoid = sum(1 for m in markets if m['confidence_score'] < 50)

                f.write("OVERALL STATISTICS:\n")
                f.write(f"  Average Confidence: {avg_confidence:.1f}\n")
                f.write(f"  Highest Confidence: {max(m['confidence_score'] for m in markets):.1f}\n")
                f.write(f"  Lowest Confidence: {min(m['confidence_score'] for m in markets):.1f}\n\n")

                f.write("SIGNAL DISTRIBUTION:\n")
                f.write(f"  🟢 STRONG BUY (80-100): {strong_buy} markets\n")
                f.write(f"  🟢 MODERATE BUY (70-79): {moderate_buy} markets\n")
                f.write(f"  🟡 WEAK BUY (60-69): {weak_buy} markets\n")
                f.write(f"  🟡 UNCERTAIN (50-59): {uncertain} markets\n")
                f.write(f"  🔴 AVOID (0-49): {avoid} markets\n\n")

                # Category breakdown
                category_scores = defaultdict(list)
                for market in markets:
                    category_scores[market['category']].append(market['confidence_score'])

                f.write("CATEGORY BREAKDOWN:\n")
                for category, scores in sorted(category_scores.items()):
                    avg = statistics.mean(scores)
                    f.write(f"  {category}: {avg:.1f} avg confidence ({len(scores)} markets)\n")

                # Top 5 most confident
                f.write("\nTOP 5 MOST CONFIDENT MARKETS:\n")
                for i, market in enumerate(markets[:5], 1):
                    f.write(f"  {i}. {market['market_title'][:60]}\n")
                    f.write(f"     Confidence: {market['confidence_score']:.1f} - {market['classification']}\n")

                # Top 5 least confident
                f.write("\nTOP 5 LEAST CONFIDENT MARKETS:\n")
                for i, market in enumerate(markets[-5:], 1):
                    f.write(f"  {i}. {market['market_title'][:60]}\n")
                    f.write(f"     Confidence: {market['confidence_score']:.1f} - {market['classification']}\n")

            f.write("\n" + "="*70 + "\n")

        print(f"  → {output_path}")

    def _generate_quality_csv(self, markets: List[Dict], output_path: str):
        """Generate signal quality report CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Market Title',
                'Confidence Score',
                'Consensus Confidence (%)',
                'Specialists Agree',
                'Total Specialists',
                'Implied Trader ELO',
                'Total Volume ($)',
                'Total Traders',
                'Category Accuracy (%)',
                'Disagreement Flag',
                'Recommendation'
            ])

            for market in markets:
                writer.writerow([
                    market['market_title'],
                    market['confidence_score'],
                    market['raw_data']['consensus_confidence'],
                    market['raw_data']['specialists_agree'],
                    market['raw_data']['total_specialists'],
                    'N/A',  # Would need to calculate separately
                    f"{market['raw_data']['total_volume']:.2f}",
                    market['raw_data']['total_traders'],
                    market['raw_data']['category_accuracy'],
                    'Yes' if market['disagreement'] else 'No',
                    market['recommendation']
                ])

        print(f"  → {output_path}")

    def display_dashboard(self):
        """Display confidence meter dashboard in terminal."""
        print("\n" + "="*70)
        print("  MARKET CONFIDENCE METER - SIGNAL DASHBOARD")
        print("="*70)

        # Sort by confidence
        sorted_markets = sorted(
            self.market_confidence_scores.values(),
            key=lambda x: x['confidence_score'],
            reverse=True
        )

        # High confidence signals
        high_confidence = [m for m in sorted_markets if m['confidence_score'] >= 80]

        print("\n🟢 HIGH CONFIDENCE SIGNALS (80-100):")
        print("="*70)

        if high_confidence:
            for market in high_confidence:
                print(f"\nMarket: {market['market_title'][:60]}")
                print(f"Category: {market['category']}")
                print(f"→ Predicted: {market['predicted_outcome']}")
                print(f"→ CONFIDENCE: {market['confidence_score']:.0f}/100 {market['classification']}")
                print(f"→ Components:")
                print(f"  • Weighted Consensus: {market['raw_data']['consensus_confidence']:.0f}% (score: {market['component_scores']['consensus']:.0f})")
                print(f"  • Specialist Agreement: {market['raw_data']['specialists_agree']}/{market['raw_data']['total_specialists']} agree (score: {market['component_scores']['specialist']:.0f})")
                print(f"  • Trader Quality: (score: {market['component_scores']['trader_quality']:.0f})")
                print(f"  • Volume: ${market['raw_data']['total_volume']:,.0f} (score: {market['component_scores']['volume']:.0f})")
                print(f"  • Historical: {market['raw_data']['category_accuracy']:.0f}% accuracy (score: {market['component_scores']['historical']:.0f})")

                if market['flags']:
                    print(f"→ Flags: {', '.join(market['flags'])}")

                if market['top_traders']:
                    traders_str = ', '.join(f"{addr[:12]}... ({elo:.0f})" for addr, elo, _ in market['top_traders'][:3])
                    print(f"→ Top Traders: {traders_str}")

                print(f"→ RECOMMENDATION: {market['recommendation']}")
        else:
            print("  No high confidence signals at this time")

        # Summary statistics
        print("\n" + "="*70)
        print("📊 OVERALL DASHBOARD:")
        print("-"*70)

        if sorted_markets:
            avg_confidence = statistics.mean(m['confidence_score'] for m in sorted_markets)

            strong_buy = sum(1 for m in sorted_markets if m['confidence_score'] >= 80)
            moderate_buy = sum(1 for m in sorted_markets if 70 <= m['confidence_score'] < 80)
            uncertain = sum(1 for m in sorted_markets if 50 <= m['confidence_score'] < 70)
            avoid = sum(1 for m in sorted_markets if m['confidence_score'] < 50)

            print(f"Average Confidence: {avg_confidence:.1f}")
            print(f"Markets Analyzed: {len(sorted_markets)}")
            print(f"STRONG BUY Signals: {strong_buy}")
            print(f"MODERATE BUY Signals: {moderate_buy}")
            print(f"UNCERTAIN Markets: {uncertain}")
            print(f"AVOID Markets: {avoid}")

            # Category breakdown
            print("\nCategory Breakdown:")
            category_scores = defaultdict(list)
            for market in sorted_markets:
                category_scores[market['category']].append(market['confidence_score'])

            for category, scores in sorted(category_scores.items(), key=lambda x: statistics.mean(x[1]), reverse=True):
                avg = statistics.mean(scores)
                if avg >= 70:
                    strength = "(strong)"
                elif avg >= 60:
                    strength = "(moderate)"
                else:
                    strength = "(weak)"
                print(f"  {category}: {avg:.0f} avg confidence {strength}")

        print("\n" + "="*70 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Market Confidence Meter')
    parser.add_argument('--market', type=str, help='Analyze specific market ID')
    parser.add_argument('--min-confidence', type=int, default=0, help='Minimum confidence threshold')

    args = parser.parse_args()

    # Load API key
    api_key = None
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('POLYMARKET_API_KEY='):
                    api_key = line.strip().split('=', 1)[1].strip('"').strip("'")
                    break

    # Check database
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
    if not os.path.exists(db_path):
        print("❌ Error: polymarket_tracker.db not found in /data/")
        print("   Make sure the monitoring script has run and collected trades")
        return

    # Ensure reports directory
    reports_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    # Initialize confidence meter
    print("="*70)
    print("  MARKET CONFIDENCE METER - INTEGRATION ANALYSIS")
    print("="*70)

    meter = MarketConfidenceMeter(api_key=api_key)

    # Run all analyses
    meter.run_all_analyses()

    # Calculate confidence scores
    meter.calculate_all_confidence_scores()

    # Generate reports
    meter.generate_reports(reports_dir)

    # Display dashboard
    meter.display_dashboard()


if __name__ == "__main__":
    main()
