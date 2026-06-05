#!/usr/bin/env python3
"""Test comprehensive statistics calculation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database
from monitoring.trader_statistics import TraderStatisticsCalculator

db = Database()
calc = TraderStatisticsCalculator(db)

# Get a trader with both resolution and position data if possible
traders = db.get_flagged_traders()[:5]

print("="*70)
print("TESTING COMPREHENSIVE STATISTICS")
print("="*70)

for trader in traders:
    stats = calc.calculate_comprehensive_stats(trader)

    print(f"\nTrader: {trader[:10]}...")
    print(f"  Resolution-based:")
    print(f"    Win Rate: {stats['resolution_based']['win_rate']:.1f}%")
    print(f"    Resolved: {stats['resolution_based']['resolved_trades']} trades")
    print(f"  P&L-based:")
    print(f"    Realized P&L: ${stats['pnl_based']['realized_pnl']:,.2f}")
    print(f"    Avg ROI: {stats['pnl_based']['avg_roi']:.1f}%")
    print(f"    Closed Positions: {stats['pnl_based']['closed_positions']}")
    print(f"  Combined Metrics:")
    print(f"    Total Profit: ${stats['combined']['total_profit']:,.2f}")
    print(f"    Sample Size: {stats['combined']['sample_size']['resolved_trades']} resolved trades, "
          f"{stats['combined']['sample_size']['closed_positions']} closed positions")

print("\n[SUCCESS] Comprehensive stats calculation working!")
