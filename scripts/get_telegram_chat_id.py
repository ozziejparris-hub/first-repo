#!/usr/bin/env python3
"""
Helper script to get your Telegram Chat ID.

Run this script, then send a message to your bot on Telegram.
This script will show you your chat ID which you can add to .env
"""

import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

load_dotenv()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and show chat ID."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    print("\n" + "="*70)
    print("✅ GOT YOUR CHAT ID!")
    print("="*70)
    print(f"\nChat ID: {chat_id}")
    print(f"User: {user.first_name} {user.last_name or ''}")
    print(f"Username: @{user.username}" if user.username else "")
    print("\nAdd this to your .env file:")
    print(f"TELEGRAM_CHAT_ID={chat_id}")
    print("="*70 + "\n")

    await update.message.reply_text(
        f"✅ Your Chat ID is: `{chat_id}`\n\n"
        f"Add this to your .env file:\n"
        f"`TELEGRAM_CHAT_ID={chat_id}`\n\n"
        f"Then you can run the main tracker!",
        parse_mode='Markdown'
    )

    # Stop the bot after getting the chat ID
    print("✅ Chat ID captured! You can stop this script now (Ctrl+C)")


async def main():
    """Main function to run the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env file")
        print("\nPlease add your Telegram bot token to .env:")
        print("TELEGRAM_BOT_TOKEN=your_bot_token_here")
        return

    print("="*70)
    print("TELEGRAM CHAT ID FINDER")
    print("="*70)
    print(f"\nBot token loaded: {token[:10]}...{token[-4:]}")
    print("\n📱 Instructions:")
    print("1. Open Telegram")
    print("2. Find your bot (search for its username)")
    print("3. Send ANY message to your bot")
    print("4. Your Chat ID will appear here\n")
    print("⏳ Waiting for message...")
    print("="*70 + "\n")

    # Create application
    app = Application.builder().token(token).build()

    # Add handler for all messages
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Keep running until manually stopped
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Stopping...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Done!")
