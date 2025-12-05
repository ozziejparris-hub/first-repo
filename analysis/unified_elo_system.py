#!/usr/bin/env python3
"""
Unified ELO Rating System for Polymarket Traders

Consolidates and extends the two previous ELO implementations:
1. weighted_consensus_system.py - basic global ELO
2. trader_specialization_analysis.py - category-specific ELO

This system uses CategorySpecificELO as the core engine and provides:
- Per-category ELO ratings (Elections, Geopolitics, Economics, etc.)
- Global ELO ratings (weighted average across categories)
- Specialist identification and scoring
- Export methods for integration with other analysis tools
- Backward compatibility with existing code

Category-specific ratings are more accurate because traders may excel in
specific domains (e.g., Elections) while performing poorly in others (e.g., Crypto).
"""

import sqlite3
import requests
import os
import math
import csv
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
import time

# Import behavioral analysis
from trading_behavior_analysis import TradingBehaviorAnalyzer

# Import advanced metrics analyzers
from calibration_analysis import CalibrationAnalyzer
from risk_adjusted_returns import RiskAdjustedAnalyzer
from regret_analysis import RegretAnalyzer

# Import network analysis
from correlation_matrix import TraderCorrelationMatrix
from copy_trade_detector import CopyTradeDetector


# Market category keywords for auto-categorization
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

ALL_CATEGORIES = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment', 'Other']


class CategorySpecificELO:
    """
    Core ELO engine that manages category-specific ratings.

    This is the foundation of the unified system, providing separate ELO ratings
    for each market category. Traders can excel in specific domains while
    performing poorly in others.
    """

    def __init__(self, starting_elo: int = 1500, k_factor: int = 32):
        """
        Initialize the category-specific ELO system.

        Args:
            starting_elo: Initial ELO rating for all traders (default: 1500)
            k_factor: ELO K-factor controlling rating volatility (default: 32)
        """
        self.starting_elo = starting_elo
        self.k_factor = k_factor

        # Structure: trader -> category -> ELO
        self.category_elos = defaultdict(lambda: defaultdict(lambda: starting_elo))

        # Track history: trader -> category -> list of updates
        self.category_history = defaultdict(lambda: defaultdict(list))

        # Track markets per category: trader -> category -> count
        self.category_market_counts = defaultdict(lambda: defaultdict(int))

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """
        Calculate expected score for player A vs player B using ELO formula.

        Args:
            rating_a: ELO rating of player A
            rating_b: ELO rating of player B

        Returns:
            Expected score (0.0 to 1.0) for player A
        """
        return 1 / (1 + math.pow(10, (rating_b - rating_a) / 400))

    def update_rating(self, trader_address: str, category: str, actual_score: float,
                     opponent_rating: float, bet_size: float = 1.0,
                     market_difficulty: float = 1.0, timestamp: datetime = None):
        """
        Update trader's category-specific ELO rating based on outcome.

        Args:
            trader_address: Trader's address
            category: Market category (e.g., 'Elections', 'Crypto')
            actual_score: 1.0 for win, 0.0 for loss, 0.5 for draw
            opponent_rating: Average ELO of opposing traders in this category
            bet_size: Relative bet size (larger = more confidence = bigger swings)
            market_difficulty: Market difficulty factor (low liquidity = harder)
            timestamp: When the update occurred (for history tracking)

        Returns:
            New ELO rating for this category
        """
        current_elo = self.category_elos[trader_address][category]
        expected = self.expected_score(current_elo, opponent_rating)

        # Adjust K-factor based on bet size and market difficulty
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
        """
        Get trader's ELO for specific category.

        Args:
            trader_address: Trader's address
            category: Market category

        Returns:
            ELO rating for this category (defaults to starting_elo if no trades)
        """
        return self.category_elos[trader_address][category]

    def get_overall_elo(self, trader_address: str) -> float:
        """
        Calculate overall ELO as weighted average across all categories.

        Categories with more markets are weighted more heavily.

        Args:
            trader_address: Trader's address

        Returns:
            Weighted average ELO across all categories
        """
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
        """
        Get number of markets trader participated in for category.

        Args:
            trader_address: Trader's address
            category: Market category

        Returns:
            Number of markets in this category
        """
        return self.category_market_counts[trader_address][category]

    def get_confidence_level(self, trader_address: str, category: str) -> str:
        """
        Determine confidence level for trader's category rating.

        Based on number of markets traded:
        - Established: 10+ markets
        - Emerging: 5-9 markets
        - Insufficient Data: <5 markets

        Args:
            trader_address: Trader's address
            category: Market category

        Returns:
            Confidence level string
        """
        count = self.get_market_count(trader_address, category)

        if count >= 10:
            return "Established"
        elif count >= 5:
            return "Emerging"
        else:
            return "Insufficient Data"

    def get_all_traders(self) -> List[str]:
        """
        Get list of all trader addresses with ELO ratings.

        Returns:
            List of trader addresses
        """
        return list(self.category_elos.keys())

    def get_trader_categories(self, trader_address: str) -> List[str]:
        """
        Get list of categories where trader has participated.

        Args:
            trader_address: Trader's address

        Returns:
            List of category names
        """
        if trader_address not in self.category_elos:
            return []
        return list(self.category_elos[trader_address].keys())


