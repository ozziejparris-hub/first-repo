#!/usr/bin/env python3
"""
Integrate Behavioral ELO - Complete Integration Orchestrator

Orchestrates the complete behavioral ELO integration pipeline:
1. Update database schema
2. Calculate behavioral metrics (Kelly, patience, timing)
3. Calculate weighted metrics (market difficulty, confidence)
4. Calculate trader performance (ROI)
5. Run unified ELO with behavioral modifiers
6. Update database with results
7. Generate comprehensive report

This script ties together all phases of the simulation learnings integration.
"""

import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_section(title: str):
    """Print formatted section header."""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def update_database_schema(db_path: str) -> bool:
    """
    Phase 1: Update database schema with new columns.

    Returns:
        bool: True if successful
    """
    print_section("PHASE 1: Update Database Schema")

    from scripts.update_database_schema import update_schema

    try:
        return update_schema(db_path)
    except Exception as e:
        print(f"[ERROR] Schema update failed: {e}")
        return False


def calculate_behavioral_metrics(db_path: str) -> dict:
    """
    Phase 2: Calculate behavioral metrics (Kelly, patience, timing).

    Returns:
        dict: Trader behavioral metrics
    """
    print_section("PHASE 2: Calculate Behavioral Metrics")

    from analysis.trading_behavior_analysis import TradingBehaviorAnalyzer

    try:
        analyzer = TradingBehaviorAnalyzer(db_path=db_path)
        metrics = analyzer.analyze_all_traders(days_filter=None)

        # Save to CSV
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        csv_path = reports_dir / f"behavioral_metrics_{datetime.now().strftime('%Y%m%d')}.csv"
        analyzer.save_to_csv(metrics, str(csv_path))

        print(f"[OK] Analyzed {len(metrics)} traders")
        print(f"[OK] Saved to {csv_path}")

        return metrics
    except Exception as e:
        print(f"[ERROR] Behavioral analysis failed: {e}")
        return {}


def calculate_weighted_metrics(db_path: str) -> dict:
    """
    Phase 3: Calculate weighted metrics (market difficulty, confidence adjustment).

    Returns:
        dict: Trader weighted metrics
    """
    print_section("PHASE 3: Calculate Weighted Metrics")

    from analysis.calculate_weighted_metrics import WeightedMetricsCalculator

    try:
        calculator = WeightedMetricsCalculator(db_path=db_path)
        metrics = calculator.analyze_all_traders()

        # Save to CSV
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        csv_path = reports_dir / f"weighted_metrics_{datetime.now().strftime('%Y%m%d')}.csv"
        calculator.save_to_csv(metrics, str(csv_path))

        print(f"[OK] Analyzed {len(metrics)} traders")
        print(f"[OK] Saved to {csv_path}")

        return metrics
    except Exception as e:
        print(f"[ERROR] Weighted metrics calculation failed: {e}")
        return {}


def calculate_trader_performance(db_path: str) -> dict:
    """
    Phase 4: Calculate trader performance (ROI, win rate).

    Returns:
        dict: Trader performance metrics
    """
    print_section("PHASE 4: Calculate Trader Performance")

    from analysis.trader_performance_analysis import TraderPerformanceAnalyzer

    try:
        # Load API key if available
        api_key = None
        env_path = Path(__file__).parent.parent / '.env'
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    if line.startswith('POLYMARKET_API_KEY='):
                        api_key = line.strip().split('=', 1)[1].strip('"').strip("'")
                        break

        analyzer = TraderPerformanceAnalyzer(db_path=db_path, api_key=api_key)
        metrics = analyzer.analyze_trader_performance(days_filter=None)

        # Save to CSV
        reports_dir = Path(__file__).parent.parent / 'reports'
        reports_dir.mkdir(exist_ok=True)
        csv_path = reports_dir / f"trader_performance_{datetime.now().strftime('%Y%m%d')}.csv"
        analyzer.save_to_csv(metrics, str(csv_path))

        print(f"[OK] Analyzed {len(metrics)} traders")
        print(f"[OK] Saved to {csv_path}")

        return metrics
    except Exception as e:
        print(f"[ERROR] Performance analysis failed: {e}")
        return {}


