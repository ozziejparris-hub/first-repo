# Behavioral Integration for Unified ELO System

**Date:** 2025-12-04
**Status:** ✅ Integrated
**Enhancement to:** unified_elo_system.py

---

## Overview

The Unified ELO System now incorporates behavioral modifiers that adjust ELO ratings based on trader behavior patterns beyond simple win/loss records.

### Key Idea

**Traditional ELO captures wins/losses, but misses important signals:**
- A trader with 70% win rate from 10 lucky bets on one market
- A trader with 70% win rate from 200 disciplined bets across 50 markets

Traditional ELO treats them equally. **Behavioral modifiers distinguish them.**

---

## Four Behavioral Dimensions

### 1. Consistency Modifier (0.92x - 1.10x)

**Measures:** Bet size consistency (coefficient of variation)

**Logic:**
- Very Consistent (CV < 30%) → 1.10x
- Moderately Consistent (CV 30-60%) → 1.05x
- Variable (CV 60-100%) → 0.98x
- Highly Variable (CV > 100%) → 0.92x

**Why it matters:** Consistent traders are disciplined. Their ELO represents true skill, not variance.

**Example:**
```
Trader A: Bets $50, $48, $52, $51 (CV=3%) → Very Consistent → 1.10x
Trader B: Bets $10, $200, $5, $150 (CV=150%) → Highly Variable → 0.92x
```

### 2. Diversification Modifier (0.93x - 1.08x)

**Measures:** Market spread (unique markets / total trades)

**Logic:**
- Excellent (≥70% unique markets) → 1.08x
- Good (60-69%) → 1.05x
- Moderate (40-59%) → 1.02x
- Neutral (30-39%) → 1.00x
- Concentrated (20-29%) → 0.97x
- Very Concentrated (<20%) → 0.93x

**Why it matters:** Diversified traders demonstrate broader skill, less vulnerable to category-specific luck.

**Example:**
```
Trader A: 100 trades across 75 markets (75% diversification) → 1.08x
Trader B: 100 trades on 15 markets (15% diversification) → 0.93x (lucky on one category?)
```

### 3. Trading Style Modifier (0.92x - 1.12x)

**Measures:** Behavioral classification from trading patterns

**Logic:**
- Power User → 1.12x (high volume + high frequency + high diversification)
- Active Trader → 1.08x (engaged, active)
- High Volume Specialist → 1.06x (focused, disciplined volume)
- Market Specialist → 1.05x (niche expertise)
- Strategic Explorer → 1.03x (thoughtful diversification)
- Cautious Diversifier → 1.02x (risk-aware)
- General Trader → 1.00x (neutral)
- Big Better → 0.98x (high variance, possible overconfidence)
- Micro Trader → 0.96x (limited capital, less conviction)
- Weekend Warrior → 0.94x (casual, less engaged)
- Casual Trader → 0.92x (low engagement)

**Why it matters:** Sophistication and engagement correlate with skill.

### 4. Activity Modifier (0.97x - 1.06x)

**Measures:** Trading frequency and activity patterns

**Logic:**
- High frequency + high diversification → 1.06x (sophisticated active)
- Medium frequency (1-5 trades/day) → 1.02x (engaged)
- Low frequency (0.5-1 trade/day) → 1.00x (neutral)
- High frequency + low diversification → 0.98x (churning same markets)
- Very low frequency (<0.5 trades/day) → 0.97x (insufficient engagement)

**Bonuses/Penalties:**
- Active >70% of trading days → +1.03x (consistent presence)
- Active <30% of trading days → 0.98x (sporadic, bursty)

**Why it matters:** Engaged traders are less likely to be lucky flukes.

---

## Combined Multiplier

All four dimensions multiply together:

```
Combined = Consistency × Diversification × Style × Activity
```

**Clamped to [0.80, 1.40]** (max ±40% adjustment)

### Example Calculation

```
Power User with Very Consistent bets and Good Diversification:

Consistency: 1.10x (Very Consistent)
Diversification: 1.05x (Good)
Style: 1.12x (Power User)
Activity: 1.02x (Medium frequency)

Combined: 1.10 × 1.05 × 1.12 × 1.02 = 1.31x

Base ELO: 1600
Adjusted ELO: 1600 × 1.31 = 2096

This trader's ELO is boosted by 31% due to excellent behavioral patterns.
```

