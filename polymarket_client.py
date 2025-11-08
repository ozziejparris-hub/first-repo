import requests
from typing import List, Dict, Optional
from datetime import datetime
import time


class PolymarketClient:
    """Client for interacting with Polymarket API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

    def get_markets(self, category: str = "Geopolitics", limit: int = 100) -> List[Dict]:
        """
        Fetch markets from Polymarket.
        Note: Polymarket's API structure may vary. This is a general implementation.
        """
        try:
            # Using the public API endpoint for markets
            url = f"{self.base_url}/markets"
            params = {
                "limit": limit,
                "offset": 0,
                "active": True
            }

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            markets = response.json()

            # Filter for geopolitics category
            # Note: The exact field name might vary based on Polymarket's API
            filtered_markets = []
            for market in markets:
                # Check if market has tags/category related to geopolitics
                tags = market.get('tags', []) or []
                category_field = market.get('category', '').lower()

                if ('geopolitics' in [t.lower() for t in tags] or
                    'geopolitics' in category_field or
                    'politics' in category_field):
                    filtered_markets.append(market)

            return filtered_markets

        except requests.exceptions.RequestException as e:
            print(f"Error fetching markets: {e}")
            return []

    def get_market_trades(self, market_id: str, limit: int = 100) -> List[Dict]:
        """
        Fetch recent trades for a specific market.
        """
        try:
            url = f"{self.clob_url}/trades"
            params = {
                "market": market_id,
                "limit": limit
            }

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Error fetching trades for market {market_id}: {e}")
            return []

    def get_trader_history(self, trader_address: str, limit: int = 1000) -> List[Dict]:
        """
        Fetch trading history for a specific trader.
        This endpoint may require authentication or may not be publicly available.
        """
        try:
            # Note: This endpoint structure is hypothetical and may need adjustment
            # based on actual Polymarket API documentation
            url = f"{self.clob_url}/trades"
            params = {
                "maker": trader_address,
                "limit": limit
            }

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Error fetching trader history for {trader_address}: {e}")
            return []

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get detailed information about a specific market."""
        try:
            url = f"{self.base_url}/markets/{market_id}"

            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Error fetching market details for {market_id}: {e}")
            return None

    def analyze_trader_performance(self, trader_address: str) -> Dict:
        """
        Analyze a trader's performance based on their trade history.
        Returns win rate, total trades, and other metrics.
        """
        trades = self.get_trader_history(trader_address)

        if not trades:
            return {
                'total_trades': 0,
                'successful_trades': 0,
                'win_rate': 0.0,
                'total_volume': 0.0
            }

        # This is a simplified analysis
        # In reality, we'd need to check if markets resolved and if trader was on winning side
        total_trades = len(trades)

        # Calculate total volume
        total_volume = sum(
            float(trade.get('size', 0)) * float(trade.get('price', 0))
            for trade in trades
        )

        # For now, we'll need to implement proper win rate calculation
        # This requires checking market resolutions
        # Placeholder for demonstration
        successful_trades = 0

        for trade in trades:
            # This needs actual market resolution data
            # Placeholder logic
            pass

        win_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0.0

        return {
            'total_trades': total_trades,
            'successful_trades': successful_trades,
            'win_rate': win_rate,
            'total_volume': total_volume
        }

    def get_active_traders_from_markets(self, markets: List[Dict]) -> set:
        """
        Extract unique trader addresses from recent market activity.
        """
        traders = set()

        for market in markets:
            market_id = market.get('id') or market.get('market_id')
            if not market_id:
                continue

            trades = self.get_market_trades(market_id, limit=50)
            time.sleep(0.5)  # Rate limiting

            for trade in trades:
                maker = trade.get('maker')
                taker = trade.get('taker')

                if maker:
                    traders.add(maker)
                if taker:
                    traders.add(taker)

        return traders
