#!/usr/bin/env python3
"""
Polymarket Simulation Market Viewer

Inspect simulated markets and trader behavior.

Features:
- List all simulated markets (resolved and pending)
- Show trader participation by market
- Display outcomes and winners/losers
- Calculate market difficulty (elite success rate)
- Show ELO changes from each market

Usage:
    py scripts/simulation/view_markets.py                          # List all markets
    py scripts/simulation/view_markets.py --market-id <id>         # Market details
    py scripts/simulation/view_markets.py --sort-by difficulty     # Hardest markets
    py scripts/simulation/view_markets.py --sort-by volume         # Most traded
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from monitoring.database import Database


class MarketViewer:
    """View and analyze simulated markets."""

    def __init__(self, db: Database, simulation_age_days: int = 7):
        """Initialize market viewer."""
        self.db = db
        self.simulation_age_days = simulation_age_days
        self.simulation_traders = []
        self.trader_elos = {}

    def load_simulation_traders(self):
        """Load simulation traders and their ELO ratings."""
        cutoff_date = (datetime.now() - timedelta(days=self.simulation_age_days)).strftime('%Y-%m-%d %H:%M:%S')

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT address, comprehensive_elo, win_rate, total_trades
            FROM traders
            WHERE total_trades > 0
            AND total_trades < 100
            AND last_updated > ?
            ORDER BY comprehensive_elo DESC
        """, (cutoff_date,))

        rows = cursor.fetchall()
        self.simulation_traders = [row[0] for row in rows]
        self.trader_elos = {row[0]: {'elo': row[1], 'win_rate': row[2], 'total_trades': row[3]} for row in rows}

        conn.close()
        return len(self.simulation_traders)

    def get_elite_traders(self) -> List[str]:
        """Get list of elite traders (>60% win rate)."""
        return [addr for addr, data in self.trader_elos.items() if data['win_rate'] > 0.60]

    def list_markets(self, sort_by: str = 'created', limit: int = None) -> List[Dict]:
        """
        List all simulated markets.

        Args:
            sort_by: 'created', 'difficulty', 'volume', 'title'
            limit: Maximum number of markets to return
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        if not self.simulation_traders:
            return []

        # Get markets with trades from simulation traders
        placeholders = ','.join('?' * len(self.simulation_traders))
        cursor.execute(f"""
            SELECT DISTINCT
                m.market_id,
                m.title,
                m.resolved,
                m.winning_outcome,
                m.category,
                COUNT(t.trade_id) as trade_count
            FROM markets m
            INNER JOIN trades t ON t.market_id = m.market_id
            WHERE t.trader_address IN ({placeholders})
            GROUP BY m.market_id
            ORDER BY trade_count DESC
        """, tuple(self.simulation_traders))

        markets = []
        elite_traders = self.get_elite_traders()

        for row in cursor.fetchall():
            market_id, title, resolved, winning_outcome, category, trade_count = row

            # Calculate difficulty for resolved markets
            difficulty = None
            elite_success_rate = None

            if resolved and winning_outcome:
                # Get elite trader outcomes
                elite_placeholders = ','.join('?' * len(elite_traders))
                cursor.execute(f"""
                    SELECT outcome
                    FROM trades
                    WHERE market_id = ?
                    AND trader_address IN ({elite_placeholders})
                """, (market_id,) + tuple(elite_traders))

                elite_outcomes = cursor.fetchall()
                if elite_outcomes:
                    correct = sum(1 for (outcome,) in elite_outcomes if outcome == winning_outcome)
                    elite_success_rate = correct / len(elite_outcomes)
                    difficulty = 1 - elite_success_rate  # Higher = harder

            markets.append({
                'market_id': market_id,
                'title': title,
                'resolved': bool(resolved),
                'winning_outcome': winning_outcome,
                'category': category,
                'trade_count': trade_count,
                'difficulty': difficulty,
                'elite_success_rate': elite_success_rate
            })

        conn.close()

        # Sort markets
        if sort_by == 'difficulty' and any(m['difficulty'] is not None for m in markets):
            markets = sorted([m for m in markets if m['difficulty'] is not None],
                           key=lambda m: m['difficulty'], reverse=True)
        elif sort_by == 'volume':
            markets = sorted(markets, key=lambda m: m['trade_count'], reverse=True)
        elif sort_by == 'title':
            markets = sorted(markets, key=lambda m: m['title'])
        # else: keep default order (by trade_count DESC)

        if limit:
            markets = markets[:limit]

        return markets

    def get_market_details(self, market_id: str) -> Optional[Dict]:
        """Get detailed information about a specific market."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get market info
        cursor.execute("""
            SELECT market_id, title, resolved, winning_outcome, category
            FROM markets
            WHERE market_id = ?
        """, (market_id,))

        market_row = cursor.fetchone()
        if not market_row:
            conn.close()
            return None

        market_id, title, resolved, winning_outcome, category = market_row

        # Get all trades on this market from simulation traders
        if not self.simulation_traders:
            conn.close()
            return None

        placeholders = ','.join('?' * len(self.simulation_traders))
        cursor.execute(f"""
            SELECT
                trader_address,
                outcome,
                shares,
                price,
                side,
                timestamp
            FROM trades
            WHERE market_id = ?
            AND trader_address IN ({placeholders})
            ORDER BY timestamp
        """, (market_id,) + tuple(self.simulation_traders))

        trades = []
        outcome_counts = defaultdict(int)

        for row in cursor.fetchall():
            trader_address, outcome, shares, price, side, timestamp = row
            trades.append({
                'trader_address': trader_address,
                'outcome': outcome,
                'shares': shares,
                'price': price,
                'side': side,
                'timestamp': timestamp
            })
            outcome_counts[outcome] += 1

        conn.close()

        # Analyze trades
        winners = []
        losers = []
        elite_traders = self.get_elite_traders()

        if resolved and winning_outcome:
            for trade in trades:
                trader = trade['trader_address']
                trader_data = self.trader_elos.get(trader, {})

                won = (trade['outcome'] == winning_outcome)

                # Calculate P&L
                if won:
                    pnl = trade['shares'] * (1 - trade['price'])
                else:
                    pnl = -trade['shares'] * trade['price']

                trade_detail = {
                    'trader_address': trader,
                    'trader_elo': trader_data.get('elo', 0),
                    'trader_win_rate': trader_data.get('win_rate', 0),
                    'is_elite': trader in elite_traders,
                    'outcome': trade['outcome'],
                    'shares': trade['shares'],
                    'price': trade['price'],
                    'pnl': pnl,
                    'won': won
                }

                if won:
                    winners.append(trade_detail)
                else:
                    losers.append(trade_detail)

        # Calculate difficulty
        difficulty = None
        elite_success_rate = None

        if resolved and winning_outcome and elite_traders:
            elite_trades = [t for t in trades if t['trader_address'] in elite_traders]
            if elite_trades:
                correct = sum(1 for t in elite_trades if t['outcome'] == winning_outcome)
                elite_success_rate = correct / len(elite_trades)
                difficulty = 1 - elite_success_rate

        return {
            'market_id': market_id,
            'title': title,
            'resolved': bool(resolved),
            'winning_outcome': winning_outcome,
            'category': category,
            'trade_count': len(trades),
            'outcome_counts': dict(outcome_counts),
            'difficulty': difficulty,
            'elite_success_rate': elite_success_rate,
            'winners': sorted(winners, key=lambda w: w['pnl'], reverse=True),
            'losers': sorted(losers, key=lambda l: l['pnl']),
            'all_trades': trades
        }

    def display_market_list(self, markets: List[Dict]):
        """Display list of markets in formatted output."""
        print()
        print("=" * 80)
        print(f"  SIMULATED MARKETS (Last {self.simulation_age_days} Days)")
        print("=" * 80)
        print()

        if not markets:
            print("No simulated markets found.")
            return

        resolved_count = sum(1 for m in markets if m['resolved'])
        print(f"Total: {len(markets)} markets ({resolved_count} resolved, {len(markets) - resolved_count} pending)")
        print()

        for market in markets:
            status = "RESOLVED" if market['resolved'] else "PENDING"
            outcome = f" -> {market['winning_outcome']}" if market['winning_outcome'] else ""

            print(f"Market: {market['market_id'][:20]}...")
            print(f"  Title: {market['title'][:70]}")
            print(f"  Status: {status}{outcome}")
            print(f"  Trades: {market['trade_count']}")

            if market['difficulty'] is not None:
                difficulty_pct = market['difficulty'] * 100
                elite_success_pct = market['elite_success_rate'] * 100

                if difficulty_pct > 50:
                    difficulty_label = "HARD"
                elif difficulty_pct > 30:
                    difficulty_label = "MEDIUM"
                else:
                    difficulty_label = "EASY"

                print(f"  Difficulty: {difficulty_pct:.1f}% ({difficulty_label})")
                print(f"  Elite Success: {elite_success_pct:.1f}%")

            print()

    def display_market_details(self, market: Dict):
        """Display detailed market information."""
        print()
        print("=" * 80)
        print(f"  MARKET DETAILS")
        print("=" * 80)
        print()

        print(f"Market ID: {market['market_id']}")
        print(f"Title: {market['title']}")
        print(f"Category: {market['category']}")
        print()

        status = "RESOLVED" if market['resolved'] else "PENDING"
        outcome = f" -> {market['winning_outcome']}" if market['winning_outcome'] else ""
        print(f"Status: {status}{outcome}")
        print()

        # Outcome distribution
        print("Outcome Distribution:")
        for outcome, count in market['outcome_counts'].items():
            pct = count / market['trade_count'] * 100
            print(f"  {outcome}: {count} trades ({pct:.1f}%)")
        print()

        # Difficulty
        if market['difficulty'] is not None:
            difficulty_pct = market['difficulty'] * 100
            elite_success_pct = market['elite_success_rate'] * 100

            if difficulty_pct > 50:
                difficulty_label = "HARD"
            elif difficulty_pct > 30:
                difficulty_label = "MEDIUM"
            else:
                difficulty_label = "EASY"

            print(f"Difficulty: {difficulty_pct:.1f}% ({difficulty_label})")
            print(f"Elite Success Rate: {elite_success_pct:.1f}%")
            print()

        # Winners and losers
        if market['resolved'] and market['winning_outcome']:
            print(f"Winners ({len(market['winners'])} traders):")
            for i, winner in enumerate(market['winners'][:10], 1):
                elite_marker = "[ELITE]" if winner['is_elite'] else ""
                print(f"  {i}. {winner['trader_address'][:20]}... "
                      f"{elite_marker} "
                      f"P&L: ${winner['pnl']:.2f} "
                      f"(bet {winner['outcome']} at {winner['price']:.2f})")
            if len(market['winners']) > 10:
                print(f"  ... and {len(market['winners']) - 10} more winners")
            print()

            print(f"Losers ({len(market['losers'])} traders):")
            for i, loser in enumerate(market['losers'][:10], 1):
                elite_marker = "[ELITE]" if loser['is_elite'] else ""
                print(f"  {i}. {loser['trader_address'][:20]}... "
                      f"{elite_marker} "
                      f"P&L: ${loser['pnl']:.2f} "
                      f"(bet {loser['outcome']} at {loser['price']:.2f})")
            if len(market['losers']) > 10:
                print(f"  ... and {len(market['losers']) - 10} more losers")
            print()

            # P&L summary
            total_winner_pnl = sum(w['pnl'] for w in market['winners'])
            total_loser_pnl = sum(l['pnl'] for l in market['losers'])
            avg_winner_pnl = total_winner_pnl / len(market['winners']) if market['winners'] else 0
            avg_loser_pnl = total_loser_pnl / len(market['losers']) if market['losers'] else 0

            print("P&L Summary:")
            print(f"  Total Winners P&L: ${total_winner_pnl:.2f}")
            print(f"  Total Losers P&L: ${total_loser_pnl:.2f}")
            print(f"  Avg Winner P&L: ${avg_winner_pnl:.2f}")
            print(f"  Avg Loser P&L: ${avg_loser_pnl:.2f}")
            print()


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='View and analyze simulated markets',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all markets
  py scripts/simulation/view_markets.py

  # Show hardest markets
  py scripts/simulation/view_markets.py --sort-by difficulty --limit 10

  # Show most traded markets
  py scripts/simulation/view_markets.py --sort-by volume --limit 10

  # Show specific market details
  py scripts/simulation/view_markets.py --market-id <market_id>

  # Use custom time window
  py scripts/simulation/view_markets.py --simulation-age-days 14
        """
    )

    parser.add_argument('--market-id', type=str,
                       help='Show details for specific market')

    parser.add_argument('--sort-by', type=str,
                       choices=['created', 'difficulty', 'volume', 'title'],
                       default='volume',
                       help='Sort markets by (default: volume)')

    parser.add_argument('--limit', type=int,
                       help='Maximum number of markets to show')

    parser.add_argument('--simulation-age-days', type=int, default=7,
                       help='Consider traders updated within N days (default: 7)')

    args = parser.parse_args()

    # Initialize
    db = Database()
    viewer = MarketViewer(db, simulation_age_days=args.simulation_age_days)

    # Load simulation traders
    num_traders = viewer.load_simulation_traders()

    if num_traders == 0:
        print("[ERROR] No simulation traders found")
        print(f"Try increasing --simulation-age-days (current: {args.simulation_age_days})")
        return 1

    try:
        if args.market_id:
            # Show specific market details
            market = viewer.get_market_details(args.market_id)
            if market:
                viewer.display_market_details(market)
            else:
                print(f"[ERROR] Market not found: {args.market_id}")
                return 1
        else:
            # List markets
            markets = viewer.list_markets(sort_by=args.sort_by, limit=args.limit)
            viewer.display_market_list(markets)

        return 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Cancelled by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