---

## API Usage

### Get Adjusted ELO

```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()

trader = '0x1234...'

# Base ELO (traditional)
base_elo = system.get_trader_global_elo(trader)

# Adjusted ELO (with behavioral modifiers)
adjusted_elo = system.get_trader_global_elo(trader, apply_behavioral=True)

print(f"Base: {base_elo:.0f}")
print(f"Adjusted: {adjusted_elo:.0f}")
print(f"Boost: {(adjusted_elo / base_elo - 1) * 100:.1f}%")
```

### Get Behavioral Breakdown

```python
# Get detailed breakdown
behavior_data = system.calculate_behavioral_multiplier(trader)

print(f"Consistency: {behavior_data['consistency']:.3f}")
print(f"Diversification: {behavior_data['diversification']:.3f}")
print(f"Style: {behavior_data['trading_style']:.3f}")
print(f"Activity: {behavior_data['activity']:.3f}")
print(f"Combined: {behavior_data['combined_multiplier']:.3f}")
print(f"\n{behavior_data['breakdown']}")
```

### Category-Specific with Behavioral

```python
# Apply behavioral modifiers to category-specific ELO
elections_base = system.get_trader_category_elo(trader, 'Elections')
elections_adjusted = system.get_trader_category_elo(trader, 'Elections', apply_behavioral=True)

print(f"Elections Base: {elections_base:.0f}")
print(f"Elections Adjusted: {elections_adjusted:.0f}")
```

### Export Behavioral Analysis

```python
# Get behavioral data for all traders
export = system.export_behavioral_analysis()

print(f"Total traders: {export['total_traders']}")
print(f"With behavioral data: {export['traders_with_behavior']}")
print(f"Avg consistency modifier: {export['avg_consistency_modifier']:.3f}")
print(f"Avg diversification modifier: {export['avg_diversification_modifier']:.3f}")
print(f"Avg style modifier: {export['avg_style_modifier']:.3f}")
print(f"Avg activity modifier: {export['avg_activity_modifier']:.3f}")

# Top 10 traders by adjusted ELO
for trader_data in export['top_behavioral_traders']:
    print(f"{trader_data['trader'][:10]}... "
          f"Base: {trader_data['base_elo']:.0f} → "
          f"Adjusted: {trader_data['adjusted_elo']:.0f} "
          f"({trader_data['behavioral_multiplier']:.2f}x)")
```

### Generate CSV Report

```python
# Generate behavioral modifiers report
report_path = system.generate_behavioral_report()

print(f"Report saved to: {report_path}")
# Creates: reports/behavioral_modifiers_YYYYMMDD.csv

# Columns:
# - trader_address
# - base_global_elo
# - consistency_modifier
# - diversification_modifier
# - trading_style_modifier
# - activity_modifier
# - combined_multiplier
# - adjusted_global_elo
# - trading_style (classification)
# - bet_consistency
# - diversification_score
# - trades_per_day
```

---

## Integration with export_for_integration()

Behavioral data is automatically included in the main export:

```python
export = system.export_for_integration()

# Access behavioral modifiers
for trader, modifiers in export['behavioral_modifiers'].items():
    print(f"{trader[:10]}...")
    print(f"  Consistency: {modifiers['consistency']:.3f}")
    print(f"  Diversification: {modifiers['diversification']:.3f}")
    print(f"  Style: {modifiers['style']:.3f}")
    print(f"  Activity: {modifiers['activity']:.3f}")
    print(f"  Combined: {modifiers['combined']:.3f}")
```

---

## Caching

Behavioral data is expensive to calculate, so it's cached for 24 hours:

```python
# First call: loads and caches behavioral data
behavior1 = system.calculate_behavioral_multiplier(trader)
# Output: [BEHAVIORAL] Loading trader behavioral data...
#         [BEHAVIORAL] Loaded data for 157 traders

# Second call: uses cache
behavior2 = system.calculate_behavioral_multiplier(trader)
# Output: [BEHAVIORAL] Using cached behavioral data (age: 0.0 hours)

# Force refresh
system._load_behavioral_data(force_refresh=True)
# Output: [BEHAVIORAL] Loading trader behavioral data...
```

---

## When to Use Behavioral Adjustments

