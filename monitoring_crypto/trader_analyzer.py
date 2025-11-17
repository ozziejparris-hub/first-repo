from typing import List, Dict
from database import Database
from polymarket_client import PolymarketClient


class TraderAnalyzer:
    """Analyze traders to identify successful ones worth tracking."""

    def __init__(self, db: Database, polymarket: PolymarketClient,
                 min_trades: int = 50, min_volume: float = 10000.0):
        self.db = db
        self.polymarket = polymarket
        self.min_trades = min_trades
        self.min_volume = min_volume  # Minimum $10k traded

    def analyze_and_flag_traders(self, trader_addresses: List[str]) -> int:
        """
        Analyze a list of traders and flag those meeting success criteria.
        Returns the number of newly flagged traders.
        """
        newly_flagged = 0

        for address in trader_addresses:
            # Check if already flagged
            existing = self.db.get_trader_stats(address)
            if existing and existing['is_flagged']:
                continue

            # Analyze trader performance
            print(f"Analyzing trader: {address[:10]}...")
            stats = self.polymarket.analyze_trader_performance(address)

            total_trades = stats['total_trades']
            total_volume = stats['total_volume']
            win_rate = stats['win_rate']  # Keep as 0 for now (placeholder)

            # Flag based on volume AND trade count (not win rate)
            should_flag = (total_trades >= self.min_trades and
                          total_volume >= self.min_volume)

            self.db.add_or_update_trader(
                address=address,
                total_trades=total_trades,
                successful_trades=stats['successful_trades'],
                win_rate=win_rate,  # Store as 0 (placeholder for future)
                total_volume=total_volume,
                is_flagged=should_flag
            )

            if should_flag:
                newly_flagged += 1
                print(f"✅ Flagged trader {address[:10]}... "
                      f"(Volume: ${total_volume:.2f}, Trades: {total_trades})")

        return newly_flagged

    def scan_for_successful_traders(self) -> int:
        """
        Scan geopolitics markets for active traders and identify successful ones.
        Returns the number of newly flagged traders.
        """
        print("Fetching geopolitics markets...")
        markets = self.polymarket.get_markets(category="Geopolitics")
        print(f"Found {len(markets)} geopolitics markets")

        print("Extracting active traders from markets...")
        traders = self.polymarket.get_active_traders_from_markets(markets)
        print(f"Found {len(traders)} unique traders")

        print("Analyzing traders for success criteria...")
        newly_flagged = self.analyze_and_flag_traders(list(traders))

        return newly_flagged

    def get_flagged_traders_summary(self) -> str:
        """Get a formatted summary of all flagged traders."""
        traders = self.db.get_all_flagged_traders_stats()

        if not traders:
            return "No flagged traders yet."

        summary = f"📊 Currently tracking {len(traders)} successful traders:\n\n"

        for i, trader in enumerate(traders, 1):
            summary += (
                f"{i}. Address: {trader['address'][:10]}...\n"
                f"   Win Rate: {trader['win_rate']:.1f}% | "
                f"Trades: {trader['total_trades']} | "
                f"Volume: ${trader['total_volume']:.2f}\n\n"
            )

        return summary
