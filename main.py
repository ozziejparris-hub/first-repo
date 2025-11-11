#!/usr/bin/env python3
"""
Polymarket Trader Tracker
Monitors geopolitical prediction markets and tracks successful traders.
"""

import os
import asyncio
from dotenv import load_dotenv
from pydantic_ai import Agent
from monitor import main as run_monitor

# Load environment variables from .env
load_dotenv()

# Get API keys from environment
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Optional

# Set environment variables for Ollama (local Mistral model)
os.environ["OPENAI_API_KEY"] = "not-needed"  # Dummy value for Ollama
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"


def validate_environment():
    """Validate that all required environment variables are set."""
    missing = []

    if not POLYMARKET_API_KEY:
        missing.append("POLYMARKET_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if missing:
        print("❌ Missing required environment variables:")
        for var in missing:
            print(f"   - {var}")
        print("\nPlease check your .env file.")
        return False

    print("✅ Environment variables loaded successfully.")
    return True


def initialize_pydantic_agent():
    """Initialize the Pydantic AI agent with Mistral via Ollama."""
    agent = Agent(
        "openai:mistral:latest",
        system_prompt=(
            "You are PredictionDataBoy, an AI assistant that monitors Polymarket "
            "prediction markets. You track successful traders in geopolitical markets "
            "and notify users when these traders make new bets. You have access to "
            "the Polymarket API and can send Telegram notifications."
        ),
    )

    return agent


async def start_monitoring():
    """Start the monitoring service."""
    print("="*70)
    print("  🎯 Polymarket Trader Tracker")
    print("="*70)
    print()

    # Validate environment
    if not validate_environment():
        return

    # Initialize Pydantic AI agent
    print("\n🤖 Initializing Pydantic AI agent...")
    agent = initialize_pydantic_agent()

    # Test agent connection
    try:
        response = await agent.run(
            "Introduce yourself briefly and confirm you're ready to monitor Polymarket."
        )
        print(f"\n{response.data}\n")
    except Exception as e:
        print(f"⚠️ Warning: Could not connect to Ollama Mistral model: {e}")
        print("Continuing without AI agent (monitoring will still work)...\n")

    # Start the monitoring service
    print("🚀 Starting monitoring service...")
    print(f"📊 Target: Geopolitical markets on Polymarket")
    print(f"🎯 Criteria: Min $5k volume, Min 20 trades")
    print(f"⏰ Check interval: Every 15 minutes")
    print(f"💬 Telegram: Notifications enabled")
    print()

    try:
        await run_monitor(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    except KeyboardInterrupt:
        print("\n\n⚠️ Received shutdown signal...")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
    finally:
        print("\n👋 Shutting down gracefully...")


def main():
    """Main entry point."""
    try:
        asyncio.run(start_monitoring())
    except KeyboardInterrupt:
        print("\n\n✅ Shutdown complete.")


if __name__ == "__main__":
    main()
