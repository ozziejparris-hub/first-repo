import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from typing import Optional, Callable
from datetime import datetime


class TelegramNotifier:
    """Handle Telegram bot operations for notifications and remote control."""

    def __init__(self, bot_token: str, chat_id: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.application = None
        self.should_stop = False
        self.on_stop_callback: Optional[Callable] = None
        # Rate limiting: track last notification time per trader
        self.last_notification = {}  # trader_address -> timestamp
        self.notification_cooldown = 300  # 5 minutes in seconds

    async def send_message(self, message: str):
        """Send a message to the configured chat, splitting if too long."""
        if not self.chat_id:
            print("⚠️ Chat ID not configured. Cannot send message.")
            return

        # Telegram max message length is 4096 characters
        MAX_LENGTH = 4000  # Leave some margin

        try:
            if len(message) <= MAX_LENGTH:
                # Message is short enough, send as-is
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='HTML'
                )
            else:
                # Split into multiple messages
                parts = []
                current_part = ""

                for line in message.split('\n'):
                    if len(current_part) + len(line) + 1 <= MAX_LENGTH:
                        current_part += line + '\n'
                    else:
                        if current_part:
                            parts.append(current_part)
                        current_part = line + '\n'

                if current_part:
                    parts.append(current_part)

                # Send each part
                for i, part in enumerate(parts, 1):
                    if len(parts) > 1:
                        header = f"[Part {i}/{len(parts)}]\n\n"
                        part = header + part

                    await self.application.bot.send_message(
                        chat_id=self.chat_id,
                        text=part,
                        parse_mode='HTML'
                    )
                    await asyncio.sleep(0.5)  # Small delay between messages

        except Exception as e:
            print(f"Error sending Telegram message: {e}")

    def should_notify_trader(self, trader_address: str) -> bool:
        """Check if enough time has passed since last notification for this trader."""
        now = datetime.now().timestamp()
        last_time = self.last_notification.get(trader_address, 0)

        if now - last_time >= self.notification_cooldown:
            self.last_notification[trader_address] = now
            return True
        return False

    async def send_bundled_trade_alerts(self, trades_by_trader: dict, trader_stats_map: dict):
        """Send bundled trade alerts grouped by trader with rate limiting."""
        for trader_address, trades in trades_by_trader.items():
            # Rate limiting: skip if notified recently
            if not self.should_notify_trader(trader_address):
                print(f"⏭️ Skipping {trader_address[:10]}... (rate limited)")
                continue

            trader_stats = trader_stats_map.get(trader_address)
            if not trader_stats:
                continue

            # Build bundled message
            if len(trades) == 1:
                # Single trade
                trade = trades[0]
                message = (
                    f"🚨 <b>New Trade Alert!</b>\n\n"
                    f"<b>Trader:</b> <code>{trader_address[:16]}...</code>\n"
                    f"<b>Volume:</b> ${trader_stats['total_volume']:.2f} "
                    f"({trader_stats['total_trades']} trades)\n\n"
                    f"<b>Market:</b> {trade['market_title'][:60]}\n"
                    f"<b>Outcome:</b> {trade['outcome']}\n"
                    f"<b>Side:</b> {trade['side'].upper()}\n"
                    f"<b>Shares:</b> {trade['shares']:.2f}\n"
                    f"<b>Price:</b> ${trade['price']:.4f}\n"
                    f"<b>Time:</b> {trade['timestamp']}\n"
                )
            else:
                # Multiple trades - bundle them
                message = (
                    f"🚨 <b>{len(trades)} New Trades!</b>\n\n"
                    f"<b>Trader:</b> <code>{trader_address[:16]}...</code>\n"
                    f"<b>Volume:</b> ${trader_stats['total_volume']:.2f} "
                    f"({trader_stats['total_trades']} trades)\n\n"
                )

                for i, trade in enumerate(trades[:5], 1):  # Max 5 per message
                    message += (
                        f"<b>Trade {i}:</b>\n"
                        f"  Market: {trade['market_title'][:50]}\n"
                        f"  {trade['outcome']} {trade['side'].upper()} "
                        f"{trade['shares']:.1f} @ ${trade['price']:.3f}\n\n"
                    )

                if len(trades) > 5:
                    message += f"<i>...and {len(trades) - 5} more trades</i>\n"

            await self.send_message(message)
            await asyncio.sleep(1)  # Delay between traders

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        # Store chat_id when user first interacts
        if not self.chat_id:
            self.chat_id = str(update.effective_chat.id)
            print(f"Chat ID stored: {self.chat_id}")

        await update.message.reply_text(
            "👋 PredictionDataBoy is active!\n\n"
            "I'm monitoring geopolitical prediction markets on Polymarket.\n\n"
            "Commands:\n"
            "/status - Check system status\n"
            "/traders - View tracked traders\n"
            "/stop - Stop monitoring (remote shutdown)\n"
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        status_msg = (
            "✅ <b>System Status</b>\n\n"
            f"🤖 Bot: Active\n"
            f"📊 Monitoring: Running\n"
            f"🕐 Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        await update.message.reply_text(status_msg, parse_mode='HTML')

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command - remote shutdown."""
        await update.message.reply_text(
            "🛑 Stopping monitoring service...\n"
            "The bot will shut down gracefully."
        )

        self.should_stop = True

        # Call the callback if set
        if self.on_stop_callback:
            self.on_stop_callback()

    async def traders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /traders command - show tracked traders."""
        # This will be populated by the main monitor
        await update.message.reply_text(
            "📊 Use this command to view your tracked traders.\n"
            "(This will be implemented in the monitor)"
        )

    def set_stop_callback(self, callback: Callable):
        """Set a callback function to be called when stop command is received."""
        self.on_stop_callback = callback

    async def initialize(self):
        """Initialize the bot application."""
        self.application = Application.builder().token(self.bot_token).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("traders", self.traders_command))

        # Initialize the application
        await self.application.initialize()
        await self.application.start()

        print("✅ Telegram bot initialized")

    async def start_polling(self):
        """Start polling for updates in the background."""
        if not self.application:
            await self.initialize()

        await self.application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES
        )

    async def stop(self):
        """Stop the bot gracefully."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            print("✅ Telegram bot stopped")

    def check_should_stop(self) -> bool:
        """Check if stop command was received."""
        return self.should_stop
