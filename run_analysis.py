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
    print("3. Weighted Consensus System ⭐ NEW")
    print("   ELO ratings + weighted majority algorithm for market predictions")
    print("   Requires: Resolved markets for ELO calculation")
    print()
    print("4. Test Analysis Demo")
    print("   Demo of performance analysis calculations (no database)")
    print()
    print("5. Test Behavior Demo")
    print("   Demo of behavior analysis calculations (no database)")
    print()
    print("6. Test Market Filtering")
    print("   Test crypto/sports market exclusion logic")
    print()
    print("7. Exit")
    print()

    choice = input("Enter choice (1-7): ").strip()

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
        print("\nRunning Performance Analysis Demo...")
        from test_analysis_demo import main as demo_main
        demo_main()

    elif choice == "5":
        print("\nRunning Behavior Analysis Demo...")
        from test_behavior_demo import main as behavior_demo_main
        behavior_demo_main()

    elif choice == "6":
        print("\nRunning Market Filtering Test...")
        from test_market_filtering import test_market_exclusion
        test_market_exclusion()

    elif choice == "7":
        print("Goodbye!")
        return

    else:
        print("Invalid choice. Please enter a number between 1 and 7.")
        return


if __name__ == "__main__":
    main()
