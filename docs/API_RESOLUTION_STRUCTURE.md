# Polymarket API Resolution Structure

**Investigation Date:** 2025-12-11 16:16:24

## Summary

This document details how to detect market resolution and extract winning outcomes
from the Polymarket Gamma API.

## Market Categories

Based on analysis of 500 markets:

- **Active Markets:** 0
- **Closed Markets:** 500
- **Archived Markets:** 0

## Resolution Detection Logic

### Primary Method: Outcome Prices

The most reliable way to detect a resolved market:

```python
def is_market_resolved(market: dict) -> bool:
    """Check if market is resolved by examining outcome prices."""
    try:
        prices_raw = market.get('outcomePrices', '[]')
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Market is resolved if any outcome has price >= 0.99
        return any(float(p) >= 0.99 for p in prices if p)
    except:
        return False
```

### Secondary Indicators

- `closed: true` - Market is closed for trading
- `archived: true` - Market is archived
- `umaResolutionStatus: "resolved"` - UMA oracle has resolved (unreliable)

**Note:** Not all closed markets are resolved, and not all resolved markets have
`umaResolutionStatus == "resolved"`. Always use outcome prices as primary indicator.

## Field Mapping

| API Field | Database Field | Type | Description |
|-----------|---------------|------|-------------|
| `id` | `api_id` | Integer | Numeric ID for API lookups |
| `conditionId` | `market_id`, `condition_id` | String (hex) | Blockchain condition ID |
| `question` | `title` | String | Market question |
| `outcomes` | - | JSON string | Array of outcome names |
| `outcomePrices` | - | JSON string | Array of outcome prices |
| `closed` | - | Boolean | Market closed for trading |
| `archived` | `archived` | Boolean | Market archived |
| `category` | `category` | String | Market category |
| `endDate` | `end_date` | Timestamp | Market end date |

## Extracting Winning Outcome

```python
def extract_winner(market: dict) -> str:
    """Extract winning outcome from resolved market."""
    try:
        outcomes_raw = market.get('outcomes', '[]')
        prices_raw = market.get('outcomePrices', '[]')

        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Find outcome with price >= 0.99
        for idx, price in enumerate(prices):
            if float(price) >= 0.99:
                return outcomes[idx]

        return None
    except Exception as e:
        return None
```

## Market ID Strategy

### Recommended Approach

1. **Primary Key:** Use `conditionId` (hex string) as `market_id`
   - Unique identifier
   - Used in blockchain transactions
   - Required for matching trades

2. **API Lookup:** Use `id` (numeric) as `api_id`
   - Required for Gamma API endpoints
   - Example: `GET /markets/{id}`

3. **Database Schema:**
```sql
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,      -- conditionId
    api_id TEXT,                      -- numeric id
    condition_id TEXT,                -- duplicate of market_id for clarity
    ...
);
```

## Edge Cases Identified

No edge cases identified in sample.


## Example Code

### Complete Resolution Checker

```python
import json
import requests

def check_market_resolution(market_id: str) -> dict:
    """
    Check if market is resolved and extract winner.

    Args:
        market_id: Numeric market ID (api_id)

    Returns:
        {
            'resolved': bool,
            'winner': str or None,
            'closed': bool
        }
    """
    response = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}")
    if response.status_code != 200:
        return {'resolved': False, 'winner': None, 'closed': False}

    market = response.json()

    # Parse outcomes
    try:
        outcomes_raw = market.get('outcomes', '[]')
        prices_raw = market.get('outcomePrices', '[]')

        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

        # Find winner
        winner = None
        for idx, price in enumerate(prices):
            if float(price) >= 0.99:
                winner = outcomes[idx]
                break

        return {
            'resolved': winner is not None,
            'winner': winner,
            'closed': market.get('closed', False)
        }
    except:
        return {'resolved': False, 'winner': None, 'closed': market.get('closed', False)}
```

## Outcome Structure Examples

### Example 1

**Question:** Will Kim Kardashian and Kanye West divorce before Jan 1, 2021?

**Outcomes:** `['Yes', 'No']`

**Prices:** `['0.000001011082052522541417308141468657552', '0.9999989889179474774585826918585313']`

**Winner:** `No`

### Example 2

**Question:** Will Coinbase begin publicly trading before Jan 1, 2021?

**Outcomes:** `['Yes', 'No']`

**Prices:** `['0.000001024519509568169644816863666886675', '0.9999989754804904318303551831363331']`

**Winner:** `No`

### Example 3

**Question:** Will Trump win the 2020 U.S. presidential election?

**Outcomes:** `['Yes', 'No']`

**Prices:** `['0.00000004364303498046286702037228176483457', '0.9999999563569650195371329796277182']`

**Winner:** `No`


## Recommendations

1. **Always use outcome prices** as the primary resolution indicator
2. **Store both IDs:** `conditionId` for database key, `id` for API lookups
3. **Handle edge cases:** Markets with no clear winner (all prices < 0.99)
4. **Use threshold 0.99** instead of exact 1.0 for floating-point tolerance
5. **Parse JSON strings:** Both `outcomes` and `outcomePrices` are JSON strings

## Testing

Test the resolution detection with these commands:

```bash
# Diagnose resolution matching
python monitoring/diagnose_resolution_matching.py

# Run fast batch resolution check (test mode)
python monitoring/fast_resolution_check.py --test --limit 100

# Update database with resolutions
python monitoring/fast_resolution_check.py --limit 1000
```

---

*Generated by: scripts/investigate_resolutions.py*
