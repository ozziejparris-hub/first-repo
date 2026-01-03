#!/usr/bin/env python3
"""
Convenience script to run Polymarket analysis tools.

Provides a menu to select which analysis to run.
"""

import sys
import os

# Add analysis directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'analysis'))


def main():
    print("="*70)
    print("  🎯 Polymarket Analysis Tools")
    print("="*70)
    print()
    print("Select analysis to run:")
    print()
    print("1. Trader Performance Analysis")
    print("   Analyzes win rates and ROI based on resolved markets")
    print("   Requires: Markets that have resolved")
    print()
    print("2. Trading Behavior Analysis")
    print("   Analyzes betting patterns, diversification, and activity")
    print("   Requires: Trade history data")
    print()
    print("3. Weighted Consensus System")
    print("   ELO ratings + weighted majority algorithm for market predictions")
    print("   Requires: Resolved markets for ELO calculation")
    print()
    print("4. Trader Specialization Analysis")
    print("   Category-specific ELO + specialist identification + context-aware predictions")
    print("   Requires: Resolved markets across multiple categories")
    print()
    print("5. Market Confidence Meter")
    print("   Integration tool - combines all analyses into confidence scores (0-100)")
    print("   Requires: All previous analyses to have run")
    print()
    print("6. Consensus Divergence Detector ⭐ NEW")
    print("   Identifies profitable disagreement opportunities and contrarian traders")
    print("   Requires: Resolved markets for contrarian analysis")
    print()
    print("7. Test Analysis Demo")
    print("   Demo of performance analysis calculations (no database)")
    print()
    print("8. Test Behavior Demo")
    print("   Demo of behavior analysis calculations (no database)")
    print()
    print("9. Test Market Filtering")
    print("   Test crypto/sports market exclusion logic")
    print()
    print("10. Exit")
    print()

    choice = input("Enter choice (1-10): ").strip()

    if choice == "1":
        print("\nRunning Trader Performance Analysis...")
        from trader_performance_analysis import main as perf_main
        perf_main()

    elif choice == "2":
        print("\nRunning Trading Behavior Analysis...")
        from trading_behavior_analysis import main as behavior_main
        behavior_main()

    elif choice == "3":
        print("\nRunning Weighted Consensus System...")
        from weighted_consensus_system import main as consensus_main
        consensus_main()

    elif choice == "4":
        print("\nRunning Trader Specialization Analysis...")
        from trader_specialization_analysis import main as spec_main
        spec_main()

    elif choice == "5":
        print("\nRunning Market Confidence Meter...")
        from market_confidence_meter import main as confidence_main
        confidence_main()

    elif choice == "6":
        print("\nRunning Consensus Divergence Detector...")
        from consensus_divergence_detector import main as divergence_main
        divergence_main()

    elif choice == "7":
        print("\nRunning Performance Analysis Demo...")
        from test_analysis_demo import main as demo_main
        demo_main()

    elif choice == "8":
        print("\nRunning Behavior Analysis Demo...")
        from test_behavior_demo import main as behavior_demo_main
        behavior_demo_main()

    elif choice == "9":
        print("\nRunning Market Filtering Test...")
        from test_market_filtering import test_market_exclusion
        test_market_exclusion()

    elif choice == "10":
        print("Goodbye!")
        return

    else:
        print("Invalid choice. Please enter a number between 1 and 10.")
        return


if __name__ == "__main__":
    main()
