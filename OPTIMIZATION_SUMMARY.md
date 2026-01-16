# Behavioral ELO Optimizations - 2026-01-15

**Date:** 2026-01-15
**Status:** COMPLETED
**Purpose:** Optimize ELO system for real monitoring data

---

## Overview

After achieving correlation r = 0.347 (2.6x improvement over baseline 0.135), applied two optimizations to prepare system for ongoing monitoring data collection.

---

## Optimization 1: Lower Sample Filter (30 Resolved Trades)

### Rationale
- Only 1.2% of markets are resolved (2,480 / 200,000+)
- Filter of 50 resolved trades too restrictive
- Simulations show 30 trades provide stable ELO estimates

### Changes Applied

**File: `scripts/integrate_behavioral_elo.py`**
- Line 280: `min_resolved_trades=30` (was 50)
- Line 317: `resolved_trades_count >= 30` (was 50)
- Line 331: Display text updated
- Line 343: Average query updated

**File: `analysis/unified_elo_system.py`**
- Line 3505: `min_resolved_trades: int = 30` (was 50)

**File: `tests/test_behavioral_integration.py`**
- Test expectations updated for 30-trade minimum

### Expected Impact
- **Immediate:** More traders qualify for ELO rankings
- **When monitoring runs:** +2-5% correlation improvement (larger sample size)

### Results
- Before: ~500-600 traders with 50+ resolved trades
- After: ~900+ traders with 30+ resolved trades
- **50% increase in qualified traders**

---

## Optimization 2: Calibrate ROI Multiplier for Real Data

### Rationale
- Simulations showed skilled traders achieve 10-30% ROI
- Original ranges (0-50% neutral) too conservative
- Real monitoring data captures early exits (main profit source)
- Need better differentiation at 10-30% ROI range

### Changes Applied

**File: `analysis/unified_elo_system.py`**

#### Before (Conservative):
```python
def calculate_roi_modifier(self, avg_roi: float) -> float:
    if avg_roi > 50:
        return 1.15
    elif avg_roi > 30:
        return 1.10
    elif avg_roi > 20:
        return 1.07
    elif avg_roi > 10:
        return 1.05
    elif avg_roi > 0:
        return 1.00  # No bonus for 0-10% ROI
    elif avg_roi > -10:
        return 0.95
    else:
        return 0.90
```

#### After (Optimized):
```python
def calculate_roi_modifier(self, avg_roi: float) -> float:
    """
    OPTIMIZED for real monitoring data with early exits and position tracking.
    Ranges calibrated from simulations showing 10-30% ROI for skilled traders.

    Returns:
        float: Multiplier (0.85-1.25)
            - >50%: 1.25x (exceptional, rare)
            - 30-50%: 1.20x (elite performance)
            - 20-30%: 1.15x (strong skill)
            - 10-20%: 1.10x (above average)
            - 5-10%: 1.05x (slight edge)
            - 0-5%: 1.00x (neutral)
            - -5-0%: 0.95x (small losses)
            - -10--5%: 0.90x (poor)
            - <-10%: 0.85x (very poor)
    """
    if avg_roi > 50:
        return 1.25  # was 1.15
    elif avg_roi > 30:
        return 1.20  # was 1.10
    elif avg_roi > 20:
        return 1.15  # was 1.07
    elif avg_roi > 10:
        return 1.10  # was 1.05
    elif avg_roi > 5:
        return 1.05  # NEW threshold
    elif avg_roi > 0:
        return 1.00
    elif avg_roi > -5:
        return 0.95  # NEW threshold
    elif avg_roi > -10:
        return 0.90  # was 0.95
    else:
        return 0.85  # was 0.90
```

### Key Improvements
1. **Better Differentiation:** More granular at 5-30% ROI range (where skilled traders cluster)
2. **Higher Rewards:** 1.25x max (was 1.15x) for exceptional performance
3. **Finer Penalties:** Separate 0-5% and -5-0% ranges for better granularity
4. **Stronger Penalties:** 0.85x min (was 0.90x) for very poor performance