class UnifiedELOSystem:
    """
    Unified ELO rating system that provides both category-specific and global ratings.

    This is the main interface for ELO calculations and integrations.
    Uses CategorySpecificELO as the core engine.
    """

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        """
        Initialize the unified ELO system.

        Args:
            db_path: Path to SQLite database (defaults to standard location)
            api_key: Polymarket API key (optional, for market resolution checks)
        """
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.api_key = api_key

        # Core ELO engine
        self.elo_system = CategorySpecificELO()

        # Polymarket API setup
        self.base_url = "https://gamma-api.polymarket.com"
        self.session = requests.Session()

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
        self.specialist_cache = {}  # trader_address -> specialist data

        # Behavioral analysis integration
        self.behavior_analyzer = TradingBehaviorAnalyzer(db_path=self.db_path)
        self.behavior_cache = {}  # trader_address -> behavioral metrics
        self.behavior_cache_timestamp = None

        # Advanced metrics analyzers
        self.calibration_analyzer = CalibrationAnalyzer(db_path=self.db_path, api_key=self.api_key)
        self.risk_analyzer = RiskAdjustedAnalyzer(db_path=self.db_path, api_key=self.api_key)
        self.regret_analyzer = RegretAnalyzer(db_path=self.db_path, api_key=self.api_key)

        # Cache for advanced metrics
        self.calibration_cache = {}  # trader -> brier_score
        self.sharpe_cache = {}  # trader -> sharpe_ratio
        self.regret_cache = {}  # trader -> regret_rate
        self.advanced_metrics_timestamp = None  # Last cache refresh

        # Network analysis components
        self.correlation_analyzer = TraderCorrelationMatrix(db_path=self.db_path)
        self.copy_detector = CopyTradeDetector(db_path=self.db_path)

        # Cache for network data
        self.independence_scores = {}  # trader -> independence_score (0-100)
        self.copy_relationships = {}  # trader -> {is_follower, is_leader, leaders, followers}
        self.correlation_clusters = []  # List of correlation clusters
        self.avg_correlations = {}  # trader -> avg_correlation with others
        self.network_cache_timestamp = None  # Last cache refresh

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def categorize_market(self, market_title: str, market_category: str = None) -> str:
        """
        Categorize market based on title and category field.

        If market_category is provided from database, use it.
        Otherwise, auto-categorize based on keywords in title.

        Args:
            market_title: Market title/question
            market_category: Category from database (optional)

        Returns:
            Category name (one of: Elections, Geopolitics, Economics, Crypto, Sports, Entertainment, Other)
        """
        # If category provided from database, use it
        if market_category and market_category != 'Unknown':
            # Map database categories to our standard categories
            cat_lower = market_category.lower()
            if 'election' in cat_lower or 'politic' in cat_lower:
                return 'Elections'
            elif 'geo' in cat_lower or 'war' in cat_lower or 'conflict' in cat_lower:
                return 'Geopolitics'
            elif 'econ' in cat_lower or 'finance' in cat_lower or 'business' in cat_lower:
                return 'Economics'
            elif 'crypto' in cat_lower or 'blockchain' in cat_lower:
                return 'Crypto'
            elif 'sport' in cat_lower:
                return 'Sports'
            elif 'entertainment' in cat_lower or 'pop culture' in cat_lower:
                return 'Entertainment'
            else:
                # Fall through to keyword-based categorization
                pass

        # Auto-categorize based on keywords in title
        search_text = market_title.lower()

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
        """
        Get market resolution status from Polymarket API.

        Args:
            market_id: Market identifier

        Returns:
            Dict with resolution info (resolved, winning_outcome, etc.)
        """
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

    def calculate_elo_ratings(self, verbose: bool = True):
        """
        Calculate category-specific ELO ratings for all traders based on historical trades.

        This is the main method to run after initializing the system.

        Args:
            verbose: Print progress messages
        """
        if verbose:
            print("\n" + "="*70)
            print("  UNIFIED ELO SYSTEM - CALCULATING RATINGS")
            print("="*70)
            print("\nLoading historical trades...")

        trades = self.get_all_trades()
        if verbose:
            print(f"Found {len(trades)} total trades")

        # Group trades by market
        market_trades = defaultdict(list)
        for trade in trades:
            market_id = trade.get('market_id')
            if market_id:
                market_trades[market_id].append(trade)

        if verbose:
            print(f"Checking resolution status for {len(market_trades)} markets...")

        # Get resolutions for all markets
        resolved_markets = 0
        for i, market_id in enumerate(market_trades.keys(), 1):
            if verbose and i % 10 == 0:
                print(f"Progress: {i}/{len(market_trades)} markets checked", end='\r')
            resolution = self.get_market_resolution(market_id)
            if resolution.get('resolved'):
                resolved_markets += 1
            time.sleep(0.1)  # Rate limiting

        if verbose:
            print(f"\nFound {resolved_markets} resolved markets")
            print("\nUpdating category-specific ELO ratings...")

        # Process each resolved market to update category-specific ELO
        updates_count = 0
        category_updates = defaultdict(int)

        for market_id, trades_list in market_trades.items():
            resolution = self.market_resolutions.get(market_id)
            if not resolution or not resolution.get('resolved'):
                continue

            winning_outcome = resolution.get('winning_outcome')
            if not winning_outcome:
                continue

            # Determine market category
            if trades_list:
                market_title = trades_list[0].get('market_title', '')
                market_cat = trades_list[0].get('market_category')
                category = self.categorize_market(market_title, market_cat)
                self.market_categories[market_id] = category
            else:
                continue

            # Separate winners and losers
            winners = []
            losers = []

            for trade in trades_list:
                outcome = str(trade.get('outcome', '')).lower()
                if outcome == winning_outcome:
                    winners.append(trade)
                else:
                    losers.append(trade)

            # Calculate average ELO for each group (within this category)
            winner_elos = [self.elo_system.get_category_elo(w.get('trader_address'), category) for w in winners]
            loser_elos = [self.elo_system.get_category_elo(l.get('trader_address'), category) for l in losers]

            avg_winner_elo = sum(winner_elos) / len(winner_elos) if winner_elos else 1500
            avg_loser_elo = sum(loser_elos) / len(loser_elos) if loser_elos else 1500

            # Update winners (they beat the losers)
            for winner in winners:
                trader_address = winner.get('trader_address')
                shares = float(winner.get('shares', 1))

                # Normalize bet size
                all_shares = [float(w.get('shares', 1)) for w in winners + losers]
                max_shares = max(all_shares) if all_shares else 1
                normalized_bet_size = min(shares / max_shares, 2.0) if max_shares > 0 else 1.0

                # Market difficulty (fewer traders = harder market)
                total_traders = len(set([t.get('trader_address') for t in trades_list]))
                market_difficulty = max(0.5, min(1.5, 1.0 + (10 - total_traders) / 20))

                self.elo_system.update_rating(
                    trader_address=trader_address,
                    category=category,
                    actual_score=1.0,  # Win
                    opponent_rating=avg_loser_elo,
                    bet_size=normalized_bet_size,
                    market_difficulty=market_difficulty,
                    timestamp=winner.get('timestamp')
                )
                updates_count += 1
                category_updates[category] += 1

            # Update losers (they lost to the winners)
            for loser in losers:
                trader_address = loser.get('trader_address')
                shares = float(loser.get('shares', 1))

                all_shares = [float(w.get('shares', 1)) for w in winners + losers]
                max_shares = max(all_shares) if all_shares else 1
                normalized_bet_size = min(shares / max_shares, 2.0) if max_shares > 0 else 1.0

                total_traders = len(set([t.get('trader_address') for t in trades_list]))
                market_difficulty = max(0.5, min(1.5, 1.0 + (10 - total_traders) / 20))

                self.elo_system.update_rating(
                    trader_address=trader_address,
                    category=category,
                    actual_score=0.0,  # Loss
                    opponent_rating=avg_winner_elo,
                    bet_size=normalized_bet_size,
                    market_difficulty=market_difficulty,
                    timestamp=loser.get('timestamp')
                )
                updates_count += 1
                category_updates[category] += 1

        if verbose:
            print(f"✅ Updated {updates_count} category-specific ratings")
            print("\nRatings by category:")
            for category in sorted(category_updates.keys()):
                print(f"  {category}: {category_updates[category]} rating updates")
            print()

    # ==================== BEHAVIORAL MODIFIERS ====================

    def _load_behavioral_data(self, force_refresh: bool = False):
        """
        Load behavioral data for all traders (with caching).

        Behavioral data is cached for 24 hours to avoid repeated expensive analysis.

        Args:
            force_refresh: Force reload even if cache is valid

        Returns:
            Dict mapping trader_address to behavioral metrics
        """
        # Check if cache is stale (>24 hours old)
        cache_age = None
        if self.behavior_cache_timestamp:
            cache_age = (datetime.now() - self.behavior_cache_timestamp).total_seconds()

        if force_refresh or self.behavior_cache_timestamp is None or cache_age > 86400:
            print("[BEHAVIORAL] Loading trader behavioral data...")
            try:
                behavior_metrics = self.behavior_analyzer.analyze_all_traders(days_filter=None)
                self.behavior_cache = behavior_metrics
                self.behavior_cache_timestamp = datetime.now()
                print(f"[BEHAVIORAL] Loaded data for {len(behavior_metrics)} traders")
            except Exception as e:
                print(f"[BEHAVIORAL] WARNING: Failed to load behavioral data: {e}")
                print("[BEHAVIORAL] Continuing with neutral behavioral multipliers")
                self.behavior_cache = {}
        else:
            print(f"[BEHAVIORAL] Using cached behavioral data (age: {cache_age/3600:.1f} hours)")

        return self.behavior_cache

    def calculate_consistency_modifier(self, trader_address: str) -> float:
        """
        Calculate consistency modifier based on bet size consistency.

        Consistent traders are more reliable - their ELO represents true skill
        rather than lucky variance.

        Args:
            trader_address: Trader's address

        Returns:
            Multiplier (0.92-1.10) based on consistency
            - 1.10: Very Consistent (disciplined, reliable)
            - 1.05: Moderately Consistent (mostly consistent)
            - 0.98: Variable (some inconsistency)
            - 0.92: Highly Variable (chaotic, less reliable)
            - 1.00: Unknown/Insufficient data

        Examples:
            Very Consistent trader (CV < 30%) → 1.10x
            Highly Variable trader (CV > 100%) → 0.92x
        """
        behavior_data = self._load_behavioral_data()

        if trader_address not in behavior_data:
            return 1.0

        trader_behavior = behavior_data[trader_address]
        consistency = trader_behavior.get('bet_size_consistency', 'N/A')
        cv = trader_behavior.get('coefficient_of_variation', 0)

        # Base modifier from consistency classification
        if consistency == "Very Consistent":
            modifier = 1.10
        elif consistency == "Moderately Consistent":
            modifier = 1.05
        elif consistency == "Variable":
            modifier = 0.98
        elif consistency == "Highly Variable":
            modifier = 0.92
        else:
            modifier = 1.00

        # Apply CV-based adjustments
        if cv > 0:
            if cv < 20:  # Extremely tight betting
                modifier *= 1.03
            elif cv > 150:  # Extremely erratic
                modifier *= 0.97

        return modifier

    def calculate_diversification_modifier(self, trader_address: str) -> float:
        """
        Calculate diversification modifier based on market spread.

        Well-diversified traders are less vulnerable to category-specific luck
        and demonstrate broader skill.

        Args:
            trader_address: Trader's address

        Returns:
            Multiplier (0.93-1.08) based on diversification
            - 1.08: Excellent diversification (≥70%)
            - 1.05: Good diversification (60-69%)
            - 1.02: Moderate diversification (40-59%)
            - 1.00: Neutral (30-39%)
            - 0.97: Concentrated (20-29%)
            - 0.93: Very concentrated (<20%, vulnerable to luck)
            - 1.00: Unknown

        Examples:
            Well diversified (75% unique markets) → 1.08x
            Highly concentrated (15% unique markets) → 0.93x
        """
        behavior_data = self._load_behavioral_data()

        if trader_address not in behavior_data:
            return 1.0

        trader_behavior = behavior_data[trader_address]
        div_score = trader_behavior.get('diversification_score', 0)
        concentration = trader_behavior.get('market_concentration', 'N/A')

        # Base modifier from diversification score
        if div_score >= 70:
            modifier = 1.08
        elif div_score >= 60:
            modifier = 1.05
        elif div_score >= 40:
            modifier = 1.02
        elif div_score >= 30:
            modifier = 1.00
        elif div_score >= 20:
            modifier = 0.97
        else:
            modifier = 0.93

        # Apply concentration-based adjustments
        if concentration == "Well Diversified":
            modifier *= 1.02
        elif concentration == "Highly Concentrated":
            modifier *= 0.98

        return modifier

    def calculate_trading_style_modifier(self, trader_address: str) -> float:
        """
        Calculate trading style modifier based on behavioral classification.

        Different trading styles indicate different levels of sophistication
        and engagement with the platform.

        Args:
            trader_address: Trader's address

        Returns:
            Multiplier (0.92-1.12) based on trading style
            - 1.12: Power User (sophisticated, high engagement)
            - 1.08: Active Trader (active, engaged)
            - 1.06: High Volume Specialist (focused, disciplined)
            - 1.05: Market Specialist (niche expertise)
            - 1.03: Strategic Explorer (thoughtful diversification)
            - 1.02: Cautious Diversifier (risk-aware)
            - 1.00: General Trader (neutral)
            - 0.98: Big Better (higher variance, possible overconfidence)
            - 0.96: Micro Trader (limited capital, less conviction)
            - 0.94: Weekend Warrior (casual, less engaged)
            - 0.92: Casual Trader (low engagement)
            - 1.00: Unknown

        Examples:
            Power User → 1.12x
            Casual Trader → 0.92x
        """
        behavior_data = self._load_behavioral_data()

        if trader_address not in behavior_data:
            return 1.0

        trader_behavior = behavior_data[trader_address]
        style = trader_behavior.get('trading_style', 'Unknown')

        style_modifiers = {
            "Power User": 1.12,
            "Active Trader": 1.08,
            "High Volume Specialist": 1.06,
            "Market Specialist": 1.05,
            "Strategic Explorer": 1.03,
            "Cautious Diversifier": 1.02,
            "General Trader": 1.00,
            "Big Better": 0.98,
            "Micro Trader": 0.96,
            "Weekend Warrior": 0.94,
            "Casual Trader": 0.92,
        }

        return style_modifiers.get(style, 1.00)

    def calculate_activity_modifier(self, trader_address: str) -> float:
        """
        Calculate activity modifier based on trading frequency and patterns.

        More engaged traders with consistent activity demonstrate commitment
        and are less likely to be lucky flukes.

        Args:
            trader_address: Trader's address

        Returns:
            Multiplier (0.97-1.06) based on activity
            - 1.06: High frequency + high diversification (sophisticated active)
            - 1.02: Medium frequency (engaged, moderate activity)
            - 1.00: Low frequency (neutral)
            - 0.98: High frequency + low diversification (churning same markets)
            - 0.97: Very low frequency (insufficient data/engagement)
            - 1.00: Unknown

        Additional bonuses/penalties:
            - +1.03x: Consistent presence (active >70% of trading days)
            - 0.98x: Sporadic activity (active <30% of trading days)

        Examples:
            5 trades/day with 65% diversification → 1.06x
            0.3 trades/day → 0.97x
        """
        behavior_data = self._load_behavioral_data()

        if trader_address not in behavior_data:
            return 1.0

        trader_behavior = behavior_data[trader_address]
        trades_per_day = trader_behavior.get('trades_per_day', 0)
        div_score = trader_behavior.get('diversification_score', 0)
        active_days = trader_behavior.get('active_days', 0)
        trading_days = trader_behavior.get('trading_days', 1)

        # Base modifier from frequency
        if trades_per_day >= 5:
            # High frequency - check diversification
            if div_score >= 60:
                modifier = 1.06  # Sophisticated active trader
            else:
                modifier = 0.98  # Churning same markets
        elif trades_per_day >= 1:
            modifier = 1.02  # Engaged, moderate activity
        elif trades_per_day >= 0.5:
            modifier = 1.00  # Low but reasonable frequency
        else:
            modifier = 0.97  # Very low frequency

        # Apply activity consistency adjustment
        if trading_days > 0:
            activity_ratio = active_days / trading_days
            if activity_ratio > 0.7:
                modifier *= 1.03  # Consistent presence
            elif activity_ratio < 0.3:
                modifier *= 0.98  # Sporadic, bursty

        return modifier

    def calculate_behavioral_multiplier(self, trader_address: str) -> Dict:
        """
        Calculate combined behavioral multiplier from all factors.

        This is the main method for getting behavioral adjustments. It combines
        consistency, diversification, trading style, and activity into a single
        multiplier that adjusts ELO ratings.

        Args:
            trader_address: Trader's address

        Returns:
            Dict with:
                - consistency: float (0.92-1.10)
                - diversification: float (0.93-1.08)
                - trading_style: float (0.92-1.12)
                - activity: float (0.97-1.06)
                - combined_multiplier: float (0.80-1.40, clamped)
                - breakdown: str (human-readable explanation)

        Examples:
            Power User with Very Consistent bets and Good Diversification:
            {
                'consistency': 1.10,
                'diversification': 1.05,
                'trading_style': 1.12,
                'activity': 1.02,
                'combined_multiplier': 1.31,
                'breakdown': 'Consistency: 1.10x (Very Consistent) | ...'
            }
        """
        # Calculate all individual modifiers
        consistency = self.calculate_consistency_modifier(trader_address)
        diversification = self.calculate_diversification_modifier(trader_address)
        style = self.calculate_trading_style_modifier(trader_address)
        activity = self.calculate_activity_modifier(trader_address)

        # Combine by multiplication
        combined = consistency * diversification * style * activity

        # Clamp to [0.80, 1.40] range (max ±40% adjustment)
        combined = max(0.80, min(1.40, combined))

        # Get style name for breakdown
        behavior_data = self._load_behavioral_data()
        trader_behavior = behavior_data.get(trader_address, {})
        style_name = trader_behavior.get('trading_style', 'Unknown')
        consistency_name = trader_behavior.get('bet_size_consistency', 'Unknown')

        # Generate breakdown string
        breakdown = (
            f"Consistency: {consistency:.2f}x ({consistency_name}) | "
            f"Diversification: {diversification:.2f}x | "
            f"Style: {style:.2f}x ({style_name}) | "
            f"Activity: {activity:.2f}x | "
            f"TOTAL: {combined:.2f}x"
        )

        return {
            'consistency': consistency,
            'diversification': diversification,
            'trading_style': style,
            'activity': activity,
            'combined_multiplier': combined,
            'breakdown': breakdown
        }

    def get_behavioral_weighted_elo(self, trader_address: str, category: str = None) -> float:
        """
        Get ELO rating adjusted by behavioral multipliers.

        Args:
            trader_address: Trader's address
            category: Specific category (None = global ELO)

        Returns:
            Adjusted ELO rating

        Examples:
            Base ELO: 1600
            Behavioral multiplier: 1.25
            Adjusted ELO: 2000
        """
        # Get base ELO
        if category:
            base_elo = self.get_trader_category_elo(trader_address, category)
        else:
            base_elo = self.get_trader_global_elo(trader_address)

        # Get behavioral multiplier
        behavior_data = self.calculate_behavioral_multiplier(trader_address)
        multiplier = behavior_data['combined_multiplier']

        # Apply multiplier
        adjusted_elo = base_elo * multiplier

        return adjusted_elo

    # ==================== ADVANCED METRICS (Calibration, Sharpe, Regret) ====================

    def _load_advanced_metrics_data(self, force_refresh: bool = False) -> bool:
        """
        Load advanced metrics data for all traders (with caching).

        Calculates:
        - Calibration (Brier scores) - Forecasting accuracy
        - Risk-adjusted returns (Sharpe ratios) - Consistency
        - Regret analysis - Execution quality

        Returns:
            bool: True if data loaded successfully, False if no resolved markets yet
        """
        # Check if cache is stale (>24 hours old)
        cache_age = None
        if self.advanced_metrics_timestamp:
            cache_age = (datetime.now() - self.advanced_metrics_timestamp).total_seconds()

        if force_refresh or self.advanced_metrics_timestamp is None or cache_age > 86400:

            print("[ADVANCED METRICS] Loading calibration, risk-adjusted, and regret data...")

            try:
                # 1. Load calibration data (Brier scores)
                print("[CALIBRATION] Calculating Brier scores...")
                calibration_results = self.calibration_analyzer.analyze_all_traders()

                if calibration_results:
                    for trader, data in calibration_results.items():
                        if data.get('total_predictions', 0) >= 5:  # Minimum predictions threshold
                            self.calibration_cache[trader] = data.get('brier_score', 0.5)
                    print(f"[CALIBRATION] Loaded {len(self.calibration_cache)} traders with calibration data")
                else:
                    print("[CALIBRATION] ⚠️  No resolved markets yet - calibration unavailable")

                # 2. Load risk-adjusted returns (Sharpe ratios)
                print("[RISK-ADJUSTED] Calculating Sharpe ratios...")
                risk_results = self.risk_analyzer.analyze_all_traders()

                if risk_results:
                    for trader, data in risk_results.items():
                        if data.get('total_trades', 0) >= 10:  # Minimum trades threshold
                            self.sharpe_cache[trader] = data.get('sharpe_ratio', 0.0)
                    print(f"[RISK-ADJUSTED] Loaded {len(self.sharpe_cache)} traders with Sharpe ratios")
                else:
                    print("[RISK-ADJUSTED] ⚠️  No resolved markets yet - Sharpe ratios unavailable")

                # 3. Load regret analysis (execution quality)
                print("[REGRET] Calculating regret rates...")
                regret_results = self.regret_analyzer.analyze_all_traders()

                if regret_results:
                    for trader, data in regret_results.items():
                        if data.get('total_trades', 0) >= 10:  # Minimum trades threshold
                            self.regret_cache[trader] = data.get('regret_rate', 50.0)
                    print(f"[REGRET] Loaded {len(self.regret_cache)} traders with regret data")
                else:
                    print("[REGRET] ⚠️  No resolved markets yet - regret analysis unavailable")

                self.advanced_metrics_timestamp = datetime.now()

                # Return True if we have at least some data
                has_data = len(self.calibration_cache) > 0 or len(self.sharpe_cache) > 0 or len(self.regret_cache) > 0

                if has_data:
                    print(f"[ADVANCED METRICS] ✅ Successfully loaded advanced metrics")
                else:
                    print(f"[ADVANCED METRICS] ⚠️  No resolved markets - advanced metrics unavailable")

                return has_data

            except Exception as e:
                print(f"[ADVANCED METRICS] ❌ Error loading data: {e}")
                print(f"[ADVANCED METRICS] Continuing with neutral modifiers (1.0x)")
                return False
        else:
            print(f"[ADVANCED METRICS] Using cached data (age: {cache_age/3600:.1f} hours)")

        return True  # Cache is fresh

    def get_calibration_weight(self, trader_address: str) -> float:
        """
        Calculate calibration-based weight from Brier score.

        Brier score measures forecasting accuracy (0.0 = perfect, 1.0 = worst).
        Lower Brier = better forecasting = higher weight.

        Weight formula: 2.0 - brier_score (range 0.5-2.0)

        Args:
            trader_address: Trader's address

        Returns:
            float: Weight multiplier (0.5-2.0)
                - Brier 0.00-0.10: 1.90-2.00x (exceptional forecasting)
                - Brier 0.10-0.20: 1.80-1.90x (excellent forecasting)
                - Brier 0.20-0.30: 1.70-1.80x (good forecasting)
                - Brier 0.30-0.40: 1.60-1.70x (above average)
                - Brier 0.40-0.50: 1.50-1.60x (average)
                - Brier 0.50-0.60: 1.40-1.50x (below average)
                - Brier >0.60: 0.50-1.40x (poor forecasting)

        Examples:
            Brier 0.15 (excellent) → 1.85x weight
            Brier 0.50 (random guessing) → 1.50x weight
            Brier 0.80 (poor) → 1.20x weight
        """
        # Load data if not cached
        if not self.calibration_cache and self.advanced_metrics_timestamp is None:
            self._load_advanced_metrics_data()

        # Get Brier score (default 0.5 = random guessing)
        brier_score = self.calibration_cache.get(trader_address, 0.5)

        # Calculate weight: 2.0 - brier_score
        weight = 2.0 - brier_score

        # Clamp to [0.5, 2.0] range
        weight = max(0.5, min(2.0, weight))

        return weight

    def get_adaptive_k_factor(self, trader_address: str) -> int:
        """
        Calculate adaptive K-factor based on Sharpe ratio.

        K-factor controls ELO rating volatility:
        - Low K = stable ratings (consistent performer, proven skill)
        - High K = volatile ratings (inconsistent, likely to regress to mean)

        Sharpe ratio measures risk-adjusted returns:
        - High Sharpe = consistent profits (skill, not luck)
        - Low Sharpe = volatile profits (luck, high variance)

        Args:
            trader_address: Trader's address

        Returns:
            int: K-factor (16-40)
                - Sharpe >2.5: K=16 (very stable, proven consistency)
                - Sharpe 2.0-2.5: K=20 (stable, high consistency)
                - Sharpe 1.5-2.0: K=24 (moderately stable)
                - Sharpe 1.0-1.5: K=28 (slight stability)
                - Sharpe 0.5-1.0: K=32 (default, neutral)
                - Sharpe 0-0.5: K=36 (volatile, likely luck)
                - Sharpe <0: K=40 (very volatile, poor performance)

        Examples:
            Sharpe 3.0 (exceptional) → K=16 (very stable)
            Sharpe 0.8 (average) → K=32 (normal volatility)
            Sharpe -0.5 (poor) → K=40 (high volatility)
        """
        # Load data if not cached
        if not self.sharpe_cache and self.advanced_metrics_timestamp is None:
            self._load_advanced_metrics_data()

        # Get Sharpe ratio (default 0.5 = neutral)
        sharpe_ratio = self.sharpe_cache.get(trader_address, 0.5)

        # Calculate K-factor based on Sharpe
        if sharpe_ratio >= 2.5:
            k_factor = 16  # Very stable ratings
        elif sharpe_ratio >= 2.0:
            k_factor = 20
        elif sharpe_ratio >= 1.5:
            k_factor = 24
        elif sharpe_ratio >= 1.0:
            k_factor = 28
        elif sharpe_ratio >= 0.5:
            k_factor = 32  # Default
        elif sharpe_ratio >= 0.0:
            k_factor = 36
        else:  # Negative Sharpe
            k_factor = 40  # Very volatile ratings

        return k_factor

    def get_execution_modifier(self, trader_address: str) -> float:
        """
        Calculate execution quality modifier from regret rate.

        Regret rate measures how often trader exits positions early
        (sells before peak profit or holds losing positions too long).

        Low regret = excellent timing/execution
        High regret = poor timing/execution

        Args:
            trader_address: Trader's address

        Returns:
            float: Execution multiplier (0.90-1.15)
                - Regret 0-10%: 1.15x (exceptional execution)
                - Regret 10-20%: 1.10x (excellent execution)
                - Regret 20-30%: 1.07x (very good execution)
                - Regret 30-40%: 1.05x (good execution)
                - Regret 40-50%: 1.02x (above average)
                - Regret 50-60%: 1.00x (average)
                - Regret 60-70%: 0.97x (below average)
                - Regret 70-80%: 0.94x (poor execution)
                - Regret >80%: 0.90x (very poor execution)

        Examples:
            Regret 5% (excellent timing) → 1.15x
            Regret 55% (average) → 1.00x
            Regret 85% (poor timing) → 0.90x
        """
        # Load data if not cached
        if not self.regret_cache and self.advanced_metrics_timestamp is None:
            self._load_advanced_metrics_data()

        # Get regret rate (default 50% = average)
        regret_rate = self.regret_cache.get(trader_address, 50.0)

        # Calculate modifier based on regret rate
        if regret_rate < 10:
            modifier = 1.15
        elif regret_rate < 20:
            modifier = 1.10
        elif regret_rate < 30:
            modifier = 1.07
        elif regret_rate < 40:
            modifier = 1.05
        elif regret_rate < 50:
            modifier = 1.02
        elif regret_rate < 60:
            modifier = 1.00
        elif regret_rate < 70:
            modifier = 0.97
        elif regret_rate < 80:
            modifier = 0.94
        else:
            modifier = 0.90

        return modifier

    def calculate_advanced_metrics_multiplier(self, trader_address: str) -> Dict:
        """
        Calculate combined advanced metrics multiplier.

        Combines three dimensions:
        1. Calibration weight (forecasting accuracy from Brier scores)
        2. Execution modifier (timing quality from regret analysis)
        3. K-factor recommendation (consistency from Sharpe ratios)

        Args:
            trader_address: Trader's address

        Returns:
            dict: {
                'calibration_weight': float (0.5-2.0),
                'execution_modifier': float (0.90-1.15),
                'k_factor': int (16-40),
                'combined_multiplier': float (0.45-2.3),
                'brier_score': float or None,
                'sharpe_ratio': float or None,
                'regret_rate': float or None,
                'breakdown': str (human-readable explanation)
            }

        Examples:
            Exceptional trader (Brier 0.15, Regret 8%, Sharpe 2.8):
                calibration_weight: 1.85x
                execution_modifier: 1.15x
                combined_multiplier: 2.13x
                k_factor: 16

            Average trader (defaults):
                calibration_weight: 1.50x
                execution_modifier: 1.00x
                combined_multiplier: 1.50x
                k_factor: 32
        """
        # Get individual components
        calibration_weight = self.get_calibration_weight(trader_address)
        execution_modifier = self.get_execution_modifier(trader_address)
        k_factor = self.get_adaptive_k_factor(trader_address)

        # Combined multiplier (calibration × execution)
        combined = calibration_weight * execution_modifier

        # Clamp to reasonable range [0.45, 2.3]
        combined = max(0.45, min(2.3, combined))

        # Get raw metrics for reporting
        brier_score = self.calibration_cache.get(trader_address)
        sharpe_ratio = self.sharpe_cache.get(trader_address)
        regret_rate = self.regret_cache.get(trader_address)

        # Build breakdown string
        breakdown_parts = []

        if brier_score is not None:
            breakdown_parts.append(f"Calibration: {calibration_weight:.2f}x (Brier: {brier_score:.3f})")
        else:
            breakdown_parts.append(f"Calibration: {calibration_weight:.2f}x (Default)")

        if regret_rate is not None:
            breakdown_parts.append(f"Execution: {execution_modifier:.2f}x (Regret: {regret_rate:.1f}%)")
        else:
            breakdown_parts.append(f"Execution: {execution_modifier:.2f}x (Default)")

        if sharpe_ratio is not None:
            breakdown_parts.append(f"K-Factor: {k_factor} (Sharpe: {sharpe_ratio:.2f})")
        else:
            breakdown_parts.append(f"K-Factor: {k_factor} (Default)")

        breakdown_parts.append(f"TOTAL: {combined:.2f}x")

        breakdown = " | ".join(breakdown_parts)

        return {
            'calibration_weight': round(calibration_weight, 3),
            'execution_modifier': round(execution_modifier, 3),
            'k_factor': k_factor,
            'combined_multiplier': round(combined, 3),
            'brier_score': round(brier_score, 4) if brier_score is not None else None,
            'sharpe_ratio': round(sharpe_ratio, 3) if sharpe_ratio is not None else None,
            'regret_rate': round(regret_rate, 2) if regret_rate is not None else None,
            'breakdown': breakdown
        }

    def get_advanced_weighted_elo(self, trader_address: str, category: str = None) -> float:
        """
        Get ELO rating with advanced metrics weighting applied.

        Applies calibration (forecasting accuracy) and execution (timing quality)
        multipliers to base ELO rating.

        Args:
            trader_address: Trader to evaluate
            category: Specific category (or None for global)

        Returns:
            float: ELO rating adjusted by advanced metrics

        Examples:
            Base ELO 1600, advanced multiplier 1.85x → 2960
            Base ELO 1500, advanced multiplier 0.80x → 1200
        """
        # Get base ELO
        if category:
            base_elo = self.get_trader_category_elo(trader_address, category)
        else:
            base_elo = self.get_trader_global_elo(trader_address)

        # Get advanced metrics multiplier
        advanced = self.calculate_advanced_metrics_multiplier(trader_address)
        combined_multiplier = advanced['combined_multiplier']

        # Apply multiplier
        adjusted_elo = base_elo * combined_multiplier

        return adjusted_elo

    # ==================== NETWORK ANALYSIS (Correlation, Copy-Trade Detection) ====================

    def _load_network_data(self, force_refresh: bool = False) -> bool:
        """
        Load network analysis data (correlation matrix + copy-trade detection).

        This is an expensive operation, so results are cached for 24 hours.

        Args:
            force_refresh: Force reload even if cache is valid

        Returns:
            bool: True if data loaded successfully
        """
        # Check if cache is stale (>24 hours old)
        cache_age = None
        if self.network_cache_timestamp:
            cache_age = (datetime.now() - self.network_cache_timestamp).total_seconds()

        if force_refresh or self.network_cache_timestamp is None or cache_age > 86400:

            print("[NETWORK] Loading correlation and copy-trade data...")

            try:
                # 1. Load correlation data
                print("[CORRELATION] Building correlation matrix...")

                # Check if correlation cache exists
                cache_file = os.path.join(os.path.dirname(self.db_path), 'reports', 'correlation_cache.json')

                if os.path.exists(cache_file):
                    # Load from cache
                    cache_file_age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).total_seconds() / 3600

                    if cache_file_age < 24:  # Cache valid for 24 hours
                        print(f"[CORRELATION] Loading from cache (age: {cache_file_age:.1f} hours)...")
                        with open(cache_file, 'r') as f:
                            correlation_data = json.load(f)

                        self.independence_scores = correlation_data.get('independence_scores', {})
                        self.correlation_clusters = correlation_data.get('correlation_clusters', [])
                        self.avg_correlations = correlation_data.get('avg_correlations', {})

                        print(f"[CORRELATION] Loaded {len(self.independence_scores)} independence scores from cache")
                    else:
                        print(f"[CORRELATION] Cache stale ({cache_file_age:.1f} hours), recalculating...")
                        correlation_data = self._calculate_correlation_data()
                else:
                    print("[CORRELATION] No cache found, calculating fresh data...")
                    correlation_data = self._calculate_correlation_data()

                # 2. Load copy-trade relationships
                print("[COPY-TRADE] Detecting copy-trade relationships...")

                # Run copy-trade detection
                copy_results = self.copy_detector.detect_copy_trading()

                if copy_results:
                    # Process results into self.copy_relationships
                    for relationship in copy_results.get('relationships', []):
                        leader = relationship['leader']
                        follower = relationship['follower']

                        # Mark follower
                        if follower not in self.copy_relationships:
                            self.copy_relationships[follower] = {
                                'is_follower': True,
                                'is_leader': False,
                                'leaders': [],
                                'followers': [],
                                'copy_score': 0.0
                            }

                        self.copy_relationships[follower]['leaders'].append(leader)
                        self.copy_relationships[follower]['copy_score'] = max(
                            self.copy_relationships[follower]['copy_score'],
                            relationship.get('copy_score', 0.0)
                        )

                        # Mark leader
                        if leader not in self.copy_relationships:
                            self.copy_relationships[leader] = {
                                'is_follower': False,
                                'is_leader': True,
                                'leaders': [],
                                'followers': [],
                                'copy_score': 0.0
                            }

                        self.copy_relationships[leader]['followers'].append(follower)
                        self.copy_relationships[leader]['is_leader'] = True

                    print(f"[COPY-TRADE] Detected {len([t for t, r in self.copy_relationships.items() if r['is_follower']])} followers")
                    print(f"[COPY-TRADE] Detected {len([t for t, r in self.copy_relationships.items() if r['is_leader']])} leaders")
                else:
                    print("[COPY-TRADE] ⚠️  Copy-trade detection returned no results")

                self.network_cache_timestamp = datetime.now()

                print("[NETWORK] ✅ Successfully loaded network data")
                return True

            except Exception as e:
                print(f"[NETWORK] ❌ Error loading network data: {e}")
                print(f"[NETWORK] Continuing with neutral network modifiers")
                return False
        else:
            print(f"[NETWORK] Using cached data (age: {cache_age/3600:.1f} hours)")

        return True  # Cache is fresh

    def _calculate_correlation_data(self) -> Dict:
        """Calculate correlation matrix and export data."""
        # This runs the full correlation analysis
        correlation_data = self.correlation_analyzer.export_for_integration()

        self.independence_scores = correlation_data.get('independence_scores', {})
        self.correlation_clusters = correlation_data.get('correlation_clusters', [])
        self.avg_correlations = correlation_data.get('avg_correlations', {})

        print(f"[CORRELATION] Calculated {len(self.independence_scores)} independence scores")

        return correlation_data

    def get_independence_modifier(self, trader_address: str) -> float:
        """
        Calculate independence-based modifier from correlation analysis.

        Independence score measures how uncorrelated a trader's decisions
        are with other traders. High independence = genuine signal.

        Formula: independence_score = (1 - avg_correlation) × 100

        Args:
            trader_address: Trader's address

        Returns:
            float: Independence multiplier (0.5-1.25)
                - Score 90-100: 1.25x (very independent, unique alpha)
                - Score 80-89: 1.20x (highly independent)
                - Score 70-79: 1.15x (independent)
                - Score 60-69: 1.10x (mostly independent)
                - Score 50-59: 1.05x (somewhat independent)
                - Score 40-49: 1.00x (neutral)
                - Score 30-39: 0.90x (some correlation)
                - Score 20-29: 0.80x (moderate correlation)
                - Score 10-19: 0.70x (high correlation)
                - Score 0-9: 0.50x (very high correlation, possible copy-trader)
        """
        # Load data if not cached
        if not self.independence_scores and self.network_cache_timestamp is None:
            self._load_network_data()

        # Get independence score (default 50 = neutral)
        independence_score = self.independence_scores.get(trader_address, 50)

        # Calculate modifier based on independence score
        if independence_score >= 90:
            modifier = 1.25  # Very independent
        elif independence_score >= 80:
            modifier = 1.20
        elif independence_score >= 70:
            modifier = 1.15
        elif independence_score >= 60:
            modifier = 1.10
        elif independence_score >= 50:
            modifier = 1.05
        elif independence_score >= 40:
            modifier = 1.00  # Neutral
        elif independence_score >= 30:
            modifier = 0.90
        elif independence_score >= 20:
            modifier = 0.80
        elif independence_score >= 10:
            modifier = 0.70
        else:  # < 10
            modifier = 0.50  # Likely copy-trader

        return modifier

    def is_copy_trader(self, trader_address: str) -> Dict:
        """
        Check if trader is identified as copy-trader (follower).

        Args:
            trader_address: Trader to check

        Returns:
            dict: {
                'is_follower': bool,
                'is_leader': bool,
                'copy_score': float (0-1),
                'leaders': List[str],
                'followers': List[str],
                'should_exclude': bool  # True if follower with high copy_score
            }
        """
        # Load data if not cached
        if not self.copy_relationships and self.network_cache_timestamp is None:
            self._load_network_data()

        # Get copy relationship data
        if trader_address not in self.copy_relationships:
            # Not identified as copy-trader
            return {
                'is_follower': False,
                'is_leader': False,
                'copy_score': 0.0,
                'leaders': [],
                'followers': [],
                'should_exclude': False
            }

        relationship = self.copy_relationships[trader_address]

        # Determine if should exclude from consensus calculations
        # Exclude if: follower with copy_score > 0.7
        should_exclude = relationship['is_follower'] and relationship['copy_score'] > 0.7

        return {
            'is_follower': relationship['is_follower'],
            'is_leader': relationship['is_leader'],
            'copy_score': relationship['copy_score'],
            'leaders': relationship['leaders'],
            'followers': relationship['followers'],
            'should_exclude': should_exclude
        }

    def is_in_suspicious_cluster(self, trader_address: str) -> Dict:
        """
        Check if trader is in a suspicious correlation cluster.

        Suspicious clusters have very high avg correlation (>0.8),
        suggesting coordinated trading or copy networks.

        Args:
            trader_address: Trader to check

        Returns:
            dict: {
                'in_cluster': bool,
                'cluster_id': int or None,
                'cluster_type': str or None (SUSPICIOUS, TIGHT, LOOSE),
                'cluster_size': int or None,
                'avg_correlation': float or None,
                'penalty_modifier': float (0.5-1.0)
            }
        """
        # Load data if not cached
        if not self.correlation_clusters and self.network_cache_timestamp is None:
            self._load_network_data()

        # Check if trader is in any cluster
        for cluster in self.correlation_clusters:
            if trader_address in cluster.get('traders', []):
                cluster_type = cluster.get('cluster_type', 'LOOSE')
                avg_corr = cluster.get('avg_correlation', 0.5)

                # Calculate penalty modifier based on cluster type
                if 'SUSPICIOUS' in cluster_type.upper() or avg_corr >= 0.8:
                    penalty_modifier = 0.50  # Heavy penalty
                elif 'TIGHT' in cluster_type.upper() or avg_corr >= 0.7:
                    penalty_modifier = 0.75  # Moderate penalty
                else:  # LOOSE
                    penalty_modifier = 0.90  # Light penalty

                return {
                    'in_cluster': True,
                    'cluster_id': cluster.get('cluster_id'),
                    'cluster_type': cluster_type,
                    'cluster_size': cluster.get('size', 0),
                    'avg_correlation': avg_corr,
                    'penalty_modifier': penalty_modifier
                }

        # Not in any cluster
        return {
            'in_cluster': False,
            'cluster_id': None,
            'cluster_type': None,
            'cluster_size': None,
            'avg_correlation': None,
            'penalty_modifier': 1.0  # No penalty
        }

    def calculate_network_modifier(self, trader_address: str) -> Dict:
        """
        Calculate combined network-based modifier.

        Combines three network dimensions:
        1. Independence score (correlation with others)
        2. Copy-trader status (follower/leader)
        3. Cluster membership (suspicious networks)

        Args:
            trader_address: Trader to evaluate

        Returns:
            dict: {
                'independence_modifier': float (0.5-1.25),
                'independence_score': int (0-100),
                'copy_trader_status': dict,
                'cluster_status': dict,
                'combined_modifier': float (0.0-1.25),
                'should_exclude': bool,
                'breakdown': str
            }
        """
        # Get independence modifier
        independence_modifier = self.get_independence_modifier(trader_address)
        independence_score = self.independence_scores.get(trader_address, 50)

        # Get copy-trader status
        copy_status = self.is_copy_trader(trader_address)

        # Get cluster status
        cluster_status = self.is_in_suspicious_cluster(trader_address)

        # Calculate combined modifier
        combined = independence_modifier

        # Apply copy-trader penalty
        if copy_status['is_follower']:
            if copy_status['copy_score'] > 0.8:
                combined = 0.0  # Complete exclusion
            elif copy_status['copy_score'] > 0.7:
                combined *= 0.25  # Heavy penalty
            elif copy_status['copy_score'] > 0.6:
                combined *= 0.50  # Moderate penalty
            else:
                combined *= 0.75  # Light penalty

        # Apply cluster penalty (multiplicative)
        if cluster_status['in_cluster']:
            combined *= cluster_status['penalty_modifier']

        # Determine if should exclude from calculations
        should_exclude = copy_status['should_exclude'] or (combined < 0.1)

        # Build breakdown string
        breakdown_parts = []
        breakdown_parts.append(f"Independence: {independence_modifier:.2f}x (Score: {independence_score})")

        if copy_status['is_follower']:
            breakdown_parts.append(f"Copy-Trader: FOLLOWER (Score: {copy_status['copy_score']:.2f})")
        elif copy_status['is_leader']:
            breakdown_parts.append(f"Copy-Trader: LEADER ({len(copy_status['followers'])} followers)")
        else:
            breakdown_parts.append(f"Copy-Trader: INDEPENDENT")

        if cluster_status['in_cluster']:
            breakdown_parts.append(f"Cluster: {cluster_status['cluster_type']} (Penalty: {cluster_status['penalty_modifier']:.2f}x)")
        else:
            breakdown_parts.append(f"Cluster: NONE")

        if should_exclude:
            breakdown_parts.append("STATUS: EXCLUDED")
        else:
            breakdown_parts.append(f"TOTAL: {combined:.2f}x")

        breakdown = " | ".join(breakdown_parts)

        return {
            'independence_modifier': round(independence_modifier, 3),
            'independence_score': independence_score,
            'copy_trader_status': copy_status,
            'cluster_status': cluster_status,
            'combined_modifier': round(combined, 3),
            'should_exclude': should_exclude,
            'breakdown': breakdown
        }

    # ==================== INTEGRATION METHODS ====================

    def get_trader_global_elo(self, trader_address: str, apply_behavioral: bool = False,
                              apply_advanced: bool = False, apply_network: bool = False) -> float:
        """
        Get trader's global ELO rating (weighted average across all categories).

        This provides a single overall skill rating, but category-specific ratings
        are more accurate for domain-specific predictions.

        Args:
            trader_address: Trader's address
            apply_behavioral: If True, apply behavioral multipliers to adjust ELO
            apply_advanced: If True, apply advanced metrics (calibration, execution, Sharpe)
            apply_network: If True, apply network filtering (independence, copy-trader detection)

        Returns:
            Global ELO rating (weighted average), optionally adjusted by behavioral, advanced, and/or network factors
            Returns 0.0 if trader should be excluded (copy-trader)

        Examples:
            Base ELO: system.get_trader_global_elo(trader)
            Behavioral: system.get_trader_global_elo(trader, apply_behavioral=True)
            Advanced: system.get_trader_global_elo(trader, apply_advanced=True)
            Network: system.get_trader_global_elo(trader, apply_network=True)
            All: system.get_trader_global_elo(trader, apply_behavioral=True, apply_advanced=True, apply_network=True)
        """
        # Check if should exclude due to copy-trading
        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            if network_data['should_exclude']:
                return 0.0  # Exclude from calculations

        base_elo = self.elo_system.get_overall_elo(trader_address)
        adjusted_elo = base_elo

        if apply_behavioral:
            behavior_data = self.calculate_behavioral_multiplier(trader_address)
            adjusted_elo *= behavior_data['combined_multiplier']

        if apply_advanced:
            advanced_data = self.calculate_advanced_metrics_multiplier(trader_address)
            adjusted_elo *= advanced_data['combined_multiplier']

        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            adjusted_elo *= network_data['combined_modifier']

        return adjusted_elo

    def get_trader_category_elo(self, trader_address: str, category: str,
                                apply_behavioral: bool = False, apply_advanced: bool = False,
                                apply_network: bool = False) -> float:
        """
        Get trader's ELO rating for a specific category.

        Use this for category-aware predictions (more accurate than global ELO).

        Args:
            trader_address: Trader's address
            category: Market category (e.g., 'Elections', 'Crypto')
            apply_behavioral: If True, apply behavioral multipliers to adjust ELO
            apply_advanced: If True, apply advanced metrics (calibration, execution, Sharpe)
            apply_network: If True, apply network filtering (independence, copy-trader detection)

        Returns:
            Category-specific ELO rating, optionally adjusted by behavioral, advanced, and/or network factors
            Returns 0.0 if trader should be excluded (copy-trader)

        Examples:
            Base ELO: system.get_trader_category_elo(trader, 'Elections')
            With behavioral: system.get_trader_category_elo(trader, 'Elections', apply_behavioral=True)
            With advanced: system.get_trader_category_elo(trader, 'Elections', apply_advanced=True)
            With network: system.get_trader_category_elo(trader, 'Elections', apply_network=True)
            With all: system.get_trader_category_elo(trader, 'Elections', apply_behavioral=True, apply_advanced=True, apply_network=True)
        """
        # Check if should exclude due to copy-trading
        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            if network_data['should_exclude']:
                return 0.0  # Exclude from calculations

        base_elo = self.elo_system.get_category_elo(trader_address, category)
        adjusted_elo = base_elo

        if apply_behavioral:
            behavior_data = self.calculate_behavioral_multiplier(trader_address)
            adjusted_elo *= behavior_data['combined_multiplier']

        if apply_advanced:
            advanced_data = self.calculate_advanced_metrics_multiplier(trader_address)
            adjusted_elo *= advanced_data['combined_multiplier']

        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            adjusted_elo *= network_data['combined_modifier']

        return adjusted_elo

    def is_specialist(self, trader_address: str, category: str = None,
                     min_markets: int = 5, min_advantage: float = 100) -> Tuple[bool, float]:
        """
        Determine if trader is a specialist in a category.

        A specialist has:
        1. At least min_markets trades in the category
        2. Category ELO at least min_advantage points above global ELO

        Args:
            trader_address: Trader's address
            category: Specific category to check (None = find best category)
            min_markets: Minimum markets required
            min_advantage: Minimum ELO advantage required

        Returns:
            Tuple of (is_specialist: bool, specialization_score: float)
            specialization_score = (category_elo - global_elo) if specialist, else 0
        """
        # Check cache
        cache_key = f"{trader_address}:{category}:{min_markets}:{min_advantage}"
        if cache_key in self.specialist_cache:
            return self.specialist_cache[cache_key]

        global_elo = self.get_trader_global_elo(trader_address)

        if category:
            # Check specific category
            cat_elo = self.get_trader_category_elo(trader_address, category)
            market_count = self.elo_system.get_market_count(trader_address, category)

            if market_count >= min_markets and cat_elo >= global_elo + min_advantage:
                specialization_score = cat_elo - global_elo
                result = (True, specialization_score)
            else:
                result = (False, 0.0)

            self.specialist_cache[cache_key] = result
            return result
        else:
            # Find best category
            best_category = None
            best_score = 0.0

            for cat in ALL_CATEGORIES:
                cat_elo = self.get_trader_category_elo(trader_address, cat)
                market_count = self.elo_system.get_market_count(trader_address, cat)

                if market_count >= min_markets:
                    advantage = cat_elo - global_elo
                    if advantage >= min_advantage and advantage > best_score:
                        best_category = cat
                        best_score = advantage

            result = (best_category is not None, best_score)
            self.specialist_cache[cache_key] = result
            return result

    def get_filtered_traders_for_consensus(self, category: str = None, min_elo: float = 0) -> List[str]:
        """
        Get list of traders suitable for consensus calculation.

        Filters out:
        - Copy-traders (followers with high copy_score)
        - Traders in suspicious correlation clusters
        - Traders below minimum ELO threshold

        Args:
            category: Filter by category (or None for global)
            min_elo: Minimum ELO threshold

        Returns:
            List[str]: Trader addresses suitable for consensus
        """
        # Load network data
        self._load_network_data()

        # Get all traders
        all_traders = list(self.elo_system.category_elos.keys())

        filtered = []

        for trader in all_traders:
            # Check network status
            network_data = self.calculate_network_modifier(trader)

            # Exclude if flagged
            if network_data['should_exclude']:
                continue

            # Check ELO threshold
            if category:
                elo = self.get_trader_category_elo(trader, category,
                                                   apply_behavioral=True,
                                                   apply_advanced=True,
                                                   apply_network=True)
            else:
                elo = self.get_trader_global_elo(trader,
                                                apply_behavioral=True,
                                                apply_advanced=True,
                                                apply_network=True)

            if elo >= min_elo:
                filtered.append(trader)

        return filtered

    def export_network_analysis(self) -> Dict:
        """
        Export network analysis for all traders.

        Returns comprehensive network data for integration.
        """
        print("[NETWORK] Exporting network analysis...")

        # Load data if needed
        self._load_network_data()

        traders_with_network = []

        # Get all traders
        all_traders = set(self.independence_scores.keys()) | set(self.copy_relationships.keys())

        for trader in all_traders:
            network_data = self.calculate_network_modifier(trader)

            traders_with_network.append({
                'trader': trader,
                'independence_score': network_data['independence_score'],
                'independence_modifier': network_data['independence_modifier'],
                'is_follower': network_data['copy_trader_status']['is_follower'],
                'is_leader': network_data['copy_trader_status']['is_leader'],
                'copy_score': network_data['copy_trader_status']['copy_score'],
                'in_cluster': network_data['cluster_status']['in_cluster'],
                'cluster_type': network_data['cluster_status']['cluster_type'],
                'combined_modifier': network_data['combined_modifier'],
                'should_exclude': network_data['should_exclude']
            })

        # Sort by independence score (highest first)
        traders_with_network.sort(key=lambda x: x['independence_score'], reverse=True)

        # Calculate statistics
        followers = [t for t in traders_with_network if t['is_follower']]
        leaders = [t for t in traders_with_network if t['is_leader']]
        excluded = [t for t in traders_with_network if t['should_exclude']]
        suspicious_clusters = [c for c in self.correlation_clusters if 'SUSPICIOUS' in c.get('cluster_type', '')]

        export = {
            'timestamp': datetime.now().isoformat(),
            'total_traders_analyzed': len(traders_with_network),
            'independent_traders': len([t for t in traders_with_network if t['independence_score'] >= 75]),
            'followers_detected': len(followers),
            'leaders_detected': len(leaders),
            'traders_excluded': len(excluded),
            'suspicious_clusters': len(suspicious_clusters),
            'avg_independence_score': sum(t['independence_score'] for t in traders_with_network) / len(traders_with_network) if traders_with_network else 0,
            'top_independent_traders': [t for t in traders_with_network if not t['should_exclude']][:10]
        }

        print(f"[NETWORK] Export complete: {export['independent_traders']}/{export['total_traders_analyzed']} independent traders")
        print(f"[NETWORK] Excluded {export['traders_excluded']} copy-traders from consensus")

        return export

    def generate_network_report(self, output_dir: str = 'reports'):
        """
        Generate CSV report of network analysis.

        Creates: reports/network_analysis_YYYYMMDD.csv

        Columns:
            - Rank
            - Trader Address
            - Independence Score (0-100)
            - Independence Modifier
            - Avg Correlation
            - Copy Status (Independent/Leader/Follower)
            - Copy Score
            - Cluster Type
            - Network Modifier
            - Should Exclude

        Args:
            output_dir: Output directory for reports

        Returns:
            Path to generated report
        """
        print(f"[NETWORK] Generating network analysis report...")

        # Create output directory
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Load network data
        self._load_network_data()

        # Get all traders
        all_traders = set(self.independence_scores.keys()) | set(self.copy_relationships.keys())

        # Generate report data
        report_rows = []

        for trader in all_traders:
            network_data = self.calculate_network_modifier(trader)

            # Determine copy status
            if network_data['copy_trader_status']['is_follower']:
                copy_status = 'Follower'
            elif network_data['copy_trader_status']['is_leader']:
                copy_status = 'Leader'
            else:
                copy_status = 'Independent'

            # Get avg correlation
            avg_corr = self.avg_correlations.get(trader, 0.0)

            report_rows.append({
                'trader_address': trader,
                'independence_score': network_data['independence_score'],
                'independence_modifier': f"{network_data['independence_modifier']:.3f}",
                'avg_correlation': f"{avg_corr:.3f}",
                'copy_status': copy_status,
                'copy_score': f"{network_data['copy_trader_status']['copy_score']:.3f}",
                'cluster_type': network_data['cluster_status']['cluster_type'] or 'NONE',
                'network_modifier': f"{network_data['combined_modifier']:.3f}",
                'should_exclude': 'YES' if network_data['should_exclude'] else 'NO'
            })

        # Sort by independence score (highest first)
        report_rows.sort(key=lambda x: x['independence_score'], reverse=True)

        # Add rank column
        for i, row in enumerate(report_rows, 1):
            row['rank'] = i

        # Reorder columns with rank first
        column_order = ['rank', 'trader_address', 'independence_score', 'independence_modifier',
                       'avg_correlation', 'copy_status', 'copy_score', 'cluster_type',
                       'network_modifier', 'should_exclude']

        # Write CSV
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(output_dir, f'network_analysis_{date_str}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8', errors='ignore') as f:
            if report_rows:
                writer = csv.DictWriter(f, fieldnames=column_order)
                writer.writeheader()
                writer.writerows(report_rows)

        print(f"[NETWORK] Report saved: {output_path}")
        print(f"[NETWORK] {len(report_rows)} traders included")

        return output_path

    def export_behavioral_analysis(self) -> Dict:
        """
        Export behavioral analysis data for all traders.

        Returns:
            Dict with:
                - timestamp: Analysis timestamp
                - total_traders: Total number of traders
                - traders_with_behavior: Number with behavioral data
                - avg_*_modifier: Average modifier for each component
                - top_behavioral_traders: Top 10 by adjusted ELO
        """
        print("[BEHAVIORAL] Exporting behavioral analysis...")

        all_traders = self.elo_system.get_all_traders()
        behavior_data = self._load_behavioral_data()

        # Calculate statistics
        consistency_mods = []
        diversification_mods = []
        style_mods = []
        activity_mods = []

        trader_adjusted_elos = []

        for trader in all_traders:
            if trader in behavior_data:
                behavior_mult = self.calculate_behavioral_multiplier(trader)
                consistency_mods.append(behavior_mult['consistency'])
                diversification_mods.append(behavior_mult['diversification'])
                style_mods.append(behavior_mult['trading_style'])
                activity_mods.append(behavior_mult['activity'])

                # Calculate adjusted ELO for ranking
                base_elo = self.get_trader_global_elo(trader)
                adjusted_elo = base_elo * behavior_mult['combined_multiplier']

                trader_adjusted_elos.append({
                    'trader': trader,
                    'base_elo': base_elo,
                    'behavioral_multiplier': behavior_mult['combined_multiplier'],
                    'adjusted_elo': adjusted_elo,
                    'breakdown': behavior_mult['breakdown']
                })

        # Sort by adjusted ELO
        trader_adjusted_elos.sort(key=lambda x: x['adjusted_elo'], reverse=True)

        export = {
            'timestamp': datetime.now().isoformat(),
            'total_traders': len(all_traders),
            'traders_with_behavior': len(behavior_data),
            'avg_consistency_modifier': sum(consistency_mods) / len(consistency_mods) if consistency_mods else 1.0,
            'avg_diversification_modifier': sum(diversification_mods) / len(diversification_mods) if diversification_mods else 1.0,
            'avg_style_modifier': sum(style_mods) / len(style_mods) if style_mods else 1.0,
            'avg_activity_modifier': sum(activity_mods) / len(activity_mods) if activity_mods else 1.0,
            'top_behavioral_traders': trader_adjusted_elos[:10]
        }

        print(f"[BEHAVIORAL] Export complete: {export['traders_with_behavior']}/{export['total_traders']} traders with behavioral data")

        return export

    def generate_behavioral_report(self, output_dir: str = 'reports'):
        """
        Generate CSV report of behavioral modifiers.

        Creates: reports/behavioral_modifiers_YYYYMMDD.csv

        Args:
            output_dir: Output directory for reports

        Returns:
            Path to generated report
        """
        print(f"[BEHAVIORAL] Generating behavioral modifiers report...")

        # Create output directory
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Get all traders and behavioral data
        all_traders = self.elo_system.get_all_traders()
        behavior_data = self._load_behavioral_data()

        # Generate report data
        report_rows = []

        for trader in all_traders:
            base_elo = self.get_trader_global_elo(trader)

            if trader in behavior_data:
                trader_behavior = behavior_data[trader]
                behavior_mult = self.calculate_behavioral_multiplier(trader)

                adjusted_elo = base_elo * behavior_mult['combined_multiplier']

                report_rows.append({
                    'trader_address': trader,
                    'base_global_elo': f"{base_elo:.1f}",
                    'consistency_modifier': f"{behavior_mult['consistency']:.3f}",
                    'diversification_modifier': f"{behavior_mult['diversification']:.3f}",
                    'trading_style_modifier': f"{behavior_mult['trading_style']:.3f}",
                    'activity_modifier': f"{behavior_mult['activity']:.3f}",
                    'combined_multiplier': f"{behavior_mult['combined_multiplier']:.3f}",
                    'adjusted_global_elo': f"{adjusted_elo:.1f}",
                    'trading_style': trader_behavior.get('trading_style', 'Unknown'),
                    'bet_consistency': trader_behavior.get('bet_size_consistency', 'Unknown'),
                    'diversification_score': f"{trader_behavior.get('diversification_score', 0):.1f}",
                    'trades_per_day': f"{trader_behavior.get('trades_per_day', 0):.2f}"
                })
            else:
                # No behavioral data
                report_rows.append({
                    'trader_address': trader,
                    'base_global_elo': f"{base_elo:.1f}",
                    'consistency_modifier': '1.000',
                    'diversification_modifier': '1.000',
                    'trading_style_modifier': '1.000',
                    'activity_modifier': '1.000',
                    'combined_multiplier': '1.000',
                    'adjusted_global_elo': f"{base_elo:.1f}",
                    'trading_style': 'Unknown',
                    'bet_consistency': 'Unknown',
                    'diversification_score': '0.0',
                    'trades_per_day': '0.00'
                })

        # Sort by adjusted ELO (highest first)
        report_rows.sort(key=lambda x: float(x['adjusted_global_elo']), reverse=True)

        # Write CSV
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(output_dir, f'behavioral_modifiers_{date_str}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8', errors='ignore') as f:
            if report_rows:
                writer = csv.DictWriter(f, fieldnames=report_rows[0].keys())
                writer.writeheader()
                writer.writerows(report_rows)

        print(f"[BEHAVIORAL] Report saved: {output_path}")
        print(f"[BEHAVIORAL] {len(report_rows)} traders included")

        return output_path

    def export_advanced_metrics_analysis(self) -> Dict:
        """
        Export advanced metrics analysis data for all traders.

        Returns:
            Dict with:
                - timestamp: Analysis timestamp
                - total_traders: Total number of traders
                - traders_with_metrics: Number with advanced metrics data
                - avg_calibration_weight: Average calibration weight
                - avg_execution_modifier: Average execution modifier
                - avg_k_factor: Average K-factor
                - avg_brier_score: Average Brier score
                - avg_sharpe_ratio: Average Sharpe ratio
                - avg_regret_rate: Average regret rate
                - top_advanced_traders: Top 10 by adjusted ELO
        """
        print("[ADVANCED METRICS] Exporting advanced metrics analysis...")

        all_traders = self.elo_system.get_all_traders()

        # Load advanced metrics
        metrics_loaded = self._load_advanced_metrics_data()

        if not metrics_loaded:
            print("[ADVANCED METRICS] Warning: No advanced metrics data available")
            return {
                'timestamp': datetime.now().isoformat(),
                'total_traders': len(all_traders),
                'traders_with_metrics': 0,
                'avg_calibration_weight': 1.5,
                'avg_execution_modifier': 1.0,
                'avg_k_factor': 32,
                'avg_brier_score': 0.0,
                'avg_sharpe_ratio': 0.0,
                'avg_regret_rate': 0.0,
                'top_advanced_traders': []
            }

        # Calculate statistics
        calibration_weights = []
        execution_modifiers = []
        k_factors = []
        brier_scores = []
        sharpe_ratios = []
        regret_rates = []

        trader_adjusted_elos = []

        for trader in all_traders:
            if trader in self.calibration_cache or trader in self.sharpe_cache or trader in self.regret_cache:
                advanced_mult = self.calculate_advanced_metrics_multiplier(trader)

                calibration_weights.append(advanced_mult['calibration'])
                execution_modifiers.append(advanced_mult['execution'])
                k_factors.append(advanced_mult['k_factor'])

                # Raw metrics
                brier = self.calibration_cache.get(trader, 0.25)
                sharpe = self.sharpe_cache.get(trader, 0.0)
                regret = self.regret_cache.get(trader, 0.0)

                brier_scores.append(brier)
                sharpe_ratios.append(sharpe)
                regret_rates.append(regret)

                # Calculate adjusted ELO for ranking
                base_elo = self.get_trader_global_elo(trader)
                adjusted_elo = base_elo * advanced_mult['combined_multiplier']

                trader_adjusted_elos.append({
                    'trader': trader,
                    'base_elo': base_elo,
                    'advanced_multiplier': advanced_mult['combined_multiplier'],
                    'adjusted_elo': adjusted_elo,
                    'calibration_weight': advanced_mult['calibration'],
                    'execution_modifier': advanced_mult['execution'],
                    'k_factor': advanced_mult['k_factor'],
                    'brier_score': brier,
                    'sharpe_ratio': sharpe,
                    'regret_rate': regret,
                    'breakdown': advanced_mult['breakdown']
                })

        # Sort by adjusted ELO
        trader_adjusted_elos.sort(key=lambda x: x['adjusted_elo'], reverse=True)

        export = {
            'timestamp': datetime.now().isoformat(),
            'total_traders': len(all_traders),
            'traders_with_metrics': len(trader_adjusted_elos),
            'avg_calibration_weight': sum(calibration_weights) / len(calibration_weights) if calibration_weights else 1.5,
            'avg_execution_modifier': sum(execution_modifiers) / len(execution_modifiers) if execution_modifiers else 1.0,
            'avg_k_factor': sum(k_factors) / len(k_factors) if k_factors else 32,
            'avg_brier_score': sum(brier_scores) / len(brier_scores) if brier_scores else 0.0,
            'avg_sharpe_ratio': sum(sharpe_ratios) / len(sharpe_ratios) if sharpe_ratios else 0.0,
            'avg_regret_rate': sum(regret_rates) / len(regret_rates) if regret_rates else 0.0,
            'top_advanced_traders': trader_adjusted_elos[:10]
        }

        print(f"[ADVANCED METRICS] Export complete: {export['traders_with_metrics']}/{export['total_traders']} traders with advanced metrics")

        return export

    def generate_advanced_metrics_report(self, output_dir: str = 'reports'):
        """
        Generate CSV report of advanced metrics modifiers.

        Creates: reports/advanced_metrics_YYYYMMDD.csv

        Columns:
            - Rank
            - Trader Address
            - Base ELO
            - Calibration Weight (0.5-2.0x)
            - Brier Score
            - Execution Modifier (0.90-1.15x)
            - Regret Rate
            - K-Factor (16-40)
            - Sharpe Ratio
            - Combined Multiplier
            - Adjusted ELO
            - ELO Change

        Args:
            output_dir: Output directory for reports

        Returns:
            Path to generated report
        """
        print(f"[ADVANCED METRICS] Generating advanced metrics report...")

        # Create output directory
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Get all traders and advanced metrics
        all_traders = self.elo_system.get_all_traders()
        metrics_loaded = self._load_advanced_metrics_data()

        # Generate report data
        report_rows = []

        for trader in all_traders:
            base_elo = self.get_trader_global_elo(trader)

            if metrics_loaded and (trader in self.calibration_cache or trader in self.sharpe_cache or trader in self.regret_cache):
                advanced_mult = self.calculate_advanced_metrics_multiplier(trader)

                # Raw metrics
                brier = self.calibration_cache.get(trader, 0.25)
                sharpe = self.sharpe_cache.get(trader, 0.0)
                regret = self.regret_cache.get(trader, 0.0)

                adjusted_elo = base_elo * advanced_mult['combined_multiplier']
                elo_change = adjusted_elo - base_elo

                report_rows.append({
                    'trader_address': trader,
                    'base_elo': f"{base_elo:.1f}",
                    'calibration_weight': f"{advanced_mult['calibration']:.3f}",
                    'brier_score': f"{brier:.4f}",
                    'execution_modifier': f"{advanced_mult['execution']:.3f}",
                    'regret_rate': f"{regret:.4f}",
                    'k_factor': advanced_mult['k_factor'],
                    'sharpe_ratio': f"{sharpe:.3f}",
                    'combined_multiplier': f"{advanced_mult['combined_multiplier']:.3f}",
                    'adjusted_elo': f"{adjusted_elo:.1f}",
                    'elo_change': f"{elo_change:+.1f}"
                })
            else:
                # No advanced metrics data - neutral defaults
                report_rows.append({
                    'trader_address': trader,
                    'base_elo': f"{base_elo:.1f}",
                    'calibration_weight': '1.500',
                    'brier_score': '0.2500',
                    'execution_modifier': '1.000',
                    'regret_rate': '0.0000',
                    'k_factor': 32,
                    'sharpe_ratio': '0.000',
                    'combined_multiplier': '1.500',
                    'adjusted_elo': f"{base_elo * 1.5:.1f}",
                    'elo_change': f"{base_elo * 0.5:+.1f}"
                })

        # Sort by adjusted ELO (highest first)
        report_rows.sort(key=lambda x: float(x['adjusted_elo']), reverse=True)

        # Add rank column
        for i, row in enumerate(report_rows, 1):
            row['rank'] = i

        # Reorder columns with rank first
        column_order = ['rank', 'trader_address', 'base_elo', 'calibration_weight', 'brier_score',
                       'execution_modifier', 'regret_rate', 'k_factor', 'sharpe_ratio',
                       'combined_multiplier', 'adjusted_elo', 'elo_change']

        # Write CSV
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(output_dir, f'advanced_metrics_{date_str}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8', errors='ignore') as f:
            if report_rows:
                writer = csv.DictWriter(f, fieldnames=column_order)
                writer.writeheader()
                writer.writerows(report_rows)

        print(f"[ADVANCED METRICS] Report saved: {output_path}")
        print(f"[ADVANCED METRICS] {len(report_rows)} traders included")

        return output_path

    def export_for_integration(self) -> Dict:
        """
        Export all ELO data for integration with other analysis tools.

        Returns comprehensive data structure including:
        - All trader global ELOs
        - All category-specific ELOs
        - Specialist identifications
        - Market counts per category
        - Top traders per category

        Returns:
            Dict with all ELO data ready for integration
        """
        all_traders = self.elo_system.get_all_traders()

        # Build comprehensive data structure
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'total_traders': len(all_traders),
            'categories': ALL_CATEGORIES,
            'trader_data': {},
            'top_traders_global': [],
            'top_traders_by_category': {},
            'specialists': []
        }

        # Collect all trader data
        trader_global_elos = []

        for trader_address in all_traders:
            global_elo = self.get_trader_global_elo(trader_address)

            category_data = {}
            for category in ALL_CATEGORIES:
                cat_elo = self.get_trader_category_elo(trader_address, category)
                market_count = self.elo_system.get_market_count(trader_address, category)
                confidence = self.elo_system.get_confidence_level(trader_address, category)

                category_data[category] = {
                    'elo': cat_elo,
                    'market_count': market_count,
                    'confidence_level': confidence
                }

            # Check if specialist
            is_spec, spec_score = self.is_specialist(trader_address)

            trader_global_elos.append((trader_address, global_elo))

            export_data['trader_data'][trader_address] = {
                'global_elo': global_elo,
                'categories': category_data,
                'is_specialist': is_spec,
                'specialization_score': spec_score
            }

        # Top 20 traders globally
        trader_global_elos.sort(key=lambda x: x[1], reverse=True)
        export_data['top_traders_global'] = [
            {'address': addr, 'elo': elo}
            for addr, elo in trader_global_elos[:20]
        ]

        # Top 10 traders per category
        for category in ALL_CATEGORIES:
            category_elos = []
            for trader_address in all_traders:
                cat_elo = self.get_trader_category_elo(trader_address, category)
                market_count = self.elo_system.get_market_count(trader_address, category)

                # Only include if they have meaningful participation
                if market_count >= 3:
                    category_elos.append((trader_address, cat_elo, market_count))

            category_elos.sort(key=lambda x: x[1], reverse=True)
            export_data['top_traders_by_category'][category] = [
                {'address': addr, 'elo': elo, 'market_count': count}
                for addr, elo, count in category_elos[:10]
            ]

        # Find all specialists
        for trader_address in all_traders:
            for category in ALL_CATEGORIES:
                is_spec, spec_score = self.is_specialist(trader_address, category)
                if is_spec:
                    export_data['specialists'].append({
                        'address': trader_address,
                        'category': category,
                        'specialization_score': spec_score,
                        'category_elo': self.get_trader_category_elo(trader_address, category),
                        'global_elo': self.get_trader_global_elo(trader_address)
                    })

        # Add behavioral modifiers (if available)
        try:
            behavior_data = self._load_behavioral_data()
            behavioral_modifiers = {}

            for trader_address in all_traders:
                if trader_address in behavior_data:
                    behavior_mult = self.calculate_behavioral_multiplier(trader_address)
                    behavioral_modifiers[trader_address] = {
                        'consistency': behavior_mult['consistency'],
                        'diversification': behavior_mult['diversification'],
                        'style': behavior_mult['trading_style'],
                        'activity': behavior_mult['activity'],
                        'combined': behavior_mult['combined_multiplier']
                    }

            export_data['behavioral_modifiers'] = behavioral_modifiers
            export_data['behavioral_analysis_timestamp'] = datetime.now().isoformat()
            print(f"[BEHAVIORAL] Included behavioral data for {len(behavioral_modifiers)} traders in export")
        except Exception as e:
            print(f"[BEHAVIORAL] WARNING: Could not include behavioral data in export: {e}")
            export_data['behavioral_modifiers'] = {}
            export_data['behavioral_analysis_timestamp'] = None

        # Add advanced metrics (if available)
        try:
            metrics_loaded = self._load_advanced_metrics_data()
            advanced_metrics = {}

            if metrics_loaded:
                for trader_address in all_traders:
                    if trader_address in self.calibration_cache or trader_address in self.sharpe_cache or trader_address in self.regret_cache:
                        advanced_mult = self.calculate_advanced_metrics_multiplier(trader_address)

                        # Get raw metrics
                        brier = self.calibration_cache.get(trader_address, 0.25)
                        sharpe = self.sharpe_cache.get(trader_address, 0.0)
                        regret = self.regret_cache.get(trader_address, 0.0)

                        advanced_metrics[trader_address] = {
                            'calibration_weight': advanced_mult['calibration'],
                            'execution_modifier': advanced_mult['execution'],
                            'k_factor': advanced_mult['k_factor'],
                            'combined': advanced_mult['combined_multiplier'],
                            'brier_score': brier,
                            'sharpe_ratio': sharpe,
                            'regret_rate': regret
                        }

                export_data['advanced_metrics'] = advanced_metrics
                export_data['advanced_metrics_timestamp'] = datetime.now().isoformat()
                print(f"[ADVANCED METRICS] Included advanced metrics for {len(advanced_metrics)} traders in export")
            else:
                export_data['advanced_metrics'] = {}
                export_data['advanced_metrics_timestamp'] = None
                print("[ADVANCED METRICS] No advanced metrics data available for export")
        except Exception as e:
            print(f"[ADVANCED METRICS] WARNING: Could not include advanced metrics in export: {e}")
            export_data['advanced_metrics'] = {}
            export_data['advanced_metrics_timestamp'] = None

        # Add network analysis (if available)
        try:
            network_loaded = self._load_network_data()
            network_analysis = {}
            filtered_traders = []
            excluded_traders = []

            if network_loaded:
                for trader_address in all_traders:
                    network_data = self.calculate_network_modifier(trader_address)
                    copy_status = self.is_copy_trader(trader_address)

                    network_analysis[trader_address] = {
                        'independence_score': self.independence_scores.get(trader_address, 50.0),
                        'independence_modifier': network_data['independence_modifier'],
                        'is_follower': copy_status['is_follower'],
                        'is_leader': copy_status['is_leader'],
                        'copy_score': copy_status['copy_score'],
                        'leaders': copy_status['leaders'],
                        'followers': copy_status['followers'],
                        'cluster_penalty': network_data['cluster_penalty'],
                        'combined_modifier': network_data['combined_modifier'],
                        'should_exclude': network_data['should_exclude']
                    }

                    # Track excluded traders
                    if network_data['should_exclude']:
                        excluded_traders.append(trader_address)

                # Get filtered traders suitable for consensus
                filtered_traders = self.get_filtered_traders_for_consensus()

                export_data['network_analysis'] = network_analysis
                export_data['filtered_traders'] = filtered_traders
                export_data['excluded_traders'] = excluded_traders
                export_data['network_analysis_timestamp'] = datetime.now().isoformat()
                print(f"[NETWORK] Included network analysis for {len(network_analysis)} traders in export")
                print(f"[NETWORK] {len(filtered_traders)} traders suitable for consensus (excluded {len(excluded_traders)})")
            else:
                export_data['network_analysis'] = {}
                export_data['filtered_traders'] = []
                export_data['excluded_traders'] = []
                export_data['network_analysis_timestamp'] = None
                print("[NETWORK] No network analysis data available for export")
        except Exception as e:
            print(f"[NETWORK] WARNING: Could not include network analysis in export: {e}")
            export_data['network_analysis'] = {}
            export_data['filtered_traders'] = []
            export_data['excluded_traders'] = []
            export_data['network_analysis_timestamp'] = None

        return export_data

    def get_top_traders(self, category: str = None, limit: int = 10) -> List[Dict]:
        """
        Get top traders by ELO rating.

        Args:
            category: Specific category (None = global ELO)
            limit: Number of traders to return

        Returns:
            List of dicts with trader data sorted by ELO
        """
        all_traders = self.elo_system.get_all_traders()
        trader_ratings = []

        for trader_address in all_traders:
            if category:
                elo = self.get_trader_category_elo(trader_address, category)
                market_count = self.elo_system.get_market_count(trader_address, category)

                # Only include if meaningful participation
                if market_count >= 3:
                    trader_ratings.append({
                        'address': trader_address,
                        'elo': elo,
                        'market_count': market_count,
                        'category': category
                    })
            else:
                elo = self.get_trader_global_elo(trader_address)
                trader_ratings.append({
                    'address': trader_address,
                    'elo': elo
                })

        trader_ratings.sort(key=lambda x: x['elo'], reverse=True)
        return trader_ratings[:limit]


