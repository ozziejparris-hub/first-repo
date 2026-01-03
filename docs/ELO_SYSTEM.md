# Polymarket Trader Tracker - ELO Rating System

Comprehensive 6-dimension trader skill rating system.

## Overview

The ELO system evaluates trader skill across 6 dimensions:

1. **Base Category ELO** - Win/loss in specific market categories
2. **Behavioral Modifiers** - Trading patterns and consistency
3. **Advanced Metrics** - Calibration, Sharpe ratio, Kelly sizing
4. **P&L Modifiers** - Profitability and risk-adjusted returns
5. **Network Analysis** - Trader influence and market impact
6. **Contrarian Analysis** - Independent thinking vs consensus

**Final Rating:** Weighted combination of all 6 dimensions

## Quick Start

### View Top Traders

```bash
python scripts/view_trader_rankings.py
```

Output:
```
TOP 10 TRADERS BY COMPREHENSIVE ELO

Rank  Address           ELO    Win Rate  Trades  Volume
----  -------           ---    --------  ------  ------
1     0xAAAA...         1847   68.5%     157     $125,432
2     0xBBBB...         1789   71.2%     89      $98,123
...
```

### View Trader Details

```bash
python scripts/view_trader_stats.py 0xAAAA...
```

###

 Recalculate All ELO Ratings

```bash
python scripts/recalculate_comprehensive_elo.py
```

## ELO Dimensions Explained

### 1. Base Category ELO

**What it measures:** Win/loss record in specific market categories

**How it works:**
- Start at 1500 (baseline)
- Win a trade: +points based on difficulty
- Lose a trade: -points based on expected outcome
- Separate ELO per category (Politics, World, News, etc.)

**Formula:** Standard ELO rating (chess-style)
```
New ELO = Old ELO + K × (Actual - Expected)
K = 32 (volatility factor)
```

### 2. Behavioral Modifiers

**What it measures:** Trading discipline and consistency

**Factors:**
- **Trade frequency** - Overtrading penalty
- **Market timing** - Entry/exit timing quality
- **Position sizing** - Consistent vs erratic sizing
- **Market selection** - Category specialization

**Impact:** ±50 points

### 3. Advanced Metrics

**What it measures:** Statistical edge and calibration

**Factors:**
- **Calibration score** - Predicted probabilities vs outcomes
- **Sharpe ratio** - Risk-adjusted returns
- **Kelly criterion adherence** - Optimal position sizing
- **ROI consistency** - Stable vs volatile returns

**Impact:** ±100 points

### 4. P&L Modifiers

**What it measures:** Profitability

**Factors:**
- **Total P&L** - Absolute profit/loss
- **P&L per trade** - Efficiency
- **Win/loss ratio** - Size of wins vs losses
- **Maximum drawdown** - Risk management

**Impact:** ±75 points

### 5. Network Analysis

**What it measures:** Trader influence and market impact

**Factors:**
- **Copy trading** - How many traders copy this trader
- **Market moving** - Does their activity move prices
- **Correlation** - Relationship to other traders
- **Influence score** - Overall market impact

**Impact:** ±50 points

**Note:** Expensive to calculate, skipped in quick updates

### 6. Contrarian Analysis

**What it measures:** Independent thinking

**Factors:**
- **Consensus divergence** - Trading against the crowd
- **Early mover advantage** - Getting in before consensus
- **Conviction sizing** - Larger bets on contrarian views
- **Contrarian success rate** - Win rate on contrarian trades

**Impact:** ±75 points

**Note:** Expensive to calculate, skipped in quick updates

## Performance Optimization

### Caching Strategy

**Problem:** Calculating ELO for all traders on every cycle was too slow (~200s)

**Solution:** Multi-tier caching

**Tier 1 - Base ELO Cache** (1 hour TTL):
- Avoids recalculating all 1,946+ historical markets
- Only updates when markets resolve
- **Speedup:** 45x faster (13.5s → 0.3s per trader)

**Tier 2 - Behavioral/Advanced Cache** (during monitoring):
- Reuses expensive analysis
- Only P&L recalculated fresh
- **Speedup:** 4/6 dimensions instant

**Tier 3 - Full Recalculation** (daily or on-demand):
- All 6 dimensions fresh
- Includes network and contrarian
- **Time:** ~15 minutes for all traders

### Quick vs Full Updates

**Quick Update** (monitoring cycle):
```python
elo_bridge.quick_elo_update_for_traders(trader_addresses)
```
- 4/6 dimensions
- Uses caches
- Target: <10s for 50-100 traders

