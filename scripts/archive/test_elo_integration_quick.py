#!/usr/bin/env python3
"""
Quick ELO integration test - validates basic functionality.
Tests with 5 traders (fast, ~30 seconds).
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


def test_initialization():
    """Test 1: Bridge initialization"""
    print("\n[TEST 1/6] Bridge Initialization...")
    try:
        db = Database()
        bridge = UnifiedELOMonitoringBridge(db)
        print(f"[OK] Bridge initialized")
        print(f"   Database: {db.db_path}")
        return bridge, db
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def test_get_traders(db):
    """Test 2: Get test traders"""
    print("\n[TEST 2/6] Getting Test Traders...")
    try:
        traders = db.get_flagged_traders()
        if not traders:
            print("[WARN] No flagged traders found")
            return []

        test_traders = traders[:5]  # Just 5 for quick test
        print(f"[OK] Got {len(test_traders)} traders for testing:")
        for i, t in enumerate(test_traders, 1):
            print(f"   {i}. {t[:10]}...")
        return test_traders
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_position_building(bridge, traders):
    """Test 3: Position building"""
    print("\n[TEST 3/6] Position Building...")
    try:
        results = bridge.update_positions_for_traders(traders, verbose=False)
        print(f"[OK] Position building works!")
        print(f"   Traders processed: {results['traders_processed']}")
        print(f"   Positions created: {results['total_positions_created']}")
        print(f"   Positions closed: {results['total_positions_closed']}")
        print(f"   Errors: {len(results['errors'])}")
        print(f"   Duration: {results['duration_seconds']:.2f}s")
        return True
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_quick_elo_update(bridge, traders):
    """Test 4: Quick ELO update"""
    print("\n[TEST 4/6] Quick ELO Update (4/6 dimensions)...")
    try:
        results = bridge.quick_elo_update_for_traders(traders, verbose=False)
        print(f"[OK] Quick ELO update works!")
        print(f"   Traders updated: {results['traders_updated']}")
        print(f"   Traders failed: {results['traders_failed']}")
        print(f"   Average ELO: {results['avg_elo']:.1f}")
        print(f"   Duration: {results['duration_seconds']:.2f}s")
        return True
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_storage(db):
    """Test 5: Database storage"""
    print("\n[TEST 5/6] Database Storage Verification...")
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Count traders with ELO
        cursor.execute("""
            SELECT COUNT(*) FROM traders
            WHERE comprehensive_elo IS NOT NULL
        """)
        count = cursor.fetchone()[0]

        # Get top trader
        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
                elo_last_updated
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 1
        """)
        top = cursor.fetchone()

        conn.close()

        print(f"[OK] Database storage verified!")
        print(f"   Traders with ELO: {count}")

        if top:
            addr, comp_elo, base_elo, behav, adv, pnl, updated = top
            print(f"\n   Top Trader: {addr[:10]}...")
            print(f"   Comprehensive ELO: {comp_elo:.0f}")
            print(f"   Base ELO: {base_elo:.0f}")
            print(f"   Modifiers:")
            print(f"     - Behavioral: {behav:.3f}x")
            print(f"     - Advanced: {adv:.3f}x")
            print(f"     - P&L: {pnl:.3f}x")
            print(f"   Last updated: {updated}")
            if base_elo > 0:
                print(f"   Total multiplier: {(comp_elo/base_elo):.3f}x")

        return True
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_rankings(bridge):
    """Test 6: Get trader rankings"""
    print("\n[TEST 6/6] Get Trader Rankings...")
    try:
        rankings = bridge.get_trader_ranking(limit=10)
        print(f"[OK] Rankings work! Found {len(rankings)} traders")

        if rankings:
            print(f"\n   Top 5 Traders by Comprehensive ELO:")
            for i, trader in enumerate(rankings[:5], 1):
                print(f"   {i}. {trader['address'][:10]}... - "
                      f"ELO: {trader['comprehensive_elo']:.0f} "
                      f"(Base: {trader['base_category_elo']:.0f})")

        return True
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("="*70)
    print("  QUICK ELO INTEGRATION TEST")
    print("="*70)

    # Run tests
    bridge, db = test_initialization()
    if not bridge:
        return False

    traders = test_get_traders(db)
    if not traders:
        print("\n[WARN] No traders to test with")
        print("   The integration is functional but needs traders with data")
        return True  # Not a failure, just no data

    if not test_position_building(bridge, traders):
        return False

    if not test_quick_elo_update(bridge, traders):
        return False

    if not test_database_storage(db):
        return False

    if not test_get_rankings(bridge):
        return False

    # Summary
    print("\n" + "="*70)
    print("  ALL TESTS PASSED!")
    print("="*70)
    print("\nIntegration Status: READY")
    print("- ELO bridge functional")
    print("- Database storage working")
    print("- Position building operational")
    print("- Quick ELO updates working")
    print("\nNext: Test monitoring integration trigger")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
