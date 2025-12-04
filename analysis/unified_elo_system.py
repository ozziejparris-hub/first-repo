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
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter
import time


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

    # ==================== INTEGRATION METHODS ====================

    def get_trader_global_elo(self, trader_address: str) -> float:
        """
        Get trader's global ELO rating (weighted average across all categories).

        This provides a single overall skill rating, but category-specific ratings
        are more accurate for domain-specific predictions.

        Args:
            trader_address: Trader's address

        Returns:
            Global ELO rating (weighted average)
        """
        return self.elo_system.get_overall_elo(trader_address)

    def get_trader_category_elo(self, trader_address: str, category: str) -> float:
        """
        Get trader's ELO rating for a specific category.

        Use this for category-aware predictions (more accurate than global ELO).

        Args:
            trader_address: Trader's address
            category: Market category (e.g., 'Elections', 'Crypto')

        Returns:
            Category-specific ELO rating
        """
        return self.elo_system.get_category_elo(trader_address, category)

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