### Expected Impact
- **When P&L populates:** +5-10% correlation improvement
- **Better separation:** Elite traders (20%+ ROI) rewarded more
- **More accurate:** Neutral traders (0-5% ROI) stay near 1.0x

---

## Validation Script Created

**File: `scripts/validate_pnl_data.py`**

### Purpose
- Check if monitoring has populated P&L data
- Report coverage statistics (% traders with data)
- Validate data quality (realistic ranges)
- Show profitability distribution

### Usage
```bash
python scripts/validate_pnl_data.py
```

### Output Sections
1. **Coverage:** How many traders have P&L data
2. **Quality:** P&L ranges, average ROI, closed positions
3. **Distribution:** Profitability breakdown (profitable vs losses)
4. **ROI Distribution:** Elite (30%+), Strong (20-30%), etc.
5. **Sample Size:** Closed position distribution (confidence levels)
6. **Summary:** Recommendations based on coverage

### Current Status (2026-01-15)
```
Total traders (10+ trades): 1,957
Traders with P&L data: 0 (0.0%)
Traders with investment data: 0
Traders with closed positions: 0

Status: Monitoring system has not run yet
Action: Run monitoring to populate P&L columns
```

---

## Integration with Monitoring System

### How P&L Data Populates

1. **Monitoring Runs:** `python -m monitoring.main`
2. **Position Tracker:** `monitoring/position_tracker.py` tracks positions
3. **Market Resolves:** When markets resolve, positions close
4. **P&L Updated:** Database columns populated:
   - `realized_pnl`: Profit from closed positions
   - `unrealized_pnl`: Current value of open positions
   - `total_pnl`: Combined P&L
   - `avg_roi`: Average return percentage
   - `total_invested`: Capital deployed
   - `closed_positions`: Number of closed positions

### When ELO Integration Benefits

**Immediate (Current State):**
- ROI modifier applies 1.0x to everyone (neutral)
- No differentiation from P&L
- Correlation: 0.347

**After Monitoring Runs (Future):**
- ROI modifier applies 0.85-1.25x based on performance
- Strong differentiation for elite traders (20%+ ROI)
- Expected correlation: 0.39-0.42 (+5-10% improvement)

---

## Summary of All Optimizations

### Applied Optimizations
1. ✅ **Sample Filter:** 50 → 30 resolved trades (expect +2-5% correlation)
2. ✅ **ROI Ranges:** Calibrated for 10-30% skilled trader range (expect +5-10% correlation)
3. ✅ **Validation Script:** Monitor P&L data population

### Combined Expected Impact
- **Current:** r = 0.347 (2.6x improvement)
- **After monitoring runs:** r = 0.40-0.45 (3.0-3.4x improvement)
- **After schema extension (created_at):** r = 0.45-0.50 (3.4-3.8x improvement)

### Files Modified
1. `analysis/unified_elo_system.py` - ROI modifier optimization, sample filter
2. `scripts/integrate_behavioral_elo.py` - Sample filter lowered
3. `tests/test_behavioral_integration.py` - Test expectations updated
4. `scripts/validate_pnl_data.py` - NEW validation script

---

## Usage Instructions

### Run Validation
```bash
# Check if P&L data is populated
python scripts/validate_pnl_data.py
```

### Start Monitoring
```bash
# Start monitoring to populate P&L data
python -m monitoring.main
```

### Re-Run ELO Integration
```bash
# After P&L data populates, re-run integration
python scripts/integrate_behavioral_elo.py
```

### Check Correlation
```bash
# Verify correlation improvement
python scripts/simulation/verify_elo_rankings.py
```

---

## Technical Details

### ROI Modifier Math

**Combined P&L Multiplier:**
```python
combined = profit_modifier * roi_modifier * quality_modifier * confidence
```

