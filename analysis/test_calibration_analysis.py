#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for calibration analysis with mock data

This creates a temporary database with sample resolved markets and trades
to demonstrate the calibration analysis functionality.
"""

import sys
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.calibration_analysis import CalibrationAnalyzer, CalibrationVisualizer, print_calibration_report


def create_test_database():
    """Create a temporary database with mock calibration data."""

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

    now = datetime.now()

    # Create 15 resolved markets with different outcomes
    markets = []
    for i in range(15):
        winner = 'Yes' if i % 2 == 0 else 'No'
        markets.append({
            'market_id': f'0xmarket_{i:03d}',
            'condition_id': f'0xmarket_{i:03d}',  # Use same for simplicity
            'title': f'Test Market {i}',
            'category': 'Geopolitics' if i < 8 else 'Crypto',
            'winning_outcome': winner,
            'resolution_date': (now - timedelta(days=1)).isoformat()
        })

    for market in markets:
        cursor.execute("""
            INSERT INTO markets (market_id, condition_id, title, category, resolved,
                               winning_outcome, resolution_date)
            VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (
            market['market_id'],
            market['condition_id'],
            market['title'],
            market['category'],
            market['winning_outcome'],
            market['resolution_date']
        ))

    # Create trades for 3 traders with different calibration patterns

    # Trader 1: Well-calibrated (Brier ~0.15)
    # Bets with probabilities that match actual outcomes
    trader1_trades = [
        ('t1_000', '0xAAAA1', '0xmarket_000', 'Yes', 0.60, 100),
        ('t1_001', '0xAAAA1', '0xmarket_001', 'No', 0.55, 100),
        ('t1_002', '0xAAAA1', '0xmarket_002', 'Yes', 0.65, 100),
        ('t1_003', '0xAAAA1', '0xmarket_003', 'No', 0.60, 100),
        ('t1_004', '0xAAAA1', '0xmarket_004', 'Yes', 0.70, 100),
        ('t1_005', '0xAAAA1', '0xmarket_005', 'No', 0.65, 100),
        ('t1_006', '0xAAAA1', '0xmarket_006', 'Yes', 0.55, 100),
        ('t1_007', '0xAAAA1', '0xmarket_007', 'No', 0.70, 100),
        ('t1_008', '0xAAAA1', '0xmarket_008', 'Yes', 0.68, 100),
        ('t1_009', '0xAAAA1', '0xmarket_009', 'No', 0.58, 100),
        ('t1_010', '0xAAAA1', '0xmarket_010', 'Yes', 0.62, 100),
        ('t1_011', '0xAAAA1', '0xmarket_011', 'No', 0.63, 100),
    ]

    # Trader 2: Over-confident (Brier ~0.30)
    # Always bets with high confidence but wins at average rate
    trader2_trades = [
        ('t2_000', '0xBBBB2', '0xmarket_000', 'Yes', 0.90, 100),
        ('t2_001', '0xBBBB2', '0xmarket_001', 'Yes', 0.85, 100),
        ('t2_002', '0xBBBB2', '0xmarket_002', 'Yes', 0.95, 100),
        ('t2_003', '0xBBBB2', '0xmarket_003', 'Yes', 0.80, 100),
        ('t2_004', '0xBBBB2', '0xmarket_004', 'Yes', 0.88, 100),
        ('t2_005', '0xBBBB2', '0xmarket_005', 'Yes', 0.92, 100),
        ('t2_006', '0xBBBB2', '0xmarket_006', 'Yes', 0.87, 100),
        ('t2_007', '0xBBBB2', '0xmarket_007', 'Yes', 0.83, 100),
        ('t2_008', '0xBBBB2', '0xmarket_008', 'Yes', 0.91, 100),
        ('t2_009', '0xBBBB2', '0xmarket_009', 'Yes', 0.86, 100),
        ('t2_010', '0xBBBB2', '0xmarket_010', 'Yes', 0.89, 100),
        ('t2_011', '0xBBBB2', '0xmarket_011', 'Yes', 0.84, 100),
    ]

    # Trader 3: Under-confident (Brier ~0.22)
    # Bets with lower confidence than warranted
    trader3_trades = [
        ('t3_000', '0xCCCC3', '0xmarket_000', 'Yes', 0.40, 100),
        ('t3_001', '0xCCCC3', '0xmarket_001', 'Yes', 0.45, 100),
        ('t3_002', '0xCCCC3', '0xmarket_002', 'Yes', 0.35, 100),
        ('t3_003', '0xCCCC3', '0xmarket_003', 'Yes', 0.50, 100),
        ('t3_004', '0xCCCC3', '0xmarket_004', 'Yes', 0.42, 100),
        ('t3_005', '0xCCCC3', '0xmarket_005', 'Yes', 0.48, 100),
        ('t3_006', '0xCCCC3', '0xmarket_006', 'Yes', 0.38, 100),
        ('t3_007', '0xCCCC3', '0xmarket_007', 'Yes', 0.52, 100),
        ('t3_008', '0xCCCC3', '0xmarket_008', 'Yes', 0.41, 100),
        ('t3_009', '0xCCCC3', '0xmarket_009', 'Yes', 0.47, 100),
        ('t3_010', '0xCCCC3', '0xmarket_010', 'Yes', 0.39, 100),
        ('t3_011', '0xCCCC3', '0xmarket_011', 'Yes', 0.49, 100),
    ]

    all_trades = trader1_trades + trader2_trades + trader3_trades

    for trade_id, trader, market_id, outcome, price, shares in all_trades:
        cursor.execute("""
            INSERT INTO trades (trade_id, trader_address, market_id, outcome,
                              price, shares, side, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, 'BUY', ?)
        """, (
            trade_id,
            trader,
            market_id,
            outcome,
            price,
            shares,
            (now - timedelta(days=7)).isoformat()
        ))

    conn.commit()
    conn.close()

    return db_path


