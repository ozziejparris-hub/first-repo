#!/usr/bin/env python3
"""
P&L Data Validation Script

Checks if monitoring system has populated P&L data in database.
Reports coverage statistics and data quality.

Usage:
    python scripts/validate_pnl_data.py
"""

import sqlite3
import os
from datetime import datetime


def validate_pnl_data(db_path: str = None):
    """
    Validate P&L data quality in database.

    Checks:
    1. Coverage: How many traders have P&L data
    2. Data quality: Are values realistic
    3. Distribution: Profitability breakdown
    """
    if db_path is None:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')

    if not os.path.exists(db_path):
        print(f"[X] Error: Database not found at {db_path}")
        return False

    print("="*70)
    print("P&L DATA VALIDATION REPORT")
    print(f"Database: {db_path}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Coverage Analysis
    print("[COVERAGE] P&L Data Population")
    print("-"*70)

    cursor.execute("SELECT COUNT(*) FROM traders WHERE total_trades >= 10")
    total_traders = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE total_trades >= 10
        AND total_pnl IS NOT NULL
        AND total_pnl != 0
    """)
    traders_with_pnl = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE total_trades >= 10
        AND total_invested IS NOT NULL
        AND total_invested > 0
    """)
    traders_with_investment = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE total_trades >= 10
        AND closed_positions IS NOT NULL
        AND closed_positions > 0
    """)
    traders_with_closed_pos = cursor.fetchone()[0]

    coverage_pct = (traders_with_pnl / total_traders * 100) if total_traders > 0 else 0

    print(f"  Total traders (10+ trades): {total_traders:,}")
    print(f"  Traders with P&L data: {traders_with_pnl:,} ({coverage_pct:.1f}%)")
    print(f"  Traders with investment data: {traders_with_investment:,}")
    print(f"  Traders with closed positions: {traders_with_closed_pos:,}")
    print()

    # 2. Data Quality Analysis
    print("[QUALITY] P&L Data Quality")
    print("-"*70)

    if traders_with_pnl == 0:
        print("  [!] WARNING: No P&L data found")
        print("  [!] Monitoring system has not populated position tracking data yet")
        print()
        print("  To populate P&L data:")
        print("    1. Run monitoring system: python -m monitoring.main")
        print("    2. Wait for markets to resolve")
        print("    3. Position tracker will update P&L columns")
        print()
        conn.close()
        return False

    # Get P&L statistics
    cursor.execute("""
        SELECT
            AVG(total_pnl) as avg_pnl,
            MIN(total_pnl) as min_pnl,
            MAX(total_pnl) as max_pnl,
            AVG(avg_roi) as avg_roi,
            MIN(avg_roi) as min_roi,
            MAX(avg_roi) as max_roi,
            AVG(closed_positions) as avg_closed
        FROM traders
        WHERE total_trades >= 10
        AND total_pnl IS NOT NULL
        AND total_pnl != 0
    """)

    stats = cursor.fetchone()
    avg_pnl, min_pnl, max_pnl, avg_roi, min_roi, max_roi, avg_closed = stats

    print(f"  Average P&L: ${avg_pnl:,.2f}")
    print(f"  P&L range: ${min_pnl:,.2f} to ${max_pnl:,.2f}")
    print(f"  Average ROI: {avg_roi:.2f}%")
    print(f"  ROI range: {min_roi:.2f}% to {max_roi:.2f}%")
    print(f"  Average closed positions: {avg_closed:.1f}")
    print()

    # 3. Profitability Distribution
    print("[DISTRIBUTION] Profitability Breakdown")
    print("-"*70)

    cursor.execute("""
        SELECT
            COUNT(CASE WHEN total_pnl > 100 THEN 1 END) as highly_profitable,
            COUNT(CASE WHEN total_pnl > 0 AND total_pnl <= 100 THEN 1 END) as profitable,
            COUNT(CASE WHEN total_pnl = 0 THEN 1 END) as breakeven,
            COUNT(CASE WHEN total_pnl < 0 AND total_pnl >= -100 THEN 1 END) as small_loss,
            COUNT(CASE WHEN total_pnl < -100 THEN 1 END) as large_loss
        FROM traders
        WHERE total_trades >= 10
        AND total_pnl IS NOT NULL
    """)

    dist = cursor.fetchone()
    highly_profitable, profitable, breakeven, small_loss, large_loss = dist
    total = sum(dist)

    if total > 0:
        print(f"  Highly Profitable (>$100): {highly_profitable:,} ({highly_profitable/total*100:.1f}%)")
        print(f"  Profitable ($0-$100): {profitable:,} ({profitable/total*100:.1f}%)")
        print(f"  Breakeven ($0): {breakeven:,} ({breakeven/total*100:.1f}%)")
        print(f"  Small Loss ($0 to -$100): {small_loss:,} ({small_loss/total*100:.1f}%)")
        print(f"  Large Loss (<-$100): {large_loss:,} ({large_loss/total*100:.1f}%)")
    print()

    # 4. ROI Distribution
    print("[ROI] Return Distribution")
    print("-"*70)

    cursor.execute("""
        SELECT
            COUNT(CASE WHEN avg_roi > 50 THEN 1 END) as exceptional,
            COUNT(CASE WHEN avg_roi > 30 AND avg_roi <= 50 THEN 1 END) as elite,
            COUNT(CASE WHEN avg_roi > 20 AND avg_roi <= 30 THEN 1 END) as strong,
            COUNT(CASE WHEN avg_roi > 10 AND avg_roi <= 20 THEN 1 END) as above_avg,
            COUNT(CASE WHEN avg_roi > 0 AND avg_roi <= 10 THEN 1 END) as positive,
            COUNT(CASE WHEN avg_roi = 0 THEN 1 END) as zero,
            COUNT(CASE WHEN avg_roi < 0 THEN 1 END) as negative
        FROM traders
        WHERE total_trades >= 10
        AND avg_roi IS NOT NULL
    """)

    roi_dist = cursor.fetchone()
    exceptional, elite, strong, above_avg, positive, zero, negative = roi_dist
    total_roi = sum(roi_dist)

    if total_roi > 0:
        print(f"  Exceptional (>50% ROI): {exceptional:,} ({exceptional/total_roi*100:.1f}%)")
        print(f"  Elite (30-50% ROI): {elite:,} ({elite/total_roi*100:.1f}%)")
        print(f"  Strong (20-30% ROI): {strong:,} ({strong/total_roi*100:.1f}%)")
        print(f"  Above Avg (10-20% ROI): {above_avg:,} ({above_avg/total_roi*100:.1f}%)")
        print(f"  Positive (0-10% ROI): {positive:,} ({positive/total_roi*100:.1f}%)")
        print(f"  Zero (0% ROI): {zero:,} ({zero/total_roi*100:.1f}%)")
        print(f"  Negative (<0% ROI): {negative:,} ({negative/total_roi*100:.1f}%)")
    print()

    # 5. Sample Size Analysis
    print("[SAMPLES] Closed Position Distribution")
    print("-"*70)

    cursor.execute("""
        SELECT
            COUNT(CASE WHEN closed_positions >= 50 THEN 1 END) as very_high_conf,
            COUNT(CASE WHEN closed_positions >= 30 AND closed_positions < 50 THEN 1 END) as high_conf,
            COUNT(CASE WHEN closed_positions >= 20 AND closed_positions < 30 THEN 1 END) as medium_conf,
            COUNT(CASE WHEN closed_positions >= 10 AND closed_positions < 20 THEN 1 END) as low_conf,
            COUNT(CASE WHEN closed_positions > 0 AND closed_positions < 10 THEN 1 END) as very_low_conf
        FROM traders
        WHERE total_trades >= 10
        AND closed_positions IS NOT NULL
    """)

    sample_dist = cursor.fetchone()
    very_high, high, medium, low, very_low = sample_dist
    total_samples = sum(sample_dist)

    if total_samples > 0:
        print(f"  Very High Confidence (50+ closed): {very_high:,} ({very_high/total_samples*100:.1f}%)")
        print(f"  High Confidence (30-49 closed): {high:,} ({high/total_samples*100:.1f}%)")
        print(f"  Medium Confidence (20-29 closed): {medium:,} ({medium/total_samples*100:.1f}%)")
        print(f"  Low Confidence (10-19 closed): {low:,} ({low/total_samples*100:.1f}%)")
        print(f"  Very Low Confidence (1-9 closed): {very_low:,} ({very_low/total_samples*100:.1f}%)")
    print()

    conn.close()

    # 6. Summary and Recommendations
    print("="*70)
    print("[SUMMARY] Validation Results")
    print("="*70)

    if coverage_pct >= 80:
        print("  [OK] Excellent P&L data coverage (80%+)")
        print("  [OK] ELO system will have strong ROI modifiers")
    elif coverage_pct >= 50:
        print("  [OK] Good P&L data coverage (50-80%)")
        print("  [OK] ELO system will benefit from ROI modifiers")
    elif coverage_pct >= 20:
        print("  [!] Moderate P&L data coverage (20-50%)")
        print("  [!] Some traders will have neutral ROI modifiers")
    elif coverage_pct > 0:
        print("  [!] Low P&L data coverage (<20%)")
        print("  [!] Most traders will have neutral ROI modifiers")
        print("  [!] Consider running monitoring system longer")
    else:
        print("  [X] No P&L data found")
        print("  [X] ROI modifiers will be neutral for all traders")
        print("  [X] Run monitoring system to populate data")

    print()

    if traders_with_pnl > 0:
        print("Recommendations:")
        print("  1. P&L data is ready for ELO integration")
        print("  2. Run: python scripts/integrate_behavioral_elo.py")
        print("  3. Monitor P&L population as monitoring runs")
    else:
        print("Next Steps:")
        print("  1. Start monitoring: python -m monitoring.main")
        print("  2. Wait for markets to resolve")
        print("  3. Re-run this validation script")
        print("  4. When coverage >20%, run ELO integration")

    print()
    print("="*70)

    return traders_with_pnl > 0


if __name__ == "__main__":
    validate_pnl_data()
