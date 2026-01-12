#!/usr/bin/env python3
"""
Production-Grade Polymarket Simulation Data Seeder

Generates highly realistic simulation data that mirrors real Polymarket behavior:
- Time-series price evolution with Brownian motion
- News events that shock prices
- Trader position building over time
- Market correlation clusters
- Multi-category markets
- Behavioral biases
- Market lifecycle simulation

Usage:
    py scripts/simulation/seed_production_data.py --config experiments/configs/config_production.json
    py scripts/simulation/seed_production_data.py --clear-simulation  # Clear old data first
    py scripts/simulation/seed_production_data.py --validate-only     # Just validate
"""

import sys
import os
import json
import secrets
import random
import math
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from monitoring.database import Database


# Market title templates by category
MARKET_TEMPLATES = {
    'Elections': [
        "Will {person} win the {year} presidential election?",
        "Will {party} win the {state} Senate seat in {year}?",
        "Will {person} announce presidential run by {date}?",
        "{person} to win {state} primary?",
        "Will {person} drop out of {year} race before {month}?",
    ],
    'Geopolitics': [
        "Will {country} {action} {target} by {date}?",
        "{country} ceasefire agreement before {date}?",
        "Will {country} join {alliance} in {year}?",
        "{leader} to {action} by {month} {year}?",
        "Will {treaty} be signed in {year}?",
    ],
    'Economics': [
        "Will {metric} exceed {value} in {quarter} {year}?",
        "Fed to {action} rates in {month} {year}?",
        "Will {company} {event} by {date}?",
        "{index} above {level} by end of {year}?",
        "US recession in {year}?",
    ],
    'Crypto': [
        "Will Bitcoin exceed ${price}K by {date}?",
        "Ethereum above ${price} by {month} {year}?",
        "Will {coin} reach {target} market cap?",
        "{exchange} to {event} in {year}?",
        "Bitcoin ETF approval by {date}?",
    ],
    'Sports': [
        "Will {team} win {championship} in {year}?",
        "{player} to win MVP in {year}?",
        "{team} vs {opponent} - {team} wins?",
        "Will {team} make playoffs in {year}?",
        "{player} to score {stat} in {event}?",
    ],
    'Entertainment': [
        "Will {movie} gross over ${amount}M opening weekend?",
        "{person} to win {award} at {ceremony} {year}?",
        "Will {show} be renewed for season {num}?",
        "{artist} album to debut #1?",
        "{celebrity} {event} announcement before {date}?",
    ],
    'Other': [
        "Will {event} happen by {date}?",
        "{subject} to {action} in {year}?",
        "Will {phenomenon} occur before {month} {year}?",
    ]
}

# Template fill data
TEMPLATE_DATA = {
    'person': ['Trump', 'Biden', 'Harris', 'DeSantis', 'Newsom', 'Haley', 'Ramaswamy'],
    'party': ['Republicans', 'Democrats'],
    'state': ['Pennsylvania', 'Georgia', 'Arizona', 'Michigan', 'Wisconsin', 'Nevada', 'Florida', 'Texas'],
    'country': ['Russia', 'China', 'USA', 'Iran', 'Israel', 'Ukraine', 'Taiwan', 'North Korea'],
    'target': ['Ukraine', 'Taiwan', 'NATO', 'Iran', 'Syria'],
    'leader': ['Putin', 'Xi Jinping', 'Netanyahu', 'Zelenskyy', 'Kim Jong Un'],
    'action': ['invade', 'strike', 'sanction', 'recognize', 'withdraw from'],
    'alliance': ['NATO', 'EU', 'BRICS', 'UN Security Council'],
    'treaty': ['Peace Agreement', 'Trade Deal', 'Climate Accord', 'Nuclear Treaty'],
    'metric': ['GDP growth', 'Inflation', 'Unemployment', 'Job growth'],
    'value': ['2%', '3%', '4%', '5%', '100K'],
    'quarter': ['Q1', 'Q2', 'Q3', 'Q4'],
    'company': ['Tesla', 'Apple', 'Amazon', 'Google', 'Microsoft', 'Meta', 'Nvidia'],
    'event': ['IPO', 'merger', 'bankruptcy', 'layoffs', 'stock split'],
    'index': ['S&P 500', 'Dow', 'Nasdaq', 'Russell 2000'],
    'level': ['5000', '40000', '16000', '2500'],
    'price': ['50', '75', '100', '150', '200'],
    'coin': ['Solana', 'XRP', 'Cardano', 'Dogecoin', 'Polygon'],
    'exchange': ['Binance', 'Coinbase', 'Kraken', 'FTX'],
    'team': ['Lakers', 'Yankees', 'Chiefs', 'Patriots', 'Warriors', 'Cowboys'],
    'opponent': ['Celtics', 'Red Sox', 'Eagles', 'Bills', 'Suns', 'Giants'],
    'player': ['LeBron', 'Mahomes', 'Ohtani', 'Curry', 'Brady'],
    'championship': ['NBA Finals', 'Super Bowl', 'World Series', 'Stanley Cup'],
    'stat': ['30+ points', '3+ TDs', '2+ home runs'],
    'movie': ['Avatar 3', 'Mission Impossible', 'Fast & Furious', 'Marvel Film'],
    'award': ['Best Picture', 'Best Actor', 'Best Director', 'Album of the Year'],
    'ceremony': ['Oscars', 'Emmys', 'Grammys', 'Golden Globes'],
    'show': ['Succession', 'The Bear', 'Yellowstone', 'House of Dragon'],
    'num': ['2', '3', '4', '5'],
    'artist': ['Taylor Swift', 'Drake', 'Beyonce', 'Bad Bunny'],
    'celebrity': ['Elon Musk', 'Taylor Swift', 'Kanye', 'Rihanna'],
    'amount': ['100', '200', '300', '500'],
    'subject': ['AI regulation', 'Climate action', 'Space mission'],
    'phenomenon': ['Major earthquake', 'Solar eclipse', 'Northern lights'],
    'year': ['2025', '2026', '2027'],
    'month': ['January', 'March', 'June', 'September', 'December'],
    'date': ['March 2025', 'June 2025', 'December 2025', 'Q2 2026'],
}


