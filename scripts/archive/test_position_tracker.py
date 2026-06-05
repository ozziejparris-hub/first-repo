#!/usr/bin/env python3
"""
Test if position tracker works and diagnose why ROI is still zero.
"""

import sys
from pathlib import Path
import sqlite3

sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    print("\n" + "="*70)
    print("  POSITION TRACKER DIAGNOSTIC")
    print("="*70 + "\n")

    db_path = 'data/polymarket_tracker.db'

    if not Path(db_path).exists():
        print("[ERROR] ERROR: Database not found!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Check if positions table exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='positions'
    """)

    positions_table_exists = cursor.fetchone() is not None

    print(f"1. Positions table exists: {'YES [OK]' if positions_table_exists else 'NO [ERROR]'}")

    if positions_table_exists:
        # 2. Check position count
        cursor.execute("SELECT COUNT(*) FROM positions")
        total_positions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM positions WHERE status='closed'")
        closed_positions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM positions WHERE status='open'")
        open_positions = cursor.fetchone()[0]

        print(f"   Total positions: {total_positions:,}")
        print(f"   Closed: {closed_positions:,}")
        print(f"   Open: {open_positions:,}\n")

        if total_positions == 0:
            print("[WARN]  WARNING: Zero positions tracked!")
            print("   Position tracker is NOT running or not integrated.\n")
    else:
        print("   [ERROR] Position tracking table does not exist!")
        print("   Position tracker has never been initialized.\n")

    # 3. Check for resolved markets
    cursor.execute("""
        SELECT COUNT(*) FROM markets
        WHERE resolved = 1
        AND winning_outcome IS NOT NULL
    """)
    resolved_count = cursor.fetchone()[0]

    print(f"2. Resolved markets in database: {resolved_count:,}")

    if resolved_count == 0:
        print("   [WARN]  WARNING: No resolved markets!")
        print("   Position tracker needs resolved markets to calculate P&L.\n")
    else:
        print(f"   [OK] {resolved_count} resolved markets available for P&L calculation\n")

    # 4. Check traders with P&L data
    cursor.execute("""
        SELECT COUNT(*) FROM traders
        WHERE realized_pnl IS NOT NULL
        AND ABS(realized_pnl) > 0.01
    """)
    traders_with_pnl = cursor.fetchone()[0]

    print(f"3. Traders with P&L data: {traders_with_pnl:,}")

    if traders_with_pnl == 0:
        print("   [ERROR] PROBLEM CONFIRMED: Zero traders have P&L data\n")

        print("[DIAG] Likely causes:")
        if not positions_table_exists:
            print("   -> Position tracker never initialized (table doesn't exist)")
        elif total_positions == 0:
            print("   -> Position tracker not running in main monitoring loop")
        elif resolved_count == 0:
            print("   -> No resolved markets (need time for markets to resolve)")
        else:
            print("   -> Position closing logic has a bug")
            print("   -> P&L calculation failing silently")
    else:
        print(f"   [OK] {traders_with_pnl} traders have P&L data\n")

    # 5. Check if position_tracker.py exists
    position_tracker_file = Path('monitoring/position_tracker.py')
    print(f"4. Position tracker file exists: {'YES [OK]' if position_tracker_file.exists() else 'NO [ERROR]'}")

    if not position_tracker_file.exists():
        print("   [ERROR] position_tracker.py is missing!")
        print("   File needs to be created.\n")
    else:
        print("   File location: monitoring/position_tracker.py\n")

    # 6. Check monitor.py for position tracker integration
    main_file = Path('monitoring/monitor.py')
    if main_file.exists():
        main_content = main_file.read_text(encoding='utf-8')

        has_import = 'position_tracker' in main_content.lower() or 'PositionTracker' in main_content
        has_instantiation = 'PositionTracker(' in main_content
        has_update_call = 'update_position_tracking' in main_content or 'match_trades_for_trader' in main_content

        print(f"5. Main monitoring loop integration:")
        print(f"   Position tracker imported: {'YES [OK]' if has_import else 'NO [ERROR]'}")
        print(f"   Position tracker instantiated: {'YES [OK]' if has_instantiation else 'NO [ERROR]'}")
        print(f"   Position updates called: {'YES [OK]' if has_update_call else 'NO [ERROR]'}\n")

        if not (has_import and has_instantiation and has_update_call):
            print("   [WARN]  Position tracker NOT FULLY INTEGRATED!")
            print("   This is why ROI is still zero.\n")
        else:
            print("   [OK] Position tracker is fully integrated!\n")
    else:
        print("5. Main monitoring file not found\n")

    # 7. Sample some trades to check data flow
    cursor.execute("SELECT COUNT(*) FROM trades")
    total_trades = cursor.fetchone()[0]

    print(f"6. Total trades in database: {total_trades:,}")

    if total_trades > 0:
        cursor.execute("""
            SELECT COUNT(DISTINCT trader_address) FROM trades
        """)
        unique_traders = cursor.fetchone()[0]
        print(f"   Unique traders: {unique_traders:,}")
        print(f"   [OK] Trades are being recorded\n")
    else:
        print("   [WARN]  No trades recorded - monitoring may not be running\n")

    conn.close()

    print("="*70)
    print("  DIAGNOSTIC SUMMARY")
    print("="*70 + "\n")

    if not positions_table_exists:
        print("[CRITICAL] ROOT CAUSE: Position tracking never initialized")
        print("\nFIX: Create positions table and implement position tracker")
    elif total_positions == 0 and total_trades > 0 and not (has_import and has_instantiation and has_update_call):
        print("[CRITICAL] ROOT CAUSE: Position tracker not integrated in monitoring loop")
        print("\nFIX: Add position tracker calls to monitoring/monitor.py")
    elif total_positions == 0 and total_trades > 0 and (has_import and has_instantiation and has_update_call):
        print("[CRITICAL] ROOT CAUSE: Position tracker integrated BUT never run")
        print("\nFIX: Restart monitoring system to start P&L tracking")
        print("     Command: py -m monitoring.main")
    elif resolved_count == 0:
        print("[PARTIAL] PARTIAL ISSUE: No resolved markets yet")
        print("\nACTION: Wait for markets to resolve, or check resolution detection")
    elif traders_with_pnl == 0 and closed_positions > 0:
        print("[CRITICAL] ROOT CAUSE: P&L calculation logic broken")
        print("\nFIX: Debug P&L calculation in position_tracker.py")
    elif traders_with_pnl > 0:
        print("[SUCCESS] SYSTEM WORKING: P&L data exists!")
        print(f"\nRe-run ROI validation: py scripts/validate_roi_rebalancing.py")

    print("\n" + "="*70 + "\n")

if __name__ == '__main__':
    main()
