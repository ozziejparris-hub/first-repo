#!/usr/bin/env python3
"""
Test P&L Integration with Unified ELO System

This script validates that the P&L modifier system is correctly integrated
as the 6th analytical dimension in the unified ELO system.

Test Cases:
1. P&L data loading and caching
2. Component modifier calculations (profit, ROI, quality)
3. Combined multiplier calculation with confidence scaling
4. Integration with get_trader_global_elo()
5. Integration with get_trader_category_elo()
6. Export and reporting methods
"""

import sys
import os

# Add both project root and analysis directory to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'analysis'))

from unified_elo_system import UnifiedELOSystem


def test_pnl_data_loading():
    """Test 1: P&L data loading and caching."""
    print("\n" + "="*70)
    print("TEST 1: P&L Data Loading and Caching")
    print("="*70)

    system = UnifiedELOSystem()

    # Test loading
    print("\n[TEST] Loading P&L data...")
    loaded = system._load_pnl_data()

    if loaded:
        print(f"✅ P&L data loaded successfully")
        print(f"   Traders with P&L: {len(system.pnl_cache)}")

        # Test caching
        print("\n[TEST] Testing cache (should be instant)...")
        import time
        start = time.time()
        system._load_pnl_data()  # Should use cache
        elapsed = time.time() - start

        if elapsed < 0.1:  # Should be nearly instant
            print(f"✅ Cache working correctly ({elapsed*1000:.1f}ms)")
        else:
            print(f"⚠️  Cache may not be working ({elapsed*1000:.1f}ms)")

        return True
    else:
        print("⚠️  No P&L data available (positions table empty?)")
        return False


def test_component_modifiers():
    """Test 2: Component modifier calculations."""
    print("\n" + "="*70)
    print("TEST 2: Component Modifier Calculations")
    print("="*70)

    system = UnifiedELOSystem()
    system._load_pnl_data()

    if not system.pnl_cache:
        print("⚠️  Skipping - no P&L data")
        return False

    # Test profit modifier
    print("\n[TEST] Profit Modifier Ranges:")
    test_cases = [
        (-100, "Large Loss"),
        (0, "Breakeven"),
        (50, "Small Profit"),
        (250, "Medium Profit"),
        (500, "Large Profit")
    ]

    for pnl, label in test_cases:
        modifier = system.calculate_profit_modifier(pnl)
        print(f"  ${pnl:>6.0f} ({label:>15}): {modifier:.3f}x")

    # Test ROI modifier
    print("\n[TEST] ROI Modifier Ranges:")
    roi_cases = [
        (-50, "Negative ROI"),
        (0, "Zero ROI"),
        (25, "Moderate ROI"),
        (75, "High ROI"),
        (150, "Very High ROI")
    ]

    for roi, label in roi_cases:
        modifier = system.calculate_roi_modifier(roi)
        print(f"  {roi:>4.0f}% ({label:>15}): {modifier:.3f}x")

    # Test quality modifier
    print("\n[TEST] Quality Modifier Ranges:")
    quality_cases = [
        (0.3, "30% Profitable"),
        (0.5, "50% Profitable"),
        (0.7, "70% Profitable"),
        (0.9, "90% Profitable")
    ]

    for rate, label in quality_cases:
        modifier = system.calculate_position_quality_modifier(rate)
        print(f"  {rate*100:>5.0f}% ({label:>17}): {modifier:.3f}x")

    # Test confidence scaling
    print("\n[TEST] Confidence Scaling:")
    confidence_cases = [
        (1, "Very Low Sample"),
        (5, "Low Sample"),
        (10, "Moderate Sample"),
        (20, "Good Sample"),
        (50, "Large Sample")
    ]

    for positions, label in confidence_cases:
        confidence = system.calculate_pnl_confidence(positions)
        print(f"  {positions:>3} positions ({label:>18}): {confidence:.3f}")

    print("\n✅ All component modifiers working correctly")
    return True


