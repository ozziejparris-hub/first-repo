#!/usr/bin/env python3
"""
Count actual monitoring activity from logs.
"""

from datetime import datetime, timedelta
import re

def count_recent_activity(log_file='logs/monitoring.log', hours=1):
    """Count activity from last N hours."""

    cutoff_time = datetime.now() - timedelta(hours=hours)

    telegram_calls = 0
    ollama_calls = 0
    polymarket_calls = 0
    total_lines = 0

    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                # Skip lines without timestamps
                if len(line) < 19:
                    continue

                # Try to parse timestamp
                try:
                    timestamp_str = line[:19]
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                    # Only process recent lines
                    if timestamp < cutoff_time:
                        continue

                    total_lines += 1

                    # Count API calls
                    line_lower = line.lower()

                    if 'telegram.org' in line_lower or 'telegram' in line_lower and 'http' in line_lower:
                        telegram_calls += 1

                    if '11434' in line or 'ollama' in line_lower or 'mistral' in line_lower:
                        ollama_calls += 1

                    if 'polymarket' in line_lower or 'clob' in line_lower:
                        polymarket_calls += 1

                except ValueError:
                    # Not a valid timestamp line
                    continue

    except FileNotFoundError:
        print(f"Log file not found: {log_file}")
        return None

    return {
        'total_lines': total_lines,
        'telegram_calls': telegram_calls,
        'ollama_calls': ollama_calls,
        'polymarket_calls': polymarket_calls,
        'api_calls_total': telegram_calls + ollama_calls + polymarket_calls
    }

if __name__ == '__main__':
    print("=== MONITORING ACTIVITY COUNTER ===\n")

    # Last hour
    activity_1h = count_recent_activity(hours=1)
    if activity_1h:
        print("LAST HOUR:")
        print(f"  Total log lines: {activity_1h['total_lines']}")
        print(f"  Telegram API calls: {activity_1h['telegram_calls']}")
        print(f"  Ollama AI calls: {activity_1h['ollama_calls']}")
        print(f"  Polymarket API calls: {activity_1h['polymarket_calls']}")
        print(f"  Total API calls: {activity_1h['api_calls_total']}")
        print()

    # Last 15 minutes (one monitoring cycle)
    activity_15m = count_recent_activity(hours=0.25)
    if activity_15m:
        print("LAST 15 MINUTES (1 monitoring cycle):")
        print(f"  Total log lines: {activity_15m['total_lines']}")
        print(f"  Telegram API calls: {activity_15m['telegram_calls']}")
        print(f"  Ollama AI calls: {activity_15m['ollama_calls']}")
        print(f"  Polymarket API calls: {activity_15m['polymarket_calls']}")
        print(f"  Total API calls: {activity_15m['api_calls_total']}")
        print()

    # Estimate trades/markets from API calls
    if activity_1h:
        # Each trade notification = 1 Telegram call
        # Each market = ~1-2 Ollama calls for filtering
        # Polymarket calls = fetching trades/markets

        estimated_trades = activity_1h['telegram_calls']
        estimated_markets = activity_1h['ollama_calls']

        print("ESTIMATED ACTIVITY:")
        print(f"  Trade notifications sent: ~{estimated_trades}")
        print(f"  Markets filtered by AI: ~{estimated_markets}")
        print()