# ==================== BACKWARD COMPATIBILITY ====================

class UnifiedWeightedConsensusWrapper:
    """
    Backward compatibility wrapper for WeightedConsensusSystem.

    Provides the same interface as the old WeightedConsensusSystem class,
    but uses UnifiedELOSystem under the hood.

    This allows existing code to continue working without modifications.
    """

    def __init__(self, db_path: str = None, api_key: Optional[str] = None):
        """
        Initialize wrapper using UnifiedELOSystem.

        Args:
            db_path: Path to database
            api_key: Polymarket API key
        """
        self.unified_system = UnifiedELOSystem(db_path, api_key)
        self.db_path = db_path
        self.api_key = api_key

    def calculate_elo_ratings(self, verbose: bool = False):
        """Calculate ELO ratings (delegates to unified system)."""
        self.unified_system.calculate_elo_ratings(verbose=verbose)

    def get_trader_elo(self, trader_address: str) -> float:
        """Get trader's global ELO (backward compatible method)."""
        return self.unified_system.get_trader_global_elo(trader_address)

    def export_for_integration(self) -> Dict:
        """Export data for integration (delegates to unified system)."""
        return self.unified_system.export_for_integration()


if __name__ == "__main__":
    """
    Example usage of the Unified ELO System.
    """
    print("="*70)
    print("  UNIFIED ELO SYSTEM - EXAMPLE USAGE")
    print("="*70)

    # Initialize system
    system = UnifiedELOSystem()

    # Calculate all ratings
    system.calculate_elo_ratings(verbose=True)

    # Example 1: Get trader's global ELO
    print("\n" + "="*70)
    print("EXAMPLE 1: Get Global ELO")
    print("="*70)
    top_traders = system.get_top_traders(limit=5)
    for i, trader in enumerate(top_traders, 1):
        print(f"{i}. {trader['address'][:10]}... - ELO: {trader['elo']:.1f}")

    # Example 2: Get category-specific ELO
    print("\n" + "="*70)
    print("EXAMPLE 2: Top Elections Traders")
    print("="*70)
    elections_traders = system.get_top_traders(category='Elections', limit=5)
    for i, trader in enumerate(elections_traders, 1):
        print(f"{i}. {trader['address'][:10]}... - ELO: {trader['elo']:.1f} ({trader['market_count']} markets)")

    # Example 3: Check if trader is specialist
    print("\n" + "="*70)
    print("EXAMPLE 3: Specialist Detection")
    print("="*70)
    if top_traders:
        trader = top_traders[0]['address']
        for category in ['Elections', 'Crypto', 'Sports']:
            is_spec, score = system.is_specialist(trader, category)
            if is_spec:
                print(f"[YES] Specialist in {category} (advantage: +{score:.1f} ELO)")
            else:
                print(f"[NO] Not specialist in {category}")

    # Example 4: Export for integration
    print("\n" + "="*70)
    print("EXAMPLE 4: Export Data")
    print("="*70)
    export = system.export_for_integration()
    print(f"Total traders: {export['total_traders']}")
    print(f"Categories tracked: {len(export['categories'])}")
    print(f"Specialists identified: {len(export['specialists'])}")

    # Example 5: Behavioral Analysis Integration
    print("\n" + "="*70)
    print("EXAMPLE 5: Behavioral Analysis")
    print("="*70)

    # Get a trader with behavioral data
    traders = system.elo_system.get_all_traders()
    if traders:
        test_trader = list(traders)[0]

        print(f"\n[TEST] Analyzing trader: {test_trader[:12]}...")

        # Get base ELO
        base_elo = system.get_trader_global_elo(test_trader)
        print(f"Base Global ELO: {base_elo:.0f}")

        # Get behavioral multiplier
        try:
            behavior_data = system.calculate_behavioral_multiplier(test_trader)
            print(f"Behavioral Multiplier: {behavior_data['combined_multiplier']:.3f}")
            print(f"Breakdown: {behavior_data['breakdown']}")

            # Get adjusted ELO
            adjusted_elo = system.get_trader_global_elo(test_trader, apply_behavioral=True)
            print(f"Adjusted Global ELO: {adjusted_elo:.0f}")
            print(f"Change: {adjusted_elo - base_elo:+.0f}")

            # Generate behavioral report
            print("\n[TEST] Generating behavioral modifiers report...")
            report_path = system.generate_behavioral_report()
            print(f"[TEST] Report generated: {report_path}")
        except Exception as e:
            print(f"[TEST] Behavioral analysis skipped: {e}")

    # Example 6: Advanced Metrics Integration
    print("\n" + "="*70)
    print("EXAMPLE 6: Advanced Metrics Analysis")
    print("="*70)

    # Get a trader with advanced metrics
    traders = system.elo_system.get_all_traders()
    if traders:
        test_trader = list(traders)[0]

        print(f"\n[TEST] Analyzing trader: {test_trader[:12]}...")

        # Get base ELO
        base_elo = system.get_trader_global_elo(test_trader)
        print(f"Base Global ELO: {base_elo:.0f}")

        # Get advanced metrics multiplier
        try:
            advanced_data = system.calculate_advanced_metrics_multiplier(test_trader)
            print(f"\nAdvanced Metrics Multiplier: {advanced_data['combined_multiplier']:.3f}")
            print(f"  - Calibration Weight: {advanced_data['calibration']:.3f} (Brier: {advanced_data.get('brier_score', 0):.4f})")
            print(f"  - Execution Modifier: {advanced_data['execution']:.3f} (Regret: {advanced_data.get('regret_rate', 0):.4f})")
            print(f"  - K-Factor: {advanced_data['k_factor']} (Sharpe: {advanced_data.get('sharpe_ratio', 0):.3f})")
            print(f"Breakdown: {advanced_data['breakdown']}")

            # Get adjusted ELO with advanced metrics only
            adjusted_elo_advanced = system.get_trader_global_elo(test_trader, apply_advanced=True)
            print(f"\nAdjusted ELO (advanced only): {adjusted_elo_advanced:.0f}")
            print(f"Change: {adjusted_elo_advanced - base_elo:+.0f}")

            # Get adjusted ELO with both behavioral and advanced
            adjusted_elo_both = system.get_trader_global_elo(test_trader, apply_behavioral=True, apply_advanced=True)
            print(f"\nAdjusted ELO (behavioral + advanced): {adjusted_elo_both:.0f}")
            print(f"Total Change: {adjusted_elo_both - base_elo:+.0f}")

            # Generate advanced metrics report
            print("\n[TEST] Generating advanced metrics report...")
            report_path = system.generate_advanced_metrics_report()
            print(f"[TEST] Report generated: {report_path}")

            # Export advanced metrics analysis
            print("\n[TEST] Exporting advanced metrics analysis...")
            export_advanced = system.export_advanced_metrics_analysis()
            print(f"[TEST] Traders with metrics: {export_advanced['traders_with_metrics']}/{export_advanced['total_traders']}")
            print(f"[TEST] Avg Calibration Weight: {export_advanced['avg_calibration_weight']:.3f}")
            print(f"[TEST] Avg Execution Modifier: {export_advanced['avg_execution_modifier']:.3f}")
            print(f"[TEST] Avg K-Factor: {export_advanced['avg_k_factor']:.1f}")
        except Exception as e:
            print(f"[TEST] Advanced metrics analysis skipped: {e}")

    # Example 7: Network Analysis Integration
    print("\n" + "="*70)
    print("EXAMPLE 7: Network Analysis (Copy-Trade Filtering)")
    print("="*70)

    # Get traders for network analysis
    traders = system.elo_system.get_all_traders()
    if traders:
        # Test network filtering on first 5 traders
        print(f"\n[TEST] Analyzing network relationships for {min(5, len(traders))} traders...")

        for i, test_trader in enumerate(list(traders)[:5]):
            print(f"\n--- Trader {i+1}: {test_trader[:12]}... ---")

            # Get base ELO
            base_elo = system.get_trader_global_elo(test_trader)
            print(f"Base Global ELO: {base_elo:.0f}")

            # Get network modifier
            try:
                network_data = system.calculate_network_modifier(test_trader)
                print(f"\nNetwork Analysis:")
                print(f"  - Independence Score: {system.independence_scores.get(test_trader, 50.0):.1f}/100")
                print(f"  - Independence Modifier: {network_data['independence_modifier']:.3f}")

                # Copy-trade status
                copy_status = system.is_copy_trader(test_trader)
                if copy_status['is_follower']:
                    print(f"  - Copy-Trader (FOLLOWER): Yes (score: {copy_status['copy_score']:.2f})")
                    print(f"    Leaders: {len(copy_status['leaders'])} traders")
                elif copy_status['is_leader']:
                    print(f"  - Copy-Trade Leader: Yes")
                    print(f"    Followers: {len(copy_status['followers'])} traders")
                else:
                    print(f"  - Copy-Trader: No (independent)")

                # Cluster status
                cluster_info = system.is_in_suspicious_cluster(test_trader)
                if cluster_info['in_cluster']:
                    print(f"  - Cluster: {cluster_info['cluster_type']} (penalty: {cluster_info['penalty_modifier']:.2f}x)")
                else:
                    print(f"  - Cluster: Not in suspicious cluster")

                print(f"\nCombined Network Modifier: {network_data['combined_modifier']:.3f}")
                print(f"Should Exclude: {'YES - COPY-TRADER' if network_data['should_exclude'] else 'No'}")
                print(f"Breakdown: {network_data['breakdown']}")

                # Get adjusted ELO with network filtering
                adjusted_elo_network = system.get_trader_global_elo(test_trader, apply_network=True)
                if adjusted_elo_network == 0.0:
                    print(f"\nAdjusted ELO (with network): 0.0 (EXCLUDED)")
                else:
                    print(f"\nAdjusted ELO (with network): {adjusted_elo_network:.0f}")
                    print(f"Change: {adjusted_elo_network - base_elo:+.0f}")

                # Get fully adjusted ELO (all modifiers)
                adjusted_elo_all = system.get_trader_global_elo(
                    test_trader,
                    apply_behavioral=True,
                    apply_advanced=True,
                    apply_network=True
                )
                if adjusted_elo_all == 0.0:
                    print(f"Fully Adjusted ELO (all modifiers): 0.0 (EXCLUDED)")
                else:
                    print(f"Fully Adjusted ELO (all modifiers): {adjusted_elo_all:.0f}")
                    print(f"Total Change: {adjusted_elo_all - base_elo:+.0f}")

            except Exception as e:
                print(f"[TEST] Network analysis failed for trader: {e}")

        # Generate network analysis report
        print("\n" + "="*70)
        print("[TEST] Generating network analysis report...")
        try:
            report_path = system.generate_network_report()
            print(f"[TEST] Report generated: {report_path}")
        except Exception as e:
            print(f"[TEST] Report generation failed: {e}")

        # Export network analysis
        print("\n[TEST] Exporting network analysis...")
        try:
            export_network = system.export_network_analysis()
            print(f"[TEST] Total traders analyzed: {export_network['total_traders_analyzed']}")
            print(f"[TEST] Independent traders (score >= 75): {export_network['independent_traders']}")
            print(f"[TEST] Followers detected: {export_network['followers_detected']}")
            print(f"[TEST] Leaders detected: {export_network['leaders_detected']}")
            print(f"[TEST] Traders excluded: {export_network['traders_excluded']}")
            print(f"[TEST] Suspicious clusters: {export_network['suspicious_clusters']}")
            print(f"[TEST] Avg independence score: {export_network['avg_independence_score']:.1f}")
        except Exception as e:
            print(f"[TEST] Network export failed: {e}")

        # Test filtered traders for consensus
        print("\n[TEST] Getting filtered traders for consensus...")
        try:
            filtered_traders = system.get_filtered_traders_for_consensus(min_elo=1600)
            total_traders = len(system.elo_system.get_all_traders())
            print(f"[TEST] {len(filtered_traders)}/{total_traders} traders suitable for consensus (min ELO: 1600)")
            print(f"[TEST] Excluded {total_traders - len(filtered_traders)} copy-traders and low-ELO traders")
        except Exception as e:
            print(f"[TEST] Filtering failed: {e}")

    print("\n" + "="*70)
    print("All examples completed!")
    print("="*70)
