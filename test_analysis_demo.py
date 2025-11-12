#!/usr/bin/env python3
"""
Demo/Test script for trader_performance_analysis.py

Shows how the analysis calculations work with sample data.
Run this to verify the logic before running on real database.
"""

from datetime import datetime


def demo_pnl_calculation():
    """Demonstrate P&L calculation logic."""
    print("="*70)
    print("PROFIT/LOSS CALCULATION DEMO")
    print("="*70 + "\n")

    # Example trades
    examples = [
        {
            "name": "Winning Buy Trade",
            "side": "buy",
            "outcome": "yes",
            "winning_outcome": "yes",
            "shares": 100,
            "price": 0.65,
            "expected": "PROFIT"
        },
        {
            "name": "Losing Buy Trade",
            "side": "buy",
            "outcome": "yes",
            "winning_outcome": "no",
            "shares": 100,
            "price": 0.65,
            "expected": "LOSS"
        },
        {
            "name": "Winning Sell/Short",
            "side": "sell",
            "outcome": "no",
            "winning_outcome": "yes",
            "shares": 100,
            "price": 0.35,
            "expected": "PROFIT"
        },
        {
            "name": "High Confidence Win",
            "side": "buy",
            "outcome": "yes",
            "winning_outcome": "yes",
            "shares": 200,
            "price": 0.85,
            "expected": "SMALL PROFIT"
        },
    ]

    for i, trade in enumerate(examples, 1):
        print(f"Example {i}: {trade['name']}")
        print(f"  Trade: {trade['side'].upper()} {trade['shares']} shares @ ${trade['price']:.2f}")
        print(f"  Outcome: {trade['outcome'].upper()}")
        print(f"  Market resolved: {trade['winning_outcome'].upper()}")

        invested = trade['shares'] * trade['price']
        print(f"  Amount invested: ${invested:.2f}")

        # Calculate if won
        trader_won = False
        if trade['side'] == 'buy':
            trader_won = (trade['outcome'] == trade['winning_outcome'])
        elif trade['side'] == 'sell':
            trader_won = (trade['outcome'] != trade['winning_outcome'])

        if trader_won:
            payout = trade['shares'] * 1.0
            pnl = payout - invested
            print(f"  Result: WON ✓")
            print(f"  Payout: ${payout:.2f}")
            print(f"  Profit: ${pnl:.2f}")
        else:
            pnl = -invested
            print(f"  Result: LOST ✗")
            print(f"  Loss: ${pnl:.2f}")

        print(f"  Expected: {trade['expected']}")
        print()

    print("="*70 + "\n")


def demo_metrics_calculation():
    """Demonstrate win rate and ROI calculation."""
    print("="*70)
    print("METRICS CALCULATION DEMO")
    print("="*70 + "\n")

    # Sample trader data
    trader_trades = [
        {"resolved": True, "won": True, "pnl": 35.00, "invested": 65.00},   # Win
        {"resolved": True, "won": True, "pnl": 42.50, "invested": 57.50},   # Win
        {"resolved": True, "won": False, "pnl": -45.00, "invested": 45.00}, # Loss
        {"resolved": True, "won": True, "pnl": 28.00, "invested": 72.00},   # Win
        {"resolved": True, "won": False, "pnl": -30.00, "invested": 30.00}, # Loss
        {"resolved": False, "won": None, "pnl": 0, "invested": 100.00},     # Unresolved
        {"resolved": True, "won": True, "pnl": 15.00, "invested": 85.00},   # Win
    ]

    total_trades = len(trader_trades)
    resolved_trades = sum(1 for t in trader_trades if t['resolved'])
    winning_trades = sum(1 for t in trader_trades if t.get('won') == True)
    total_pnl = sum(t['pnl'] for t in trader_trades if t['resolved'])
    total_invested = sum(t['invested'] for t in trader_trades if t['resolved'])

    win_rate = (winning_trades / resolved_trades * 100) if resolved_trades > 0 else 0
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    print(f"Trader Address: 0xdemo123456789abcdef\n")

    print("Trades Breakdown:")
    for i, trade in enumerate(trader_trades, 1):
        if trade['resolved']:
            result = "WIN ✓" if trade['won'] else "LOSS ✗"
            print(f"  Trade {i}: {result} | P&L: ${trade['pnl']:>7.2f} | Invested: ${trade['invested']:.2f}")
        else:
            print(f"  Trade {i}: UNRESOLVED (not counted)")

    print(f"\nCalculations:")
    print(f"  Total trades: {total_trades}")
    print(f"  Resolved trades: {resolved_trades}")
    print(f"  Winning trades: {winning_trades}")
    print(f"  Losing trades: {resolved_trades - winning_trades}")
    print(f"  Win Rate: {winning_trades}/{resolved_trades} = {win_rate:.2f}%")
    print(f"  Total P&L: ${total_pnl:.2f}")
    print(f"  Total Invested: ${total_invested:.2f}")
    print(f"  ROI: ${total_pnl:.2f} / ${total_invested:.2f} = {roi:.2f}%")
    print(f"  Combined Score: ({win_rate:.2f} * 0.5) + ({roi:.2f} * 0.5) = {(win_rate * 0.5 + roi * 0.5):.2f}")

    print("\n" + "="*70 + "\n")


