# Position & P&L Tracking System

## Overview

The Position & P&L Tracking System is a **complementary** addition to the existing resolution-based trader evaluation. It tracks profits from early exits (selling when odds improve) to identify traders who are skilled at **timing** rather than just **prediction**.

This system works **ALONGSIDE** (not replacing) the resolution-based tracking to provide a complete view of trader performance.

## Why This System Exists

### Two Types of Successful Traders

1. **Prediction-Focused Traders** (Resolution-based)
   - Hold positions until market resolves
   - Win if they correctly predicted the outcome
   - Tracked by: Win Rate from resolved markets

2. **Trading-Focused Traders** (P&L-based)
   - Exit positions early when odds shift favorably
   - Profit from price movements before resolution
   - Tracked by: Realized P&L from position matching

**Example Scenarios:**

- Trader A buys "Yes" @ $0.30, holds to resolution, wins → Captured by resolution tracking
- Trader B buys "Yes" @ $0.30, sells @ $0.70 (early exit), profits $0.40 → Captured by P&L tracking
- Trader C does BOTH strategies → Benefits from both tracking systems

## Architecture

### New Components

1. **monitoring/position_tracker.py** (NEW)
   - `Position` class - Represents matched BUY/SELL trades
   - `PositionTracker` class - FIFO matching engine
   - Calculates realized P&L, ROI, holding periods

2. **Database Schema** (EXTENDED)
   - `positions` table - Stores matched positions
   - `traders` table - Added P&L fields (realized_pnl, avg_roi, etc.)

3. **monitoring/trader_statistics.py** (EXTENDED)
   - Added `calculate_comprehensive_stats()` - Combines BOTH metrics
   - Added `update_trader_comprehensive_stats()` - Updates database with both

4. **Scripts** (NEW)
   - `scripts/migrate_add_positions.py` - Database migration
   - `scripts/build_positions_historical.py` - One-time historical processing
   - `scripts/view_pnl_performance.py` - View P&L metrics

### Existing Components (Reviewed)

- `analysis/trader_performance_analysis.py` - **Read-only**, resolution-based P&L
- `analysis/risk_adjusted_returns.py` - **Read-only**, risk metrics
- **Neither tracks position matching or early exits**

## How It Works

### Position Matching (FIFO)

The system uses **First In, First Out (FIFO)** matching:

```
Timeline:
T1: BUY 100 shares @ $0.30  → Opens position
T2: BUY 50 shares @ $0.40   → Adds to position
T3: SELL 100 shares @ $0.70 → Closes first BUY (T1), Partially closes second BUY (T2)
T4: SELL 50 shares @ $0.60  → Closes remaining from T2

Positions Created:
- Position 1: Buy 100 @ $0.30, Sell 100 @ $0.70 → P&L: +$40.00 (133% ROI)
- Position 2: Buy 50 @ $0.40, Sell 50 @ $0.60  → P&L: +$10.00 (50% ROI)
```

### P&L Calculation

```python
# For a closed position
cost_basis = entry_shares * entry_avg_price
proceeds = exit_shares * exit_avg_price
realized_pnl = proceeds - cost_basis
roi_percent = (realized_pnl / cost_basis) * 100

# Example
entry: 100 shares @ $0.30 = $30.00 cost
exit:  100 shares @ $0.70 = $70.00 proceeds
P&L:   $70.00 - $30.00    = $40.00 profit
ROI:   ($40.00 / $30.00)  = 133%
```

### Database Schema

**positions table:**
```sql
CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,
    trader_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    outcome TEXT NOT NULL,

    -- Entry
    entry_shares REAL NOT NULL,
    entry_avg_price REAL NOT NULL,
    entry_total_cost REAL NOT NULL,
    entry_timestamp TIMESTAMP NOT NULL,
    entry_trade_ids TEXT,  -- JSON array

    -- Exit
    exit_shares REAL,
    exit_avg_price REAL,
    exit_total_received REAL,
    exit_timestamp TIMESTAMP,
    exit_trade_ids TEXT,  -- JSON array

    -- P&L
    realized_pnl REAL,
    roi_percent REAL,
    holding_period_hours REAL,

    -- Status
    status TEXT NOT NULL,  -- 'open', 'closed', 'partially_closed'
    remaining_shares REAL
)
```

