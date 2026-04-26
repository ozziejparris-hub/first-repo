#!/usr/bin/env python3
"""
Daily Comprehensive ELO Recalculation (All 6 Dimensions)

Runs a complete ELO recalculation including expensive analyses:
- Network analysis (correlation matrix)
- Contrarian analysis (consensus divergence)
- Plus all 4 quick dimensions

Schedule via cron:
0 2 * * * cd /path/to/project && python scripts/recalculate_comprehensive_elo.py >> logs/elo_recalc.log 2>&1

Or run manually:
python scripts/recalculate_comprehensive_elo.py
"""

import sys
import os
import argparse

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge
from datetime import datetime
import time


def parse_args():
    parser = argparse.ArgumentParser(
        description="Full 6-dimensional ELO recalculation for all traders."
    )
    parser.add_argument(
        '--skip-correlation',
        action='store_true',
        help=(
            'Skip correlation matrix calculation (use cached/neutral scores). '
            'Reduces runtime from 5+ hours to ~15 minutes. '
            'Use when running during active monitoring hours.'
        )
    )
    parser.add_argument(
        '--skip-contrarian',
        action='store_true',
        help=(
            'Skip contrarian analysis (bypasses internal ELO recalculation + market '
            'resolution pass). Uses neutral modifiers instead. '
            'Use alongside --skip-correlation for fastest runtime (~15 minutes).'
        )
    )
    return parser.parse_args()


def print_banner(text):
    """Print formatted banner."""
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)


def main():
    args = parse_args()

    print_banner("COMPREHENSIVE ELO RECALCULATION")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    start_time = time.time()

    # Initialize
    print("\n[INIT] Initializing ELO bridge...")
    try:
        db = Database()
        bridge = UnifiedELOMonitoringBridge(db)
        print("[OK] Bridge initialized")
    except Exception as e:
        print(f"[ERROR] FAILED to initialize: {e}")
        return 1

    # Get current statistics
    print("\n[STATS] Current database state...")
    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
        total_flagged = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM traders WHERE comprehensive_elo IS NOT NULL")
        traders_with_elo = cursor.fetchone()[0]

        cursor.execute("""
            SELECT AVG(comprehensive_elo)
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
        """)
        avg_elo_before = cursor.fetchone()[0] or 0

        conn.close()

        print(f"  Total flagged traders: {total_flagged}")
        print(f"  Traders with ELO: {traders_with_elo}")
        print(f"  Average ELO (before): {avg_elo_before:.0f}")
    except Exception as e:
        print(f"[WARN] Could not get stats: {e}")

    # Run full recalculation
    print_banner("RUNNING FULL RECALCULATION (6/6 Dimensions)")
    print("\nThis includes:")
    print("  1. Base category ELO (resolution-based)")
    print("  2. Behavioral modifiers (consistency, diversity)")
    print("  3. Advanced metrics (calibration, risk, regret)")
    if args.skip_correlation:
        print("  4. Network analysis (correlation, copy-trade) [SKIPPED]")
    else:
        print("  4. Network analysis (correlation, copy-trade) [EXPENSIVE]")
    if args.skip_contrarian:
        print("  5. Contrarian analysis (anti-consensus) [SKIPPED]")
    else:
        print("  5. Contrarian analysis (anti-consensus) [EXPENSIVE]")
    print("  6. P&L modifiers (profit, ROI, quality)")
    if args.skip_correlation:
        print("\n[CORRELATION] --skip-correlation active: correlation matrix bypassed.")
        print("[CORRELATION] Using cached results if available, neutral scores otherwise.")
    if args.skip_contrarian:
        print("[CONTRARIAN] --skip-contrarian active: contrarian analysis bypassed.")
        print("[CONTRARIAN] Using neutral modifiers instead.")
    if not args.skip_correlation and not args.skip_contrarian:
        print("\nThis may take 5-15 minutes for large datasets...")
    print()

    try:
        results = bridge.full_elo_recalculation(
            verbose=True,
            force_refresh=True,  # Force refresh all caches
            skip_correlation=args.skip_correlation,
            skip_contrarian=args.skip_contrarian
        )

        elapsed = time.time() - start_time

        print_banner("RECALCULATION COMPLETE")
        print(f"  Traders updated: {results['traders_updated']}")
        print(f"  Traders failed: {results['traders_failed']}")
        print(f"  Average comprehensive ELO: {results['avg_elo']:.1f}")
        print(f"  Total time: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")

        # Show top 10
        if results['top_traders']:
            print("\n  Top 10 Traders by Comprehensive ELO:")
            for i, trader in enumerate(results['top_traders'][:10], 1):
                comp_elo = trader['comprehensive_elo']
                base_elo = trader['base_category_elo']
                multiplier = comp_elo / base_elo if base_elo > 0 else 1.0
                print(f"    {i:2d}. {trader['address'][:10]}... - "
                      f"ELO: {comp_elo:6.0f} "
                      f"(Base: {base_elo:6.0f}, "
                      f"Multiplier: {multiplier:.3f}x)")

        # Show statistics after
        if results['traders_updated'] > 0:
            print("\n  Performance Metrics:")
            print(f"    Average time per trader: {(elapsed/results['traders_updated']):.2f}s")
            print(f"    Throughput: {(results['traders_updated']/elapsed*60):.1f} traders/minute")

        print_banner("SUCCESS")
        print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\nNext steps:")
        print("  - View rankings: python scripts/view_trader_rankings.py")
        print("  - Check status: python scripts/check_elo_status.py")
        print("  - Schedule daily: Add to cron (see script header)")

        return 0

    except Exception as e:
        print_banner("FAILED")
        print(f"[ERROR] Error during recalculation: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)
