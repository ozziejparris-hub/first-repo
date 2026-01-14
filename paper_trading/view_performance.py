#!/usr/bin/env python3
"""
View Paper Trading Performance

Displays detailed performance metrics and trade history.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from paper_trading.portfolio_manager import PortfolioManager


def main():
    print("=" * 70)
    print("  PAPER TRADING PERFORMANCE REPORT")
    print("=" * 70)
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Load portfolio
    pm = PortfolioManager()
    perf = pm.get_performance()

    # Overview
    print("\n  OVERVIEW")
    print("  " + "-" * 30)
    print(f"  Initial Capital:    ${perf['initial_capital']:.2f}")
    print(f"  Current Capital:    ${perf['current_capital']:.2f}")
    print(f"  Open Positions:     ${perf['positions_value']:.2f}")
    print(f"  Total Value:        ${perf['total_value']:.2f}")
    print()
    roi_sign = "+" if perf['roi'] >= 0 else ""
    pnl_sign = "+" if perf['total_pnl'] >= 0 else ""
    print(f"  Total P&L:          {pnl_sign}${perf['total_pnl']:.2f}")
    print(f"  ROI:                {roi_sign}{perf['roi']:.2f}%")

    # Trade Statistics
    print("\n  TRADE STATISTICS")
    print("  " + "-" * 30)
    print(f"  Total Trades:       {perf['total_trades']}")
    print(f"  Winning Trades:     {perf['winning_trades']}")
    print(f"  Losing Trades:      {perf['losing_trades']}")
    print(f"  Win Rate:           {perf['win_rate']:.1%}")
    print()
    print(f"  Average P&L:        ${perf['avg_pnl']:+.2f}")
    print(f"  Average Win:        ${perf['avg_win']:+.2f}")
    print(f"  Average Loss:       ${perf['avg_loss']:+.2f}")

    # Open Positions
    if pm.positions:
        print("\n  OPEN POSITIONS")
        print("  " + "-" * 30)
        for i, pos in enumerate(pm.positions, 1):
            print(f"  {i}. {pos['outcome']} @ ${pos['avg_price']:.3f}")
            print(f"     {pos['market_title'][:50]}...")
            print(f"     Cost: ${pos['total_cost']:.2f}, Confidence: {pos['confidence']:.1%}")
            print()

    # Recent Trade History
    if pm.trade_history:
        print("\n  RECENT TRADE HISTORY")
        print("  " + "-" * 30)
        for trade in pm.trade_history[-10:]:  # Last 10 trades
            pnl_sign = "+" if trade['pnl'] >= 0 else ""
            status = "[W]" if trade['pnl'] >= 0 else "[L]"
            print(f"  {status} {trade['outcome']} on {trade['market_title'][:40]}...")
            print(f"      Entry: ${trade['avg_price']:.3f} -> Exit: ${trade['exit_price']:.3f}")
            print(f"      P&L: {pnl_sign}${trade['pnl']:.2f} ({pnl_sign}{trade['pnl_pct']:.1f}%)")
            print(f"      Reason: {trade['close_reason']}")
            print()

    # Validation vs Simulation
    print("\n  VALIDATION VS SIMULATION")
    print("  " + "-" * 30)
    print("  Simulation Predictions:")
    print("    - Expected Win Rate: 65-70%")
    print("    - Expected ROI: 20-30%")
    print()

    # Check if performance matches simulation
    if perf['total_trades'] >= 10:
        if 0.55 <= perf['win_rate'] <= 0.80:
            print("  [OK] Win rate matches simulation expectations")
        else:
            print("  [!!] Win rate differs from simulation")

        if -10 <= perf['roi'] <= 50:
            print("  [OK] ROI in expected range")
        else:
            print("  [!!] ROI outside expected range")
    else:
        print("  [..] Not enough trades for validation (need 10+)")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
