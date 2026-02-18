"""
Position Tracker - Match BUY/SELL trades and calculate P&L.

This system tracks trading profits from early exits (selling when odds improve)
as a complement to the resolution-based evaluation system.

EXISTING P&L LOGIC REVIEW:
- analysis/trader_performance_analysis.py: Resolution-based P&L only (lines 157-203)
- analysis/risk_adjusted_returns.py: Resolution-based returns with risk metrics
- Both are READ-ONLY and don't track position matching or early exits

THIS IS NEW: First system to match BUY→SELL positions for early-exit P&L tracking

Key Concepts:
- Position: A matched set of BUY and SELL trades for same (trader, market, outcome)
- Realized P&L: Profit/loss from closed positions (fully sold)
- Unrealized P&L: Current value of open positions (not yet sold)
- ROI: Return on Investment percentage
- FIFO Matching: First In, First Out - oldest BUY trades matched first
"""

import json
from collections import deque  # O(1) operations for queue
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from monitoring.database import Database


class Position:
    """Represents a trading position (entry and optional exit)."""

    def __init__(self, trader_address: str, market_id: str, market_title: str,
                 outcome: str, entry_shares: float, entry_avg_price: float,
                 entry_timestamp: datetime, entry_trade_ids: List[str]):
        self.position_id = f"{trader_address[:8]}_{market_id[:8]}_{outcome}_{int(entry_timestamp.timestamp())}"
        self.trader_address = trader_address
        self.market_id = market_id
        self.market_title = market_title
        self.outcome = outcome

        # Entry
        self.entry_shares = entry_shares
        self.entry_avg_price = entry_avg_price
        self.entry_total_cost = entry_shares * entry_avg_price
        self.entry_timestamp = entry_timestamp
        self.entry_trade_ids = entry_trade_ids

        # Exit (initially None for open positions)
        self.exit_shares = None
        self.exit_avg_price = None
        self.exit_total_received = None
        self.exit_timestamp = None
        self.exit_trade_ids = []

        # Status
        self.status = 'open'
        self.remaining_shares = entry_shares

        # P&L (calculated when position closes)
        self.realized_pnl = None
        self.roi_percent = None
        self.holding_period_hours = None

    def close_position(self, exit_shares: float, exit_avg_price: float,
                      exit_timestamp: datetime, exit_trade_ids: List[str]):
        """Close or partially close the position."""
        self.exit_shares = exit_shares
        self.exit_avg_price = exit_avg_price
        self.exit_total_received = exit_shares * exit_avg_price
        self.exit_timestamp = exit_timestamp
        self.exit_trade_ids = exit_trade_ids

        # Calculate P&L (proportional to shares sold)
        proportion_sold = exit_shares / self.entry_shares
        cost_basis = self.entry_total_cost * proportion_sold

        self.realized_pnl = self.exit_total_received - cost_basis
        self.roi_percent = (self.realized_pnl / cost_basis) * 100 if cost_basis > 0 else 0

        # Holding period
        time_diff = exit_timestamp - self.entry_timestamp
        self.holding_period_hours = time_diff.total_seconds() / 3600

        # Update remaining shares
        self.remaining_shares = self.entry_shares - exit_shares

        # Set status
        if self.remaining_shares <= 0.001:  # Account for floating point
            self.status = 'closed'
            self.remaining_shares = 0
        else:
            self.status = 'partially_closed'

    def to_dict(self) -> Dict:
        """Convert to dictionary for database storage."""
        return {
            'position_id': self.position_id,
            'trader_address': self.trader_address,
            'market_id': self.market_id,
            'market_title': self.market_title,
            'outcome': self.outcome,
            'entry_shares': self.entry_shares,
            'entry_avg_price': self.entry_avg_price,
            'entry_total_cost': self.entry_total_cost,
            'entry_timestamp': self.entry_timestamp.isoformat(),
            'entry_trade_ids': json.dumps(self.entry_trade_ids),
            'exit_shares': self.exit_shares,
            'exit_avg_price': self.exit_avg_price,
            'exit_total_received': self.exit_total_received,
            'exit_timestamp': self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            'exit_trade_ids': json.dumps(self.exit_trade_ids),
            'realized_pnl': self.realized_pnl,
            'roi_percent': self.roi_percent,
            'holding_period_hours': self.holding_period_hours,
            'status': self.status,
            'remaining_shares': self.remaining_shares
        }


