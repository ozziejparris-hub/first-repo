"""
Test script to verify daily report implementation.

This script tests the daily report functionality by:
1. Collecting daily metrics
2. Formatting and sending the report to Telegram
"""

import asyncio
import sys
import os

# Add monitoring module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitoring.system_observer import SystemObserver


async def test_daily_report():
    """Test daily report generation and sending."""

    print("="*70)
    print("  DAILY REPORT TEST")
    print("="*70)
    print()

    # Initialize System Observer
    print("[1/3] Initializing System Observer...")

    # Get credentials from environment
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not telegram_token or not chat_id:
        print("[ERROR] Missing Telegram credentials")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        return False

    observer = SystemObserver(telegram_token, chat_id)
    print("[OK] System Observer initialized")
    print()

    # Collect daily metrics
    print("[2/3] Collecting daily metrics...")
    metrics = await observer._collect_daily_metrics()

    # Display metrics summary
    print("[OK] Metrics collected:")
    print(f"  • Top traders: {len(metrics.get('top_10_traders', []))}")
    print(f"  • Winners (24h): {len(metrics.get('daily_winners', []))}")
    print(f"  • Losers (24h): {len(metrics.get('daily_losers', []))}")
    print(f"  • Best trade: {'Yes' if metrics.get('best_trade') else 'No'}")
    print(f"  • Trades (24h): {metrics.get('trades_24h', 0):,}")
    print(f"  • Active traders (24h): {metrics.get('active_traders_24h', 0):,}")
    print(f"  • Markets resolved (24h): {metrics.get('markets_resolved_24h', 0)}")
    print(f"  • Total P&L (24h): ${metrics.get('total_pnl_24h', 0):+,.2f}")
    print(f"  • Worker coverage: {metrics.get('worker_coverage', 0):.1f}%")

    if 'error' in metrics:
        print(f"\n[ERROR] Error in metrics collection: {metrics['error']}")
        return False

    print()

    # Send daily report to Telegram
    print("[3/3] Sending daily report to Telegram...")

    if not observer.telegram:
        print("[ERROR] Telegram not configured")
        return False

    success = await observer.telegram.send_daily_report(metrics)

    if success:
        print("[OK] Daily report sent successfully!")
        print()
        print("="*70)
        print("Check your Telegram bot for the daily report message")
        print("="*70)
        return True
    else:
        print("[ERROR] Failed to send daily report")
        return False


async def test_metrics_only():
    """Test only metrics collection (no Telegram send)."""

    print("="*70)
    print("  DAILY METRICS COLLECTION TEST (No Telegram)")
    print("="*70)
    print()

    # Get credentials from environment or use dummy values for testing
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', 'dummy_token_for_testing')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '0')

    observer = SystemObserver(telegram_token, chat_id)

    print("Collecting metrics...")
    metrics = await observer._collect_daily_metrics()

    if 'error' in metrics:
        print(f"[ERROR] {metrics['error']}")
        return

    # Display detailed metrics
    print("\n[STATS] METRICS COLLECTED:\n")

    # Top 10 traders
    print("[TOP] TOP 10 TRADERS:")
    if metrics.get('top_10_traders'):
        for i, trader in enumerate(metrics['top_10_traders'], 1):
            print(f"  {i:2d}. {trader['address'][:10]}... "
                  f"ELO: {trader['elo']:.0f} | "
                  f"ROI: {trader['roi']:+.1f}% | "
                  f"Trades: {trader['total_trades']}")
    else:
        print("  (No data)")

    # Winners
    print("\n[WINNERS] BIGGEST WINNERS (24h):")
    if metrics.get('daily_winners'):
        for winner in metrics['daily_winners']:
            print(f"  • {winner['address'][:10]}... "
                  f"P&L: ${winner['pnl_24h']:+.2f} | "
                  f"ELO: {winner['elo']:.0f}")
    else:
        print("  (No profitable positions closed)")

    # Losers
    print("\n[LOSERS] BIGGEST LOSERS (24h):")
    if metrics.get('daily_losers'):
        for loser in metrics['daily_losers']:
            print(f"  • {loser['address'][:10]}... "
                  f"P&L: ${loser['pnl_24h']:+.2f} | "
                  f"ELO: {loser['elo']:.0f}")
    else:
        print("  (No losing positions closed)")

    # Best trade
    print("\n[BEST] BEST TRADE:")
    if metrics.get('best_trade'):
        best = metrics['best_trade']
        print(f"  Trader: {best['trader'][:10]}...")
        print(f"  Market: {best['market_title'][:50]}")
        print(f"  Outcome: {best['outcome']}")
        print(f"  ROI: {best['roi']:.1f}% | P&L: ${best['pnl']:+.2f}")
    else:
        print("  (No closed positions today)")

    # System stats
    print("\n[STATS] SYSTEM STATS (24h):")
    print(f"  • Trades: {metrics.get('trades_24h', 0):,}")
    print(f"  • Active traders: {metrics.get('active_traders_24h', 0):,}")
    print(f"  • Markets resolved: {metrics.get('markets_resolved_24h', 0)}")
    print(f"  • Total P&L: ${metrics.get('total_pnl_24h', 0):+,.2f}")
    print(f"  • Worker coverage: {metrics.get('worker_coverage', 0):.1f}%")

    print("\n" + "="*70)
    print("[OK] Metrics collection test complete")
    print("="*70)


def main():
    """Main entry point."""

    import argparse

    parser = argparse.ArgumentParser(description='Test daily report implementation')
    parser.add_argument('--mode', choices=['full', 'metrics-only'], default='full',
                       help='Test mode: full (with Telegram) or metrics-only')

    args = parser.parse_args()

    try:
        if args.mode == 'full':
            print("\nRunning FULL test (with Telegram send)...\n")
            result = asyncio.run(test_daily_report())
            sys.exit(0 if result else 1)
        else:
            print("\nRunning METRICS-ONLY test (no Telegram)...\n")
            asyncio.run(test_metrics_only())
            sys.exit(0)

    except KeyboardInterrupt:
        print("\n\n[ERROR] Test interrupted by user")
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
