# Simulation Quick Reference Guide

Quick reference for building Polymarket data simulation.

---

## Table Relationships Diagram

```
┌─────────────────┐
│    traders      │
│  (34,614 rows)  │
├─────────────────┤
│ PK: address     │
│    total_trades │
│    win_rate     │
│    total_volume │
│    realized_pnl │
│    comp_elo     │
└────────┬────────┘
         │
         │ FK: trader_address
         │
    ┌────▼──────────────┐
    │      trades       │
    │   (15,674 rows)   │
    ├───────────────────┤
    │ PK: trade_id      │
    │ FK: trader_address│
    │     market_id     │
    │     outcome       │
    │     shares        │
    │     price         │
    │     side          │
    │     timestamp     │
    └────┬──────────────┘
         │
         │ market_id (no FK)
         │
    ┌────▼────────────┐
    │    markets      │
    │ (213,461 rows)  │
    ├─────────────────┤
    │ PK: market_id   │
    │     title       │
    │     category    │
    │     resolved    │
    │     winning_out │
    └────┬────────────┘
         │
         │ market_id
         │
    ┌────▼───────────────┐
    │    positions       │
    │   (8,591 rows)     │
    ├────────────────────┤
    │ PK: position_id    │
    │ FK: trader_address │
    │     market_id      │
    │     entry_shares   │
    │     exit_shares    │
    │     realized_pnl   │
    │     status         │
    └────────────────────┘
```

---

## Required Field Cheat Sheet

### Trade Object (Minimum Required)
```python
{
    'trade_id': '0x' + 64_hex_chars,        # Unique transaction hash
    'trader_address': '0x' + 40_hex_chars,  # Must exist in traders table
    'market_id': '0x' + 64_hex_chars,       # Market identifier
    'market_title': str,                     # Question text
    'market_category': 'Geopolitics',        # Category string
    'outcome': 'Yes' | 'No',                 # Outcome being traded
    'shares': float,                         # Positive number
    'price': float,                          # Between 0.0 and 1.0
    'side': 'BUY' | 'SELL',                 # Trade direction
    'timestamp': datetime                    # ISO format
}
```

### Market Object (Minimum Required)
```python
{
    'market_id': '0x' + 64_hex_chars,       # Unique identifier
    'title': str,                            # Market question
    'category': 'Geopolitics',               # Category
    'end_date': datetime | None,             # Close date (optional)
    'resolved': 0 | 1,                       # Boolean (0=pending, 1=resolved)
    'winning_outcome': str | None,           # 'Yes'/'No' if resolved
    'condition_id': '0x' + 64_hex_chars,    # For trade matching
    'api_id': str | None                     # API ID (optional)
}
```

### Trader Object (Minimum Required)
```python
{
    'address': '0x' + 40_hex_chars,         # Unique Ethereum address
    'total_trades': int,                     # Count >= 0
    'total_volume': float,                   # Dollar volume >= 0
    'comprehensive_elo': float,              # Default 1500.0
    'base_category_elo': float               # Default 1500.0
}
```

---

## Sample Valid Objects

### Sample Trade
```python
trade = {
    'trade_id': '0xc19837b3e5f3989dfd4da75ef568af9f97e4685d665faa828b3c928cdb8bbe3a',
    'trader_address': '0x0c36bdedfbe0282ad9583bb30e4d2f0683d074df',
    'market_id': '0xef5880e94212f24f17d45b756c9aa42bc7d39c3feda659fc22417adae5e22d00',
    'market_title': 'Will Catalin Drula be the next Mayor of Bucharest?',
    'market_category': 'Geopolitics',
    'outcome': 'No',
    'shares': 12.0,
    'price': 0.89,
    'side': 'BUY',
    'timestamp': datetime(2025, 11, 20, 21, 10, 39)
}
```

### Sample Market (Resolved)
```python
market = {
    'market_id': '0x9b946f54f3428aafc308c33aa04a943fe13a011bdac9a9b66e1ba16c416ca256',
    'title': 'Will Kim Kardashian and Kanye West divorce before Jan 1, 2021?',
    'category': 'Pop-Culture',
    'end_date': datetime(2021, 1, 2),
    'resolved': 1,
    'winning_outcome': 'No',
    'condition_id': '0x9b946f54f3428aafc308c33aa04a943fe13a011bdac9a9b66e1ba16c416ca256',
    'api_id': '19'
}
```

### Sample Market (Pending)
```python
market = {
    'market_id': '0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9',
    'title': 'Will Joe Biden get Coronavirus before the election?',
    'category': 'US-current-affairs',
    'end_date': datetime(2020, 11, 4),
    'resolved': 0,
    'winning_outcome': None,
    'condition_id': '0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9',
    'api_id': '12'
}
```

### Sample Trader
```python
trader = {
    'address': '0x46b6820bf82ca3a118623491e452d7e5f7cb128d',
    'total_trades': 78,
    'successful_trades': 0,
    'win_rate': 0.0,
    'total_volume': 982.46,
    'comprehensive_elo': 1500.0,
    'base_category_elo': 1500.0,
    'behavioral_modifier': 1.0,
    'advanced_modifier': 1.0,
    'pnl_modifier': 1.0
}
```

