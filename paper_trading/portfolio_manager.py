#!/usr/bin/env python3
"""
Virtual Portfolio Manager

Manages paper trading portfolio:
- Track positions
- Calculate P&L
- Risk management
- Position sizing
"""

import json
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path


class PortfolioManager:
    """Manage virtual trading portfolio."""

    def __init__(self, config_path: str = "config/paper_trading_config.json"):
        """Initialize portfolio."""
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.capital = self.config['trading']['initial_capital']
        self.initial_capital = self.capital
        self.positions = []  # List of open positions
        self.trade_history = []  # List of completed trades

        # Risk limits
        self.max_position_size = self.config['trading']['max_position_size']
        self.max_exposure = self.config['trading']['max_total_exposure']
        self.max_trades_per_day = self.config['risk_management']['max_trades_per_day']
        self.stop_loss_pct = self.config['risk_management']['stop_loss_pct']
        self.take_profit_pct = self.config['risk_management']['take_profit_pct']

        # Load existing portfolio if exists
        self.load_portfolio()

    def load_portfolio(self):
        """Load portfolio from disk."""
        portfolio_file = Path("results/paper_trading/portfolio.json")

        if portfolio_file.exists():
            try:
                with open(portfolio_file, 'r') as f:
                    data = json.load(f)
                    self.capital = data.get('capital', self.initial_capital)
                    self.positions = data.get('positions', [])
                    self.trade_history = data.get('trade_history', [])
                    print(f"[PORTFOLIO] Loaded: ${self.capital:.2f} capital, {len(self.positions)} positions")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[WARN] Could not load portfolio: {e}")

    def save_portfolio(self):
        """Save portfolio to disk."""
        portfolio_file = Path("results/paper_trading/portfolio.json")
        portfolio_file.parent.mkdir(exist_ok=True, parents=True)

        data = {
            'capital': self.capital,
            'initial_capital': self.initial_capital,
            'positions': self.positions,
            'trade_history': self.trade_history,
            'last_updated': datetime.now().isoformat()
        }

        with open(portfolio_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    def calculate_position_size(self, signal: Dict, current_price: float) -> float:
        """
        Calculate position size based on Kelly criterion and risk limits.

        Args:
            signal: Trade signal dictionary
            current_price: Current market price

        Returns:
            Position size in dollars
        """
        # Kelly fraction based on confidence
        confidence = signal['confidence']
        kelly_fraction = confidence * 0.5  # Half-Kelly for safety

        # Apply position size limit
        max_position = self.capital * self.max_position_size
        kelly_position = self.capital * kelly_fraction

        position_size = min(max_position, kelly_position)

        # Check total exposure limit
        current_exposure = sum(p['total_cost'] for p in self.positions)
        max_total_exposure = self.capital * self.max_exposure

        if current_exposure + position_size > max_total_exposure:
            position_size = max(0, max_total_exposure - current_exposure)

        return position_size

    def check_existing_position(self, market_id: str) -> Optional[Dict]:
        """
        Check if we already have a position in this market.

        Args:
            market_id: Market identifier

        Returns:
            Existing position or None
        """
        for pos in self.positions:
            if pos['market_id'] == market_id:
                return pos
        return None

    def open_position(self, signal: Dict, current_price: float) -> Optional[Dict]:
        """
        Open a new position.

        Args:
            signal: Trade signal
            current_price: Current market price

        Returns:
            Position dictionary or None
        """
        # Check for existing position
        existing = self.check_existing_position(signal['market_id'])
        if existing:
            print(f"[PORTFOLIO] Already have position in this market")
            return None

        # Calculate position size
        position_size = self.calculate_position_size(signal, current_price)

        if position_size < 10:  # Minimum $10 position
            print(f"[PORTFOLIO] Position too small: ${position_size:.2f}")
            return None

        # Check daily trade limit
        today = datetime.now().date()
        today_trades = [
            t for t in self.trade_history
            if datetime.fromisoformat(t['timestamp']).date() == today
        ]

        if len(today_trades) >= self.max_trades_per_day:
            print(f"[PORTFOLIO] Daily trade limit reached ({self.max_trades_per_day})")
            return None

        # Check we have enough capital
        if position_size > self.capital:
            position_size = self.capital - 10  # Leave $10 buffer
            if position_size < 10:
                print(f"[PORTFOLIO] Insufficient capital")
                return None

        # Determine outcome to buy
        outcome = 'Yes' if signal['signal'] == 'BUY_YES' else 'No'

        # Calculate shares
        shares = position_size / current_price

        # Create position
        position = {
            'id': len(self.trade_history) + len(self.positions) + 1,
            'market_id': signal['market_id'],
            'market_title': signal.get('market_title', 'Unknown'),
            'market_category': signal.get('market_category', 'Unknown'),
            'outcome': outcome,
            'shares': shares,
            'avg_price': current_price,
            'total_cost': position_size,
            'confidence': signal['confidence'],
            'num_traders': signal.get('num_traders', 0),
            'timestamp': datetime.now().isoformat(),
            'stop_loss': current_price * (1 - self.stop_loss_pct),
            'take_profit': current_price * (1 + self.take_profit_pct)
        }

        # Update portfolio
        self.positions.append(position)
        self.capital -= position_size

        print(f"[PORTFOLIO] OPENED: {outcome} on {signal['market_title'][:50]}...")
        print(f"           Size: ${position_size:.2f} ({shares:.2f} shares @ ${current_price:.3f})")
        print(f"           Capital remaining: ${self.capital:.2f}")

        self.save_portfolio()
        return position

    def close_position(self, position: Dict, exit_price: float, reason: str = "MANUAL") -> Dict:
        """
        Close an existing position.

        Args:
            position: Position dictionary
            exit_price: Exit price
            reason: Close reason (MANUAL, STOP_LOSS, TAKE_PROFIT, RESOLVED)

        Returns:
            Completed trade dictionary
        """
        # Calculate P&L
        proceeds = position['shares'] * exit_price
        pnl = proceeds - position['total_cost']
        pnl_pct = (pnl / position['total_cost']) * 100 if position['total_cost'] > 0 else 0

        # Update capital
        self.capital += proceeds

        # Create trade record
        trade = {
            **position,
            'exit_price': exit_price,
            'proceeds': proceeds,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'close_reason': reason,
            'close_timestamp': datetime.now().isoformat()
        }

        self.trade_history.append(trade)

        # Remove from open positions
        if position in self.positions:
            self.positions.remove(position)

        pnl_emoji = "[+]" if pnl >= 0 else "[-]"
        print(f"[PORTFOLIO] CLOSED: {position['outcome']} on {position['market_title'][:50]}...")
        print(f"           {pnl_emoji} P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%) - Reason: {reason}")
        print(f"           Capital: ${self.capital:.2f}")

        self.save_portfolio()
        return trade

    def check_stop_loss_take_profit(self, position: Dict, current_price: float) -> Optional[str]:
        """
        Check if position hits stop loss or take profit.

        Args:
            position: Position dictionary
            current_price: Current market price

        Returns:
            'STOP_LOSS', 'TAKE_PROFIT', or None
        """
        entry_price = position['avg_price']
        pnl_pct = ((current_price / entry_price) - 1) * 100

        if pnl_pct <= -self.stop_loss_pct * 100:
            return 'STOP_LOSS'
        elif pnl_pct >= self.take_profit_pct * 100:
            return 'TAKE_PROFIT'

        return None

    def get_performance(self) -> Dict:
        """
        Calculate portfolio performance metrics.

        Returns:
            Performance statistics
        """
        total_pnl = sum(t['pnl'] for t in self.trade_history)
        total_trades = len(self.trade_history)
        winning_trades = sum(1 for t in self.trade_history if t['pnl'] > 0)

        if total_trades > 0:
            win_rate = winning_trades / total_trades
            avg_pnl = total_pnl / total_trades
            avg_win = sum(t['pnl'] for t in self.trade_history if t['pnl'] > 0) / max(1, winning_trades)
            avg_loss = sum(t['pnl'] for t in self.trade_history if t['pnl'] < 0) / max(1, total_trades - winning_trades)
        else:
            win_rate = 0
            avg_pnl = 0
            avg_win = 0
            avg_loss = 0

        # Current positions value
        positions_value = sum(p['total_cost'] for p in self.positions)

        roi = ((self.capital + positions_value - self.initial_capital) / self.initial_capital) * 100

        return {
            'current_capital': self.capital,
            'initial_capital': self.initial_capital,
            'positions_value': positions_value,
            'total_value': self.capital + positions_value,
            'total_pnl': total_pnl,
            'roi': roi,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'open_positions': len(self.positions)
        }

    def print_summary(self):
        """Print portfolio summary."""
        perf = self.get_performance()

        print("\n" + "=" * 60)
        print("  PORTFOLIO SUMMARY")
        print("=" * 60)
        print(f"\n  Capital:          ${perf['current_capital']:.2f}")
        print(f"  Positions Value:  ${perf['positions_value']:.2f}")
        print(f"  Total Value:      ${perf['total_value']:.2f}")
        print(f"  Total P&L:        ${perf['total_pnl']:+.2f}")
        print(f"  ROI:              {perf['roi']:+.2f}%")
        print()
        print(f"  Total Trades:     {perf['total_trades']}")
        print(f"  Win Rate:         {perf['win_rate']:.1%}")
        print(f"  Avg P&L:          ${perf['avg_pnl']:+.2f}")
        print(f"  Open Positions:   {perf['open_positions']}")

        if self.positions:
            print("\n  Open Positions:")
            for pos in self.positions:
                print(f"    - {pos['outcome']} @ ${pos['avg_price']:.3f}: {pos['market_title'][:40]}...")

        print("\n" + "=" * 60)

    def reset(self):
        """Reset portfolio to initial state."""
        self.capital = self.initial_capital
        self.positions = []
        self.trade_history = []
        self.save_portfolio()
        print("[PORTFOLIO] Reset to initial state")


def main():
    """Test portfolio manager."""
    print("[TEST] Testing Portfolio Manager...")
    print()

    pm = PortfolioManager()
    pm.print_summary()

    # Simulate a trade
    print("\n[TEST] Simulating a trade...")

    test_signal = {
        'market_id': 'test_market_001',
        'market_title': 'Test Market - Will BTC exceed $100K?',
        'signal': 'BUY_YES',
        'confidence': 0.75,
        'num_traders': 15
    }

    # Open position
    pos = pm.open_position(test_signal, current_price=0.65)

    if pos:
        print("\n[TEST] Position opened successfully")
        pm.print_summary()

        # Close position with profit
        print("\n[TEST] Closing with 20% profit...")
        pm.close_position(pos, exit_price=0.78, reason="TAKE_PROFIT")
        pm.print_summary()


if __name__ == '__main__':
    main()
