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

    async def send_message(self, message: str):
        """Send a message to the configured chat."""
        if not self.chat_id:
            print("⚠️ Chat ID not configured. Cannot send message.")
            return

        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Error sending Telegram message: {e}")

    async def send_trade_alert(self, trade: dict, trader_stats: dict):
        """Send a formatted alert for a new trade from a flagged trader."""
        message = (
            f"🚨 <b>New Trade Alert!</b>\n\n"
            f"<b>Trader:</b> <code>{trade['trader_address'][:16]}...</code>\n"
            f"<b>Win Rate:</b> {trader_stats['win_rate']:.1f}% "
            f"({trader_stats['successful_trades']}/{trader_stats['total_trades']} trades)\n\n"
            f"<b>Market:</b> {trade['market_title']}\n"
            f"<b>Outcome:</b> {trade['outcome']}\n"
            f"<b>Side:</b> {trade['side'].upper()}\n"
            f"<b>Shares:</b> {trade['shares']:.2f}\n"
            f"<b>Price:</b> ${trade['price']:.4f}\n"
            f"<b>Time:</b> {trade['timestamp']}\n"
        )

        await self.send_message(message)

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
