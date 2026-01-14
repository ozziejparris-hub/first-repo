#!/usr/bin/env python3
"""
Polymarket API Client

Handles all interactions with Polymarket CLOB API:
- Fetch active markets
- Get order book data
- Monitor trader activity
- Track market prices
"""

import requests
import time
import json
from typing import Dict, List, Optional
from datetime import datetime
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[WARN] python-dotenv not installed, using environment variables directly")


class PolymarketClient:
    """Client for Polymarket CLOB API."""

    def __init__(self, config_path: str = "config/paper_trading_config.json"):
        """Initialize client with config."""
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.base_url = self.config['polymarket']['api_base_url']
        self.gamma_url = self.config['polymarket']['gamma_api_url']
        self.api_key = os.getenv('POLYMARKET_API_KEY')

        # Rate limiting
        self.requests_this_minute = 0
        self.minute_start = time.time()
        self.rate_limit = self.config['polymarket']['rate_limit_per_minute']

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'PolymarketPaperTrader/1.0'
        })

        if self.api_key:
            self.session.headers['Authorization'] = f'Bearer {self.api_key}'

    def _rate_limit_check(self):
        """Enforce rate limiting."""
        current_time = time.time()

        # Reset counter every minute
        if current_time - self.minute_start >= 60:
            self.requests_this_minute = 0
            self.minute_start = current_time

        # Wait if at limit
        if self.requests_this_minute >= self.rate_limit:
            wait_time = 60 - (current_time - self.minute_start)
            if wait_time > 0:
                print(f"[RATE LIMIT] Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.requests_this_minute = 0
                self.minute_start = time.time()

        self.requests_this_minute += 1

    def get_active_markets(self, category: str = None, limit: int = 100) -> List[Dict]:
        """
        Fetch active markets from Gamma API.

        Args:
            category: Optional category filter
            limit: Max markets to return

        Returns:
            List of market dictionaries
        """
        self._rate_limit_check()

        endpoint = f"{self.gamma_url}/markets"
        params = {
            'limit': limit,
            'active': 'true',
            'closed': 'false'
        }

        if category:
            params['tag'] = category

        try:
            response = self.session.get(endpoint, params=params, timeout=15)
            response.raise_for_status()

            markets = response.json()

            # Filter for active only
            if isinstance(markets, list):
                active = [m for m in markets if m.get('active', False) and not m.get('closed', True)]
            else:
                active = []

            print(f"[API] Fetched {len(active)} active markets" + (f" in {category}" if category else ""))
            return active

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch markets: {e}")
            return []

    def get_market_by_id(self, market_id: str) -> Optional[Dict]:
        """
        Get a specific market by ID.

        Args:
            market_id: Market identifier (condition_id)

        Returns:
            Market data or None
        """
        self._rate_limit_check()

        endpoint = f"{self.gamma_url}/markets/{market_id}"

        try:
            response = self.session.get(endpoint, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch market {market_id}: {e}")
            return None

    def get_market_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get order book for a market token.

        Args:
            token_id: Token identifier (YES or NO token)

        Returns:
            Order book data or None
        """
        self._rate_limit_check()

        endpoint = f"{self.base_url}/book"
        params = {'token_id': token_id}

        try:
            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch orderbook for {token_id}: {e}")
            return None

    def get_recent_trades(self, market_id: str = None, limit: int = 100) -> List[Dict]:
        """
        Get recent trades for a market or globally.

        Args:
            market_id: Optional market identifier
            limit: Number of trades to fetch

        Returns:
            List of trade dictionaries
        """
        self._rate_limit_check()

        endpoint = f"{self.base_url}/trades"
        params = {'limit': limit}

        if market_id:
            params['market'] = market_id

        try:
            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch trades: {e}")
            return []

    def get_market_price(self, market: Dict) -> Optional[Dict]:
        """
        Get current market prices from market data.

        Args:
            market: Market dictionary with tokens

        Returns:
            Price data or None
        """
        try:
            # Get prices from market data - try multiple field names
            prices = market.get('outcomePrices', market.get('outcomes_prices', []))

            # If prices is a JSON string, parse it
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except json.JSONDecodeError:
                    prices = []

            # Parse individual prices
            def parse_price(p):
                if p is None:
                    return None
                if isinstance(p, (int, float)):
                    return float(p)
                if isinstance(p, str):
                    # Try JSON decode first
                    try:
                        decoded = json.loads(p)
                        if isinstance(decoded, (int, float)):
                            return float(decoded)
                        if isinstance(decoded, list) and len(decoded) > 0:
                            return float(decoded[0])
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
                    # Clean and parse
                    cleaned = p.strip().strip('"\'[]')
                    if cleaned == '' or cleaned is None:
                        return None
                    try:
                        return float(cleaned)
                    except ValueError:
                        return None
                return None

            if len(prices) >= 2:
                yes_price = parse_price(prices[1]) if len(prices) > 1 else None
                no_price = parse_price(prices[0]) if len(prices) > 0 else None

                # If we couldn't parse prices, return None
                if yes_price is None or no_price is None:
                    return None

                return {
                    'yes_price': yes_price,
                    'no_price': no_price,
                    'mid_price': yes_price,  # YES token price is the probability
                    'spread': abs(yes_price + no_price - 1)
                }

            return None

        except (ValueError, TypeError, IndexError) as e:
            print(f"[ERROR] Failed to parse prices: {e}")
            return None

    def get_trader_activity(self, trader_address: str, limit: int = 100) -> List[Dict]:
        """
        Get recent activity for a specific trader.

        Args:
            trader_address: Trader wallet address
            limit: Number of trades to fetch

        Returns:
            List of trade dictionaries
        """
        self._rate_limit_check()

        endpoint = f"{self.base_url}/trades"
        params = {
            'maker': trader_address,
            'limit': limit
        }

        try:
            response = self.session.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch trader activity: {e}")
            return []

    def test_connection(self) -> bool:
        """
        Test API connection.

        Returns:
            True if connected successfully
        """
        try:
            markets = self.get_active_markets(limit=5)
            return len(markets) > 0
        except Exception as e:
            print(f"[ERROR] Connection test failed: {e}")
            return False


def main():
    """Test the client."""
    print("[TEST] Testing Polymarket API Client...")
    print()

    client = PolymarketClient()

    # Test connection
    if client.test_connection():
        print("[OK] Connection successful!")

        # Get some markets
        markets = client.get_active_markets(limit=5)
        print(f"\nSample markets:")
        for m in markets[:3]:
            title = m.get('question', m.get('title', 'Unknown'))[:60]
            print(f"  - {title}...")

            # Get price
            price_data = client.get_market_price(m)
            if price_data:
                print(f"    YES: ${price_data['yes_price']:.3f}, NO: ${price_data['no_price']:.3f}")
    else:
        print("[FAIL] Connection failed!")


if __name__ == '__main__':
    main()
