#!/usr/bin/env python3
"""
Quick ELO Integration Status Check

Displays current state of the ELO integration.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from monitoring.database import Database
from datetime import datetime, timedelta


def main():
    print("="*70)
    print("  ELO INTEGRATION STATUS")
    print("="*70)

    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()

    # Check database schema
    print("\n[DATABASE SCHEMA]")
    cursor.execute("PRAGMA table_info(traders)")
    columns = [col[1] for col in cursor.fetchall()]

    required = ['comprehensive_elo', 'base_category_elo', 'elo_last_updated',
                'behavioral_modifier', 'advanced_modifier', 'pnl_modifier']

    for col in required:
        status = "[OK]" if col in columns else "[ERROR]"
        print(f"  {status} {col}")

    # Check ELO coverage
    print("\n[ELO COVERAGE]")
    cursor.execute("SELECT COUNT(*) FROM traders WHERE is_flagged = 1")
    total_flagged = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM traders WHERE comprehensive_elo IS NOT NULL")
    with_elo = cursor.fetchone()[0]

    coverage = (with_elo / total_flagged * 100) if total_flagged > 0 else 0

    print(f"  Total flagged traders: {total_flagged}")
    print(f"  Traders with ELO: {with_elo}")
    print(f"  Coverage: {coverage:.1f}%")

    # Check recent updates
    print("\n[RECENT UPDATES]")
    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE elo_last_updated IS NOT NULL
        AND datetime(elo_last_updated) >= datetime('now', '-24 hours')
    """)
    updated_24h = cursor.fetchone()[0]

    cursor.execute("""
        SELECT MAX(elo_last_updated) FROM traders
        WHERE elo_last_updated IS NOT NULL
    """)
    last_update = cursor.fetchone()[0]

    print(f"  Updated in last 24 hours: {updated_24h}")
    print(f"  Most recent update: {last_update or 'Never'}")

    # Check ELO statistics
    print("\n[ELO STATISTICS]")
    cursor.execute("""
        SELECT
            AVG(comprehensive_elo),
            AVG(base_category_elo),
            MAX(comprehensive_elo),
            MIN(comprehensive_elo)
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
    """)
    result = cursor.fetchone()
    avg_comp, avg_base, max_elo, min_elo = result

    if avg_comp:
        print(f"  Average comprehensive ELO: {avg_comp:.0f}")
        print(f"  Average base ELO: {avg_base:.0f}")
        print(f"  Average multiplier: {(avg_comp/avg_base):.3f}x")
        print(f"  Range: {min_elo:.0f} - {max_elo:.0f}")
    else:
        print("  No ELO data yet")

    conn.close()

    # Overall status
    print("\n[OVERALL STATUS]")
    if all(col in columns for col in required):
        print("  [OK] Database schema: OK")
    else:
        print("  [ERROR] Database schema: INCOMPLETE")

    if coverage > 0:
        print(f"  [OK] ELO coverage: {coverage:.1f}%")
    else:
        print("  [WARN] ELO coverage: 0% (run recalculation)")

    if updated_24h > 0:
        print(f"  [OK] Recent activity: {updated_24h} updates in 24h")
    else:
        print("  [WARN] Recent activity: None (monitoring may be offline)")

    print("="*70)
    print("\nQuick Actions:")
    print("  - Run full recalc: python scripts/recalculate_comprehensive_elo.py")
    print("  - View rankings: python scripts/view_trader_rankings.py")
    print("  - Test integration: python scripts/test_end_to_end_integration.py")


if __name__ == "__main__":
    main()
