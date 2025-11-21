#!/usr/bin/env python3
"""
Trader Specialization Analysis System

Identifies category specialists and provides context-aware predictions based on
trader expertise in specific market categories.

Features:
1. Market Categorization - Auto-categorize markets (Elections, Geopolitics, etc.)
2. Category-Specific ELO - Separate ELO ratings per category for each trader
3. Specialist Identification - Identify specialists vs generalists
4. Context-Aware Consensus - Use specialist knowledge for predictions
5. Cross-Category Analysis - Correlation patterns between categories
6. Comprehensive Reporting - Multiple output formats
"""

import sqlite3
import requests
import csv
import os
import math
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
import time


# Market category keywords
CATEGORY_KEYWORDS = {
    'Elections': [
        'election', 'presidential', 'senate', 'congress', 'governor', 'mayor',
        'vote', 'ballot', 'candidate', 'primary', 'republican', 'democrat',
        'electoral', 'campaign', 'poll', 'swing state', 'biden', 'trump'
    ],
    'Geopolitics': [
        'war', 'conflict', 'ceasefire', 'invasion', 'military', 'nato',
        'ukraine', 'russia', 'gaza', 'israel', 'iran', 'china', 'taiwan',
        'sanctions', 'treaty', 'diplomatic', 'nuclear', 'peace deal',
        'territorial', 'sovereignty', 'alliance'
    ],
    'Economics': [
        'gdp', 'inflation', 'recession', 'fed', 'interest rate', 'unemployment',
        'stock', 'market', 'sp500', 's&p', 'dow', 'nasdaq', 'earnings',
        'ipo', 'merger', 'acquisition', 'bankruptcy', 'corporate', 'revenue'
    ],
    'Crypto': [
        'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain', 'nft',
        'defi', 'token', 'coin', 'satoshi', 'mining', 'wallet', 'exchange',
        'altcoin', 'binance', 'coinbase'
    ],
    'Sports': [
        'nfl', 'nba', 'mlb', 'nhl', 'fifa', 'super bowl', 'world cup',
        'championship', 'playoff', 'finals', 'game', 'match', 'team',
        'player', 'athlete', 'tournament', 'league', 'season', 'draft'
    ],
    'Entertainment': [
        'movie', 'film', 'oscar', 'emmy', 'grammy', 'album', 'song',
        'celebrity', 'actor', 'actress', 'director', 'box office',
        'netflix', 'disney', 'tv show', 'series', 'elon musk', 'tweet',
        'taylor swift', 'kardashian'
    ]
}


class CategorySpecificELO:
    """Manages category-specific ELO ratings for traders."""

    def __init__(self, starting_elo: int = 1500, k_factor: int = 32):
        self.starting_elo = starting_elo
        self.k_factor = k_factor

        # Structure: trader -> category -> ELO
        self.category_elos = defaultdict(lambda: defaultdict(lambda: starting_elo))

        # Track history: trader -> category -> list of updates
        self.category_history = defaultdict(lambda: defaultdict(list))

        # Track markets per category: trader -> category -> count
        self.category_market_counts = defaultdict(lambda: defaultdict(int))

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calculate expected score for player A vs player B."""
        return 1 / (1 + math.pow(10, (rating_b - rating_a) / 400))

    def update_rating(self, trader_address: str, category: str, actual_score: float,
                     opponent_rating: float, bet_size: float = 1.0,
                     market_difficulty: float = 1.0, timestamp: datetime = None):
        """
        Update trader's category-specific ELO rating.

        Args:
            trader_address: Trader's address
            category: Market category
            actual_score: 1.0 for win, 0.0 for loss
            opponent_rating: Average ELO of opposing traders in this category
            bet_size: Relative bet size
            market_difficulty: Market difficulty factor
            timestamp: When the update occurred
        """
        current_elo = self.category_elos[trader_address][category]
        expected = self.expected_score(current_elo, opponent_rating)

        # Adjust K-factor
        adjusted_k = self.k_factor * bet_size * market_difficulty

        # Calculate new rating
        new_elo = current_elo + adjusted_k * (actual_score - expected)

        # Update
        self.category_elos[trader_address][category] = new_elo
        self.category_market_counts[trader_address][category] += 1

        # Track history
        if timestamp:
            self.category_history[trader_address][category].append({
                'timestamp': timestamp,
                'old_elo': current_elo,
                'new_elo': new_elo,
                'change': new_elo - current_elo,
                'actual_score': actual_score,
                'expected_score': expected
            })

        return new_elo

    def get_category_elo(self, trader_address: str, category: str) -> float:
        """Get trader's ELO for specific category."""
        return self.category_elos[trader_address][category]

    def get_overall_elo(self, trader_address: str) -> float:
        """Calculate overall ELO as weighted average across categories."""
        if trader_address not in self.category_elos:
            return self.starting_elo

        total_weight = 0
        weighted_sum = 0

        for category, elo in self.category_elos[trader_address].items():
            markets_count = self.category_market_counts[trader_address][category]
            total_weight += markets_count
            weighted_sum += elo * markets_count

        if total_weight == 0:
            return self.starting_elo

        return weighted_sum / total_weight

    def get_market_count(self, trader_address: str, category: str) -> int:
        """Get number of markets trader participated in for category."""
        return self.category_market_counts[trader_address][category]

    def get_confidence_level(self, trader_address: str, category: str) -> str:
        """Determine confidence level for trader's category rating."""
        count = self.get_market_count(trader_address, category)

        if count >= 10:
            return "Established"
        elif count >= 5:
            return "Emerging"
        else:
            return "Insufficient Data"