### Use Behavioral Adjustments When:

1. **Ranking traders for copy-trading** - You want reliable, disciplined traders
2. **Building consensus models** - Weight sophisticated traders higher
3. **Identifying high-quality signals** - Filter out lucky casual traders
4. **Portfolio construction** - Select traders with proven behavioral quality

### Don't Use Behavioral Adjustments When:

1. **Pure skill assessment** - Traditional ELO already captures win/loss skill
2. **Short-term predictions** - Behavioral patterns are long-term indicators
3. **Comparing across different time periods** - Behavioral data may be incomplete

---

## Example Use Cases

### Use Case 1: Filter High-Quality Copy-Trade Leaders

```python
# Find leaders with excellent behavioral patterns
export = system.export_for_integration()

high_quality_leaders = []
for trader, modifiers in export['behavioral_modifiers'].items():
    if modifiers['combined'] > 1.15:  # 15%+ behavioral boost
        elo_adjusted = system.get_trader_global_elo(trader, apply_behavioral=True)
        if elo_adjusted > 1700:  # High adjusted ELO
            high_quality_leaders.append({
                'address': trader,
                'adjusted_elo': elo_adjusted,
                'behavioral_multiplier': modifiers['combined']
            })

high_quality_leaders.sort(key=lambda x: x['adjusted_elo'], reverse=True)

print(f"Found {len(high_quality_leaders)} high-quality leaders:")
for leader in high_quality_leaders[:10]:
    print(f"{leader['address'][:10]}... "
          f"Adjusted ELO: {leader['adjusted_elo']:.0f} "
          f"(Boost: {leader['behavioral_multiplier']:.2f}x)")
```

### Use Case 2: Weighted Consensus with Behavioral Boost

```python
def weighted_consensus_with_behavior(market_category, trader_positions):
    """
    Calculate weighted consensus using category-specific ELOs
    with behavioral adjustments.
    """
    system = UnifiedELOSystem()

    outcome_weights = {}
    for trader, outcome in trader_positions:
        # Use category-specific ELO with behavioral adjustment
        elo = system.get_trader_category_elo(
            trader, market_category, apply_behavioral=True
        )

        # Add to outcome weight
        outcome_weights[outcome] = outcome_weights.get(outcome, 0) + elo

    # Find winner
    total = sum(outcome_weights.values())
    top_outcome = max(outcome_weights, key=outcome_weights.get)
    confidence = outcome_weights[top_outcome] / total * 100

    return {
        'outcome': top_outcome,
        'confidence': confidence,
        'weights': outcome_weights
    }
```

### Use Case 3: Identify Lucky vs Skilled Traders

```python
# Find traders with good ELO but poor behavioral patterns
# (potentially lucky traders)

suspicious_traders = []
for trader in system.elo_system.get_all_traders():
    base_elo = system.get_trader_global_elo(trader)

    if base_elo > 1600:  # High base ELO
        behavior_mult = system.calculate_behavioral_multiplier(trader)
        multiplier = behavior_mult['combined_multiplier']

        if multiplier < 0.90:  # Poor behavioral patterns (10%+ penalty)
            suspicious_traders.append({
                'trader': trader,
                'base_elo': base_elo,
                'behavioral_multiplier': multiplier,
                'adjusted_elo': base_elo * multiplier,
                'breakdown': behavior_mult['breakdown']
            })

print(f"Found {len(suspicious_traders)} potentially lucky traders:")
for trader_data in suspicious_traders[:5]:
    print(f"\n{trader_data['trader'][:10]}...")
    print(f"  Base ELO: {trader_data['base_elo']:.0f}")
    print(f"  Behavioral Penalty: {trader_data['behavioral_multiplier']:.2f}x")
    print(f"  Adjusted ELO: {trader_data['adjusted_elo']:.0f}")
    print(f"  {trader_data['breakdown']}")
```

---

## Performance Impact

### Calculation Time

- **First behavioral analysis:** 30-60 seconds (analyzes all trades)
- **Cached access:** <1 second (24-hour cache)
- **Individual modifier calculation:** <1ms (reads from cache)

### Memory Usage

- **Behavioral cache:** ~5-10 MB for 200 traders
- **Negligible overhead** on top of existing ELO system

---

## Validation

