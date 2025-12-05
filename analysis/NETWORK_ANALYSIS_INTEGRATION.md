# Network Analysis Integration for Unified ELO System

**Date:** 2025-12-05
**Status:** ✅ Integrated
**Enhancement to:** unified_elo_system.py

---

## Overview

The Unified ELO System now incorporates network analysis (correlation matrix and copy-trade detection) to filter copy-traders from consensus calculations and reward independent traders with genuine signals.

### Key Idea

**Traditional ELO misses network effects:**
- A trader with 70% win rate who copies all trades from another trader
- A trader with 70% win rate with independent, uncorrelated positions

Traditional ELO treats them equally. **Network filtering excludes the first, rewards the second.**

---

## Three Network Dimensions

### 1. Independence Modifier (0.5x - 1.25x)

**Measures:** Correlation with other traders (independence score 0-100)

**Logic:**
- Very Independent (≥90) → 1.25x (unique signals)
- High Independence (80-89) → 1.20x
- Good Independence (70-79) → 1.15x
- Moderate Independence (60-69) → 1.10x
- Neutral (50-59) → 1.00x
- Some Correlation (40-49) → 0.95x
- Moderately Correlated (30-39) → 0.90x
- Highly Correlated (20-29) → 0.80x
- Very Correlated (10-19) → 0.65x
- Likely Copy-Trader (<10) → 0.50x

**Independence Score Formula:**
```
Independence Score = (1 - avg_correlation) × 100
```

**Why it matters:** Independent traders have genuine signals, not copied positions.

**Example:**
```
Trader A: avg_correlation = 0.05 → Independence Score = 95 → 1.25x
Trader B: avg_correlation = 0.92 → Independence Score = 8 → 0.50x
```

### 2. Copy-Trader Penalty (0.0x - 1.0x)

**Measures:** Copy-trading detection (follower/leader identification)

**Logic:**
- Not a copy-trader → 1.00x (no penalty)
- Light copier (copy_score ≤ 0.6) → 0.75x
- Moderate copier (copy_score ≤ 0.7) → 0.50x
- Heavy copier (copy_score ≤ 0.8) → 0.25x
- Confirmed copier (copy_score > 0.8) → 0.00x (complete exclusion)

**Copy Score:** Confidence level (0-1) that trader is copying others

**Why it matters:** Copy-traders double-count signals, skew consensus, provide no new information.

**Example:**
```
Trader A: Not a follower → 1.00x
Trader B: Follower with copy_score 0.85 → 0.00x (EXCLUDED)
```

### 3. Cluster Penalty (0.5x - 1.0x)

**Measures:** Suspicious correlation clusters (coordinated trading)

**Logic:**
- Not in cluster → 1.00x (no penalty)
- LOOSE cluster (avg_corr < 0.7) → 0.90x (light penalty)
- TIGHT cluster (avg_corr ≥ 0.7) → 0.75x (moderate penalty)
- SUSPICIOUS cluster (avg_corr ≥ 0.8) → 0.50x (heavy penalty)

**Why it matters:** Coordinated trading suggests manipulation or collusion.

**Example:**
```
Trader A: Not in cluster → 1.00x
Trader B: SUSPICIOUS cluster (avg_corr 0.85) → 0.50x
```

---

## Combined Modifier

All three dimensions multiply together:

```
Combined = Independence × Copy-Trader Penalty × Cluster Penalty
```

**Range: 0.0-1.25x**

**Exclusion Logic:**
```python
should_exclude = (is_follower and copy_score > 0.7) or (combined_modifier < 0.1)
```

If excluded, trader returns ELO = 0.0 when `apply_network=True`

### Example Calculation

```
Independent Trader with No Copy-Trading:

Independence: 1.25x (score 92/100)
Copy-Trader: 1.00x (not a follower)
Cluster: 1.00x (not in cluster)

Combined: 1.25 × 1.00 × 1.00 = 1.25x

Base ELO: 1600
Adjusted ELO: 2000 (25% boost!)

This trader's ELO is boosted by 25% for having independent signals.
```

```
Copy-Trader in Suspicious Cluster:

Independence: 0.50x (score 8/100, highly correlated)
Copy-Trader: 0.00x (follower with copy_score 0.85)
Cluster: 0.50x (SUSPICIOUS cluster)

Combined: 0.50 × 0.00 × 0.50 = 0.00x
Should Exclude: YES

Base ELO: 1600
Adjusted ELO: 0.0 (EXCLUDED from consensus)

This trader is completely excluded due to confirmed copy-trading.
```

---

## API Usage

### Get Adjusted ELO with Network Filtering

