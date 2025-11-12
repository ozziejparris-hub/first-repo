#!/usr/bin/env python3
"""
Trading Behavior Analysis Script

Analyzes trader behavior patterns including:
- Betting patterns (bet size, consistency)
- Market diversification
- Activity frequency and timing
- Trading style classification

Reads from polymarket_tracker.db without modifying it.
"""

import sqlite3
import csv
import os
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, Counter


class TradingBehaviorAnalyzer:
    """Analyzes trading behavior patterns and classifies trader styles."""

    def __init__(self, db_path: str = "polymarket_tracker.db"):
        self.db_path = db_path

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_trades(self, days_filter: Optional[int] = None) -> List[Dict]:
        """
        Get all trades from database.

        Args:
            days_filter: If specified, only get trades from last N days
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        if days_filter:
            cutoff_date = datetime.now() - timedelta(days=days_filter)
            cursor.execute("""
                SELECT * FROM trades
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
            """, (cutoff_date,))
        else:
            cursor.execute("SELECT * FROM trades ORDER BY timestamp ASC")

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return trades

    def calculate_betting_patterns(self, trades: List[Dict]) -> Dict:
        """Calculate betting pattern metrics for a trader's trades."""
        if not trades:
            return {
                'avg_bet_size': 0,
                'median_bet_size': 0,
                'min_bet_size': 0,
                'max_bet_size': 0,
                'std_dev_bet_size': 0,
                'total_volume': 0,
                'bet_size_consistency': 'N/A'
            }

        # Calculate bet sizes (shares * price)
        bet_sizes = []
        for trade in trades:
            shares = float(trade.get('shares', 0))
            price = float(trade.get('price', 0))
            bet_size = shares * price
            bet_sizes.append(bet_size)

        total_volume = sum(bet_sizes)
        avg_bet_size = statistics.mean(bet_sizes)
        median_bet_size = statistics.median(bet_sizes)
        min_bet_size = min(bet_sizes)
        max_bet_size = max(bet_sizes)

        # Standard deviation (measure of consistency)
        std_dev = statistics.stdev(bet_sizes) if len(bet_sizes) > 1 else 0

        # Consistency score: low std_dev relative to mean = consistent
        if avg_bet_size > 0:
            cv = (std_dev / avg_bet_size) * 100  # Coefficient of variation
            if cv < 30:
                consistency = "Very Consistent"
            elif cv < 60:
                consistency = "Moderately Consistent"
            elif cv < 100:
                consistency = "Variable"
            else:
                consistency = "Highly Variable"
        else:
            consistency = "N/A"

        return {
            'avg_bet_size': avg_bet_size,
            'median_bet_size': median_bet_size,
            'min_bet_size': min_bet_size,
            'max_bet_size': max_bet_size,
            'std_dev_bet_size': std_dev,
            'total_volume': total_volume,
            'bet_size_consistency': consistency,
            'coefficient_of_variation': cv if avg_bet_size > 0 else 0
        }

    def calculate_diversification(self, trades: List[Dict]) -> Dict:
        """Calculate market diversification metrics."""
        if not trades:
            return {
                'unique_markets': 0,
                'diversification_score': 0,
                'top_markets': [],
                'market_concentration': 'N/A'
            }

        # Count trades per market
        market_counts = Counter()
        market_titles = {}

        for trade in trades:
            market_id = trade.get('market_id', 'unknown')
            market_title = trade.get('market_title', 'Unknown Market')
            market_counts[market_id] += 1
            market_titles[market_id] = market_title

        unique_markets = len(market_counts)
        total_trades = len(trades)
        diversification_score = (unique_markets / total_trades * 100) if total_trades > 0 else 0

        # Top 3 most traded markets
        top_markets = []
        for market_id, count in market_counts.most_common(3):
            title = market_titles.get(market_id, 'Unknown')
            percentage = (count / total_trades * 100)
            top_markets.append({
                'market_id': market_id,
                'title': title[:40],
                'trade_count': count,
                'percentage': percentage
            })

        # Market concentration: what % of trades are in top market?
        if top_markets:
            top_market_pct = top_markets[0]['percentage']
            if top_market_pct > 50:
                concentration = "Highly Concentrated"
            elif top_market_pct > 30:
                concentration = "Moderately Concentrated"
            else:
                concentration = "Well Diversified"
        else:
            concentration = "N/A"

        return {
            'unique_markets': unique_markets,
            'diversification_score': diversification_score,
            'top_markets': top_markets,
            'market_concentration': concentration
        }

    def calculate_activity_frequency(self, trades: List[Dict]) -> Dict:
        """Calculate activity frequency and timing patterns."""
        if not trades:
            return {
                'total_trades': 0,
                'trades_per_day': 0,
                'trades_per_week': 0,
                'most_active_day': 'N/A',
                'most_active_hour': 'N/A',
                'activity_trend': 'N/A',
                'first_trade': None,
                'last_trade': None,
                'active_days': 0
            }

        # Parse timestamps
        timestamps = []
        for trade in trades:
            ts = trade.get('timestamp')
            if ts:
                try:
                    if isinstance(ts, str):
                        # Try parsing ISO format
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    elif isinstance(ts, (int, float)):
                        dt = datetime.fromtimestamp(ts)
                    else:
                        dt = datetime.fromisoformat(str(ts))
                    timestamps.append(dt)
                except:
                    continue

        if not timestamps:
            return {
                'total_trades': len(trades),
                'trades_per_day': 0,
                'trades_per_week': 0,
                'most_active_day': 'N/A',
                'most_active_hour': 'N/A',
                'activity_trend': 'N/A',
                'first_trade': None,
                'last_trade': None,
                'active_days': 0
            }

        timestamps.sort()
        first_trade = timestamps[0]
        last_trade = timestamps[-1]
        total_trades = len(trades)

        # Calculate trading period
        trading_period = (last_trade - first_trade).total_seconds()
        trading_days = max(trading_period / 86400, 1)  # At least 1 day

        trades_per_day = total_trades / trading_days
        trades_per_week = trades_per_day * 7

        # Day of week analysis
        day_counts = Counter(ts.strftime('%A') for ts in timestamps)
        most_active_day = day_counts.most_common(1)[0][0] if day_counts else 'N/A'

        # Hour of day analysis
        hour_counts = Counter(ts.hour for ts in timestamps)
        most_active_hour = hour_counts.most_common(1)[0][0] if hour_counts else 'N/A'

        # Activity trend (compare first half to second half)
        if len(timestamps) >= 4:
            midpoint = len(timestamps) // 2
            first_half = timestamps[:midpoint]
            second_half = timestamps[midpoint:]

            first_period = (first_half[-1] - first_half[0]).total_seconds() / 86400 or 1
            second_period = (second_half[-1] - second_half[0]).total_seconds() / 86400 or 1

            first_rate = len(first_half) / first_period
            second_rate = len(second_half) / second_period

            if second_rate > first_rate * 1.2:
                trend = "Increasing"
            elif second_rate < first_rate * 0.8:
                trend = "Decreasing"
            else:
                trend = "Stable"
        else:
            trend = "Insufficient Data"

        # Count unique active days
        active_days = len(set(ts.date() for ts in timestamps))

        return {
            'total_trades': total_trades,
            'trades_per_day': trades_per_day,
            'trades_per_week': trades_per_week,
            'most_active_day': most_active_day,
            'most_active_hour': f"{most_active_hour}:00" if isinstance(most_active_hour, int) else most_active_hour,
            'activity_trend': trend,
            'first_trade': first_trade,
            'last_trade': last_trade,
            'active_days': active_days,
            'trading_days': trading_days
        }

    def classify_trading_style(self, betting: Dict, diversification: Dict, activity: Dict) -> str:
        """
        Classify trader into a style category based on behavior patterns.
        """
        total_trades = activity['total_trades']
        avg_bet = betting['avg_bet_size']
        diversification_score = diversification['diversification_score']
        trades_per_day = activity['trades_per_day']

        # Define thresholds
        high_volume_trades = total_trades >= 50
        medium_volume_trades = 20 <= total_trades < 50
        low_volume_trades = total_trades < 20

        high_bet_size = avg_bet >= 100
        medium_bet_size = 20 <= avg_bet < 100
        low_bet_size = avg_bet < 20

        high_diversification = diversification_score >= 60
        medium_diversification = 30 <= diversification_score < 60
        low_diversification = diversification_score < 30

        high_frequency = trades_per_day >= 5
        medium_frequency = 1 <= trades_per_day < 5
        low_frequency = trades_per_day < 1

        # Weekend warrior check
        most_active_day = activity.get('most_active_day', '')
        is_weekend_focused = most_active_day in ['Saturday', 'Sunday']

        # Classification logic
        if high_volume_trades and high_frequency and high_diversification:
            return "Power User"

        if high_volume_trades and low_diversification:
            return "High Volume Specialist"

        if high_bet_size and low_volume_trades:
            return "Big Better"

        if low_bet_size and high_volume_trades and high_diversification:
            return "Micro Trader"

        if medium_diversification and medium_volume_trades and betting['bet_size_consistency'] == "Very Consistent":
            return "Cautious Diversifier"

        if is_weekend_focused and low_frequency:
            return "Weekend Warrior"

        if high_frequency and medium_diversification:
            return "Active Trader"

        if low_frequency and medium_bet_size:
            return "Casual Trader"

        if high_diversification and low_frequency:
            return "Strategic Explorer"

        if low_diversification and high_bet_size:
            return "Market Specialist"

        return "General Trader"

    def analyze_all_traders(self, days_filter: Optional[int] = None) -> Dict:
        """
        Analyze all traders and calculate comprehensive behavior metrics.

        Returns dict with trader_address as key and all metrics as value.
        """
        print(f"\n{'='*70}")
        print(f"TRADING BEHAVIOR ANALYSIS")
        if days_filter:
            print(f"Analyzing last {days_filter} days")
        else:
            print(f"Analyzing all time")
        print(f"{'='*70}\n")

        # Get all trades
        print("📊 Loading trades from database...")
        trades = self.get_all_trades(days_filter)
        print(f"Found {len(trades)} total trades")

        if not trades:
            print("❌ No trades found in database")
            return {}

        # Group trades by trader
        trader_trades = defaultdict(list)
        for trade in trades:
            trader_trades[trade['trader_address']].append(trade)

        print(f"Analyzing {len(trader_trades)} unique traders...\n")

        # Analyze each trader
        trader_metrics = {}

        for idx, (trader_address, trades_list) in enumerate(trader_trades.items(), 1):
            if idx % 20 == 0 or idx == len(trader_trades):
                print(f"Progress: {idx}/{len(trader_trades)} traders analyzed", end='\r')

            # Calculate all metrics
            betting = self.calculate_betting_patterns(trades_list)
            diversification = self.calculate_diversification(trades_list)
            activity = self.calculate_activity_frequency(trades_list)

            # Classify trading style
            trading_style = self.classify_trading_style(betting, diversification, activity)

            # Check for hot streak (high activity in last 48 hours)
            recent_trades = 0
            if activity['last_trade']:
                cutoff = datetime.now() - timedelta(hours=48)
                for trade in trades_list:
                    ts = trade.get('timestamp')
                    if ts:
                        try:
                            if isinstance(ts, str):
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            elif isinstance(ts, (int, float)):
                                dt = datetime.fromtimestamp(ts)
                            else:
                                continue

                            if dt >= cutoff:
                                recent_trades += 1
                        except:
                            continue

            is_hot_streak = recent_trades >= 5

            # Flag for low reliability (too few trades)
            low_reliability = activity['total_trades'] < 10

            trader_metrics[trader_address] = {
                'trader_address': trader_address,
                'trading_style': trading_style,
                'is_hot_streak': is_hot_streak,
                'recent_48h_trades': recent_trades,
                'low_reliability': low_reliability,
                **betting,
                **diversification,
                **activity
            }

        print(f"\nProgress: {len(trader_trades)}/{len(trader_trades)} traders analyzed ✓\n")

        return trader_metrics

    def generate_report(self, trader_metrics: Dict, days_filter: Optional[int] = None):
        """Generate and display behavior analysis report."""

        print(f"\n{'='*70}")
        print(f"TRADING BEHAVIOR REPORT")
        print(f"{'='*70}\n")

        if not trader_metrics:
            print("⚠️ No trader data to analyze")
            return

        # Filter out low reliability traders for statistics
        reliable_traders = {
            addr: metrics for addr, metrics in trader_metrics.items()
            if not metrics['low_reliability']
        }

        print(f"Total traders analyzed: {len(trader_metrics)}")
        print(f"Reliable traders (≥10 trades): {len(reliable_traders)}")
        print(f"Low reliability traders (<10 trades): {len(trader_metrics) - len(reliable_traders)}\n")

        if not reliable_traders:
            print("⚠️ No traders with enough trades for reliable analysis")
            return

        # Overall statistics
        all_trades = [m['total_trades'] for m in reliable_traders.values()]
        all_avg_bets = [m['avg_bet_size'] for m in reliable_traders.values()]
        all_diversification = [m['diversification_score'] for m in reliable_traders.values()]
        all_trades_per_day = [m['trades_per_day'] for m in reliable_traders.values()]

        print(f"📈 OVERALL STATISTICS:")
        print(f"   Average trades per trader: {statistics.mean(all_trades):.1f}")
        print(f"   Average bet size: ${statistics.mean(all_avg_bets):.2f}")
        print(f"   Average diversification score: {statistics.mean(all_diversification):.1f}%")
        print(f"   Average trades per day: {statistics.mean(all_trades_per_day):.2f}")

        # Hot streak traders
        hot_streak_traders = [m for m in reliable_traders.values() if m['is_hot_streak']]
        if hot_streak_traders:
            print(f"\n🔥 HOT STREAK TRADERS (≥5 trades in last 48h): {len(hot_streak_traders)}")

        # Trading style distribution
        style_counts = Counter(m['trading_style'] for m in reliable_traders.values())
        print(f"\n📊 TRADING STYLE DISTRIBUTION:")
        for style, count in style_counts.most_common():
            percentage = (count / len(reliable_traders) * 100)
            print(f"   {style}: {count} traders ({percentage:.1f}%)")

        # LEADERBOARDS
        print(f"\n{'='*70}")
        print(f"🏆 MOST ACTIVE TRADERS (by trades per day)")
        print(f"{'='*70}")
        top_active = sorted(
            reliable_traders.values(),
            key=lambda x: x['trades_per_day'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Trades/Day':<12}{'Total Trades':<14}{'Style':<25}")
        print(f"{'-'*70}")
        for i, trader in enumerate(top_active, 1):
            addr_short = trader['trader_address'][:12] + "..."
            print(f"{i:<6}{addr_short:<15}{trader['trades_per_day']:>7.2f}{trader['total_trades']:>12}{trader['trading_style']:<25}")

        print(f"\n{'='*70}")
        print(f"🎯 MOST DIVERSIFIED TRADERS (by unique markets)")
        print(f"{'='*70}")
        top_diversified = sorted(
            reliable_traders.values(),
            key=lambda x: x['unique_markets'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Unique Markets':<15}{'Div Score':<12}{'Concentration':<20}")
        print(f"{'-'*70}")
        for i, trader in enumerate(top_diversified, 1):
            addr_short = trader['trader_address'][:12] + "..."
            print(f"{i:<6}{addr_short:<15}{trader['unique_markets']:>12}{trader['diversification_score']:>9.1f}%  {trader['market_concentration']:<20}")

        print(f"\n{'='*70}")
        print(f"💰 BIGGEST BETTORS (by average bet size)")
        print(f"{'='*70}")
        top_bettors = sorted(
            reliable_traders.values(),
            key=lambda x: x['avg_bet_size'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Avg Bet':<12}{'Total Volume':<15}{'Consistency':<20}")
        print(f"{'-'*70}")
        for i, trader in enumerate(top_bettors, 1):
            addr_short = trader['trader_address'][:12] + "..."
            avg_bet = f"${trader['avg_bet_size']:,.2f}"
            volume = f"${trader['total_volume']:,.2f}"
            print(f"{i:<6}{addr_short:<15}{avg_bet:<12}{volume:<15}{trader['bet_size_consistency']:<20}")

        print(f"\n{'='*70}")
        print(f"⚡ POWER USERS (by combined metrics)")
        print(f"{'='*70}")

        # Calculate power score: trades_per_day * diversification * (avg_bet/100)
        for trader in reliable_traders.values():
            trader['power_score'] = (
                trader['trades_per_day'] *
                (trader['diversification_score'] / 10) *
                (trader['avg_bet_size'] / 10)
            )

        top_power = sorted(
            reliable_traders.values(),
            key=lambda x: x['power_score'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Power Score':<13}{'Style':<25}")
        print(f"{'-'*70}")
        for i, trader in enumerate(top_power, 1):
            addr_short = trader['trader_address'][:12] + "..."
            print(f"{i:<6}{addr_short:<15}{trader['power_score']:>10.2f}  {trader['trading_style']:<25}")

        # Activity by day of week
        print(f"\n{'='*70}")
        print(f"📅 MOST POPULAR TRADING DAYS")
        print(f"{'='*70}")
        day_counts = Counter(m['most_active_day'] for m in reliable_traders.values() if m['most_active_day'] != 'N/A')
        for day, count in day_counts.most_common():
            percentage = (count / len(reliable_traders) * 100)
            print(f"   {day}: {count} traders ({percentage:.1f}%)")

        print(f"\n{'='*70}\n")

    def save_to_csv(self, trader_metrics: Dict, filename: str = "trading_behavior_report.csv"):
        """Save behavior analysis results to CSV file."""

        # Sort by power score
        for trader in trader_metrics.values():
            trader['power_score'] = (
                trader.get('trades_per_day', 0) *
                (trader.get('diversification_score', 0) / 10) *
                (trader.get('avg_bet_size', 0) / 10)
            )

        sorted_traders = sorted(
            trader_metrics.values(),
            key=lambda x: x.get('power_score', 0),
            reverse=True
        )

        # Add timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(['Analysis Timestamp', timestamp])
            writer.writerow([])
            writer.writerow([
                'Rank',
                'Trader Address',
                'Trading Style',
                'Total Trades',
                'Avg Bet Size ($)',
                'Median Bet Size ($)',
                'Min Bet ($)',
                'Max Bet ($)',
                'Std Dev Bet ($)',
                'Total Volume ($)',
                'Bet Consistency',
                'Unique Markets',
                'Diversification Score (%)',
                'Market Concentration',
                'Trades Per Day',
                'Trades Per Week',
                'Most Active Day',
                'Most Active Hour',
                'Activity Trend',
                'Active Days',
                'Trading Period (days)',
                'Hot Streak (48h)',
                'Recent 48h Trades',
                'Power Score',
                'Low Reliability Flag'
            ])

            # Write data
            for i, trader in enumerate(sorted_traders, 1):
                # Top markets as string
                top_markets_str = '; '.join(
                    f"{m['title'][:30]} ({m['trade_count']})"
                    for m in trader.get('top_markets', [])[:3]
                )

                writer.writerow([
                    i,
                    trader['trader_address'],
                    trader['trading_style'],
                    trader['total_trades'],
                    f"{trader['avg_bet_size']:.2f}",
                    f"{trader['median_bet_size']:.2f}",
                    f"{trader['min_bet_size']:.2f}",
                    f"{trader['max_bet_size']:.2f}",
                    f"{trader['std_dev_bet_size']:.2f}",
                    f"{trader['total_volume']:.2f}",
                    trader['bet_size_consistency'],
                    trader['unique_markets'],
                    f"{trader['diversification_score']:.2f}",
                    trader['market_concentration'],
                    f"{trader['trades_per_day']:.2f}",
                    f"{trader['trades_per_week']:.2f}",
                    trader['most_active_day'],
                    trader['most_active_hour'],
                    trader['activity_trend'],
                    trader['active_days'],
                    f"{trader.get('trading_days', 0):.1f}",
                    'Yes' if trader['is_hot_streak'] else 'No',
                    trader['recent_48h_trades'],
                    f"{trader['power_score']:.2f}",
                    'Yes' if trader['low_reliability'] else 'No'
                ])

            # Add top markets section
            writer.writerow([])
            writer.writerow(['TOP 3 MARKETS PER TRADER'])
            writer.writerow(['Trader Address', 'Top Markets (Title, Trade Count)'])

            for trader in sorted_traders:
                top_markets_str = '; '.join(
                    f"{m['title'][:40]} ({m['trade_count']} trades, {m['percentage']:.1f}%)"
                    for m in trader.get('top_markets', [])[:3]
                )
                writer.writerow([trader['trader_address'], top_markets_str])

        print(f"✅ Report saved to: {filename}")
        print(f"   Total traders: {len(sorted_traders)}")
        print(f"   Timestamp: {timestamp}\n")


def main():
    """Main entry point."""

    # Initialize analyzer
    analyzer = TradingBehaviorAnalyzer()

    # Check if database exists
    if not os.path.exists("polymarket_tracker.db"):
        print("❌ Error: polymarket_tracker.db not found")
        print("   Make sure the monitoring script has run and collected trades")
        return

    # Run analysis for different time periods
    print("\nSelect analysis period:")
    print("1. Last 7 days")
    print("2. Last 30 days")
    print("3. All time")
    print("4. All periods (sequential)")

    choice = input("\nEnter choice (1-4) [default: 3]: ").strip() or "3"

    if choice == "1":
        days_filter = 7
        metrics = analyzer.analyze_all_traders(days_filter)
        analyzer.generate_report(metrics, days_filter)
        analyzer.save_to_csv(metrics, f"trading_behavior_7days_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "2":
        days_filter = 30
        metrics = analyzer.analyze_all_traders(days_filter)
        analyzer.generate_report(metrics, days_filter)
        analyzer.save_to_csv(metrics, f"trading_behavior_30days_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "3":
        metrics = analyzer.analyze_all_traders(None)
        analyzer.generate_report(metrics, None)
        analyzer.save_to_csv(metrics, f"trading_behavior_alltime_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "4":
        # Run all periods
        for period, days in [("7 days", 7), ("30 days", 30), ("All time", None)]:
            metrics = analyzer.analyze_all_traders(days)
            analyzer.generate_report(metrics, days)
            suffix = f"{days}days" if days else "alltime"
            analyzer.save_to_csv(metrics, f"trading_behavior_{suffix}_{datetime.now().strftime('%Y%m%d')}.csv")
            print("\n" + "="*70 + "\n")

    else:
        print("Invalid choice, running all-time analysis...")
        metrics = analyzer.analyze_all_traders(None)
        analyzer.generate_report(metrics, None)
        analyzer.save_to_csv(metrics, f"trading_behavior_alltime_{datetime.now().strftime('%Y%m%d')}.csv")


if __name__ == "__main__":
    main()