**traders table (new fields):**
```sql
ALTER TABLE traders ADD COLUMN realized_pnl REAL DEFAULT 0;
ALTER TABLE traders ADD COLUMN avg_roi REAL DEFAULT 0;
ALTER TABLE traders ADD COLUMN total_invested REAL DEFAULT 0;
ALTER TABLE traders ADD COLUMN closed_positions INTEGER DEFAULT 0;
ALTER TABLE traders ADD COLUMN open_positions INTEGER DEFAULT 0;
```

## Current State

After running the migration and historical build:

- **Total Positions**: 8,590
- **Closed Positions**: 80 (positions with exits)
- **Open Positions**: 8,510 (still holding)
- **Total Realized P&L**: $186.00
- **Average ROI**: -2.56%
- **Profitable Positions**: 33/80 (41.2%)
- **Traders with P&L**: 62

## Usage Examples

### Example 1: View P&L Performance

```bash
# Overall summary + top performers
python scripts/view_pnl_performance.py

# Top traders by ROI (minimum 5 closed positions)
python scripts/view_pnl_performance.py --top 10 --min-positions 5

# Compare P&L vs resolution-based rankings
python scripts/view_pnl_performance.py --compare

# View specific trader's positions
python scripts/view_pnl_performance.py --trader 0x123...
```

### Example 2: Calculate Comprehensive Stats

```python
from monitoring.database import Database
from monitoring.trader_statistics import TraderStatisticsCalculator

db = Database()
calc = TraderStatisticsCalculator(db)

# Get BOTH resolution-based AND P&L-based metrics
stats = calc.calculate_comprehensive_stats("0x123...")

print("Resolution-based (Prediction Accuracy):")
print(f"  Win Rate: {stats['resolution_based']['win_rate']:.1f}%")
print(f"  Resolved Trades: {stats['resolution_based']['resolved_trades']}")

print("\nP&L-based (Trading Skill):")
print(f"  Realized P&L: ${stats['pnl_based']['realized_pnl']:,.2f}")
print(f"  Average ROI: {stats['pnl_based']['avg_roi']:.1f}%")
print(f"  Closed Positions: {stats['pnl_based']['closed_positions']}")
```

### Example 3: Position Matching

```python
from monitoring.database import Database
from monitoring.position_tracker import PositionTracker

db = Database()
tracker = PositionTracker(db)

# Match all trades for a trader into positions
positions = tracker.match_trades_for_trader("0x123...")

# Store positions in database
tracker.store_positions(positions)

# Calculate P&L summary
pnl_stats = tracker.calculate_trader_pnl("0x123...")
print(f"Realized P&L: ${pnl_stats['realized_pnl']:,.2f}")
print(f"Avg ROI: {pnl_stats['avg_roi']:.1f}%")
print(f"Closed Positions: {pnl_stats['closed_positions']}")
```

## Key Design Decisions

### 1. FIFO Matching

**Why FIFO?** Most accurate for tax reporting and intuitive for position tracking. Oldest shares are sold first.

**Alternative Considered:** LIFO (Last In, First Out) - Rejected because it doesn't reflect typical trading behavior.

### 2. Additive System

**Why Additive?** The two metrics capture different skills:
- Resolution-based: Prediction accuracy (fundamental analysis)
- P&L-based: Trading timing (technical analysis)

**Best Traders:** Excel at BOTH - they predict correctly AND exit profitably.

### 3. SQL-Based Statistics Update

**Why SQL?** Updating 5,416 traders by recalculating positions would be slow and cause database locks. Instead, we aggregate directly from the `positions` table using SQL subqueries.

### 4. Separate from Analysis Tools

**Why Separate?** Existing `analysis/trader_performance_analysis.py` and `analysis/risk_adjusted_returns.py` are **read-only** reporting tools. The monitoring system needs **write access** to update operational metrics in real-time.

## Integration Points

### With Trader Statistics System

```python
# In monitoring/trader_statistics.py
class TraderStatisticsCalculator:
    def __init__(self, database, min_resolved_trades=5):
        self.db = database
        self.position_tracker = PositionTracker(database)  # NEW

    def calculate_comprehensive_stats(self, trader_address):
        # Returns BOTH resolution-based AND P&L-based metrics
        resolution_stats = self.calculate_trader_win_rate(trader_address)
        pnl_stats = self.position_tracker.calculate_trader_pnl(trader_address)
        return {'resolution_based': ..., 'pnl_based': ..., 'combined': ...}
```

