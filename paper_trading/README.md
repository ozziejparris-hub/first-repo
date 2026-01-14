# Paper Trading System for Polymarket ELO Strategy

This paper trading system validates the ELO-based trader ranking system against real Polymarket data without risking actual money.

## System Overview

The paper trading bot:
1. **Monitors** active Polymarket markets via API
2. **Generates signals** based on top ELO-rated traders
3. **Executes virtual trades** with simulated capital
4. **Tracks performance** to validate simulation predictions

## Prerequisites

- Python 3.8+
- Validated ELO system (r=0.773, 82.5% elite accuracy)
- Polymarket account (for API access)

## Quick Start

### Step 1: Install Dependencies

```bash
pip install requests python-dotenv
```

### Step 2: Configure API Keys

1. Copy the template:
```bash
cp .env.template .env
```

2. Edit `.env` and add your Polymarket API key:
```
POLYMARKET_API_KEY=your_actual_key_here
```

You can get an API key from: https://polymarket.com/settings/api

### Step 3: Test Connection

```bash
py paper_trading/test_connection.py
```

Expected output:
```
[OK] API connection: WORKING
[OK] Market data: AVAILABLE
[OK] Markets found: 142
SUCCESS - Ready for paper trading!
```

### Step 4: Start Paper Trading

```bash
py paper_trading/run_paper_trading.py
```

The bot will:
- Check markets every 5 minutes
- Generate signals from top 20 ELO traders
- Execute paper trades with virtual $10,000
- Track performance in `results/paper_trading/`

### Step 5: View Performance

```bash
py paper_trading/view_performance.py
```

## Configuration

Edit `config/paper_trading_config.json` to customize:

```json
{
  "trading": {
    "initial_capital": 10000,    // Starting virtual capital
    "max_position_size": 0.05,   // Max 5% per trade
    "min_confidence": 0.60,      // Minimum signal confidence
    "follow_top_n": 20,          // Follow top N traders
    "min_trader_elo": 1600       // Minimum ELO to follow
  },
  "monitoring": {
    "check_interval_seconds": 300,  // Check every 5 minutes
    "categories": ["Elections", "Geopolitics", "Economics", "Crypto"]
  },
  "risk_management": {
    "max_trades_per_day": 10,
    "stop_loss_pct": 0.20,       // 20% stop loss
    "take_profit_pct": 0.50      // 50% take profit
  }
}
```

## Risk Management

The system includes several safety features:

| Feature | Default | Description |
|---------|---------|-------------|
| Max Position Size | 5% | Maximum capital per trade |
| Max Total Exposure | 25% | Maximum capital in open positions |
| Stop Loss | 20% | Auto-close losing positions |
| Take Profit | 50% | Auto-close winning positions |
| Daily Trade Limit | 10 | Maximum trades per day |

## Expected Performance

Based on simulation validation (r=0.773, 82.5% elite accuracy):

| Metric | Expected Range |
|--------|---------------|
| Win Rate | 65-70% |
| ROI | 20-30% |
| Sharpe Ratio | 0.5-1.5 |
| Max Drawdown | < 15% |

## File Structure

```
paper_trading/
├── __init__.py              # Module init
├── polymarket_client.py     # Polymarket API client
├── signal_generator.py      # Trade signal generation
├── portfolio_manager.py     # Virtual portfolio tracking
├── run_paper_trading.py     # Main bot loop
├── test_connection.py       # API connection test
├── view_performance.py      # Performance viewer
└── README.md                # This file

config/
└── paper_trading_config.json # Configuration

results/paper_trading/
└── portfolio.json           # Saved portfolio state
```

## Commands

| Command | Description |
|---------|-------------|
| `py paper_trading/test_connection.py` | Test API connection |
| `py paper_trading/run_paper_trading.py` | Start paper trading |
| `py paper_trading/run_paper_trading.py --test` | Single iteration test |
| `py paper_trading/run_paper_trading.py -n 5` | Run 5 iterations |
| `py paper_trading/view_performance.py` | View performance |

## Troubleshooting

### "API key invalid"
- Check `.env` file has correct key
- Verify key is active at polymarket.com

### "Rate limit exceeded"
- Increase `check_interval_seconds` in config
- Default 300s (5 min) is safe

### "No signals generated"
- Check database has ELO ratings
- Run: `py scripts/simulation/calculate_elo_simple.py --k-factor 32`
- Verify top traders exist: `py paper_trading/signal_generator.py`

### "Connection failed"
- Check internet connection
- Verify API endpoint is up
- Try again in a few minutes

## Next Steps

After 1-2 weeks of paper trading:

1. **Validate Performance**
   - Compare win rate to simulation (target: 65-70%)
   - Compare ROI to simulation (target: 20-30%)
   - Review false positives

2. **If Validated:**
   - Proceed to micro-live trading ($100)
   - Use same strategy with real API
   - Monitor for drift

3. **If Not Validated:**
   - Review signal generation
   - Check ELO calculations
   - Adjust confidence thresholds

## Security Notes

- **NEVER commit `.env` file** (already in .gitignore)
- **Use read-only API keys** when possible
- **Start with paper trading only** (no real money)
- **Keep API keys secure** (don't share)

## License

Internal use only. Part of the Polymarket ELO Tracker project.
