import asyncio
import time
import re
from datetime import datetime
from typing import Optional
from database import Database
from polymarket_client import PolymarketClient
from telegram_bot import TelegramNotifier
from trader_analyzer import TraderAnalyzer


class PolymarketCryptoMonitor:
    """Crypto-focused monitoring service - tracks crypto 'Up or Down' and price prediction markets."""

    def __init__(self, polymarket_api_key: str, telegram_token: str,
                 telegram_chat_id: Optional[str] = None,
                 check_interval: int = 600):  # 600 seconds = 10 minutes
        self.db = Database(db_name="polymarket_crypto_tracker.db")
        self.polymarket = PolymarketClient(polymarket_api_key)
        self.telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.analyzer = TraderAnalyzer(self.db, self.polymarket)
        self.check_interval = check_interval
        self.is_running = False

        # Set stop callback
        self.telegram.set_stop_callback(self.request_stop)

    def request_stop(self):
        """Request the monitor to stop."""
        print("🛑 Stop requested via Telegram")
        self.is_running = False

    def _should_include_market(self, market_title: str) -> bool:
        """
        Check if a market should be INCLUDED - CRYPTO TRACKER VERSION.

        INVERTED LOGIC: Include ONLY crypto markets, exclude everything else.

        CRYPTO PATTERNS TO INCLUDE:
        1. 🪙 "Up or Down" crypto speculation
        2. 🪙 "Dip to $" crypto markets
        3. 🪙 "Price of [crypto]" patterns
        4. 🪙 Other crypto price predictions (reach $, hit $, ATH, etc.)

        Returns True if market should be INCLUDED (kept for tracking).
        """
        title = market_title
        title_lower = market_title.lower()

        # List of crypto names (both full names AND tickers)
        crypto_names = [
            'bitcoin', 'btc',
            'ethereum', 'eth',
            'solana', 'sol',
            'xrp', 'ripple',
            'bnb', 'binance',
            'cardano', 'ada',
            'dogecoin', 'doge',
            'polygon', 'matic',
            'avalanche', 'avax',
            'chainlink', 'link',
            'polkadot', 'dot',
            'shiba', 'shib',
            'litecoin', 'ltc',
            'uniswap', 'uni',
            'pepe'
        ]

        # ===== PATTERN 1: "UP OR DOWN" - HIGHEST PRIORITY =====
        # These are ALWAYS crypto speculation markets
        if "up or down" in title_lower:
            return True  # INCLUDE

        # ===== PATTERN 2: "DIP TO $" =====
        if "dip to $" in title_lower:
            return True  # INCLUDE

        # ===== PATTERN 3: "PRICE OF [CRYPTO]" =====
        if "price of" in title_lower:
            price_indicators = [
                'be above $', 'be less than $', 'be below $', 'be between $',
                'above $', 'less than $', 'below $', 'reach $', 'hit $'
            ]

            has_crypto = any(crypto in title_lower for crypto in crypto_names)
            has_price_indicator = any(indicator in title_lower for indicator in price_indicators)

            if has_crypto and has_price_indicator:
                return True  # INCLUDE

        # ===== PATTERN 4: CRYPTO + PRICE PREDICTION VERBS =====
        price_verbs = [
            'reach $', 'hit $', 'close above', 'close between', 'close below',
            'finish week', 'all time high', 'ath ', 'new high', 'new low',
            'trade above', 'trade below', 'be between $', 'be above $', 'be below $'
        ]

        has_crypto = any(crypto in title_lower for crypto in crypto_names)
        has_price_verb = any(verb in title_lower for verb in price_verbs)

        if has_crypto and has_price_verb:
            return True  # INCLUDE

        # ===== DEFAULT: EXCLUDE =====
        # If no crypto pattern matched, exclude (opposite of geopolitics tracker)
        return False

    def _categorize_crypto_market(self, market_title: str) -> str:
        """
        Categorize crypto market by coin/token.

        Categories:
        - BTC (Bitcoin)
        - ETH (Ethereum)
        - SOL (Solana)
        - XRP (Ripple)
        - Major Altcoins (BNB, ADA, DOGE, AVAX, MATIC, LINK, DOT)
        - Meme Coins (SHIB, PEPE, DOGE)
        - Other Crypto
        """
        title_lower = market_title.lower()

        # Category mappings
        if any(name in title_lower for name in ['bitcoin', 'btc']):
            return 'BTC'
        elif any(name in title_lower for name in ['ethereum', 'eth']):
            return 'ETH'
        elif any(name in title_lower for name in ['solana', 'sol']):
            return 'SOL'
        elif any(name in title_lower for name in ['xrp', 'ripple']):
            return 'XRP'
        elif any(name in title_lower for name in ['bnb', 'binance', 'cardano', 'ada', 'avalanche', 'avax', 'polygon', 'matic', 'chainlink', 'link', 'polkadot', 'dot']):
            return 'Major Altcoins'
        elif any(name in title_lower for name in ['shib', 'shiba', 'pepe', 'doge', 'dogecoin']):
            return 'Meme Coins'
        else:
            return 'Other Crypto'

    async def initial_scan(self):
        """Perform initial scan to identify successful crypto traders."""
        print("🔍 Starting initial scan for successful crypto traders...")
        await self.telegram.send_message("🔍 Starting initial crypto trader scan...")

        newly_flagged = self.analyzer.scan_for_successful_traders()

        summary = self.analyzer.get_flagged_traders_summary()
        await self.telegram.send_message(
            f"✅ Initial scan complete!\n\n"
            f"Found {newly_flagged} new successful crypto traders.\n\n"
            f"{summary}"
        )

        print(f"✅ Initial scan complete. Flagged {newly_flagged} traders.")

    def check_for_new_trades(self):
        """Check for new trades from flagged traders in crypto markets."""
        flagged_traders = self.db.get_flagged_traders()

        if not flagged_traders:
            print("No flagged traders to monitor yet.")
            return 0

        print(f"Monitoring {len(flagged_traders)} flagged traders...")

        # Strategy: Fetch all recent trades and filter for our flagged traders
        print("Fetching recent trades from Polymarket...")
        all_recent_trades = self.polymarket.get_market_trades(market_id=None, limit=500)

        print(f"✅ Fetched {len(all_recent_trades)} recent trades")

        # Convert flagged traders to a set for fast lookup
        flagged_set = set(flagged_traders)

        # Filter for trades from our flagged traders
        relevant_trades = []
        for trade in all_recent_trades:
            trader = trade.get('proxyWallet')
            if trader in flagged_set:
                relevant_trades.append((trader, trade))

        print(f"📊 Found {len(relevant_trades)} trades from flagged traders")

        new_trades_count = 0
        duplicate_count = 0
        excluded_count = 0

        for trader_address, trade in relevant_trades:
            # Extract trade information
            trade_id = trade.get('transactionHash') or trade.get('id')
            if not trade_id:
                print(f"⚠️ Trade missing ID, skipping...")
                continue

            market_id = trade.get('conditionId') or trade.get('market')
            outcome = trade.get('outcome', 'Unknown')
            shares = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            side = trade.get('side', 'unknown')
            timestamp_raw = trade.get('timestamp')
            market_title = trade.get('title', 'Unknown Market')

            # CHECK: Only include crypto markets (INVERTED LOGIC)
            if not self._should_include_market(market_title):
                excluded_count += 1
                continue

            # Categorize the market
            market_category = self._categorize_crypto_market(market_title)

            # Parse timestamp
            try:
                if isinstance(timestamp_raw, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp_raw)
                else:
                    timestamp = datetime.fromisoformat(str(timestamp_raw).replace('Z', '+00:00'))
            except:
                timestamp = datetime.now()

            # Try to add trade to database
            is_new = self.db.add_trade(
                trade_id=trade_id,
                trader_address=trader_address,
                market_id=market_id,
                market_title=market_title,
                market_category=market_category,
                outcome=outcome,
                shares=shares,
                price=price,
                side=side,
                timestamp=timestamp
            )

            if is_new:
                new_trades_count += 1
                print(f"🪙 NEW: {trader_address[:10]}... traded {shares:.1f} @ ${price:.3f} in {market_title[:30]}...")
            else:
                duplicate_count += 1

        print(f"✅ New trades: {new_trades_count} | Already seen: {duplicate_count} | Excluded (non-crypto): {excluded_count}")
        return new_trades_count

    async def notify_new_trades(self):
        """Send bundled notifications for trades that haven't been notified yet."""
        unnotified_trades = self.db.get_unnotified_trades()

        if not unnotified_trades:
            return

        print(f"Processing {len(unnotified_trades)} trade notifications...")

        # Bundle trades by trader
        trades_by_trader = {}
        for trade in unnotified_trades:
            trader = trade['trader_address']
            if trader not in trades_by_trader:
                trades_by_trader[trader] = []
            trades_by_trader[trader].append(trade)

        # Get trader stats for all traders
        trader_stats_map = {}
        for trader in trades_by_trader.keys():
            stats = self.db.get_trader_stats(trader)
            if stats:
                trader_stats_map[trader] = stats

        print(f"Bundled into {len(trades_by_trader)} traders")

        # Send bundled notifications
        await self.telegram.send_bundled_trade_alerts(trades_by_trader, trader_stats_map)

        # Mark all as notified
        for trade in unnotified_trades:
            self.db.mark_trade_notified(trade['trade_id'])

    async def monitoring_loop(self):
        """Main monitoring loop that runs every check_interval."""
        cycle_count = 0

        while self.is_running:
            cycle_count += 1
            print(f"\n{'='*60}")
            print(f"Crypto Monitoring Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")

            try:
                # Check for new trades
                new_trades = self.check_for_new_trades()

                # Send notifications for new trades
                if new_trades > 0:
                    await self.notify_new_trades()

                # Periodically re-scan for new successful traders (every 10 cycles)
                if cycle_count % 10 == 0:
                    print("\n🔄 Performing periodic trader re-scan...")
                    newly_flagged = self.analyzer.scan_for_successful_traders()
                    if newly_flagged > 0:
                        await self.telegram.send_message(
                            f"🆕 Found {newly_flagged} new successful crypto traders!"
                        )

                print(f"\n✅ Cycle complete. Next check in {self.check_interval // 60} minutes.")

            except Exception as e:
                print(f"❌ Error in monitoring cycle: {e}")
                await self.telegram.send_message(f"⚠️ Error in monitoring: {str(e)}")

            # Wait for next cycle or until stop is requested
            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                await asyncio.sleep(1)

        print("\n🛑 Monitoring loop stopped")

    async def start(self):
        """Start the crypto monitoring service."""
        print("🚀 Starting Polymarket Crypto Monitor...")
        self.is_running = True

        # Initialize Telegram bot
        await self.telegram.initialize()
        await self.telegram.start_polling()

        # Send startup message
        await self.telegram.send_message(
            "🚀 <b>Polymarket Crypto Monitor Started!</b>\n\n"
            "🪙 Monitoring crypto 'Up or Down' and price prediction markets.\n\n"
            "Tracking: BTC, ETH, SOL, XRP, and major altcoins.\n\n"
            "Use /stop to stop the service remotely."
        )

        # Perform initial scan
        await self.initial_scan()

        # Start monitoring loop
        await self.monitoring_loop()

    async def stop(self):
        """Stop the monitoring service gracefully."""
        print("🛑 Stopping Polymarket Crypto Monitor...")
        self.is_running = False

        await self.telegram.send_message("👋 Polymarket Crypto Monitor stopped.")
        await self.telegram.stop()

        print("✅ Monitor stopped successfully")


async def main(polymarket_api_key: str, telegram_token: str,
               telegram_chat_id: Optional[str] = None):
    """Main entry point for the crypto monitor."""
    monitor = PolymarketCryptoMonitor(
        polymarket_api_key=polymarket_api_key,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        check_interval=600  # 10 minutes
    )

    try:
        await monitor.start()
    except KeyboardInterrupt:
        print("\n⚠️ Keyboard interrupt received")
    finally:
        await monitor.stop()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Optional

    if not POLYMARKET_API_KEY or not TELEGRAM_BOT_TOKEN:
        print("❌ Missing required environment variables!")
        print("Please ensure POLYMARKET_API_KEY and TELEGRAM_BOT_TOKEN are set in .env")
        exit(1)

    asyncio.run(main(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
