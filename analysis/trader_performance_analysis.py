#!/usr/bin/env python3
"""
Trader Performance Analysis Script

Analyzes trader performance by calculating:
- Win rate based on resolved markets
- ROI (Return on Investment)
- Combined performance score

Reads from polymarket_tracker.db without modifying it.
"""

import sqlite3
import requests
import csv
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import time


class TraderPerformanceAnalyzer:
    """Analyzes trader performance based on actual market resolutions."""

    def __init__(self, db_path: str = "polymarket_tracker.db", api_key: Optional[str] = None):
        self.db_path = db_path
        self.api_key = api_key
        self.base_url = "https://gamma-api.polymarket.com"
        self.session = requests.Session()

        # Set up headers
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PolymarketTracker/1.0"
        }

        if api_key:
            headers.update({
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "APIKEY": api_key
            })

        self.session.headers.update(headers)

        # Cache for market resolutions
        self.market_resolutions = {}

    def get_db_connection(self):
        """Get read-only database connection."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_trades(self, days_filter: Optional[int] = None) -> List[Dict]:
        """
        Get all trades from database.

        Args:
            days_filter: If specified, only get trades from last N days
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        if days_filter:
            cutoff_date = datetime.now() - timedelta(days=days_filter)
            cursor.execute("""
                SELECT * FROM trades
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """, (cutoff_date,))
        else:
            cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return trades

    def get_market_resolution(self, market_id: str) -> Optional[Dict]:
        """
        Get market resolution status from Polymarket API.

        Returns dict with:
        - resolved: bool
        - winning_outcome: str (if resolved)
        - resolution_date: datetime (if resolved)
        """
        # Check cache first
        if market_id in self.market_resolutions:
            return self.market_resolutions[market_id]

        try:
            # Try to get market details
            url = f"{self.base_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                # Market not found or API error - assume not resolved
                result = {"resolved": False}
                self.market_resolutions[market_id] = result
                return result

            data = response.json()

            # Check if market is closed/resolved
            closed = data.get('closed', False)
            archived = data.get('archived', False)

            if not (closed or archived):
                result = {"resolved": False}
                self.market_resolutions[market_id] = result
                return result

            # Market is closed - try to determine winner
            # Polymarket uses 'markets' with outcomes, winning outcome has payoutNumerator
            outcomes = data.get('outcomes', [])
            events = data.get('events', [])

            winning_outcome = None

            # Method 1: Check outcomes array
            for outcome in outcomes:
                # If this outcome paid out (payoutNumerator = 1000), it won
                if outcome.get('payoutNumerator') == 1000:
                    winning_outcome = outcome.get('name', '').lower()
                    break

            # Method 2: Check market status
            if not winning_outcome and data.get('status') == 'resolved':
                # Try to infer from description or events
                for event in events:
                    if event.get('resolved'):
                        winning_outcome = event.get('winningOutcome', '').lower()
                        break

            result = {
                "resolved": True,
                "winning_outcome": winning_outcome,
                "resolution_date": data.get('endDate') or data.get('resolvedAt')
            }

            self.market_resolutions[market_id] = result
            return result

        except Exception as e:
            print(f"Error fetching market {market_id}: {e}")
            result = {"resolved": False}
            self.market_resolutions[market_id] = result
            return result

    def calculate_trade_pnl(self, trade: Dict, market_resolution: Dict) -> Optional[float]:
        """
        Calculate profit/loss for a single trade.

        Returns:
            float: Profit (positive) or loss (negative) in dollars
            None: If market not resolved or can't determine
        """
        if not market_resolution.get('resolved'):
            return None

        winning_outcome = market_resolution.get('winning_outcome')
        if not winning_outcome:
            return None

        # Extract trade details
        trade_outcome = str(trade.get('outcome', '')).lower()
        trade_side = str(trade.get('side', '')).lower()
        shares = float(trade.get('shares', 0))
        price = float(trade.get('price', 0))

        # Amount invested
        invested = shares * price

        # Determine if this trade won
        # In Polymarket: buying means you think outcome will happen
        # If you bought "Yes" and Yes won, you profit
        # If you bought "No" and No won, you profit

        trader_won = False

        if trade_side == 'buy':
            # Trader bought this outcome, wins if this outcome won
            trader_won = (trade_outcome == winning_outcome)
        elif trade_side == 'sell':
            # Trader sold/shorted this outcome, wins if this outcome lost
            trader_won = (trade_outcome != winning_outcome)

        if trader_won:
            # Winning trades pay out shares * $1.00
            # Profit = payout - invested
            payout = shares * 1.0
            profit = payout - invested
            return profit
        else:
            # Losing trades: lose the amount invested
            return -invested

    def analyze_trader_performance(self, days_filter: Optional[int] = None) -> Dict:
        """
        Analyze all traders and calculate performance metrics.

        Returns dict with trader_address as key and metrics as value.
        """
        print(f"\n{'='*70}")
        print(f"TRADER PERFORMANCE ANALYSIS")
        if days_filter:
            print(f"Analyzing last {days_filter} days")
        else:
            print(f"Analyzing all time")
        print(f"{'='*70}\n")

        # Get all trades
        print("📊 Loading trades from database...")
        trades = self.get_all_trades(days_filter)
        print(f"Found {len(trades)} total trades")

        # Group trades by trader
        trader_trades = defaultdict(list)
        for trade in trades:
            trader_trades[trade['trader_address']].append(trade)

        print(f"Analyzing {len(trader_trades)} unique traders...\n")

        # Get unique markets
        unique_markets = set(trade['market_id'] for trade in trades if trade.get('market_id'))
        print(f"Checking resolution status for {len(unique_markets)} markets...")

        # Fetch market resolutions with progress
        for i, market_id in enumerate(unique_markets, 1):
            if i % 10 == 0 or i == len(unique_markets):
                print(f"Progress: {i}/{len(unique_markets)} markets checked", end='\r')
            self.get_market_resolution(market_id)
            time.sleep(0.1)  # Rate limiting

        print(f"\nProgress: {len(unique_markets)}/{len(unique_markets)} markets checked ✓")

        # Count resolved markets
        resolved_count = sum(1 for res in self.market_resolutions.values() if res.get('resolved'))
        print(f"Found {resolved_count} resolved markets ({resolved_count/len(unique_markets)*100:.1f}%)\n")

        # Analyze each trader
        trader_metrics = {}

        print("Analyzing trader performance...")
        for idx, (trader_address, trades_list) in enumerate(trader_trades.items(), 1):
            if idx % 50 == 0 or idx == len(trader_trades):
                print(f"Progress: {idx}/{len(trader_trades)} traders analyzed", end='\r')

            total_trades = len(trades_list)
            resolved_trades = 0
            winning_trades = 0
            total_pnl = 0.0
            total_invested = 0.0

            for trade in trades_list:
                market_id = trade.get('market_id')
                if not market_id:
                    continue

                resolution = self.market_resolutions.get(market_id)
                if not resolution or not resolution.get('resolved'):
                    continue

                resolved_trades += 1

                # Calculate P&L
                pnl = self.calculate_trade_pnl(trade, resolution)
                if pnl is not None:
                    total_pnl += pnl

                    # Track investment
                    shares = float(trade.get('shares', 0))
                    price = float(trade.get('price', 0))
                    invested = shares * price
                    total_invested += invested

                    # Count wins
                    if pnl > 0:
                        winning_trades += 1

            # Calculate metrics
            win_rate = (winning_trades / resolved_trades * 100) if resolved_trades > 0 else 0.0
            roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

            # Calculate total volume from all trades
            total_volume = sum(
                float(t.get('shares', 0)) * float(t.get('price', 0))
                for t in trades_list
            )

            trader_metrics[trader_address] = {
                'trader_address': trader_address,
                'total_trades': total_trades,
                'resolved_trades': resolved_trades,
                'winning_trades': winning_trades,
                'losing_trades': resolved_trades - winning_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'total_invested': total_invested,
                'total_volume': total_volume,
                'roi': roi,
                'combined_score': (win_rate * 0.5 + roi * 0.5) if resolved_trades >= 5 else 0.0
            }

        print(f"\nProgress: {len(trader_trades)}/{len(trader_trades)} traders analyzed ✓\n")

        return trader_metrics

    def generate_report(self, trader_metrics: Dict, days_filter: Optional[int] = None):
        """Generate and display performance report."""

        print(f"\n{'='*70}")
        print(f"PERFORMANCE REPORT")
        print(f"{'='*70}\n")

        # Filter traders with minimum resolved trades
        min_resolved_trades = 10
        qualified_traders = {
            addr: metrics for addr, metrics in trader_metrics.items()
            if metrics['resolved_trades'] >= min_resolved_trades
        }

        print(f"Qualified traders (≥{min_resolved_trades} resolved trades): {len(qualified_traders)}\n")

        if not qualified_traders:
            print("⚠️ No traders with enough resolved trades for analysis")
            return

        # Calculate statistics
        all_win_rates = [m['win_rate'] for m in qualified_traders.values()]
        all_rois = [m['roi'] for m in qualified_traders.values()]
        all_pnls = [m['total_pnl'] for m in qualified_traders.values()]

        avg_win_rate = sum(all_win_rates) / len(all_win_rates)
        median_roi = sorted(all_rois)[len(all_rois) // 2]
        total_analyzed_trades = sum(m['total_trades'] for m in trader_metrics.values())
        total_resolved = sum(m['resolved_trades'] for m in trader_metrics.values())

        print(f"📈 OVERALL STATISTICS:")
        print(f"   Total trades analyzed: {total_analyzed_trades:,}")
        print(f"   Resolved trades: {total_resolved:,} ({total_resolved/total_analyzed_trades*100:.1f}%)")
        print(f"   Average win rate: {avg_win_rate:.2f}%")
        print(f"   Median ROI: {median_roi:.2f}%")
        print(f"   Total P&L: ${sum(all_pnls):,.2f}")

        # Top 10 by win rate
        print(f"\n{'='*70}")
        print(f"🏆 TOP 10 TRADERS BY WIN RATE")
        print(f"{'='*70}")
        top_win_rate = sorted(
            qualified_traders.values(),
            key=lambda x: x['win_rate'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Win Rate':<12}{'W-L':<12}{'Resolved':<12}{'ROI':<12}")
        print(f"{'-'*70}")

        for i, trader in enumerate(top_win_rate, 1):
            addr_short = trader['trader_address'][:12] + "..."
            wl = f"{trader['winning_trades']}-{trader['losing_trades']}"
            print(f"{i:<6}{addr_short:<15}{trader['win_rate']:>6.2f}%{wl:>10}{trader['resolved_trades']:>10}{trader['roi']:>9.2f}%")

        # Top 10 by ROI
        print(f"\n{'='*70}")
        print(f"💰 TOP 10 TRADERS BY ROI (Return on Investment)")
        print(f"{'='*70}")
        top_roi = sorted(
            qualified_traders.values(),
            key=lambda x: x['roi'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'ROI':<12}{'P&L':<15}{'Win Rate':<12}{'Resolved':<12}")
        print(f"{'-'*70}")

        for i, trader in enumerate(top_roi, 1):
            addr_short = trader['trader_address'][:12] + "..."
            pnl = f"${trader['total_pnl']:,.2f}"
            print(f"{i:<6}{addr_short:<15}{trader['roi']:>6.2f}%{pnl:>13}{trader['win_rate']:>9.2f}%{trader['resolved_trades']:>10}")

        # Top 10 by combined score
        print(f"\n{'='*70}")
        print(f"⭐ TOP 10 TRADERS BY COMBINED SCORE (Win Rate 50% + ROI 50%)")
        print(f"{'='*70}")
        top_combined = sorted(
            qualified_traders.values(),
            key=lambda x: x['combined_score'],
            reverse=True
        )[:10]

        print(f"{'Rank':<6}{'Address':<15}{'Score':<12}{'Win Rate':<12}{'ROI':<12}{'Resolved':<12}")
        print(f"{'-'*70}")

        for i, trader in enumerate(top_combined, 1):
            addr_short = trader['trader_address'][:12] + "..."
            print(f"{i:<6}{addr_short:<15}{trader['combined_score']:>6.2f}{trader['win_rate']:>9.2f}%{trader['roi']:>9.2f}%{trader['resolved_trades']:>10}")

        print(f"\n{'='*70}\n")

    def save_to_csv(self, trader_metrics: Dict, filename: str = "trader_performance_report.csv"):
        """Save analysis results to CSV file."""

        # Sort by combined score
        sorted_traders = sorted(
            trader_metrics.values(),
            key=lambda x: x.get('combined_score', 0),
            reverse=True
        )

        # Add timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header
            writer.writerow(['Analysis Timestamp', timestamp])
            writer.writerow([])
            writer.writerow([
                'Rank',
                'Trader Address',
                'Total Trades',
                'Resolved Trades',
                'Winning Trades',
                'Losing Trades',
                'Win Rate (%)',
                'Total P&L ($)',
                'Total Invested ($)',
                'Total Volume ($)',
                'ROI (%)',
                'Combined Score'
            ])

            # Write data
            for i, trader in enumerate(sorted_traders, 1):
                writer.writerow([
                    i,
                    trader['trader_address'],
                    trader['total_trades'],
                    trader['resolved_trades'],
                    trader['winning_trades'],
                    trader['losing_trades'],
                    f"{trader['win_rate']:.2f}",
                    f"{trader['total_pnl']:.2f}",
                    f"{trader['total_invested']:.2f}",
                    f"{trader['total_volume']:.2f}",
                    f"{trader['roi']:.2f}",
                    f"{trader['combined_score']:.2f}"
                ])

        print(f"✅ Report saved to: {filename}")
        print(f"   Total traders: {len(sorted_traders)}")
        print(f"   Timestamp: {timestamp}\n")


def main():
    """Main entry point."""

    # Load API key from .env if available
    api_key = None
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                if line.startswith('POLYMARKET_API_KEY='):
                    api_key = line.strip().split('=', 1)[1].strip('"').strip("'")
                    break

    # Initialize analyzer
    analyzer = TraderPerformanceAnalyzer(api_key=api_key)

    # Check if database exists
    if not os.path.exists("polymarket_tracker.db"):
        print("❌ Error: polymarket_tracker.db not found")
        print("   Make sure the monitoring script has run and collected trades")
        return

    # Run analysis for different time periods
    print("\nSelect analysis period:")
    print("1. Last 7 days")
    print("2. Last 30 days")
    print("3. All time")
    print("4. All periods (sequential)")

    choice = input("\nEnter choice (1-4) [default: 3]: ").strip() or "3"

    if choice == "1":
        days_filter = 7
        metrics = analyzer.analyze_trader_performance(days_filter)
        analyzer.generate_report(metrics, days_filter)
        analyzer.save_to_csv(metrics, f"trader_performance_7days_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "2":
        days_filter = 30
        metrics = analyzer.analyze_trader_performance(days_filter)
        analyzer.generate_report(metrics, days_filter)
        analyzer.save_to_csv(metrics, f"trader_performance_30days_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "3":
        metrics = analyzer.analyze_trader_performance(None)
        analyzer.generate_report(metrics, None)
        analyzer.save_to_csv(metrics, f"trader_performance_alltime_{datetime.now().strftime('%Y%m%d')}.csv")

    elif choice == "4":
        # Run all periods
        for period, days in [("7 days", 7), ("30 days", 30), ("All time", None)]:
            metrics = analyzer.analyze_trader_performance(days)
            analyzer.generate_report(metrics, days)
            suffix = f"{days}days" if days else "alltime"
            analyzer.save_to_csv(metrics, f"trader_performance_{suffix}_{datetime.now().strftime('%Y%m%d')}.csv")
            print("\n" + "="*70 + "\n")

    else:
        print("Invalid choice, running all-time analysis...")
        metrics = analyzer.analyze_trader_performance(None)
        analyzer.generate_report(metrics, None)
        analyzer.save_to_csv(metrics, f"trader_performance_alltime_{datetime.now().strftime('%Y%m%d')}.csv")


if __name__ == "__main__":
    main()