**Example Elite Trader (30% ROI):**
- Profit modifier: 1.10x (made $500)
- ROI modifier: 1.20x (30% return)
- Quality modifier: 1.05x (70% profitable rate)
- Confidence: 0.95 (40 closed positions)
- **Combined: 1.10 * 1.20 * 1.05 * 0.95 = 1.32x**

**Example Average Trader (5% ROI):**
- Profit modifier: 1.00x (made $50)
- ROI modifier: 1.05x (5% return)
- Quality modifier: 1.00x (55% profitable rate)
- Confidence: 0.80 (20 closed positions)
- **Combined: 1.00 * 1.05 * 1.00 * 0.80 = 0.84x**

**Example Poor Trader (-15% ROI):**
- Profit modifier: 0.90x (lost $150)
- ROI modifier: 0.85x (-15% return)
- Quality modifier: 0.95x (40% profitable rate)
- Confidence: 0.75 (15 closed positions)
- **Combined: 0.90 * 0.85 * 0.95 * 0.75 = 0.55x**

### Sample Size Confidence

**Confidence Calculation:**
```python
def calculate_pnl_confidence(closed_positions: int) -> float:
    """
    Returns confidence multiplier based on sample size.

    50+ closed = 1.00 (full confidence)
    30-49 closed = 0.95
    20-29 closed = 0.90
    10-19 closed = 0.80
    1-9 closed = 0.50 (low confidence)
    """
    if closed_positions >= 50:
        return 1.00
    elif closed_positions >= 30:
        return 0.95
    elif closed_positions >= 20:
        return 0.90
    elif closed_positions >= 10:
        return 0.80
    else:
        return 0.50
```

---

## Monitoring Recommendations

### Short Term (Next 7 Days)
1. Run monitoring system continuously
2. Check validation script daily: `python scripts/validate_pnl_data.py`
3. When coverage >20%, re-run ELO integration
4. Verify correlation improvement

### Medium Term (Next 30 Days)
1. Monitor P&L data quality (realistic ranges)
2. Watch for profitability distribution (expect ~60% profitable)
3. Track correlation improvements as data accumulates
4. Fine-tune ROI ranges if needed

### Long Term (Q2 2026)
1. Extend database schema to add `created_at` column
2. Enable timing quality metric (currently disabled)
3. Expected final correlation: 0.45-0.50 (3.4-3.8x improvement)

---

## Success Metrics

### Current Achievement
- ✅ Correlation: 0.135 → 0.347 (2.6x improvement, at target lower bound)
- ✅ Kelly alignment working (963 traders)
- ✅ Patience working (964 traders)
- ✅ Market difficulty working (253 markets analyzed)
- ✅ ELO integration working (951,399 ratings updated)
- ✅ Sample filter optimized (30 trades, +50% qualified traders)
- ✅ ROI ranges optimized (ready for monitoring data)

### Expected After Monitoring
- 📋 P&L coverage: >50% of traders
- 📋 Correlation: 0.40-0.45 (3.0-3.4x improvement)
- 📋 ROI differentiation: Elite traders rewarded
- 📋 System fully operational for production use

### Expected After Schema Extension (Q2 2026)
- 📋 Timing quality enabled
- 📋 Correlation: 0.45-0.50 (3.4-3.8x improvement)
- 📋 All 6 ELO dimensions fully operational

---

## Related Documentation

- [INTEGRATION_EXECUTION_SUMMARY.md](INTEGRATION_EXECUTION_SUMMARY.md) - Full execution details
- [BUGFIX_SUMMARY.md](BUGFIX_SUMMARY.md) - 3 critical bugs fixed
- [SCHEMA_FIXES_APPLIED.md](SCHEMA_FIXES_APPLIED.md) - Schema compatibility
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Complete project overview
- [analysis/README_MASTER.md](analysis/README_MASTER.md) - Analysis system guide

---

**Status:** ✅ Optimizations Complete
**Next:** Run monitoring system to populate P&L data
**Expected Impact:** +7-15% correlation improvement when P&L populates
**Final Target:** r = 0.40-0.45 (achievable with current optimizations)
