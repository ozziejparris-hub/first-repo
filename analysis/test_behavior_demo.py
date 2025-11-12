#!/usr/bin/env python3
"""
Demo/Test script for trading_behavior_analysis.py

Shows how behavior analysis calculations work with sample data.
"""

import statistics
from collections import Counter


def demo_betting_patterns():
    """Demonstrate betting pattern calculations."""
    print("="*70)
    print("BETTING PATTERNS CALCULATION DEMO")
    print("="*70 + "\n")

    # Sample trades
    trades = [
        {"shares": 100, "price": 0.65},  # $65
        {"shares": 150, "price": 0.70},  # $105
        {"shares": 120, "price": 0.60},  # $72
        {"shares": 200, "price": 0.55},  # $110
        {"shares": 80, "price": 0.80},   # $64
        {"shares": 110, "price": 0.75},  # $82.50
    ]

    print("Sample Trades:")
    bet_sizes = []
    for i, trade in enumerate(trades, 1):
        bet_size = trade['shares'] * trade['price']
        bet_sizes.append(bet_size)
        print(f"  Trade {i}: {trade['shares']} shares @ ${trade['price']:.2f} = ${bet_size:.2f}")

    print(f"\nCalculations:")
    avg_bet = statistics.mean(bet_sizes)
    median_bet = statistics.median(bet_sizes)
    min_bet = min(bet_sizes)
    max_bet = max(bet_sizes)
    std_dev = statistics.stdev(bet_sizes)
    total_volume = sum(bet_sizes)
    cv = (std_dev / avg_bet) * 100

    print(f"  Average bet size: ${avg_bet:.2f}")
    print(f"  Median bet size: ${median_bet:.2f}")
    print(f"  Min bet: ${min_bet:.2f}")
    print(f"  Max bet: ${max_bet:.2f}")
    print(f"  Standard deviation: ${std_dev:.2f}")
    print(f"  Total volume: ${total_volume:.2f}")
    print(f"  Coefficient of Variation: {cv:.2f}%")

    # Consistency classification
    if cv < 30:
        consistency = "Very Consistent"
    elif cv < 60:
        consistency = "Moderately Consistent"
    elif cv < 100:
        consistency = "Variable"
    else:
        consistency = "Highly Variable"

    print(f"  Consistency: {consistency}")
    print()


def demo_diversification():
    """Demonstrate diversification calculations."""
    print("="*70)
    print("MARKET DIVERSIFICATION CALCULATION DEMO")
    print("="*70 + "\n")

    # Sample trades across markets
    trades = [
        {"market_id": "market_1", "title": "Will Ukraine ceasefire happen?"},
        {"market_id": "market_1", "title": "Will Ukraine ceasefire happen?"},
        {"market_id": "market_2", "title": "Trump win 2024?"},
        {"market_id": "market_1", "title": "Will Ukraine ceasefire happen?"},
        {"market_id": "market_3", "title": "Gaza peace deal?"},
        {"market_id": "market_2", "title": "Trump win 2024?"},
        {"market_id": "market_4", "title": "Iran nuclear deal?"},
        {"market_id": "market_1", "title": "Will Ukraine ceasefire happen?"},
        {"market_id": "market_5", "title": "NATO expansion?"},
        {"market_id": "market_2", "title": "Trump win 2024?"},
    ]

    market_counts = Counter(t['market_id'] for t in trades)
    market_titles = {t['market_id']: t['title'] for t in trades}

    print(f"Total trades: {len(trades)}")
    print(f"\nMarket Distribution:")
    for market_id, count in market_counts.most_common():
        title = market_titles[market_id]
        percentage = (count / len(trades)) * 100
        print(f"  {title[:40]}: {count} trades ({percentage:.1f}%)")

    unique_markets = len(market_counts)
    diversification_score = (unique_markets / len(trades)) * 100

    print(f"\nCalculations:")
    print(f"  Unique markets: {unique_markets}")
    print(f"  Total trades: {len(trades)}")
    print(f"  Diversification score: {diversification_score:.1f}%")

    top_market_pct = market_counts.most_common(1)[0][1] / len(trades) * 100
    if top_market_pct > 50:
        concentration = "Highly Concentrated"
    elif top_market_pct > 30:
        concentration = "Moderately Concentrated"
    else:
        concentration = "Well Diversified"

    print(f"  Top market concentration: {top_market_pct:.1f}%")
    print(f"  Classification: {concentration}")
    print()


