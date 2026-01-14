#!/usr/bin/env python3
"""
Trade Signal Generator

Generates buy/sell signals based on:
- Top ELO trader activity
- Consensus among elite traders
- Market price vs trader positions
- Confidence thresholds
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.database import Database


class SignalGenerator:
    """Generate trade signals from ELO rankings and trader activity."""

    def __init__(self, config: Dict, db: Database):
        """Initialize signal generator."""
        self.config = config
        self.db = db

        self.min_elo = config['trading']['min_trader_elo']
        self.top_n = config['trading']['follow_top_n']
        self.min_confidence = config['trading']['min_confidence']

    def get_top_traders(self) -> List[Dict]:
        """
        Get top N traders by ELO.

        Returns:
            List of trader dictionaries
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get simulation traders with high ELO
        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                win_rate,
                total_trades,
                total_volume
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            AND comprehensive_elo >= ?
            AND total_trades >= 10
            ORDER BY comprehensive_elo DESC
            LIMIT ?
        """, (self.min_elo, self.top_n))

        traders = []
        for row in cursor.fetchall():
            traders.append({
                'address': row[0],
                'elo': row[1] if row[1] else 1500,
                'win_rate': row[2] if row[2] else 0.5,
                'total_trades': row[3] if row[3] else 0,
                'total_volume': row[4] if row[4] else 0
            })

        conn.close()
        return traders

    def get_trader_positions(self, trader_address: str, market_id: str) -> Optional[Dict]:
        """
        Get trader's position in a market.

        Args:
            trader_address: Trader wallet address
            market_id: Market identifier

        Returns:
            Position data or None
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                outcome_bet,
                SUM(shares) as total_shares,
                AVG(price) as avg_price,
                COUNT(*) as num_trades
            FROM trades
            WHERE trader_address = ?
            AND market_id = ?
            GROUP BY outcome_bet
            ORDER BY total_shares DESC
        """, (trader_address, market_id))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'outcome': row[0],
            'shares': row[1] if row[1] else 0,
            'avg_price': row[2] if row[2] else 0.5,
            'num_trades': row[3] if row[3] else 0
        }

    def get_market_trader_consensus(self, market_id: str) -> Optional[Dict]:
        """
        Get consensus of top traders for a market from database.

        Args:
            market_id: Market identifier

        Returns:
            Consensus data or None
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get trades from top ELO traders on this market
        cursor.execute("""
            SELECT
                t.outcome_bet,
                t.shares,
                t.price,
                tr.comprehensive_elo,
                tr.win_rate
            FROM trades t
            JOIN traders tr ON t.trader_address = tr.address
            WHERE t.market_id = ?
            AND tr.comprehensive_elo >= ?
            AND tr.comprehensive_elo IS NOT NULL
            ORDER BY tr.comprehensive_elo DESC
        """, (market_id, self.min_elo))

        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 3:  # Need at least 3 top trader positions
            return None

        # Calculate weighted consensus
        yes_weight = 0
        no_weight = 0
        total_weight = 0

        for row in rows:
            outcome, shares, price, elo, win_rate = row
            shares = shares if shares else 0
            elo = elo if elo else 1500

            # Weight by ELO and position size
            weight = (elo / 1500) * (shares ** 0.5)  # Square root to reduce impact of huge positions

            if outcome == 'Yes':
                yes_weight += weight
            else:
                no_weight += weight

            total_weight += weight

        if total_weight == 0:
            return None

        consensus_prob = yes_weight / total_weight
        confidence = abs(consensus_prob - 0.5) * 2  # 0 = 50/50, 1 = 100% agreement

        return {
            'market_id': market_id,
            'consensus_prob': consensus_prob,
            'confidence': confidence,
            'num_traders': len(rows),
            'yes_weight': yes_weight,
            'no_weight': no_weight
        }

    def calculate_consensus(self, market_id: str, market_title: str = None) -> Optional[Dict]:
        """
        Calculate consensus among top traders for a market.

        Args:
            market_id: Market identifier
            market_title: Optional market title

        Returns:
            Consensus signal or None
        """
        top_traders = self.get_top_traders()

        if not top_traders:
            return None

        # Get positions for each top trader
        positions = []
        for trader in top_traders:
            pos = self.get_trader_positions(trader['address'], market_id)
            if pos and pos['shares'] > 0:
                total_vol = trader['total_volume'] if trader['total_volume'] > 0 else 1
                positions.append({
                    'trader_elo': trader['elo'],
                    'outcome': pos['outcome'],
                    'shares': pos['shares'],
                    'confidence': min(1.0, pos['shares'] / (total_vol * 0.1))  # Position size as confidence proxy
                })

        if len(positions) < 3:  # Need at least 3 traders
            return None

        # Calculate weighted consensus
        yes_weight = 0
        no_weight = 0

        for pos in positions:
            weight = (pos['trader_elo'] / 1500) * pos['confidence']  # ELO-weighted confidence

            if pos['outcome'] == 'Yes':
                yes_weight += weight
            else:
                no_weight += weight

        total_weight = yes_weight + no_weight

        if total_weight == 0:
            return None

        consensus_prob = yes_weight / total_weight
        confidence = abs(consensus_prob - 0.5) * 2  # 0 = 50/50, 1 = 100% agreement

        # Determine signal
        if confidence >= self.min_confidence:
            signal = 'BUY_YES' if consensus_prob > 0.5 else 'BUY_NO'

            return {
                'market_id': market_id,
                'market_title': market_title or 'Unknown',
                'signal': signal,
                'confidence': confidence,
                'consensus_prob': consensus_prob,
                'num_traders': len(positions),
                'timestamp': datetime.now()
            }

        return None

    def generate_signals(self, active_markets: List[Dict]) -> List[Dict]:
        """
        Generate trade signals for all active markets.

        Args:
            active_markets: List of active market dictionaries

        Returns:
            List of trade signals
        """
        signals = []

        print(f"\n[SIGNALS] Analyzing {len(active_markets)} markets...")

        for market in active_markets:
            market_id = market.get('conditionId', market.get('id', ''))
            market_title = market.get('question', market.get('title', 'Unknown'))

            # Calculate consensus
            consensus = self.calculate_consensus(market_id, market_title)

            if consensus:
                consensus['market_category'] = market.get('category', 'Unknown')
                signals.append(consensus)

        # Sort by confidence
        signals.sort(key=lambda x: x['confidence'], reverse=True)

        print(f"[SIGNALS] Generated {len(signals)} high-confidence signals")

        return signals

    def get_all_market_signals(self) -> List[Dict]:
        """
        Generate signals for all markets in database.

        Returns:
            List of signals
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get all active markets
        cursor.execute("""
            SELECT DISTINCT market_id, title, category
            FROM markets
            WHERE resolved = 0
            ORDER BY last_checked DESC
            LIMIT 100
        """)

        markets = []
        for row in cursor.fetchall():
            markets.append({
                'conditionId': row[0],
                'question': row[1],
                'category': row[2]
            })

        conn.close()

        return self.generate_signals(markets)


def main():
    """Test signal generation."""
    print("[TEST] Testing Signal Generator...")
    print()

    db = Database()

    # Load config
    import json
    with open('config/paper_trading_config.json', 'r') as f:
        config = json.load(f)

    generator = SignalGenerator(config, db)

    # Get top traders
    top_traders = generator.get_top_traders()
    print(f"Top {len(top_traders)} traders:")
    for i, t in enumerate(top_traders[:5], 1):
        print(f"  {i}. ELO: {t['elo']:.1f}, Win Rate: {t['win_rate']:.1%}, Trades: {t['total_trades']}")

    # Generate signals from database markets
    print("\nGenerating signals from database markets...")
    signals = generator.get_all_market_signals()

    if signals:
        print(f"\nTop signals:")
        for i, sig in enumerate(signals[:5], 1):
            print(f"  {i}. {sig['signal']} - {sig['market_title'][:50]}...")
            print(f"     Confidence: {sig['confidence']:.1%}, Traders: {sig['num_traders']}")
    else:
        print("\n[WARN] No signals generated (check database has ELO-rated traders)")


if __name__ == '__main__':
    main()
