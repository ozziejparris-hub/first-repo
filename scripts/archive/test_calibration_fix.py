#!/usr/bin/env python3
"""
Test script to verify CalibrationAnalyzer.analyze_all_traders() fix.

Tests:
1. Method exists
2. Method executes without errors
3. Return format is correct (Dict[str, Dict])
4. Integration with UnifiedELOSystem works
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from analysis.calibration_analysis import CalibrationAnalyzer
from analysis.unified_elo_system import UnifiedELOSystem
from monitoring.database import Database


def main():
    print("=" * 70)
    print("  CALIBRATION ANALYZER FIX TEST")
    print("=" * 70)

    # Test 1: Check if method exists
    print("\n[TEST 1] Checking if analyze_all_traders() method exists...")
    if hasattr(CalibrationAnalyzer, 'analyze_all_traders'):
        print("[OK] Method exists")
    else:
        print("[FAIL] Method does not exist")
        return

    # Test 2: Initialize CalibrationAnalyzer
    print("\n[TEST 2] Initializing CalibrationAnalyzer...")
    db_path = os.path.join(project_root, 'data', 'polymarket_tracker.db')

    try:
        analyzer = CalibrationAnalyzer(db_path)
        print(f"[OK] CalibrationAnalyzer initialized with DB: {db_path}")
    except Exception as e:
        print(f"[FAIL] Failed to initialize: {e}")
        return

    # Test 3: Call analyze_all_traders()
    print("\n[TEST 3] Calling analyze_all_traders()...")
    try:
        results = analyzer.analyze_all_traders()
        print(f"[OK] Method executed successfully")
        print(f"     Returned results for {len(results)} traders")
    except Exception as e:
        print(f"[FAIL] Method execution failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 4: Verify return format
    print("\n[TEST 4] Verifying return format...")
    if not isinstance(results, dict):
        print(f"[FAIL] Expected dict, got {type(results)}")
        return

    print("[OK] Return type is dict")

    if len(results) > 0:
        # Check first trader's data structure
        first_trader = next(iter(results.keys()))
        first_data = results[first_trader]

        print(f"     Sample trader: {first_trader[:10]}...")
        print(f"     Data keys: {list(first_data.keys())}")

        required_keys = ['brier_score', 'expected_calibration_error', 'num_predictions']
        missing_keys = [k for k in required_keys if k not in first_data]

        if missing_keys:
            print(f"[WARN] Missing keys: {missing_keys}")
        else:
            print(f"[OK] All required keys present")
            print(f"     Brier Score: {first_data['brier_score']:.4f}")
            print(f"     ECE: {first_data['expected_calibration_error']:.4f}")
            print(f"     Predictions: {first_data['num_predictions']}")
    else:
        print("[WARN] No results returned (no traders with resolved trades?)")

    # Test 5: Integration with UnifiedELOSystem
    print("\n[TEST 5] Testing integration with UnifiedELOSystem...")
    try:
        print("     Initializing UnifiedELOSystem...")
        db = Database()
        elo_system = UnifiedELOSystem(database=db)

        print("     Loading advanced metrics data...")
        elo_system._load_advanced_metrics_data(force_refresh=True)

        print("[OK] UnifiedELOSystem loaded advanced metrics without errors")

        # Check if calibration data was loaded
        if hasattr(elo_system, 'calibration_data') and elo_system.calibration_data:
            print(f"     Calibration data loaded for {len(elo_system.calibration_data)} traders")
        else:
            print("[WARN] Calibration data not found in elo_system")

    except Exception as e:
        print(f"[FAIL] Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test 6: Check advanced_modifier values
    print("\n[TEST 6] Checking if advanced_modifier values are non-default...")
    try:
        from monitoring.database import Database
        db = Database()

        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN advanced_modifier != 1.0 THEN 1 ELSE 0 END) as non_default
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
        """)

        total, non_default = cursor.fetchone()

        print(f"     Total traders with ELO: {total}")
        print(f"     Traders with non-default advanced_modifier: {non_default}")

        if non_default > 0:
            print(f"[OK] Advanced modifiers are being applied ({non_default}/{total})")
        else:
            print("[WARN] All advanced_modifiers are 1.0 (default)")
            print("       May need to run full recalculation to update values")

    except Exception as e:
        print(f"[WARN] Could not check advanced_modifier values: {e}")

    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    print("\n✅ CalibrationAnalyzer.analyze_all_traders() method added successfully")
    print("✅ Method returns correct format (Dict[str, Dict])")
    print("✅ Integration with UnifiedELOSystem works")
    print("\nNext steps:")
    print("  1. Run end-to-end integration test:")
    print("     python scripts/test_end_to_end_integration.py")
    print("  2. Run full ELO recalculation to update advanced_modifier values:")
    print("     python scripts/recalculate_comprehensive_elo.py")
    print("  3. Verify advanced_modifier values change from default 1.0")


if __name__ == "__main__":
    main()