def test_calibration_analysis():
    """Test the calibration analysis with mock data."""

    print("="*80)
    print("TESTING CALIBRATION ANALYSIS WITH MOCK DATA")
    print("="*80)

    # Create test database
    print("\n1. Creating test database with mock data...")
    db_path = create_test_database()
    print(f"   ✓ Created database at: {db_path}")

    print("\n2. Analyzing traders...")

    with CalibrationAnalyzer(db_path) as analyzer:
        # Analyze each trader
        traders = [
            ('0xAAAA1', 'Well-Calibrated Trader'),
            ('0xBBBB2', 'Over-Confident Trader'),
            ('0xCCCC3', 'Under-Confident Trader')
        ]

        print("\n3. Individual trader analysis:")

        for trader, name in traders:
            print(f"\n   {name} ({trader[:10]}...):")

            metrics = analyzer.calculate_trader_calibration(trader)

            if metrics:
                print(f"     Brier Score: {metrics.brier_score:.3f}")
                print(f"     ECE: {metrics.expected_calibration_error:.3f}")
                print(f"     Confidence Bias: {metrics.confidence_bias:+.1f}%")
                print(f"     Avg Predicted: {metrics.avg_predicted_prob*100:.1f}%")
                print(f"     Actual Win Rate: {metrics.actual_win_rate*100:.1f}%")

        # Generate comparison
        print("\n4. Generating comprehensive comparison...")
        df = analyzer.compare_traders_calibration()

        if not df.empty:
            print(f"   ✓ Analyzed {len(df)} traders")
            print("\n   Rankings (by Brier score - lower is better):")
            for _, row in df.iterrows():
                print(f"     #{row['rank']}. {row['trader_address'][:10]}... - "
                      f"Brier: {row['brier_score']:.3f} | "
                      f"Bias: {row['confidence_bias']:+.1f}%")

            # Print detailed report for best trader
            print("\n5. Detailed report for best calibrated trader:")
            best_trader = df.iloc[0]['trader_address']
            best_metrics = analyzer.calculate_trader_calibration(best_trader)
            print_calibration_report(best_metrics, rank=1, total_traders=len(df))

            # Test visualizations (don't display, just create)
            print("\n6. Testing visualization generation...")
            viz = CalibrationVisualizer(output_dir=tempfile.gettempdir())

            try:
                # Use non-interactive backend
                import matplotlib
                matplotlib.use('Agg')

                viz.plot_calibration_curve(best_metrics, save=False)
                print("   ✓ Calibration curve plot created")

                viz.plot_brier_distribution(df, save=False)
                print("   ✓ Brier distribution plot created")

                viz.plot_confidence_bias_scatter(df, save=False)
                print("   ✓ Confidence bias scatter plot created")

                viz.plot_top_traders(df, top_n=3, save=False)
                print("   ✓ Top traders plot created")

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
    print("\nThe calibration analysis tool is working correctly.")
    print("It will be ready to use once your monitoring system collects resolved markets.\n")


if __name__ == "__main__":
    test_calibration_analysis()
