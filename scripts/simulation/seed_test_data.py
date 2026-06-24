#!/usr/bin/env python3
"""
Polymarket Simulation Data Seeder

Generates realistic test data with known outcomes for:
- ELO algorithm testing
- Parameter optimization
- Strategy backtesting
- System validation

Usage:
    py scripts/seed_test_data.py --config experiments/config_default.json
    py scripts/seed_test_data.py --clear  # Clear DB and seed fresh
    py scripts/seed_test_data.py --quick  # Fast mode (50/20/500)
"""

import sys
import os
import json
import secrets
import random
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root and simulation dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from monitoring.database import Database
from _sim_db_guard import add_sim_db_args, resolve_sim_db, assert_safe_to_write, SIM_DB_DEFAULT


# Market title templates
MARKET_TEMPLATES = [
    "Will {country} {action} by {date}?",
    "Will {person} win {election} in {year}?",
    "{Country} {political_event} before {date}?",
    "Will {treaty} be signed in {year}?",
    "Will {conflict} escalate by {date}?",
    "{Leader} to {action} by {month} {year}?",
    "Will {country} join {alliance} in {year}?",
    "{Event} to happen before {date}?",
]

COUNTRIES = ["Russia", "China", "USA", "Iran", "Israel", "Ukraine", "Taiwan", "North Korea", "India", "Brazil"]
LEADERS = ["Trump", "Biden", "Putin", "Xi Jinping", "Netanyahu", "Zelenskyy"]
ACTIONS = ["invade", "strike", "sanction", "withdraw from", "sign treaty with", "impose tariffs on"]
EVENTS = ["NATO expansion", "Peace talks", "Trade agreement", "Military escalation", "Diplomatic breakthrough"]
YEARS = ["2025", "2026", "2027"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


class MarketSimulator:
    """Generate realistic Polymarket data with skill-based traders."""

    def __init__(self, config_path: str = None, seed: int = 42,
                 db_path: str = SIM_DB_DEFAULT):
        """Initialize with config file."""
        self.seed = seed
        random.seed(seed)

        # Load config
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                self.config = json.load(f)
        else:
            # Default config
            self.config = self._default_config()

        # Override seed if specified in config
        if 'seed' in self.config:
            self.seed = self.config['seed']
            random.seed(self.seed)

        self.db = Database(db_path)
        self.trader_profiles = []
        self.markets = []

    def _default_config(self) -> Dict:
        """Default configuration."""
        return {
            "seed": 42,
            "description": "Default balanced simulation",

            "traders": {
                "total": 100,
                "distribution": {
                    "elite": 0.05,
                    "good": 0.15,
                    "average": 0.50,
                    "poor": 0.30
                },
                "skill_ranges": {
                    "elite": [0.65, 0.80],
                    "good": [0.55, 0.63],
                    "average": [0.47, 0.54],
                    "poor": [0.30, 0.46]
                },
                "volume_ranges": {
                    "elite": [10000, 100000],
                    "good": [5000, 50000],
                    "average": [1000, 20000],
                    "poor": [500, 10000]
                },
                "trade_frequency": {
                    "elite": [30, 50],
                    "good": [20, 40],
                    "average": [10, 30],
                    "poor": [5, 20]
                }
            },

            "markets": {
                "total": 50,
                "resolved_ratio": 0.30,
                "category": "Geopolitics",
                "days_old_range": [1, 90]
            },

            "trades": {
                "total": 1000,
                "buy_sell_ratio": 0.80,
                "trades_per_market_range": [5, 30]
            },

            "options": {
                "clear_database": False,
                "validate": True,
                "verbose": True
            }
        }

    def _create_trader_profiles(self) -> List[Dict]:
        """Generate trader profiles with known skill levels."""
        profiles = []
        total_traders = self.config['traders']['total']
        distribution = self.config['traders']['distribution']
        skill_ranges = self.config['traders']['skill_ranges']
        volume_ranges = self.config['traders']['volume_ranges']
        trade_frequency = self.config['traders']['trade_frequency']

        # Calculate counts for each tier
        counts = {
            'elite': int(total_traders * distribution['elite']),
            'good': int(total_traders * distribution['good']),
            'average': int(total_traders * distribution['average']),
            'poor': int(total_traders * distribution['poor'])
        }

        # Adjust for rounding errors
        total_allocated = sum(counts.values())
        if total_allocated < total_traders:
            counts['average'] += (total_traders - total_allocated)

        # Generate profiles for each tier
        tier_index = {'elite': 0, 'good': 0, 'average': 0, 'poor': 0}

        for tier, count in counts.items():
            for i in range(count):
                tier_index[tier] += 1

                # Generate unique address
                address = '0x' + secrets.token_hex(20)

                # Assign skill level from range
                skill_min, skill_max = skill_ranges[tier]
                skill_level = random.uniform(skill_min, skill_max)

                # Assign volume range
                volume_range = volume_ranges[tier]

                # Assign trade frequency
                freq_min, freq_max = trade_frequency[tier]
                avg_trades = random.randint(freq_min, freq_max)

                profile = {
                    'address': address,
                    'tier': tier,
                    'tier_index': tier_index[tier],
                    'skill_level': skill_level,
                    'volume_range': volume_range,
                    'avg_trades_per_market': avg_trades,
                    'total_trades': 0,
                    'successful_trades': 0,
                    'total_volume': 0.0
                }

                profiles.append(profile)

        return profiles

    def _create_market_templates(self) -> List[Dict]:
        """Generate market templates."""
        markets = []
        total_markets = self.config['markets']['total']
        resolved_ratio = self.config['markets']['resolved_ratio']
        category = self.config['markets']['category']
        days_range = self.config['markets']['days_old_range']

        num_resolved = int(total_markets * resolved_ratio)

        for i in range(total_markets):
            # Generate unique market ID
            market_id = '0x' + secrets.token_hex(32)

            # Generate title from template
            template = random.choice(MARKET_TEMPLATES)
            title = template.format(
                country=random.choice(COUNTRIES),
                person=random.choice(LEADERS),
                action=random.choice(ACTIONS),
                election="presidential election",
                political_event=random.choice(EVENTS),
                treaty=random.choice(EVENTS),
                conflict=random.choice(EVENTS),
                date=f"{random.choice(MONTHS)} {random.randint(1, 28)}",
                year=random.choice(YEARS),
                month=random.choice(MONTHS),
                Leader=random.choice(LEADERS),
                Event=random.choice(EVENTS),
                Country=random.choice(COUNTRIES),
                alliance="NATO"
            )

            # Determine if resolved
            is_resolved = i < num_resolved
            winning_outcome = random.choice(['Yes', 'No']) if is_resolved else None

            # Generate timestamps
            days_old = random.uniform(days_range[0], days_range[1])
            end_date = datetime.now() - timedelta(days=days_old if is_resolved else -days_old)

            market = {
                'market_id': market_id,
                'title': title,
                'category': category,
                'end_date': end_date,
                'resolved': 1 if is_resolved else 0,
                'winning_outcome': winning_outcome,
                'condition_id': market_id,
                'api_id': str(i + 1),
                'days_old': days_old
            }

            markets.append(market)

        return markets

    def generate_trade(self, trader_profile: Dict, market: Dict, market_outcome: str = None) -> Dict:
        """
        Generate trade based on trader skill.

        CRITICAL: Skilled traders bet correctly more often.
        """
        skill = trader_profile['skill_level']

        # Determine if trader predicts correctly
        predicts_correctly = random.random() < skill

        if market_outcome == 'Yes':
            # Correct prediction = BUY Yes
            if predicts_correctly:
                side = 'BUY'
                outcome = 'Yes'
            else:
                # Wrong prediction = BUY No (or SELL Yes, equivalent)
                side = random.choice(['BUY', 'SELL'])
                outcome = 'No' if side == 'BUY' else 'Yes'

        elif market_outcome == 'No':
            # Correct prediction = BUY No
            if predicts_correctly:
                side = random.choice(['BUY', 'SELL'])
                outcome = 'No' if side == 'BUY' else 'Yes'
            else:
                # Wrong prediction = BUY Yes
                side = 'BUY'
                outcome = 'Yes'

        else:
            # Market not resolved - random prediction
            side = random.choice(['BUY', 'SELL'])
            outcome = random.choice(['Yes', 'No'])

        # Generate volume and shares
        min_vol, max_vol = trader_profile['volume_range']
        volume = random.uniform(min_vol, max_vol)

        # Price reflects market efficiency + noise
        if predicts_correctly and market_outcome:
            # Skilled trader getting good price on correct side
            price = random.uniform(0.45, 0.65)
        elif market_outcome:
            # Wrong side or unskilled trader
            price = random.uniform(0.35, 0.55)
        else:
            # Market not resolved - random price
            price = random.uniform(0.40, 0.60)

        shares = volume / price

        # Generate timestamp (chronologically before market end)
        if market['resolved']:
            # Trade happened before resolution
            days_before = random.uniform(0, market['days_old'])
            timestamp = datetime.now() - timedelta(days=days_before)
        else:
            # Recent trade on pending market
            days_ago = random.uniform(0, 30)
            timestamp = datetime.now() - timedelta(days=days_ago)

        # Update trader profile
        trader_profile['total_trades'] += 1
        trader_profile['total_volume'] += volume
        if predicts_correctly and market_outcome:
            trader_profile['successful_trades'] += 1

        return {
            'trade_id': '0x' + secrets.token_hex(32),
            'trader_address': trader_profile['address'],
            'market_id': market['market_id'],
            'market_title': market['title'],
            'market_category': market['category'],
            'outcome': outcome,
            'shares': shares,
            'price': price,
            'side': side,
            'timestamp': timestamp,
            'outcome_bet': outcome,
            'was_successful': predicts_correctly if market_outcome else None,
            'trade_result': 'won' if (predicts_correctly and market_outcome) else ('lost' if market_outcome else 'pending')
        }

    def clear_simulation_data(self, verbose: bool = True):
        """
        Clear only simulation data (recent traders with low trade counts).

        Keeps production data intact by only removing traders that:
        - Have < 100 total trades (production traders have 500+)
        - Were updated recently (within last 7 days)

        This allows re-running simulations without affecting production data.
        """
        if verbose:
            print("[CLEAR] Removing simulation traders...")
            print("        Criteria: total_trades < 100 AND updated within 7 days")
            print()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # First, count how many will be deleted
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

            # Show a few examples
            cursor.execute("""
                SELECT address, total_trades, last_updated
                FROM traders
                WHERE total_trades < 100
                AND (
                    elo_last_updated > datetime('now', '-7 days')
                    OR last_updated > datetime('now', '-7 days')
                )
                LIMIT 5
            """)

            examples = cursor.fetchall()
            for addr, trades, updated in examples:
                print(f"          - {addr[:20]}... (trades={trades})")

        # Get trader addresses to delete
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

        # Delete associated trades first (foreign key constraint)
        placeholders = ','.join('?' * len(trader_addresses))
        cursor.execute(f"""
            DELETE FROM trades
            WHERE trader_address IN ({placeholders})
        """, trader_addresses)

        trades_deleted = cursor.rowcount

        # Delete positions
        cursor.execute(f"""
            DELETE FROM positions
            WHERE trader_address IN ({placeholders})
        """, trader_addresses)

        positions_deleted = cursor.rowcount

        # Delete traders
        cursor.execute(f"""
            DELETE FROM traders
            WHERE address IN ({placeholders})
        """, trader_addresses)

        traders_deleted = cursor.rowcount

        # Also clean up simulation markets (markets with very few trades)
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

    def seed_database(self, clear_existing: bool = False):
        """Main seeding logic."""
        verbose = self.config['options'].get('verbose', True)

        if verbose:
            print("=" * 70)
            print("  POLYMARKET SIMULATION - SEED TEST DATA")
            print("=" * 70)
            print()
            print(f"Configuration: {self.config.get('description', 'Custom')}")
            print(f"Seed: {self.seed}")
            print()

        # Clear database if requested
        if clear_existing or self.config['options'].get('clear_database', False):
            if verbose:
                print("[CLEAR] Clearing existing data...")
            # TODO: Implement database clearing
            # For now, just note that we would clear here

        # Step 1: Generate and seed traders
        if verbose:
            print("[1/4] Seeding traders...")

        self.trader_profiles = self._create_trader_profiles()

        tier_counts = {'elite': 0, 'good': 0, 'average': 0, 'poor': 0}

        for profile in self.trader_profiles:
            tier = profile['tier']
            tier_counts[tier] += 1

            # Show first few of each tier
            if verbose and tier_counts[tier] <= 2:
                print(f"  [{tier.upper():7}] {profile['address'][:20]}... (skill={profile['skill_level']*100:.0f}%, ~{profile['avg_trades_per_market']} trades)")

            # Insert into database
            self.db.add_or_update_trader(
                address=profile['address'],
                total_trades=0,
                successful_trades=0,
                win_rate=0.0,
                total_volume=0.0,
                is_flagged=(tier in ['elite', 'good'])  # Flag top traders
            )

        if verbose:
            print(f"[OK] {len(self.trader_profiles)} traders seeded " +
                  f"({tier_counts['elite']} elite, {tier_counts['good']} good, " +
                  f"{tier_counts['average']} average, {tier_counts['poor']} poor)")
            print()

        # Step 2: Generate and seed markets
        if verbose:
            print("[2/4] Seeding markets...")

        self.markets = self._create_market_templates()

        resolved_count = 0
        for i, market in enumerate(self.markets):
            is_resolved = market['resolved'] == 1
            if is_resolved:
                resolved_count += 1

            # Show first few markets
            if verbose and i < 4:
                status = "RESOLVED" if is_resolved else "PENDING "
                outcome = f"-> {market['winning_outcome']}" if is_resolved else "-> TBD"
                print(f"  [{status}] {market['title'][:50]}... {outcome}")

            # Insert into database
            self.db.update_market(
                market_id=market['market_id'],
                title=market['title'],
                category=market['category'],
                end_date=market['end_date'],
                resolved=market['resolved'] == 1,
                winning_outcome=market['winning_outcome'],
                condition_id=market['condition_id']
            )

            # Update api_id separately if method exists
            if hasattr(self.db, 'update_market_api_id'):
                self.db.update_market_api_id(market['market_id'], market['api_id'])

        if verbose:
            print(f"[OK] {len(self.markets)} markets seeded ({resolved_count} resolved, {len(self.markets) - resolved_count} pending)")
            print()

        # Step 3: Generate and seed trades
        if verbose:
            print("[3/4] Seeding trades...")

        total_trades = self.config['trades']['total']
        buy_sell_ratio = self.config['trades']['buy_sell_ratio']

        trades_generated = 0
        buy_count = 0
        sell_count = 0

        # Distribute trades across markets
        trades_per_market = {}
        for market in self.markets:
            min_trades, max_trades = self.config['trades']['trades_per_market_range']
            trades_per_market[market['market_id']] = random.randint(min_trades, max_trades)

        # Generate trades for each market
        for market_idx, market in enumerate(self.markets):
            num_trades = trades_per_market[market['market_id']]
            market_outcome = market['winning_outcome']

            # Select traders for this market (weighted by avg_trades_per_market)
            participating_traders = random.choices(
                self.trader_profiles,
                k=min(num_trades, len(self.trader_profiles))
            )

            market_trades = 0
            for trader in participating_traders:
                if trades_generated >= total_trades:
                    break

                # Generate trade
                trade = self.generate_trade(trader, market, market_outcome)

                # Insert into database
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
                    trades_generated += 1
                    market_trades += 1

                    if trade['side'] == 'BUY':
                        buy_count += 1
                    else:
                        sell_count += 1

                    # Show progress
                    if verbose and trades_generated % 100 == 0:
                        print(f"  Progress: {trades_generated}/{total_trades} trades generated...")

            # Show market summary (first few)
            if verbose and market_idx < 3:
                status_symbol = "+" if market['resolved'] else "o"
                print(f"  {status_symbol} {market['title'][:40]}...  {market_trades} trades")

        if verbose:
            buy_pct = (buy_count / trades_generated * 100) if trades_generated > 0 else 0
            print(f"[OK] {trades_generated} trades seeded ({buy_count} BUY, {sell_count} SELL = {buy_pct:.1f}% BUY)")
            print()

        # Step 4: Update trader statistics
        if verbose:
            print("[4/4] Updating trader statistics...")

        for profile in self.trader_profiles:
            win_rate = profile['successful_trades'] / profile['total_trades'] if profile['total_trades'] > 0 else 0.0

            self.db.add_or_update_trader(
                address=profile['address'],
                total_trades=profile['total_trades'],
                successful_trades=profile['successful_trades'],
                win_rate=win_rate,
                total_volume=profile['total_volume'],
                is_flagged=(profile['tier'] in ['elite', 'good'])
            )

        if verbose:
            print(f"[OK] Trader statistics updated")
            print()

        # Validation
        if self.config['options'].get('validate', True):
            self.validate_data()

        # Print summary
        if verbose:
            print("=" * 70)
            print("  SEED COMPLETE")
            print("=" * 70)
            print()
            print("Database Summary:")
            print(f"  Traders: {len(self.trader_profiles)}")
            print(f"  Markets: {len(self.markets)} ({resolved_count} resolved, {len(self.markets) - resolved_count} pending)")
            print(f"  Trades: {trades_generated} ({buy_count} BUY, {sell_count} SELL)")
            print()
            print("Trader Distribution:")
            print(f"  Elite (65-80% skill): {tier_counts['elite']} traders")
            print(f"  Good (55-63% skill): {tier_counts['good']} traders")
            print(f"  Average (47-54% skill): {tier_counts['average']} traders")
            print(f"  Poor (30-46% skill): {tier_counts['poor']} traders")
            print()
            print("Next steps:")
            print("  1. Calculate ELO: py scripts/calculate_elo.py")
            print("  2. Verify rankings: py scripts/verify_elo_rankings.py")
            print("  3. Run backtests: py scripts/backtest_strategy.py")
            print()
            print("Reproducibility:")
            print(f"  Seed: {self.seed}")
            print(f"  Command: py scripts/seed_test_data.py --seed {self.seed}")
            print()

    def validate_data(self):
        """Comprehensive validation checks."""
        verbose = self.config['options'].get('verbose', True)

        if verbose:
            print("[VALIDATE] Running data validation...")

        errors = []

        # Get data from database
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Check 1: Unique trader addresses
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT address) FROM traders")
            total, unique = cursor.fetchone()
            if total != unique:
                errors.append(f"Duplicate trader addresses: {total} total, {unique} unique")
            elif verbose:
                print("  [OK] All trader addresses unique")

            # Check 2: Unique market IDs
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT market_id) FROM markets")
            total, unique = cursor.fetchone()
            if total != unique:
                errors.append(f"Duplicate market IDs: {total} total, {unique} unique")
            elif verbose:
                print("  [OK] All market IDs unique")

            # Check 3: Unique trade IDs
            cursor.execute("SELECT COUNT(*), COUNT(DISTINCT trade_id) FROM trades")
            total, unique = cursor.fetchone()
            if total != unique:
                errors.append(f"Duplicate trade IDs: {total} total, {unique} unique")
            elif verbose:
                print("  [OK] All trade IDs unique")

            # Check 4: Foreign key validity (trades -> traders)
            cursor.execute("""
                SELECT COUNT(*) FROM trades
                WHERE trader_address NOT IN (SELECT address FROM traders)
            """)
            invalid_fk = cursor.fetchone()[0]
            if invalid_fk > 0:
                errors.append(f"Invalid foreign keys: {invalid_fk} trades reference non-existent traders")
            elif verbose:
                print("  [OK] All foreign keys valid")

            # Check 5: Price range
            cursor.execute("SELECT MIN(price), MAX(price) FROM trades")
            min_price, max_price = cursor.fetchone()
            if min_price < 0 or max_price > 1:
                errors.append(f"Invalid prices: range [{min_price}, {max_price}] outside [0, 1]")
            elif verbose:
                print("  [OK] All prices in [0.0, 1.0]")

            # Check 6: Positive shares
            cursor.execute("SELECT COUNT(*) FROM trades WHERE shares <= 0")
            invalid_shares = cursor.fetchone()[0]
            if invalid_shares > 0:
                errors.append(f"Invalid shares: {invalid_shares} trades have shares <= 0")
            elif verbose:
                print("  [OK] All shares > 0")

            # Check 7: Resolved markets have outcomes
            cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1 AND winning_outcome IS NULL")
            invalid_outcomes = cursor.fetchone()[0]
            if invalid_outcomes > 0:
                errors.append(f"Invalid outcomes: {invalid_outcomes} resolved markets missing winning_outcome")
            elif verbose:
                print("  [OK] Resolved markets have outcomes")

            # Check 8: Trade distribution
            cursor.execute("SELECT side, COUNT(*) FROM trades GROUP BY side")
            side_counts = {row[0]: row[1] for row in cursor.fetchall()}
            buy_count = side_counts.get('BUY', 0)
            sell_count = side_counts.get('SELL', 0)
            total_trades = buy_count + sell_count

            if total_trades > 0:
                buy_pct = buy_count / total_trades * 100
                if verbose:
                    print(f"  [OK] Trade distribution: {buy_pct:.1f}% BUY, {100-buy_pct:.1f}% SELL")

        finally:
            conn.close()

        # Report results
        if errors:
            if verbose:
                print(f"[FAIL] Validation failed - {len(errors)} error(s):")
                for error in errors:
                    print(f"  [X] {error}")
            return False
        else:
            if verbose:
                print(f"[OK] Validation passed - 0 errors")
            return True


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Seed Polymarket simulation test data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  py scripts/seed_test_data.py                                    # Use default config
  py scripts/seed_test_data.py --config experiments/config_realistic.json
  py scripts/seed_test_data.py --clear                            # Clear DB first
  py scripts/seed_test_data.py --quick                            # Fast mode
  py scripts/seed_test_data.py --seed 12345                       # Custom seed
        """
    )

    parser.add_argument('--config', type=str, help='Path to config JSON file')
    parser.add_argument('--clear', action='store_true', help='Clear database before seeding')
    parser.add_argument('--clear-simulation', action='store_true', help='Clear only simulation data (keep production data)')
    parser.add_argument('--quick', action='store_true', help='Quick mode (50 traders, 20 markets, 500 trades)')
    parser.add_argument('--seed', type=int, help='Random seed for reproducibility')
    parser.add_argument('--quiet', action='store_true', help='Quiet mode (minimal output)')
    parser.add_argument('--validate-only', action='store_true', help='Only run validation, no seeding')
    add_sim_db_args(parser)

    args = parser.parse_args()

    # Resolve DB path — default is simulation_test.db, NOT production
    db_path = resolve_sim_db(args)

    # Guard: seeder always writes, so refuse production unless explicitly unlocked
    assert_safe_to_write(db_path, args.allow_production_write)

    # Create simulator
    seed = args.seed if args.seed else 42
    sim = MarketSimulator(config_path=args.config, seed=seed, db_path=db_path)

    # Apply quick mode
    if args.quick:
        sim.config['traders']['total'] = 50
        sim.config['markets']['total'] = 20
        sim.config['trades']['total'] = 500

    # Apply quiet mode
    if args.quiet:
        sim.config['options']['verbose'] = False

    # Apply clear flag
    if args.clear:
        sim.config['options']['clear_database'] = True

    # Clear simulation data if requested
    if args.clear_simulation:
        sim.clear_simulation_data()

    # Run validation only
    if args.validate_only:
        sim.validate_data()
        return

    # Seed database
    try:
        sim.seed_database(clear_existing=args.clear)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Seeding cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
