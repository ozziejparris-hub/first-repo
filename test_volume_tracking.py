#!/usr/bin/env python3
"""
Test the complete flow with volume-based trader identification.
"""

import os
from dotenv import load_dotenv
from polymarket_client import PolymarketClient
from database import Database
from trader_analyzer import TraderAnalyzer

load_dotenv()


def test_volume_based_tracking():
    """Test the complete flow with volume + trade count criteria."""
    print("="*70)
    print("TESTING VOLUME-BASED TRADER TRACKING")
    print("="*70)

    api_key = os.getenv("POLYMARKET_API_KEY")
    if not api_key:
        print("❌ No API key found")
        return

    # Initialize components
    client = PolymarketClient(api_key)
    db = Database("test_tracker.db")
    analyzer = TraderAnalyzer(db, client, min_trades=20, min_volume=5000.0)

    print("\n📊 Step 1: Fetch geopolitics markets")
    print("-"*70)
    markets = client.get_markets(category="Geopolitics", limit=50)
    print(f"✅ Found {len(markets)} geopolitics markets")

    print("\n📊 Step 2: Extract active traders")
    print("-"*70)
    traders = client.get_active_traders_from_markets(markets)
    print(f"✅ Found {len(traders)} unique traders")

    if not traders:
        print("\n❌ No traders found! Check proxyWallet field extraction.")
        return

    print(f"\nSample trader addresses:")
    for i, trader in enumerate(list(traders)[:5], 1):
        print(f"  {i}. {trader}")

    print("\n📊 Step 3: Analyze trader performance")
    print("-"*70)

    # Test analyzing a few traders
    sample_traders = list(traders)[:3]

    for trader in sample_traders:
        print(f"\nTrader: {trader[:16]}...")
        stats = client.analyze_trader_performance(trader)

        print(f"  Total Trades: {stats['total_trades']}")
        print(f"  Total Volume: ${stats['total_volume']:.2f}")
        print(f"  Win Rate: {stats['win_rate']:.1f}% (placeholder)")

        # Check if would be flagged
        meets_criteria = (stats['total_trades'] >= 20 and
                         stats['total_volume'] >= 5000.0)

        if meets_criteria:
            print(f"  ✅ WOULD BE FLAGGED (meets criteria)")
        else:
            print(f"  ⚠️ Does not meet criteria yet")

    print("\n📊 Step 4: Run full trader analysis")
    print("-"*70)

    newly_flagged = analyzer.analyze_and_flag_traders(list(traders)[:10])

    print(f"\n✅ Analysis complete!")
    print(f"   Newly flagged: {newly_flagged} traders")

    # Show flagged traders
    flagged = db.get_all_flagged_traders_stats()

    if flagged:
        print(f"\n📋 Flagged Traders ({len(flagged)}):")
        for i, t in enumerate(flagged, 1):
            print(f"\n{i}. {t['address'][:16]}...")
            print(f"   Volume: ${t['total_volume']:.2f}")
            print(f"   Trades: {t['total_trades']}")
            print(f"   Win Rate: {t['win_rate']:.1f}% (placeholder)")
    else:
        print("\n⚠️ No traders flagged yet.")
        print("This means no traders met the criteria:")
        print("  - Minimum 20 trades")
        print("  - Minimum $5,000 volume")

    print("\n" + "="*70)
    print("✅ VOLUME-BASED TRACKING TEST COMPLETE")
    print("="*70)

    # Cleanup test database
    import os as os_module
    if os_module.path.exists("test_tracker.db"):
        os_module.remove("test_tracker.db")
        print("\n🧹 Cleaned up test database")


if __name__ == "__main__":
    test_volume_based_tracking()