def update_database_columns(db_path: str, behavioral_metrics: dict,
                            weighted_metrics: dict, performance_metrics: dict):
    """
    Phase 5: Update database with calculated metrics.

    Args:
        db_path: Path to database
        behavioral_metrics: Behavioral metrics dict
        weighted_metrics: Weighted metrics dict
        performance_metrics: Performance metrics dict
    """
    print_section("PHASE 5: Update Database Columns")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    updated_count = 0

    # Get all trader addresses
    all_traders = set(behavioral_metrics.keys()) | set(weighted_metrics.keys()) | set(performance_metrics.keys())

    print(f"Updating {len(all_traders)} traders...")

    for trader_address in all_traders:
        behavioral = behavioral_metrics.get(trader_address, {})
        weighted = weighted_metrics.get(trader_address, {})
        performance = performance_metrics.get(trader_address, {})

        # Extract values
        kelly_score = behavioral.get('kelly_alignment_score')
        patience_score = behavioral.get('patience_score')
        timing_score = behavioral.get('optimal_timing_score')
        weighted_wr = weighted.get('weighted_win_rate')
        roi_pct = performance.get('roi')
        resolved_count = weighted.get('resolved_trades_count') or performance.get('resolved_trades')

        # Update trader record
        cursor.execute("""
            UPDATE traders
            SET kelly_alignment_score = ?,
                patience_score = ?,
                timing_score = ?,
                weighted_win_rate = ?,
                roi_percentage = ?,
                resolved_trades_count = ?
            WHERE address = ?
        """, (
            kelly_score, patience_score, timing_score,
            weighted_wr, roi_pct, resolved_count,
            trader_address
        ))

        if cursor.rowcount > 0:
            updated_count += 1

    conn.commit()
    conn.close()

    print(f"[OK] Updated {updated_count} trader records")


