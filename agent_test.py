import os
from dotenv import load_dotenv
from pydantic_ai import Agent

# Load environment variables from .env
load_dotenv()

# Get keys from .env
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Set environment variables for Ollama (local model)
os.environ["OPENAI_API_KEY"] = "not-needed"  # Dummy value for Ollama
os.environ["OPENAI_BASE_URL"] = "http://localhost:11434/v1"

# Create the agent using local Ollama Mistral
agent = Agent(
    "openai:mistral:latest",
    system_prompt=(
        "You are a helpful assistant that connects to Polymarket and Telegram. "
        "You have access to environment variables for API keys and can use them "
        "to authenticate when needed."
    ),
)

# Run a quick test query (basic functionality)
response = agent.run_sync("Say hello in a friendly way!")

print("Agent response:", response.output)

# Optional sanity check for API keys (won’t print full keys)
if POLYMARKET_API_KEY and TELEGRAM_BOT_TOKEN:
    print("✅ Environment variables loaded successfully.")
else:
    print("⚠️ Missing one or more environment variables. Check your .env file.")
