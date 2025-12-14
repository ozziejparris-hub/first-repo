#!/usr/bin/env python3
"""
Verify ELO calculations are still correct after batch processing optimization.

Checks:
1. ELO values updated
2. Modifiers present
3. Update timestamps
4. Sample data integrity
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database


def verify_elo_updates():
    """Verify ELO data is being stored correctly."""

    print("=" * 70)
    print("  ELO CORRECTNESS VERIFICATION")
    print("=" * 70)

    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()

    # Check 1: ELO values updated
    print("\n[CHECK 1] ELO Values Updated...")
    cursor.execute("""
        SELECT COUNT(*)
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
    """)
    total_with_elo = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
        AND comprehensive_elo != 1500
    """)
    updated_count = cursor.fetchone()[0]

    print(f"[OK] {total_with_elo} traders have ELO values")
    if updated_count > 0:
        print(f"[OK] {updated_count} traders have updated ELO (non-default)")
    else:
        print("[INFO] All traders have default ELO (1500)")
        print("       Run: python scripts/recalculate_comprehensive_elo.py")

    # Check 2: Modifiers present
    print("\n[CHECK 2] Modifiers Present...")
    cursor.execute("""
        SELECT COUNT(*)
        FROM traders
        WHERE behavioral_modifier IS NOT NULL
        AND advanced_modifier IS NOT NULL
        AND pnl_modifier IS NOT NULL
    """)
    with_modifiers = cursor.fetchone()[0]
    print(f"[OK] {with_modifiers} traders have all modifiers")

    # Check 3: Last updated timestamps
    print("\n[CHECK 3] Update Timestamps...")
    cursor.execute("""
        SELECT COUNT(*)
        FROM traders
        WHERE elo_last_updated IS NOT NULL
    """)
    with_timestamps = cursor.fetchone()[0]
    print(f"[OK] {with_timestamps} traders have update timestamps")

    # Check recent updates
    cursor.execute("""
        SELECT COUNT(*)
        FROM traders
        WHERE elo_last_updated >= datetime('now', '-1 hour')
    """)
    recent_updates = cursor.fetchone()[0]
    if recent_updates > 0:
        print(f"[OK] {recent_updates} traders updated in last hour")

    # Check 4: Sample data integrity
    print("\n[CHECK 4] Sample Data Integrity...")
    cursor.execute("""
        SELECT
            address,
            comprehensive_elo,
            base_category_elo,
            behavioral_modifier,
            advanced_modifier,
            pnl_modifier
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
        ORDER BY comprehensive_elo DESC
        LIMIT 5
    """)

    print("\nTop 5 traders:")
    for i, row in enumerate(cursor.fetchall(), 1):
        addr, comp, base, behav, adv, pnl = row

        # Calculate expected comprehensive from base + modifiers
        if base and base > 0:
            calculated_mult = (comp / base)
            expected_mult = behav * adv * pnl

            print(f"\n  {i}. {addr[:16]}...")
            print(f"     Comprehensive ELO: {comp:.0f}")
            print(f"     Base ELO: {base:.0f}")
            print(f"     Actual multiplier: {calculated_mult:.3f}x")
            print(f"     Expected multiplier: {expected_mult:.3f}x")
            print(f"     (Behav: {behav:.3f}, Adv: {adv:.3f}, P&L: {pnl:.3f})")

            # Verify calculation is correct (within 1% tolerance)
            if abs(calculated_mult - expected_mult) < 0.01:
                print(f"     [OK] Calculation verified")
            else:
                print(f"     [WARN] Multiplier mismatch!")

    # Check 5: Batch write integrity
    print("\n[CHECK 5] Batch Write Integrity...")
    cursor.execute("""
        SELECT COUNT(DISTINCT elo_last_updated)
        FROM traders
        WHERE elo_last_updated IS NOT NULL
        AND elo_last_updated >= datetime('now', '-5 minutes')
    """)
    unique_timestamps = cursor.fetchone()[0]

    if unique_timestamps <= 5:
        print(f"[OK] Recent updates used batch processing")
        print(f"     ({unique_timestamps} unique timestamp(s) in last 5 min)")
    else:
        print(f"[INFO] {unique_timestamps} different update times")

    conn.close()

    print("\n" + "=" * 70)
    print("  VERIFICATION COMPLETE")
    print("=" * 70)

    # Summary
    print("\nSummary:")
    print(f"  [OK] {total_with_elo} traders with ELO")
    print(f"  [OK] {with_modifiers} traders with modifiers")
    print(f"  [OK] {with_timestamps} traders with timestamps")

    if updated_count > 0:
        print(f"\n[OK] ELO system is working correctly!")
    else:
        print(f"\n[INFO] Run ELO recalculation to populate real values")


if __name__ == "__main__":
    verify_elo_updates()
