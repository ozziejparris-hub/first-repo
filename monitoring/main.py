#!/usr/bin/env python3
"""
Polymarket Trader Tracker
Monitors geopolitical prediction markets and tracks successful traders.
"""

import os
import asyncio
import requests
from dotenv import load_dotenv
from pydantic_ai import Agent
from monitor import main as run_monitor

# Load environment variables from .env (in parent directory)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

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


def check_ollama_running():
    """Check if Ollama is running and accessible."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def check_mistral_model_available():
    """Check if Mistral model is downloaded in Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return any('mistral' in m.get('name', '').lower() for m in models)
        return False
    except Exception:
        return False


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

    # Initialize Pydantic AI agent with comprehensive checks
    print("\n🤖 Initializing Pydantic AI agent...")

    # Check if Ollama is running
    if not check_ollama_running():
        print("⚠️ Ollama is not running or not accessible.")
        print("   To use AI features, start Ollama with: ollama serve")
        print("   Continuing without AI agent (monitoring will still work)...\n")
        agent = None
    # Check if Mistral model is available
    elif not check_mistral_model_available():
        print("⚠️ Mistral model not found in Ollama.")
        print("   To use AI features, download with: ollama pull mistral")
        print("   Continuing without AI agent (monitoring will still work)...\n")
        agent = None
    else:
        # Initialize agent
        agent = initialize_pydantic_agent()

        # Test agent connection with robust error handling
        try:
            response = await agent.run(
                "Introduce yourself briefly and confirm you're ready to monitor Polymarket."
            )

            # Try multiple ways to access the response data
            message = None
            if hasattr(response, 'data'):
                message = response.data
            elif hasattr(response, 'output'):
                message = response.output
            elif hasattr(response, 'text'):
                message = response.text
            elif hasattr(response, 'result'):
                message = response.result
            else:
                # Fallback: try string conversion
                message = str(response)

            print(f"\n✅ AI Agent: {message}\n")

        except AttributeError as e:
            # Debug information for attribute errors
            print(f"[DEBUG] Response type: {type(response)}")
            print(f"[DEBUG] Available attributes: {[attr for attr in dir(response) if not attr.startswith('_')]}")
            print(f"⚠️ Warning: Could not access agent response: {e}")
            print("Continuing without AI agent (monitoring will still work)...\n")
            agent = None

        except Exception as e:
            print(f"⚠️ Warning: Could not connect to Ollama Mistral model: {e}")
            print("Continuing without AI agent (monitoring will still work)...\n")
            agent = None

    # Start the monitoring service
    print("🚀 Starting monitoring service...")
    print(f"📊 Target: Geopolitical markets on Polymarket")
    print(f"🎯 Criteria: Min $10k volume, Min 50 trades")
    print(f"⏰ Check interval: Every 15 minutes")
    print(f"💬 Telegram: Bundled notifications with 5min rate limit")
    if agent:
        print(f"🤖 AI Agent: Enabled (Mistral via Ollama)")
    else:
        print(f"🤖 AI Agent: Disabled")
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
