# Unified ELO System - Quick Start Guide

**For:** Developers integrating with the unified ELO system
**Time to read:** 5 minutes
**See also:** [UNIFIED_ELO_SYSTEM.md](UNIFIED_ELO_SYSTEM.md) (full documentation)

---

## What Is This?

The **Unified ELO System** rates trader skill using category-specific ELO ratings.

**Key Idea:** A trader might be great at Elections but terrible at Crypto. Using category-specific ratings gives you more accurate predictions than a single global rating.

---

## Installation

No installation needed - it's already in your analysis/ directory.

```bash
# File location
analysis/unified_elo_system.py
```

---

## 30-Second Usage

```python
from unified_elo_system import UnifiedELOSystem

# 1. Initialize
system = UnifiedELOSystem()

# 2. Calculate ratings (do this once)
system.calculate_elo_ratings(verbose=True)

# 3. Get trader's category-specific ELO
elo = system.get_trader_category_elo('0x1234...', 'Elections')

# 4. Check if they're a specialist
is_specialist, score = system.is_specialist('0x1234...', 'Elections')
```

That's it!

---

## Common Use Cases

### Use Case 1: Weight Predictions by Category ELO

```python
def predict_market(market_category, trader_positions):
    """
    Predict market outcome using category-specific ELO weights.

    Args:
        market_category: 'Elections', 'Crypto', 'Sports', etc.
        trader_positions: List of (trader_address, outcome) tuples

    Returns:
        Predicted outcome with confidence
    """
    system = UnifiedELOSystem()

    outcome_weights = {}
    for trader, outcome in trader_positions:
        # Use category-specific ELO (more accurate!)
        elo = system.get_trader_category_elo(trader, market_category)

        # Add weight
        outcome_weights[outcome] = outcome_weights.get(outcome, 0) + elo

    # Find winner
    top_outcome = max(outcome_weights, key=outcome_weights.get)
    confidence = outcome_weights[top_outcome] / sum(outcome_weights.values())

    return top_outcome, confidence

# Usage
outcome, conf = predict_market('Elections', [
    ('0xaaa...', 'Yes'),
    ('0xbbb...', 'Yes'),
    ('0xccc...', 'No')
])

print(f"Prediction: {outcome} ({conf*100:.1f}% confidence)")
```

### Use Case 2: Find Specialists to Follow

```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()

# Get all specialists
export = system.export_for_integration()
specialists = export['specialists']

# Filter for Elections experts
elections_experts = [
    s for s in specialists
    if s['category'] == 'Elections' and s['category_elo'] > 1700
]

# Sort by specialization score
elections_experts.sort(key=lambda x: x['specialization_score'], reverse=True)

print(f"Top 5 Elections Specialists:")
for i, expert in enumerate(elections_experts[:5], 1):
    print(f"{i}. {expert['address'][:10]}... - {expert['category_elo']:.1f} ELO")
```

### Use Case 3: Boost Specialists in Predictions

```python
def weighted_prediction_with_boost(market_category, trader_positions):
    """Same as Use Case 1, but boost specialists."""
    system = UnifiedELOSystem()

    outcome_weights = {}
    for trader, outcome in trader_positions:
        elo = system.get_trader_category_elo(trader, market_category)

        # Check if specialist - boost them!
        is_spec, spec_score = system.is_specialist(trader, market_category)
        if is_spec:
            elo += spec_score * 0.5  # 50% of advantage as boost

        outcome_weights[outcome] = outcome_weights.get(outcome, 0) + elo

    top_outcome = max(outcome_weights, key=outcome_weights.get)
    confidence = outcome_weights[top_outcome] / sum(outcome_weights.values())

    return top_outcome, confidence
```

---

## Categories

The system tracks 7 categories:

| Category | Examples |
|----------|----------|
| **Elections** | Presidential races, senate elections, gubernatorial |
| **Geopolitics** | Wars, conflicts, international relations |
| **Economics** | GDP, inflation, stock markets, corporate events |
| **Crypto** | Bitcoin, Ethereum, blockchain events |
| **Sports** | NFL, NBA, MLB, FIFA, championships |
| **Entertainment** | Movies, celebrities, pop culture |
| **Other** | Everything else |

Markets are auto-categorized by keywords in their titles.

---

## Key Methods

### `get_trader_category_elo(trader, category)`
→ Returns trader's ELO for specific category (float)

**Use this for category-aware predictions.**

```python
elo = system.get_trader_category_elo('0x1234...', 'Elections')
# 1850.2
```

