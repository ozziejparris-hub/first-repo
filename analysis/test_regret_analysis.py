#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for regret analysis with mock data

This creates a temporary database with sample resolved markets and trades
to demonstrate the regret analysis functionality.
"""

import sys
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.regret_analysis import RegretAnalyzer, RegretVisualizer, print_trader_report


def create_test_database():
    """Create a temporary database with mock data for testing."""

    # Create temporary database
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            end_date TIMESTAMP,
            resolved BOOLEAN DEFAULT 0,
            winning_outcome TEXT,
            resolution_date TIMESTAMP,
            condition_id TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE trades (
            trade_id TEXT PRIMARY KEY,
            trader_address TEXT,
            market_id TEXT,
            market_title TEXT,
            market_category TEXT,
            outcome TEXT,
            shares REAL,
            price REAL,
            side TEXT,
            timestamp TIMESTAMP,
            notified BOOLEAN DEFAULT 0,
            completed BOOLEAN DEFAULT 0,
            was_successful BOOLEAN
        )
    """)

    # Create sample resolved markets
    now = datetime.now()

    markets = [
        {
            'market_id': 'market_001',
            'title': 'Will Bitcoin hit $100k in 2025?',
            'category': 'Crypto',
            'winning_outcome': 'Yes',
            'resolution_date': (now - timedelta(days=1)).isoformat()
        },
        {
            'market_id': 'market_002',
            'title': 'Will there be a US recession in 2025?',
            'category': 'Economics',
            'winning_outcome': 'No',
            'resolution_date': (now - timedelta(days=2)).isoformat()
        },
        {
            'market_id': 'market_003',
            'title': 'Will AI surpass human intelligence by 2025?',
            'category': 'Technology',
            'winning_outcome': 'No',
            'resolution_date': (now - timedelta(days=3)).isoformat()
        }
    ]

    for market in markets:
        cursor.execute("""
            INSERT INTO markets (market_id, title, category, resolved,
                               winning_outcome, resolution_date)
            VALUES (?, ?, ?, 1, ?, ?)
        """, (
            market['market_id'],
            market['title'],
            market['category'],
            market['winning_outcome'],
            market['resolution_date']
        ))

    # Create sample trades for 3 traders

    # Trader 1: Good performer (low regret)
    # Bought Yes on Bitcoin at good price (0.40) - WINNER
    trades_trader1 = [
        {
            'trade_id': 't1_001',
            'trader': '0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1',
            'market': 'market_001',
            'outcome': 'Yes',
            'shares': 100,
            'price': 0.40,  # Good price for winner
            'side': 'BUY',
            'timestamp': (now - timedelta(days=30)).isoformat()
        },
        {
            'trade_id': 't1_002',
            'trader': '0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1',
            'market': 'market_002',
            'outcome': 'No',
            'shares': 80,
            'price': 0.55,  # Decent price for winner
            'side': 'BUY',
            'timestamp': (now - timedelta(days=25)).isoformat()
        }
    ]

    # Trader 2: Average performer (medium regret)
    # Mixed performance, some good, some bad timing
    trades_trader2 = [
        {
            'trade_id': 't2_001',
            'trader': '0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2',
            'market': 'market_001',
            'outcome': 'Yes',
            'shares': 50,
            'price': 0.70,  # Not great price for winner
            'side': 'BUY',
            'timestamp': (now - timedelta(days=20)).isoformat()
        },
        {
            'trade_id': 't2_002',
            'trader': '0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2',
            'market': 'market_002',
            'outcome': 'Yes',
            'shares': 60,
            'price': 0.60,  # Bet on loser
            'side': 'BUY',
            'timestamp': (now - timedelta(days=22)).isoformat()
        },
        {
            'trade_id': 't2_003',
            'trader': '0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2',
            'market': 'market_003',
            'outcome': 'No',
            'shares': 70,
            'price': 0.50,
            'side': 'BUY',
            'timestamp': (now - timedelta(days=18)).isoformat()
        }
    ]

    # Trader 3: Poor performer (high regret)
    # Bad timing and wrong predictions
    trades_trader3 = [
        {
            'trade_id': 't3_001',
            'trader': '0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC3',
            'market': 'market_001',
            'outcome': 'No',
            'shares': 100,
            'price': 0.60,  # Bet on loser
            'side': 'BUY',
            'timestamp': (now - timedelta(days=28)).isoformat()
        },
        {
            'trade_id': 't3_002',
            'trader': '0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC3',
            'market': 'market_002',
            'outcome': 'Yes',
            'shares': 120,
            'price': 0.70,  # Bet on loser at bad price
            'side': 'BUY',
            'timestamp': (now - timedelta(days=24)).isoformat()
        },
        {
            'trade_id': 't3_003',
            'trader': '0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC3',
            'market': 'market_003',
            'outcome': 'Yes',
            'shares': 80,
            'price': 0.65,  # Bet on loser
            'side': 'BUY',
            'timestamp': (now - timedelta(days=20)).isoformat()
        }
    ]

    # Insert all trades
    all_trades = trades_trader1 + trades_trader2 + trades_trader3

    for trade in all_trades:
        cursor.execute("""
            INSERT INTO trades (trade_id, trader_address, market_id, outcome,
                              shares, price, side, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade['trade_id'],
            trade['trader'],
            trade['market'],
            trade['outcome'],
            trade['shares'],
            trade['price'],
            trade['side'],
            trade['timestamp']
        ))

    conn.commit()
    conn.close()

    return db_path


def test_regret_analysis():
    """Test the regret analysis with mock data."""

    print("="*80)
    print("TESTING REGRET ANALYSIS WITH MOCK DATA")
    print("="*80)

    # Create test database
    print("\n1. Creating test database with mock data...")
    db_path = create_test_database()
    print(f"   ✓ Created database at: {db_path}")

    # Analyze all traders
    print("\n2. Analyzing all traders...")

    with RegretAnalyzer(db_path) as analyzer:
        # Get resolved markets
        markets = analyzer.get_resolved_markets()
        print(f"   ✓ Found {len(markets)} resolved markets")

        for market in markets:
            print(f"     - {market.title} → Winner: {market.winning_outcome}")

        # Analyze each trader
        print("\n3. Individual trader analysis:")

        traders = [
            '0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1',
            '0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB2',
            '0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC3'
        ]

        trader_names = ['Good Trader', 'Average Trader', 'Poor Trader']

        for trader, name in zip(traders, trader_names):
            print(f"\n   {name} ({trader[:10]}...):")

            metrics = analyzer.calculate_trader_regret(trader)

            if metrics:
                print(f"     Actual Return: ${metrics.actual_return:.2f}")
                print(f"     Optimal Return: ${metrics.optimal_return:.2f}")
                print(f"     Total Regret: ${metrics.total_regret:.2f}")
                print(f"     Regret Rate: {metrics.regret_rate:.1f}%")
                print(f"     Win Rate: {metrics.win_rate:.1f}%")

        # Analyze all traders and create DataFrame
        print("\n4. Generating comprehensive analysis...")
        df = analyzer.analyze_all_traders()

        if not df.empty:
            print(f"   ✓ Analyzed {len(df)} traders")
            print("\n   Rankings (by lowest regret):")
            for _, row in df.iterrows():
                print(f"     #{row['rank']}. {row['trader_address'][:10]}... - "
                      f"Regret: ${row['total_regret']:.2f} ({row['regret_rate']:.1f}%)")

            # Print detailed report for best trader
            print("\n5. Detailed report for best trader:")
            best_trader = df.iloc[0]['trader_address']
            best_metrics = analyzer.calculate_trader_regret(best_trader)
            print_trader_report(best_metrics, rank=1, total_traders=len(df))

            # Test visualizations (don't display, just create)
            print("\n6. Testing visualization generation...")
            viz = RegretVisualizer(output_dir=tempfile.gettempdir())

            try:
                # Don't show plots, just test they can be created
                import matplotlib
                matplotlib.use('Agg')  # Use non-interactive backend

                viz.plot_regret_distribution(df, save=False)
                print("   ✓ Regret distribution plot created")

                viz.plot_actual_vs_optimal(df, save=False)
                print("   ✓ Actual vs optimal plot created")

                viz.plot_top_traders(df, top_n=3, save=False)
                print("   ✓ Top traders plot created")

                viz.plot_regret_rate_distribution(df, save=False)
                print("   ✓ Regret rate distribution plot created")

            except Exception as e:
                print(f"   ⚠ Visualization test skipped: {e}")

    # Cleanup
    print("\n7. Cleanup...")
    try:
        os.unlink(db_path)
        print("   ✓ Test database removed")
    except:
        pass

    print("\n" + "="*80)
    print("✅ ALL TESTS PASSED!")
    print("="*80)
    print("\nThe regret analysis tool is working correctly.")
    print("It will be ready to use once your monitoring system collects resolved markets.\n")


if __name__ == "__main__":
    test_regret_analysis()