```python
from unified_elo_system import UnifiedELOSystem

system = UnifiedELOSystem()
system.calculate_elo_ratings()

trader = '0x1234...'

# Base ELO (traditional)
base_elo = system.get_trader_global_elo(trader)

# Adjusted ELO (with network filtering)
adjusted_elo = system.get_trader_global_elo(trader, apply_network=True)

if adjusted_elo == 0.0:
    print(f"Trader EXCLUDED (copy-trader)")
else:
    print(f"Base: {base_elo:.0f}")
    print(f"Adjusted: {adjusted_elo:.0f}")
    print(f"Boost: {(adjusted_elo / base_elo - 1) * 100:.1f}%")
```

### Get Network Analysis Breakdown

```python
# Get detailed breakdown
network_data = system.calculate_network_modifier(trader)

print(f"Independence Score: {system.independence_scores.get(trader, 50.0):.1f}/100")
print(f"Independence Modifier: {network_data['independence_modifier']:.3f}")

# Check copy-trader status
copy_status = system.is_copy_trader(trader)
if copy_status['is_follower']:
    print(f"Copy-Trader (FOLLOWER): Yes (score: {copy_status['copy_score']:.2f})")
    print(f"  Leaders: {len(copy_status['leaders'])} traders")
    if copy_status['should_exclude']:
        print(f"  SHOULD EXCLUDE: Yes (copy_score > 0.7)")
elif copy_status['is_leader']:
    print(f"Copy-Trade Leader: Yes")
    print(f"  Followers: {len(copy_status['followers'])} traders")
else:
    print(f"Copy-Trader: No (independent)")

# Check cluster status
cluster_info = system.is_in_suspicious_cluster(trader)
if cluster_info['in_cluster']:
    print(f"Cluster: {cluster_info['cluster_type']}")
    print(f"  Avg Correlation: {cluster_info['avg_correlation']:.3f}")
    print(f"  Penalty Modifier: {cluster_info['penalty_modifier']:.2f}x")
else:
    print(f"Cluster: Not in suspicious cluster")

print(f"\nCombined Network Modifier: {network_data['combined_modifier']:.3f}")
print(f"Should Exclude: {network_data['should_exclude']}")
print(f"\n{network_data['breakdown']}")
```

### Category-Specific with Network Filtering

```python
# Apply network filtering to category-specific ELO
elections_base = system.get_trader_category_elo(trader, 'Elections')
elections_adjusted = system.get_trader_category_elo(trader, 'Elections', apply_network=True)

if elections_adjusted == 0.0:
    print(f"Elections ELO: EXCLUDED (copy-trader)")
else:
    print(f"Elections Base: {elections_base:.0f}")
    print(f"Elections Adjusted: {elections_adjusted:.0f}")
```

### Combine with All Modifiers

```python
# Get ELO with behavioral, advanced, AND network adjustments
fully_adjusted_elo = system.get_trader_global_elo(
    trader,
    apply_behavioral=True,   # Behavioral patterns
    apply_advanced=True,     # Calibration, Sharpe, Regret
    apply_network=True       # Network filtering
)

if fully_adjusted_elo == 0.0:
    print(f"Trader EXCLUDED (copy-trader)")
else:
    print(f"Fully Adjusted ELO: {fully_adjusted_elo:.0f}")
    print(f"Total Change: {fully_adjusted_elo - base_elo:+.0f}")
```

### Filter Traders for Consensus

```python
# Get traders suitable for consensus (no copy-traders, min ELO 1600)
filtered_traders = system.get_filtered_traders_for_consensus(
    category='Elections',
    min_elo=1600
)

total_traders = len(system.elo_system.get_all_traders())
print(f"{len(filtered_traders)}/{total_traders} traders suitable for consensus")
print(f"Excluded {total_traders - len(filtered_traders)} copy-traders and low-ELO traders")

# Use in consensus calculation
outcome_weights = {}
for trader in filtered_traders:
    # Get network-adjusted ELO
    elo = system.get_trader_category_elo(
        trader, 'Elections',
        apply_behavioral=True,
        apply_advanced=True,
        apply_network=True
    )
    # elo will never be 0.0 since traders are pre-filtered
    weight = elo / 1500.0
    # Add to consensus...
```

### Export Network Analysis

```python
# Get network data for all traders
export = system.export_network_analysis()

print(f"Total traders analyzed: {export['total_traders_analyzed']}")
print(f"Independent traders (score >= 75): {export['independent_traders']}")
print(f"Followers detected: {export['followers_detected']}")
print(f"Leaders detected: {export['leaders_detected']}")
print(f"Traders excluded: {export['traders_excluded']}")
print(f"Suspicious clusters: {export['suspicious_clusters']}")
print(f"Avg independence score: {export['avg_independence_score']:.1f}")

# Top 10 independent traders
for trader_data in export['top_independent_traders']:
    print(f"{trader_data['trader'][:10]}... "
          f"Independence: {trader_data['independence_score']:.1f} "
          f"(Modifier: {trader_data['network_modifier']:.2f}x)")
```

