import requests
from typing import List, Dict, Optional
from datetime import datetime
import time
import json


class PolymarketClient:
    """Client for interacting with Polymarket API."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.base_url = "https://gamma-api.polymarket.com"
        self.clob_url = "https://clob.polymarket.com"
        self.session = requests.Session()

        # Set up headers with multiple authentication formats
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PolymarketTracker/1.0"
        }

        # Add API key in multiple header formats to maximize compatibility
        if api_key:
            headers.update({
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "APIKEY": api_key
            })

        self.session.headers.update(headers)

    def get_markets(self, category: str = "Geopolitics", limit: int = 100) -> List[Dict]:
        """
        Fetch markets from Polymarket and filter by category.

        Since Polymarket markets don't have tags or category fields,
        we use keyword matching on questions, descriptions, and event titles.
        """
        try:
            url = f"{self.base_url}/markets"

            # Use correct Polymarket API parameters
            params = {
                "limit": limit,
                "offset": 0,
                "closed": False,  # Only active markets
                "archived": False  # Exclude archived
            }

            print(f"Fetching markets from: {url}")
            print(f"Params: {params}")

            response = self.session.get(url, params=params, timeout=30)

            print(f"Response status: {response.status_code}")

            # Don't raise for status yet - let's see what we got
            if response.status_code != 200:
                print(f"Error response: {response.text}")
                print(f"Response headers: {dict(response.headers)}")
                return []

            # Handle response data
            data = response.json()

            # Response might be a list or a dict with 'data' key
            if isinstance(data, dict):
                if 'data' in data:
                    markets = data['data']
                elif 'markets' in data:
                    markets = data['markets']
                else:
                    print(f"Unexpected response format. Keys: {data.keys()}")
                    return []
            else:
                markets = data

            print(f"Total markets fetched: {len(markets)}")

            # Filter based on category using keyword matching
            filtered_markets = self._filter_by_category(markets, category)

            print(f"Filtered to {len(filtered_markets)} {category} markets")
            return filtered_markets

        except requests.exceptions.RequestException as e:
            print(f"Request error fetching markets: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error fetching markets: {e}")
            return []

    def _filter_by_category(self, markets: List[Dict], category: str) -> List[Dict]:
        """
        Filter markets by category using keyword matching.

        Since Polymarket doesn't use tags/categories, we match keywords
        in questions, descriptions, and event titles.
        """
        category_lower = category.lower()

        # Define keywords for different categories
        keyword_sets = {
            'geopolitics': [
                'geopolitic', 'war', 'election', 'president', 'prime minister',
                'congress', 'senate', 'parliament', 'government', 'military',
                'ukraine', 'russia', 'china', 'taiwan', 'israel', 'iran',
                'politics', 'political', 'nato', 'treaty', 'sanctions',
                'ambassador', 'diplomat', 'foreign policy', 'invasion',
                'ceasefire', 'peace deal', 'united nations', 'brexit',
                'referendum', 'impeach', 'cabinet', 'minister', 'secretary of',
                'supreme leader', 'dictator', 'regime'
            ],
            'politics': [
                'election', 'president', 'congress', 'senate', 'parliament',
                'government', 'politics', 'political', 'vote', 'ballot',
                'campaign', 'candidate', 'governor', 'mayor', 'legislative'
            ],
            'crypto': [
                'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'blockchain',
                'nft', 'defi', 'token', 'coin', 'satoshi', 'mining'
            ],
            'sports': [
                'nfl', 'nba', 'mlb', 'nhl', 'fifa', 'olympics', 'super bowl',
                'world cup', 'championship', 'playoff', 'finals', 'match',
                'game', 'team', 'player', 'athlete', 'tournament'
            ],
            'finance': [
                'stock', 'market', 'sp500', 's&p', 'dow', 'nasdaq', 'fed',
                'interest rate', 'inflation', 'recession', 'gdp', 'unemployment'
            ]
        }

        # Get keywords for requested category
        keywords = keyword_sets.get(category_lower, [category_lower])

        filtered = []

        for market in markets:
            # Get searchable text fields
            question = str(market.get('question', '')).lower()
            description = str(market.get('description', '')).lower()

            # Check events for category keywords
            events = market.get('events', [])
            event_text = ''
            for event in events:
                event_title = str(event.get('title', '')).lower()
                event_slug = str(event.get('slug', '')).lower()
                event_text += f" {event_title} {event_slug}"

            # Combine all searchable text
            searchable = f"{question} {description} {event_text}"

            # Check if any keyword matches
            if any(keyword in searchable for keyword in keywords):
                filtered.append(market)

        return filtered

    def get_all_markets(self, limit: int = 100) -> List[Dict]:
        """
        Fetch ALL markets without category filtering.
        Useful for debugging and seeing what's available.
        """
        try:
            url = f"{self.base_url}/markets"
            params = {
                "limit": limit,
                "offset": 0,
                "closed": False,
                "archived": False
            }

            response = self.session.get(url, params=params, timeout=30)

            if response.status_code != 200:
                print(f"Error: {response.status_code} - {response.text}")
                return []

            data = response.json()

            if isinstance(data, dict):
                markets = data.get('data', data.get('markets', []))
            else:
                markets = data

            return markets

        except Exception as e:
            print(f"Error fetching all markets: {e}")
            return []

    def get_market_trades(self, market_id: str, limit: int = 100) -> List[Dict]:
        """
        Fetch recent trades for a specific market.

        Note: CLOB API may not accept the same authentication as Gamma API.
        Trying without auth headers first.
        """
        try:
            url = f"{self.clob_url}/trades"
            params = {
                "market": market_id,
                "limit": limit
            }

            # Try without authentication first (CLOB might be public)
            response = requests.get(url, params=params, timeout=30)

            if response.status_code != 200:
                print(f"Error fetching trades for {market_id}: {response.status_code}")
                return []

            data = response.json()

            # Response might be list or dict
            if isinstance(data, dict) and 'data' in data:
                return data['data']
            return data if isinstance(data, list) else []

        except Exception as e:
            print(f"Error fetching trades for market {market_id}: {e}")
            return []

    def get_trader_history(self, trader_address: str, limit: int = 1000) -> List[Dict]:
        """
        Fetch trading history for a specific trader.

        Note: CLOB API likely doesn't require authentication for public trade data.
        """
        try:
            url = f"{self.clob_url}/trades"
            params = {
                "maker": trader_address,
                "limit": limit
            }

            # Try without authentication (CLOB might be public)
            response = requests.get(url, params=params, timeout=30)

            if response.status_code != 200:
                print(f"Error fetching trader history for {trader_address}: {response.status_code}")
                return []

            data = response.json()

            # Response might be list or dict
            if isinstance(data, dict) and 'data' in data:
                return data['data']
            return data if isinstance(data, list) else []

        except Exception as e:
            print(f"Error fetching trader history for {trader_address}: {e}")
            return []

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get detailed information about a specific market."""
        try:
            url = f"{self.base_url}/markets/{market_id}"

            response = self.session.get(url, timeout=30)

            if response.status_code != 200:
                return None

            return response.json()

        except Exception as e:
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

        # Calculate metrics from trade history
        total_trades = len(trades)

        # Calculate total volume
        total_volume = sum(
            float(trade.get('size', 0)) * float(trade.get('price', 0))
            for trade in trades
        )

        # Win rate calculation requires market resolution data
        # This is a placeholder - in production you'd need to:
        # 1. Get all markets the trader participated in
        # 2. Check if those markets are resolved
        # 3. Determine if the trader's position won
        successful_trades = 0

        for trade in trades:
            # TODO: Implement actual win rate calculation
            # This requires checking market resolutions
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
            market_id = market.get('id') or market.get('market_id') or market.get('conditionId')
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

    def test_connection(self) -> bool:
        """
        Test if the API connection is working.
        Returns True if successful, False otherwise.
        """
        try:
            url = f"{self.base_url}/markets"
            params = {"limit": 1}

            response = self.session.get(url, params=params, timeout=10)

            if response.status_code == 200:
                print("✅ API connection successful!")
                return True
            else:
                print(f"❌ API returned status {response.status_code}: {response.text}")
                return False

        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            return False
