#!/usr/bin/env python3
"""
Paper Trading Bot

Main loop that:
1. Fetches active markets
2. Generates signals from top ELO traders
3. Executes paper trades
4. Monitors positions
5. Logs performance
"""

import sys
import time
import signal as sig
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database
from paper_trading.polymarket_client import PolymarketClient
from paper_trading.signal_generator import SignalGenerator
from paper_trading.portfolio_manager import PortfolioManager


class PaperTradingBot:
    """Main paper trading bot."""

    def __init__(self):
        """Initialize bot."""
        print("=" * 70)
        print("  PAPER TRADING BOT - INITIALIZING")
        print("=" * 70)
        print()

        self.db = Database()
        print("[OK] Database connected")

        self.client = PolymarketClient()
        print("[OK] Polymarket client initialized")

        self.signals = SignalGenerator(self.client.config, self.db)
        print("[OK] Signal generator initialized")

        self.portfolio = PortfolioManager()
        print("[OK] Portfolio manager initialized")

        self.running = True
        self.iteration = 0

        # Set up graceful shutdown
        sig.signal(sig.SIGINT, self.shutdown)
        sig.signal(sig.SIGTERM, self.shutdown)

        print()

    def shutdown(self, signum, frame):
        """Handle shutdown signal."""
        print("\n[SHUTDOWN] Stopping paper trading bot...")
        self.running = False

    def log_iteration(self, message: str):
        """Log iteration message with timestamp."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message}")

    def run_once(self) -> bool:
        """
        Run a single iteration of the trading loop.

        Returns:
            True if successful, False otherwise
        """
        self.iteration += 1

        print(f"\n{'='*70}")
        print(f"  ITERATION {self.iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")

        try:
            # 1. Fetch active markets
            print("[1/4] Fetching active markets...")
            categories = self.client.config['monitoring']['categories']
            all_markets = []

            for cat in categories:
                try:
                    markets = self.client.get_active_markets(category=cat, limit=50)
                    all_markets.extend(markets)
                    time.sleep(0.5)  # Small delay between requests
                except Exception as e:
                    print(f"      [WARN] Failed to fetch {cat}: {e}")

            print(f"      Found {len(all_markets)} active markets\n")

            if not all_markets:
                print("      [WARN] No markets found, using database markets")
                # Fall back to database signals
                signals = self.signals.get_all_market_signals()
            else:
                # 2. Generate signals
                print("[2/4] Generating trade signals...")
                signals = self.signals.generate_signals(all_markets)

            if signals:
                print(f"\n      Top 3 Signals:")
                for i, s in enumerate(signals[:3], 1):
                    print(f"      {i}. {s['signal']} - {s['market_title'][:55]}...")
                    print(f"         Confidence: {s['confidence']:.1%}, Traders: {s['num_traders']}")
            print()

            # 3. Execute trades
            print("[3/4] Executing paper trades...")
            trades_executed = 0

            for s in signals[:5]:  # Top 5 signals only
                # Check if we can trade this market
                if self.portfolio.check_existing_position(s['market_id']):
                    continue

                # Get current price (use consensus probability as proxy)
                current_price = s.get('consensus_prob', 0.5)

                # Ensure price is reasonable
                if 0.05 <= current_price <= 0.95:
                    position = self.portfolio.open_position(s, current_price)
                    if position:
                        trades_executed += 1

            print(f"      Executed {trades_executed} trades\n")

            # 4. Monitor positions
            print("[4/4] Monitoring open positions...")
            positions_checked = 0

            for pos in list(self.portfolio.positions):
                # For paper trading, use simulated price movement
                # In live trading, this would fetch real prices
                entry_price = pos['avg_price']

                # Simulate small random price movement for now
                import random
                price_change = random.gauss(0, 0.02)  # 2% standard deviation
                current_price = entry_price * (1 + price_change)
                current_price = max(0.01, min(0.99, current_price))

                # Check stop loss / take profit
                action = self.portfolio.check_stop_loss_take_profit(pos, current_price)
                if action:
                    self.portfolio.close_position(pos, current_price, action)

                positions_checked += 1

            print(f"      Monitored {positions_checked} positions\n")

            # Show performance
            self.portfolio.print_summary()

            return True

        except Exception as e:
            print(f"[ERROR] Iteration failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def run(self, max_iterations: int = None):
        """
        Main trading loop.

        Args:
            max_iterations: Optional max iterations (for testing)
        """
        print("=" * 70)
        print("  PAPER TRADING BOT STARTED")
        print("=" * 70)
        print()

        # Show initial portfolio
        self.portfolio.print_summary()

        while self.running:
            success = self.run_once()

            # Check iteration limit
            if max_iterations and self.iteration >= max_iterations:
                print(f"\n[INFO] Reached max iterations ({max_iterations})")
                break

            # Wait before next iteration
            if self.running:
                wait_time = self.client.config['monitoring']['check_interval_seconds']
                print(f"\nWaiting {wait_time}s until next check (Ctrl+C to stop)...")

                # Use smaller sleep intervals for responsiveness
                for _ in range(int(wait_time)):
                    if not self.running:
                        break
                    time.sleep(1)

        print("\n" + "=" * 70)
        print("  PAPER TRADING BOT STOPPED")
        print("=" * 70)

        # Final summary
        self.portfolio.print_summary()

        # Save final state
        self.portfolio.save_portfolio()


def main():
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description='Paper Trading Bot')
    parser.add_argument('--iterations', '-n', type=int, default=None,
                       help='Max iterations (default: unlimited)')
    parser.add_argument('--test', action='store_true',
                       help='Run single iteration for testing')

    args = parser.parse_args()

    bot = PaperTradingBot()

    if args.test:
        print("\n[TEST MODE] Running single iteration...\n")
        bot.run_once()
    else:
        bot.run(max_iterations=args.iterations)


if __name__ == '__main__':
    main()