### With Resolution Checking (Future)

When markets resolve:
1. Resolution checker detects resolved market
2. Trade evaluator marks trades as won/lost
3. **Position tracker updates any positions for that market** (future enhancement)
4. Trader statistics recalculates BOTH metrics

### With ELO System (Future)

The comprehensive stats will feed into ELO calculation:

```python
# Future ELO formula (conceptual)
elo_components = {
    'prediction_accuracy': stats['resolution_based']['win_rate'] * 0.4,
    'trading_skill': stats['pnl_based']['avg_roi'] * 0.3,
    'profitability': stats['pnl_based']['realized_pnl'] * 0.3
}
final_elo = calculate_elo(**elo_components)
```

## Limitations & Future Enhancements

### Current Limitations

1. **Open Position Valuation**: Currently set to $0 unrealized P&L
   - **Fix**: Fetch current market prices from API to value open positions

2. **No Resolution Link**: Position P&L is separate from resolution outcome
   - **Fix**: Link positions to market resolutions to compare "held to resolution" vs "exited early" outcomes

3. **No Transaction Costs**: P&L calculations don't include fees
   - **Fix**: Subtract Polymarket's 2% fee from realized P&L

4. **Simple FIFO Only**: Doesn't track specific lots or tax optimization
   - **Enhancement**: Add LIFO, HIFO (Highest In, First Out) options

### Planned Enhancements

1. **Live Position Updates**
   - When new trades come in, automatically update positions
   - Currently: Positions built once from historical data

2. **Position Alerts**
   - Notify when trader closes position with high ROI
   - Identify profitable exit patterns

3. **Strategy Classification**
   - Label traders as "Hold-to-Resolution" vs "Active Trading" vs "Hybrid"
   - Based on ratio of closed positions to resolved trades

4. **Performance Attribution**
   - Calculate: "Did exiting early help or hurt vs holding to resolution?"
   - Requires linking positions to market resolutions

## File Reference

### Core Implementation
- `monitoring/position_tracker.py` - Position matching engine (370 lines)
- `monitoring/trader_statistics.py` - Comprehensive stats calculator (extended)
- `monitoring/database.py` - Database layer (unchanged, uses positions table)

### Scripts
- `scripts/migrate_add_positions.py` - Database migration
- `scripts/build_positions_historical.py` - Historical position builder
- `scripts/view_pnl_performance.py` - P&L performance viewer
- `scripts/test_comprehensive_stats.py` - Test comprehensive calculation

### Database
- Positions table: 8,590 positions (80 closed, 8,510 open)
- Traders table: 5,416 flagged traders with P&L fields

## Performance

- **Migration**: ~1 second
- **Historical Build**: 9.8 seconds for 11,513 trades across 5,416 traders
- **Statistics Update**: <1 second using SQL aggregation
- **Position Query**: Fast with indexes on (trader_address, market_id, status)

## Testing

```bash
# Test migration
python scripts/migrate_add_positions.py

# Build positions from historical trades
python scripts/build_positions_historical.py

# Test comprehensive stats
python scripts/test_comprehensive_stats.py

# View results
python scripts/view_pnl_performance.py
```

## Success Metrics

✅ Positions table created with indexes
✅ PositionTracker matches BUY/SELL using FIFO
✅ Handles partial positions correctly
✅ Calculates accurate P&L and ROI
✅ TraderStatisticsCalculator combines BOTH metrics
✅ Traders table has win_rate AND realized_pnl
✅ Built 8,590 positions from 11,513 trades
✅ View scripts show both rankings
✅ System tracks TWO complementary skills:
   - Prediction accuracy (resolution-based)
   - Trading skill (P&L-based)
✅ Ready for ELO integration (future)

## Related Documentation

- [Trader Statistics System](TRADER_STATISTICS_SYSTEM.md) - Resolution-based tracking
- [API Resolution Structure](API_RESOLUTION_STRUCTURE.md) - How markets resolve
- [Trade Evaluator](../monitoring/trade_evaluator.py) - Resolution-based evaluation
