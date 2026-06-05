#!/usr/bin/env python3
"""
Pre-calculate Market Difficulties

Calculate difficulty scores for all markets and store in database.
Run this before ELO integration to speed up processing.

Usage:
    python scripts/precalculate_market_difficulties.py
"""

import sqlite3
import statistics
from pathlib import Path
from datetime import datetime


def calculate_market_difficulty(cursor, market_id: str) -> float:
    """
    Calculate difficulty score for a market.

    Uses 4 factors:
    1. Volatility (35%): Price range
    2. Liquidity (30%): Total volume
    3. Activity (20%): Number of trades
    4. Clarity (15%): Distance from 50% odds

    Returns:
        float: Difficulty score (0.0-1.0)
    """

    cursor.execute("""
        SELECT
            COUNT(DISTINCT t.trader_address) as num_traders,
            COUNT(t.trade_id) as num_trades,
            AVG(t.price) as avg_price,
            MIN(t.price) as min_price,
            MAX(t.price) as max_price,
            SUM(t.shares * t.price) as volume_usd
        FROM trades t
        WHERE t.market_id = ?
        GROUP BY t.market_id
    """, (market_id,))

    row = cursor.fetchone()

    if not row or row[1] == 0:
        return 0.5  # Default difficulty

    num_traders, num_trades, avg_price, min_price, max_price, volume = row

    # Factor 1: Volatility (35%)
    price_range = max_price - min_price
    volatility_score = min(price_range / 0.5, 1.0)

    # Factor 2: Liquidity (30%) - inverted (higher volume = easier)
    if volume >= 10000:
        liquidity_difficulty = 0.2
    elif volume >= 5000:
        liquidity_difficulty = 0.4
    elif volume >= 1000:
        liquidity_difficulty = 0.6
    elif volume >= 500:
        liquidity_difficulty = 0.8
    else:
        liquidity_difficulty = 1.0

    # Factor 3: Activity (20%) - more trades = easier (better price discovery)
    if num_trades >= 100:
        activity_difficulty = 0.2
    elif num_trades >= 50:
        activity_difficulty = 0.4
    elif num_trades >= 20:
        activity_difficulty = 0.6
    elif num_trades >= 10:
        activity_difficulty = 0.8
    else:
        activity_difficulty = 1.0

    # Factor 4: Clarity (15%) - close to 50% = harder (uncertain outcome)
    distance_from_50 = abs(avg_price - 0.5)
    clarity_difficulty = 1.0 - (distance_from_50 * 2)

    # Weighted combination
    difficulty = (
        volatility_score * 0.35 +
        liquidity_difficulty * 0.30 +
        activity_difficulty * 0.20 +
        clarity_difficulty * 0.15
    )

    return min(max(difficulty, 0.0), 1.0)


def main():
    """Pre-calculate and cache market difficulties."""

    db_path = Path('data/polymarket_tracker.db')

    if not db_path.exists():
        print("[X] Database not found at data/polymarket_tracker.db")
        return

    print("\n" + "="*70)
    print("  PRE-CALCULATING MARKET DIFFICULTIES")
    print("="*70)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

    # Open database in read-write mode
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get all markets with trades
    print("[1/3] Finding markets with trade data...")
    cursor.execute("""
        SELECT DISTINCT market_id
        FROM trades
        WHERE market_id IS NOT NULL
    """)

    market_ids = [row[0] for row in cursor.fetchall()]

    print(f"   Found {len(market_ids):,} markets to analyze\n")

    # Calculate difficulties
    print("[2/3] Calculating difficulty scores...")
    updated = 0
    skipped = 0
    difficulties = []

    for i, market_id in enumerate(market_ids, 1):
        if i % 1000 == 0 or i == len(market_ids):
            print(f"   Progress: {i:,}/{len(market_ids):,} markets ({i/len(market_ids)*100:.1f}%)", end='\r')

        difficulty = calculate_market_difficulty(cursor, market_id)
        difficulties.append(difficulty)

        # Update market difficulty in database
        cursor.execute("""
            UPDATE markets
            SET difficulty_score = ?
            WHERE market_id = ?
        """, (difficulty, market_id))

        if cursor.rowcount > 0:
            updated += 1
        else:
            skipped += 1

        # Commit every 1000 markets
        if i % 1000 == 0:
            conn.commit()

    print(f"   Progress: {len(market_ids):,}/{len(market_ids):,} markets (100.0%)")

    # Final commit
    conn.commit()

    # Verify results
    print("\n[3/3] Verifying difficulty scores...")
    cursor.execute("""
        SELECT COUNT(*)
        FROM markets
        WHERE difficulty_score IS NOT NULL
    """)

    verified_count = cursor.fetchone()[0]

    conn.close()

    # Summary
    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)
    print(f"   Markets analyzed: {len(market_ids):,}")
    print(f"   Markets updated: {updated:,}")
    print(f"   Markets skipped: {skipped:,} (not in markets table)")
    print(f"   Verified in DB: {verified_count:,}")
    print()
    print(f"   Average difficulty: {statistics.mean(difficulties):.3f}")
    print(f"   Min difficulty: {min(difficulties):.3f}")
    print(f"   Max difficulty: {max(difficulties):.3f}")
    print(f"   Std dev: {statistics.stdev(difficulties):.3f}")
    print("="*70)
    print()
    print("[OK] Market difficulties cached in database")
    print("[OK] Integration will be 5-10x faster!")
    print()
    print("Next steps:")
    print("  1. Run ELO integration: py scripts/integrate_behavioral_elo.py")
    print("  2. After monitoring runs, re-run this script to update difficulties")
    print()


if __name__ == '__main__':
    main()