@dataclass
class PricePoint:
    """A single price observation."""
    timestamp: datetime
    price: float
    volume: float = 0.0
    event: Optional[str] = None


@dataclass
class NewsEvent:
    """A news event that affects market prices."""
    timestamp: datetime
    event_type: str
    magnitude: float
    direction: int  # 1 for positive (toward Yes), -1 for negative (toward No)
    categories_affected: List[str]
    duration_hours: float


@dataclass
class TraderProfile:
    """Enhanced trader profile with behavioral attributes."""
    address: str
    tier: str
    skill_level: float
    volume_range: Tuple[float, float]
    avg_trades: int
    reaction_time_hours: Tuple[float, float]
    confidence_threshold: float
    diversification_range: Tuple[int, int]
    scales_positions: bool
    uses_stop_loss: bool
    overconfidence: float
    loss_aversion: float
    total_trades: int = 0
    successful_trades: int = 0
    total_volume: float = 0.0
    active_markets: List[str] = field(default_factory=list)


@dataclass
class Market:
    """Enhanced market with price history and lifecycle."""
    market_id: str
    title: str
    category: str
    creation_date: datetime
    resolution_date: Optional[datetime]
    true_outcome: str  # What will actually happen
    winning_outcome: Optional[str]  # Set when resolved
    liquidity_level: str
    difficulty: float
    correlation_cluster: Optional[int]
    price_history: List[PricePoint] = field(default_factory=list)
    news_events: List[NewsEvent] = field(default_factory=list)


