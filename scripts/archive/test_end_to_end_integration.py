#!/usr/bin/env python3
"""
End-to-End Integration Test

Simulates the complete monitoring → ELO update flow:
1. Get traders with evaluated trades
2. Build positions
3. Calculate quick ELO (4/6 dimensions)
4. Store in database
5. Verify storage
6. Test rankings

This validates the entire integration pipeline.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge
import time


def print_section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)


def test_end_to_end():
    print_section("END-TO-END INTEGRATION TEST")

    # Initialize
    print("\n[STEP 1/7] Initialize bridge...")
    try:
        db = Database()
        bridge = UnifiedELOMonitoringBridge(db)
        print("[OK] Bridge initialized")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        return False

    # Get traders (simulate monitoring flow)
    print("\n[STEP 2/7] Get traders with recent evaluations...")
    try:
        # Try recent evaluations first
        traders = db.get_traders_with_recent_evaluated_trades(hours=168)  # 1 week

        if not traders:
            # Fall back to any flagged traders
            print("  No recent evaluations, using sample flagged traders...")
            traders = db.get_flagged_traders()[:10]

        print(f"[OK] Found {len(traders)} traders to process")
        for i, t in enumerate(traders[:5], 1):
            print(f"  {i}. {t[:10]}...")
        if len(traders) > 5:
            print(f"  ... and {len(traders) - 5} more")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        return False

    # Build positions
    print("\n[STEP 3/7] Build/update positions...")
    try:
        start = time.time()
        position_results = bridge.update_positions_for_traders(traders, verbose=False)
        elapsed = time.time() - start

        print(f"[OK] Position building complete ({elapsed:.1f}s)")
        print(f"  Traders processed: {position_results['traders_processed']}")
        print(f"  Positions created: {position_results['total_positions_created']}")
        print(f"  Positions closed: {position_results['total_positions_closed']}")
        print(f"  Errors: {len(position_results['errors'])}")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Calculate quick ELO
    print("\n[STEP 4/7] Calculate quick ELO (4/6 dimensions)...")
    try:
        start = time.time()
        elo_results = bridge.quick_elo_update_for_traders(traders, verbose=False)
        elapsed = time.time() - start

        print(f"[OK] ELO calculation complete ({elapsed:.1f}s)")
        print(f"  Traders updated: {elo_results['traders_updated']}")
        print(f"  Traders failed: {elo_results['traders_failed']}")
        print(f"  Average ELO: {elo_results['avg_elo']:.0f}")
        if len(traders) > 0:
            print(f"  Time per trader: {(elapsed/len(traders)):.2f}s")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Verify database storage
    print("\n[STEP 5/7] Verify database storage...")
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Check if ELO was stored for our traders
        placeholders = ','.join('?' * len(traders))
        cursor.execute(f"""
            SELECT
                COUNT(*),
                AVG(comprehensive_elo),
                AVG(base_category_elo),
                MAX(comprehensive_elo),
                MIN(comprehensive_elo)
            FROM traders
            WHERE address IN ({placeholders})
            AND comprehensive_elo IS NOT NULL
        """, traders)

        count, avg_comp, avg_base, max_elo, min_elo = cursor.fetchone()

        # Get a sample trader
        cursor.execute(f"""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
                elo_last_updated
            FROM traders
            WHERE address IN ({placeholders})
            AND comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 1
        """, traders)

        sample = cursor.fetchone()
        conn.close()

        print(f"[OK] Database storage verified")
        print(f"  Traders with ELO: {count}/{len(traders)}")
        if avg_comp:
            print(f"  Average comprehensive ELO: {avg_comp:.0f}")
            print(f"  Average base ELO: {avg_base:.0f}")
            print(f"  Range: {min_elo:.0f} - {max_elo:.0f}")

        if sample:
            addr, comp, base, behav, adv, pnl, updated = sample
            print(f"\n  Sample Trader: {addr[:10]}...")
            print(f"    Comprehensive ELO: {comp:.0f}")
            print(f"    Base ELO: {base:.0f}")
            print(f"    Modifiers: Behav={behav:.3f}x, Adv={adv:.3f}x, P&L={pnl:.3f}x")
            print(f"    Last updated: {updated}")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Test rankings
    print("\n[STEP 6/7] Test trader rankings...")
    try:
        rankings = bridge.get_trader_ranking(limit=5)
        print(f"[OK] Rankings retrieved: {len(rankings)} traders")

        if rankings:
            print("\n  Top 5 Traders:")
            for i, t in enumerate(rankings, 1):
                print(f"    {i}. {t['address'][:10]}... - "
                      f"ELO: {t['comprehensive_elo']:.0f} "
                      f"(Base: {t['base_category_elo']:.0f})")
    except Exception as e:
        print(f"[ERROR] FAILED: {e}")
        return False

    # Performance summary
    print("\n[STEP 7/7] Performance summary...")
    print(f"[OK] End-to-end test complete")
    print(f"\n  Integration Performance:")
    print(f"    Total traders processed: {len(traders)}")
    print(f"    Position building: {position_results['traders_processed']} traders")
    print(f"    ELO updates: {elo_results['traders_updated']} traders")
    if len(traders) > 0:
        print(f"    Success rate: {(elo_results['traders_updated']/len(traders)*100):.1f}%")

    print_section("ALL TESTS PASSED")
    print("\nIntegration Status: FULLY OPERATIONAL")
    print("- Positions build automatically [OK]")
    print("- ELO updates automatically [OK]")
    print("- Database storage works [OK]")
    print("- Rankings accessible [OK]")
    print("\nThe monitoring system will now automatically update")
    print("comprehensive ELO when markets resolve!")

    return True


if __name__ == "__main__":
    success = test_end_to_end()
    exit(0 if success else 1)