### `get_trader_global_elo(trader)`
→ Returns trader's global ELO (weighted average)

**Use this for overall skill assessment.**

```python
elo = system.get_trader_global_elo('0x1234...')
# 1650.5
```

### `is_specialist(trader, category)`
→ Returns (is_specialist: bool, score: float)

**Use this to identify domain experts.**

```python
is_spec, score = system.is_specialist('0x1234...', 'Elections')
if is_spec:
    print(f"Elections specialist! Advantage: +{score:.1f}")
```

### `export_for_integration()`
→ Returns Dict with all data

**Use this to get everything at once.**

```python
data = system.export_for_integration()

# Access data
top_global = data['top_traders_global']
top_elections = data['top_traders_by_category']['Elections']
all_specialists = data['specialists']
trader_data = data['trader_data']['0x1234...']
```

---

## Migration from Old System

### If you're using `weighted_consensus_system.py`:

**Old:**
```python
from weighted_consensus_system import WeightedConsensusSystem

system = WeightedConsensusSystem()
system.calculate_elo_ratings()
elo = system.elo_system.get_elo('0x1234...')
```

**New:**
```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()
elo = system.get_trader_global_elo('0x1234...')

# Or better - use category-specific:
elo = system.get_trader_category_elo('0x1234...', 'Elections')
```

---

## Performance

- **First calculation:** 5-10 minutes (API rate limiting)
- **Memory usage:** ~50-100 MB
- **Subsequent calls:** Instant (data cached)

**Tip:** Calculate once, export, and reuse:

```python
# Calculate once
system = UnifiedELOSystem()
system.calculate_elo_ratings()
export = system.export_for_integration()

# Now use export everywhere - no recalculation needed
trader_elo = export['trader_data']['0x1234...']['categories']['Elections']['elo']
```

---

## Troubleshooting

### "All ELOs are 1500"
→ No resolved markets yet. Wait for markets to resolve or check API key.

### "No specialists found"
→ Thresholds too strict. Lower them:
```python
is_spec, score = system.is_specialist(
    trader, category,
    min_markets=3,      # Lower from default 5
    min_advantage=50    # Lower from default 100
)
```

### "Takes too long to calculate"
→ API rate limiting. This is normal. First run takes 5-10 minutes.

---

## Examples in Action

### market_confidence_meter.py Integration

```python
from unified_elo_system import UnifiedELOSystem

class MarketConfidenceMeter:
    def __init__(self, db_path=None):
        self.elo_system = UnifiedELOSystem(db_path)
        self.elo_system.calculate_elo_ratings(verbose=False)

    def calculate_confidence(self, market_id, market_category, trader_positions):
        """Calculate confidence using category-specific ELOs."""
        outcome_weights = {}

        for trader, outcome in trader_positions:
            # Category-specific ELO
            elo = self.elo_system.get_trader_category_elo(trader, market_category)

            # Boost specialists
            is_spec, spec_score = self.elo_system.is_specialist(
                trader, market_category
            )
            if is_spec:
                elo += spec_score * 0.5

            outcome_weights[outcome] = outcome_weights.get(outcome, 0) + elo

        # Calculate confidence
        total = sum(outcome_weights.values())
        top_outcome = max(outcome_weights, key=outcome_weights.get)
        confidence = outcome_weights[top_outcome] / total * 100

        return {
            'outcome': top_outcome,
            'confidence': confidence,
            'category': market_category
        }
```

---

## When to Use What

| Scenario | Method to Use | Why |
|----------|---------------|-----|
| Predicting Elections market | `get_trader_category_elo(trader, 'Elections')` | Category-specific is more accurate |
| Overall trader ranking | `get_trader_global_elo(trader)` | Single number for leaderboard |
| Finding domain experts | `is_specialist(trader, category)` | Identifies true specialists |
| Building dashboards | `export_for_integration()` | Get all data at once |
| Copy-trade leader filtering | `export['specialists']` + filter by ELO | Find high-value traders |

---

## Full Documentation

For complete API reference, examples, and architecture details:

→ [UNIFIED_ELO_SYSTEM.md](UNIFIED_ELO_SYSTEM.md)

For implementation details and migration guide:

→ [ELO_UNIFICATION_SUMMARY.md](ELO_UNIFICATION_SUMMARY.md)

---

## Support

Questions? Check:
1. This quick start guide (you're here)
2. Full documentation (UNIFIED_ELO_SYSTEM.md)
3. Code comments in unified_elo_system.py
4. Example usage at bottom of unified_elo_system.py

---

**Last Updated:** 2025-12-04
**Version:** 1.0