### How to Validate Behavioral Integration

1. **Check modifiers are in range:**
```python
behavior = system.calculate_behavioral_multiplier(trader)
assert 0.80 <= behavior['combined_multiplier'] <= 1.40
assert 0.92 <= behavior['consistency'] <= 1.10
assert 0.93 <= behavior['diversification'] <= 1.08
assert 0.92 <= behavior['trading_style'] <= 1.12
assert 0.97 <= behavior['activity'] <= 1.06
```

2. **Check adjusted ELO differs from base:**
```python
base = system.get_trader_global_elo(trader)
adjusted = system.get_trader_global_elo(trader, apply_behavioral=True)
assert adjusted != base  # Should differ if trader has behavioral data
```

3. **Check CSV report generates:**
```python
report_path = system.generate_behavioral_report()
assert os.path.exists(report_path)
```

4. **Check export includes behavioral data:**
```python
export = system.export_for_integration()
assert 'behavioral_modifiers' in export
assert 'behavioral_analysis_timestamp' in export
```

---

## Troubleshooting

### "All behavioral multipliers are 1.00"

**Cause:** No behavioral data loaded

**Fix:**
```python
# Force refresh
system._load_behavioral_data(force_refresh=True)
```

### "Behavioral analysis failed"

**Cause:** trading_behavior_analysis.py not found or import error

**Fix:**
```python
# Check import works
from trading_behavior_analysis import TradingBehaviorAnalyzer
analyzer = TradingBehaviorAnalyzer()
```

### "Adjusted ELO same as base ELO"

**Cause:** Trader has no behavioral data

**Fix:**
```python
# Check if trader has behavioral data
behavior_data = system._load_behavioral_data()
if trader in behavior_data:
    print("Trader has behavioral data")
else:
    print("Trader has NO behavioral data (returns 1.0x multiplier)")
```

---

## Design Philosophy

### Why These Specific Modifiers?

1. **Consistency** - Reliable traders are more trustworthy
2. **Diversification** - Broad skill > category-specific luck
3. **Trading Style** - Sophistication correlates with skill
4. **Activity** - Engagement indicates commitment

### Why These Ranges?

- **Max boost: 1.40x (40%)** - Prevents over-weighting behavioral factors
- **Max penalty: 0.80x (20%)** - Prevents over-penalizing casual traders
- **Neutral: 1.00x** - No behavioral data = no adjustment (fair)

### Why Multiply Instead of Add?

**Multiplicative scales with ELO magnitude:**
- Elite trader (2000 ELO) with 1.3x boost → 2600 ELO (still elite)
- Average trader (1500 ELO) with 1.3x boost → 1950 ELO (boosted appropriately)

**Additive would be less fair:**
- Elite trader (2000 ELO) + 300 → 2300 ELO (13% boost)
- Average trader (1500 ELO) + 300 → 1800 ELO (20% boost)

---

## Backward Compatibility

**All existing code continues to work:**

```python
# Old code (still works, no behavioral adjustments)
elo = system.get_trader_global_elo(trader)

# New code (opt-in behavioral adjustments)
elo = system.get_trader_global_elo(trader, apply_behavioral=True)
```

**apply_behavioral parameter defaults to False** - no breaking changes.

---

## Future Enhancements

### Planned for v2.0

1. **Time-weighted behavioral modifiers** - Recent behavior matters more
2. **Category-specific behavioral patterns** - Different modifiers per category
3. **Behavioral trend analysis** - Improving/declining behavioral quality over time
4. **Peer comparison** - Compare trader's behavior to category peers
5. **Behavioral confidence intervals** - Statistical confidence in modifiers

---

## Summary

**Behavioral integration adds a layer of quality assessment on top of ELO:**

- **Traditional ELO:** Skill from wins/losses
- **Behavioral Modifiers:** Reliability, sophistication, engagement

**Result:** More accurate trader assessment that distinguishes:
- Lucky casual traders from skilled professionals
- One-market wonders from diversified experts
- Volatile big bettors from consistent strategists

**Usage:** Opt-in with `apply_behavioral=True` parameter

**Performance:** Minimal overhead (<1ms per trader with caching)

**Compatibility:** 100% backward compatible

---

**Last Updated:** 2025-12-04
**Version:** 1.0
**Status:** Production Ready
