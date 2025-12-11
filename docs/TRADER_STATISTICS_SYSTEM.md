# Trader Statistics System

## Overview

The Trader Statistics System calculates and tracks real win rates for traders based on actual market resolutions. This bridges the monitoring system (which tracks traders and trades) with the analysis system (which generates reports).

## Architecture

### Components

1. **monitoring/trader_statistics.py** (NEW)
   - `TraderStatisticsCalculator` - Core calculation engine
   - Calculates win rates from resolved trades
   - Updates traders table in database

2. **monitoring/trader_analyzer.py** (MODIFIED)
   - Integrated automatic statistics updates after resolution detection
   - Calls `TraderStatisticsCalculator` when markets resolve

3. **scripts/recalculate_trader_stats.py** (NEW)
   - Manual recalculation trigger
   - Useful after backfills or data fixes

4. **scripts/view_trader_stats.py** (NEW)
   - View trader performance from database
   - Multiple view modes: summary, top performers, all traders, specific trader

### Database Schema

**Traders Table** (existing, now properly utilized):
- `address` - Trader wallet address
- `total_trades` - Total number of trades
- `successful_trades` - Number of winning trades (updated by stats system)
- `win_rate` - Calculated win rate percentage (updated by stats system)
- `total_volume` - Total dollar volume traded
- `is_flagged` - Whether trader is being actively tracked

**Trades Table** (existing):
- `trade_id` - Unique trade identifier
- `trader_address` - FK to traders
- `outcome_bet` - Which outcome trader bet on
- `trade_result` - 'won', 'lost', 'pending', 'invalid'
- (other fields...)

## How It Works

### Automatic Flow (Integrated)

1. **Market Resolution Detection**
   - `TraderAnalyzer.check_market_resolutions()` runs periodically
   - Detects newly resolved markets via Polymarket API

2. **Trade Evaluation**
   - `TradeEvaluator.batch_evaluate_resolved_markets()` is called
   - Marks each trade as 'won' or 'lost' based on market outcome

3. **Statistics Update** (NEW)
   - `TraderStatisticsCalculator.recalculate_all_flagged_traders()` is called
   - Recalculates win rates from resolved trades
   - Updates traders table with new statistics

### Manual Flow

1. **Run Recalculation Script**
   ```bash
   python scripts/recalculate_trader_stats.py
   ```
   - Recalculates statistics for all flagged traders
   - Useful after running backfills or fixing data

2. **View Statistics**
   ```bash
   # Summary + top performers
   python scripts/view_trader_stats.py

   # Specific trader
   python scripts/view_trader_stats.py --trader 0x123...

   # All traders
   python scripts/view_trader_stats.py --all

   # Summary only
   python scripts/view_trader_stats.py --summary
   ```

## Usage Examples

### Example 1: After Market Resolution

When markets resolve naturally through the monitoring system:

```python
from monitoring.trader_analyzer import TraderAnalyzer
from monitoring.database import Database
from monitoring.polymarket_client import PolymarketClient

db = Database()
client = PolymarketClient(api_key)
analyzer = TraderAnalyzer(db, client)

# This automatically:
# 1. Checks for resolved markets
# 2. Evaluates trades
# 3. Updates trader statistics
newly_resolved = analyzer.check_market_resolutions()
```

### Example 2: Manual Recalculation

After running a backfill or data fix:

```bash
# Run backfill
python scripts/backfill_trade_results.py

# Recalculate statistics
python scripts/recalculate_trader_stats.py

# View results
python scripts/view_trader_stats.py --top 10
```

### Example 3: Programmatic Access

```python
from monitoring.database import Database
from monitoring.trader_statistics import TraderStatisticsCalculator

db = Database()
calc = TraderStatisticsCalculator(db, min_resolved_trades=5)

# Calculate for specific trader
stats = calc.calculate_trader_win_rate("0x123...")
print(f"Win Rate: {stats['win_rate']:.2f}%")
print(f"Resolved Trades: {stats['resolved_trades']}")
print(f"Won: {stats['won_trades']}, Lost: {stats['lost_trades']}")

# Update database
calc.update_trader_win_rate("0x123...", verbose=True)

# Recalculate all
summary = calc.recalculate_all_flagged_traders(verbose=True)
print(f"Average win rate: {summary['average_win_rate']:.2f}%")
```

## Key Features

### Minimum Trade Threshold

- Default: 5 resolved trades required for reliable statistics
- Configurable via `min_resolved_trades` parameter
- Traders below threshold still get calculated stats but are marked as having insufficient data

### Win Rate Calculation

```
Win Rate = (Won Trades / (Won Trades + Lost Trades)) * 100
```

- Only counts trades with result 'won' or 'lost'
- Ignores pending trades
- Ignores invalid trades

### Integration Points

1. **Automatic Updates**
   - Triggered by: `TraderAnalyzer.check_market_resolutions()`
   - When: After detecting newly resolved markets
   - What: Evaluates trades + updates statistics

2. **Manual Updates**
   - Triggered by: `scripts/recalculate_trader_stats.py`
   - When: User-initiated
   - What: Full recalculation for all flagged traders

## Comparison with Analysis Tools

### analysis/trader_performance_analysis.py (Read-Only)

- **Purpose**: Generate detailed performance reports with ROI, P&L
- **Database**: Read-only, never modifies
- **Output**: Console reports and CSV files
- **Use Case**: Deep analysis, reporting, research

### monitoring/trader_statistics.py (Write-Enabled)

- **Purpose**: Update trader win rates in operational database
- **Database**: Writes to traders table
- **Output**: Updated database records
- **Use Case**: Real-time monitoring, automated tracking

**Both tools can coexist** - one for real-time tracking, one for detailed analysis.

## Current State

As of the latest check:

- Flagged Traders: 5,287
- Total Trades: 11,205
- Resolved Trades: 0
- Status: Waiting for markets to resolve

The system is ready and will automatically calculate win rates once markets resolve.

## Troubleshooting

### No Resolved Trades

**Symptom**: All win rates show 0.00%

**Cause**: Markets haven't resolved yet

**Solution**:
1. Run fast resolution checker: `python monitoring/fast_resolution_check.py`
2. Run trade evaluator: `python scripts/backfill_trade_results.py`
3. Recalculate stats: `python scripts/recalculate_trader_stats.py`

### Win Rates Not Updating

**Symptom**: New markets resolved but win rates unchanged

**Solution**:
1. Check if trades were evaluated: `python scripts/view_trader_stats.py --summary`
2. Manually recalculate: `python scripts/recalculate_trader_stats.py`

### Specific Trader Shows 0%

**Symptom**: Trader has trades but 0% win rate

**Solution**:
1. Check trader details: `python scripts/view_trader_stats.py --trader 0x...`
2. Verify trades are resolved (not pending)
3. Run recalculation if needed

## Future Enhancements

Potential additions to the system:

1. **Decay/Weighting**: Weight recent trades more heavily
2. **Category-Specific Win Rates**: Track performance by market category
3. **Confidence Intervals**: Calculate statistical confidence based on sample size
4. **Historical Tracking**: Store win rate history over time
5. **Automated Alerts**: Notify when trader's performance changes significantly

## Related Documentation

- [API Resolution Structure](API_RESOLUTION_STRUCTURE.md) - How market resolutions work
- [Trade Evaluation System](../monitoring/trade_evaluator.py) - How trades are evaluated
- [Database Schema](../monitoring/database.py) - Full database structure