---

## ID Generation Patterns

### Trade ID (Transaction Hash)
```python
import secrets

trade_id = '0x' + secrets.token_hex(32)
# Example: 0xc19837b3e5f3989dfd4da75ef568af9f97e4685d665faa828b3c928cdb8bbe3a
```

### Market ID (Condition ID)
```python
import secrets

market_id = '0x' + secrets.token_hex(32)
# Example: 0xef5880e94212f24f17d45b756c9aa42bc7d39c3feda659fc22417adae5e22d00
```

### Trader Address (Ethereum Address)
```python
import secrets

trader_address = '0x' + secrets.token_hex(20)
# Example: 0x0c36bdedfbe0282ad9583bb30e4d2f0683d074df
```

### Position ID
```python
# Format: {trader_prefix}_{market_prefix}_{outcome}_{timestamp}
import secrets

position_id = f"{trader_address[:10]}_{market_id[:10]}_{outcome}_{int(time.time())}"
# Example: 0x30cecd_0x6d1ed3_No_1763969365
```

---

## Data Generation Rules

### Trade Generation
```python
# BUY/SELL ratio: 80/20
side = random.choices(['BUY', 'SELL'], weights=[0.8, 0.2])[0]

# Price range for competitive markets
price = random.uniform(0.3, 0.95)

# Shares range (logarithmic distribution)
shares = random.lognormvariate(mu=5, sigma=1.5)

# Outcome (binary markets)
outcome = random.choice(['Yes', 'No'])

# Timestamp (chronological)
timestamp = start_date + timedelta(seconds=random.randint(0, total_seconds))
```

### Market Generation
```python
# Category (currently only Geopolitics)
category = 'Geopolitics'

# Title templates
templates = [
    "Will {person} {action} by {date}?",
    "Will {event} happen in {year}?",
    "{Country} {political_event} before {date}?",
]

# End date (future or past)
end_date = datetime.now() + timedelta(days=random.randint(1, 365))

# Resolved (20% of markets)
resolved = random.random() < 0.2

# Winning outcome (if resolved)
winning_outcome = random.choice(['Yes', 'No']) if resolved else None
```

### Trader Generation
```python
# Total trades per trader (log-normal)
total_trades = int(random.lognormvariate(mu=2.5, sigma=1.0))

# Total volume (correlates with trades)
total_volume = total_trades * random.uniform(50, 500)

# ELO (normal distribution around 1500)
comprehensive_elo = random.normalvariate(mu=1500, sigma=200)

# Win rate (for traders with resolved trades)
win_rate = random.betavariate(alpha=2, beta=2)  # Bell curve 0-1
```

---

## Validation Rules

### Trade Validation
```python
def validate_trade(trade):
    assert trade['trade_id'].startswith('0x'), "trade_id must start with 0x"
    assert len(trade['trade_id']) == 66, "trade_id must be 66 chars (0x + 64 hex)"

    assert trade['trader_address'].startswith('0x'), "trader_address must start with 0x"
    assert len(trade['trader_address']) == 42, "trader_address must be 42 chars"

    assert trade['market_id'].startswith('0x'), "market_id must start with 0x"
    assert len(trade['market_id']) == 66, "market_id must be 66 chars"

    assert 0 < trade['price'] <= 1, "price must be between 0 and 1"
    assert trade['shares'] > 0, "shares must be positive"
    assert trade['side'] in ['BUY', 'SELL'], "side must be BUY or SELL"
    assert trade['outcome'] in ['Yes', 'No'], "outcome must be Yes or No"
```

### Market Validation
```python
def validate_market(market):
    assert market['market_id'].startswith('0x'), "market_id must start with 0x"
    assert len(market['market_id']) == 66, "market_id must be 66 chars"

    assert market['resolved'] in [0, 1], "resolved must be 0 or 1"

    if market['resolved'] == 1:
        assert market['winning_outcome'] is not None, "resolved market must have winning_outcome"
        assert market['winning_outcome'] in ['Yes', 'No'], "winning_outcome must be Yes or No"

    if market['condition_id']:
        assert market['condition_id'].startswith('0x'), "condition_id must start with 0x"
        assert len(market['condition_id']) == 66, "condition_id must be 66 chars"
```

### Trader Validation
```python
def validate_trader(trader):
    assert trader['address'].startswith('0x'), "address must start with 0x"
    assert len(trader['address']) == 42, "address must be 42 chars"

    assert trader['total_trades'] >= 0, "total_trades must be non-negative"
    assert trader['total_volume'] >= 0, "total_volume must be non-negative"

    assert 500 <= trader['comprehensive_elo'] <= 3000, "ELO should be 500-3000"
```

---

## Database Insert Order

**CRITICAL:** Must insert in this order to satisfy foreign key constraints:

