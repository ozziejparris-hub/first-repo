import asyncio
import time
import re
from datetime import datetime
from typing import Optional
from database import Database
from polymarket_client import PolymarketClient
from telegram_bot import TelegramNotifier
from trader_analyzer import TraderAnalyzer


class PolymarketMonitor:
    """Main monitoring service that coordinates all components."""

    def __init__(self, polymarket_api_key: str, telegram_token: str,
                 telegram_chat_id: Optional[str] = None,
                 check_interval: int = 900):  # 900 seconds = 15 minutes
        self.db = Database()
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

    def _should_exclude_market(self, market_title: str) -> bool:
        """
        Check if a market should be excluded - REFINED VERSION (v2).

        CRITICAL EXCLUSIONS (main noise sources):
        1. ⚡ Team vs Team: " vs. " or " vs " (unless military)
        2. ⚡ Draw betting: "end in a draw"
        3. ⚡ Sports betting: "Total Sets:", "O/U", "Spread:"
        4. ⚡ Price predictions: crypto/stock prices (not policy)
        5. Entertainment: MrBeast, YouTube views
        6. Gaming tournaments

        Returns True if market should be EXCLUDED.
        """
        title = market_title
        title_lower = market_title.lower()

        # ===== ⚡ CRITICAL PATTERN 1: TEAM VS TEAM =====
        # Catches ~50% of sports notifications
        if ' vs. ' in title or ' vs ' in title_lower:
            military_keywords = ['military', 'clash', 'engagement', 'war', 'conflict',
                               'ceasefire', 'invasion', 'battle', 'strike', 'attack']
            if not any(keyword in title_lower for keyword in military_keywords):
                return True  # EXCLUDE: Sports match

        # ===== ⚡ CRITICAL PATTERN 2: DRAW BETTING =====
        if 'end in a draw' in title_lower:
            return True  # EXCLUDE: Soccer draw betting

        # ===== ⚡ CRITICAL PATTERN 3: SPORTS BETTING TERMS =====
        if any(term in title_lower for term in ['total sets:', 'o/u ', 'spread:', 'over/under']):
            return True  # EXCLUDE: Sports betting

        # ===== ⚡ CRITICAL PATTERN 4: PRICE PREDICTIONS =====
        asset_names = [
            'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'xrp', 'bnb',
            'cardano', 'ada', 'doge', 'dogecoin', 'gold', 'silver', 'oil',
            'aapl', 'apple', 'msft', 'microsoft', 'tsla', 'tesla',
            'googl', 'google', 'amzn', 'amazon', 'meta', 'nvidia'
        ]

        price_indicators = [
            'finish week', 'be between $', 'hit $', 'reach $',
            'close above $', 'close below $', 'close between $',
            'all time high', 'price of', 'ath ', 'above $', 'below $',
            'trade above', 'trade below'
        ]

        has_asset = any(asset in title_lower for asset in asset_names)
        has_price = any(indicator in title_lower for indicator in price_indicators)

        if has_asset and has_price:
            # EXCEPTION: Keep Fed/central bank policy
            policy_keywords = ['fed ', 'ecb ', 'bank of japan', 'interest rate',
                             'federal reserve', 'central bank', 'bps', 'basis points']
            if not any(keyword in title_lower for keyword in policy_keywords):
                return True  # EXCLUDE: Price prediction

        # ===== PATTERN 5: ENTERTAINMENT =====
        if any(keyword in title_lower for keyword in ['mrbeast', 'video get', 'youtube views', 'million views']):
            return True  # EXCLUDE: Entertainment

        # ===== PATTERN 6: GAMING TOURNAMENTS =====
        if 'cup' in title_lower and any(k in title_lower for k in ['uniswap', 'gaming', 'esports']):
            return True  # EXCLUDE: Gaming tournament

        # ===== PATTERN 7: INTERNATIONAL SPORTS MATCHES =====
        sports_match_pattern = r'will\s+[\w\s]+\s+win\s+on\s+\d{4}-\d{2}-\d{2}'
        if re.search(sports_match_pattern, title_lower):
            geopolitics_context = ['war', 'conflict', 'election', 'invasion', 'battle']
            if not any(word in title_lower for word in geopolitics_context):
                return True  # EXCLUDE: Sports match

        # ===== PATTERN 8: ESPORTS =====
        esports_keywords = ['counter-strike', 'valorant', 'league of legends', 'dota', '(bo1)', '(bo3)']
        if any(keyword in title_lower for keyword in esports_keywords):
            if any(ind in title_lower for ind in [' vs ', '(bo']):
                return True  # EXCLUDE: Esports

        # ===== PATTERN 9: OBVIOUS SPORTS TEAMS =====
        sports_teams = ['penguins', 'predators', 'thunder', 'hornets', 'nets', 'magic',
                       'clippers', 'mavericks', 'warriors', 'lakers', 'celtics']
        if any(team in title_lower for team in sports_teams):
            if any(ind in title_lower for ind in [' vs ', 'win on ', 'beat ']):
                return True  # EXCLUDE: Sports game

        # ===== PATTERN 10: TRADITIONAL SPORTS =====
        traditional_sports = ['nfl', 'nba', 'mlb', 'nhl', 'super bowl', 'stanley cup',
                            'playoff', 'championship', 'cowboys', 'patriots', 'yankees']
        if any(keyword in title_lower for keyword in traditional_sports):
            return True  # EXCLUDE: Sports

        # ===== PATTERN 11: ENTERTAINMENT/CELEBRITY =====
        celebrity_keywords = ['elon musk', 'taylor swift', 'oscar', 'grammy',
                            'movie', 'album', 'tweet', 'x post', 'tiktok']
        if any(keyword in title_lower for keyword in celebrity_keywords):
            return True  # EXCLUDE: Entertainment

        # ===== PATTERN 12: STOCK MARKET (keep policy) =====
        stock_keywords = ['s&p 500', 'sp500', 'dow jones', 'nasdaq', 'stock market']
        policy_context = ['fed', 'ecb', 'interest rate', 'central bank']
        has_policy = any(word in title_lower for word in policy_context)

        if not has_policy and any(keyword in title_lower for keyword in stock_keywords):
            return True  # EXCLUDE: Stock market

        return False  # PASS: Keep this market

    async def initial_scan(self):
        """Perform initial scan to identify successful traders."""
        print("🔍 Starting initial scan for successful traders...")
        await self.telegram.send_message("🔍 Starting initial trader scan...")

        newly_flagged = self.analyzer.scan_for_successful_traders()

        summary = self.analyzer.get_flagged_traders_summary()
        await self.telegram.send_message(
            f"✅ Initial scan complete!\n\n"
            f"Found {newly_flagged} new successful traders.\n\n"
            f"{summary}"
        )

        print(f"✅ Initial scan complete. Flagged {newly_flagged} traders.")

    def check_for_new_trades(self):
        """Check for new trades from flagged traders."""
        flagged_traders = self.db.get_flagged_traders()

        if not flagged_traders:
            print("No flagged traders to monitor yet.")
            return 0

        print(f"Monitoring {len(flagged_traders)} flagged traders...")

        # Strategy: Fetch all recent trades and filter for our flagged traders
        # This is more efficient than calling get_trader_history() for each trader
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

            # CHECK: Skip trades from excluded markets (crypto/sports/entertainment)
            if self._should_exclude_market(market_title):
                excluded_count += 1
                continue

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
                market_category='Geopolitics',
                outcome=outcome,
                shares=shares,
                price=price,
                side=side,
                timestamp=timestamp
            )

            if is_new:
                new_trades_count += 1
                print(f"📝 NEW: {trader_address[:10]}... traded {shares:.1f} @ ${price:.3f} in {market_title[:30]}...")
            else:
                duplicate_count += 1

        print(f"✅ New trades: {new_trades_count} | Already seen: {duplicate_count} | Excluded (crypto/sports): {excluded_count}")
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
            print(f"Monitoring Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
                            f"🆕 Found {newly_flagged} new successful traders!"
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
        """Start the monitoring service."""
        print("🚀 Starting Polymarket Monitor...")
        self.is_running = True

        # Initialize Telegram bot
        await self.telegram.initialize()
        await self.telegram.start_polling()

        # Send startup message
        await self.telegram.send_message(
            "🚀 <b>Polymarket Monitor Started!</b>\n\n"
            "Monitoring geopolitical markets for successful trader activity.\n\n"
            "Use /stop to stop the service remotely."
        )

        # Perform initial scan
        await self.initial_scan()

        # Start monitoring loop
        await self.monitoring_loop()

    async def stop(self):
        """Stop the monitoring service gracefully."""
        print("🛑 Stopping Polymarket Monitor...")
        self.is_running = False

        await self.telegram.send_message("👋 Polymarket Monitor stopped.")
        await self.telegram.stop()

        print("✅ Monitor stopped successfully")


async def main(polymarket_api_key: str, telegram_token: str,
               telegram_chat_id: Optional[str] = None):
    """Main entry point for the monitor."""
    monitor = PolymarketMonitor(
        polymarket_api_key=polymarket_api_key,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        check_interval=900  # 15 minutes
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