### Generate CSV Report

```python
# Generate network analysis report
report_path = system.generate_network_report()

print(f"Report saved to: {report_path}")
# Creates: reports/network_analysis_YYYYMMDD.csv

# Columns:
# - rank
# - trader_address
# - independence_score
# - independence_modifier
# - avg_correlation
# - copy_status (Independent/Follower/Leader)
# - copy_score
# - cluster_type (None/LOOSE/TIGHT/SUSPICIOUS)
# - network_modifier (combined)
# - should_exclude (True/False)
```

---

## Integration with export_for_integration()

Network data is automatically included in the main export:

```python
export = system.export_for_integration()

# Access network analysis data
for trader, network_data in export['network_analysis'].items():
    print(f"{trader[:10]}...")
    print(f"  Independence Score: {network_data['independence_score']:.1f}")
    print(f"  Independence Modifier: {network_data['independence_modifier']:.3f}")
    print(f"  Is Follower: {network_data['is_follower']}")
    print(f"  Is Leader: {network_data['is_leader']}")
    print(f"  Copy Score: {network_data['copy_score']:.2f}")
    print(f"  Combined Modifier: {network_data['combined_modifier']:.3f}")
    print(f"  Should Exclude: {network_data['should_exclude']}")

# Use pre-filtered traders (already excludes copy-traders)
filtered_traders = export['filtered_traders']
print(f"{len(filtered_traders)} traders suitable for consensus")

# Get excluded traders (copy-traders)
excluded_traders = export['excluded_traders']
print(f"{len(excluded_traders)} traders excluded (copy-traders)")
```

---

## Caching

Network data is expensive to calculate, so it's cached for 24 hours:

```python
# First call: loads correlation matrix + copy-trade detection
network1 = system.calculate_network_modifier(trader)
# Output: [NETWORK] Loading network analysis data...
#         [CORRELATION] Running correlation analysis...
#         [COPY-TRADE] Detecting copy-trading relationships...
#         [NETWORK] Loaded data for 157 traders

# Second call: uses cache
network2 = system.calculate_network_modifier(trader)
# Output: [NETWORK] Using cached network data (age: 0.0 hours)

# Force refresh (recalculate correlation matrix)
system._load_network_data(force_refresh=True)
# Output: [NETWORK] Loading network analysis data...
```

**Cache File:** `reports/correlation_cache.json`

---

## When to Use Network Filtering

### Use Network Filtering When:

1. **Building consensus models** - Exclude copy-traders to avoid double-counting
2. **Identifying quality traders** - Find independent traders with genuine signals
3. **Copy-trade detection** - Identify followers and leaders
4. **Risk management** - Filter coordinated trading clusters
5. **Quality-weighted predictions** - Weight independent traders higher

### Don't Use Network Filtering When:

1. **Copy-trade leader identification** - Leaders should NOT be excluded
2. **Pure skill assessment** - Traditional ELO already captures win/loss skill
3. **Insufficient trader count** - Need at least 10 traders for correlation analysis

---

## Example Use Cases

### Use Case 1: Weighted Consensus with Copy-Trader Filtering

```python
def weighted_consensus_with_network_filtering(market_id: str, category: str):
    """
    Calculate weighted consensus using category-specific ELOs
    with network filtering to exclude copy-traders.
    """
    system = UnifiedELOSystem()

    # Get filtered traders (no copy-traders, min ELO 1500)
    filtered_traders = system.get_filtered_traders_for_consensus(
        category=category,
        min_elo=1500
    )

    # Get trader positions on this market
    trader_positions = get_trader_positions(market_id)  # Your function

    outcome_weights = {}
    for trader, outcome in trader_positions:
        # Only include filtered traders
        if trader not in filtered_traders:
            continue

        # Use category-specific ELO with all adjustments
        elo = system.get_trader_category_elo(
            trader, category,
            apply_behavioral=True,
            apply_advanced=True,
            apply_network=True
        )

        # Add to outcome weight
        outcome_weights[outcome] = outcome_weights.get(outcome, 0) + elo

    # Find winner
    if not outcome_weights:
        return None  # No qualified traders

    total = sum(outcome_weights.values())
    top_outcome = max(outcome_weights, key=outcome_weights.get)
    confidence = outcome_weights[top_outcome] / total * 100

    return {
        'outcome': top_outcome,
        'confidence': confidence,
        'weights': outcome_weights,
        'qualified_traders': len([t for t, _ in trader_positions if t in filtered_traders])
    }
```