def demo_ranking():
    """Demonstrate trader ranking."""
    print("="*70)
    print("TRADER RANKING DEMO")
    print("="*70 + "\n")

    # Sample traders
    traders = [
        {
            "address": "0x1a2b3c4d5e...",
            "resolved_trades": 25,
            "winning_trades": 18,
            "win_rate": 72.0,
            "roi": 24.5,
            "total_pnl": 1250.50
        },
        {
            "address": "0x9f8e7d6c5b...",
            "resolved_trades": 30,
            "winning_trades": 21,
            "win_rate": 70.0,
            "roi": 31.2,
            "total_pnl": 1876.25
        },
        {
            "address": "0x7k9m4n2p8q...",
            "resolved_trades": 15,
            "winning_trades": 12,
            "win_rate": 80.0,
            "roi": 18.3,
            "total_pnl": 892.10
        },
        {
            "address": "0x3x5y7z1a4b...",
            "resolved_trades": 20,
            "winning_trades": 11,
            "win_rate": 55.0,
            "roi": 8.2,
            "total_pnl": 325.75
        },
    ]

    # Calculate combined scores
    for trader in traders:
        trader['combined_score'] = trader['win_rate'] * 0.5 + trader['roi'] * 0.5

    print("🏆 TOP TRADERS BY WIN RATE")
    print("-"*70)
    top_by_winrate = sorted(traders, key=lambda x: x['win_rate'], reverse=True)
    print(f"{'Rank':<6}{'Address':<18}{'Win Rate':<12}{'Resolved':<12}{'ROI':<12}")
    for i, t in enumerate(top_by_winrate, 1):
        print(f"{i:<6}{t['address']:<18}{t['win_rate']:>6.1f}%{t['resolved_trades']:>10}{t['roi']:>9.1f}%")

    print("\n💰 TOP TRADERS BY ROI")
    print("-"*70)
    top_by_roi = sorted(traders, key=lambda x: x['roi'], reverse=True)
    print(f"{'Rank':<6}{'Address':<18}{'ROI':<12}{'P&L':<15}{'Win Rate':<12}")
    for i, t in enumerate(top_by_roi, 1):
        print(f"{i:<6}{t['address']:<18}{t['roi']:>6.1f}%  ${t['total_pnl']:>10,.2f}{t['win_rate']:>9.1f}%")

    print("\n⭐ TOP TRADERS BY COMBINED SCORE")
    print("-"*70)
    top_by_combined = sorted(traders, key=lambda x: x['combined_score'], reverse=True)
    print(f"{'Rank':<6}{'Address':<18}{'Score':<12}{'Win Rate':<12}{'ROI':<12}")
    for i, t in enumerate(top_by_combined, 1):
        print(f"{i:<6}{t['address']:<18}{t['combined_score']:>6.2f}{t['win_rate']:>9.1f}%{t['roi']:>9.1f}%")

    print("\n" + "="*70 + "\n")


def main():
    """Run all demos."""
    print("\n" + "="*70)
    print("TRADER PERFORMANCE ANALYSIS - CALCULATION DEMO")
    print("="*70 + "\n")

    print("This demo shows how the analysis calculations work.")
    print("No database or API calls required - just logic demonstration.\n")

    input("Press Enter to start demo...")

    demo_pnl_calculation()
    input("Press Enter for next demo...")

    demo_metrics_calculation()
    input("Press Enter for next demo...")

    demo_ranking()

    print("✅ Demo complete!")
    print("\nWhen you run the actual analysis:")
    print("  python trader_performance_analysis.py")
    print("\nIt will use these same calculations on real trade data from polymarket_tracker.db")
    print()


if __name__ == "__main__":
    main()
