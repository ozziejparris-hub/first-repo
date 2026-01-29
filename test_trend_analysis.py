"""
Test script for market trend analysis.

Tests trend detection and Telegram alert formatting.
"""
import asyncio
import sys
import os
from monitoring.system_observer import SystemObserver


async def test_check_only():
    """Check configuration only (no Telegram send)."""
    print("\n" + "="*70)
    print("  TREND ANALYSIS - CONFIGURATION CHECK")
    print("="*70)
    print()

    # Check environment variables
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if telegram_token and chat_id:
        print("[OK] Telegram credentials found")
        print(f"  Token: {telegram_token[:20]}...")
        print(f"  Chat ID: {chat_id}")
    else:
        print("[WARNING] Telegram credentials not found")
        print("  Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable alerts")

    # Check database
    db_path = 'data/polymarket_tracker.db'
    if os.path.exists(db_path):
        print(f"\n[OK] Database found: {db_path}")

        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check for active markets
        cursor.execute("""
            SELECT COUNT(*) FROM markets WHERE resolved = 0
        """)
        active_markets = cursor.fetchone()[0]

        # Check for recent trades
        cursor.execute("""
            SELECT COUNT(*) FROM trades
            WHERE timestamp >= datetime('now', '-1 day')
        """)
        recent_trades = cursor.fetchone()[0]

        # Check for elite traders
        cursor.execute("""
            SELECT COUNT(*) FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 20
        """)
        elite_traders = cursor.fetchone()[0]

        conn.close()

        print(f"  Active markets: {active_markets:,}")
        print(f"  Recent trades (24h): {recent_trades:,}")
        print(f"  Elite traders: {elite_traders}")

        if active_markets > 0 and recent_trades > 0:
            print("\n[OK] System ready for trend analysis")
        else:
            print("\n[WARNING] Insufficient data for trend analysis")
    else:
        print(f"\n[ERROR] Database not found: {db_path}")

    print("\n" + "="*70)


async def test_detect_only():
    """Test trend detection only (no Telegram send)."""
    print("\n" + "="*70)
    print("  TREND DETECTION TEST (No Telegram)")
    print("="*70)
    print()

    # Create observer with dummy credentials for testing
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', 'dummy_token_for_testing')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '0')

    observer = SystemObserver(telegram_token, chat_id)

    print("Detecting market trends...")
    trends = await observer._detect_market_trends()

    print(f"\n[RESULTS] Detected {len(trends)} trends\n")

    if trends:
        print("="*70)
        print("  TOP TRENDS (Sorted by Consensus Shift)")
        print("="*70)

        for i, trend in enumerate(trends[:10], 1):
            title = trend['title']
            if len(title) > 55:
                title = title[:52] + "..."

            print(f"\n{i}. {title}")
            print(f"   Consensus Shift: {trend['consensus_shift']:+.1%}")
            print(f"   Direction: {trend['direction']}")
            print(f"   Elite Consensus: {trend['elite_consensus']}")
            print(f"   Elite Agreement: {trend['elite_agreement']:.1%}")
            print(f"   Elite Traders: {trend['elite_trader_count']}")
            print(f"   Recent Trades: {trend['recent_trades']:,}")

            if trend['volume_spike']:
                print(f"   [SPIKE] Volume: {trend['volume_multiplier']:.1f}x normal")

        # High confidence trends
        high_conf = [t for t in trends if t['elite_agreement'] >= 0.70 or t['volume_spike']]
        print(f"\n{'='*70}")
        print(f"  HIGH-CONFIDENCE TRENDS: {len(high_conf)}")
        print(f"{'='*70}")

        if high_conf:
            for trend in high_conf[:5]:
                title = trend['title']
                if len(title) > 50:
                    title = title[:47] + "..."
                print(f"[BULLET] {title}")
                print(f"  Elite Agreement: {trend['elite_agreement']:.1%}, "
                      f"Volume Spike: {'Yes' if trend['volume_spike'] else 'No'}")
        else:
            print("  No high-confidence trends detected")
    else:
        print("  No trends detected (markets may be stable)")

    print("\n" + "="*70)


async def test_full():
    """Full test with Telegram send."""
    print("\n" + "="*70)
    print("  FULL TREND ANALYSIS TEST (With Telegram)")
    print("="*70)
    print()

    # Check credentials
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not telegram_token or not chat_id:
        print("[ERROR] Telegram credentials not found")
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        print("\n" + "="*70)
        return

    observer = SystemObserver(telegram_token, chat_id)

    print("Detecting trends...")
    trends = await observer._detect_market_trends()

    print(f"Detected {len(trends)} trends")

    # Send alerts for high-confidence trends
    high_conf = [t for t in trends if t['elite_agreement'] >= 0.70 or t['volume_spike']]

    if high_conf:
        print(f"\nSending {len(high_conf)} trend alerts to Telegram...")

        for i, trend in enumerate(high_conf[:5], 1):
            title = trend['title']
            if len(title) > 50:
                title = title[:47] + "..."
            print(f"  {i}. {title}...")
            await observer.telegram.send_trend_alert(trend)

        print("\n[OK] Trend alerts sent!")
    else:
        print("\n[WARNING] No high-confidence trends to alert")

    print("\n" + "="*70)


if __name__ == "__main__":
    # Parse command line arguments
    mode = 'detect-only'

    if len(sys.argv) > 1:
        if '--mode' in sys.argv:
            idx = sys.argv.index('--mode')
            if idx + 1 < len(sys.argv):
                mode = sys.argv[idx + 1]

    # Run test
    if mode == 'check-only':
        asyncio.run(test_check_only())
    elif mode == 'detect-only':
        asyncio.run(test_detect_only())
    elif mode == 'full':
        asyncio.run(test_full())
    else:
        print(f"Unknown mode: {mode}")
        print("Usage: python test_trend_analysis.py --mode <check-only|detect-only|full>")
        print()
        print("Modes:")
        print("  check-only   - Check configuration only")
        print("  detect-only  - Detect trends without sending to Telegram (default)")
        print("  full         - Detect and send to Telegram")