### Use Case 2: Identify Copy-Trade Leaders

```python
# Find leaders being copied (potential high-quality traders)
export = system.export_for_integration()

leaders = []
for trader, network_data in export['network_analysis'].items():
    if network_data['is_leader'] and len(network_data['followers']) >= 5:
        # Get trader's adjusted ELO
        elo = system.get_trader_global_elo(
            trader,
            apply_behavioral=True,
            apply_advanced=True,
            apply_network=True
        )

        leaders.append({
            'address': trader,
            'followers': len(network_data['followers']),
            'independence_score': network_data['independence_score'],
            'adjusted_elo': elo,
            'follower_list': network_data['followers']
        })

# Sort by number of followers
leaders.sort(key=lambda x: x['followers'], reverse=True)

print(f"Found {len(leaders)} leaders with 5+ followers:")
for leader in leaders[:10]:
    print(f"\n{leader['address'][:10]}...")
    print(f"  Followers: {leader['followers']}")
    print(f"  Independence Score: {leader['independence_score']:.1f}")
    print(f"  Adjusted ELO: {leader['adjusted_elo']:.0f}")
```

### Use Case 3: Detect and Exclude Copy-Traders

```python
# Get list of excluded traders
export = system.export_for_integration()
excluded_traders = export['excluded_traders']

print(f"Excluding {len(excluded_traders)} copy-traders from analysis:")

for trader in excluded_traders:
    network_data = export['network_analysis'][trader]
    copy_status = system.is_copy_trader(trader)

    print(f"\n{trader[:10]}... EXCLUDED")
    print(f"  Copy Score: {network_data['copy_score']:.2f}")
    print(f"  Independence Score: {network_data['independence_score']:.1f}")

    if copy_status['is_follower']:
        print(f"  Copying from {len(copy_status['leaders'])} leaders:")
        for leader in copy_status['leaders'][:3]:  # Show first 3
            print(f"    - {leader[:10]}...")
```

### Use Case 4: Quality Filtering with Independence Score

```python
# Rank by independence score
export = system.export_network_analysis()

print("Top 10 Most Independent Traders:")
for i, trader_data in enumerate(export['top_independent_traders'][:10]):
    print(f"\n{i+1}. {trader_data['trader'][:10]}...")
    print(f"   Independence Score: {trader_data['independence_score']:.1f}/100")
    print(f"   Network Modifier: {trader_data['network_modifier']:.2f}x")
    print(f"   Avg Correlation: {trader_data['avg_correlation']:.3f}")

    # Get adjusted ELO
    elo = system.get_trader_global_elo(
        trader_data['trader'],
        apply_network=True
    )
    print(f"   Adjusted ELO: {elo:.0f}")
```

---

## Performance Impact

### Calculation Time

- **First network analysis:** 120-180 seconds
  - Correlation matrix calculation: 60-90 seconds
  - Copy-trade detection: 60-90 seconds
- **Cached access:** <1 second (24-hour cache)
- **Individual modifier calculation:** <1ms (reads from cache)

### Memory Usage

- **Network cache:** ~10-15 MB for 200 traders
- **Correlation cache file:** ~5 MB (saved to `reports/correlation_cache.json`)
- **Negligible overhead** on top of existing ELO system

### Cache Strategy

```python
# Cache file location
cache_file = 'reports/correlation_cache.json'

# Cache structure
{
    'timestamp': '2025-12-05T14:30:00',
    'correlations': {
        'trader1': {
            'trader2': 0.85,
            'trader3': 0.12,
            ...
        },
        ...
    },
    'avg_correlations': {
        'trader1': 0.45,
        'trader2': 0.32,
        ...
    }
}

# Cache validity: 24 hours
# If older than 24 hours, recalculate
```

---

## Validation

### How to Validate Network Integration

1. **Check modifiers are in range:**
```python
network = system.calculate_network_modifier(trader)
assert 0.0 <= network['combined_modifier'] <= 1.25
assert 0.5 <= network['independence_modifier'] <= 1.25
assert 0.5 <= network['cluster_penalty'] <= 1.0
```

2. **Check exclusion logic:**
```python
copy_status = system.is_copy_trader(trader)
if copy_status['is_follower'] and copy_status['copy_score'] > 0.7:
    # Should be excluded
    assert network['should_exclude'] == True
    elo = system.get_trader_global_elo(trader, apply_network=True)
    assert elo == 0.0
```