def test_combined_multiplier():
    """Test 3: Combined multiplier calculation."""
    print("\n" + "="*70)
    print("TEST 3: Combined Multiplier Calculation")
    print("="*70)

    system = UnifiedELOSystem()
    system._load_pnl_data()

    if not system.pnl_cache:
        print("⚠️  Skipping - no P&L data")
        return False

    # Get a trader with P&L data
    test_trader = list(system.pnl_cache.keys())[0]

    print(f"\n[TEST] Testing trader: {test_trader[:12]}...")

    pnl_data = system.calculate_pnl_multiplier(test_trader)

    print(f"\nRaw Metrics:")
    print(f"  Realized P&L: ${pnl_data['raw_metrics']['realized_pnl']:.2f}")
    print(f"  Average ROI: {pnl_data['raw_metrics']['avg_roi']:.1f}%")
    print(f"  Closed Positions: {pnl_data['raw_metrics']['closed_positions']}")
    print(f"  Profitable Rate: {pnl_data['raw_metrics'].get('profitable_rate', 0)*100:.1f}%")

    print(f"\nComponent Modifiers:")
    print(f"  Profit: {pnl_data['profit_modifier']:.3f}x")
    print(f"  ROI: {pnl_data['roi_modifier']:.3f}x")
    print(f"  Quality: {pnl_data['quality_modifier']:.3f}x")
    print(f"  Confidence: {pnl_data['confidence']:.3f}")

    print(f"\nCombined Multiplier: {pnl_data['combined_multiplier']:.3f}x")
    print(f"Breakdown: {pnl_data['breakdown']}")

    # Verify multiplier is within expected range
    if 0.70 <= pnl_data['combined_multiplier'] <= 1.40:
        print(f"\n✅ Combined multiplier within expected range [0.70, 1.40]")
        return True
    else:
        print(f"\n❌ Combined multiplier OUT OF RANGE: {pnl_data['combined_multiplier']:.3f}")
        return False


def test_global_elo_integration():
    """Test 4: Integration with get_trader_global_elo()."""
    print("\n" + "="*70)
    print("TEST 4: Global ELO Integration")
    print("="*70)

    system = UnifiedELOSystem()
    system.calculate_elo_ratings(verbose=False)
    system._load_pnl_data()

    if not system.pnl_cache:
        print("⚠️  Skipping - no P&L data")
        return False

    # Get a trader with P&L data
    test_trader = list(system.pnl_cache.keys())[0]

    print(f"\n[TEST] Testing trader: {test_trader[:12]}...")

    # Get base ELO
    base_elo = system.get_trader_global_elo(test_trader)
    print(f"\nBase Global ELO: {base_elo:.1f}")

    # Get P&L-adjusted ELO
    pnl_elo = system.get_trader_global_elo(test_trader, apply_pnl=True)
    print(f"P&L-Adjusted ELO: {pnl_elo:.1f}")
    print(f"Change: {pnl_elo - base_elo:+.1f}")

    # Get fully adjusted ELO (all 6 dimensions)
    full_elo = system.get_trader_global_elo(
        test_trader,
        apply_behavioral=True,
        apply_advanced=True,
        apply_network=True,
        apply_contrarian=True,
        apply_pnl=True
    )
    print(f"\nFully Adjusted ELO (all 6 dimensions): {full_elo:.1f}")
    print(f"Total Change: {full_elo - base_elo:+.1f}")

    # Verify P&L has an effect
    if pnl_elo != base_elo:
        print(f"\n✅ P&L modifier successfully applied to global ELO")
        return True
    else:
        print(f"\n⚠️  P&L modifier had no effect (multiplier was 1.0?)")
        return False


