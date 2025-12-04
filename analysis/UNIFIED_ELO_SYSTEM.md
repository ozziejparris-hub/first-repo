# Unified ELO System Documentation

**Created:** 2025-12-04
**Status:** ✅ Active
**Replaces:** weighted_consensus_system.py (now deprecated)

---

## Table of Contents

1. [Overview](#overview)
2. [Why Unify?](#why-unify)
3. [Architecture](#architecture)
4. [Quick Start](#quick-start)
5. [API Reference](#api-reference)
6. [Migration Guide](#migration-guide)
7. [Examples](#examples)
8. [Integration](#integration)

---

## Overview

The **Unified ELO System** consolidates two previous ELO implementations into a single, more powerful system:

1. ~~weighted_consensus_system.py~~ - Basic global ELO (deprecated)
2. ~~trader_specialization_analysis.py~~ - Category-specific ELO (core engine)

### Key Features

✅ **Category-Specific Ratings** - Separate ELO for Elections, Crypto, Sports, etc.
✅ **Global ELO** - Weighted average across all categories
✅ **Specialist Detection** - Automatically identify domain experts
✅ **Integration APIs** - Easy export to other analysis tools
✅ **Backward Compatible** - Existing code continues to work
✅ **Single Source of Truth** - One system for all ELO calculations

---

## Why Unify?

### Problems with Old System

**1. Duplicate Code**
- Two separate ELO implementations
- Inconsistent ratings between tools
- Maintenance burden

**2. Inaccurate Global ELO**
- Traders excel in specific domains
- A crypto expert might fail at elections
- Global average obscured specialization

**3. Poor Integration**
- Each tool calculated its own ratings
- No shared state
- Wasted computation

### Benefits of Unified System

**1. Category-Specific Accuracy**
```
Trader A:
  Global ELO: 1500 (average)
  Elections ELO: 1800 (expert!)
  Crypto ELO: 1200 (poor)

Old system: "Meh, average trader"
New system: "Elections specialist - trust them there, avoid elsewhere"
```

**2. Specialist Boosting**
- Detect traders who excel in specific categories
- Weight their predictions higher in their specialty
- Ignore them in other categories

**3. Single Calculation**
- Calculate once, use everywhere
- Consistent ratings across all tools
- Shared cache for performance

---

## Architecture

### Core Components

```
unified_elo_system.py
├── CategorySpecificELO (core engine)
│   ├── Per-category rating tracking
│   ├── ELO calculation algorithms
│   └── History tracking
│
├── UnifiedELOSystem (main interface)
│   ├── Database integration
│   ├── Market categorization
│   ├── Rating calculation
│   └── Integration methods
│
└── UnifiedWeightedConsensusWrapper (backward compatibility)
    └── Provides old API for existing code
```

### Data Structure

```python
trader_elos = {
    'trader_address': {
        'Elections': 1800,      # Strong in elections
        'Crypto': 1200,         # Weak in crypto
        'Sports': 1500,         # Average in sports
        'Geopolitics': 1650,    # Good in geopolitics
        # ... other categories
    }
}

global_elo = weighted_average_by_market_count
```

### Categories

- **Elections** - Presidential, senate, gubernatorial races
- **Geopolitics** - Wars, conflicts, international relations
- **Economics** - GDP, inflation, stock markets, corporate events
- **Crypto** - Bitcoin, Ethereum, blockchain events
- **Sports** - NFL, NBA, MLB, FIFA, championships
- **Entertainment** - Movies, celebrities, pop culture
- **Other** - Everything else

---

## Quick Start

### Basic Usage

```python
from unified_elo_system import UnifiedELOSystem

# Initialize system
system = UnifiedELOSystem()

# Calculate all ratings (do this once)
system.calculate_elo_ratings(verbose=True)

# Get trader's global ELO
global_elo = system.get_trader_global_elo('0x1234...')
print(f"Global ELO: {global_elo:.1f}")

# Get category-specific ELO
elections_elo = system.get_trader_category_elo('0x1234...', 'Elections')
print(f"Elections ELO: {elections_elo:.1f}")

# Check if specialist
is_specialist, score = system.is_specialist('0x1234...', 'Elections')
if is_specialist:
    print(f"Elections specialist! Advantage: +{score:.1f} ELO")
```

### Command-Line Usage

```bash
# Run example usage
python analysis/unified_elo_system.py

# Output shows:
# - Top traders globally
# - Top traders per category
# - Specialist detection
# - Export data summary
```

---

## API Reference

### UnifiedELOSystem

Main interface for the unified ELO system.

#### `__init__(db_path=None, api_key=None)`

Initialize the system.

**Parameters:**
- `db_path` (str, optional) - Path to SQLite database
- `api_key` (str, optional) - Polymarket API key for resolution checks

**Example:**
```python
system = UnifiedELOSystem(
    db_path='data/polymarket_tracker.db',
    api_key='your_api_key'
)
```

#### `calculate_elo_ratings(verbose=True)`

Calculate all category-specific ELO ratings from historical trades.

**Run this once after initialization before using other methods.**

**Parameters:**
- `verbose` (bool) - Print progress messages

**Time:** 5-10 minutes (depends on API rate limits)

**Example:**
```python
system.calculate_elo_ratings(verbose=True)
# Output:
# Found 2,450 trades
# Checking 523 markets...
# Updated 8,234 category-specific ratings
```

#### `get_trader_global_elo(trader_address) -> float`

Get trader's global ELO rating (weighted average across all categories).

**Parameters:**
- `trader_address` (str) - Trader's Ethereum address

**Returns:**
- `float` - Global ELO rating

**Example:**
```python
elo = system.get_trader_global_elo('0xabc123...')
# 1650.5
```

#### `get_trader_category_elo(trader_address, category) -> float`

Get trader's ELO for a specific category.

**Use this for category-aware predictions (more accurate than global).**

**Parameters:**
- `trader_address` (str) - Trader's address
- `category` (str) - One of: Elections, Geopolitics, Economics, Crypto, Sports, Entertainment, Other

**Returns:**
- `float` - Category-specific ELO rating

**Example:**
```python
elo = system.get_trader_category_elo('0xabc123...', 'Elections')
# 1850.2
```

#### `is_specialist(trader_address, category=None, min_markets=5, min_advantage=100) -> Tuple[bool, float]`

Determine if trader is a specialist.

**Specialist Criteria:**
1. At least `min_markets` trades in the category
2. Category ELO at least `min_advantage` points above global ELO

**Parameters:**
- `trader_address` (str) - Trader's address
- `category` (str, optional) - Category to check (None = find best)
- `min_markets` (int) - Minimum markets required (default: 5)
- `min_advantage` (float) - Minimum ELO advantage (default: 100)

**Returns:**
- `Tuple[bool, float]` - (is_specialist, specialization_score)

**Example:**
```python
is_spec, score = system.is_specialist('0xabc123...', 'Elections')
if is_spec:
    print(f"Elections specialist with +{score:.1f} ELO advantage")

# Auto-detect best category
is_spec, score = system.is_specialist('0xabc123...')
# Returns True if specialist in ANY category
```

#### `export_for_integration() -> Dict`

Export all ELO data for integration with other tools.

**Returns comprehensive data including:**
- All trader global ELOs
- All category-specific ELOs
- Specialist identifications
- Top traders per category
- Market counts per category

**Returns:**
- `Dict` - Complete ELO dataset

**Example:**
```python
data = system.export_for_integration()

print(f"Total traders: {data['total_traders']}")
print(f"Specialists: {len(data['specialists'])}")

# Top trader globally
top = data['top_traders_global'][0]
print(f"Top: {top['address']} - {top['elo']:.1f}")

# Top Elections trader
elections_top = data['top_traders_by_category']['Elections'][0]
print(f"Top Elections: {elections_top['address']} - {elections_top['elo']:.1f}")

# All specialist data
for spec in data['specialists']:
    print(f"{spec['address'][:10]}... - {spec['category']} specialist")
```

#### `get_top_traders(category=None, limit=10) -> List[Dict]`

Get top traders by ELO rating.

**Parameters:**
- `category` (str, optional) - Specific category (None = global)
- `limit` (int) - Number of traders to return

**Returns:**
- `List[Dict]` - Traders sorted by ELO (highest first)

**Example:**
```python
# Top 10 globally
top_global = system.get_top_traders(limit=10)
for trader in top_global:
    print(f"{trader['address'][:10]}... - {trader['elo']:.1f}")

# Top 5 Elections traders
top_elections = system.get_top_traders(category='Elections', limit=5)
for trader in top_elections:
    print(f"{trader['address'][:10]}... - {trader['elo']:.1f} ({trader['market_count']} markets)")
```

---

## Migration Guide

### From weighted_consensus_system.py

**Old Code:**
```python
from weighted_consensus_system import WeightedConsensusSystem

system = WeightedConsensusSystem()
system.calculate_elo_ratings()
elo = system.elo_system.get_elo('0x1234...')
```

**New Code (Option 1: Direct Migration):**
```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()
elo = system.get_trader_global_elo('0x1234...')
```

**New Code (Option 2: Backward Compatible):**
```python
from unified_elo_system import UnifiedWeightedConsensusWrapper

system = UnifiedWeightedConsensusWrapper()
system.calculate_elo_ratings()
elo = system.get_trader_elo('0x1234...')
```

### From trader_specialization_analysis.py

**Old Code:**
```python
from trader_specialization_analysis import TraderSpecializationAnalyzer

analyzer = TraderSpecializationAnalyzer()
analyzer.calculate_category_elos()
specialists = analyzer.identify_specialists()
```

**New Code:**
```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()

# Get specialist data
export = system.export_for_integration()
specialists = export['specialists']

# Or check individual traders
is_spec, score = system.is_specialist('0x1234...', 'Elections')
```

---

## Examples

### Example 1: Find Elections Specialists

```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()

# Get all traders
export = system.export_for_integration()

# Filter for Elections specialists
elections_specialists = [
    spec for spec in export['specialists']
    if spec['category'] == 'Elections'
]

# Sort by specialization score
elections_specialists.sort(key=lambda x: x['specialization_score'], reverse=True)

print(f"Found {len(elections_specialists)} Elections specialists:")
for spec in elections_specialists[:5]:
    print(f"\n{spec['address'][:10]}...")
    print(f"  Category ELO: {spec['category_elo']:.1f}")
    print(f"  Global ELO: {spec['global_elo']:.1f}")
    print(f"  Advantage: +{spec['specialization_score']:.1f}")
```

### Example 2: Category-Aware Consensus

```python
from unified_elo_system import UnifiedELOSystem

def weighted_prediction(market_id, market_category, trader_positions):
    """
    Calculate weighted consensus using category-specific ELOs.

    Args:
        market_id: Market identifier
        market_category: Category (e.g., 'Elections')
        trader_positions: List of (trader_address, outcome) tuples

    Returns:
        Predicted outcome with confidence score
    """
    system = UnifiedELOSystem()

    outcome_weights = {}

    for trader_address, outcome in trader_positions:
        # Use category-specific ELO for weighting
        elo = system.get_trader_category_elo(trader_address, market_category)

        # Boost specialists
        is_spec, spec_score = system.is_specialist(trader_address, market_category)
        if is_spec:
            elo += spec_score * 0.5  # 50% of advantage as boost

        # Add weight to outcome
        if outcome not in outcome_weights:
            outcome_weights[outcome] = 0
        outcome_weights[outcome] += elo

    # Find top outcome
    total_weight = sum(outcome_weights.values())
    top_outcome = max(outcome_weights, key=outcome_weights.get)
    confidence = outcome_weights[top_outcome] / total_weight * 100

    return {
        'outcome': top_outcome,
        'confidence': confidence,
        'weights': outcome_weights
    }

# Usage
prediction = weighted_prediction(
    market_id='0x789...',
    market_category='Elections',
    trader_positions=[
        ('0xaaa...', 'Yes'),
        ('0xbbb...', 'Yes'),
        ('0xccc...', 'No')
    ]
)

print(f"Prediction: {prediction['outcome']}")
print(f"Confidence: {prediction['confidence']:.1f}%")
```

### Example 3: Trader Profile Dashboard

```python
from unified_elo_system import UnifiedELOSystem

def trader_profile(trader_address):
    """Generate comprehensive trader profile."""
    system = UnifiedELOSystem()

    print("="*70)
    print(f"  TRADER PROFILE: {trader_address[:20]}...")
    print("="*70)

    # Global ELO
    global_elo = system.get_trader_global_elo(trader_address)
    print(f"\n📊 Global ELO: {global_elo:.1f}")

    # Category breakdown
    print("\n📈 Category Performance:")
    export = system.export_for_integration()
    trader_data = export['trader_data'].get(trader_address)

    if trader_data:
        categories = trader_data['categories']

        # Sort by ELO
        sorted_cats = sorted(
            categories.items(),
            key=lambda x: x[1]['elo'],
            reverse=True
        )

        for category, data in sorted_cats:
            if data['market_count'] > 0:
                elo = data['elo']
                count = data['market_count']
                diff = elo - global_elo

                indicator = "⭐" if diff > 100 else "✅" if diff > 0 else "❌"

                print(f"  {indicator} {category:15s}: {elo:7.1f} ELO ({count:3d} markets) [{diff:+6.1f}]")

    # Specializations
    print("\n🎯 Specializations:")
    specializations = []
    for category in ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']:
        is_spec, score = system.is_specialist(trader_address, category)
        if is_spec:
            specializations.append((category, score))

    if specializations:
        specializations.sort(key=lambda x: x[1], reverse=True)
        for category, score in specializations:
            print(f"  ⭐ {category} Specialist (advantage: +{score:.1f} ELO)")
    else:
        print("  ❌ No specializations detected (Generalist or Insufficient Data)")

    print("\n" + "="*70)

# Usage
trader_profile('0x1234567890abcdef...')
```

### Example 4: Compare Two Traders

```python
from unified_elo_system import UnifiedELOSystem

def compare_traders(trader1, trader2):
    """Compare two traders across all categories."""
    system = UnifiedELOSystem()

    print("="*70)
    print(f"  TRADER COMPARISON")
    print("="*70)
    print(f"Trader A: {trader1[:20]}...")
    print(f"Trader B: {trader2[:20]}...")
    print("="*70)

    # Global comparison
    elo1 = system.get_trader_global_elo(trader1)
    elo2 = system.get_trader_global_elo(trader2)

    print(f"\n📊 Global ELO:")
    print(f"  Trader A: {elo1:.1f}")
    print(f"  Trader B: {elo2:.1f}")
    print(f"  Winner: {'Trader A' if elo1 > elo2 else 'Trader B'} (+{abs(elo1-elo2):.1f})")

    # Category comparison
    print(f"\n📈 Category-by-Category:")

    categories = ['Elections', 'Geopolitics', 'Economics', 'Crypto', 'Sports', 'Entertainment']

    wins_a = 0
    wins_b = 0

    for category in categories:
        cat_elo1 = system.get_trader_category_elo(trader1, category)
        cat_elo2 = system.get_trader_category_elo(trader2, category)

        count1 = system.elo_system.get_market_count(trader1, category)
        count2 = system.elo_system.get_market_count(trader2, category)

        if count1 > 0 or count2 > 0:
            winner = "A" if cat_elo1 > cat_elo2 else "B"
            diff = abs(cat_elo1 - cat_elo2)

            if cat_elo1 > cat_elo2:
                wins_a += 1
            else:
                wins_b += 1

            print(f"  {category:15s}: A={cat_elo1:6.1f} ({count1:2d}) vs B={cat_elo2:6.1f} ({count2:2d}) → {winner} wins (+{diff:.1f})")

    print(f"\n🏆 Overall: Trader A won {wins_a} categories, Trader B won {wins_b} categories")
    print("="*70)

# Usage
compare_traders('0xaaa...', '0xbbb...')
```

---

## Integration

### With market_confidence_meter.py

Replace WeightedConsensusSystem with UnifiedELOSystem:

```python
# OLD
from weighted_consensus_system import WeightedConsensusSystem
self.consensus_system = WeightedConsensusSystem(db_path, api_key)

# NEW
from unified_elo_system import UnifiedELOSystem
self.elo_system = UnifiedELOSystem(db_path, api_key)
```

Then use category-specific ratings:

```python
# For an Elections market
market_category = 'Elections'
for trader in traders:
    # Use category-specific ELO instead of global
    elo = self.elo_system.get_trader_category_elo(trader, market_category)

    # Boost specialists
    is_spec, spec_score = self.elo_system.is_specialist(trader, market_category)
    if is_spec:
        elo += spec_score * 0.5

    # Use in weighting
    weight = elo / 1500.0  # Normalize
```

### With copy_trade_detector.py

Use specialist data to filter leaders:

```python
from unified_elo_system import UnifiedELOSystem

elo_system = UnifiedELOSystem()
elo_system.calculate_elo_ratings()

# When detecting copy-trade leaders, prioritize specialists
export = elo_system.export_for_integration()

# Filter for high-ELO specialists only
high_value_leaders = []
for spec in export['specialists']:
    if spec['category_elo'] > 1700 and spec['specialization_score'] > 150:
        high_value_leaders.append(spec['address'])

# Use these as "verified alpha" traders to follow
```

### With analysis_scheduler.py

Add unified ELO calculation as a phase:

```python
from unified_elo_system import UnifiedELOSystem

# In Phase 1 (Independent Analysis)
print("Calculating Unified ELO Ratings...")
elo_system = UnifiedELOSystem()
elo_system.calculate_elo_ratings(verbose=False)

# Export for other tools
elo_export = elo_system.export_for_integration()

# Pass to later phases
# Other tools can now use category-specific ratings
```

---

## Performance

### Calculation Time

- **First run:** 5-10 minutes (API rate limiting)
- **Cached run:** <1 minute (if resolutions cached)

### Memory Usage

- ~50-100 MB for 1,000 traders
- Scales linearly with trader count

### Optimization Tips

1. **Cache resolutions:** Market resolutions are cached in-memory
2. **Batch processing:** Process all markets in one pass
3. **Parallel calculation:** Could parallelize category calculations (future)

---

## Troubleshooting

### "No traders found"

**Cause:** Database empty or path incorrect

**Fix:**
```python
# Check database path
system = UnifiedELOSystem(db_path='correct/path/to/db')

# Verify trades exist
trades = system.get_all_trades()
print(f"Found {len(trades)} trades")
```

### "All ELOs are 1500"

**Cause:** No resolved markets (can't calculate performance)

**Fix:**
- Wait for markets to resolve
- Check API key is valid
- Verify markets are actually resolved on Polymarket

### "Specialist detection returns False for everyone"

**Cause:** Thresholds too strict or insufficient data

**Fix:**
```python
# Lower thresholds
is_spec, score = system.is_specialist(
    trader,
    category,
    min_markets=3,      # Lower from 5
    min_advantage=50    # Lower from 100
)
```

---

## Future Enhancements

### Planned for v2.0

1. **Time decay** - Recent performance weighted more heavily
2. **Confidence intervals** - Statistical confidence in ratings
3. **Cross-category correlations** - Detect related specialties
4. **Market difficulty** - Adjust for easy vs hard markets
5. **Ensemble methods** - Combine multiple rating systems

### Research Ideas

- **Bayesian ELO** - Probabilistic rating updates
- **Skill curves** - Track trader improvement over time
- **Meta-learning** - Learn which categories predict others
- **Automated rebalancing** - Periodic rating recalculation

---

## Appendix

### Category Keywords

See `CATEGORY_KEYWORDS` dictionary in unified_elo_system.py for full keyword lists used in auto-categorization.

### ELO Formula

```
Expected Score: E = 1 / (1 + 10^((ELO_opponent - ELO_player) / 400))

New ELO: ELO_new = ELO_old + K * (Actual - Expected)

Where:
- K = K-factor (volatility, default 32)
- Actual = 1.0 for win, 0.0 for loss
- Adjustments for bet size and market difficulty
```

### File Structure

```
analysis/
├── unified_elo_system.py          # Main unified system
├── weighted_consensus_system.py   # Deprecated (kept for compatibility)
├── trader_specialization_analysis.py  # Contains original CategorySpecificELO
└── UNIFIED_ELO_SYSTEM.md          # This documentation
```

---

## Support

For issues, questions, or contributions:
- Check existing analysis tools documentation
- Review code comments in unified_elo_system.py
- Test with small datasets first
- Verify database schema matches expected format

---

**Last Updated:** 2025-12-04
**Version:** 1.0
**Status:** Production Ready