3. **Check filtered traders excludes copy-traders:**
```python
filtered = system.get_filtered_traders_for_consensus()
excluded = system.export_for_integration()['excluded_traders']

for trader in excluded:
    assert trader not in filtered
```

4. **Check CSV report generates:**
```python
report_path = system.generate_network_report()
assert os.path.exists(report_path)
```

5. **Check export includes network data:**
```python
export = system.export_for_integration()
assert 'network_analysis' in export
assert 'filtered_traders' in export
assert 'excluded_traders' in export
assert 'network_analysis_timestamp' in export
```

---

## Troubleshooting

### "All network modifiers are 1.00"

**Cause:** No network data loaded

**Fix:**
```python
# Force refresh
system._load_network_data(force_refresh=True)
```

### "Network analysis failed"

**Cause:** correlation_matrix.py or copy_trade_detector.py not found

**Fix:**
```python
# Check imports work
from correlation_matrix import TraderCorrelationMatrix
from copy_trade_detector import CopyTradeDetector

correlation_analyzer = TraderCorrelationMatrix()
copy_detector = CopyTradeDetector()
```

### "Adjusted ELO same as base ELO"

**Cause:** Trader has neutral network modifier (1.0x)

**Fix:**
```python
# Check if trader has network data
network_data = system.calculate_network_modifier(trader)
print(f"Combined Modifier: {network_data['combined_modifier']:.3f}")
print(f"Breakdown: {network_data['breakdown']}")
```

### "No traders returned from get_filtered_traders_for_consensus"

**Cause:** All traders excluded or below min_elo threshold

**Fix:**
```python
# Lower the minimum ELO threshold
filtered_traders = system.get_filtered_traders_for_consensus(min_elo=0)

# Check exclusion stats
export = system.export_network_analysis()
print(f"Total traders: {export['total_traders_analyzed']}")
print(f"Excluded: {export['traders_excluded']}")
```

---

## Design Philosophy

### Why These Specific Modifiers?

1. **Independence** - Uncorrelated trading indicates genuine signals
2. **Copy-Trader Penalty** - Followers double-count signals, provide no value
3. **Cluster Penalty** - Coordinated trading suggests manipulation

### Why These Ranges?

- **Max boost: 1.25x (25%)** - Rewards independence without over-weighting
- **Max penalty: 0.0x (exclusion)** - Complete removal of confirmed copy-traders
- **Neutral: 1.00x** - No network data = no adjustment (fair)

### Why Exclude Copy-Traders Completely?

**Problem:** Copy-traders create false consensus
- 1 leader with signal
- 5 followers copying leader
- Naive consensus: 6 traders agree → high confidence
- Reality: Only 1 genuine signal

**Solution:** Exclude followers → only 1 trader counted → correct confidence

### Why Multiply Instead of Add?

**Multiplicative scales with ELO magnitude:**
- Elite trader (2000 ELO) with 1.25x boost → 2500 ELO (still elite)
- Average trader (1500 ELO) with 1.25x boost → 1875 ELO (boosted appropriately)

**Additive would be less fair:**
- Elite trader (2000 ELO) + 300 → 2300 ELO (15% boost)
- Average trader (1500 ELO) + 300 → 1800 ELO (20% boost)

---

## Backward Compatibility

**All existing code continues to work:**

```python
# Old code (still works, no network filtering)
elo = system.get_trader_global_elo(trader)

# New code (opt-in network filtering)
elo = system.get_trader_global_elo(trader, apply_network=True)
```

**apply_network parameter defaults to False** - no breaking changes.

---

## Future Enhancements

### Planned for v2.0

1. **Time-weighted correlation** - Recent correlation matters more
2. **Category-specific copy-trading** - Detect category-focused copiers
3. **Copy-trade confidence intervals** - Statistical confidence in detection
4. **Dynamic exclusion thresholds** - Adjust based on trader pool size
5. **Leader quality scoring** - Rank leaders by follower performance
6. **Network visualization** - Graph of copy-trade relationships

---

## Summary

**Network integration adds copy-trader filtering on top of ELO:**

- **Traditional ELO:** Skill from wins/losses
- **Network Filtering:** Exclude copy-traders, reward independence

**Result:** More accurate consensus that:
- Eliminates double-counting from copy-traders
- Rewards genuine independent signals
- Detects coordinated manipulation
- Identifies high-quality leaders

**Usage:** Opt-in with `apply_network=True` parameter

**Performance:** Minimal overhead (<1ms per trader with caching)

**Compatibility:** 100% backward compatible

---

**Last Updated:** 2025-12-05
**Version:** 1.0
**Status:** Production Ready