```python
# 1. Create all traders FIRST
for trader in traders:
    db.add_or_update_trader(**trader)

# 2. Create all markets SECOND
for market in markets:
    db.store_market_dict(market)

# 3. Create all trades LAST (references traders and markets)
for trade in trades:
    db.add_trade(**trade)

# 4. Positions auto-created by position tracker (optional)
```

---

## Realistic Patterns

### Trade Accumulation Pattern
```python
# Trader makes multiple entries on same market
trader_address = generate_trader_address()
market_id = generate_market_id()

# Multiple BUYs over time (averaging in)
for i in range(3):
    trade = {
        'trade_id': generate_trade_id(),
        'trader_address': trader_address,
        'market_id': market_id,
        'outcome': 'Yes',
        'shares': random.uniform(100, 1000),
        'price': 0.85 + (i * 0.03),  # Price increasing
        'side': 'BUY',
        'timestamp': base_time + timedelta(hours=i*24)
    }
```

### Market Evolution Pattern
```python
# Market starts pending, later resolves
market = {
    'market_id': generate_market_id(),
    'title': 'Will event happen?',
    'resolved': 0,
    'winning_outcome': None,
    'end_date': datetime.now() + timedelta(days=30)
}

# ... time passes, market ends ...

# Update market to resolved
market['resolved'] = 1
market['winning_outcome'] = 'Yes'
market['resolution_date'] = market['end_date']
```

---

## Common Patterns from Real Data

### High-Volume Trader Pattern
```python
# From sample data: 0x000d257d2dc7616fea...
# Pattern: Large positions (2000-13000 shares), political focus, high conviction

trades = [
    {'outcome': 'Yes', 'shares': 2106.76, 'price': 0.967},  # High conviction
    {'outcome': 'No', 'shares': 8000.0, 'price': 0.94},     # Large position
    {'outcome': 'Yes', 'shares': 2284.73, 'price': 0.894},  # Multiple entries
    {'outcome': 'Yes', 'shares': 8098.38, 'price': 0.918},  # Same market
    {'outcome': 'Yes', 'shares': 13027.04, 'price': 0.988}  # Averaging up
]
```

### Market Category Distribution
```python
# 100% Geopolitics (current system)
categories = ['Geopolitics'] * 100

# For realistic diversity (if expanding):
categories = {
    'Geopolitics': 0.60,      # 60%
    'US-current-affairs': 0.20,
    'Pop-Culture': 0.10,
    'Sports': 0.05,
    'Crypto': 0.05
}
```

---

## Quick Start Simulation Template

```python
import secrets
import random
from datetime import datetime, timedelta
from monitoring.database import Database

def generate_simulation_data(num_traders=100, num_markets=50, num_trades=1000):
    """Generate realistic simulation data."""

    db = Database()

    # 1. Generate traders
    traders = []
    for _ in range(num_traders):
        address = '0x' + secrets.token_hex(20)
        traders.append({
            'address': address,
            'total_trades': 0,  # Will update
            'total_volume': 0,  # Will update
            'comprehensive_elo': 1500.0,
            'base_category_elo': 1500.0
        })
        db.add_or_update_trader(**traders[-1])

    # 2. Generate markets
    markets = []
    for _ in range(num_markets):
        market_id = '0x' + secrets.token_hex(32)
        resolved = random.random() < 0.2
        markets.append({
            'market_id': market_id,
            'title': f'Will {random.choice(["event", "person"])} happen?',
            'category': 'Geopolitics',
            'end_date': datetime.now() + timedelta(days=random.randint(1, 365)),
            'resolved': 1 if resolved else 0,
            'winning_outcome': random.choice(['Yes', 'No']) if resolved else None,
            'condition_id': market_id
        })
        db.store_market_dict(markets[-1])

    # 3. Generate trades
    for _ in range(num_trades):
        trader = random.choice(traders)
        market = random.choice(markets)

        trade = {
            'trade_id': '0x' + secrets.token_hex(32),
            'trader_address': trader['address'],
            'market_id': market['market_id'],
            'market_title': market['title'],
            'market_category': market['category'],
            'outcome': random.choice(['Yes', 'No']),
            'shares': random.lognormvariate(5, 1.5),
            'price': random.uniform(0.3, 0.95),
            'side': random.choices(['BUY', 'SELL'], weights=[0.8, 0.2])[0],
            'timestamp': datetime.now() - timedelta(days=random.randint(0, 30))
        }
        db.add_trade(**trade)

# Run simulation
generate_simulation_data()
```

---

## Testing Checklist

After generating simulation data:

- [ ] All trader addresses are unique
- [ ] All market IDs are unique
- [ ] All trade IDs are unique
- [ ] Every trade references existing trader
- [ ] Every trade references existing market
- [ ] Prices are between 0.0 and 1.0
- [ ] Shares are positive
- [ ] Sides are "BUY" or "SELL"
- [ ] Timestamps are chronological
- [ ] Resolved markets have winning_outcome
- [ ] Pending markets have winning_outcome = None
- [ ] FK constraints are satisfied
- [ ] Database queries run without errors
- [ ] ELO system can process the data

---

*Quick Reference Complete*
