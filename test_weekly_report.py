"""
Test script for weekly performance summary.

Tests weekly metrics collection and Telegram report formatting.
"""

import asyncio
import sys
import os

# Add monitoring module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitoring.system_observer import SystemObserver


async def test_weekly_metrics():
    """Test weekly metrics collection only (no Telegram send)."""

    print("="*70)
    print("  WEEKLY METRICS COLLECTION TEST (No Telegram)")
    print("="*70)
    print()

    # Get credentials from environment or use dummy values for testing
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', 'dummy_token_for_testing')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '0')

    observer = SystemObserver(telegram_token, chat_id)

    print("Collecting metrics...")
    metrics = await observer._collect_weekly_metrics()

    if 'error' in metrics:
        print(f"[ERROR] {metrics['error']}")
        return

    # Display detailed metrics
    print("\n[STATS] METRICS COLLECTED:\n")

    # Top 20 traders
    print("[TOP] TOP 20 TRADERS:")
    if metrics.get('top_20_traders'):
        for i, trader in enumerate(metrics['top_20_traders'][:10], 1):
            print(f"  {i:2d}. {trader['address'][:10]}... "
                  f"ELO: {trader['elo']:.0f} | "
                  f"ROI: {trader['roi']:+.1f}% | "
                  f"Trades: {trader['total_trades']}")
        if len(metrics['top_20_traders']) > 10:
            print(f"  ... and {len(metrics['top_20_traders']) - 10} more")
    else:
        print("  (No traders)")

    # Most active traders
    print(f"\n[ACTIVE] MOST ACTIVE TRADERS (7d):")
    if metrics.get('most_active_7d'):
        for trader in metrics['most_active_7d'][:5]:
            print(f"  • {trader['address'][:10]}... "
                  f"{trader['trades_7d']} trades | "
                  f"ELO: {trader['elo']:.0f}")
    else:
        print("  (No active traders)")

    # Best trades
    print(f"\n[BEST] BEST TRADES (7d):")
    if metrics.get('best_trades_7d'):
        for i, trade in enumerate(metrics['best_trades_7d'][:3], 1):
            print(f"  {i}. {trade['trader'][:10]}... "
                  f"ROI: {trade['roi']:.1f}% | "
                  f"P&L: ${trade['pnl']:+.2f}")
            print(f"     {trade['market_title'][:60]}")
    else:
        print("  (No closed positions)")

    # P&L leaders
    print(f"\n[PNL] P&L LEADERS (7d):")
    if metrics.get('pnl_leaders_7d'):
        for leader in metrics['pnl_leaders_7d'][:5]:
            print(f"  • {leader['address'][:10]}... "
                  f"${leader['pnl_7d']:+.2f} "
                  f"({leader['trades_closed']} positions)")
    else:
        print("  (No profitable positions)")

    # Win rate leaders
    print(f"\n[WIN] WIN RATE LEADERS (7d):")
    if metrics.get('win_rate_leaders_7d'):
        for leader in metrics['win_rate_leaders_7d'][:5]:
            print(f"  • {leader['address'][:10]}... "
                  f"{leader['win_rate']:.1f}% "
                  f"({leader['wins']}/{leader['total']})")
    else:
        print("  (Insufficient data)")

    # Most active markets
    print(f"\n[MARKETS] MOST ACTIVE MARKETS (7d):")
    if metrics.get('active_markets_7d'):
        for i, market in enumerate(metrics['active_markets_7d'][:3], 1):
            print(f"  {i}. \"{market['title'][:50]}...\"")
            print(f"     {market['total_trades']} trades | {market['unique_traders']} traders")
    else:
        print("  (No active markets)")

    # Markets resolved
    print(f"\n[RESOLVED] MARKETS RESOLVED (7d):")
    if metrics.get('markets_resolved_7d'):
        print(f"  Total: {len(metrics['markets_resolved_7d'])}")
        for market in metrics['markets_resolved_7d'][:3]:
            print(f"  • \"{market['title'][:50]}...\"")
            print(f"    Outcome: {market['outcome']}")
    else:
        print("  (No markets resolved)")

    # System stats
    print(f"\n[STATS] SYSTEM STATS (7d):")
    print(f"  • Trades: {metrics.get('trades_7d', 0):,}")
    print(f"  • Active traders: {metrics.get('active_traders_7d', 0):,}")
    print(f"  • Markets resolved: {metrics.get('markets_resolved_count', 0)}")
    print(f"  • Total P&L: ${metrics.get('total_pnl_7d', 0):+,.2f}")
    print(f"  • Worker coverage: {metrics.get('worker_coverage', 0):.1f}%")
    print(f"  • Total traders: {metrics.get('total_traders', 0):,}")

    print("\n" + "="*70)
    print("[OK] Metrics collection test complete")
    print("="*70)


async def test_weekly_full():
    """Test full weekly report with Telegram send."""

    print("="*70)
    print("  WEEKLY REPORT TEST (Full)")
    print("="*70)
    print()

    # Get credentials from environment
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not telegram_token or not chat_id:
        print("[ERROR] Missing Telegram credentials")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        return False

    print("[1/3] Initializing System Observer...")
    observer = SystemObserver(telegram_token, chat_id)
    print("[OK] System Observer initialized")
    print()

    # Collect weekly metrics
    print("[2/3] Collecting weekly metrics...")
    metrics = await observer._collect_weekly_metrics()

    # Display metrics summary
    print("[OK] Metrics collected:")
    print(f"  • Top 20 traders: {len(metrics.get('top_20_traders', []))}")
    print(f"  • Most active (7d): {len(metrics.get('most_active_7d', []))}")
    print(f"  • Best trades (7d): {len(metrics.get('best_trades_7d', []))}")
    print(f"  • P&L leaders (7d): {len(metrics.get('pnl_leaders_7d', []))}")
    print(f"  • Win rate leaders (7d): {len(metrics.get('win_rate_leaders_7d', []))}")
    print(f"  • Active markets (7d): {len(metrics.get('active_markets_7d', []))}")
    print(f"  • Markets resolved (7d): {len(metrics.get('markets_resolved_7d', []))}")
    print(f"  • Trades (7d): {metrics.get('trades_7d', 0):,}")
    print(f"  • Active traders (7d): {metrics.get('active_traders_7d', 0):,}")
    print(f"  • Total P&L (7d): ${metrics.get('total_pnl_7d', 0):+,.2f}")

    if 'error' in metrics:
        print(f"\n[ERROR] Error in metrics collection: {metrics['error']}")
        return False

    print()

    # Send weekly report to Telegram
    print("[3/3] Sending weekly report to Telegram...")

    if not observer.telegram:
        print("[ERROR] Telegram not configured")
        return False

    success = await observer.telegram.send_weekly_report(metrics)

    if success:
        print("[OK] Weekly report sent successfully!")
        print()
        print("="*70)
        print("Check your Telegram bot for the weekly report message")
        print("="*70)
        return True
    else:
        print("[ERROR] Failed to send weekly report")
        return False


def main():
    """Main entry point."""

    import argparse

    parser = argparse.ArgumentParser(description='Test weekly report implementation')
    parser.add_argument('--mode', choices=['full', 'metrics-only'], default='metrics-only',
                       help='Test mode: full (with Telegram) or metrics-only')

    args = parser.parse_args()

    try:
        if args.mode == 'full':
            print("\nRunning FULL test (with Telegram send)...\n")
            result = asyncio.run(test_weekly_full())
            sys.exit(0 if result else 1)
        else:
            print("\nRunning METRICS-ONLY test (no Telegram)...\n")
            asyncio.run(test_weekly_metrics())
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
