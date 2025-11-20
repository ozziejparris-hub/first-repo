#!/usr/bin/env python3
"""
Consensus Divergence Detector - Contrarian Opportunity Finder

Identifies when top traders DISAGREE on market outcomes, signaling either
high uncertainty (avoid) or contrarian opportunities (potential alpha).

Core Insight:
- Strong consensus → Lower value (price reflects agreement)
- High disagreement + valuable contrarians → Alpha opportunity
- High disagreement + no contrarians → Avoid (chaos)

Detects:
- Trader disagreement patterns
- Profitable contrarian traders
- Smart money divergence
- Uncertainty scoring
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
from trader_specialization_analysis import TraderSpecializationAnalyzer


class ConsensusDivergenceDetector:
    """
    Detects profitable disagreement opportunities when top traders diverge.
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
        self.market_disagreements = {}
        self.contrarian_traders = {}
        self.contrarian_opportunities = []
        self.smart_money_divergences = []

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def run_prerequisite_analyses(self):
        """Run ELO and specialization analyses."""
        print("\n" + "="*70)
        print("  CONSENSUS DIVERGENCE DETECTOR - RUNNING ANALYSES")
        print("="*70)

        print("\n[1/2] Calculating ELO ratings...")
        self.consensus_system.calculate_elo_ratings(verbose=False)

        print("\n[2/2] Calculating category specializations...")
        self.specialization_system.calculate_category_elos(verbose=False)
        self.specialists = self.specialization_system.identify_specialists()

        print("\n✅ Prerequisite analyses complete!\n")

    def calculate_disagreement_score(self, market_id: str) -> Dict:
        """
        Calculate disagreement metrics for a market.

        Returns dict with:
        - top_trader_split: % Yes vs % No among top 20 traders
        - disagreement_score: 0-1 (1 = maximum disagreement)
        - specialist_split: % Yes vs % No among specialists
        - elo_weighted_split: ELO-weighted % split
        - bet_size_disagreement: Variance in bet sizes on opposite sides
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get all trades for this market with trader ELOs
        cursor.execute("""
            SELECT trader_address, outcome, shares, price, timestamp
            FROM trades
            WHERE market_id = ?
            ORDER BY timestamp
        """, (market_id,))

        trades = cursor.fetchall()
        conn.close()

        if not trades:
            return None

        # Get ELO for each trader
        trader_elos = {}
        for trade in trades:
            trader = trade['trader_address']
            if trader not in trader_elos:
                trader_elos[trader] = self.consensus_system.elo_system.get_elo(trader)

        # Sort traders by ELO
        top_traders = sorted(trader_elos.items(), key=lambda x: x[1], reverse=True)[:20]
        top_trader_addresses = [addr for addr, _ in top_traders]

        # 1. TOP TRADER SPLIT
        top_trader_positions = {}
        for trade in trades:
            trader = trade['trader_address']
            if trader in top_trader_addresses:
                outcome = trade['outcome']
                if trader not in top_trader_positions:
                    top_trader_positions[trader] = outcome
                # Use most recent position

        if not top_trader_positions:
            return None

        yes_count = sum(1 for outcome in top_trader_positions.values() if outcome.lower() in ['yes', 'true', '1'])
        total_count = len(top_trader_positions)
        yes_pct = yes_count / total_count if total_count > 0 else 0
        no_pct = 1 - yes_pct

        # Disagreement score: 1 - |yes% - no%|
        disagreement_score = 1 - abs(yes_pct - no_pct)

        # 2. SPECIALIST DIVERGENCE
        # Get category for this market
        cursor = conn.get_db_connection().cursor()
        cursor.execute("SELECT title, tags FROM markets WHERE market_id = ?", (market_id,))
        market_row = cursor.fetchone()
        market_title = market_row['title'] if market_row else ""
        market_tags = market_row['tags'] if market_row else ""
        category = self.specialization_system.categorize_market(market_title, market_tags)
        conn.close()

        # Find specialists in this category
        specialist_positions = {}
        for trader, specs in self.specialists.items():
            if trader in top_trader_addresses and category in specs.get('specializations', []):
                if trader in top_trader_positions:
                    specialist_positions[trader] = top_trader_positions[trader]

        if specialist_positions:
            spec_yes = sum(1 for o in specialist_positions.values() if o.lower() in ['yes', 'true', '1'])
            spec_total = len(specialist_positions)
            spec_yes_pct = spec_yes / spec_total
            spec_no_pct = 1 - spec_yes_pct
            specialist_disagreement = 1 - abs(spec_yes_pct - spec_no_pct)
        else:
            spec_yes_pct = 0
            spec_no_pct = 0
            specialist_disagreement = 0

        # 3. ELO-WEIGHTED SPLIT
        yes_elo_weight = 0
        no_elo_weight = 0

        for trader, outcome in top_trader_positions.items():
            elo = trader_elos[trader]
            if outcome.lower() in ['yes', 'true', '1']:
                yes_elo_weight += elo
            else:
                no_elo_weight += elo

        total_elo_weight = yes_elo_weight + no_elo_weight
        elo_yes_pct = yes_elo_weight / total_elo_weight if total_elo_weight > 0 else 0
        elo_no_pct = 1 - elo_yes_pct
        elo_weighted_disagreement = 1 - abs(elo_yes_pct - elo_no_pct)

        # 4. BET SIZE DISAGREEMENT
        yes_bet_sizes = []
        no_bet_sizes = []

        for trade in trades:
            if trade['trader_address'] in top_trader_addresses:
                bet_size = float(trade['shares']) * float(trade['price'])
                outcome = trade['outcome']
                if outcome.lower() in ['yes', 'true', '1']:
                    yes_bet_sizes.append(bet_size)
                else:
                    no_bet_sizes.append(bet_size)

        # Calculate if large bets on both sides
        large_bet_threshold = 1000  # $1000+
        yes_large_bets = sum(1 for size in yes_bet_sizes if size > large_bet_threshold)
        no_large_bets = sum(1 for size in no_bet_sizes if size > large_bet_threshold)
        bet_size_conflict = min(yes_large_bets, no_large_bets)  # Both sides have large bets

        return {
            'market_id': market_id,
            'category': category,
            'top_trader_split': {
                'yes_pct': yes_pct,
                'no_pct': no_pct,
                'yes_count': yes_count,
                'no_count': total_count - yes_count,
                'total': total_count
            },
            'disagreement_score': disagreement_score,
            'specialist_split': {
                'yes_pct': spec_yes_pct,
                'no_pct': spec_no_pct,
                'total': len(specialist_positions)
            },
            'specialist_disagreement': specialist_disagreement,
            'elo_weighted_split': {
                'yes_pct': elo_yes_pct,
                'no_pct': elo_no_pct,
                'yes_weight': yes_elo_weight,
                'no_weight': no_elo_weight
            },
            'elo_weighted_disagreement': elo_weighted_disagreement,
            'bet_size_conflict': bet_size_conflict,
            'top_traders': top_trader_addresses
        }

    def classify_market_by_disagreement(self, disagreement_score: float) -> Tuple[str, str]:
        """
        Classify market by disagreement level.

        Returns (classification, description)
        """
        if disagreement_score < 0.30:
            return ("STRONG CONSENSUS", "Low uncertainty, clear agreement")
        elif disagreement_score < 0.60:
            return ("MODERATE SPLIT", "Some disagreement, one side favored")
        elif disagreement_score < 0.80:
            return ("HIGH DISAGREEMENT", "Significant split among experts")
        else:
            return ("MAXIMUM UNCERTAINTY", "Nearly 50/50 split")

    def identify_contrarian_traders(self) -> Dict:
        """
        Identify traders who profit by going against consensus.

        Returns dict mapping trader_address to contrarian metrics.
        """
        print("🔍 Identifying contrarian traders...")

        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get all resolved markets with trades
        cursor.execute("""
            SELECT DISTINCT m.market_id, m.title, m.resolved_outcome
            FROM markets m
            JOIN trades t ON m.market_id = t.market_id
            WHERE m.resolved_outcome IS NOT NULL
                AND m.resolved_outcome != ''
                AND m.resolved_outcome != 'Unknown'
        """)

        resolved_markets = cursor.fetchall()

        # For each trader, track contrarian performance
        trader_stats = defaultdict(lambda: {
            'total_bets': 0,
            'contrarian_bets': 0,
            'contrarian_wins': 0,
            'consensus_bets': 0,
            'consensus_wins': 0,
            'contrarian_profit': 0,
            'consensus_profit': 0
        })

        for market in resolved_markets:
            market_id = market['market_id']
            resolved_outcome = market['resolved_outcome']

            # Get all trades for this market
            cursor.execute("""
                SELECT trader_address, outcome, shares, price
                FROM trades
                WHERE market_id = ?
            """, (market_id,))

            trades = cursor.fetchall()

            # Determine consensus (majority outcome)
            outcome_counts = defaultdict(int)
            for trade in trades:
                outcome_counts[trade['outcome']] += 1

            if not outcome_counts:
                continue

            consensus_outcome = max(outcome_counts.items(), key=lambda x: x[1])[0]
            total_trades = sum(outcome_counts.values())

            # Check each trader's position
            for trade in trades:
                trader = trade['trader_address']
                outcome = trade['outcome']
                bet_size = float(trade['shares']) * float(trade['price'])

                trader_stats[trader]['total_bets'] += 1

                # Determine if contrarian (bet against majority)
                is_contrarian = (outcome != consensus_outcome)

                if is_contrarian:
                    trader_stats[trader]['contrarian_bets'] += 1

                    # Check if won
                    if outcome == resolved_outcome:
                        trader_stats[trader]['contrarian_wins'] += 1
                        trader_stats[trader]['contrarian_profit'] += bet_size  # Simplified P&L

                else:
                    trader_stats[trader]['consensus_bets'] += 1

                    if outcome == resolved_outcome:
                        trader_stats[trader]['consensus_wins'] += 1
                        trader_stats[trader]['consensus_profit'] += bet_size

        conn.close()

        # Calculate contrarian metrics
        contrarian_traders = {}

        for trader, stats in trader_stats.items():
            if stats['total_bets'] < 10:  # Minimum bet threshold
                continue

            contrarian_rate = stats['contrarian_bets'] / stats['total_bets']

            contrarian_win_rate = (
                stats['contrarian_wins'] / stats['contrarian_bets']
                if stats['contrarian_bets'] > 0 else 0
            )

            consensus_win_rate = (
                stats['consensus_wins'] / stats['consensus_bets']
                if stats['consensus_bets'] > 0 else 0
            )

            contrarian_roi = (
                (stats['contrarian_profit'] / stats['contrarian_bets'])
                if stats['contrarian_bets'] > 0 else 0
            )

            # Classify contrarian type
            if contrarian_rate > 0.6 and contrarian_win_rate > 0.6:
                contrarian_type = "Consistent Contrarian"
            elif contrarian_rate > 0.3 and contrarian_win_rate > 0.65:
                contrarian_type = "Selective Contrarian"
            elif contrarian_rate < 0.2:
                contrarian_type = "Herd Follower"
            elif contrarian_rate > 0.4 and contrarian_win_rate < 0.5:
                contrarian_type = "Chaos Bettor"
            else:
                contrarian_type = "Balanced Trader"

            # Identify valuable contrarians
            is_valuable = (
                contrarian_win_rate > 0.6 and
                contrarian_rate > 0.3 and
                contrarian_roi > 10
            )

            contrarian_traders[trader] = {
                'elo': self.consensus_system.elo_system.get_elo(trader),
                'total_bets': stats['total_bets'],
                'contrarian_rate': contrarian_rate,
                'contrarian_win_rate': contrarian_win_rate,
                'consensus_win_rate': consensus_win_rate,
                'contrarian_roi': contrarian_roi,
                'contrarian_bets': stats['contrarian_bets'],
                'contrarian_wins': stats['contrarian_wins'],
                'contrarian_type': contrarian_type,
                'is_valuable': is_valuable
            }

        print(f"✅ Identified {len(contrarian_traders)} traders with contrarian metrics\n")
        return contrarian_traders

    def detect_smart_money_divergence(self, market_id: str, disagreement_data: Dict) -> bool:
        """
        Detect if smart money (top 5 ELO) bets opposite of majority.

        Returns True if divergence detected.
        """
        if not disagreement_data:
            return False

        # Get top 5 ELO traders on this market
        top_traders = disagreement_data['top_traders'][:5]

        # Get their positions
        conn = self.get_db_connection()
        cursor = conn.cursor()

        positions = {}
        for trader in top_traders:
            cursor.execute("""
                SELECT outcome
                FROM trades
                WHERE market_id = ? AND trader_address = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (market_id, trader))

            row = cursor.fetchone()
            if row:
                positions[trader] = row['outcome']

        conn.close()

        if len(positions) < 3:
            return False

        # Check if top traders bet opposite of overall majority
        top_split = disagreement_data['top_trader_split']
        majority_outcome = 'Yes' if top_split['yes_pct'] > 0.5 else 'No'

        # Count how many of top 5 bet against majority
        divergent_count = 0
        for outcome in positions.values():
            if (majority_outcome == 'Yes' and outcome.lower() not in ['yes', 'true', '1']) or \
               (majority_outcome == 'No' and outcome.lower() in ['yes', 'true', '1']):
                divergent_count += 1

        # If 3+ of top 5 bet against majority, it's divergence
        return divergent_count >= 3

    def calculate_uncertainty_score(self, disagreement_data: Dict) -> float:
        """
        Calculate uncertainty score (0-100).

        High uncertainty = disagreement + specialist split + bet size conflict
        """
        if not disagreement_data:
            return 0

        # Component 1: Base disagreement (50%)
        disagreement = disagreement_data['disagreement_score']
        disagreement_component = disagreement * 50

        # Component 2: Specialist disagreement (30%)
        specialist_disagreement = disagreement_data['specialist_disagreement']
        specialist_component = specialist_disagreement * 30

        # Component 3: Bet size conflict (20%)
        bet_conflict = disagreement_data['bet_size_conflict']
        conflict_component = min(bet_conflict / 5, 1.0) * 20  # Normalize to 0-1

        uncertainty = disagreement_component + specialist_component + conflict_component

        return min(uncertainty, 100)

    def detect_contrarian_opportunities(self):
        """
        Identify markets with contrarian alpha potential.

        High disagreement + valuable contrarians = opportunity
        """
        print("🎯 Detecting contrarian opportunities...")

        opportunities = []

        for market_id, disagreement_data in self.market_disagreements.items():
            if not disagreement_data:
                continue

            disagreement_score = disagreement_data['disagreement_score']

            # Only consider high disagreement markets
            if disagreement_score < 0.60:
                continue

            # Get market details
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM markets WHERE market_id = ?", (market_id,))
            market_row = cursor.fetchone()
            market_title = market_row['title'] if market_row else "Unknown"
            conn.close()

            # Check for valuable contrarians on this market
            contrarians_on_market = []
            consensus_side = 'Yes' if disagreement_data['top_trader_split']['yes_pct'] > 0.5 else 'No'

            for trader in disagreement_data['top_traders']:
                if trader in self.contrarian_traders:
                    trader_data = self.contrarian_traders[trader]
                    if trader_data['is_valuable']:
                        # Get trader's position
                        conn = self.get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT outcome
                            FROM trades
                            WHERE market_id = ? AND trader_address = ?
                            ORDER BY timestamp DESC
                            LIMIT 1
                        """, (market_id, trader))

                        row = cursor.fetchone()
                        conn.close()

                        if row:
                            outcome = row['outcome']
                            contrarians_on_market.append({
                                'trader': trader,
                                'outcome': outcome,
                                'contrarian_win_rate': trader_data['contrarian_win_rate'],
                                'elo': trader_data['elo']
                            })

            # Check if multiple valuable contrarians agree
            if len(contrarians_on_market) >= 2:
                # Check if they align on same side
                outcomes = [c['outcome'] for c in contrarians_on_market]
                yes_count = sum(1 for o in outcomes if o.lower() in ['yes', 'true', '1'])
                no_count = len(outcomes) - yes_count

                contrarian_side = 'Yes' if yes_count > no_count else 'No'

                # If contrarians bet opposite of consensus, it's an opportunity
                if contrarian_side != consensus_side:
                    # Check for smart money divergence
                    smart_money_flag = self.detect_smart_money_divergence(market_id, disagreement_data)

                    # Calculate expected value (simplified)
                    avg_contrarian_wr = statistics.mean(
                        c['contrarian_win_rate'] for c in contrarians_on_market
                    )
                    expected_value = "High" if avg_contrarian_wr > 0.65 else "Moderate"

                    uncertainty = self.calculate_uncertainty_score(disagreement_data)

                    opportunities.append({
                        'market_id': market_id,
                        'market_title': market_title,
                        'category': disagreement_data['category'],
                        'disagreement_score': disagreement_score,
                        'consensus_side': consensus_side,
                        'contrarian_side': contrarian_side,
                        'valuable_contrarians': contrarians_on_market,
                        'valuable_contrarian_count': len(contrarians_on_market),
                        'expected_value': expected_value,
                        'smart_money_divergence': smart_money_flag,
                        'uncertainty_score': uncertainty,
                        'signal_strength': 'STRONG' if len(contrarians_on_market) >= 3 else 'MODERATE'
                    })

        self.contrarian_opportunities = sorted(
            opportunities,
            key=lambda x: (x['valuable_contrarian_count'], x['disagreement_score']),
            reverse=True
        )

        print(f"✅ Found {len(self.contrarian_opportunities)} contrarian opportunities\n")

    def analyze_all_markets(self):
        """Analyze disagreement for all active markets."""
        print("📊 Analyzing disagreement for all markets...")

        conn = self.get_db_connection()
        cursor = conn.cursor()

        # Get all markets with trades (active or resolved)
        cursor.execute("""
            SELECT DISTINCT m.market_id, m.title
            FROM markets m
            JOIN trades t ON m.market_id = t.market_id
        """)

        markets = cursor.fetchall()
        conn.close()

        print(f"Found {len(markets)} markets to analyze")

        for market in markets:
            market_id = market['market_id']
            disagreement_data = self.calculate_disagreement_score(market_id)

            if disagreement_data:
                disagreement_data['market_title'] = market['title']
                self.market_disagreements[market_id] = disagreement_data

        print(f"✅ Analyzed {len(self.market_disagreements)} markets\n")

    def generate_reports(self, output_dir: str):
        """Generate all divergence detector reports."""
        print("💾 Generating consensus divergence reports...")

        timestamp = datetime.now().strftime('%Y%m%d')

        # 1. Disagreement Analysis CSV
        self._generate_disagreement_csv(
            os.path.join(output_dir, f'disagreement_analysis_{timestamp}.csv')
        )

        # 2. Contrarian Traders CSV
        self._generate_contrarian_traders_csv(
            os.path.join(output_dir, f'contrarian_traders_{timestamp}.csv')
        )

        # 3. Contrarian Opportunities CSV
        self._generate_opportunities_csv(
            os.path.join(output_dir, f'contrarian_opportunities_{timestamp}.csv')
        )

        # 4. Disagreement Insights TXT
        self._generate_insights_txt(
            os.path.join(output_dir, f'disagreement_insights_{timestamp}.txt')
        )

        print("✅ All reports generated\n")

    def _generate_disagreement_csv(self, output_path: str):
        """Generate disagreement analysis CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Market Title',
                'Category',
                'Disagreement Score',
                'Classification',
                'Top Trader Split (Yes%)',
                'Top Trader Split (No%)',
                'Specialist Split (Yes%)',
                'Specialist Split (No%)',
                'ELO Weighted Split (Yes%)',
                'ELO Weighted Split (No%)',
                'Bet Size Conflict',
                'Uncertainty Score',
                'Smart Money Divergence'
            ])

            for market_id, data in self.market_disagreements.items():
                classification, _ = self.classify_market_by_disagreement(data['disagreement_score'])
                uncertainty = self.calculate_uncertainty_score(data)
                smart_money = self.detect_smart_money_divergence(market_id, data)

                writer.writerow([
                    data['market_title'],
                    data['category'],
                    f"{data['disagreement_score']:.3f}",
                    classification,
                    f"{data['top_trader_split']['yes_pct']*100:.1f}",
                    f"{data['top_trader_split']['no_pct']*100:.1f}",
                    f"{data['specialist_split']['yes_pct']*100:.1f}",
                    f"{data['specialist_split']['no_pct']*100:.1f}",
                    f"{data['elo_weighted_split']['yes_pct']*100:.1f}",
                    f"{data['elo_weighted_split']['no_pct']*100:.1f}",
                    data['bet_size_conflict'],
                    f"{uncertainty:.1f}",
                    'Yes' if smart_money else 'No'
                ])

        print(f"  → {output_path}")

    def _generate_contrarian_traders_csv(self, output_path: str):
        """Generate contrarian traders CSV."""
        # Sort by contrarian win rate
        sorted_contrarians = sorted(
            self.contrarian_traders.items(),
            key=lambda x: x[1]['contrarian_win_rate'],
            reverse=True
        )

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Rank',
                'Trader Address',
                'Overall ELO',
                'Contrarian Rate (%)',
                'Contrarian Win Rate (%)',
                'Consensus Win Rate (%)',
                'Contrarian ROI',
                'Total Bets',
                'Contrarian Bets',
                'Contrarian Wins',
                'Contrarian Type',
                'Valuable'
            ])

            for rank, (trader, data) in enumerate(sorted_contrarians, 1):
                writer.writerow([
                    rank,
                    trader,
                    f"{data['elo']:.0f}",
                    f"{data['contrarian_rate']*100:.1f}",
                    f"{data['contrarian_win_rate']*100:.1f}",
                    f"{data['consensus_win_rate']*100:.1f}",
                    f"{data['contrarian_roi']:.2f}",
                    data['total_bets'],
                    data['contrarian_bets'],
                    data['contrarian_wins'],
                    data['contrarian_type'],
                    'Yes' if data['is_valuable'] else 'No'
                ])

        print(f"  → {output_path}")

    def _generate_opportunities_csv(self, output_path: str):
        """Generate contrarian opportunities CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Rank',
                'Market Title',
                'Category',
                'Disagreement Score',
                'Consensus Side',
                'Contrarian Side',
                'Valuable Contrarians Count',
                'Top Contrarians',
                'Expected Value',
                'Uncertainty Score',
                'Smart Money Divergence',
                'Signal Strength'
            ])

            for rank, opp in enumerate(self.contrarian_opportunities, 1):
                contrarians_str = '; '.join(
                    f"{c['trader'][:12]}... (WR: {c['contrarian_win_rate']*100:.0f}%)"
                    for c in opp['valuable_contrarians'][:3]
                )

                writer.writerow([
                    rank,
                    opp['market_title'],
                    opp['category'],
                    f"{opp['disagreement_score']:.3f}",
                    opp['consensus_side'],
                    opp['contrarian_side'],
                    opp['valuable_contrarian_count'],
                    contrarians_str,
                    opp['expected_value'],
                    f"{opp['uncertainty_score']:.1f}",
                    'Yes' if opp['smart_money_divergence'] else 'No',
                    opp['signal_strength']
                ])

        print(f"  → {output_path}")

    def _generate_insights_txt(self, output_path: str):
        """Generate disagreement insights text report."""
        with open(output_path, 'w') as f:
            f.write("="*70 + "\n")
            f.write("CONSENSUS DIVERGENCE DETECTOR - INSIGHTS REPORT\n")
            f.write("="*70 + "\n\n")

            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Overall statistics
            if self.market_disagreements:
                avg_disagreement = statistics.mean(
                    d['disagreement_score'] for d in self.market_disagreements.values()
                )

                high_disagreement = sum(
                    1 for d in self.market_disagreements.values()
                    if d['disagreement_score'] > 0.60
                )

                low_disagreement = sum(
                    1 for d in self.market_disagreements.values()
                    if d['disagreement_score'] < 0.30
                )

                f.write("OVERALL DISAGREEMENT STATISTICS:\n")
                f.write(f"  Total Markets Analyzed: {len(self.market_disagreements)}\n")
                f.write(f"  Average Disagreement: {avg_disagreement:.3f}\n")
                f.write(f"  High Disagreement Markets (>0.60): {high_disagreement}\n")
                f.write(f"  Low Disagreement Markets (<0.30): {low_disagreement}\n\n")

                # Category breakdown
                category_disagreements = defaultdict(list)
                for data in self.market_disagreements.values():
                    category_disagreements[data['category']].append(data['disagreement_score'])

                f.write("CATEGORY BREAKDOWN:\n")
                for category, scores in sorted(category_disagreements.items()):
                    avg = statistics.mean(scores)
                    f.write(f"  {category}: {avg:.3f} avg disagreement ({len(scores)} markets)\n")
                f.write("\n")

            # Contrarian statistics
            if self.contrarian_traders:
                valuable_contrarians = [
                    t for t in self.contrarian_traders.values()
                    if t['is_valuable']
                ]

                f.write("CONTRARIAN TRADER STATISTICS:\n")
                f.write(f"  Total Traders Analyzed: {len(self.contrarian_traders)}\n")
                f.write(f"  Valuable Contrarians: {len(valuable_contrarians)}\n")

                if valuable_contrarians:
                    avg_contrarian_wr = statistics.mean(
                        t['contrarian_win_rate'] for t in valuable_contrarians
                    )
                    f.write(f"  Avg Contrarian Win Rate: {avg_contrarian_wr*100:.1f}%\n")

                # Contrarian type distribution
                type_counts = defaultdict(int)
                for trader_data in self.contrarian_traders.values():
                    type_counts[trader_data['contrarian_type']] += 1

                f.write("\n  Contrarian Type Distribution:\n")
                for ctype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
                    f.write(f"    {ctype}: {count} traders\n")
                f.write("\n")

            # Opportunities
            f.write("CONTRARIAN OPPORTUNITIES:\n")
            f.write(f"  Total Opportunities Detected: {len(self.contrarian_opportunities)}\n")

            if self.contrarian_opportunities:
                strong_signals = sum(
                    1 for o in self.contrarian_opportunities
                    if o['signal_strength'] == 'STRONG'
                )
                f.write(f"  Strong Signals: {strong_signals}\n")

                smart_money_count = sum(
                    1 for o in self.contrarian_opportunities
                    if o['smart_money_divergence']
                )
                f.write(f"  Smart Money Divergences: {smart_money_count}\n\n")

                f.write("  Top 5 Opportunities:\n")
                for i, opp in enumerate(self.contrarian_opportunities[:5], 1):
                    f.write(f"  {i}. {opp['market_title'][:60]}\n")
                    f.write(f"     Disagreement: {opp['disagreement_score']:.3f}\n")
                    f.write(f"     Contrarians: {opp['valuable_contrarian_count']}\n")
                    f.write(f"     Signal: {opp['signal_strength']}\n\n")

            # Most divided markets
            if self.market_disagreements:
                sorted_by_disagreement = sorted(
                    self.market_disagreements.values(),
                    key=lambda x: x['disagreement_score'],
                    reverse=True
                )

                f.write("MOST DIVIDED MARKETS:\n")
                for i, data in enumerate(sorted_by_disagreement[:5], 1):
                    f.write(f"  {i}. {data['market_title'][:60]}\n")
                    f.write(f"     Disagreement: {data['disagreement_score']:.3f}\n")
                    yes_pct = data['top_trader_split']['yes_pct'] * 100
                    no_pct = data['top_trader_split']['no_pct'] * 100
                    f.write(f"     Split: {yes_pct:.0f}% Yes, {no_pct:.0f}% No\n\n")

            f.write("="*70 + "\n")

        print(f"  → {output_path}")

    def display_dashboard(self):
        """Display divergence detector dashboard in terminal."""
        print("\n" + "="*70)
        print("  CONSENSUS DIVERGENCE DETECTOR - OPPORTUNITY DASHBOARD")
        print("="*70)

        # High disagreement markets
        high_disagreement = [
            (market_id, data) for market_id, data in self.market_disagreements.items()
            if data['disagreement_score'] > 0.60
        ]

        print("\n🎯 HIGH DISAGREEMENT MARKETS (Opportunities):")
        print("="*70)

        if high_disagreement:
            for market_id, data in high_disagreement[:5]:
                print(f"\nMarket: {data['market_title'][:60]}")
                print(f"Category: {data['category']}")

                disagreement = data['disagreement_score']
                classification, description = self.classify_market_by_disagreement(disagreement)
                print(f"→ Disagreement: {disagreement:.2f} ({classification})")

                yes_pct = data['top_trader_split']['yes_pct'] * 100
                no_pct = data['top_trader_split']['no_pct'] * 100
                print(f"→ Top Trader Split: {yes_pct:.0f}% Yes, {no_pct:.0f}% No")

                if data['specialist_split']['total'] > 0:
                    spec_yes = data['specialist_split']['yes_pct'] * 100
                    spec_no = data['specialist_split']['no_pct'] * 100
                    print(f"→ Specialist Split: {spec_yes:.0f}% Yes, {spec_no:.0f}% No")

                uncertainty = self.calculate_uncertainty_score(data)
                print(f"→ Uncertainty Score: {uncertainty:.0f}/100")

                # Check for smart money divergence
                smart_money = self.detect_smart_money_divergence(market_id, data)
                if smart_money:
                    print("→ 🔥 SMART MONEY DIVERGENCE: Top ELO traders betting against majority")

                # Check for contrarian signal
                market_opps = [
                    o for o in self.contrarian_opportunities
                    if o['market_id'] == market_id
                ]

                if market_opps:
                    opp = market_opps[0]
                    print(f"→ 🎯 CONTRARIAN SIGNAL: {opp['valuable_contrarian_count']} valuable contrarians")
                    for c in opp['valuable_contrarians'][:3]:
                        print(f"  • {c['trader'][:12]}... (Win Rate: {c['contrarian_win_rate']*100:.0f}%, betting {c['outcome']})")
                    print(f"→ SIGNAL: {opp['signal_strength']} CONTRARIAN OPPORTUNITY")
                    print(f"→ EXPECTED VALUE: {opp['expected_value']}")
                else:
                    print("→ No contrarian signal detected")

        else:
            print("  No high disagreement markets at this time")

        # Top contrarian traders
        print("\n" + "="*70)
        print("🏆 TOP CONTRARIAN TRADERS:")
        print("-"*70)

        if self.contrarian_traders:
            sorted_contrarians = sorted(
                self.contrarian_traders.items(),
                key=lambda x: x[1]['contrarian_win_rate'],
                reverse=True
            )[:10]

            print(f"{'Rank':<6}{'Address':<16}{'Type':<22}{'Win Rate':<12}{'ROI':<12}{'Bets':<8}")
            print("-"*70)

            for rank, (trader, data) in enumerate(sorted_contrarians, 1):
                addr_short = trader[:12] + "..."
                ctype_short = data['contrarian_type'][:20]
                wr = f"{data['contrarian_win_rate']*100:.1f}%"
                roi = f"+{data['contrarian_roi']:.1f}%" if data['contrarian_roi'] > 0 else f"{data['contrarian_roi']:.1f}%"
                bets = data['contrarian_bets']

                print(f"{rank:<6}{addr_short:<16}{ctype_short:<22}{wr:<12}{roi:<12}{bets:<8}")

        # Summary statistics
        print("\n" + "="*70)
        print("📊 DISAGREEMENT STATISTICS:")
        print("-"*70)

        if self.market_disagreements:
            avg_disagreement = statistics.mean(
                d['disagreement_score'] for d in self.market_disagreements.values()
            )

            high_count = sum(1 for d in self.market_disagreements.values() if d['disagreement_score'] > 0.60)
            low_count = sum(1 for d in self.market_disagreements.values() if d['disagreement_score'] < 0.30)

            print(f"Average Disagreement: {avg_disagreement:.3f}")
            print(f"Markets with High Disagreement (>0.60): {high_count}")
            print(f"Markets with Low Disagreement (<0.30): {low_count}")

            # Category breakdown
            print("\nCategory Breakdown:")
            category_scores = defaultdict(list)
            for data in self.market_disagreements.values():
                category_scores[data['category']].append(data['disagreement_score'])

            for category, scores in sorted(category_scores.items(), key=lambda x: statistics.mean(x[1]), reverse=True):
                avg = statistics.mean(scores)
                status = "(very divided)" if avg > 0.60 else "(divided)" if avg > 0.40 else "(clear favorites)"
                print(f"  {category}: {avg:.3f} avg disagreement {status}")

            # Smart money and opportunities
            smart_money_count = sum(
                1 for market_id, data in self.market_disagreements.items()
                if self.detect_smart_money_divergence(market_id, data)
            )

            print(f"\nSmart Money Divergences: {smart_money_count} markets")
            print(f"Contrarian Opportunities: {len(self.contrarian_opportunities)} markets")

        # Key insights
        print("\n💡 KEY INSIGHTS:")
        if self.contrarian_traders:
            valuable_contrarians = [t for t in self.contrarian_traders.values() if t['is_valuable']]

            if valuable_contrarians:
                avg_contrarian_wr = statistics.mean(t['contrarian_win_rate'] for t in valuable_contrarians)
                print(f"✅ Contrarians profitable: {avg_contrarian_wr*100:.1f}% avg win rate")

            selective_contrarians = [
                t for t in self.contrarian_traders.values()
                if t['contrarian_type'] == 'Selective Contrarian'
            ]

            if selective_contrarians:
                print(f"✅ {len(selective_contrarians)} selective contrarians identified")

        if self.contrarian_opportunities:
            strong_opps = [o for o in self.contrarian_opportunities if o['signal_strength'] == 'STRONG']
            print(f"🎯 {len(strong_opps)} STRONG contrarian signals available now")

        print("\n" + "="*70 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Consensus Divergence Detector')
    parser.add_argument('--market', type=str, help='Analyze specific market ID')
    parser.add_argument('--min-disagreement', type=float, default=0.0,
                       help='Minimum disagreement threshold (0-1)')

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

    # Initialize detector
    print("="*70)
    print("  CONSENSUS DIVERGENCE DETECTOR - CONTRARIAN OPPORTUNITIES")
    print("="*70)

    detector = ConsensusDivergenceDetector(api_key=api_key)

    # Run analyses
    detector.run_prerequisite_analyses()

    # Identify contrarian traders
    detector.contrarian_traders = detector.identify_contrarian_traders()

    # Analyze disagreement
    detector.analyze_all_markets()

    # Detect opportunities
    detector.detect_contrarian_opportunities()

    # Generate reports
    detector.generate_reports(reports_dir)

    # Display dashboard
    detector.display_dashboard()


if __name__ == "__main__":
    main()