class PositionTracker:
    """
    Match BUY/SELL trades into positions and calculate P&L.

    Uses FIFO (First In, First Out) matching:
    - Oldest BUY trades are matched with SELL trades first
    - Handles partial positions (buy 100, sell 50, sell 50 later)
    """

    def __init__(self, database: Database):
        self.db = database

    def match_trades_for_trader(self, trader_address: str, verbose: bool = False) -> List[Position]:
        """
        Match all trades for a trader into positions using FIFO.

        Algorithm:
        1. Get all trades for trader, sorted by timestamp
        2. Group by (market_id, outcome)
        3. For each group, match BUYs with SELLs chronologically
        4. Track remaining shares in open positions

        Args:
            trader_address: Trader's wallet address
            verbose: Print detailed matching info

        Returns:
            List of Position objects
        """
        # Get all trades for trader
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT trade_id, market_id, market_title, outcome, shares, price,
                   side, timestamp
            FROM trades
            WHERE trader_address = ?
            ORDER BY timestamp ASC
        """, (trader_address,))

        trades = cursor.fetchall()
        conn.close()

        if verbose:
            print(f"  Found {len(trades)} trades for {trader_address[:10]}...")

        # Group by (market_id, outcome)
        grouped_trades = {}
        for trade in trades:
            trade_id, market_id, market_title, outcome, shares, price, side, timestamp = trade

            # Parse timestamp
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)

            key = (market_id, outcome)
            if key not in grouped_trades:
                grouped_trades[key] = []

            grouped_trades[key].append({
                'trade_id': trade_id,
                'market_title': market_title,
                'shares': shares,
                'price': price,
                'side': side,
                'timestamp': timestamp
            })

        if verbose:
            print(f"  Grouped into {len(grouped_trades)} (market, outcome) pairs")

        # Match BUYs and SELLs for each group
        all_positions = []

        for (market_id, outcome), trade_group in grouped_trades.items():
            positions = self._match_group(trader_address, market_id, outcome, trade_group, verbose)
            all_positions.extend(positions)

        if verbose:
            closed = sum(1 for p in all_positions if p.status == 'closed')
            open_pos = sum(1 for p in all_positions if p.status == 'open')
            print(f"  Created {len(all_positions)} positions ({closed} closed, {open_pos} open)")

        return all_positions

    def _match_group(self, trader_address: str, market_id: str, outcome: str,
                    trades: List[Dict], verbose: bool = False) -> List[Position]:
        """
        Match BUYs with SELLs for a specific (trader, market, outcome) group.

        Uses FIFO: oldest BUYs matched first.

        Args:
            trader_address: Trader's address
            market_id: Market identifier
            outcome: Outcome (e.g., "Yes", "No")
            trades: List of trades for this group
            verbose: Print matching details

        Returns:
            List of Position objects
        """
        positions = []
        open_buy_queue = deque()  # O(1) queue operations (was list)

        for trade in trades:
            if trade['side'].upper() == 'BUY':
                # Add to open positions queue
                open_buy_queue.append(trade)

            elif trade['side'].upper() == 'SELL':
                # Match against open BUYs
                sell_shares_remaining = trade['shares']
                matched_buys = []

                while sell_shares_remaining > 0.001 and open_buy_queue:  # Tolerance for floating point
                    oldest_buy = open_buy_queue[0]

                    if oldest_buy['shares'] <= sell_shares_remaining:
                        # Fully match this BUY
                        matched_buys.append(oldest_buy.copy())
                        sell_shares_remaining -= oldest_buy['shares']
                        open_buy_queue.popleft()  # O(1) operation (was pop(0) = O(n))
                    else:
                        # Partially match this BUY
                        partial_buy = oldest_buy.copy()
                        partial_buy['shares'] = sell_shares_remaining
                        matched_buys.append(partial_buy)

                        # Update remaining in queue
                        oldest_buy['shares'] -= sell_shares_remaining
                        sell_shares_remaining = 0

                # Create position from matched trades
                if matched_buys:
                    # Calculate weighted average entry price
                    total_shares = sum(b['shares'] for b in matched_buys)
                    total_cost = sum(b['shares'] * b['price'] for b in matched_buys)
                    avg_entry_price = total_cost / total_shares if total_shares > 0 else 0

                    # Get earliest entry timestamp
                    entry_timestamp = matched_buys[0]['timestamp']
                    entry_trade_ids = [b['trade_id'] for b in matched_buys]

                    # Create position
                    market_title = matched_buys[0].get('market_title', 'Unknown')
                    position = Position(
                        trader_address, market_id, market_title, outcome,
                        total_shares, avg_entry_price, entry_timestamp, entry_trade_ids
                    )

                    # Close it with the SELL
                    position.close_position(
                        total_shares, trade['price'], trade['timestamp'], [trade['trade_id']]
                    )

                    positions.append(position)

        # Any remaining BUYs are open positions
        for buy_trade in open_buy_queue:
            market_title = buy_trade.get('market_title', 'Unknown')
            position = Position(
                trader_address, market_id, market_title, outcome,
                buy_trade['shares'], buy_trade['price'],
                buy_trade['timestamp'], [buy_trade['trade_id']]
            )
            positions.append(position)

        return positions

    def calculate_trader_pnl(self, trader_address: str) -> Dict:
        """
        Calculate comprehensive P&L for a trader.

        Returns:
        {
            'realized_pnl': float,      # From closed positions
            'unrealized_pnl': float,    # Current value of open positions (placeholder)
            'total_pnl': float,
            'avg_roi': float,           # Average ROI across closed positions
            'total_invested': float,    # Total capital deployed
            'closed_positions': int,
            'open_positions': int,
            'best_trade': Dict,         # Highest ROI
            'worst_trade': Dict,        # Lowest ROI
            'total_positions': int,     # Total number of positions
            'profitable_positions': int, # Number with positive P&L
            'profitable_rate': float    # % of closed positions that were profitable
        }
        """
        positions = self.match_trades_for_trader(trader_address)

        closed = [p for p in positions if p.status == 'closed']
        open_pos = [p for p in positions if p.status == 'open']

        # Realized P&L
        realized_pnl = sum(p.realized_pnl for p in closed if p.realized_pnl is not None)

        # Profitable positions
        profitable_positions = sum(1 for p in closed if p.realized_pnl and p.realized_pnl > 0)
        profitable_rate = (profitable_positions / len(closed) * 100) if closed else 0

        # Unrealized P&L (assume current price = entry price for conservative estimate)
        # In production, you'd fetch current market prices from API
        unrealized_pnl = 0  # Placeholder - would need live market data

        # Open position cost basis: capital still tied up in unresolved markets
        open_cost_basis = sum(p.entry_total_cost for p in open_pos)

        # Average ROI
        rois = [p.roi_percent for p in closed if p.roi_percent is not None]
        avg_roi = sum(rois) / len(rois) if rois else 0

        # Total invested
        total_invested = sum(p.entry_total_cost for p in positions)

        # Best/worst trades
        best_trade = max(closed, key=lambda p: p.roi_percent) if closed else None
        worst_trade = min(closed, key=lambda p: p.roi_percent) if closed else None

        return {
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'open_cost_basis': open_cost_basis,
            'total_pnl': realized_pnl + unrealized_pnl,
            'avg_roi': avg_roi,
            'total_invested': total_invested,
            'closed_positions': len(closed),
            'open_positions': len(open_pos),
            'best_trade': best_trade.to_dict() if best_trade else None,
            'worst_trade': worst_trade.to_dict() if worst_trade else None,
            'total_positions': len(positions),
            'profitable_positions': profitable_positions,
            'profitable_rate': profitable_rate
        }

    def store_positions(self, positions: List[Position], verbose: bool = False):
        """Store positions in database."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        stored = 0
        for pos in positions:
            data = pos.to_dict()

            cursor.execute("""
                INSERT OR REPLACE INTO positions (
                    position_id, trader_address, market_id, market_title, outcome,
                    entry_shares, entry_avg_price, entry_total_cost, entry_timestamp, entry_trade_ids,
                    exit_shares, exit_avg_price, exit_total_received, exit_timestamp, exit_trade_ids,
                    realized_pnl, roi_percent, holding_period_hours, status, remaining_shares
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['position_id'], data['trader_address'], data['market_id'],
                data['market_title'], data['outcome'],
                data['entry_shares'], data['entry_avg_price'], data['entry_total_cost'],
                data['entry_timestamp'], data['entry_trade_ids'],
                data['exit_shares'], data['exit_avg_price'], data['exit_total_received'],
                data['exit_timestamp'], data['exit_trade_ids'],
                data['realized_pnl'], data['roi_percent'], data['holding_period_hours'],
                data['status'], data['remaining_shares']
            ))
            stored += 1

        conn.commit()
        conn.close()

        if verbose:
            print(f"  Stored {stored} positions to database")

    def get_positions_for_trader(self, trader_address: str, status: Optional[str] = None) -> List[Dict]:
        """
        Get positions for a trader from database.

        Args:
            trader_address: Trader's address
            status: Optional filter ('open', 'closed', 'partially_closed')

        Returns:
            List of position dictionaries
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM positions WHERE trader_address = ?"
        params = [trader_address]

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY entry_timestamp DESC"

        cursor.execute(query, params)

        positions = []
        for row in cursor.fetchall():
            positions.append(dict(row))

        conn.close()
        return positions
