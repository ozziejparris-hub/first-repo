#!/usr/bin/env python3
"""
Polymarket Trader Tracker
Monitors geopolitical prediction markets and tracks successful traders.
"""

import os
import sys
import asyncio
import requests
import logging
from dotenv import load_dotenv
from pydantic_ai import Agent
from .monitor import main as run_monitor

# Fix Windows console encoding to handle Unicode
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure logging to write to both file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/monitoring.log', encoding='utf-8'),
        logging.StreamHandler()  # Also print to console
    ]
)

logger = logging.getLogger(__name__)

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
        logger.error("[ERROR] Missing required environment variables:")
        for var in missing:
            logger.error(f"   - {var}")
        logger.error("\nPlease check your .env file.")
        return False

    logger.info("[OK] Environment variables loaded successfully.")
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
    logger.info("="*70)
    logger.info("  Polymarket Trader Tracker")
    logger.info("="*70)
    logger.info("")

    # Validate environment
    if not validate_environment():
        return

    # Initialize Pydantic AI agent with comprehensive checks
    logger.info("\nInitializing Pydantic AI agent...")

    # Check if Ollama is running
    if not check_ollama_running():
        logger.warning("[WARNING] Ollama is not running or not accessible.")
        logger.warning("   To use AI features, start Ollama with: ollama serve")
        logger.warning("   Continuing without AI agent (monitoring will still work)...\n")
        agent = None
    # Check if Mistral model is available
    elif not check_mistral_model_available():
        logger.warning("[WARNING] Mistral model not found in Ollama.")
        logger.warning("   To use AI features, download with: ollama pull mistral")
        logger.warning("   Continuing without AI agent (monitoring will still work)...\n")
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

            logger.info(f"\n[OK] AI Agent: {message}\n")

        except AttributeError as e:
            # Debug information for attribute errors
            logger.debug(f"[DEBUG] Response type: {type(response)}")
            logger.debug(f"[DEBUG] Available attributes: {[attr for attr in dir(response) if not attr.startswith('_')]}")
            logger.warning(f"[WARNING] Could not access agent response: {e}")
            logger.warning("Continuing without AI agent (monitoring will still work)...\n")
            agent = None

        except Exception as e:
            logger.warning(f"[WARNING] Could not connect to Ollama Mistral model: {e}")
            logger.warning("Continuing without AI agent (monitoring will still work)...\n")
            agent = None

    # Start the monitoring service
    logger.info("Starting monitoring service...")
    logger.info(f"Target: Geopolitical markets on Polymarket")
    logger.info(f"Criteria: Min $10k volume, Min 50 trades")
    logger.info(f"Check interval: Every 15 minutes")
    logger.info(f"Telegram: Bundled notifications with 5min rate limit")
    if agent:
        logger.info(f"AI Agent: Enabled (Mistral via Ollama)")
        logger.info(f"AI Filtering: Hybrid mode (keywords + AI for ambiguous cases)")
    else:
        logger.info(f"AI Agent: Disabled (keywords only)")
    logger.info("")

    try:
        await run_monitor(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ai_agent=agent)
    except KeyboardInterrupt:
        logger.info("\n\n[SHUTDOWN] Received shutdown signal...")
    except Exception as e:
        logger.error(f"\n\n[ERROR] Fatal error: {e}")
    finally:
        logger.info("\nShutting down gracefully...")


def main():
    """Main entry point."""
    logger.info("Monitoring system starting...")
    try:
        asyncio.run(start_monitoring())
    except KeyboardInterrupt:
        logger.info("\n\n[OK] Shutdown complete.")


if __name__ == "__main__":
    main()
