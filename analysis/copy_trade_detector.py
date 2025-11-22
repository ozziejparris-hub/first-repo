#!/usr/bin/env python3
"""
Copy Trade Detector Analysis Tool

Detects copy trading relationships by analyzing time-lagged position copying.
Identifies:
1. Leader → follower relationships (time lag analysis)
2. Copy trading networks (who follows who)
3. Trader classifications (Leaders/Followers/Independents)
4. Front-run opportunities (detect when leaders bet, followers will follow)
"""

import os
import sys
import sqlite3
import argparse
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import csv

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitoring.database import Database
from analysis.correlation_matrix import TraderCorrelationMatrix


class CopyTradeDetector:
    """
    Detects copy trading relationships and builds follower networks.

    Uses time-lagged position analysis to identify who copies who.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize with database and correlation matrix integration.

        Args:
            db_path: Path to database
        """
        if db_path:
            self.db = Database(db_path)
        else:
            self.db = Database()

        # Initialize correlation matrix analyzer for efficiency
        self.correlation_analyzer = TraderCorrelationMatrix(db_path)

        # Cache for performance
        self.trader_trades_cache = {}
        self.copy_scores_cache = {}

        # Get high correlation pairs as candidates
        print("[COPY DETECTOR] Loading correlation matrix data...")
        corr_data = self.correlation_analyzer.export_for_integration()
        self.high_corr_pairs = corr_data['high_correlation_pairs']
        print(f"[COPY DETECTOR] Found {len(self.high_corr_pairs)} high correlation pairs to analyze")

    def _get_trader_trades(self, trader_address: str) -> List[Dict]:
        """Get all trades for a trader (with caching)."""
        if trader_address in self.trader_trades_cache:
            return self.trader_trades_cache[trader_address]

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, outcome, timestamp, side, shares, price
            FROM trades
            WHERE trader_address = ?
            ORDER BY timestamp
        """, (trader_address,))

        trades = []
        for row in cursor.fetchall():
            trades.append({
                'market_id': row[0],
                'outcome': row[1],
                'timestamp': row[2],
                'side': row[3],
                'shares': row[4],
                'price': row[5]
            })

        conn.close()
        self.trader_trades_cache[trader_address] = trades
        return trades

    def calculate_time_lag(self, trader_a: str, trader_b: str, market_id: str) -> Optional[float]:
        """
        Calculate time lag between trader A and B for specific market.

        Returns:
            Time lag in hours (positive = B trades after A)
            None if they don't trade this market
        """
        trades_a = self._get_trader_trades(trader_a)
        trades_b = self._get_trader_trades(trader_b)

        # Get first trade on this market for each trader
        time_a = None
        time_b = None

        for trade in trades_a:
            if trade['market_id'] == market_id:
                try:
                    time_a = datetime.fromisoformat(str(trade['timestamp']).replace('Z', '+00:00'))
                    break
                except:
                    continue

        for trade in trades_b:
            if trade['market_id'] == market_id:
                try:
                    time_b = datetime.fromisoformat(str(trade['timestamp']).replace('Z', '+00:00'))
                    break
                except:
                    continue

        if not time_a or not time_b:
            return None

        # Calculate lag in hours
        lag_seconds = (time_b - time_a).total_seconds()
        lag_hours = lag_seconds / 3600

        return lag_hours

    def calculate_copy_score(self, leader: str, follower: str) -> Dict:
        """
        Calculate copy score for potential leader → follower relationship.

        Returns comprehensive metrics including time consistency, outcome matching,
        order preservation, and volume correlation.
        """
        # Check cache
        cache_key = (leader, follower)
        if cache_key in self.copy_scores_cache:
            return self.copy_scores_cache[cache_key]

        trades_leader = self._get_trader_trades(leader)
        trades_follower = self._get_trader_trades(follower)

        # Group trades by market
        markets_leader = defaultdict(list)
        markets_follower = defaultdict(list)

        for trade in trades_leader:
            markets_leader[trade['market_id']].append(trade)

        for trade in trades_follower:
            markets_follower[trade['market_id']].append(trade)

        # Find shared markets
        shared_markets = set(markets_leader.keys()) & set(markets_follower.keys())

        if len(shared_markets) < 3:
            return {
                'copy_score': 0.0,
                'time_consistency': 0.0,
                'outcome_matching': 0.0,
                'order_preservation': 0.0,
                'volume_correlation': 0.0,
                'shared_markets': len(shared_markets),
                'avg_lag_hours': 0.0,
                'lag_std_dev': 0.0
            }

        # Calculate metrics
        time_lags = []
        outcome_matches = 0
        order_preserved = 0
        volume_diffs = []

        for market_id in shared_markets:
            lag = self.calculate_time_lag(leader, follower, market_id)

            if lag is not None and 0.25 <= lag <= 48:  # 15 min to 48 hours
                time_lags.append(lag)

                # Check outcome matching
                leader_outcome = markets_leader[market_id][0]['outcome']
                follower_outcome = markets_follower[market_id][0]['outcome']

                if leader_outcome.lower() == follower_outcome.lower():
                    outcome_matches += 1

                # Order preservation (follower always after leader)
                if lag > 0:
                    order_preserved += 1

                # Volume correlation
                leader_volume = sum(t['shares'] for t in markets_leader[market_id])
                follower_volume = sum(t['shares'] for t in markets_follower[market_id])

                if leader_volume > 0:
                    volume_ratio = min(follower_volume / leader_volume, 2.0)
                    volume_diffs.append(abs(1.0 - volume_ratio))

        if not time_lags:
            return {
                'copy_score': 0.0,
                'time_consistency': 0.0,
                'outcome_matching': 0.0,
                'order_preservation': 0.0,
                'volume_correlation': 0.0,
                'shared_markets': len(shared_markets),
                'avg_lag_hours': 0.0,
                'lag_std_dev': 0.0
            }

        # Calculate component scores
        avg_lag = statistics.mean(time_lags)
        std_dev = statistics.stdev(time_lags) if len(time_lags) > 1 else 0.0

        # Time consistency: low std dev = high consistency
        time_consistency = max(0.0, 1.0 - (std_dev / 24.0))

        # Outcome matching: percentage of matches
        outcome_matching = outcome_matches / len(time_lags) if time_lags else 0.0

        # Order preservation: percentage where follower comes after
        order_preservation = order_preserved / len(time_lags) if time_lags else 0.0

        # Volume correlation: similarity in bet sizes
        volume_correlation = 1.0 - (statistics.mean(volume_diffs) if volume_diffs else 1.0)
        volume_correlation = max(0.0, min(1.0, volume_correlation))

        # Calculate weighted copy score
        copy_score = (
            (time_consistency * 0.40) +
            (outcome_matching * 0.30) +
            (order_preservation * 0.20) +
            (volume_correlation * 0.10)
        )

        result = {
            'copy_score': round(copy_score, 3),
            'time_consistency': round(time_consistency, 3),
            'outcome_matching': round(outcome_matching, 3),
            'order_preservation': round(order_preservation, 3),
            'volume_correlation': round(volume_correlation, 3),
            'shared_markets': len(time_lags),
            'avg_lag_hours': round(avg_lag, 2),
            'lag_std_dev': round(std_dev, 2)
        }

        # Cache result
        self.copy_scores_cache[cache_key] = result

        return result

    def detect_copy_relationships(self, min_shared_markets: int = 5,
                                 min_copy_score: float = 0.5) -> List[Dict]:
        """
        Detect all copy trading relationships.

        Args:
            min_shared_markets: Minimum markets to analyze relationship
            min_copy_score: Minimum score to flag as copying

        Returns:
            List of copy relationships with scores and metadata
        """
        print(f"[COPY DETECTOR] Detecting copy relationships (min_markets={min_shared_markets}, min_score={min_copy_score})...")

        relationships = []
        checked_pairs = 0

        # Use high correlation pairs as candidates (efficiency boost)
        for pair_data in self.high_corr_pairs:
            trader_a = pair_data['trader_a']
            trader_b = pair_data['trader_b']

            # Test both directions (A→B and B→A)
            for leader, follower in [(trader_a, trader_b), (trader_b, trader_a)]:
                checked_pairs += 1
                if checked_pairs % 20 == 0:
                    print(f"[COPY DETECTOR] Checked {checked_pairs} pairs...")

                score_data = self.calculate_copy_score(leader, follower)

                if (score_data['shared_markets'] >= min_shared_markets and
                    score_data['copy_score'] >= min_copy_score):

                    # Classify relationship strength
                    if score_data['copy_score'] >= 0.9:
                        rel_type = "PERFECT"
                    elif score_data['copy_score'] >= 0.7:
                        rel_type = "STRONG"
                    elif score_data['copy_score'] >= 0.5:
                        rel_type = "MODERATE"
                    else:
                        rel_type = "WEAK"

                    relationships.append({
                        'leader': leader,
                        'follower': follower,
                        'copy_score': score_data['copy_score'],
                        'avg_lag_hours': score_data['avg_lag_hours'],
                        'shared_markets': score_data['shared_markets'],
                        'relationship_type': rel_type,
                        'time_consistency': score_data['time_consistency'],
                        'outcome_matching': score_data['outcome_matching']
                    })

        # Sort by copy score (highest first)
        relationships.sort(key=lambda x: x['copy_score'], reverse=True)

        print(f"[COPY DETECTOR] Found {len(relationships)} copy relationships")

        return relationships

    def build_copy_network(self) -> Dict:
        """
        Build complete copy trading network.

        Returns network structure with leaders, followers, and independents.
        """
        print("[COPY NETWORK] Building copy trading network...")

        relationships = self.detect_copy_relationships()

        # Build adjacency lists
        leaders = defaultdict(list)  # leader -> [followers]
        followers = defaultdict(list)  # follower -> [leaders]

        for rel in relationships:
            leaders[rel['leader']].append({
                'trader': rel['follower'],
                'copy_score': rel['copy_score'],
                'avg_lag': rel['avg_lag_hours']
            })
            followers[rel['follower']].append({
                'trader': rel['leader'],
                'copy_score': rel['copy_score'],
                'avg_lag': rel['avg_lag_hours']
            })

        # Get all traders
        all_traders = set(self.db.get_flagged_traders())

        # Identify independents (no copy relationships)
        involved_traders = set(leaders.keys()) | set(followers.keys())
        independent = list(all_traders - involved_traders)

        network_stats = {
            'total_traders': len(all_traders),
            'leaders_count': len(leaders),
            'followers_count': len(followers),
            'independent_count': len(independent),
            'relationships_count': len(relationships),
            'avg_followers_per_leader': sum(len(f) for f in leaders.values()) / len(leaders) if leaders else 0
        }

        print(f"[COPY NETWORK] Network built: {network_stats['leaders_count']} leaders, "
              f"{network_stats['followers_count']} followers, "
              f"{network_stats['independent_count']} independent")

        return {
            'leaders': dict(leaders),
            'followers': dict(followers),
            'independent': independent,
            'network_stats': network_stats
        }

    def classify_trader(self, trader_address: str) -> Dict:
        """
        Classify a specific trader's copy trading behavior.

        Returns classification, scores, and relationships.
        """
        network = self.build_copy_network()

        is_leader = trader_address in network['leaders']
        is_follower = trader_address in network['followers']

        if is_leader and is_follower:
            classification = "MIXED (Leader & Follower)"
        elif is_leader:
            classification = "LEADER"
        elif is_follower:
            classification = "FOLLOWER"
        else:
            classification = "INDEPENDENT"

        # Calculate leader score
        follower_count = len(network['leaders'].get(trader_address, []))
        leader_score = min(100, (follower_count / 20.0) * 100)  # Scale to 0-100

        # Get independence score from correlation matrix
        corr_data = self.correlation_analyzer.export_for_integration()
        independence_score = corr_data['independence_scores'].get(trader_address, 50)

        # Calculate average reaction time if follower
        avg_reaction = 0.0
        if is_follower:
            lags = [f['avg_lag'] for f in network['followers'][trader_address]]
            avg_reaction = sum(lags) / len(lags) if lags else 0.0

        return {
            'trader_address': trader_address,
            'classification': classification,
            'followers': network['leaders'].get(trader_address, []),
            'follows': network['followers'].get(trader_address, []),
            'leader_score': round(leader_score, 1),
            'independence_score': independence_score,
            'avg_reaction_time': round(avg_reaction, 2)
        }

    def find_front_run_opportunities(self, lookback_hours: int = 12) -> List[Dict]:
        """
        Identify markets where leaders just bet (followers will follow).

        Returns opportunities to front-run the copy trading cascade.
        """
        print(f"[FRONT-RUN] Finding opportunities (lookback: {lookback_hours} hours)...")

        network = self.build_copy_network()
        opportunities = []

        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        # Check each leader's recent trades
        for leader, follower_list in network['leaders'].items():
            if len(follower_list) < 3:  # Need significant following
                continue

            trades = self._get_trader_trades(leader)

            # Find recent trades
            for trade in reversed(trades):  # Most recent first
                try:
                    trade_time = datetime.fromisoformat(str(trade['timestamp']).replace('Z', '+00:00'))
                except:
                    continue

                if trade_time < cutoff_time:
                    break  # Too old

                market_id = trade['market_id']

                # Check how many followers have copied this position
                copied_count = 0
                not_copied = []

                for follower_data in follower_list:
                    follower = follower_data['trader']
                    follower_trades = self._get_trader_trades(follower)

                    # Check if follower has traded this market yet
                    has_traded = any(t['market_id'] == market_id for t in follower_trades)

                    if has_traded:
                        copied_count += 1
                    else:
                        not_copied.append(follower)

                # Opportunity if many followers haven't copied yet
                expected_followers = len(not_copied)

                if expected_followers >= 3:  # At least 3 followers pending
                    # Calculate opportunity score
                    hours_since = (datetime.now() - trade_time).total_seconds() / 3600
                    avg_lag = sum(f['avg_lag'] for f in follower_list) / len(follower_list)

                    # Time to cascade completion
                    time_to_cascade = max(0, avg_lag - hours_since)

                    # Opportunity score: high if many followers pending and within lag window
                    urgency = max(0, 1.0 - (hours_since / avg_lag)) if avg_lag > 0 else 0
                    magnitude = expected_followers / len(follower_list)
                    opportunity_score = (urgency * 60) + (magnitude * 40)

                    if opportunity_score >= 50:  # Threshold for meaningful opportunity
                        # Get market title
                        conn = self.db.get_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT title FROM markets WHERE market_id = ?", (market_id,))
                        row = cursor.fetchone()
                        market_title = row[0] if row else "Unknown Market"
                        conn.close()

                        opportunities.append({
                            'market_id': market_id,
                            'market_title': market_title,
                            'leader': leader,
                            'leader_position': trade['outcome'],
                            'leader_timestamp': trade_time,
                            'expected_followers': expected_followers,
                            'time_to_cascade': round(time_to_cascade, 1),
                            'opportunity_score': round(opportunity_score, 1)
                        })

        # Sort by opportunity score (highest first)
        opportunities.sort(key=lambda x: x['opportunity_score'], reverse=True)

        print(f"[FRONT-RUN] Found {len(opportunities)} opportunities")

        return opportunities

    def validate_signal_independence(self, market_id: str, traders_on_market: List[str]) -> Dict:
        """
        Check if traders on a market are independent or copycats.

        Used by confidence_meter to validate signals.
        """
        network = self.build_copy_network()

        independent_traders = []
        follower_traders = []
        copy_relationships_on_market = []

        for trader in traders_on_market:
            if trader in network['independent']:
                independent_traders.append(trader)
            elif trader in network['followers']:
                follower_traders.append(trader)

                # Check if they're following someone also on this market
                for leader_data in network['followers'][trader]:
                    if leader_data['trader'] in traders_on_market:
                        copy_relationships_on_market.append(f"{leader_data['trader']}→{trader}")
            else:
                independent_traders.append(trader)  # Assume independent if no data

        total = len(traders_on_market)
        independent_count = len(independent_traders)
        follower_count = len(follower_traders)

        independence_ratio = independent_count / total if total > 0 else 0.0

        # Validation flag
        if independence_ratio >= 0.7:
            validation_flag = "VALID"
        elif independence_ratio >= 0.4:
            validation_flag = "WARNING"
        else:
            validation_flag = "INVALID"

        return {
            'market_id': market_id,
            'total_traders': total,
            'independent_traders': independent_count,
            'followers': follower_count,
            'independence_ratio': round(independence_ratio, 3),
            'copy_relationships': copy_relationships_on_market,
            'validation_flag': validation_flag
        }

    def generate_reports(self, output_dir: str):
        """
        Generate copy trade detection reports.

        Creates 5 comprehensive reports.
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d')

        print(f"\n[REPORTS] Generating copy trade reports in {output_dir}...")

        # Build data
        relationships = self.detect_copy_relationships()
        network = self.build_copy_network()
        opportunities = self.find_front_run_opportunities()

        # 1. Copy Relationships CSV
        rel_file = os.path.join(output_dir, f'copy_relationships_{timestamp}.csv')
        with open(rel_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Leader', 'Follower', 'Copy_Score', 'Avg_Lag_Hours',
                           'Shared_Markets', 'Relationship_Type', 'Time_Consistency'])

            for rel in relationships:
                writer.writerow([
                    rel['leader'][:10] + '...',
                    rel['follower'][:10] + '...',
                    rel['copy_score'],
                    rel['avg_lag_hours'],
                    rel['shared_markets'],
                    rel['relationship_type'],
                    rel['time_consistency']
                ])

        print(f"[REPORTS] ✅ Created {rel_file}")

        # 2. Copy Networks CSV
        net_file = os.path.join(output_dir, f'copy_networks_{timestamp}.csv')
        with open(net_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Leader', 'Follower_Count', 'Followers_List',
                           'Avg_Reaction_Time'])

            for leader, follower_list in sorted(network['leaders'].items(),
                                               key=lambda x: len(x[1]), reverse=True):
                followers_str = ', '.join([f[:10] + '...' for f in
                                          [fd['trader'] for fd in follower_list[:5]]])
                avg_lag = sum(f['avg_lag'] for f in follower_list) / len(follower_list)

                writer.writerow([
                    leader[:10] + '...',
                    len(follower_list),
                    followers_str,
                    round(avg_lag, 2)
                ])

        print(f"[REPORTS] ✅ Created {net_file}")

        # 3. Trader Classifications CSV
        class_file = os.path.join(output_dir, f'trader_classifications_{timestamp}.csv')
        with open(class_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Trader', 'Classification', 'Leader_Score',
                           'Independence_Score', 'Follows_Count', 'Followers_Count',
                           'Avg_Reaction_Time'])

            all_traders = self.db.get_flagged_traders()
            for trader in all_traders:
                classification = self.classify_trader(trader)

                writer.writerow([
                    trader[:10] + '...',
                    classification['classification'],
                    classification['leader_score'],
                    classification['independence_score'],
                    len(classification['follows']),
                    len(classification['followers']),
                    classification['avg_reaction_time']
                ])

        print(f"[REPORTS] ✅ Created {class_file}")

        # 4. Front-Run Opportunities CSV
        opp_file = os.path.join(output_dir, f'front_run_opportunities_{timestamp}.csv')
        with open(opp_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Market_Title', 'Leader', 'Leader_Position',
                           'Expected_Followers', 'Time_To_Cascade', 'Opportunity_Score'])

            for opp in opportunities:
                writer.writerow([
                    opp['market_title'][:50],
                    opp['leader'][:10] + '...',
                    opp['leader_position'],
                    opp['expected_followers'],
                    opp['time_to_cascade'],
                    opp['opportunity_score']
                ])

        print(f"[REPORTS] ✅ Created {opp_file}")

        # 5. Summary TXT
        summary_file = os.path.join(output_dir, f'copy_trade_summary_{timestamp}.txt')
        with open(summary_file, 'w') as f:
            f.write("="*70 + "\n")
            f.write("  COPY TRADE DETECTOR ANALYSIS SUMMARY\n")
            f.write("="*70 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Overall statistics
            f.write("OVERALL STATISTICS:\n")
            f.write(f"  Traders Analyzed: {network['network_stats']['total_traders']}\n")
            f.write(f"  Copy Relationships Detected: {len(relationships)}\n")
            f.write(f"  Leaders Identified: {network['network_stats']['leaders_count']}\n")
            f.write(f"  Followers Identified: {network['network_stats']['followers_count']}\n")
            f.write(f"  Independent Traders: {network['network_stats']['independent_count']}\n\n")

            # Top leaders
            f.write("TOP 10 LEADERS (Most Influential):\n")
            leader_list = sorted(network['leaders'].items(),
                               key=lambda x: len(x[1]), reverse=True)[:10]

            for i, (leader, follower_list) in enumerate(leader_list, 1):
                avg_lag = sum(f['avg_lag'] for f in follower_list) / len(follower_list)
                f.write(f"{i}. {leader[:10]}... - {len(follower_list)} followers, "
                       f"Avg lag: {avg_lag:.1f} hours\n")

            # Top followers
            f.write("\n\nTOP 10 FOLLOWERS (Fastest Copiers):\n")
            follower_list = []
            for follower, leader_list in network['followers'].items():
                avg_lag = sum(l['avg_lag'] for l in leader_list) / len(leader_list)
                avg_score = sum(l['copy_score'] for l in leader_list) / len(leader_list)
                follower_list.append((follower, len(leader_list), avg_lag, avg_score))

            follower_list.sort(key=lambda x: x[2])  # Sort by fastest reaction

            for i, (follower, count, avg_lag, avg_score) in enumerate(follower_list[:10], 1):
                f.write(f"{i}. {follower[:10]}... - Follows {count} leaders, "
                       f"Avg reaction: {avg_lag:.1f} hours, "
                       f"Copy score: {avg_score:.2f}\n")

            # Front-run opportunities
            f.write("\n\nFRONT-RUN OPPORTUNITIES:\n")
            if opportunities:
                for i, opp in enumerate(opportunities[:5], 1):
                    f.write(f"{i}. {opp['market_title'][:50]}\n")
                    f.write(f"   Leader: {opp['leader'][:10]}..., "
                          f"Expected followers: {opp['expected_followers']}, "
                          f"Score: {opp['opportunity_score']}/100\n")
            else:
                f.write("No significant opportunities detected.\n")

            f.write("\n" + "="*70 + "\n")

        print(f"[REPORTS] ✅ Created {summary_file}")
        print(f"\n[REPORTS] All reports generated successfully!\n")

    def display_copy_trade_dashboard(self):
        """Display copy trading analysis in terminal."""
        print("\n" + "="*70)
        print("  COPY TRADE DETECTOR ANALYSIS")
        print("="*70 + "\n")

        relationships = self.detect_copy_relationships()
        network = self.build_copy_network()
        opportunities = self.find_front_run_opportunities()

        # Overall statistics
        print("📊 OVERALL STATISTICS:")
        print(f"Traders Analyzed: {network['network_stats']['total_traders']}")
        print(f"Copy Relationships Detected: {len(relationships)}")
        print(f"Leaders Identified: {network['network_stats']['leaders_count']}")
        print(f"Followers Identified: {network['network_stats']['followers_count']}")
        print(f"Independent Traders: {network['network_stats']['independent_count']}\n")

        # Top leaders
        print("🏆 TOP LEADERS (Most Influential):\n")
        leader_list = sorted(network['leaders'].items(),
                           key=lambda x: len(x[1]), reverse=True)[:3]

        for i, (leader, follower_list) in enumerate(leader_list, 1):
            avg_lag = sum(f['avg_lag'] for f in follower_list) / len(follower_list)
            followers_str = ', '.join([f['trader'][:10] + '...' for f in follower_list[:3]])
            more = f" (+{len(follower_list) - 3} more)" if len(follower_list) > 3 else ""

            print(f"{i}. {leader[:10]}... - {len(follower_list)} followers, "
                  f"Avg lag: {avg_lag:.1f} hours")
            print(f"   Followers: {followers_str}{more}\n")

        # Top followers
        print("📉 TOP FOLLOWERS (Fastest Copiers):\n")
        follower_rankings = []
        for follower, leader_list in network['followers'].items():
            avg_lag = sum(l['avg_lag'] for l in leader_list) / len(leader_list)
            avg_score = sum(l['copy_score'] for l in leader_list) / len(leader_list)
            follower_rankings.append((follower, len(leader_list), avg_lag, avg_score))

        follower_rankings.sort(key=lambda x: x[2])  # Sort by reaction time

        for i, (follower, count, avg_lag, avg_score) in enumerate(follower_rankings[:3], 1):
            print(f"{i}. {follower[:10]}... - Follows {count} leader(s), "
                  f"Avg reaction: {avg_lag:.1f} hours, "
                  f"Copy score: {avg_score:.2f}\n")

        # Front-run opportunities
        print("⚠️  FRONT-RUN OPPORTUNITIES:\n")
        if opportunities:
            for i, opp in enumerate(opportunities[:3], 1):
                print(f"{i}. Market: {opp['market_title'][:50]}")
                print(f"   Leader: {opp['leader'][:10]}... bet {opp['leader_position']} "
                      f"{((datetime.now() - opp['leader_timestamp']).total_seconds() / 3600):.1f} hours ago")
                print(f"   Expected: {opp['expected_followers']} followers "
                      f"(ETA: {opp['time_to_cascade']:.1f} hours)")
                print(f"   Opportunity Score: {opp['opportunity_score']}/100", end="")
                if opp['opportunity_score'] >= 80:
                    print(" ⭐")
                else:
                    print()
                print()
        else:
            print("No significant opportunities detected.\n")

        print("="*70 + "\n")

    def export_for_integration(self) -> Dict:
        """
        Export copy trade data for other analysis tools.

        Returns data for confidence_meter, divergence_detector, etc.
        """
        relationships = self.detect_copy_relationships()
        network = self.build_copy_network()

        return {
            'copy_relationships': relationships,
            'leaders': network['leaders'],
            'followers': network['followers'],
            'independent_traders': network['independent'],
            'network_stats': network['network_stats']
        }


def main():
    """Main entry point for copy trade detector."""
    parser = argparse.ArgumentParser(
        description='Copy Trade Detector - Identify leader-follower relationships',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--min-markets', type=int, default=5,
                       help='Minimum shared markets to detect copying')
    parser.add_argument('--min-score', type=float, default=0.5,
                       help='Minimum copy score threshold')
    parser.add_argument('--lookback-hours', type=int, default=12,
                       help='Hours to look back for front-run opportunities')
    parser.add_argument('--db-path', type=str, default=None,
                       help='Path to database file')

    args = parser.parse_args()

    print("\n" + "="*70)
    print("  COPY TRADE DETECTOR ANALYSIS")
    print("="*70 + "\n")

    # Initialize
    detector = CopyTradeDetector(db_path=args.db_path)

    # Detect relationships
    print("Detecting copy trading relationships...")
    relationships = detector.detect_copy_relationships(
        min_shared_markets=args.min_markets,
        min_copy_score=args.min_score
    )

    # Build network
    print("Building copy trading network...")
    network = detector.build_copy_network()

    # Find opportunities
    print("Finding front-run opportunities...")
    opportunities = detector.find_front_run_opportunities(
        lookback_hours=args.lookback_hours
    )

    # Generate reports
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
    detector.generate_reports(reports_dir)

    # Display dashboard
    detector.display_copy_trade_dashboard()

    # Export for integration
    print("[EXPORT] Exporting data for integration with other tools...")
    integration_data = detector.export_for_integration()
    print(f"[EXPORT] ✅ Exported {len(integration_data['copy_relationships'])} relationships")
    print(f"[EXPORT] ✅ Identified {len(integration_data['leaders'])} leaders")
    print(f"[EXPORT] ✅ Identified {len(integration_data['followers'])} followers")

    print("\n✅ Copy trade detection complete!\n")


if __name__ == "__main__":
    main()
