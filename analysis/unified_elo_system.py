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
from analysis.trading_behavior_analysis import TradingBehaviorAnalyzer

# Import advanced metrics analyzers
from analysis.calibration_analysis import CalibrationAnalyzer
from analysis.risk_adjusted_returns import RiskAdjustedAnalyzer
from analysis.regret_analysis import RegretAnalyzer

# Import network analysis
from analysis.correlation_matrix import TraderCorrelationMatrix
from analysis.copy_trade_detector import CopyTradeDetector

# Import contrarian analysis
from analysis.consensus_divergence_detector import ConsensusDivergenceDetector


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
        self.calibration_analyzer = CalibrationAnalyzer(db_path=self.db_path)
        self.risk_analyzer = RiskAdjustedAnalyzer(db_path=self.db_path)
        self.regret_analyzer = RegretAnalyzer(db_path=self.db_path)

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

        # Contrarian analysis component
        self.contrarian_detector = ConsensusDivergenceDetector(db_path=self.db_path, api_key=self.api_key)

        # Cache for contrarian data
        self.contrarian_traders = {}  # trader -> contrarian_metrics
        self.market_disagreements = {}  # market_id -> disagreement_data
        self.contrarian_cache_timestamp = None  # Last cache refresh

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

        # Get resolved markets from DATABASE (not API - API returns 0, DB has 2480!)
        if verbose:
            print(f"Loading resolved markets from database...")

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT market_id, winning_outcome
            FROM markets
            WHERE resolved = 1
            AND winning_outcome IS NOT NULL
        """)
        resolved_markets_db = {row[0]: str(row[1]).lower() for row in cursor.fetchall()}
        conn.close()

        if verbose:
            print(f"Found {len(resolved_markets_db)} resolved markets from database")
            print("\nUpdating category-specific ELO ratings...")

        # Process each resolved market to update category-specific ELO
        updates_count = 0
        category_updates = defaultdict(int)

        for market_id, trades_list in market_trades.items():
            # Check if market is resolved in database
            if market_id not in resolved_markets_db:
                continue

            winning_outcome = resolved_markets_db[market_id]
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
                price = float(winner.get('price', 0.5))

                # Calculate ROI for this trade
                # Win: payout is shares * $1, invested is shares * price
                invested = shares * price
                payout = shares * 1.0
                roi = (payout - invested) / invested if invested > 0 else 0.0

                # Convert ROI to score (0-1 range, with 1.0 = 100% ROI, 0.5 = 0% ROI)
                # Normalize: 100% ROI → 1.0, 0% ROI → 0.5, -100% ROI → 0.0
                actual_score = 0.5 + (roi / 2.0)  # Maps [-1.0, 1.0] to [0.0, 1.0]
                actual_score = max(0.1, min(0.9, actual_score))  # Clamp to avoid extremes

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
                    actual_score=actual_score,  # ROI-based score
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
                price = float(loser.get('price', 0.5))

                # Calculate ROI for this trade (negative)
                # Loss: payout is $0, invested is shares * price
                invested = shares * price
                payout = 0.0
                roi = (payout - invested) / invested if invested > 0 else -1.0  # Always negative

                # Convert ROI to score (0-1 range)
                # -100% ROI → 0.0, -50% ROI → 0.25, 0% ROI → 0.5
                actual_score = 0.5 + (roi / 2.0)  # Maps [-1.0, 0.0] to [0.0, 0.5]
                actual_score = max(0.1, min(0.9, actual_score))  # Clamp to avoid extremes

                all_shares = [float(w.get('shares', 1)) for w in winners + losers]
                max_shares = max(all_shares) if all_shares else 1
                normalized_bet_size = min(shares / max_shares, 2.0) if max_shares > 0 else 1.0

                total_traders = len(set([t.get('trader_address') for t in trades_list]))
                market_difficulty = max(0.5, min(1.5, 1.0 + (10 - total_traders) / 20))

                self.elo_system.update_rating(
                    trader_address=trader_address,
                    category=category,
                    actual_score=actual_score,  # ROI-based score (negative)
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

    def calculate_behavioral_elo_bonus(self, trader_address: str) -> float:
        """
        Calculate ELO bonus based on behavioral intelligence metrics.

        Integrates Kelly alignment, patience, and timing quality from
        simulation learnings. Traders with better discipline and positioning
        get ELO bonuses.

        Args:
            trader_address: Trader's address

        Returns:
            ELO bonus points (-100 to +100)
            - Kelly alignment (0-40 points): Position sizing discipline
            - Patience score (0-30 points): Trading frequency control
            - Timing quality (0-30 points): Market entry/exit timing
        """
        behavior_data = self._load_behavioral_data()

        if trader_address not in behavior_data:
            return 0.0

        trader_behavior = behavior_data[trader_address]

        # Factor 1: Kelly Alignment (0-40 points)
        kelly_score = trader_behavior.get('kelly_alignment_score')
        if kelly_score is not None:
            # Score 0.8-1.0 → 40 pts, 0.6-0.8 → 25 pts, 0.4-0.6 → 10 pts, <0.4 → -20 pts
            if kelly_score >= 0.8:
                kelly_bonus = 40
            elif kelly_score >= 0.6:
                kelly_bonus = 25
            elif kelly_score >= 0.4:
                kelly_bonus = 10
            else:
                kelly_bonus = -20  # Penalty for poor position sizing
        else:
            kelly_bonus = 0

        # Factor 2: Patience Score (0-30 points)
        patience_score = trader_behavior.get('patience_score')
        if patience_score is not None:
            # Score 0.8-1.0 → 30 pts, 0.5-0.8 → 15 pts, 0.2-0.5 → 5 pts, <0.2 → -10 pts
            if patience_score >= 0.8:
                patience_bonus = 30
            elif patience_score >= 0.5:
                patience_bonus = 15
            elif patience_score >= 0.2:
                patience_bonus = 5
            else:
                patience_bonus = -10  # Penalty for hyperactive trading
        else:
            patience_bonus = 0

        # Factor 3: Timing Quality (0-30 points)
        timing_score = trader_behavior.get('optimal_timing_score')
        if timing_score is not None:
            # Score 0.8-1.0 → 30 pts, 0.6-0.8 → 20 pts, 0.4-0.6 → 10 pts, <0.4 → -10 pts
            if timing_score >= 0.8:
                timing_bonus = 30
            elif timing_score >= 0.6:
                timing_bonus = 20
            elif timing_score >= 0.4:
                timing_bonus = 10
            else:
                timing_bonus = -10  # Penalty for poor timing
        else:
            timing_bonus = 0

        total_bonus = kelly_bonus + patience_bonus + timing_bonus

        # Clamp to [-100, +100] range
        return max(-100, min(100, total_bonus))

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
                              apply_advanced: bool = False, apply_network: bool = False,
                              apply_contrarian: bool = False, apply_pnl: bool = False,
                              market_id: str = None) -> float:
        """
        Get trader's global ELO rating (weighted average across all categories).

        This provides a single overall skill rating, but category-specific ratings
        are more accurate for domain-specific predictions.

        Args:
            trader_address: Trader's address
            apply_behavioral: If True, apply behavioral multipliers to adjust ELO
            apply_advanced: If True, apply advanced metrics (calibration, execution, Sharpe)
            apply_network: If True, apply network filtering (independence, copy-trader detection)
            apply_contrarian: If True, apply contrarian bonus
            apply_pnl: If True, apply P&L/position tracking modifier (trading skill)
            market_id: Market ID for disagreement-adjusted weighting (optional)

        Returns:
            Global ELO rating (weighted average), optionally adjusted by behavioral, advanced, network, contrarian, and/or P&L factors
            Returns 0.0 if trader should be excluded (copy-trader)

        Examples:
            Base ELO: system.get_trader_global_elo(trader)
            Behavioral: system.get_trader_global_elo(trader, apply_behavioral=True)
            Advanced: system.get_trader_global_elo(trader, apply_advanced=True)
            Network: system.get_trader_global_elo(trader, apply_network=True)
            Contrarian: system.get_trader_global_elo(trader, apply_contrarian=True)
            P&L: system.get_trader_global_elo(trader, apply_pnl=True)
            All 6 dimensions: system.get_trader_global_elo(trader, apply_behavioral=True, apply_advanced=True,
                                                            apply_network=True, apply_contrarian=True, apply_pnl=True)
        """
        # Check if should exclude due to copy-trading
        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            if network_data['should_exclude']:
                return 0.0  # Exclude from calculations

        base_elo = self.elo_system.get_overall_elo(trader_address)
        adjusted_elo = base_elo

        if apply_behavioral:
            # Apply multiplier (existing behavioral system)
            behavior_data = self.calculate_behavioral_multiplier(trader_address)
            adjusted_elo *= behavior_data['combined_multiplier']

            # Apply ELO bonus from simulation learnings (Kelly, patience, timing)
            behavioral_bonus = self.calculate_behavioral_elo_bonus(trader_address)
            adjusted_elo += behavioral_bonus

        if apply_advanced:
            advanced_data = self.calculate_advanced_metrics_multiplier(trader_address)
            adjusted_elo *= advanced_data['combined_multiplier']

        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            adjusted_elo *= network_data['combined_modifier']

        if apply_contrarian:
            contrarian_data = self.calculate_contrarian_multiplier(trader_address, market_id)
            adjusted_elo *= contrarian_data['combined_multiplier']

        if apply_pnl:
            pnl_data = self.calculate_pnl_multiplier(trader_address)
            adjusted_elo *= pnl_data['combined_multiplier']

        return adjusted_elo

    def get_trader_category_elo(self, trader_address: str, category: str,
                                apply_behavioral: bool = False, apply_advanced: bool = False,
                                apply_network: bool = False, apply_contrarian: bool = False,
                                apply_pnl: bool = False,
                                market_id: str = None) -> float:
        """
        Get trader's ELO rating for a specific category.

        Use this for category-aware predictions (more accurate than global ELO).

        Args:
            trader_address: Trader's address
            category: Market category (e.g., 'Elections', 'Crypto')
            apply_behavioral: If True, apply behavioral multipliers to adjust ELO
            apply_advanced: If True, apply advanced metrics (calibration, execution, Sharpe)
            apply_network: If True, apply network filtering (independence, copy-trader detection)
            apply_contrarian: If True, apply contrarian bonus
            apply_pnl: If True, apply P&L/position tracking multiplier (realized profits, ROI, position quality)
            market_id: Market ID for disagreement-adjusted weighting (optional)

        Returns:
            Category-specific ELO rating, optionally adjusted by behavioral, advanced, network, contrarian, and/or P&L factors
            Returns 0.0 if trader should be excluded (copy-trader)

        Examples:
            Base ELO: system.get_trader_category_elo(trader, 'Elections')
            With behavioral: system.get_trader_category_elo(trader, 'Elections', apply_behavioral=True)
            With advanced: system.get_trader_category_elo(trader, 'Elections', apply_advanced=True)
            With network: system.get_trader_category_elo(trader, 'Elections', apply_network=True)
            With contrarian: system.get_trader_category_elo(trader, 'Elections', apply_contrarian=True)
            With P&L: system.get_trader_category_elo(trader, 'Elections', apply_pnl=True)
            With all 6 dimensions: system.get_trader_category_elo(trader, 'Elections', apply_behavioral=True, apply_advanced=True, apply_network=True, apply_contrarian=True, apply_pnl=True)
        """
        # Check if should exclude due to copy-trading
        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            if network_data['should_exclude']:
                return 0.0  # Exclude from calculations

        base_elo = self.elo_system.get_category_elo(trader_address, category)
        adjusted_elo = base_elo

        if apply_behavioral:
            # Apply multiplier (existing behavioral system)
            behavior_data = self.calculate_behavioral_multiplier(trader_address)
            adjusted_elo *= behavior_data['combined_multiplier']

            # Apply ELO bonus from simulation learnings (Kelly, patience, timing)
            behavioral_bonus = self.calculate_behavioral_elo_bonus(trader_address)
            adjusted_elo += behavioral_bonus

        if apply_advanced:
            advanced_data = self.calculate_advanced_metrics_multiplier(trader_address)
            adjusted_elo *= advanced_data['combined_multiplier']

        if apply_network:
            network_data = self.calculate_network_modifier(trader_address)
            adjusted_elo *= network_data['combined_modifier']

        if apply_contrarian:
            contrarian_data = self.calculate_contrarian_multiplier(trader_address, market_id)
            adjusted_elo *= contrarian_data['combined_multiplier']

        if apply_pnl:
            pnl_data = self.calculate_pnl_multiplier(trader_address)
            adjusted_elo *= pnl_data['combined_multiplier']

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

    # ==================== CONTRARIAN ANALYSIS INTEGRATION ====================

    def _load_contrarian_data(self, force_refresh: bool = False) -> bool:
        """
        Load contrarian analysis data (trader patterns and market disagreements).

        This analysis requires resolved markets to work fully, but can identify
        contrarian patterns from historical data.

        Args:
            force_refresh: Force reload even if cache is fresh

        Returns:
            bool: True if data loaded successfully
        """
        # Check if cache is stale (>24 hours old)
        if force_refresh or self.contrarian_cache_timestamp is None or \
           (datetime.now() - self.contrarian_cache_timestamp).total_seconds() > 86400:

            print("[CONTRARIAN] Loading contrarian analysis data...")

            try:
                # 1. Identify contrarian traders
                print("[CONTRARIAN] Identifying contrarian traders...")

                # Run prerequisite analyses (ELO + specialization) if needed
                if not hasattr(self.contrarian_detector, 'contrarian_traders') or \
                   not self.contrarian_detector.contrarian_traders:

                    # Run analyses
                    self.contrarian_detector.run_prerequisite_analyses()
                    self.contrarian_detector.contrarian_traders = \
                        self.contrarian_detector.identify_contrarian_traders()

                self.contrarian_traders = self.contrarian_detector.contrarian_traders

                if self.contrarian_traders:
                    valuable_count = sum(1 for t in self.contrarian_traders.values()
                                       if t.get('is_valuable', False))
                    print(f"[CONTRARIAN] Identified {len(self.contrarian_traders)} traders with contrarian metrics")
                    print(f"[CONTRARIAN] Found {valuable_count} valuable contrarians")
                else:
                    print("[CONTRARIAN] ⚠️  No resolved markets yet - contrarian analysis limited")

                # 2. Analyze market disagreements (if markets exist)
                print("[CONTRARIAN] Analyzing market disagreements...")

                if not hasattr(self.contrarian_detector, 'market_disagreements') or \
                   not self.contrarian_detector.market_disagreements:
                    self.contrarian_detector.analyze_all_markets()

                self.market_disagreements = self.contrarian_detector.market_disagreements

                if self.market_disagreements:
                    high_disagreement = sum(1 for d in self.market_disagreements.values()
                                          if d.get('disagreement_score', 0) > 0.6)
                    print(f"[CONTRARIAN] Analyzed {len(self.market_disagreements)} markets")
                    print(f"[CONTRARIAN] Found {high_disagreement} high-disagreement markets")
                else:
                    print("[CONTRARIAN] ⚠️  No market disagreement data available")

                self.contrarian_cache_timestamp = datetime.now()

                has_data = len(self.contrarian_traders) > 0 or len(self.market_disagreements) > 0

                if has_data:
                    print("[CONTRARIAN] ✅ Successfully loaded contrarian data")
                else:
                    print("[CONTRARIAN] ⚠️  No resolved markets - contrarian bonuses inactive")

                return has_data

            except Exception as e:
                print(f"[CONTRARIAN] ❌ Error loading data: {e}")
                print(f"[CONTRARIAN] Continuing with neutral contrarian modifiers (1.0x)")
                return False
        else:
            # Cache is fresh
            cache_age = (datetime.now() - self.contrarian_cache_timestamp).total_seconds() / 3600
            print(f"[CONTRARIAN] Using cached contrarian data (age: {cache_age:.1f} hours)")

        return True  # Cache is fresh

    def get_contrarian_modifier(self, trader_address: str) -> float:
        """
        Calculate base contrarian modifier for trader.

        Rewards traders who profitably bet against consensus.

        Args:
            trader_address: Trader to evaluate

        Returns:
            float: Contrarian multiplier (0.90-1.25)
                - Consistent Contrarian (high win rate) → 1.20x
                - Selective Contrarian (picks spots) → 1.15x
                - Valuable Contrarian (general) → 1.10x
                - Balanced Trader → 1.00x (neutral)
                - Herd Follower → 0.95x
                - Chaos Bettor (contrarian but losing) → 0.90x
        """
        # Load data if not cached
        if not self.contrarian_traders and self.contrarian_cache_timestamp is None:
            self._load_contrarian_data()

        # Check if trader has contrarian data
        if trader_address not in self.contrarian_traders:
            return 1.00  # Neutral (no data)

        trader_data = self.contrarian_traders[trader_address]

        # Get contrarian type
        contrarian_type = trader_data.get('contrarian_type', 'Balanced Trader')
        is_valuable = trader_data.get('is_valuable', False)
        contrarian_win_rate = trader_data.get('contrarian_win_rate', 0.5)

        # Calculate modifier based on type and performance
        if contrarian_type == "Consistent Contrarian":
            modifier = 1.20  # Best contrarians
        elif contrarian_type == "Selective Contrarian":
            modifier = 1.15  # Picks spots well
        elif is_valuable:
            modifier = 1.10  # Generally profitable contrarian
        elif contrarian_type == "Balanced Trader":
            modifier = 1.00  # Neutral
        elif contrarian_type == "Herd Follower":
            modifier = 0.95  # Follows consensus too much
        elif contrarian_type == "Chaos Bettor":
            modifier = 0.90  # Contrarian but losing
        else:
            modifier = 1.00  # Default neutral

        # Additional boost for very high contrarian win rate
        if contrarian_win_rate > 0.7:
            modifier += 0.05  # Extra bonus for exceptional contrarians

        # Clamp to [0.90, 1.25] range
        modifier = max(0.90, min(1.25, modifier))

        return modifier

    def is_valuable_contrarian(self, trader_address: str) -> Dict:
        """
        Check if trader is identified as valuable contrarian.

        Valuable contrarian criteria:
        - Contrarian win rate > 60%
        - Contrarian rate > 30%
        - ROI > 10%

        Args:
            trader_address: Trader to evaluate

        Returns:
            dict: {
                'is_valuable': bool,
                'contrarian_type': str,
                'contrarian_rate': float,
                'contrarian_win_rate': float,
                'contrarian_roi': float,
                'contrarian_bets': int
            }
        """
        # Load data if not cached
        if not self.contrarian_traders and self.contrarian_cache_timestamp is None:
            self._load_contrarian_data()

        # Check if trader has contrarian data
        if trader_address not in self.contrarian_traders:
            return {
                'is_valuable': False,
                'contrarian_type': 'Unknown',
                'contrarian_rate': 0.0,
                'contrarian_win_rate': 0.0,
                'contrarian_roi': 0.0,
                'contrarian_bets': 0
            }

        trader_data = self.contrarian_traders[trader_address]

        return {
            'is_valuable': trader_data.get('is_valuable', False),
            'contrarian_type': trader_data.get('contrarian_type', 'Unknown'),
            'contrarian_rate': trader_data.get('contrarian_rate', 0.0),
            'contrarian_win_rate': trader_data.get('contrarian_win_rate', 0.0),
            'contrarian_roi': trader_data.get('contrarian_roi', 0.0),
            'contrarian_bets': trader_data.get('contrarian_bets', 0)
        }

    def get_disagreement_adjusted_weight(self, trader_address: str, market_id: str) -> float:
        """
        Calculate disagreement-adjusted weight for trader on specific market.

        In high-disagreement markets, valuable contrarians get extra weight
        because they provide unique signal when consensus is uncertain.

        Formula: base_weight × (1 + disagreement_boost)

        Where disagreement_boost = disagreement_score × contrarian_multiplier

        Args:
            trader_address: Trader to evaluate
            market_id: Market ID for context

        Returns:
            float: Disagreement-adjusted multiplier (1.0-1.5x)
                - High disagreement + valuable contrarian → 1.3-1.5x
                - High disagreement + regular trader → 1.0-1.1x
                - Low disagreement (any trader) → 1.0x
        """
        # Load data if not cached
        if not self.market_disagreements and self.contrarian_cache_timestamp is None:
            self._load_contrarian_data()

        # Check if market has disagreement data
        if market_id not in self.market_disagreements:
            return 1.0  # No disagreement data, neutral weight

        disagreement_data = self.market_disagreements[market_id]
        disagreement_score = disagreement_data.get('disagreement_score', 0.0)

        # Only apply boost in high-disagreement markets (>0.6)
        if disagreement_score < 0.6:
            return 1.0  # Low disagreement, no boost

        # Check if trader is valuable contrarian
        contrarian_data = self.is_valuable_contrarian(trader_address)

        if contrarian_data['is_valuable']:
            # Valuable contrarians get extra weight in high-disagreement markets
            # Maximum boost: disagreement_score (0.6-1.0) × 0.5 = 0.3-0.5
            disagreement_boost = disagreement_score * 0.5
        else:
            # Regular traders get minor boost in high-disagreement (uncertainty)
            disagreement_boost = disagreement_score * 0.1

        # Calculate final multiplier
        multiplier = 1.0 + disagreement_boost

        # Clamp to [1.0, 1.5] range
        multiplier = max(1.0, min(1.5, multiplier))

        return multiplier

    def calculate_contrarian_multiplier(self, trader_address: str,
                                       market_id: str = None) -> Dict:
        """
        Calculate combined contrarian multiplier.

        Combines two components:
        1. Base contrarian modifier (trader-intrinsic)
        2. Disagreement-adjusted weight (market-context-aware, if market_id provided)

        Args:
            trader_address: Trader to evaluate
            market_id: Optional market ID for context-aware weighting

        Returns:
            dict: {
                'base_modifier': float (0.90-1.25),
                'disagreement_adjusted': float (1.0-1.5),
                'combined_multiplier': float (0.90-1.875),
                'contrarian_data': dict,
                'disagreement_score': float or None,
                'breakdown': str
            }
        """
        # Get base contrarian modifier
        base_modifier = self.get_contrarian_modifier(trader_address)

        # Get contrarian data
        contrarian_data = self.is_valuable_contrarian(trader_address)

        # Get disagreement adjustment (if market_id provided)
        if market_id:
            disagreement_adjusted = self.get_disagreement_adjusted_weight(trader_address, market_id)
            disagreement_score = self.market_disagreements.get(market_id, {}).get('disagreement_score')
        else:
            disagreement_adjusted = 1.0
            disagreement_score = None

        # Combined multiplier
        combined = base_modifier * disagreement_adjusted

        # Clamp to [0.90, 1.875] range
        combined = max(0.90, min(1.875, combined))

        # Build breakdown string
        breakdown_parts = []

        if contrarian_data['is_valuable']:
            breakdown_parts.append(f"Contrarian: {base_modifier:.2f}x ({contrarian_data['contrarian_type']})")
        else:
            breakdown_parts.append(f"Contrarian: {base_modifier:.2f}x")

        if market_id and disagreement_score is not None:
            if disagreement_score > 0.6:
                breakdown_parts.append(f"Disagreement: {disagreement_adjusted:.2f}x (Score: {disagreement_score:.2f})")
            else:
                breakdown_parts.append(f"Disagreement: {disagreement_adjusted:.2f}x (Low)")

        breakdown_parts.append(f"TOTAL: {combined:.2f}x")

        breakdown = " | ".join(breakdown_parts)

        return {
            'base_modifier': round(base_modifier, 3),
            'disagreement_adjusted': round(disagreement_adjusted, 3),
            'combined_multiplier': round(combined, 3),
            'contrarian_data': contrarian_data,
            'disagreement_score': disagreement_score,
            'breakdown': breakdown
        }

    def export_contrarian_analysis(self) -> Dict:
        """
        Export contrarian analysis for all traders.

        Returns comprehensive contrarian data for integration.

        Returns:
            dict: {
                'timestamp': str,
                'total_traders_analyzed': int,
                'valuable_contrarians': int,
                'high_disagreement_markets': int,
                'avg_contrarian_win_rate': float,
                'top_contrarians': List[dict]
            }
        """
        # Load data if needed
        self._load_contrarian_data()

        traders_with_contrarian = []

        for trader in self.contrarian_traders.keys():
            contrarian_data = self.calculate_contrarian_multiplier(trader)

            traders_with_contrarian.append({
                'trader': trader,
                'base_modifier': contrarian_data['base_modifier'],
                'is_valuable': contrarian_data['contrarian_data']['is_valuable'],
                'contrarian_type': contrarian_data['contrarian_data']['contrarian_type'],
                'contrarian_win_rate': contrarian_data['contrarian_data']['contrarian_win_rate'],
                'contrarian_rate': contrarian_data['contrarian_data']['contrarian_rate'],
                'contrarian_bets': contrarian_data['contrarian_data']['contrarian_bets']
            })

        # Sort by base_modifier (highest first)
        traders_with_contrarian.sort(key=lambda x: x['base_modifier'], reverse=True)

        # Calculate statistics
        valuable_contrarians = [t for t in traders_with_contrarian if t['is_valuable']]

        # Get high-disagreement markets
        high_disagreement_markets = [
            m for m, d in self.market_disagreements.items()
            if d.get('disagreement_score', 0) > 0.6
        ]

        return {
            'timestamp': datetime.now().isoformat(),
            'total_traders_analyzed': len(traders_with_contrarian),
            'valuable_contrarians': len(valuable_contrarians),
            'high_disagreement_markets': len(high_disagreement_markets),
            'avg_contrarian_win_rate': sum(t['contrarian_win_rate'] for t in valuable_contrarians) / len(valuable_contrarians) if valuable_contrarians else 0,
            'top_contrarians': traders_with_contrarian[:10]
        }

    def generate_contrarian_report(self, output_dir: str = 'reports') -> str:
        """
        Generate CSV report of contrarian analysis.

        Creates: contrarian_analysis_YYYYMMDD.csv

        Columns:
        - Rank
        - Trader Address
        - Contrarian Type
        - Base Modifier
        - Is Valuable
        - Contrarian Rate (%)
        - Contrarian Win Rate (%)
        - Contrarian ROI
        - Contrarian Bets
        - Consensus Win Rate (%)

        Args:
            output_dir: Output directory for report

        Returns:
            str: Path to generated report
        """
        print("[CONTRARIAN] Generating contrarian analysis report...")

        # Load data if needed
        self._load_contrarian_data()

        # Create reports directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        report_rows = []

        for trader_address in self.contrarian_traders.keys():
            contrarian_data = self.calculate_contrarian_multiplier(trader_address)

            trader_info = contrarian_data['contrarian_data']

            # Get consensus win rate if available
            trader_metrics = self.contrarian_traders[trader_address]
            consensus_win_rate = trader_metrics.get('consensus_win_rate', 0.0)

            report_rows.append({
                'trader_address': trader_address,
                'contrarian_type': trader_info['contrarian_type'],
                'base_modifier': contrarian_data['base_modifier'],
                'is_valuable': 'Yes' if trader_info['is_valuable'] else 'No',
                'contrarian_rate_pct': round(trader_info['contrarian_rate'] * 100, 1),
                'contrarian_win_rate_pct': round(trader_info['contrarian_win_rate'] * 100, 1),
                'contrarian_roi': round(trader_info['contrarian_roi'], 3),
                'contrarian_bets': trader_info['contrarian_bets'],
                'consensus_win_rate_pct': round(consensus_win_rate * 100, 1)
            })

        # Sort by base_modifier (highest first)
        report_rows.sort(key=lambda x: x['base_modifier'], reverse=True)

        # Add rank
        for i, row in enumerate(report_rows, 1):
            row['rank'] = i

        # Reorder columns with rank first
        column_order = ['rank', 'trader_address', 'contrarian_type', 'base_modifier',
                       'is_valuable', 'contrarian_rate_pct', 'contrarian_win_rate_pct',
                       'contrarian_roi', 'contrarian_bets', 'consensus_win_rate_pct']

        # Write CSV
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(output_dir, f'contrarian_analysis_{date_str}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8', errors='ignore') as f:
            if report_rows:
                writer = csv.DictWriter(f, fieldnames=column_order)
                writer.writeheader()
                writer.writerows(report_rows)

        print(f"[CONTRARIAN] Report saved: {output_path}")
        print(f"[CONTRARIAN] {len(report_rows)} traders included")

        return output_path

    def export_pnl_analysis(self) -> Dict:
        """
        Export P&L analysis data for all traders.

        Returns:
            Dict with:
                - timestamp: Analysis timestamp
                - total_traders: Total number of traders
                - traders_with_pnl: Number with P&L data (closed positions)
                - total_realized_pnl: Total P&L across all traders
                - avg_roi: Average ROI across all closed positions
                - avg_profit_modifier: Average profit modifier
                - avg_roi_modifier: Average ROI modifier
                - avg_quality_modifier: Average quality modifier
                - profitable_traders: Number of traders with positive P&L
                - top_pnl_traders: Top 10 by adjusted ELO
        """
        print("[P&L] Exporting P&L analysis...")

        # Load P&L data
        self._load_pnl_data()

        all_traders = self.elo_system.get_all_traders()

        # Calculate statistics
        profit_mods = []
        roi_mods = []
        quality_mods = []

        trader_adjusted_elos = []
        total_pnl = 0.0
        total_roi = 0.0
        closed_positions_total = 0
        profitable_traders = 0

        for trader in all_traders:
            if trader in self.pnl_cache:
                pnl_mult = self.calculate_pnl_multiplier(trader)
                profit_mods.append(pnl_mult['profit_modifier'])
                roi_mods.append(pnl_mult['roi_modifier'])
                quality_mods.append(pnl_mult['quality_modifier'])

                # Calculate adjusted ELO for ranking
                base_elo = self.get_trader_global_elo(trader)
                adjusted_elo = base_elo * pnl_mult['combined_multiplier']

                trader_adjusted_elos.append({
                    'trader': trader,
                    'base_elo': base_elo,
                    'pnl_multiplier': pnl_mult['combined_multiplier'],
                    'adjusted_elo': adjusted_elo,
                    'realized_pnl': pnl_mult['raw_metrics']['realized_pnl'],
                    'avg_roi': pnl_mult['raw_metrics']['avg_roi'],
                    'closed_positions': pnl_mult['raw_metrics']['closed_positions'],
                    'breakdown': pnl_mult['breakdown']
                })

                # Aggregate stats
                total_pnl += pnl_mult['raw_metrics']['realized_pnl']
                total_roi += pnl_mult['raw_metrics']['avg_roi']
                closed_positions_total += pnl_mult['raw_metrics']['closed_positions']

                if pnl_mult['raw_metrics']['realized_pnl'] > 0:
                    profitable_traders += 1

        # Sort by adjusted ELO
        trader_adjusted_elos.sort(key=lambda x: x['adjusted_elo'], reverse=True)

        export = {
            'timestamp': datetime.now().isoformat(),
            'total_traders': len(all_traders),
            'traders_with_pnl': len(self.pnl_cache),
            'total_realized_pnl': total_pnl,
            'avg_roi': total_roi / len(self.pnl_cache) if self.pnl_cache else 0.0,
            'avg_profit_modifier': sum(profit_mods) / len(profit_mods) if profit_mods else 1.0,
            'avg_roi_modifier': sum(roi_mods) / len(roi_mods) if roi_mods else 1.0,
            'avg_quality_modifier': sum(quality_mods) / len(quality_mods) if quality_mods else 1.0,
            'profitable_traders': profitable_traders,
            'top_pnl_traders': trader_adjusted_elos[:10]
        }

        print(f"[P&L] Export complete: {export['traders_with_pnl']}/{export['total_traders']} traders with P&L data")

        return export

    def generate_pnl_report(self, output_dir: str = 'reports'):
        """
        Generate CSV report of P&L modifiers.

        Creates: reports/pnl_modifiers_YYYYMMDD.csv

        Args:
            output_dir: Output directory for reports

        Returns:
            Path to generated report
        """
        print(f"[P&L] Generating P&L modifiers report...")

        # Create output directory
        if not os.path.isabs(output_dir):
            output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # Load P&L data
        self._load_pnl_data()

        # Get all traders
        all_traders = self.elo_system.get_all_traders()

        # Generate report data
        report_rows = []

        for trader in all_traders:
            base_elo = self.get_trader_global_elo(trader)

            if trader in self.pnl_cache:
                pnl_stats = self.pnl_cache[trader]
                pnl_mult = self.calculate_pnl_multiplier(trader)

                adjusted_elo = base_elo * pnl_mult['combined_multiplier']

                report_rows.append({
                    'trader_address': trader,
                    'base_global_elo': f"{base_elo:.1f}",
                    'profit_modifier': f"{pnl_mult['profit_modifier']:.3f}",
                    'roi_modifier': f"{pnl_mult['roi_modifier']:.3f}",
                    'quality_modifier': f"{pnl_mult['quality_modifier']:.3f}",
                    'confidence': f"{pnl_mult['confidence']:.3f}",
                    'combined_multiplier': f"{pnl_mult['combined_multiplier']:.3f}",
                    'adjusted_global_elo': f"{adjusted_elo:.1f}",
                    'realized_pnl': f"{pnl_stats['realized_pnl']:.2f}",
                    'avg_roi': f"{pnl_stats['avg_roi']:.2f}",
                    'closed_positions': pnl_stats['closed_positions'],
                    'open_positions': pnl_stats['open_positions'],
                    'profitable_rate': f"{pnl_stats.get('profitable_rate', 0):.2f}"
                })
            else:
                # No P&L data
                report_rows.append({
                    'trader_address': trader,
                    'base_global_elo': f"{base_elo:.1f}",
                    'profit_modifier': '1.000',
                    'roi_modifier': '1.000',
                    'quality_modifier': '1.000',
                    'confidence': '1.000',
                    'combined_multiplier': '1.000',
                    'adjusted_global_elo': f"{base_elo:.1f}",
                    'realized_pnl': '0.00',
                    'avg_roi': '0.00',
                    'closed_positions': 0,
                    'open_positions': 0,
                    'profitable_rate': '0.00'
                })

        # Sort by adjusted ELO (highest first)
        report_rows.sort(key=lambda x: float(x['adjusted_global_elo']), reverse=True)

        # Write CSV
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = os.path.join(output_dir, f'pnl_modifiers_{date_str}.csv')

        with open(output_path, 'w', newline='', encoding='utf-8', errors='ignore') as f:
            if report_rows:
                writer = csv.DictWriter(f, fieldnames=report_rows[0].keys())
                writer.writeheader()
                writer.writerows(report_rows)

        print(f"[P&L] Report saved: {output_path}")
        print(f"[P&L] {len(report_rows)} traders included")

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

        # Add contrarian analysis (if available)
        try:
            contrarian_loaded = self._load_contrarian_data()
            contrarian_analysis = {}
            valuable_contrarians = []
            high_disagreement_markets = []

            if contrarian_loaded:
                for trader_address in all_traders:
                    if trader_address in self.contrarian_traders:
                        contrarian_data = self.calculate_contrarian_multiplier(trader_address)

                        contrarian_analysis[trader_address] = {
                            'base_modifier': contrarian_data['base_modifier'],
                            'is_valuable': contrarian_data['contrarian_data']['is_valuable'],
                            'contrarian_type': contrarian_data['contrarian_data']['contrarian_type'],
                            'contrarian_win_rate': contrarian_data['contrarian_data']['contrarian_win_rate'],
                            'contrarian_rate': contrarian_data['contrarian_data']['contrarian_rate']
                        }

                        # Track valuable contrarians
                        if contrarian_data['contrarian_data']['is_valuable']:
                            valuable_contrarians.append(trader_address)

                # Get high-disagreement markets
                high_disagreement_markets = [
                    m for m, d in self.market_disagreements.items()
                    if d.get('disagreement_score', 0) > 0.6
                ]

                export_data['contrarian_analysis'] = contrarian_analysis
                export_data['valuable_contrarians'] = valuable_contrarians
                export_data['high_disagreement_markets'] = high_disagreement_markets
                export_data['contrarian_analysis_timestamp'] = datetime.now().isoformat()
                print(f"[CONTRARIAN] Included contrarian analysis for {len(contrarian_analysis)} traders in export")
                print(f"[CONTRARIAN] {len(valuable_contrarians)} valuable contrarians, {len(high_disagreement_markets)} high-disagreement markets")
            else:
                export_data['contrarian_analysis'] = {}
                export_data['valuable_contrarians'] = []
                export_data['high_disagreement_markets'] = []
                export_data['contrarian_analysis_timestamp'] = None
                print("[CONTRARIAN] No contrarian analysis data available for export")
        except Exception as e:
            print(f"[CONTRARIAN] WARNING: Could not include contrarian analysis in export: {e}")
            export_data['contrarian_analysis'] = {}
            export_data['valuable_contrarians'] = []
            export_data['high_disagreement_markets'] = []
            export_data['contrarian_analysis_timestamp'] = None

        # Add P&L analysis (if available)
        try:
            pnl_loaded = self._load_pnl_data()
            pnl_analysis = {}
            high_profit_traders = []
            high_roi_traders = []

            if pnl_loaded:
                for trader_address in all_traders:
                    if trader_address in self.pnl_cache:
                        pnl_data = self.calculate_pnl_multiplier(trader_address)

                        pnl_analysis[trader_address] = {
                            'profit_modifier': pnl_data['profit_modifier'],
                            'roi_modifier': pnl_data['roi_modifier'],
                            'quality_modifier': pnl_data['quality_modifier'],
                            'confidence': pnl_data['confidence'],
                            'combined_multiplier': pnl_data['combined_multiplier'],
                            'realized_pnl': pnl_data['raw_metrics']['realized_pnl'],
                            'avg_roi': pnl_data['raw_metrics']['avg_roi'],
                            'closed_positions': pnl_data['raw_metrics']['closed_positions'],
                            'profitable_rate': pnl_data['raw_metrics'].get('profitable_rate', 0.0)
                        }

                        # Track high-profit traders (>$100 realized)
                        if pnl_data['raw_metrics']['realized_pnl'] >= 100:
                            high_profit_traders.append(trader_address)

                        # Track high-ROI traders (>50% avg ROI with 5+ positions)
                        if pnl_data['raw_metrics']['avg_roi'] >= 50 and pnl_data['raw_metrics']['closed_positions'] >= 5:
                            high_roi_traders.append(trader_address)

                export_data['pnl_analysis'] = pnl_analysis
                export_data['high_profit_traders'] = high_profit_traders
                export_data['high_roi_traders'] = high_roi_traders
                export_data['pnl_analysis_timestamp'] = datetime.now().isoformat()
                print(f"[P&L] Included P&L analysis for {len(pnl_analysis)} traders in export")
                print(f"[P&L] {len(high_profit_traders)} high-profit traders, {len(high_roi_traders)} high-ROI traders")
            else:
                export_data['pnl_analysis'] = {}
                export_data['high_profit_traders'] = []
                export_data['high_roi_traders'] = []
                export_data['pnl_analysis_timestamp'] = None
                print("[P&L] No P&L analysis data available for export")
        except Exception as e:
            print(f"[P&L] WARNING: Could not include P&L analysis in export: {e}")
            export_data['pnl_analysis'] = {}
            export_data['high_profit_traders'] = []
            export_data['high_roi_traders'] = []
            export_data['pnl_analysis_timestamp'] = None

        return export_data

    def get_top_traders(self, category: str = None, limit: int = 10,
                       min_resolved_trades: int = 50) -> List[Dict]:
        """
        Get top traders by ELO rating.

        Args:
            category: Specific category (None = global ELO)
            limit: Number of traders to return
            min_resolved_trades: Minimum resolved trades required (default: 50)

        Returns:
            List of dicts with trader data sorted by ELO
        """
        all_traders = self.elo_system.get_all_traders()
        trader_ratings = []

        # Get resolved trades count for all traders
        conn = self.get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT t.trader_address, COUNT(*) as resolved_count
            FROM trades t
            JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 1
            AND m.winning_outcome IS NOT NULL
            GROUP BY t.trader_address
        """)

        resolved_counts = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        for trader_address in all_traders:
            # Check minimum sample size
            resolved_count = resolved_counts.get(trader_address, 0)
            if resolved_count < min_resolved_trades:
                continue

            if category:
                elo = self.get_trader_category_elo(trader_address, category)
                market_count = self.elo_system.get_market_count(trader_address, category)

                # Only include if meaningful participation
                if market_count >= 3:
                    trader_ratings.append({
                        'address': trader_address,
                        'elo': elo,
                        'market_count': market_count,
                        'category': category,
                        'resolved_trades': resolved_count
                    })
            else:
                elo = self.get_trader_global_elo(trader_address)
                trader_ratings.append({
                    'address': trader_address,
                    'elo': elo,
                    'resolved_trades': resolved_count
                })

        trader_ratings.sort(key=lambda x: x['elo'], reverse=True)
        return trader_ratings[:limit]

    # ==================== P&L / POSITION TRACKING INTEGRATION ====================

    def _load_pnl_data(self, force_refresh: bool = False) -> bool:
        """
        Load P&L data from position tracker (with caching).

        P&L data is cached for 24 hours to avoid repeated queries.

        Args:
            force_refresh: Force reload even if cache is valid

        Returns:
            bool: True if data loaded successfully
        """
        # Check if cache is stale (>24 hours old)
        cache_age = None
        if hasattr(self, 'pnl_cache_timestamp') and self.pnl_cache_timestamp:
            cache_age = (datetime.now() - self.pnl_cache_timestamp).total_seconds()

        if force_refresh or not hasattr(self, 'pnl_cache_timestamp') or \
           self.pnl_cache_timestamp is None or cache_age > 86400:

            print("[P&L] Loading position tracking data...")

            try:
                # Import position tracker
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from monitoring.position_tracker import PositionTracker
                from monitoring.database import Database as MonitoringDatabase

                # Initialize tracker
                tracker = PositionTracker(MonitoringDatabase(db_path=self.db_path))

                # Cache for all traders
                self.pnl_cache = {}  # trader -> {realized_pnl, avg_roi, etc}

                # Get all flagged traders
                conn = self.get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT address FROM traders WHERE is_flagged = 1")
                traders = [row[0] for row in cursor.fetchall()]
                conn.close()

                print(f"[P&L] Loading data for {len(traders)} traders...")

                # Load P&L for each trader
                loaded_count = 0
                for trader in traders:
                    try:
                        pnl_stats = tracker.calculate_trader_pnl(trader)

                        # Only cache if trader has positions
                        if pnl_stats['closed_positions'] > 0 or pnl_stats['open_positions'] > 0:
                            self.pnl_cache[trader] = {
                                'realized_pnl': pnl_stats['realized_pnl'],
                                'avg_roi': pnl_stats['avg_roi'],
                                'closed_positions': pnl_stats['closed_positions'],
                                'open_positions': pnl_stats['open_positions'],
                                'total_invested': pnl_stats['total_invested'],
                                'profitable_rate': pnl_stats['profitable_rate']
                            }
                            loaded_count += 1
                    except Exception as e:
                        # Skip traders with no P&L data
                        continue

                self.pnl_cache_timestamp = datetime.now()

                print(f"[P&L] Loaded data for {loaded_count} traders with P&L history")
                return loaded_count > 0

            except Exception as e:
                print(f"[P&L] ERROR: Failed to load P&L data: {e}")
                print(f"[P&L] Continuing with neutral P&L modifiers (1.0x)")
                self.pnl_cache = {}
                self.pnl_cache_timestamp = datetime.now()
                return False
        else:
            print(f"[P&L] Using cached data (age: {cache_age/3600:.1f} hours)")
            return len(self.pnl_cache) > 0

    def calculate_profit_modifier(self, realized_pnl: float) -> float:
        """
        Calculate profit-based modifier from realized P&L.

        Args:
            realized_pnl: Total realized profit/loss

        Returns:
            float: Multiplier (0.85-1.20)
                - $500+: 1.20x (exceptional)
                - $250-499: 1.15x (strong)
                - $100-249: 1.10x (good)
                - $50-99: 1.05x (modest)
                - $10-49: 1.00x (neutral)
                - $0-9: 0.95x (minimal)
                - Negative: 0.85-0.95x (losses)
        """
        if realized_pnl >= 500:
            return 1.20
        elif realized_pnl >= 250:
            return 1.15
        elif realized_pnl >= 100:
            return 1.10
        elif realized_pnl >= 50:
            return 1.05
        elif realized_pnl >= 10:
            return 1.00
        elif realized_pnl >= 0:
            return 0.95
        else:
            # Negative P&L: scale from 0.85 to 0.95
            # -$100 or worse = 0.85x
            return max(0.85, 0.95 + (realized_pnl / 100) * 0.10)

    def calculate_roi_modifier(self, avg_roi: float) -> float:
        """
        Calculate ROI-based modifier from average return.

        Args:
            avg_roi: Average ROI percentage

        Returns:
            float: Multiplier (0.90-1.15)
                - >50%: 1.15x (exceptional)
                - 30-50%: 1.10x (strong)
                - 20-30%: 1.07x (good)
                - 10-20%: 1.05x (above average)
                - 0-10%: 1.00x (neutral)
                - -10-0%: 0.95x (slight losses)
                - <-10%: 0.90x (poor)
        """
        if avg_roi > 50:
            return 1.15
        elif avg_roi > 30:
            return 1.10
        elif avg_roi > 20:
            return 1.07
        elif avg_roi > 10:
            return 1.05
        elif avg_roi > 0:
            return 1.00
        elif avg_roi > -10:
            return 0.95
        else:
            return 0.90

    def calculate_position_quality_modifier(self, profitable_rate: float) -> float:
        """
        Calculate position quality modifier from profitable rate.

        Args:
            profitable_rate: Fraction of closed positions that were profitable (0-1)

        Returns:
            float: Multiplier (0.95-1.10)
                - >70%: 1.10x (very selective)
                - 60-70%: 1.07x (good selection)
                - 50-60%: 1.05x (slightly profitable)
                - 40-50%: 1.00x (neutral)
                - 30-40%: 0.97x (more losers)
                - <30%: 0.95x (poor selection)
        """
        if profitable_rate > 0.70:
            return 1.10
        elif profitable_rate > 0.60:
            return 1.07
        elif profitable_rate > 0.50:
            return 1.05
        elif profitable_rate > 0.40:
            return 1.00
        elif profitable_rate > 0.30:
            return 0.97
        else:
            return 0.95

    def calculate_pnl_confidence(self, closed_positions: int) -> float:
        """
        Calculate confidence multiplier based on sample size.

        Args:
            closed_positions: Number of closed positions

        Returns:
            float: Confidence (0.50-1.00)
                - 30+: 1.00 (full confidence)
                - 20-29: 0.90
                - 10-19: 0.75
                - 5-9: 0.60
                - <5: 0.50
        """
        if closed_positions >= 30:
            return 1.00
        elif closed_positions >= 20:
            return 0.90
        elif closed_positions >= 10:
            return 0.75
        elif closed_positions >= 5:
            return 0.60
        else:
            return 0.50

    def calculate_pnl_multiplier(self, trader_address: str) -> Dict:
        """
        Calculate combined P&L/position tracking multiplier.

        Combines three P&L dimensions:
        1. Profit score (absolute $ made)
        2. ROI score (percentage returns)
        3. Position quality (profitable rate)

        Adjusted by sample size confidence.

        Args:
            trader_address: Trader to evaluate

        Returns:
            dict: {
                'profit_modifier': float (0.85-1.20),
                'roi_modifier': float (0.90-1.15),
                'quality_modifier': float (0.95-1.10),
                'confidence': float (0.50-1.00),
                'combined_multiplier': float (0.70-1.40),
                'raw_metrics': dict,
                'breakdown': str
            }
        """
        # Load data if not cached
        if not hasattr(self, 'pnl_cache'):
            self._load_pnl_data()

        # Get trader P&L data
        if trader_address not in self.pnl_cache:
            # No P&L data - return neutral defaults
            return {
                'profit_modifier': 1.00,
                'roi_modifier': 1.00,
                'quality_modifier': 1.00,
                'confidence': 0.50,
                'combined_multiplier': 1.00,
                'raw_metrics': {
                    'realized_pnl': 0.0,
                    'avg_roi': 0.0,
                    'profitable_rate': 0.0,
                    'closed_positions': 0,
                    'open_positions': 0,
                    'total_invested': 0.0
                },
                'breakdown': 'P&L: 1.00x (No Data)'
            }

        pnl_data = self.pnl_cache[trader_address]

        # Extract metrics
        realized_pnl = pnl_data['realized_pnl']
        avg_roi = pnl_data['avg_roi']
        profitable_rate = pnl_data['profitable_rate']
        closed_positions = pnl_data['closed_positions']

        # Calculate component modifiers
        profit_modifier = self.calculate_profit_modifier(realized_pnl)
        roi_modifier = self.calculate_roi_modifier(avg_roi)
        quality_modifier = self.calculate_position_quality_modifier(profitable_rate)

        # Calculate confidence
        confidence = self.calculate_pnl_confidence(closed_positions)

        # Combined multiplier (multiplicative with confidence)
        combined = profit_modifier * roi_modifier * quality_modifier * confidence

        # Clamp to reasonable range
        combined = max(0.70, min(1.40, combined))

        # Build breakdown string
        breakdown_parts = []
        breakdown_parts.append(f"Profit: {profit_modifier:.2f}x (${realized_pnl:,.2f})")
        breakdown_parts.append(f"ROI: {roi_modifier:.2f}x ({avg_roi:.1f}%)")
        breakdown_parts.append(f"Quality: {quality_modifier:.2f}x ({profitable_rate*100:.1f}% profitable)")
        breakdown_parts.append(f"Confidence: {confidence:.2f} ({closed_positions} closed)")
        breakdown_parts.append(f"TOTAL: {combined:.2f}x")

        breakdown = " | ".join(breakdown_parts)

        return {
            'profit_modifier': round(profit_modifier, 3),
            'roi_modifier': round(roi_modifier, 3),
            'quality_modifier': round(quality_modifier, 3),
            'confidence': round(confidence, 3),
            'combined_multiplier': round(combined, 3),
            'raw_metrics': {
                'realized_pnl': round(realized_pnl, 2),
                'avg_roi': round(avg_roi, 2),
                'profitable_rate': round(profitable_rate, 3),
                'closed_positions': closed_positions,
                'open_positions': pnl_data['open_positions'],
                'total_invested': round(pnl_data['total_invested'], 2)
            },
            'breakdown': breakdown
        }

    # ==================== COMPOSITE SKILL SCORE INTEGRATION ====================

    def get_composite_skill_score(self, trader_address: str) -> int:
        """
        Get trader's composite skill score (0-100).

        This is a convenience method that uses CompositeSkillScoreSystem.

        Composite score synthesizes all 5 modifier dimensions:
        1. Category ELO (0-25 points)
        2. Forecasting Quality (0-25 points)
        3. Execution Quality (0-15 points)
        4. Consistency (0-15 points)
        5. Behavioral Profile (0-15 points)
        6. Network Independence (0-10 points)
        7. Contrarian Bonus (+5 points)
        8. Copy-Trader Penalty (-20 points)

        Args:
            trader_address: Trader to evaluate

        Returns:
            int: Composite score (0-100)
        """
        from composite_skill_score import CompositeSkillScoreSystem

        if not hasattr(self, '_composite_system'):
            self._composite_system = CompositeSkillScoreSystem(
                db_path=self.db_path,
                api_key=self.api_key
            )

        score_data = self._composite_system.calculate_composite_score(trader_address)
        return score_data['composite_score']

    def get_trader_tier(self, trader_address: str) -> str:
        """
        Get trader's tier classification.

        Tiers:
        - ELITE (85-100): Top 5%
        - STRONG (70-84): Top 20%
        - ABOVE AVERAGE (55-69): Top 40%
        - AVERAGE (40-54): Middle 40%
        - BELOW AVERAGE (25-39): Bottom 20%
        - WEAK/NOISE (0-24): Bottom 5%

        Args:
            trader_address: Trader to evaluate

        Returns:
            str: Tier classification
        """
        from composite_skill_score import CompositeSkillScoreSystem

        if not hasattr(self, '_composite_system'):
            self._composite_system = CompositeSkillScoreSystem(
                db_path=self.db_path,
                api_key=self.api_key
            )

        score_data = self._composite_system.calculate_composite_score(trader_address)
        return score_data['tier']


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

    # Example 8: Contrarian Analysis Integration
    print("\n" + "="*70)
    print("EXAMPLE 8: Contrarian Analysis (Anti-Consensus Bonus)")
    print("="*70)

    # Load contrarian data
    try:
        has_data = system._load_contrarian_data()

        if has_data and system.contrarian_traders:
            # Get valuable contrarians
            valuable = [t for t, d in system.contrarian_traders.items()
                       if d.get('is_valuable', False)]

            print(f"\n[TEST] Found {len(valuable)} valuable contrarians")

            if valuable:
                # Test first valuable contrarian
                test_trader = valuable[0]

                print(f"\n[TEST] Analyzing: {test_trader[:12]}...")

                # Get base ELO
                base_elo = system.get_trader_global_elo(test_trader)
                print(f"Base Global ELO: {base_elo:.0f}")

                # Get contrarian data
                contrarian_data = system.calculate_contrarian_multiplier(test_trader)

                print(f"\nContrarian Analysis:")
                print(f"  Contrarian Type: {contrarian_data['contrarian_data']['contrarian_type']}")
                print(f"  Contrarian Win Rate: {contrarian_data['contrarian_data']['contrarian_win_rate']*100:.1f}%")
                print(f"  Contrarian Rate: {contrarian_data['contrarian_data']['contrarian_rate']*100:.1f}%")
                print(f"  Base Modifier: {contrarian_data['base_modifier']:.2f}x")
                print(f"  Is Valuable: {contrarian_data['contrarian_data']['is_valuable']}")

                # Test disagreement-adjusted weighting (if markets available)
                if system.market_disagreements:
                    high_disagreement = [m for m, d in system.market_disagreements.items()
                                       if d.get('disagreement_score', 0) > 0.6]

                    if high_disagreement:
                        test_market = high_disagreement[0]
                        contrarian_market = system.calculate_contrarian_multiplier(test_trader, test_market)

                        print(f"\n[TEST] Disagreement-Adjusted Weight (High Disagreement Market):")
                        print(f"  Market: {test_market[:12]}...")
                        print(f"  Market Disagreement: {contrarian_market['disagreement_score']:.2f}")
                        print(f"  Adjusted Multiplier: {contrarian_market['disagreement_adjusted']:.2f}x")
                        print(f"  Combined: {contrarian_market['combined_multiplier']:.2f}x")
                        print(f"  Breakdown: {contrarian_market['breakdown']}")

                # Get adjusted ELO with contrarian only
                adjusted_elo_contrarian = system.get_trader_global_elo(test_trader, apply_contrarian=True)
                print(f"\nAdjusted ELO (contrarian only): {adjusted_elo_contrarian:.0f}")
                print(f"Change: {adjusted_elo_contrarian - base_elo:+.0f}")

                # Get fully adjusted ELO (ALL 5 modifiers)
                full_elo = system.get_trader_global_elo(test_trader,
                                                         apply_behavioral=True,
                                                         apply_advanced=True,
                                                         apply_network=True,
                                                         apply_contrarian=True)

                print(f"\nFully Adjusted ELO (ALL 5 modifiers): {full_elo:.0f}")
                print(f"Total Change: {full_elo - base_elo:+.0f}")

                # Generate contrarian report
                print("\n[TEST] Generating contrarian analysis report...")
                try:
                    report_path = system.generate_contrarian_report()
                    print(f"[TEST] Report generated: {report_path}")
                except Exception as e:
                    print(f"[TEST] Report generation failed: {e}")

                # Export contrarian analysis
                print("\n[TEST] Exporting contrarian analysis...")
                try:
                    export_contrarian = system.export_contrarian_analysis()
                    print(f"[TEST] Total traders analyzed: {export_contrarian['total_traders_analyzed']}")
                    print(f"[TEST] Valuable contrarians: {export_contrarian['valuable_contrarians']}")
                    print(f"[TEST] High-disagreement markets: {export_contrarian['high_disagreement_markets']}")
                    print(f"[TEST] Avg contrarian win rate: {export_contrarian['avg_contrarian_win_rate']*100:.1f}%")
                except Exception as e:
                    print(f"[TEST] Export failed: {e}")

            else:
                print("\n⚠️  No valuable contrarians found in current data")

        else:
            print("\n⚠️  No resolved markets yet - contrarian analysis limited")
            print("Contrarian bonuses will activate once markets resolve\n")

    except Exception as e:
        print(f"\n[TEST] Contrarian integration test failed: {e}")

    # Example 9: P&L / Position Tracking Integration
    print("\n" + "="*70)
    print("EXAMPLE 9: P&L / Position Tracking Analysis")
    print("="*70)

    # Load P&L data
    try:
        has_data = system._load_pnl_data()

        if has_data and system.pnl_cache:
            # Get traders with P&L data
            traders_with_pnl = list(system.pnl_cache.keys())

            print(f"\n[TEST] Found {len(traders_with_pnl)} traders with P&L data")

            if traders_with_pnl:
                # Test first trader with P&L data
                test_trader = traders_with_pnl[0]

                print(f"\n[TEST] Analyzing: {test_trader[:12]}...")

                # Get base ELO
                base_elo = system.get_trader_global_elo(test_trader)
                print(f"Base Global ELO: {base_elo:.0f}")

                # Get P&L data
                pnl_data = system.calculate_pnl_multiplier(test_trader)

                print(f"\nP&L Analysis:")
                print(f"  Realized P&L: ${pnl_data['raw_metrics']['realized_pnl']:.2f}")
                print(f"  Average ROI: {pnl_data['raw_metrics']['avg_roi']:.1f}%")
                print(f"  Closed Positions: {pnl_data['raw_metrics']['closed_positions']}")
                print(f"  Profitable Rate: {pnl_data['raw_metrics'].get('profitable_rate', 0)*100:.1f}%")
                print(f"\nModifiers:")
                print(f"  Profit Modifier: {pnl_data['profit_modifier']:.3f}x")
                print(f"  ROI Modifier: {pnl_data['roi_modifier']:.3f}x")
                print(f"  Quality Modifier: {pnl_data['quality_modifier']:.3f}x")
                print(f"  Confidence: {pnl_data['confidence']:.3f}")
                print(f"  Combined Multiplier: {pnl_data['combined_multiplier']:.3f}x")
                print(f"  Breakdown: {pnl_data['breakdown']}")

                # Get adjusted ELO with P&L only
                adjusted_elo_pnl = system.get_trader_global_elo(test_trader, apply_pnl=True)
                print(f"\nAdjusted ELO (P&L only): {adjusted_elo_pnl:.0f}")
                print(f"Change: {adjusted_elo_pnl - base_elo:+.0f}")

                # Get fully adjusted ELO (ALL 6 modifiers)
                full_elo = system.get_trader_global_elo(test_trader,
                                                         apply_behavioral=True,
                                                         apply_advanced=True,
                                                         apply_network=True,
                                                         apply_contrarian=True,
                                                         apply_pnl=True)

                print(f"\nFully Adjusted ELO (ALL 6 modifiers): {full_elo:.0f}")
                print(f"Total Change: {full_elo - base_elo:+.0f}")

                # Generate P&L report
                print("\n[TEST] Generating P&L modifiers report...")
                try:
                    report_path = system.generate_pnl_report()
                    print(f"[TEST] Report generated: {report_path}")
                except Exception as e:
                    print(f"[TEST] Report generation failed: {e}")

                # Export P&L analysis
                print("\n[TEST] Exporting P&L analysis...")
                try:
                    export_pnl = system.export_pnl_analysis()
                    print(f"[TEST] Total traders analyzed: {export_pnl['total_traders']}")
                    print(f"[TEST] Traders with P&L: {export_pnl['traders_with_pnl']}")
                    print(f"[TEST] Total realized P&L: ${export_pnl['total_realized_pnl']:.2f}")
                    print(f"[TEST] Avg ROI: {export_pnl['avg_roi']:.1f}%")
                    print(f"[TEST] Profitable traders: {export_pnl['profitable_traders']}")
                except Exception as e:
                    print(f"[TEST] Export failed: {e}")

            else:
                print("\n⚠️  No traders with P&L data found")

        else:
            print("\n⚠️  No positions yet - P&L analysis unavailable")
            print("P&L tracking will activate once traders close positions\n")

    except Exception as e:
        print(f"\n[TEST] P&L integration test failed: {e}")

    print("\n" + "="*70)
    print("All examples completed! (6 integration dimensions tested)")
    print("="*70)