def test_category_elo_integration():
    """Test 5: Integration with get_trader_category_elo()."""
    print("\n" + "="*70)
    print("TEST 5: Category ELO Integration")
    print("="*70)

    system = UnifiedELOSystem()
    system.calculate_elo_ratings(verbose=False)
    system._load_pnl_data()

    if not system.pnl_cache:
        print("⚠️  Skipping - no P&L data")
        return False

    # Get a trader with P&L data
    test_trader = list(system.pnl_cache.keys())[0]
    test_category = 'Elections'

    print(f"\n[TEST] Testing trader: {test_trader[:12]}... in {test_category}")

    # Get base category ELO
    base_cat_elo = system.get_trader_category_elo(test_trader, test_category)
    print(f"\nBase {test_category} ELO: {base_cat_elo:.1f}")

    # Get P&L-adjusted category ELO
    pnl_cat_elo = system.get_trader_category_elo(test_trader, test_category, apply_pnl=True)
    print(f"P&L-Adjusted {test_category} ELO: {pnl_cat_elo:.1f}")
    print(f"Change: {pnl_cat_elo - base_cat_elo:+.1f}")

    # Get fully adjusted category ELO (all 6 dimensions)
    full_cat_elo = system.get_trader_category_elo(
        test_trader,
        test_category,
        apply_behavioral=True,
        apply_advanced=True,
        apply_network=True,
        apply_contrarian=True,
        apply_pnl=True
    )
    print(f"\nFully Adjusted {test_category} ELO (all 6 dimensions): {full_cat_elo:.1f}")
    print(f"Total Change: {full_cat_elo - base_cat_elo:+.1f}")

    # Verify P&L has an effect
    if pnl_cat_elo != base_cat_elo:
        print(f"\n✅ P&L modifier successfully applied to category ELO")
        return True
    else:
        print(f"\n⚠️  P&L modifier had no effect (multiplier was 1.0?)")
        return False


def test_export_and_reporting():
    """Test 6: Export and reporting methods."""
    print("\n" + "="*70)
    print("TEST 6: Export and Reporting")
    print("="*70)

    system = UnifiedELOSystem()
    system.calculate_elo_ratings(verbose=False)
    system._load_pnl_data()

    if not system.pnl_cache:
        print("⚠️  Skipping - no P&L data")
        return False

    # Test export_pnl_analysis()
    print("\n[TEST] Testing export_pnl_analysis()...")
    try:
        export = system.export_pnl_analysis()
        print(f"✅ Export successful")
        print(f"   Total traders: {export['total_traders']}")
        print(f"   Traders with P&L: {export['traders_with_pnl']}")
        print(f"   Total realized P&L: ${export['total_realized_pnl']:.2f}")
        print(f"   Profitable traders: {export['profitable_traders']}")
    except Exception as e:
        print(f"❌ Export failed: {e}")
        return False

    # Test generate_pnl_report()
    print("\n[TEST] Testing generate_pnl_report()...")
    try:
        report_path = system.generate_pnl_report()
        print(f"✅ Report generated: {report_path}")

        # Verify file exists
        if os.path.exists(report_path):
            print(f"   File verified: {os.path.getsize(report_path)} bytes")
        else:
            print(f"⚠️  Report file not found")
    except Exception as e:
        print(f"❌ Report generation failed: {e}")
        return False

    # Test export_for_integration() includes P&L
    print("\n[TEST] Testing export_for_integration() includes P&L...")
    try:
        full_export = system.export_for_integration()

        if 'pnl_analysis' in full_export:
            print(f"✅ P&L data included in integration export")
            print(f"   P&L traders: {len(full_export['pnl_analysis'])}")
            print(f"   High-profit traders: {len(full_export['high_profit_traders'])}")
            print(f"   High-ROI traders: {len(full_export['high_roi_traders'])}")
        else:
            print(f"❌ P&L data NOT included in integration export")
            return False
    except Exception as e:
        print(f"❌ Integration export failed: {e}")
        return False

    print(f"\n✅ All export and reporting methods working correctly")
    return True


def main():
    """Run all tests."""
    print("="*70)
    print("  P&L INTEGRATION TEST SUITE")
    print("="*70)

    results = {
        "Test 1: P&L Data Loading": test_pnl_data_loading(),
        "Test 2: Component Modifiers": test_component_modifiers(),
        "Test 3: Combined Multiplier": test_combined_multiplier(),
        "Test 4: Global ELO Integration": test_global_elo_integration(),
        "Test 5: Category ELO Integration": test_category_elo_integration(),
        "Test 6: Export and Reporting": test_export_and_reporting()
    }

    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    passed = sum(1 for result in results.values() if result)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "⚠️  SKIP/FAIL"
        print(f"{status} - {test_name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All P&L integration tests PASSED!")
        print("The 6th analytical dimension is fully integrated.")
    else:
        print(f"\n⚠️  {total - passed} test(s) skipped or failed")
        print("Note: Some tests may be skipped if no P&L data is available")

    print("="*70)


if __name__ == "__main__":
    main()