class TraderSpecializationAnalyzer:
    """Analyzes trader specializations and provides context-aware predictions."""

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.api_key = api_key
        self.elo_system = CategorySpecificELO()
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

        # Cache
        self.market_resolutions = {}
        self.market_categories = {}  # market_id -> category

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def categorize_market(self, market_title: str, market_tags: str = "") -> str:
        """
        Categorize market based on title and tags.

        Returns category name or "Other" if no match.
        """
        search_text = f"{market_title} {market_tags}".lower()

        # Score each category
        category_scores = {}
        for category, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword.lower() in search_text)
            category_scores[category] = score

        # Return category with highest score, or "Other"
        max_score = max(category_scores.values())

        if max_score == 0:
            return "Other"

        return max(category_scores.items(), key=lambda x: x[1])[0]

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

    def calculate_category_elos(self, verbose: bool = False):
        """Calculate category-specific ELO ratings for all traders."""
        print("\n📊 Calculating category-specific ELO ratings...")

        trades = self.get_all_trades()
        print(f"Found {len(trades)} total trades")

        # Group trades by market
        market_trades = defaultdict(list)
        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        print(f"Categorizing {len(market_trades)} markets...")

        # Categorize markets
        for market_id, trades_list in market_trades.items():
            if trades_list:
                market_title = trades_list[0].get('market_title', '')
                category = self.categorize_market(market_title)
                self.market_categories[market_id] = category

        # Count markets per category
        category_counts = Counter(self.market_categories.values())
        print("\nMarket distribution by category:")
        for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {category}: {count} markets")

        print(f"\nChecking resolution status...")

        # Get resolutions
        resolved_markets = 0
        for i, market_id in enumerate(market_trades.keys(), 1):
            if i % 10 == 0:
                print(f"Progress: {i}/{len(market_trades)} markets checked", end='\r')
            resolution = self.get_market_resolution(market_id)
            if resolution.get('resolved'):
                resolved_markets += 1
            time.sleep(0.1)

        print(f"\nFound {resolved_markets} resolved markets")

        # Update category-specific ELOs
        print("\nUpdating category-specific ELO ratings...")
        updates_count = 0

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)
            if not resolution or not resolution.get('resolved'):
                continue

            winning_outcome = resolution.get('winning_outcome')
            if not winning_outcome:
                continue

            category = self.market_categories.get(market_id, 'Other')

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

            if winners and losers:
                # Get category-specific ELOs
                avg_winner_elo = sum(self.elo_system.get_category_elo(w['trader'], category) for w in winners) / len(winners)
                avg_loser_elo = sum(self.elo_system.get_category_elo(l['trader'], category) for l in losers) / len(losers)

                # Update winners
                for winner in winners:
                    normalized_bet_size = min(winner['bet_size'] / 100, 2.0)
                    market_difficulty = 1.0

                    self.elo_system.update_rating(
                        winner['trader'],
                        category,
                        actual_score=1.0,
                        opponent_rating=avg_loser_elo,
                        bet_size=normalized_bet_size,
                        market_difficulty=market_difficulty,
                        timestamp=winner['timestamp']
                    )
                    updates_count += 1

                # Update losers
                for loser in losers:
                    normalized_bet_size = min(loser['bet_size'] / 100, 2.0)
                    market_difficulty = 1.0

                    self.elo_system.update_rating(
                        loser['trader'],
                        category,
                        actual_score=0.0,
                        opponent_rating=avg_winner_elo,
                        bet_size=normalized_bet_size,
                        market_difficulty=market_difficulty,
                        timestamp=loser['timestamp']
                    )
                    updates_count += 1

        print(f"✅ Updated {updates_count} category-specific ratings\n")

    def identify_specialists(self) -> Dict:
        """
        Identify specialists vs generalists.

        Returns dict with trader classifications.
        """
        print("🔍 Identifying specialists and generalists...")

        trader_classifications = {}

        for trader_address in self.elo_system.category_elos.keys():
            overall_elo = self.elo_system.get_overall_elo(trader_address)

            # Get all category ELOs
            category_elos = {}
            established_categories = []

            for category in ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']:
                cat_elo = self.elo_system.get_category_elo(trader_address, category)
                market_count = self.elo_system.get_market_count(trader_address, category)
                confidence = self.elo_system.get_confidence_level(trader_address, category)

                category_elos[category] = {
                    'elo': cat_elo,
                    'count': market_count,
                    'confidence': confidence,
                    'specialization_score': ((cat_elo - overall_elo) / overall_elo * 100) if overall_elo > 0 else 0
                }

                if market_count >= 5:
                    established_categories.append(category)

            # Determine primary specialty
            if established_categories:
                primary_specialty = max(
                    established_categories,
                    key=lambda c: category_elos[c]['elo']
                )
            else:
                primary_specialty = "None"

            # Classify trader type
            if not established_categories:
                trader_type = "Insufficient Data"
            else:
                established_elos = [category_elos[c]['elo'] for c in established_categories]
                elo_range = max(established_elos) - min(established_elos)

                high_categories = [c for c in established_categories if category_elos[c]['elo'] > overall_elo + 100]
                low_categories = [c for c in established_categories if category_elos[c]['elo'] < overall_elo - 100]

                if len(high_categories) == 1 and len(low_categories) >= 2:
                    trader_type = "Specialist"
                elif len(high_categories) >= 2 and len(low_categories) >= 1:
                    trader_type = "Focused Expert"
                elif elo_range < 100:
                    trader_type = "Generalist"
                else:
                    trader_type = "Jack of All Trades"

            trader_classifications[trader_address] = {
                'overall_elo': overall_elo,
                'category_elos': category_elos,
                'primary_specialty': primary_specialty,
                'trader_type': trader_type,
                'established_categories': established_categories
            }

        print(f"Classified {len(trader_classifications)} traders\n")

        return trader_classifications

    def calculate_category_correlations(self, trader_classifications: Dict) -> Dict:
        """Calculate correlation between categories."""
        print("📈 Calculating cross-category correlations...")

        categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']
        correlations = {}

        # For each pair of categories
        for i, cat1 in enumerate(categories):
            for cat2 in categories[i+1:]:
                # Get traders with established ratings in both
                paired_elos = []

                for trader_data in trader_classifications.values():
                    cat_elos = trader_data['category_elos']

                    if (cat_elos[cat1]['count'] >= 5 and cat_elos[cat2]['count'] >= 5):
                        paired_elos.append((cat_elos[cat1]['elo'], cat_elos[cat2]['elo']))

                # Calculate correlation if enough data
                if len(paired_elos) >= 5:
                    # Simple Pearson correlation
                    n = len(paired_elos)
                    sum_x = sum(x for x, y in paired_elos)
                    sum_y = sum(y for x, y in paired_elos)
                    sum_xy = sum(x * y for x, y in paired_elos)
                    sum_x2 = sum(x * x for x, y in paired_elos)
                    sum_y2 = sum(y * y for x, y in paired_elos)

                    numerator = n * sum_xy - sum_x * sum_y
                    denominator = math.sqrt((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2))

                    if denominator != 0:
                        correlation = numerator / denominator
                    else:
                        correlation = 0.0

                    correlations[f"{cat1}-{cat2}"] = {
                        'correlation': correlation,
                        'sample_size': n
                    }

        print(f"Calculated {len(correlations)} category correlations\n")

        return correlations

    def generate_context_aware_predictions(self, trader_classifications: Dict) -> List[Dict]:
        """Generate predictions using specialist-weighted consensus."""
        print("🎯 Generating context-aware predictions...")

        trades = self.get_all_trades()
        market_trades = defaultdict(list)

        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        predictions = []

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)

            # Skip resolved markets
            if resolution and resolution.get('resolved'):
                continue

            category = self.market_categories.get(market_id, 'Other')
            market_title = trades_list[0].get('market_title', 'Unknown Market')

            # Calculate specialist-weighted consensus
            outcome_weights = defaultdict(float)
            trader_positions = {}
            specialist_votes = defaultdict(int)

            for trade in trades_list:
                trader = trade.get('trader_address')
                outcome = trade.get('outcome', 'Unknown')

                # Get category-specific ELO
                cat_elo = self.elo_system.get_category_elo(trader, category)

                # Check if specialist
                is_specialist = False
                if trader in trader_classifications:
                    trader_data = trader_classifications[trader]
                    if category in trader_data['established_categories']:
                        spec_score = trader_data['category_elos'][category]['specialization_score']
                        if spec_score > 10:  # >10% above overall
                            is_specialist = True
                            specialist_votes[outcome] += 1

                # Apply specialist boost
                weight = cat_elo * 1.2 if is_specialist else cat_elo

                outcome_weights[outcome] += weight
                trader_positions[trader] = outcome

            if not outcome_weights:
                continue

            # Sort outcomes by weight
            sorted_outcomes = sorted(outcome_weights.items(), key=lambda x: x[1], reverse=True)

            top_outcome = sorted_outcomes[0][0]
            top_weight = sorted_outcomes[0][1]
            second_weight = sorted_outcomes[1][1] if len(sorted_outcomes) > 1 else 0

            total_weight = sum(outcome_weights.values())

            # Calculate confidence
            if total_weight > 0:
                confidence = ((top_weight - second_weight) / total_weight) * 100
            else:
                confidence = 0

            # Check specialist consensus
            total_specialists = sum(specialist_votes.values())
            specialists_agree = specialist_votes.get(top_outcome, 0)

            specialist_consensus = specialists_agree >= 5 and total_specialists >= 8

            # Determine signal strength
            if specialist_consensus and confidence > 70:
                signal = "🔥 SPECIALIST CONSENSUS"
            elif confidence > 70:
                signal = "✅ STRONG"
            elif confidence > 50:
                signal = "⚠️ MODERATE"
            else:
                signal = "❌ WEAK"

            # Get top specialists on this market
            specialist_list = []
            for trader, outcome in trader_positions.items():
                if trader in trader_classifications:
                    trader_data = trader_classifications[trader]
                    if category in trader_data['established_categories']:
                        cat_elo = trader_data['category_elos'][category]['elo']
                        specialist_list.append((trader, cat_elo, outcome))

            specialist_list.sort(key=lambda x: x[1], reverse=True)
            top_3_specialists = specialist_list[:3]

            predictions.append({
                'market_id': market_id,
                'market_title': market_title,
                'category': category,
                'predicted_outcome': top_outcome,
                'confidence': confidence,
                'signal_strength': signal,
                'total_traders': len(trader_positions),
                'total_specialists': total_specialists,
                'specialists_agree': specialists_agree,
                'specialist_consensus': specialist_consensus,
                'top_specialists': top_3_specialists,
                'outcome_weights': dict(outcome_weights)
            })

        print(f"Generated predictions for {len(predictions)} active markets\n")

        return predictions

    def generate_reports(self, trader_classifications: Dict, predictions: List[Dict],
                        correlations: Dict, output_dir: str):
        """Generate all reports."""
        print("💾 Generating reports...")

        timestamp = datetime.now().strftime('%Y%m%d')

        # 1. Trader Specializations CSV
        self._generate_specializations_csv(
            trader_classifications,
            os.path.join(output_dir, f'trader_specializations_{timestamp}.csv')
        )

        # 2. Category Leaderboards CSV
        self._generate_leaderboards_csv(
            trader_classifications,
            os.path.join(output_dir, f'category_leaderboards_{timestamp}.csv')
        )

        # 3. Category Insights TXT
        self._generate_insights_txt(
            trader_classifications,
            correlations,
            os.path.join(output_dir, f'category_insights_{timestamp}.txt')
        )

        # 4. Context-Aware Predictions CSV
        self._generate_predictions_csv(
            predictions,
            os.path.join(output_dir, f'context_aware_predictions_{timestamp}.csv')
        )

        print("✅ All reports generated\n")

    def _generate_specializations_csv(self, trader_classifications: Dict, output_path: str):
        """Generate trader specializations CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Trader Address',
                'Overall ELO',
                'Elections ELO', 'Elections Count', 'Elections Confidence',
                'Geopolitics ELO', 'Geopolitics Count', 'Geopolitics Confidence',
                'Economics ELO', 'Economics Count', 'Economics Confidence',
                'Crypto ELO', 'Crypto Count', 'Crypto Confidence',
                'Sports ELO', 'Sports Count', 'Sports Confidence',
                'Entertainment ELO', 'Entertainment Count', 'Entertainment Confidence',
                'Primary Specialty',
                'Trader Type'
            ])

            # Sort by overall ELO
            sorted_traders = sorted(
                trader_classifications.items(),
                key=lambda x: x[1]['overall_elo'],
                reverse=True
            )

            for trader_address, data in sorted_traders:
                row = [
                    trader_address,
                    f"{data['overall_elo']:.2f}"
                ]

                for category in ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']:
                    cat_data = data['category_elos'][category]
                    row.extend([
                        f"{cat_data['elo']:.2f}",
                        cat_data['count'],
                        cat_data['confidence']
                    ])

                row.extend([
                    data['primary_specialty'],
                    data['trader_type']
                ])

                writer.writerow(row)

        print(f"  → {output_path}")

    def _generate_leaderboards_csv(self, trader_classifications: Dict, output_path: str):
        """Generate category leaderboards CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)

            categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']

            for category in categories:
                writer.writerow([])
                writer.writerow([f'=== {category.upper()} LEADERBOARD ==='])
                writer.writerow(['Rank', 'Trader Address', 'ELO', 'Markets', 'Confidence Level'])

                # Get traders with established ratings in this category
                category_traders = []

                for trader_address, data in trader_classifications.items():
                    cat_data = data['category_elos'][category]
                    if cat_data['count'] >= 5:
                        category_traders.append({
                            'address': trader_address,
                            'elo': cat_data['elo'],
                            'count': cat_data['count'],
                            'confidence': cat_data['confidence']
                        })

                # Sort by ELO
                category_traders.sort(key=lambda x: x['elo'], reverse=True)

                # Write top 20
                for i, trader in enumerate(category_traders[:20], 1):
                    writer.writerow([
                        i,
                        trader['address'],
                        f"{trader['elo']:.2f}",
                        trader['count'],
                        trader['confidence']
                    ])

        print(f"  → {output_path}")

    def _generate_insights_txt(self, trader_classifications: Dict, correlations: Dict,
                               output_path: str):
        """Generate category insights text report."""
        with open(output_path, 'w') as f:
            f.write("="*70 + "\n")
            f.write("CATEGORY INSIGHTS REPORT\n")
            f.write("="*70 + "\n\n")

            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Category statistics
            f.write("CATEGORY STATISTICS:\n")
            f.write("-"*70 + "\n")

            categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']

            for category in categories:
                specialists = sum(
                    1 for data in trader_classifications.values()
                    if data['primary_specialty'] == category and data['trader_type'] == 'Specialist'
                )

                established_traders = sum(
                    1 for data in trader_classifications.values()
                    if data['category_elos'][category]['count'] >= 5
                )

                if established_traders > 0:
                    avg_elo = sum(
                        data['category_elos'][category]['elo']
                        for data in trader_classifications.values()
                        if data['category_elos'][category]['count'] >= 5
                    ) / established_traders
                else:
                    avg_elo = 1500

                f.write(f"\n{category}:\n")
                f.write(f"  Established Traders: {established_traders}\n")
                f.write(f"  Specialists: {specialists}\n")
                f.write(f"  Average ELO: {avg_elo:.2f}\n")

            # Trader type distribution
            f.write("\n" + "="*70 + "\n")
            f.write("TRADER TYPE DISTRIBUTION:\n")
            f.write("-"*70 + "\n")

            type_counts = Counter(data['trader_type'] for data in trader_classifications.values())
            for trader_type, count in type_counts.most_common():
                percentage = (count / len(trader_classifications)) * 100
                f.write(f"  {trader_type}: {count} ({percentage:.1f}%)\n")

            # Category correlations
            f.write("\n" + "="*70 + "\n")
            f.write("CATEGORY CORRELATIONS:\n")
            f.write("-"*70 + "\n")

            for pair, data in sorted(correlations.items(), key=lambda x: x[1]['correlation'], reverse=True):
                corr = data['correlation']
                n = data['sample_size']

                if corr > 0.6:
                    strength = "Strong positive"
                elif corr > 0.3:
                    strength = "Moderate positive"
                elif corr > -0.3:
                    strength = "Weak/No"
                elif corr > -0.6:
                    strength = "Moderate negative"
                else:
                    strength = "Strong negative"

                f.write(f"  {pair}: {corr:.3f} ({strength}) [n={n}]\n")

            f.write("\n" + "="*70 + "\n")

        print(f"  → {output_path}")

    def _generate_predictions_csv(self, predictions: List[Dict], output_path: str):
        """Generate context-aware predictions CSV."""
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Market Title',
                'Category',
                'Predicted Outcome',
                'Confidence (%)',
                'Signal Strength',
                'Total Traders',
                'Total Specialists',
                'Specialists Agree',
                'Specialist Consensus',
                'Top Specialists'
            ])

            # Sort by confidence
            predictions.sort(key=lambda x: x['confidence'], reverse=True)

            for pred in predictions:
                top_specs = '; '.join(
                    f"{addr[:12]}... (ELO: {elo:.0f})"
                    for addr, elo, outcome in pred['top_specialists']
                )

                writer.writerow([
                    pred['market_title'],
                    pred['category'],
                    pred['predicted_outcome'],
                    f"{pred['confidence']:.2f}",
                    pred['signal_strength'],
                    pred['total_traders'],
                    pred['total_specialists'],
                    pred['specialists_agree'],
                    'Yes' if pred['specialist_consensus'] else 'No',
                    top_specs
                ])

        print(f"  → {output_path}")

    def display_terminal_report(self, trader_classifications: Dict, predictions: List[Dict],
                                correlations: Dict):
        """Display comprehensive terminal report."""
        print("\n" + "="*70)
        print("  TRADER SPECIALIZATION ANALYSIS")
        print("="*70 + "\n")

        # Category overview
        print("📊 CATEGORY OVERVIEW:")
        print("-"*70)
        print(f"{'Category':<18}{'Traders':<12}{'Specialists':<15}{'Avg ELO':<12}{'Difficulty'}")
        print("-"*70)

        categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']

        for category in categories:
            established = sum(
                1 for data in trader_classifications.values()
                if data['category_elos'][category]['count'] >= 5
            )

            specialists = sum(
                1 for data in trader_classifications.values()
                if data['primary_specialty'] == category and data['trader_type'] == 'Specialist'
            )

            if established > 0:
                avg_elo = sum(
                    data['category_elos'][category]['elo']
                    for data in trader_classifications.values()
                    if data['category_elos'][category]['count'] >= 5
                ) / established

                # Difficulty based on average ELO
                if avg_elo > 1650:
                    difficulty = "Low"
                elif avg_elo > 1600:
                    difficulty = "Medium"
                else:
                    difficulty = "High"
            else:
                avg_elo = 1500
                difficulty = "N/A"

            print(f"{category:<18}{established:<12}{specialists:<15}{avg_elo:>7.0f}{difficulty:>12}")

        # Top specialists by category
        print("\n🏆 TOP SPECIALISTS BY CATEGORY:")
        print("="*70)

        for category in categories:
            category_specialists = []

            for trader_address, data in trader_classifications.items():
                cat_data = data['category_elos'][category]
                if cat_data['count'] >= 5:
                    category_specialists.append({
                        'address': trader_address,
                        'elo': cat_data['elo'],
                        'count': cat_data['count'],
                        'confidence': cat_data['confidence']
                    })

            if category_specialists:
                category_specialists.sort(key=lambda x: x['elo'], reverse=True)

                print(f"\n{category.upper()}:")
                for i, spec in enumerate(category_specialists[:3], 1):
                    addr_short = spec['address'][:12] + "..."
                    print(f"  {i}. {addr_short} - ELO: {spec['elo']:.0f} ({spec['confidence']}) - {spec['count']} markets")

        # Specialist consensus signals
        specialist_signals = [p for p in predictions if p['specialist_consensus']]

        print("\n🎯 SPECIALIST CONSENSUS SIGNALS (Active Markets):")
        print("="*70)

        if specialist_signals:
            for pred in specialist_signals[:5]:  # Top 5
                print(f"\nMarket: {pred['market_title'][:60]}")
                print(f"Category: {pred['category']}")
                print(f"  → Predicted: {pred['predicted_outcome']} (Confidence: {pred['confidence']:.1f}%)")
                print(f"  → {pred['signal_strength']}")
                print(f"  → Specialists agree: {pred['specialists_agree']}/{pred['total_specialists']}")
                if pred['top_specialists']:
                    top_3 = ', '.join(addr[:12] + "..." for addr, _, _ in pred['top_specialists'][:3])
                    print(f"  → Top specialists: {top_3}")
        else:
            print("  No specialist consensus signals at this time")

        # Cross-category insights
        print("\n💡 CROSS-CATEGORY INSIGHTS:")
        print("="*70)

        # Show top correlations
        top_corrs = sorted(correlations.items(), key=lambda x: abs(x[1]['correlation']), reverse=True)[:5]

        for pair, data in top_corrs:
            corr = data['correlation']
            if corr > 0.5:
                relationship = "Strong skills transfer"
            elif corr > 0.3:
                relationship = "Moderate skills transfer"
            elif corr < -0.3:
                relationship = "Independent skills"
            else:
                relationship = "Weak correlation"

            print(f"  {pair}: {corr:.3f} correlation ({relationship})")

        # Hardest category
        hardest_cat = min(categories, key=lambda c: sum(
            data['category_elos'][c]['elo']
            for data in trader_classifications.values()
            if data['category_elos'][c]['count'] >= 5
        ) / max(1, sum(
            1 for data in trader_classifications.values()
            if data['category_elos'][c]['count'] >= 5
        )))

        print(f"\n  Hardest category: {hardest_cat}")

        print("\n" + "="*70 + "\n")