def demo_activity_frequency():
    """Demonstrate activity frequency calculations."""
    print("="*70)
    print("ACTIVITY FREQUENCY CALCULATION DEMO")
    print("="*70 + "\n")

    # Sample activity over 10 days
    from datetime import datetime, timedelta

    base_date = datetime(2025, 11, 1, 10, 0, 0)
    trades = [
        base_date,
        base_date + timedelta(hours=2),
        base_date + timedelta(days=1, hours=3),
        base_date + timedelta(days=1, hours=5),
        base_date + timedelta(days=2, hours=1),
        base_date + timedelta(days=5, hours=2),
        base_date + timedelta(days=5, hours=4),
        base_date + timedelta(days=5, hours=6),
        base_date + timedelta(days=8, hours=1),
        base_date + timedelta(days=9, hours=2),
    ]

    print("Sample Trade Timeline:")
    for i, ts in enumerate(trades, 1):
        print(f"  Trade {i}: {ts.strftime('%Y-%m-%d %H:%M')} ({ts.strftime('%A')})")

    first_trade = trades[0]
    last_trade = trades[-1]
    trading_period = (last_trade - first_trade).total_seconds() / 86400

    print(f"\nCalculations:")
    print(f"  First trade: {first_trade.strftime('%Y-%m-%d')}")
    print(f"  Last trade: {last_trade.strftime('%Y-%m-%d')}")
    print(f"  Trading period: {trading_period:.1f} days")
    print(f"  Total trades: {len(trades)}")
    print(f"  Trades per day: {len(trades) / trading_period:.2f}")
    print(f"  Trades per week: {(len(trades) / trading_period) * 7:.2f}")

    day_counts = Counter(ts.strftime('%A') for ts in trades)
    most_active_day = day_counts.most_common(1)[0][0]
    print(f"\nDay of week distribution:")
    for day, count in day_counts.most_common():
        print(f"  {day}: {count} trades")
    print(f"  Most active day: {most_active_day}")

    hour_counts = Counter(ts.hour for ts in trades)
    most_active_hour = hour_counts.most_common(1)[0][0]
    print(f"  Most active hour: {most_active_hour}:00")

    # Activity trend
    midpoint = len(trades) // 2
    first_half = trades[:midpoint]
    second_half = trades[midpoint:]

    first_period = (first_half[-1] - first_half[0]).total_seconds() / 86400 or 1
    second_period = (second_half[-1] - second_half[0]).total_seconds() / 86400 or 1

    first_rate = len(first_half) / first_period
    second_rate = len(second_half) / second_period

    print(f"\nActivity Trend:")
    print(f"  First half rate: {first_rate:.2f} trades/day")
    print(f"  Second half rate: {second_rate:.2f} trades/day")

    if second_rate > first_rate * 1.2:
        trend = "Increasing"
    elif second_rate < first_rate * 0.8:
        trend = "Decreasing"
    else:
        trend = "Stable"

    print(f"  Trend: {trend}")
    print()


def demo_style_classification():
    """Demonstrate trading style classification."""
    print("="*70)
    print("TRADING STYLE CLASSIFICATION DEMO")
    print("="*70 + "\n")

    # Sample trader profiles
    traders = [
        {
            "name": "Alice",
            "total_trades": 75,
            "avg_bet": 150,
            "diversification": 80,
            "trades_per_day": 6,
            "most_active_day": "Monday"
        },
        {
            "name": "Bob",
            "total_trades": 60,
            "avg_bet": 50,
            "diversification": 15,
            "trades_per_day": 4,
            "most_active_day": "Tuesday"
        },
        {
            "name": "Charlie",
            "total_trades": 15,
            "avg_bet": 250,
            "diversification": 40,
            "trades_per_day": 0.5,
            "most_active_day": "Friday"
        },
        {
            "name": "Diana",
            "total_trades": 90,
            "avg_bet": 10,
            "diversification": 75,
            "trades_per_day": 8,
            "most_active_day": "Wednesday"
        },
        {
            "name": "Eve",
            "total_trades": 25,
            "avg_bet": 40,
            "diversification": 55,
            "trades_per_day": 0.3,
            "most_active_day": "Saturday"
        },
    ]

    print("Trader Classifications:\n")

    for trader in traders:
        print(f"Trader: {trader['name']}")
        print(f"  Total trades: {trader['total_trades']}")
        print(f"  Avg bet size: ${trader['avg_bet']}")
        print(f"  Diversification: {trader['diversification']}%")
        print(f"  Trades per day: {trader['trades_per_day']}")
        print(f"  Most active: {trader['most_active_day']}")

        # Classification logic
        if trader['total_trades'] >= 50 and trader['trades_per_day'] >= 5 and trader['diversification'] >= 60:
            style = "Power User"
        elif trader['total_trades'] >= 50 and trader['diversification'] < 30:
            style = "High Volume Specialist"
        elif trader['avg_bet'] >= 100 and trader['total_trades'] < 20:
            style = "Big Better"
        elif trader['avg_bet'] < 20 and trader['total_trades'] >= 50 and trader['diversification'] >= 60:
            style = "Micro Trader"
        elif trader['most_active_day'] in ['Saturday', 'Sunday'] and trader['trades_per_day'] < 1:
            style = "Weekend Warrior"
        else:
            style = "General Trader"

        # Calculate power score
        power_score = (
            trader['trades_per_day'] *
            (trader['diversification'] / 10) *
            (trader['avg_bet'] / 10)
        )

        print(f"  → Style: {style}")
        print(f"  → Power Score: {power_score:.2f}")
        print()


def main():
    """Run all demos."""
    print("\n" + "="*70)
    print("TRADING BEHAVIOR ANALYSIS - CALCULATION DEMO")
    print("="*70 + "\n")

    print("This demo shows how behavior analysis calculations work.")
    print("No database required - just logic demonstration.\n")

    input("Press Enter to start demo...")

    demo_betting_patterns()
    input("Press Enter for next demo...")

    demo_diversification()
    input("Press Enter for next demo...")

    demo_activity_frequency()
    input("Press Enter for next demo...")

    demo_style_classification()

    print("="*70)
    print("✅ Demo complete!")
    print("\nWhen you run the actual analysis:")
    print("  python trading_behavior_analysis.py")
    print("\nIt will use these same calculations on real trade data")
    print("from polymarket_tracker.db")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
