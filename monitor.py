import asyncio
import time
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
            return

        print(f"Checking trades for {len(flagged_traders)} flagged traders...")

        new_trades_count = 0

        for trader_address in flagged_traders:
            # Get recent trades for this trader
            recent_trades = self.polymarket.get_trader_history(trader_address, limit=10)

            for trade in recent_trades:
                # Extract trade information
                trade_id = trade.get('id') or trade.get('trade_id')
                if not trade_id:
                    continue

                market_id = trade.get('market') or trade.get('market_id')
                outcome = trade.get('outcome', 'Unknown')
                shares = float(trade.get('size', 0))
                price = float(trade.get('price', 0))
                side = trade.get('side', 'unknown')
                timestamp_raw = trade.get('timestamp') or trade.get('created_at')

                # Parse timestamp
                try:
                    if isinstance(timestamp_raw, (int, float)):
                        timestamp = datetime.fromtimestamp(timestamp_raw)
                    else:
                        timestamp = datetime.fromisoformat(str(timestamp_raw).replace('Z', '+00:00'))
                except:
                    timestamp = datetime.now()

                # Get market details
                market_details = self.polymarket.get_market_details(market_id)
                market_title = market_details.get('question', 'Unknown Market') if market_details else 'Unknown Market'

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
                    print(f"📝 New trade detected: {trade_id[:16]}...")

            # Rate limiting
            time.sleep(1)

        print(f"Found {new_trades_count} new trades")
        return new_trades_count

    async def notify_new_trades(self):
        """Send notifications for trades that haven't been notified yet."""
        unnotified_trades = self.db.get_unnotified_trades()

        if not unnotified_trades:
            return

        print(f"Sending {len(unnotified_trades)} trade notifications...")

        for trade in unnotified_trades:
            # Get trader stats
            trader_stats = self.db.get_trader_stats(trade['trader_address'])

            if trader_stats:
                await self.telegram.send_trade_alert(trade, trader_stats)
                self.db.mark_trade_notified(trade['trade_id'])
                await asyncio.sleep(1)  # Rate limiting

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
