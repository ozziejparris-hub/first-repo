#!/usr/bin/env python3
"""
Main entry point for Polymarket Crypto Tracker.

This tracker monitors crypto "Up or Down" and price prediction markets,
tracking successful traders and sending Telegram notifications.
"""

import asyncio
import os
from dotenv import load_dotenv
from monitor import main as monitor_main


def main():
    """Main entry point."""
    print("=" * 70)
    print("🪙 POLYMARKET CRYPTO TRACKER")
    print("=" * 70)
    print()
    print("Monitoring crypto 'Up or Down' and price prediction markets")
    print("Tracking: BTC, ETH, SOL, XRP, and major altcoins")
    print()

    # Load environment variables
    load_dotenv()

    POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Optional

    if not POLYMARKET_API_KEY or not TELEGRAM_BOT_TOKEN:
        print("❌ Missing required environment variables!")
        print("Please ensure POLYMARKET_API_KEY and TELEGRAM_BOT_TOKEN are set in .env")
        print()
        print("Required:")
        print("  - POLYMARKET_API_KEY")
        print("  - TELEGRAM_BOT_TOKEN")
        print()
        print("Optional:")
        print("  - TELEGRAM_CHAT_ID")
        exit(1)

    print("✅ Environment variables loaded")
    print(f"✅ API Key: {POLYMARKET_API_KEY[:10]}...")
    print(f"✅ Telegram Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    if TELEGRAM_CHAT_ID:
        print(f"✅ Chat ID: {TELEGRAM_CHAT_ID}")
    print()

    print("Starting crypto tracker...")
    print()

    # Run the monitor
    asyncio.run(monitor_main(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))


if __name__ == "__main__":
    main()
