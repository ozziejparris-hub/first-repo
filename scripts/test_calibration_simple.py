#!/usr/bin/env python3
"""
Simple test for CalibrationAnalyzer.analyze_all_traders() method.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

print("=" * 70)
print("  CALIBRATION ANALYZER - SIMPLE TEST")
print("=" * 70)

# Test 1: Import
print("\n[TEST 1] Importing CalibrationAnalyzer...")
try:
    from analysis.calibration_analysis import CalibrationAnalyzer
    print("[OK] Import successful")
except Exception as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)

# Test 2: Check method exists
print("\n[TEST 2] Checking if analyze_all_traders() method exists...")
if hasattr(CalibrationAnalyzer, 'analyze_all_traders'):
    print("[OK] Method exists")
else:
    print("[FAIL] Method does not exist")
    sys.exit(1)

# Test 3: Initialize analyzer
print("\n[TEST 3] Initializing CalibrationAnalyzer...")
db_path = os.path.join(project_root, 'data', 'polymarket_tracker.db')

try:
    analyzer = CalibrationAnalyzer(db_path)
    print(f"[OK] Initialized with DB: {db_path}")
except Exception as e:
    print(f"[FAIL] Initialization failed: {e}")
    sys.exit(1)

# Test 4: Call method
print("\n[TEST 4] Calling analyze_all_traders()...")
try:
    results = analyzer.analyze_all_traders()
    print(f"[OK] Method executed successfully")
    print(f"     Returned {len(results)} traders")

    if len(results) > 0:
        first_trader = next(iter(results.keys()))
        first_data = results[first_trader]
        print(f"\n     Sample trader: {first_trader[:16]}...")
        print(f"     Brier Score: {first_data.get('brier_score', 'N/A')}")
        print(f"     ECE: {first_data.get('expected_calibration_error', 'N/A')}")
        print(f"     Predictions: {first_data.get('num_predictions', 'N/A')}")

except Exception as e:
    print(f"[FAIL] Method execution failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("  SUCCESS - Method is working!")
print("=" * 70)
print("\nThe analyze_all_traders() method has been successfully added.")
print("You can now run the full end-to-end test again.")
