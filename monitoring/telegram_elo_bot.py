#!/usr/bin/env python3
"""
Enhanced Telegram Bot with ELO Leaderboard and Elite Trader Alerts

Features:
- Daily leaderboard summaries
- Elite trader trade alerts (top 10)
- Interactive commands (/leaderboard, /rank, /elite, /stats)
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes


class ELOTelegramBot:
    """Enhanced Telegram bot with ELO features."""

    def __init__(self, token: str, chat_id: str, database):
        """
        Initialize ELO Telegram bot.

        Args:
            token: Telegram bot token
            chat_id: Default chat ID for notifications
            database: Database instance
        """
        self.token = token
        self.chat_id = chat_id
        self.db = database
        self.app = None
        self.bot = None

        # Configuration
        self.elite_threshold = 1800  # ELO threshold for elite traders
        self.top_n_elite = 10        # Top N traders for trade alerts

    async def initialize(self):
        """Initialize the bot application."""
        self.app = Application.builder().token(self.token).build()
        self.bot = self.app.bot

        # Register command handlers
        self.app.add_handler(CommandHandler("leaderboard", self.cmd_leaderboard))
        self.app.add_handler(CommandHandler("rank", self.cmd_rank))
        self.app.add_handler(CommandHandler("elite", self.cmd_elite))
        self.app.add_handler(CommandHandler("stats", self.cmd_stats))

        print("[ELO_BOT] Telegram bot initialized with ELO features")

    async def start_polling(self):
        """Start polling for commands."""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        print("[ELO_BOT] Started polling for commands")

    async def stop(self):
        """Stop the bot."""
        if self.app:
            # Only stop updater if it was started
            if self.app.updater and self.app.updater.running:
                await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    # ============================================================
    # DAILY LEADERBOARD
    # ============================================================

    async def send_daily_leaderboard(self, top_n: int = 10):
        """
        Send daily leaderboard summary.

        Args:
            top_n: Number of top traders to show
        """
        try:
            traders = self.db.get_top_traders_by_elo(limit=top_n)

            if not traders:
                await self.send_message("[WARN] No traders with ELO ratings yet")
                return

            # Build message
            message = self._format_daily_leaderboard(traders)

            await self.send_message(message, parse_mode='HTML')

        except Exception as e:
            print(f"[ELO_BOT] Error sending daily leaderboard: {e}")
            import traceback
            traceback.print_exc()

    def _format_daily_leaderboard(self, traders: List[Dict]) -> str:
        """Format daily leaderboard message."""
        date_str = datetime.now().strftime('%B %d, %Y')

        message = f"<b>DAILY LEADERBOARD - {date_str}</b>\n\n"
        message += "<b>TOP 10 TRADERS BY COMPREHENSIVE ELO:</b>\n\n"

        # Medal emojis for top 3 (using Unicode)
        medals = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}  # Gold, Silver, Bronze

        for trader in traders:
            rank = trader['rank']
            medal = medals.get(rank, f"{rank}.")

            addr = trader['address'][:10] + "..."
            elo = trader['comprehensive_elo']
            win_rate = trader['win_rate'] * 100 if trader['win_rate'] < 1 else trader['win_rate']
            pnl = trader['realized_pnl']
            roi = trader['avg_roi'] * 100 if trader['avg_roi'] < 1 else trader['avg_roi']

            message += f"{medal} <b>{addr}</b> - ELO {elo:.0f}\n"
            message += f"   Win Rate: {win_rate:.1f}% | P&L: ${pnl:.2f} | ROI: {roi:.1f}%\n\n"

        # Summary stats
        elite_count = len(self.db.get_elite_traders(self.elite_threshold))
        avg_elo = sum(t['comprehensive_elo'] for t in traders) / len(traders)

        message += f"\nElite traders (>{self.elite_threshold} ELO): {elite_count}\n"
        message += f"Average ELO (top 10): {avg_elo:.1f}\n"

        return message

    # ============================================================
    # ELITE TRADER ALERTS
    # ============================================================

    async def send_elite_trader_alert(self, trader_address: str, trade_data: Dict):
        """
        Send alert when elite trader makes a new trade.

        Args:
            trader_address: Trader's wallet address
            trade_data: Trade information dict
        """
        try:
            # Get trader's rank and stats
            rank_data = self.db.get_trader_rank(trader_address)

            if not rank_data:
                return  # Trader not found

            # Only alert for top N traders
            if rank_data['rank'] > self.top_n_elite:
                return

            message = self._format_elite_trade_alert(rank_data, trade_data)

            await self.send_message(message, parse_mode='HTML')

        except Exception as e:
            print(f"[ELO_BOT] Error sending elite trader alert: {e}")

    def _format_elite_trade_alert(self, rank_data: Dict, trade_data: Dict) -> str:
        """Format elite trader trade alert."""
        message = "<b>ELITE TRADER ALERT</b>\n\n"

        # Trader info
        addr = rank_data['address'][:10] + "..."
        rank = rank_data['rank']
        elo = rank_data['comprehensive_elo']
        win_rate = rank_data['win_rate'] * 100 if rank_data['win_rate'] < 1 else rank_data['win_rate']
        pnl = rank_data['realized_pnl']
        roi = rank_data['avg_roi'] * 100 if rank_data['avg_roi'] < 1 else rank_data['avg_roi']

        message += f"<b>Trader:</b> {addr} (Rank #{rank}, ELO {elo:.0f})\n"
        message += f"Win Rate: {win_rate:.1f}% | P&L: ${pnl:.2f} | ROI: {roi:.1f}%\n\n"

        # Trade info
        market_title = trade_data.get('market_title', 'Unknown')
        outcome = trade_data.get('outcome', 'Unknown')
        shares = trade_data.get('shares', 0)
        price = trade_data.get('price', 0)
        side = trade_data.get('side', 'unknown')

        investment = shares * price

        message += "<b>NEW TRADE:</b>\n"
        message += f"Market: \"{market_title[:60]}...\"\n"
        message += f"Position: <b>{outcome}</b> ({side})\n"
        message += f"Shares: {shares:.0f}\n"
        message += f"Entry Price: ${price:.3f}\n"
        message += f"Investment: ${investment:.2f}\n\n"

        # Timestamp
        timestamp = trade_data.get('timestamp', datetime.now())
        if isinstance(timestamp, str):
            timestamp_str = timestamp
        else:
            timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        message += f"Time: {timestamp_str}\n"

        return message

    # ============================================================
    # BOT COMMANDS
    # ============================================================

    async def cmd_leaderboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /leaderboard command."""
        await update.message.reply_text("Fetching current leaderboard...")

        traders = self.db.get_top_traders_by_elo(limit=10)

        if not traders:
            await update.message.reply_text("[WARN] No traders with ELO ratings yet")
            return

        message = self._format_daily_leaderboard(traders)
        await update.message.reply_text(message, parse_mode='HTML')

    async def cmd_rank(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rank <address> command."""
        if not context.args:
            await update.message.reply_text("Usage: /rank <trader_address>")
            return

        trader_address = context.args[0]
        rank_data = self.db.get_trader_rank(trader_address)

        if not rank_data:
            await update.message.reply_text(f"[ERROR] Trader {trader_address[:10]}... not found")
            return

        addr = rank_data['address'][:10] + "..."
        rank = rank_data['rank']
        elo = rank_data['comprehensive_elo']
        win_rate = rank_data['win_rate'] * 100 if rank_data['win_rate'] < 1 else rank_data['win_rate']
        pnl = rank_data['realized_pnl']

        message = f"<b>Trader Rank Report</b>\n\n"
        message += f"Address: {addr}\n"
        message += f"Rank: #{rank}\n"
        message += f"Comprehensive ELO: {elo:.0f}\n"
        message += f"Win Rate: {win_rate:.1f}%\n"
        message += f"Realized P&L: ${pnl:.2f}\n"

        await update.message.reply_text(message, parse_mode='HTML')

    async def cmd_elite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /elite command."""
        await update.message.reply_text(f"Fetching elite traders (>{self.elite_threshold} ELO)...")

        elite_traders = self.db.get_elite_traders(self.elite_threshold)

        if not elite_traders:
            await update.message.reply_text(f"[WARN] No elite traders (>{self.elite_threshold} ELO) yet")
            return

        message = f"<b>ELITE TRADERS (>{self.elite_threshold} ELO)</b>\n\n"
        message += f"Total: {len(elite_traders)}\n\n"

        for trader in elite_traders[:20]:  # Show top 20
            addr = trader['address'][:10] + "..."
            elo = trader['comprehensive_elo']
            rank = trader['rank']

            message += f"#{rank} {addr} - ELO {elo:.0f}\n"

        if len(elite_traders) > 20:
            message += f"\n... and {len(elite_traders) - 20} more"

        await update.message.reply_text(message, parse_mode='HTML')

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        traders = self.db.get_top_traders_by_elo(limit=1000)
        elite = self.db.get_elite_traders(self.elite_threshold)

        if not traders:
            await update.message.reply_text("[WARN] No trader data yet")
            return

        avg_elo = sum(t['comprehensive_elo'] for t in traders) / len(traders)
        max_elo = max(t['comprehensive_elo'] for t in traders)
        min_elo = min(t['comprehensive_elo'] for t in traders)

        message = "<b>SYSTEM STATISTICS</b>\n\n"
        message += f"Total flagged traders: {len(traders)}\n"
        message += f"Elite traders (>{self.elite_threshold}): {len(elite)}\n\n"
        message += f"Average ELO: {avg_elo:.1f}\n"
        message += f"Highest ELO: {max_elo:.0f}\n"
        message += f"Lowest ELO: {min_elo:.0f}\n"

        await update.message.reply_text(message, parse_mode='HTML')

    # ============================================================
    # UTILITY METHODS
    # ============================================================

    async def send_message(self, text: str, parse_mode: str = None):
        """Send message to default chat."""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
        except Exception as e:
            print(f"[ELO_BOT] Error sending message: {e}")