**Full Update** (daily/manual):
```python
elo_bridge.full_elo_update_for_all_traders()
```
- 6/6 dimensions
- Fresh calculations
- Target: <15 minutes

## ELO Rating Interpretation

| ELO Range | Skill Level | Description |
|-----------|-------------|-------------|
| 2000+ | Master | Elite traders, top 1% |
| 1800-2000 | Expert | Highly skilled, top 5% |
| 1600-1800 | Advanced | Above average, top 20% |
| 1400-1600 | Intermediate | Average trader |
| 1200-1400 | Novice | Below average |
| <1200 | Beginner | Learning phase |

**Baseline:** New traders start at 1500

## Analysis Scripts

### Test ELO Performance

```bash
python scripts/test_elo_performance.py
```

Tests speed of ELO calculation.

### Test ELO Caching

```bash
python scripts/test_elo_caching.py
```

Verifies cache is working correctly.

### Verify ELO Correctness

```bash
python scripts/verify_elo_correctness.py
```

Validates ELO calculations against known outcomes.

### Test ELO Integration

```bash
python scripts/test_elo_integration_quick.py
```

Tests monitoring→ELO integration.

### Run Full Analysis

```bash
python scripts/run_analysis.py
```

Runs complete analysis suite (all dimensions).

## Advanced Analysis Modules

Located in `analysis/`:

- `unified_elo_system.py` - Core ELO engine
- `calibration_analysis.py` - Probability calibration
- `consensus_divergence_detector.py` - Contrarian analysis
- `composite_skill_score.py` - Multi-metric scoring
- `copy_trade_detector.py` - Copy trading detection
- `correlation_matrix.py` - Trader correlation
- `market_confidence_meter.py` - Market confidence
- `regret_analysis.py` - Regret minimization analysis
- `risk_adjusted_returns.py` - Sharpe/Sortino ratios
- `trader_behavior_analyzer.py` - Behavioral patterns

## Technical Details

### Database Schema

**`traders` table:**
```sql
CREATE TABLE traders (
    address TEXT PRIMARY KEY,
    total_trades INTEGER,
    total_volume REAL,
    trades_won INTEGER,
    trades_lost INTEGER,
    win_rate REAL,
    comprehensive_elo REAL  -- 6-dimension composite score
);
```

### ELO Bridge

**File:** `monitoring/elo_bridge.py`

**Class:** `ELOBridge`

**Purpose:** Connects monitoring system to analysis/unified_elo_system

**Key methods:**
- `quick_elo_update_for_traders()` - Fast 4/6 dimensions
- `full_elo_update_for_all_traders()` - Complete 6/6 dimensions
- `get_trader_global_elo()` - Retrieve stored ELO

### Position Building

**File:** `monitoring/position_tracker.py`

**FIFO Matching:**
1. Buy orders increase position
2. Sell orders reduce position (oldest shares first)
3. Tracks average entry price
4. Calculates realized P&L

**Required for:** P&L modifiers in ELO calculation

## Troubleshooting

### Slow ELO Calculation

**Symptom:** Takes >30s per trader

**Solution:**
- Ensure caching is enabled (already is)
- Run quick updates during monitoring
- Run full updates daily (not every cycle)

### Stale ELO Ratings

**Symptom:** Ratings don't change after new trades

**Solution:**
```bash
# Force recalculation
python scripts/recalculate_comprehensive_elo.py
```

### Missing ELO Ratings

**Symptom:** `comprehensive_elo` is NULL

**Solution:**
1. Ensure monitoring has run and detected resolutions
2. Ensure positions are built:
   ```bash
   python scripts/build_positions_historical.py
   ```
3. Recalculate ELO:
   ```bash
   python scripts/recalculate_comprehensive_elo.py
   ```

### Incorrect ELO Values

**Symptom:** ELO seems wrong for a trader

**Solution:**
1. Verify trade outcomes are correct:
   ```bash
   python scripts/view_trader_stats.py 0xADDRESS
   ```
2. Check position data:
   ```bash
   # Via database query
   SELECT * FROM trader_positions WHERE trader_address='0xADDRESS'
   ```
3. Run verification:
   ```bash
   python scripts/verify_elo_correctness.py
   ```

## Related Documentation

- [MONITORING.md](MONITORING.md) - How ELO integrates with monitoring
- [SETUP.md](SETUP.md) - Installation
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [ELO_PERFORMANCE_OPTIMIZATION.md](../ELO_PERFORMANCE_OPTIMIZATION.md) - Caching details

## Further Reading

**In `archive/docs_analysis_historical/`:**
- Detailed implementation notes
- Historical integration summaries
- Performance benchmarks
- Data flow diagrams

**Consolidated from 25+ markdown files for clarity.**
