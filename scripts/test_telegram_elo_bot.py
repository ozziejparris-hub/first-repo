#!/usr/bin/env python3
"""
Test Telegram ELO bot features.
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

import asyncio
from monitoring.database import Database
from monitoring.telegram_elo_bot import ELOTelegramBot
from dotenv import load_dotenv

load_dotenv()


async def main():
    print("="*70)
    print("  TELEGRAM ELO BOT TEST")
    print("="*70)

    # Initialize
    TELEGRAM_TOKEN = os.getenv("telegram_alerts_token")
    TELEGRAM_CHAT_ID = os.getenv("telegram_chat_id")

    if not TELEGRAM_TOKEN:
        print("[ERROR] Missing telegram_alerts_token in .env")
        print("Please add: telegram_alerts_token=YOUR_BOT_TOKEN")
        return

    if not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing telegram_chat_id in .env")
        print("Please add: telegram_chat_id=YOUR_CHAT_ID")
        return

    print(f"\n[INIT] Using bot token: {TELEGRAM_TOKEN[:20]}...")
    print(f"[INIT] Chat ID: {TELEGRAM_CHAT_ID}")

    db = Database()
    bot = ELOTelegramBot(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, db)

    await bot.initialize()

    # Test 1: Database methods
    print("\n[TEST 1] Testing database methods...")
    top_traders = db.get_top_traders_by_elo(limit=10)
    print(f"[OK] Found {len(top_traders)} top traders")

    if top_traders:
        print(f"  Top trader: {top_traders[0]['address'][:10]}... "
              f"(ELO: {top_traders[0]['comprehensive_elo']:.0f})")

    # Test 2: Elite traders
    print("\n[TEST 2] Testing elite traders...")
    elite = db.get_elite_traders(min_elo=1800)
    print(f"[OK] Found {len(elite)} elite traders (>1800 ELO)")

    # Test 3: Trader rank
    print("\n[TEST 3] Testing trader rank lookup...")
    if top_traders:
        test_addr = top_traders[0]['address']
        rank_data = db.get_trader_rank(test_addr)
        if rank_data:
            print(f"[OK] Trader {test_addr[:10]}... is rank #{rank_data['rank']}")
        else:
            print("[WARN] Could not get rank data")

    # Test 4: Send daily leaderboard
    print("\n[TEST 4] Sending daily leaderboard to Telegram...")
    try:
        await bot.send_daily_leaderboard(top_n=10)
        print("[OK] Daily leaderboard sent!")
        print("     Check your Telegram to see the message")
    except Exception as e:
        print(f"[ERROR] Failed to send leaderboard: {e}")
        import traceback
        traceback.print_exc()

    # Test 5: Elite trader alert (simulate)
    print("\n[TEST 5] Testing elite trader alert format...")
    if top_traders:
        test_trader = top_traders[0]
        test_trade = {
            'market_title': 'Will Donald Trump win the 2024 election?',
            'outcome': 'YES',
            'shares': 150.0,
            'price': 0.72,
            'side': 'BUY',
            'timestamp': '2025-12-13 14:23:45'
        }

        rank_data = db.get_trader_rank(test_trader['address'])
        if rank_data:
            message = bot._format_elite_trade_alert(rank_data, test_trade)
            print("[OK] Elite alert message formatted:")
            print("---")
            print(message)
            print("---")

    print("\n" + "="*70)
    print("  ALL TESTS COMPLETE")
    print("="*70)
    print("\nNext steps:")
    print("  1. Check your Telegram for the leaderboard message")
    print("  2. Try bot commands: /leaderboard, /stats, /elite")
    print("  3. Integrate into monitoring for live alerts")

    await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