class ProductionSimulator:
    """Production-grade market simulator with realistic dynamics."""

    def __init__(self, config_path: str = None, seed: int = 42):
        """Initialize with config file."""
        self.seed = seed
        random.seed(seed)

        # Load config
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        else:
            raise ValueError(f"Config file required: {config_path}")

        # Override seed if specified in config
        if 'seed' in self.config:
            self.seed = self.config['seed']
            random.seed(self.seed)

        self.db = Database()
        self.traders: List[TraderProfile] = []
        self.markets: List[Market] = []
        self.news_events: List[NewsEvent] = []
        self.simulation_start = datetime.now() - timedelta(days=self.config.get('simulation_duration_days', 180))
        self.simulation_end = datetime.now()

    def generate_market_title(self, category: str) -> str:
        """Generate a realistic market title for a category."""
        templates = MARKET_TEMPLATES.get(category, MARKET_TEMPLATES['Other'])
        template = random.choice(templates)

        # Fill in template
        title = template
        for key, values in TEMPLATE_DATA.items():
            placeholder = '{' + key + '}'
            if placeholder in title:
                title = title.replace(placeholder, random.choice(values), 1)

        return title

    def create_trader_profiles(self) -> List[TraderProfile]:
        """Generate enhanced trader profiles with behavioral attributes."""
        profiles = []
        config = self.config['traders']
        total_traders = config['total']
        distribution = config['distribution']
        skill_ranges = config['skill_ranges']
        volume_ranges = config['volume_ranges']
        trade_frequency = config['trade_frequency']
        activity = config.get('activity_patterns', {})
        biases = config.get('behavioral_biases', {})

        # Calculate counts for each tier
        counts = {
            tier: int(total_traders * pct)
            for tier, pct in distribution.items()
        }

        # Adjust for rounding
        total_allocated = sum(counts.values())
        if total_allocated < total_traders:
            counts['average'] += (total_traders - total_allocated)

        for tier, count in counts.items():
            tier_activity = activity.get(tier, {})
            tier_overconfidence = biases.get('overconfidence', {}).get(tier, 0.15)
            tier_loss_aversion = biases.get('loss_aversion', {}).get(tier, 2.0)

            for _ in range(count):
                address = '0x' + secrets.token_hex(20)
                skill_min, skill_max = skill_ranges[tier]
                freq_min, freq_max = trade_frequency[tier]
                vol_range = volume_ranges[tier]

                # Get reaction time from activity patterns
                reaction_time = tier_activity.get('research_delay_hours', [6, 48])
                confidence_threshold = tier_activity.get('confidence_threshold', 0.55)
                diversification = tier_activity.get('diversification', [3, 8])
                scales = tier_activity.get('scales_into_positions', False)
                stop_loss = tier_activity.get('uses_stop_loss', False)

                profile = TraderProfile(
                    address=address,
                    tier=tier,
                    skill_level=random.uniform(skill_min, skill_max),
                    volume_range=tuple(vol_range),
                    avg_trades=random.randint(freq_min, freq_max),
                    reaction_time_hours=tuple(reaction_time),
                    confidence_threshold=confidence_threshold,
                    diversification_range=tuple(diversification),
                    scales_positions=scales,
                    uses_stop_loss=stop_loss,
                    overconfidence=tier_overconfidence,
                    loss_aversion=tier_loss_aversion
                )
                profiles.append(profile)

        return profiles

    def generate_price_history(self, market: Market) -> List[PricePoint]:
        """
        Generate realistic price evolution using geometric Brownian motion.

        Price moves toward true outcome over time with:
        - Random walk (Brownian motion)
        - Drift toward truth
        - Information shocks from news
        - Mean reversion
        - Time-varying volatility
        """
        config = self.config['markets']['price_dynamics']

        # Initial price based on uncertainty
        initial_range = config.get('initial_uncertainty', {'min': 0.35, 'max': 0.65})
        initial_price = random.uniform(initial_range['min'], initial_range['max'])

        # True probability (what the outcome will actually be)
        true_prob = 0.85 if market.true_outcome == 'Yes' else 0.15

        # Simulation parameters
        duration = (market.resolution_date - market.creation_date).total_seconds() / 3600  # hours
        if duration <= 0:
            duration = 24 * 30  # Default 30 days

        num_points = min(int(duration / 4), 500)  # Every 4 hours, max 500 points
        dt = duration / num_points

        # Volatility based on market phase
        base_vol = config.get('volatility', {}).get('moderate', 0.10)
        drift_rate = config.get('drift_rate', 0.02) / 24  # Per hour
        mean_reversion = config.get('mean_reversion_strength', 0.15)

        price_history = []
        current_price = initial_price
        current_time = market.creation_date

        for i in range(num_points):
            # Time-varying volatility (higher early, lower late)
            time_fraction = i / num_points
            volatility = base_vol * (1.5 - 0.8 * time_fraction)

            # Brownian motion
            random_shock = random.gauss(0, 1) * volatility * math.sqrt(dt / 24)

            # Drift toward true probability
            drift = drift_rate * (true_prob - current_price) * dt

            # Mean reversion (prevent extreme values)
            reversion = mean_reversion * (0.5 - current_price) * dt if abs(current_price - 0.5) > 0.3 else 0

            # Apply news events
            news_impact = 0
            for event in market.news_events:
                hours_since = (current_time - event.timestamp).total_seconds() / 3600
                if 0 <= hours_since <= event.duration_hours:
                    # Decaying impact
                    decay = math.exp(-hours_since / (event.duration_hours / 2))
                    news_impact += event.magnitude * event.direction * decay

            # Update price
            new_price = current_price + drift + reversion + random_shock + news_impact

            # Clamp to valid range
            new_price = max(0.02, min(0.98, new_price))

            # Calculate volume (higher near resolution and during news)
            base_volume = random.uniform(1000, 10000)
            if time_fraction > 0.8:  # Near resolution
                base_volume *= 2
            if news_impact != 0:
                base_volume *= 1.5

            price_history.append(PricePoint(
                timestamp=current_time,
                price=new_price,
                volume=base_volume,
                event='news' if news_impact != 0 else None
            ))

            current_price = new_price
            current_time += timedelta(hours=dt)

        return price_history

    def generate_news_events(self, market: Market) -> List[NewsEvent]:
        """Generate news events that affect market prices."""
        if not self.config.get('news_events', {}).get('enabled', False):
            return []

        news_config = self.config['news_events']
        events = []

        # Determine number of events based on market duration
        duration_days = (market.resolution_date - market.creation_date).days
        avg_events_per_week = self.config.get('temporal_dynamics', {}).get('news_cycles', {}).get('events_per_week', 3)
        expected_events = (duration_days / 7) * avg_events_per_week * news_config.get('types', {}).get('breaking_news', {}).get('frequency', 0.25)

        num_events = max(0, int(random.gauss(expected_events, expected_events * 0.3)))

        for _ in range(num_events):
            # Pick event type
            event_types = list(news_config.get('types', {}).keys())
            if not event_types:
                continue

            event_type = random.choice(event_types)
            event_config = news_config['types'][event_type]

            # Check if this event type affects this category
            affected = event_config.get('categories_affected', ['all'])
            if affected != ['all'] and market.category not in affected:
                continue

            # Generate event
            impact_range = event_config.get('impact_range', [0.05, 0.20])
            magnitude = random.uniform(impact_range[0], impact_range[1])

            # Direction based on true outcome
            direction = 1 if market.true_outcome == 'Yes' else -1
            # Add some noise - sometimes news is misleading
            if random.random() < 0.2:
                direction *= -1

            # Random timestamp during market lifetime
            event_time = market.creation_date + timedelta(
                hours=random.uniform(24, (market.resolution_date - market.creation_date).total_seconds() / 3600 - 24)
            )

            duration = random.uniform(
                self.config.get('news_events', {}).get('types', {}).get(event_type, {}).get('decay_hours', [2, 48])[0] if isinstance(self.config.get('news_events', {}).get('types', {}).get(event_type, {}).get('decay_hours', [2, 48]), list) else 2,
                self.config.get('news_events', {}).get('types', {}).get(event_type, {}).get('decay_hours', [2, 48])[1] if isinstance(self.config.get('news_events', {}).get('types', {}).get(event_type, {}).get('decay_hours', [2, 48]), list) else 48
            )

            events.append(NewsEvent(
                timestamp=event_time,
                event_type=event_type,
                magnitude=magnitude,
                direction=direction,
                categories_affected=[market.category],
                duration_hours=duration
            ))

        return sorted(events, key=lambda e: e.timestamp)

    def create_markets(self) -> List[Market]:
        """Create markets with full lifecycle simulation."""
        markets = []
        config = self.config['markets']
        total_markets = config['total']
        resolved_ratio = config['resolved_ratio']
        categories = config['categories']
        liquidity_levels = config.get('market_lifecycle', {}).get('liquidity_levels', {'high': 0.15, 'medium': 0.35, 'low': 0.50})
        lifecycle = config.get('market_lifecycle', {}).get('creation_to_resolution_days', {'min': 7, 'max': 180, 'median': 45})

        num_resolved = int(total_markets * resolved_ratio)

        # Assign markets to categories
        market_categories = []
        for cat, pct in categories.items():
            market_categories.extend([cat] * int(total_markets * pct))
        while len(market_categories) < total_markets:
            market_categories.append(random.choice(list(categories.keys())))
        random.shuffle(market_categories)

        # Create correlation clusters
        num_clusters = total_markets // 10
        cluster_assignments = {}
        for i in range(num_clusters):
            cluster_size = random.randint(2, 5)
            cluster_markets = random.sample(range(total_markets), min(cluster_size, total_markets - len(cluster_assignments)))
            for m in cluster_markets:
                if m not in cluster_assignments:
                    cluster_assignments[m] = i

        for i in range(total_markets):
            market_id = '0x' + secrets.token_hex(32)
            category = market_categories[i]
            title = self.generate_market_title(category)

            # Determine resolution status
            is_resolved = i < num_resolved
            true_outcome = random.choice(['Yes', 'No'])

            # Generate lifecycle dates
            duration_days = random.triangular(lifecycle['min'], lifecycle['max'], lifecycle['median'])

            if is_resolved:
                # Market already resolved
                resolution_date = self.simulation_end - timedelta(days=random.uniform(1, 90))
                creation_date = resolution_date - timedelta(days=duration_days)
                winning_outcome = true_outcome
            else:
                # Market still pending
                creation_date = self.simulation_end - timedelta(days=random.uniform(1, 60))
                resolution_date = creation_date + timedelta(days=duration_days)
                winning_outcome = None

            # Assign liquidity level
            liq_roll = random.random()
            if liq_roll < liquidity_levels.get('high', 0.15):
                liquidity = 'high'
            elif liq_roll < liquidity_levels.get('high', 0.15) + liquidity_levels.get('medium', 0.35):
                liquidity = 'medium'
            else:
                liquidity = 'low'

            # Difficulty based on how "surprising" the outcome is
            # Markets resolving to 50-50 expected outcome are harder
            difficulty = 0.3 + 0.4 * random.random()  # 0.3-0.7

            market = Market(
                market_id=market_id,
                title=title,
                category=category,
                creation_date=creation_date,
                resolution_date=resolution_date,
                true_outcome=true_outcome,
                winning_outcome=winning_outcome,
                liquidity_level=liquidity,
                difficulty=difficulty,
                correlation_cluster=cluster_assignments.get(i)
            )

            # Generate news events first
            market.news_events = self.generate_news_events(market)

            # Then generate price history
            market.price_history = self.generate_price_history(market)

            markets.append(market)

        return markets

    def get_price_at_time(self, market: Market, timestamp: datetime) -> float:
        """Get the market price at a specific timestamp."""
        if not market.price_history:
            return 0.5

        # Find closest price point
        for i, point in enumerate(market.price_history):
            if point.timestamp > timestamp:
                if i == 0:
                    return market.price_history[0].price
                return market.price_history[i - 1].price

        return market.price_history[-1].price

    def generate_trade(self, trader: TraderProfile, market: Market, timestamp: datetime) -> Optional[Dict]:
        """
        Generate a trade with realistic decision-making.

        Considers:
        - Trader skill level
        - Current market price
        - Trader's confidence threshold
        - Behavioral biases
        - News events
        """
        current_price = self.get_price_at_time(market, timestamp)

        # Skilled traders estimate true probability better
        skill = trader.skill_level
        true_prob = 0.8 if market.true_outcome == 'Yes' else 0.2

        # Trader's estimate (skill affects accuracy)
        noise = random.gauss(0, 0.3 * (1 - skill))
        trader_estimate = skill * true_prob + (1 - skill) * 0.5 + noise
        trader_estimate = max(0.1, min(0.9, trader_estimate))

        # Apply overconfidence bias
        if random.random() < trader.overconfidence:
            # Overconfident traders think their estimate is more accurate
            trader_estimate = 0.7 * trader_estimate + 0.3 * (1 if market.true_outcome == 'Yes' else 0)

        # Calculate perceived edge
        if trader_estimate > current_price:
            # Thinks Yes is underpriced
            perceived_edge = trader_estimate - current_price
            side = 'BUY'
            outcome = 'Yes'
        else:
            # Thinks No is underpriced (Yes is overpriced)
            perceived_edge = current_price - trader_estimate
            side = 'BUY'
            outcome = 'No'

        # Only trade if edge exceeds confidence threshold
        min_edge = self.config.get('trades', {}).get('trade_sizing', {}).get('min_edge_required', 0.05)
        if perceived_edge < min_edge:
            return None

        # Position sizing (Kelly criterion approximation)
        kelly = self.config.get('trades', {}).get('trade_sizing', {}).get('kelly_criterion', 0.5)
        max_position = self.config.get('trades', {}).get('trade_sizing', {}).get('max_position_pct', 0.20)

        # Kelly fraction: edge / odds
        position_fraction = min(kelly * perceived_edge * 2, max_position)

        # Generate volume
        min_vol, max_vol = trader.volume_range
        base_volume = random.uniform(min_vol, max_vol)
        volume = base_volume * position_fraction / 0.1  # Scale by position sizing

        # Calculate shares and price (with some slippage for large orders)
        price = current_price
        if market.liquidity_level == 'low' and volume > 5000:
            price += 0.02 * (1 if outcome == 'Yes' else -1)  # Slippage
        price = max(0.05, min(0.95, price))

        shares = volume / price

        # Determine if trade was successful (for resolved markets)
        was_successful = None
        trade_result = 'pending'
        if market.winning_outcome:
            was_successful = (outcome == market.winning_outcome)
            trade_result = 'won' if was_successful else 'lost'

            # Update trader stats
            trader.total_trades += 1
            trader.total_volume += volume
            if was_successful:
                trader.successful_trades += 1

        return {
            'trade_id': '0x' + secrets.token_hex(32),
            'trader_address': trader.address,
            'market_id': market.market_id,
            'market_title': market.title,
            'market_category': market.category,
            'outcome': outcome,
            'shares': shares,
            'price': price,
            'side': side,
            'timestamp': timestamp,
            'outcome_bet': outcome,
            'was_successful': was_successful,
            'trade_result': trade_result,
            'perceived_edge': perceived_edge
        }

    def generate_trades_for_market(self, market: Market, traders: List[TraderProfile]) -> List[Dict]:
        """Generate all trades for a single market over its lifetime."""
        trades = []
        config = self.config['trades']

        # Determine number of trades based on liquidity
        min_trades, max_trades = config.get('trades_per_market_range', [50, 200])
        liquidity_multiplier = {'high': 2.0, 'medium': 1.0, 'low': 0.5}
        mult = liquidity_multiplier.get(market.liquidity_level, 1.0)

        target_trades = int(random.uniform(min_trades, max_trades) * mult)

        # Select participating traders (weighted by diversification preference)
        participating = []
        for trader in traders:
            # Elite/good traders more likely to participate in more markets
            min_div, max_div = trader.diversification_range
            if len(trader.active_markets) < max_div:
                # Weight by skill for more realistic distribution
                weight = trader.skill_level * trader.avg_trades / 30
                if random.random() < weight:
                    participating.append(trader)
                    trader.active_markets.append(market.market_id)

        if not participating:
            participating = random.sample(traders, min(20, len(traders)))

        # Generate trade timestamps (more trades near resolution)
        market_duration = (market.resolution_date - market.creation_date).total_seconds()

        for _ in range(target_trades):
            if not participating:
                break

            # Select trader (skill-weighted)
            trader = random.choices(
                participating,
                weights=[t.skill_level for t in participating],
                k=1
            )[0]

            # Generate timestamp (biased toward resolution)
            # Use beta distribution to concentrate trades later
            time_fraction = random.betavariate(2, 5)  # More trades near end
            trade_time = market.creation_date + timedelta(seconds=market_duration * (1 - time_fraction))

            # Ensure trade is before resolution
            if market.winning_outcome and trade_time > market.resolution_date:
                trade_time = market.resolution_date - timedelta(hours=random.uniform(1, 24))

            # Consider trader reaction time to news
            for event in market.news_events:
                hours_since_event = (trade_time - event.timestamp).total_seconds() / 3600
                min_react, max_react = trader.reaction_time_hours
                if 0 < hours_since_event < max_react:
                    # Trader might be reacting to this news
                    if hours_since_event > min_react:
                        # Within reaction window - more likely to trade
                        if random.random() < 0.3:
                            trade_time = event.timestamp + timedelta(
                                hours=random.uniform(min_react, max_react)
                            )

            # Generate the trade
            trade = self.generate_trade(trader, market, trade_time)
            if trade:
                trades.append(trade)

        return trades

    def clear_simulation_data(self, verbose: bool = True):
        """Clear only simulation data (keep production data intact)."""
        if verbose:
            print("[CLEAR] Removing simulation traders...")
            print("        Criteria: total_trades < 100 AND updated within 7 days")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Count traders to delete
        cursor.execute("""
            SELECT COUNT(*) FROM traders
            WHERE total_trades < 100
            AND (
                elo_last_updated > datetime('now', '-7 days')
                OR last_updated > datetime('now', '-7 days')
            )
        """)
        count_to_delete = cursor.fetchone()[0]

        if verbose and count_to_delete > 0:
            print(f"        Found {count_to_delete} simulation traders to remove")

        # Get trader addresses
        cursor.execute("""
            SELECT address FROM traders
            WHERE total_trades < 100
            AND (
                elo_last_updated > datetime('now', '-7 days')
                OR last_updated > datetime('now', '-7 days')
            )
        """)
        trader_addresses = [row[0] for row in cursor.fetchall()]

        if not trader_addresses:
            if verbose:
                print("[OK] No simulation traders found to delete")
            conn.close()
            return

        # Delete associated data
        placeholders = ','.join('?' * len(trader_addresses))
        cursor.execute(f"DELETE FROM trades WHERE trader_address IN ({placeholders})", trader_addresses)
        trades_deleted = cursor.rowcount

        cursor.execute(f"DELETE FROM positions WHERE trader_address IN ({placeholders})", trader_addresses)
        positions_deleted = cursor.rowcount

        cursor.execute(f"DELETE FROM traders WHERE address IN ({placeholders})", trader_addresses)
        traders_deleted = cursor.rowcount

        # Clean up simulation markets
        cursor.execute("""
            DELETE FROM markets
            WHERE market_id IN (
                SELECT m.market_id
                FROM markets m
                LEFT JOIN trades t ON m.market_id = t.market_id
                WHERE m.last_checked > datetime('now', '-7 days')
                GROUP BY m.market_id
                HAVING COUNT(t.trade_id) < 5
            )
        """)
        markets_deleted = cursor.rowcount

        conn.commit()
        conn.close()

        if verbose:
            print(f"[OK] Deleted {traders_deleted} traders")
            print(f"     Deleted {trades_deleted} trades")
            print(f"     Deleted {positions_deleted} positions")
            print(f"     Deleted {markets_deleted} low-activity markets")
            print()

    def seed_database(self, verbose: bool = True):
        """Main seeding logic with production-grade data."""
        if verbose:
            print("=" * 70)
            print("  PRODUCTION-GRADE POLYMARKET SIMULATION")
            print("=" * 70)
            print()
            print(f"Configuration: {self.config.get('description', 'Custom')}")
            print(f"Seed: {self.seed}")
            print(f"Duration: {self.config.get('simulation_duration_days', 180)} days")
            print()

        # Step 1: Generate traders
        if verbose:
            print("[1/5] Generating trader profiles...")

        self.traders = self.create_trader_profiles()
        tier_counts = defaultdict(int)
        for t in self.traders:
            tier_counts[t.tier] += 1

        if verbose:
            for tier, count in tier_counts.items():
                print(f"       {tier.upper()}: {count} traders")
            print(f"[OK] {len(self.traders)} traders created")
            print()

        # Step 2: Generate markets with price histories
        if verbose:
            print("[2/5] Generating markets with price evolution...")

        self.markets = self.create_markets()
        cat_counts = defaultdict(int)
        resolved_count = 0
        for m in self.markets:
            cat_counts[m.category] += 1
            if m.winning_outcome:
                resolved_count += 1

        if verbose:
            for cat, count in sorted(cat_counts.items()):
                print(f"       {cat}: {count} markets")
            print(f"[OK] {len(self.markets)} markets created ({resolved_count} resolved)")
            print()

        # Step 3: Generate trades
        if verbose:
            print("[3/5] Generating trades across markets...")

        all_trades = []
        for i, market in enumerate(self.markets):
            trades = self.generate_trades_for_market(market, self.traders)
            all_trades.extend(trades)

            if verbose and (i + 1) % 50 == 0:
                print(f"       Progress: {i + 1}/{len(self.markets)} markets...")

        if verbose:
            buy_count = sum(1 for t in all_trades if t['side'] == 'BUY')
            print(f"[OK] {len(all_trades)} trades generated ({buy_count} BUY)")
            print()

        # Step 4: Save to database
        if verbose:
            print("[4/5] Saving to database...")

        # Save traders
        for trader in self.traders:
            win_rate = trader.successful_trades / trader.total_trades if trader.total_trades > 0 else 0.0
            self.db.add_or_update_trader(
                address=trader.address,
                total_trades=trader.total_trades,
                successful_trades=trader.successful_trades,
                win_rate=win_rate,
                total_volume=trader.total_volume,
                is_flagged=(trader.tier in ['elite', 'good'])
            )

        # Save markets
        for market in self.markets:
            self.db.update_market(
                market_id=market.market_id,
                title=market.title,
                category=market.category,
                end_date=market.resolution_date,
                resolved=market.winning_outcome is not None,
                winning_outcome=market.winning_outcome,
                resolution_date=market.resolution_date if market.winning_outcome else None,
                condition_id=market.market_id
            )

        # Save trades
        trades_saved = 0
        for trade in all_trades:
            success = self.db.add_trade(
                trade_id=trade['trade_id'],
                trader_address=trade['trader_address'],
                market_id=trade['market_id'],
                market_title=trade['market_title'],
                market_category=trade['market_category'],
                outcome=trade['outcome'],
                shares=trade['shares'],
                price=trade['price'],
                side=trade['side'],
                timestamp=trade['timestamp'],
                outcome_bet=trade['outcome_bet']
            )
            if success:
                trades_saved += 1

        if verbose:
            print(f"[OK] Saved {len(self.traders)} traders, {len(self.markets)} markets, {trades_saved} trades")
            print()

        # Step 5: Validation
        if verbose:
            print("[5/5] Validating data quality...")

        validation_result = self.validate_data(verbose=verbose)

        # Summary
        if verbose:
            print()
            print("=" * 70)
            print("  SEED COMPLETE")
            print("=" * 70)
            print()
            print("Database Summary:")
            print(f"  Traders: {len(self.traders)} ({tier_counts['elite']} elite, {tier_counts['good']} good)")
            print(f"  Markets: {len(self.markets)} ({resolved_count} resolved)")
            print(f"  Trades: {trades_saved}")
            print()
            print("Category Distribution:")
            for cat, count in sorted(cat_counts.items()):
                pct = count / len(self.markets) * 100
                print(f"  {cat}: {count} ({pct:.1f}%)")
            print()
            print("Next steps:")
            print("  1. Calculate ELO: py scripts/simulation/calculate_elo_simple.py")
            print("  2. Run full pipeline: py scripts/simulation/run_full_pipeline.py")
            print("  3. Validate realism: py scripts/simulation/validate_realism.py")
            print()

        return validation_result

    def validate_data(self, verbose: bool = True) -> bool:
        """Comprehensive validation of generated data."""
        errors = []

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Check 1: Unique trader addresses
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT address) FROM traders")
            total, unique = cursor.fetchone()
            if total != unique:
                errors.append(f"Duplicate traders: {total} total, {unique} unique")
            elif verbose:
                print("  [OK] All trader addresses unique")

            # Check 2: Unique market IDs
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT market_id) FROM markets")
            total, unique = cursor.fetchone()
            if total != unique:
                errors.append(f"Duplicate markets: {total} total, {unique} unique")
            elif verbose:
                print("  [OK] All market IDs unique")

            # Check 3: Valid prices
            cursor.execute("SELECT MIN(price), MAX(price) FROM trades")
            min_price, max_price = cursor.fetchone()
            if min_price and max_price:
                if min_price < 0 or max_price > 1:
                    errors.append(f"Invalid prices: [{min_price}, {max_price}]")
                elif verbose:
                    print(f"  [OK] Prices in valid range [{min_price:.3f}, {max_price:.3f}]")

            # Check 4: Category distribution
            cursor.execute("SELECT category, COUNT(*) FROM markets GROUP BY category")
            cat_dist = cursor.fetchall()
            if verbose:
                print(f"  [OK] {len(cat_dist)} categories represented")

            # Check 5: Resolved markets have outcomes
            cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1 AND winning_outcome IS NULL")
            invalid = cursor.fetchone()[0]
            if invalid > 0:
                errors.append(f"{invalid} resolved markets missing outcome")
            elif verbose:
                print("  [OK] All resolved markets have outcomes")

        finally:
            conn.close()

        if errors:
            if verbose:
                print(f"[FAIL] {len(errors)} validation errors:")
                for e in errors:
                    print(f"  [X] {e}")
            return False
        else:
            if verbose:
                print("[OK] Validation passed")
            return True


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Seed production-grade Polymarket simulation data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/simulation/seed_production_data.py --config experiments/configs/config_production.json
  py scripts/simulation/seed_production_data.py --config experiments/configs/config_production.json --clear-simulation
  py scripts/simulation/seed_production_data.py --validate-only
        """
    )

    parser.add_argument('--config', type=str, required=True,
                       help='Path to production config JSON file')
    parser.add_argument('--clear-simulation', action='store_true',
                       help='Clear simulation data before seeding')
    parser.add_argument('--seed', type=int,
                       help='Override random seed')
    parser.add_argument('--quiet', action='store_true',
                       help='Minimal output')
    parser.add_argument('--validate-only', action='store_true',
                       help='Only run validation')

    args = parser.parse_args()

    # Create simulator
    seed = args.seed if args.seed else 42
    sim = ProductionSimulator(config_path=args.config, seed=seed)

    # Clear if requested
    if args.clear_simulation:
        sim.clear_simulation_data(verbose=not args.quiet)

    # Validate only
    if args.validate_only:
        sim.validate_data(verbose=not args.quiet)
        return

    # Seed database
    try:
        sim.seed_database(verbose=not args.quiet)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Seeding cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