# Utility functions for integration
def get_trader_specialist_weight(analyzer: TraderSpecializationAnalyzer,
                                trader_address: str, category: str) -> float:
    """Get adjusted ELO weight for trader in specific category."""
    cat_elo = analyzer.elo_system.get_category_elo(trader_address, category)

    # Boost if specialist
    market_count = analyzer.elo_system.get_market_count(trader_address, category)
    overall_elo = analyzer.elo_system.get_overall_elo(trader_address)

    if market_count >= 5 and cat_elo > overall_elo + 100:
        return cat_elo * 1.2  # Specialist boost

    return cat_elo


def get_category_specialists(analyzer: TraderSpecializationAnalyzer,
                            category: str, min_markets: int = 5, top_n: int = 10) -> List[Tuple]:
    """Get top N specialists for a category."""
    specialists = []

    for trader_address in analyzer.elo_system.category_elos.keys():
        market_count = analyzer.elo_system.get_market_count(trader_address, category)

        if market_count >= min_markets:
            cat_elo = analyzer.elo_system.get_category_elo(trader_address, category)
            specialists.append((trader_address, cat_elo, market_count))

    specialists.sort(key=lambda x: x[1], reverse=True)

    return specialists[:top_n]


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Trader Specialization Analysis')
    parser.add_argument('--category', type=str, help='Filter by specific category')
    parser.add_argument('--trader', type=str, help='Analyze specific trader')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

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

    # Initialize analyzer
    print("="*70)
    print("  TRADER SPECIALIZATION ANALYSIS SYSTEM")
    print("="*70)

    analyzer = TraderSpecializationAnalyzer(api_key=api_key)

    # Calculate category-specific ELOs
    analyzer.calculate_category_elos(verbose=args.verbose)

    # Identify specialists
    trader_classifications = analyzer.identify_specialists()

    # Calculate correlations
    correlations = analyzer.calculate_category_correlations(trader_classifications)

    # Generate predictions
    predictions = analyzer.generate_context_aware_predictions(trader_classifications)

    # Generate reports
    analyzer.generate_reports(trader_classifications, predictions, correlations, reports_dir)

    # Display terminal report
    analyzer.display_terminal_report(trader_classifications, predictions, correlations)


if __name__ == "__main__":
    main()
