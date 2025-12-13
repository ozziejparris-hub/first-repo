#!/usr/bin/env python3
"""
View Trader Rankings by Comprehensive ELO

Shows top traders with their comprehensive ELO ratings and breakdown.

Usage:
  python scripts/view_trader_rankings.py                    # Top 20
  python scripts/view_trader_rankings.py --limit 50         # Top 50
  python scripts/view_trader_rankings.py --min-elo 1600     # ELO >= 1600
  python scripts/view_trader_rankings.py --detailed         # Show all modifiers
  python scripts/view_trader_rankings.py --export rankings.csv
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

import argparse
from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


def format_elo_change(comp_elo, base_elo):
    """Format ELO change."""
    change = comp_elo - base_elo
    if change > 0:
        return f"+{change:.0f}"
    elif change < 0:
        return f"{change:.0f}"
    else:
        return "0"


def main():
    parser = argparse.ArgumentParser(description='View trader rankings by comprehensive ELO')
    parser.add_argument('--limit', type=int, default=20, help='Number of traders to show (default: 20)')
    parser.add_argument('--min-elo', type=float, default=0, help='Minimum ELO threshold (default: 0)')
    parser.add_argument('--detailed', action='store_true', help='Show detailed modifier breakdown')
    parser.add_argument('--export', type=str, help='Export to CSV file')
    args = parser.parse_args()

    print("="*100)
    print(f"  TRADER RANKINGS BY COMPREHENSIVE ELO (Top {args.limit})")
    print("="*100)

    # Initialize
    db = Database()
    bridge = UnifiedELOMonitoringBridge(db)

    # Get rankings
    print(f"\nFetching rankings (min ELO: {args.min_elo})...")
    rankings = bridge.get_trader_ranking(limit=args.limit, min_elo=args.min_elo)

    if not rankings:
        print("\n[WARN] No traders found with comprehensive ELO")
        print("Run: python scripts/recalculate_comprehensive_elo.py")
        return 1

    print(f"Found {len(rankings)} traders\n")

    # Show summary statistics
    avg_comp_elo = sum(t['comprehensive_elo'] for t in rankings) / len(rankings)
    avg_base_elo = sum(t['base_category_elo'] for t in rankings) / len(rankings)
    avg_multiplier = avg_comp_elo / avg_base_elo if avg_base_elo > 0 else 1.0

    print("Summary Statistics:")
    print(f"  Average comprehensive ELO: {avg_comp_elo:.0f}")
    print(f"  Average base ELO: {avg_base_elo:.0f}")
    print(f"  Average multiplier: {avg_multiplier:.3f}x")
    print()

    # Show rankings
    if not args.detailed:
        # Simple view
        print(f"{'Rank':<6}{'Address':<20}{'Comp ELO':<12}{'Base ELO':<12}{'Change':<10}{'Win%':<8}{'Trades':<8}")
        print("-"*100)

        for i, trader in enumerate(rankings, 1):
            addr = trader['address'][:18]
            comp_elo = trader['comprehensive_elo']
            base_elo = trader['base_category_elo']
            change = format_elo_change(comp_elo, base_elo)
            win_rate = trader.get('win_rate', 0) * 100
            trades = trader.get('total_trades', 0)

            print(f"{i:<6}{addr:<20}{comp_elo:<12.0f}{base_elo:<12.0f}{change:<10}"
                  f"{win_rate:<8.1f}{trades:<8}")

    else:
        # Detailed view with modifiers
        print(f"{'Rank':<6}{'Address':<20}{'Comp ELO':<10}{'Base':<10}{'Behav':<8}{'Adv':<8}{'P&L':<8}{'Total':<8}")
        print("-"*100)

        for i, trader in enumerate(rankings, 1):
            addr = trader['address'][:18]
            comp_elo = trader['comprehensive_elo']
            base_elo = trader['base_category_elo']
            behav = trader.get('behavioral_modifier', 1.0)
            adv = trader.get('advanced_modifier', 1.0)
            pnl_mod = trader.get('pnl_modifier', 1.0)
            total_mult = (comp_elo / base_elo) if base_elo > 0 else 1.0

            print(f"{i:<6}{addr:<20}{comp_elo:<10.0f}{base_elo:<10.0f}"
                  f"{behav:<8.3f}{adv:<8.3f}{pnl_mod:<8.3f}{total_mult:<8.3f}")

        print("\nLegend:")
        print("  Behav  = Behavioral modifier (consistency, diversity, style)")
        print("  Adv    = Advanced metrics (calibration, risk, regret)")
        print("  P&L    = P&L modifier (profit, ROI, quality)")
        print("  Total  = Combined multiplier (Comp ELO / Base ELO)")

    # Export if requested
    if args.export:
        import csv
        with open(args.export, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'rank', 'address', 'comprehensive_elo', 'base_category_elo',
                'elo_change', 'win_rate', 'total_trades',
                'behavioral_modifier', 'advanced_modifier',
                'pnl_modifier', 'elo_last_updated'
            ])
            writer.writeheader()

            for i, trader in enumerate(rankings, 1):
                row = {
                    'rank': i,
                    'address': trader['address'],
                    'comprehensive_elo': trader['comprehensive_elo'],
                    'base_category_elo': trader['base_category_elo'],
                    'elo_change': trader['comprehensive_elo'] - trader['base_category_elo'],
                    'win_rate': trader.get('win_rate', 0),
                    'total_trades': trader.get('total_trades', 0),
                    'behavioral_modifier': trader.get('behavioral_modifier', 1.0),
                    'advanced_modifier': trader.get('advanced_modifier', 1.0),
                    'pnl_modifier': trader.get('pnl_modifier', 1.0),
                    'elo_last_updated': trader.get('elo_last_updated', '')
                }
                writer.writerow(row)

        print(f"\n[OK] Rankings exported to: {args.export}")

    print("\n" + "="*100)

    return 0


if __name__ == "__main__":
    exit(main())
