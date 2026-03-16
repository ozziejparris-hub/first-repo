#!/usr/bin/env python3
"""
Composite Skill Score System

The ultimate trader evaluation metric - synthesizes all analysis dimensions:
1. Category ELO (0-25 points) - Base trading skill
2. Forecasting Quality (0-25 points) - Calibration/Brier scores
3. Execution Quality (0-15 points) - Regret analysis
4. Consistency (0-15 points) - Sharpe ratios
5. Behavioral Profile (0-15 points) - Diversification, consistency, style
6. Network Independence (0-10 points) - Correlation analysis
7. Contrarian Bonus (+5 points) - Valuable contrarian skill
8. Copy-Trader Penalty (-20 points) - Follower exclusion

Total: 0-100 composite score

Tier Classification:
- 85-100: ELITE (Top 5%)
- 70-84: STRONG (Top 20%)
- 55-69: ABOVE AVERAGE (Top 40%)
- 40-54: AVERAGE (Middle 40%)
- 25-39: BELOW AVERAGE (Bottom 20%)
- 0-24: WEAK/NOISE (Bottom 5%)
"""

import os
import csv
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import statistics

from analysis.unified_elo_system import UnifiedELOSystem


class CompositeSkillScoreSystem:
    """Calculate composite skill scores for all traders."""

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        """
        Initialize Composite Skill Score System.

        Args:
            db_path: Path to database
            api_key: Polymarket API key
        """
        print("[COMPOSITE] Initializing Composite Skill Score System...")

        # Initialize unified ELO system (this loads all dimensions)
        self.unified_system = UnifiedELOSystem(db_path=db_path, api_key=api_key)

        # Cache for composite scores
        self.composite_scores = {}  # trader -> score_breakdown
        self.tier_classifications = {}  # trader -> tier

        print("[COMPOSITE] ✅ System initialized")

    def calculate_elo_component(self, trader_address: str) -> Dict:
        """
        Calculate ELO component (0-25 points).

        Uses best category ELO if specialist, weighted average if generalist.

        Scoring:
        - 2400+ ELO: 25 points (exceptional)
        - 2200-2399: 23 points (elite)
        - 2000-2199: 21 points (excellent)
        - 1800-1999: 19 points (very good)
        - 1700-1799: 17 points (good)
        - 1600-1699: 15 points (above average)
        - 1500-1599: 13 points (average)
        - 1400-1499: 11 points (below average)
        - 1300-1399: 9 points (poor)
        - 1200-1299: 7 points (weak)
        - <1200: 5 points (very weak)

        Returns:
            dict: {
                'points': float (0-25),
                'elo_used': float,
                'elo_type': str ('specialist' or 'generalist'),
                'best_category': str or None
            }
        """
        # Get global ELO (weighted average across categories)
        global_elo = self.unified_system.get_trader_global_elo(trader_address)

        # Check if specialist
        categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']
        category_elos = {}

        for category in categories:
            cat_elo = self.unified_system.elo_system.get_category_elo(trader_address, category)
            market_count = self.unified_system.elo_system.get_market_count(trader_address, category)

            if market_count >= 5:  # Established in category
                category_elos[category] = cat_elo

        # Determine if specialist
        if category_elos:
            best_category = max(category_elos.items(), key=lambda x: x[1])
            best_cat_name, best_cat_elo = best_category

            # Check if truly specialist (best category significantly higher than average)
            if best_cat_elo > global_elo + 100:
                elo_used = best_cat_elo
                elo_type = 'specialist'
                best_cat = best_cat_name
            else:
                elo_used = global_elo
                elo_type = 'generalist'
                best_cat = None
        else:
            elo_used = global_elo
            elo_type = 'generalist'
            best_cat = None

        # Convert ELO to points (0-25)
        if elo_used >= 2400:
            points = 25.0
        elif elo_used >= 2200:
            points = 23.0
        elif elo_used >= 2000:
            points = 21.0
        elif elo_used >= 1800:
            points = 19.0
        elif elo_used >= 1700:
            points = 17.0
        elif elo_used >= 1600:
            points = 15.0
        elif elo_used >= 1500:
            points = 13.0
        elif elo_used >= 1400:
            points = 11.0
        elif elo_used >= 1300:
            points = 9.0
        elif elo_used >= 1200:
            points = 7.0
        else:
            points = 5.0

        return {
            'points': points,
            'elo_used': round(elo_used, 0),
            'elo_type': elo_type,
            'best_category': best_cat
        }

    def calculate_forecasting_component(self, trader_address: str) -> Dict:
        """
        Calculate forecasting quality component (0-25 points).

        Based on Brier scores (calibration analysis).

        Scoring:
        - Brier 0.00-0.10: 25 points (exceptional)
        - Brier 0.10-0.15: 23 points (excellent)
        - Brier 0.15-0.20: 21 points (very good)
        - Brier 0.20-0.25: 18 points (good)
        - Brier 0.25-0.30: 15 points (above average)
        - Brier 0.30-0.35: 12 points (average)
        - Brier 0.35-0.40: 10 points (below average)
        - Brier 0.40-0.50: 7 points (poor)
        - Brier >0.50: 5 points (very poor)
        - No data: 13 points (default average)

        Returns:
            dict: {
                'points': float (0-25),
                'brier_score': float or None,
                'has_data': bool
            }
        """
        # Load advanced metrics if needed
        if not self.unified_system.calibration_cache:
            self.unified_system._load_advanced_metrics_data()

        # Get Brier score
        brier_score = self.unified_system.calibration_cache.get(trader_address)

        if brier_score is None:
            # No data - return default average
            return {
                'points': 13.0,
                'brier_score': None,
                'has_data': False
            }

        # Convert Brier to points
        if brier_score <= 0.10:
            points = 25.0
        elif brier_score <= 0.15:
            points = 23.0
        elif brier_score <= 0.20:
            points = 21.0
        elif brier_score <= 0.25:
            points = 18.0
        elif brier_score <= 0.30:
            points = 15.0
        elif brier_score <= 0.35:
            points = 12.0
        elif brier_score <= 0.40:
            points = 10.0
        elif brier_score <= 0.50:
            points = 7.0
        else:
            points = 5.0

        return {
            'points': points,
            'brier_score': round(brier_score, 4),
            'has_data': True
        }

    def calculate_execution_component(self, trader_address: str) -> Dict:
        """
        Calculate execution quality component (0-15 points).

        Based on regret rates (regret analysis).

        Scoring:
        - Regret 0-10%: 15 points (exceptional)
        - Regret 10-20%: 13 points (excellent)
        - Regret 20-30%: 11 points (very good)
        - Regret 30-40%: 9 points (good)
        - Regret 40-50%: 8 points (above average)
        - Regret 50-60%: 7 points (average)
        - Regret 60-70%: 5 points (below average)
        - Regret 70-80%: 3 points (poor)
        - Regret >80%: 2 points (very poor)
        - No data: 7 points (default average)

        Returns:
            dict: {
                'points': float (0-15),
                'regret_rate': float or None,
                'has_data': bool
            }
        """
        # Load advanced metrics if needed
        if not self.unified_system.regret_cache:
            self.unified_system._load_advanced_metrics_data()

        # Get regret rate
        regret_rate = self.unified_system.regret_cache.get(trader_address)

        if regret_rate is None:
            # No data - return default average
            return {
                'points': 7.0,
                'regret_rate': None,
                'has_data': False
            }

        # Convert regret to points
        if regret_rate <= 10:
            points = 15.0
        elif regret_rate <= 20:
            points = 13.0
        elif regret_rate <= 30:
            points = 11.0
        elif regret_rate <= 40:
            points = 9.0
        elif regret_rate <= 50:
            points = 8.0
        elif regret_rate <= 60:
            points = 7.0
        elif regret_rate <= 70:
            points = 5.0
        elif regret_rate <= 80:
            points = 3.0
        else:
            points = 2.0

        return {
            'points': points,
            'regret_rate': round(regret_rate, 2),
            'has_data': True
        }

    def calculate_consistency_component(self, trader_address: str) -> Dict:
        """
        Calculate consistency component (0-15 points).

        Based on Sharpe ratios (risk-adjusted returns).

        Scoring:
        - Sharpe >3.0: 15 points (exceptional)
        - Sharpe 2.5-3.0: 14 points (excellent)
        - Sharpe 2.0-2.5: 13 points (very good)
        - Sharpe 1.5-2.0: 11 points (good)
        - Sharpe 1.0-1.5: 9 points (above average)
        - Sharpe 0.5-1.0: 7 points (average)
        - Sharpe 0-0.5: 5 points (below average)
        - Sharpe <0: 3 points (poor)
        - No data: 7 points (default average)

        Returns:
            dict: {
                'points': float (0-15),
                'sharpe_ratio': float or None,
                'has_data': bool
            }
        """
        # Load advanced metrics if needed
        if not self.unified_system.sharpe_cache:
            self.unified_system._load_advanced_metrics_data()

        # Get Sharpe ratio
        sharpe_ratio = self.unified_system.sharpe_cache.get(trader_address)

        if sharpe_ratio is None:
            # No data - return default average
            return {
                'points': 7.0,
                'sharpe_ratio': None,
                'has_data': False
            }

        # Convert Sharpe to points
        if sharpe_ratio > 3.0:
            points = 15.0
        elif sharpe_ratio >= 2.5:
            points = 14.0
        elif sharpe_ratio >= 2.0:
            points = 13.0
        elif sharpe_ratio >= 1.5:
            points = 11.0
        elif sharpe_ratio >= 1.0:
            points = 9.0
        elif sharpe_ratio >= 0.5:
            points = 7.0
        elif sharpe_ratio >= 0.0:
            points = 5.0
        else:
            points = 3.0

        return {
            'points': points,
            'sharpe_ratio': round(sharpe_ratio, 3),
            'has_data': True
        }

    def calculate_behavioral_component(self, trader_address: str) -> Dict:
        """
        Calculate behavioral component (0-15 points).

        Based on diversification, consistency, and trading style.

        Sub-components:
        - Diversification (0-5 points)
        - Bet consistency (0-5 points)
        - Trading style (0-5 points)

        Returns:
            dict: {
                'points': float (0-15),
                'diversification_points': float (0-5),
                'consistency_points': float (0-5),
                'style_points': float (0-5),
                'has_data': bool
            }
        """
        # Load behavioral data if needed
        if not self.unified_system.behavior_cache:
            self.unified_system._load_behavioral_data()

        # Get behavioral data
        if trader_address not in self.unified_system.behavior_cache:
            # No data - return default average
            return {
                'points': 7.5,
                'diversification_points': 2.5,
                'consistency_points': 2.5,
                'style_points': 2.5,
                'has_data': False
            }

        trader_data = self.unified_system.behavior_cache[trader_address]

        # 1. Diversification points (0-5)
        div_score = trader_data.get('diversification_score', 50)
        if div_score >= 70:
            div_points = 5.0
        elif div_score >= 60:
            div_points = 4.0
        elif div_score >= 50:
            div_points = 3.5
        elif div_score >= 40:
            div_points = 3.0
        elif div_score >= 30:
            div_points = 2.5
        else:
            div_points = 2.0

        # 2. Bet consistency points (0-5)
        consistency_class = trader_data.get('bet_size_consistency', 'Variable')
        if consistency_class == 'Very Consistent':
            cons_points = 5.0
        elif consistency_class == 'Moderately Consistent':
            cons_points = 4.0
        elif consistency_class == 'Variable':
            cons_points = 3.0
        else:  # Highly Variable
            cons_points = 2.0

        # 3. Trading style points (0-5)
        style = trader_data.get('trading_style', 'General Trader')
        style_map = {
            'Power User': 5.0,
            'Active Trader': 4.5,
            'High Volume Specialist': 4.0,
            'Market Specialist': 4.0,
            'Strategic Explorer': 3.5,
            'Cautious Diversifier': 3.5,
            'General Trader': 3.0,
            'Big Better': 2.5,
            'Micro Trader': 2.5,
            'Weekend Warrior': 2.0,
            'Casual Trader': 2.0
        }
        style_points = style_map.get(style, 3.0)

        total_points = div_points + cons_points + style_points

        return {
            'points': round(total_points, 1),
            'diversification_points': div_points,
            'consistency_points': cons_points,
            'style_points': style_points,
            'has_data': True
        }

    def calculate_network_component(self, trader_address: str) -> Dict:
        """
        Calculate network independence component (0-10 points).

        Based on independence score from correlation analysis.

        Scoring:
        - Independence 90-100: 10 points (very independent)
        - Independence 80-89: 9 points (highly independent)
        - Independence 70-79: 8 points (independent)
        - Independence 60-69: 7 points (mostly independent)
        - Independence 50-59: 6 points (somewhat independent)
        - Independence 40-49: 5 points (neutral)
        - Independence 30-39: 4 points (some correlation)
        - Independence 20-29: 3 points (moderate correlation)
        - Independence 10-19: 2 points (high correlation)
        - Independence 0-9: 1 point (very high correlation)

        Returns:
            dict: {
                'points': float (0-10),
                'independence_score': int (0-100),
                'has_data': bool
            }
        """
        # Load network data if needed
        if not self.unified_system.independence_scores:
            self.unified_system._load_network_data()

        # Get independence score
        independence_score = self.unified_system.independence_scores.get(trader_address, 50)

        # Convert to points
        if independence_score >= 90:
            points = 10.0
        elif independence_score >= 80:
            points = 9.0
        elif independence_score >= 70:
            points = 8.0
        elif independence_score >= 60:
            points = 7.0
        elif independence_score >= 50:
            points = 6.0
        elif independence_score >= 40:
            points = 5.0
        elif independence_score >= 30:
            points = 4.0
        elif independence_score >= 20:
            points = 3.0
        elif independence_score >= 10:
            points = 2.0
        else:
            points = 1.0

        has_data = trader_address in self.unified_system.independence_scores

        return {
            'points': points,
            'independence_score': independence_score,
            'has_data': has_data
        }

    def calculate_contrarian_bonus(self, trader_address: str) -> Dict:
        """
        Calculate contrarian bonus (+0 to +5 points).

        Rewards valuable contrarians.

        Scoring:
        - Consistent Contrarian: +5 points
        - Selective Contrarian: +4 points
        - Valuable Contrarian (general): +3 points
        - Not contrarian: +0 points

        Returns:
            dict: {
                'points': float (0-5),
                'is_valuable': bool,
                'contrarian_type': str,
                'has_data': bool
            }
        """
        # Load contrarian data if needed
        if not self.unified_system.contrarian_traders:
            self.unified_system._load_contrarian_data()

        # Get contrarian data
        contrarian_data = self.unified_system.is_valuable_contrarian(trader_address)

        if not contrarian_data['is_valuable']:
            return {
                'points': 0.0,
                'is_valuable': False,
                'contrarian_type': contrarian_data['contrarian_type'],
                'has_data': trader_address in self.unified_system.contrarian_traders
            }

        # Award points based on type
        contrarian_type = contrarian_data['contrarian_type']

        if contrarian_type == 'Consistent Contrarian':
            points = 5.0
        elif contrarian_type == 'Selective Contrarian':
            points = 4.0
        else:  # Valuable but other type
            points = 3.0

        return {
            'points': points,
            'is_valuable': True,
            'contrarian_type': contrarian_type,
            'has_data': True
        }

    def calculate_copy_trader_penalty(self, trader_address: str) -> Dict:
        """
        Calculate copy-trader penalty (-0 to -20 points).

        Heavy penalty for identified copy-traders.

        Scoring:
        - Copy score >0.8: -20 points (definite copy-trader)
        - Copy score 0.7-0.8: -15 points (likely copy-trader)
        - Copy score 0.6-0.7: -10 points (possible copy-trader)
        - Copy score <0.6 or leader: -0 points

        Returns:
            dict: {
                'points': float (-20 to 0),
                'is_follower': bool,
                'copy_score': float,
                'has_data': bool
            }
        """
        # Load network data if needed
        if not self.unified_system.copy_relationships:
            self.unified_system._load_network_data()

        # Get copy-trader status
        copy_data = self.unified_system.is_copy_trader(trader_address)

        if not copy_data['is_follower']:
            return {
                'points': 0.0,
                'is_follower': False,
                'copy_score': 0.0,
                'has_data': trader_address in self.unified_system.copy_relationships
            }

        # Apply penalty based on copy score
        copy_score = copy_data['copy_score']

        if copy_score > 0.8:
            points = -20.0
        elif copy_score > 0.7:
            points = -15.0
        elif copy_score > 0.6:
            points = -10.0
        else:
            points = -5.0

        return {
            'points': points,
            'is_follower': True,
            'copy_score': round(copy_score, 3),
            'has_data': True
        }

    def calculate_composite_score(self, trader_address: str) -> Dict:
        """
        Calculate complete composite skill score (0-100).

        Combines all components:
        1. ELO (0-25)
        2. Forecasting (0-25)
        3. Execution (0-15)
        4. Consistency (0-15)
        5. Behavioral (0-15)
        6. Network (0-10)
        7. Contrarian bonus (+5)
        8. Copy-trader penalty (-20)

        Returns:
            dict: {
                'composite_score': int (0-100),
                'tier': str,
                'elo_component': dict,
                'forecasting_component': dict,
                'execution_component': dict,
                'consistency_component': dict,
                'behavioral_component': dict,
                'network_component': dict,
                'contrarian_bonus': dict,
                'copy_trader_penalty': dict,
                'breakdown': str
            }
        """
        # Calculate all components
        elo = self.calculate_elo_component(trader_address)
        forecasting = self.calculate_forecasting_component(trader_address)
        execution = self.calculate_execution_component(trader_address)
        consistency = self.calculate_consistency_component(trader_address)
        behavioral = self.calculate_behavioral_component(trader_address)
        network = self.calculate_network_component(trader_address)
        contrarian = self.calculate_contrarian_bonus(trader_address)
        copy_penalty = self.calculate_copy_trader_penalty(trader_address)

        # Calculate total
        total = (
            elo['points'] +
            forecasting['points'] +
            execution['points'] +
            consistency['points'] +
            behavioral['points'] +
            network['points'] +
            contrarian['points'] +
            copy_penalty['points']
        )

        # Clamp to [0, 100]
        composite_score = max(0, min(100, int(round(total))))

        # Determine tier
        tier = self.classify_tier(composite_score)

        # Build breakdown string
        breakdown = (
            f"ELO: {elo['points']:.0f}/25 | "
            f"Forecasting: {forecasting['points']:.0f}/25 | "
            f"Execution: {execution['points']:.0f}/15 | "
            f"Consistency: {consistency['points']:.0f}/15 | "
            f"Behavioral: {behavioral['points']:.0f}/15 | "
            f"Network: {network['points']:.0f}/10 | "
            f"Contrarian: +{contrarian['points']:.0f} | "
            f"Copy Penalty: {copy_penalty['points']:.0f} | "
            f"TOTAL: {composite_score}/100 ({tier})"
        )

        return {
            'composite_score': composite_score,
            'tier': tier,
            'elo_component': elo,
            'forecasting_component': forecasting,
            'execution_component': execution,
            'consistency_component': consistency,
            'behavioral_component': behavioral,
            'network_component': network,
            'contrarian_bonus': contrarian,
            'copy_trader_penalty': copy_penalty,
            'breakdown': breakdown
        }

    def classify_tier(self, composite_score: int) -> str:
        """
        Classify trader into tier based on composite score.

        Tiers:
        - 85-100: ELITE (Top 5%)
        - 70-84: STRONG (Top 20%)
        - 55-69: ABOVE AVERAGE (Top 40%)
        - 40-54: AVERAGE (Middle 40%)
        - 25-39: BELOW AVERAGE (Bottom 20%)
        - 0-24: WEAK/NOISE (Bottom 5%)

        Args:
            composite_score: Score (0-100)

        Returns:
            str: Tier classification
        """
        if composite_score >= 85:
            return "ELITE"
        elif composite_score >= 70:
            return "STRONG"
        elif composite_score >= 55:
            return "ABOVE AVERAGE"
        elif composite_score >= 40:
            return "AVERAGE"
        elif composite_score >= 25:
            return "BELOW AVERAGE"
        else:
            return "WEAK/NOISE"

    def rank_all_traders(self) -> List[Dict]:
        """
        Calculate composite scores for all traders and rank them.

        Returns:
            List[Dict]: Sorted list of traders with composite scores
        """
        print("\n[COMPOSITE] Calculating composite scores for all traders...")

        # Get all traders
        all_traders = list(self.unified_system.elo_system.category_elos.keys())

        print(f"[COMPOSITE] Analyzing {len(all_traders)} traders...")

        ranked_traders = []

        for idx, trader in enumerate(all_traders, 1):
            if idx % 50 == 0:
                print(f"[COMPOSITE] Progress: {idx}/{len(all_traders)} traders analyzed", end='\r')

            # Calculate composite score
            score_data = self.calculate_composite_score(trader)

            ranked_traders.append({
                'trader_address': trader,
                'composite_score': score_data['composite_score'],
                'tier': score_data['tier'],
                'elo_points': score_data['elo_component']['points'],
                'forecasting_points': score_data['forecasting_component']['points'],
                'execution_points': score_data['execution_component']['points'],
                'consistency_points': score_data['consistency_component']['points'],
                'behavioral_points': score_data['behavioral_component']['points'],
                'network_points': score_data['network_component']['points'],
                'contrarian_points': score_data['contrarian_bonus']['points'],
                'copy_penalty': score_data['copy_trader_penalty']['points'],
                'breakdown': score_data['breakdown']
            })

        # Sort by composite score (highest first)
        ranked_traders.sort(key=lambda x: x['composite_score'], reverse=True)

        # Add ranks
        for rank, trader in enumerate(ranked_traders, 1):
            trader['rank'] = rank

        print(f"\n[COMPOSITE] ✅ Ranked {len(ranked_traders)} traders")

        return ranked_traders

    def generate_composite_score_report(self, output_dir: str = 'reports') -> str:
        """
        Generate comprehensive composite score report.

        Creates CSV: composite_scores_YYYYMMDD.csv

        Returns:
            str: Path to report file
        """
        print("\n[COMPOSITE] Generating composite score report...")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Get ranked traders
        ranked_traders = self.rank_all_traders()

        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d')
        filename = os.path.join(output_dir, f'composite_scores_{timestamp}.csv')

        # Write CSV
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Rank',
                'Trader Address',
                'Composite Score',
                'Tier',
                'ELO Points (0-25)',
                'Forecasting Points (0-25)',
                'Execution Points (0-15)',
                'Consistency Points (0-15)',
                'Behavioral Points (0-15)',
                'Network Points (0-10)',
                'Contrarian Bonus (0-5)',
                'Copy Penalty (-20-0)',
                'Breakdown'
            ])

            # Data rows
            for trader in ranked_traders:
                writer.writerow([
                    trader['rank'],
                    trader['trader_address'],
                    trader['composite_score'],
                    trader['tier'],
                    f"{trader['elo_points']:.1f}",
                    f"{trader['forecasting_points']:.1f}",
                    f"{trader['execution_points']:.1f}",
                    f"{trader['consistency_points']:.1f}",
                    f"{trader['behavioral_points']:.1f}",
                    f"{trader['network_points']:.1f}",
                    f"{trader['contrarian_points']:.1f}",
                    f"{trader['copy_penalty']:.1f}",
                    trader['breakdown']
                ])

        print(f"[COMPOSITE] ✅ Report saved: {filename}")

        return filename

    def display_top_traders_dashboard(self, top_n: int = 20):
        """
        Display top N traders in terminal dashboard format.

        Args:
            top_n: Number of top traders to display
        """
        print("\n" + "="*80)
        print(f"{'COMPOSITE SKILL SCORE - TOP TRADERS DASHBOARD':^80}")
        print("="*80)

        # Get ranked traders
        ranked_traders = self.rank_all_traders()

        # Tier distribution
        tier_counts = defaultdict(int)
        for trader in ranked_traders:
            tier_counts[trader['tier']] += 1

        print(f"\n📊 TIER DISTRIBUTION (Total: {len(ranked_traders)} traders):")
        print(f"   ELITE (85-100): {tier_counts['ELITE']} ({tier_counts['ELITE']/len(ranked_traders)*100:.1f}%)")
        print(f"   STRONG (70-84): {tier_counts['STRONG']} ({tier_counts['STRONG']/len(ranked_traders)*100:.1f}%)")
        print(f"   ABOVE AVERAGE (55-69): {tier_counts['ABOVE AVERAGE']} ({tier_counts['ABOVE AVERAGE']/len(ranked_traders)*100:.1f}%)")
        print(f"   AVERAGE (40-54): {tier_counts['AVERAGE']} ({tier_counts['AVERAGE']/len(ranked_traders)*100:.1f}%)")
        print(f"   BELOW AVERAGE (25-39): {tier_counts['BELOW AVERAGE']} ({tier_counts['BELOW AVERAGE']/len(ranked_traders)*100:.1f}%)")
        print(f"   WEAK/NOISE (0-24): {tier_counts['WEAK/NOISE']} ({tier_counts['WEAK/NOISE']/len(ranked_traders)*100:.1f}%)")

        # Top traders
        print(f"\n🏆 TOP {top_n} TRADERS:")
        print("="*80)
        print(f"{'Rank':<6}{'Address':<16}{'Score':<8}{'Tier':<18}{'ELO':<7}{'Forecast':<9}{'Exec':<7}{'Consist':<9}")
        print("-"*80)

        for trader in ranked_traders[:top_n]:
            addr_short = trader['trader_address'][:12] + "..."

            print(f"{trader['rank']:<6}"
                  f"{addr_short:<16}"
                  f"{trader['composite_score']:<8}"
                  f"{trader['tier']:<18}"
                  f"{trader['elo_points']:<7.0f}"
                  f"{trader['forecasting_points']:<9.0f}"
                  f"{trader['execution_points']:<7.0f}"
                  f"{trader['consistency_points']:<9.0f}")

        print("\n" + "="*80 + "\n")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Composite Skill Score System')
    parser.add_argument('--top', type=int, default=20, help='Number of top traders to display')
    parser.add_argument('--output-dir', type=str, default='reports', help='Output directory for reports')

    args = parser.parse_args()

    print("="*80)
    print("  COMPOSITE SKILL SCORE SYSTEM")
    print("="*80)

    # Initialize system
    system = CompositeSkillScoreSystem()

    # Generate report
    report_path = system.generate_composite_score_report(output_dir=args.output_dir)

    # Display dashboard
    system.display_top_traders_dashboard(top_n=args.top)

    print(f"✅ Composite score analysis complete!")
    print(f"📄 Full report: {report_path}\n")


if __name__ == "__main__":
    main()