def run_unified_elo_with_behavioral(db_path: str) -> bool:
    """
    Phase 6: Run unified ELO system with behavioral modifiers enabled.

    Returns:
        bool: True if successful
    """
    print_section("PHASE 6: Run Unified ELO with Behavioral Modifiers")

    from analysis.unified_elo_system import UnifiedELOSystem

    try:
        # Initialize system
        system = UnifiedELOSystem(db_path=db_path)

        # Calculate ELO ratings
        system.calculate_elo_ratings(verbose=True)

        # ELO ratings are already saved to database during calculate_elo_ratings()
        # Update traders table with comprehensive_elo column
        print("\nSaving ELO ratings to database...")

        conn = sqlite3.connect(system.db_path)
        cursor = conn.cursor()

        updated_count = 0
        for trader_address in system.elo_system.get_all_traders():
            # Get ELO with behavioral modifiers applied
            comprehensive_elo = system.get_trader_global_elo(
                trader_address,
                apply_behavioral=True,
                apply_advanced=False,  # Skip advanced since calibration may not be calculated yet
                apply_network=False,
                apply_contrarian=False,
                apply_pnl=False
            )

            base_elo = system.elo_system.get_overall_elo(trader_address)

            cursor.execute("""
                UPDATE traders
                SET comprehensive_elo = ?,
                    base_category_elo = ?,
                    behavioral_modifier = ?,
                    elo_last_updated = ?
                WHERE address = ?
            """, (
                comprehensive_elo,
                base_elo,
                comprehensive_elo / max(1, base_elo),  # Calculate multiplier
                datetime.now(),
                trader_address
            ))

            if cursor.rowcount > 0:
                updated_count += 1

        conn.commit()
        conn.close()

        print(f"[OK] Saved ELO ratings for {updated_count} traders to database")

        # Show top traders with behavioral adjustment
        print("\n" + "="*70)
        print("  TOP 10 TRADERS (WITH BEHAVIORAL MODIFIERS)")
        print("="*70)

        top_traders = system.get_top_traders(category=None, limit=10, min_resolved_trades=50)

        print(f"\n{'Rank':<6}{'Address':<20}{'ELO':<10}{'Resolved':<12}")
        print("-"*70)

        for i, trader in enumerate(top_traders, 1):
            addr_short = trader['address'][:18] + "..."
            print(f"{i:<6}{addr_short:<20}{trader['elo']:<10.0f}{trader['resolved_trades']:<12}")

        return True

    except Exception as e:
        print(f"[ERROR] Unified ELO calculation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_summary_report(db_path: str):
    """
    Phase 7: Generate summary report of integration results.
    """
    print_section("PHASE 7: Generate Summary Report")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count traders with new metrics
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(kelly_alignment_score) as with_kelly,
            COUNT(patience_score) as with_patience,
            COUNT(timing_score) as with_timing,
            COUNT(weighted_win_rate) as with_weighted_wr,
            COUNT(roi_percentage) as with_roi,
            COUNT(resolved_trades_count) as with_resolved_count,
            COUNT(CASE WHEN resolved_trades_count >= 50 THEN 1 END) as qualified
        FROM traders
    """)

    row = cursor.fetchone()

    print("[INTEGRATION SUMMARY]")
    print(f"  Total traders: {row[0]:,}")
    print(f"  With Kelly alignment score: {row[1]:,} ({row[1]/max(1,row[0])*100:.1f}%)")
    print(f"  With patience score: {row[2]:,} ({row[2]/max(1,row[0])*100:.1f}%)")
    print(f"  With timing score: {row[3]:,} ({row[3]/max(1,row[0])*100:.1f}%)")
    print(f"  With weighted win rate: {row[4]:,} ({row[4]/max(1,row[0])*100:.1f}%)")
    print(f"  With ROI percentage: {row[5]:,} ({row[5]/max(1,row[0])*100:.1f}%)")
    print(f"  With resolved trades count: {row[6]:,} ({row[6]/max(1,row[0])*100:.1f}%)")
    print(f"  Qualified (50 resolved): {row[7]:,} ({row[7]/max(1,row[0])*100:.1f}%)")

    # Average scores for qualified traders
    cursor.execute("""
        SELECT
            AVG(kelly_alignment_score),
            AVG(patience_score),
            AVG(timing_score),
            AVG(weighted_win_rate),
            AVG(roi_percentage),
            AVG(comprehensive_elo)
        FROM traders
        WHERE resolved_trades_count >= 50
        AND kelly_alignment_score IS NOT NULL
    """)

    row = cursor.fetchone()

    if row[0] is not None:
        print("\n[AVERAGE METRICS (Qualified Traders)]")
        print(f"  Kelly alignment: {row[0]:.3f}")
        print(f"  Patience score: {row[1]:.3f}")
        print(f"  Timing score: {row[2]:.3f}")
        print(f"  Weighted win rate: {row[3]:.2f}%")
        print(f"  ROI percentage: {row[4]:+.2f}%")
        print(f"  Average ELO: {row[5]:.0f}")

    conn.close()


def main():
    """Main orchestrator entry point."""

    print("\n" + "="*70)
    print("  BEHAVIORAL ELO INTEGRATION - COMPLETE PIPELINE")
    print("="*70)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    # Find database
    possible_paths = [
        Path('data/polymarket_tracker.db'),
        Path('monitoring/data/markets.db'),
        Path('polymarket_tracker.db')
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = str(path)
            break

    if not db_path:
        print("\n[ERROR] Database not found in any of:")
        for path in possible_paths:
            print(f"  - {path}")
        print("\nPlease ensure the database exists before running this script.")
        return

    print(f"\nUsing database: {db_path}")

    # Run pipeline
    try:
        # Phase 1: Update schema
        if not update_database_schema(db_path):
            print("[ERROR] Schema update failed. Aborting.")
            return

        # Phase 2: Behavioral metrics
        behavioral_metrics = calculate_behavioral_metrics(db_path)
        if not behavioral_metrics:
            print("[WARN] No behavioral metrics calculated, continuing...")

        # Phase 3: Weighted metrics
        weighted_metrics = calculate_weighted_metrics(db_path)
        if not weighted_metrics:
            print("[WARN] No weighted metrics calculated, continuing...")

        # Phase 4: Performance metrics
        performance_metrics = calculate_trader_performance(db_path)
        if not performance_metrics:
            print("[WARN] No performance metrics calculated, continuing...")

        # Phase 5: Update database
        if behavioral_metrics or weighted_metrics or performance_metrics:
            update_database_columns(db_path, behavioral_metrics,
                                   weighted_metrics, performance_metrics)

        # Phase 6: Unified ELO with behavioral modifiers
        if not run_unified_elo_with_behavioral(db_path):
            print("[ERROR] Unified ELO calculation failed. Aborting.")
            return

        # Phase 7: Summary report
        generate_summary_report(db_path)

        # Success
        print("\n" + "="*70)
        print("   BEHAVIORAL ELO INTEGRATION COMPLETE")
        print("="*70)
        print(f"  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)

        print("\nNext steps:")
        print("  1. Review reports in reports/ directory")
        print("  2. Run validation tests: py tests/test_behavioral_integration.py")
        print("  3. Check correlation improvement in unified ELO system")
        print()

    except Exception as e:
        print(f"\n[FATAL ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
