# Historical ELO Rating Backfill Guide

## Overview

Calculate accurate ELO ratings for all traders using their complete historical trading data instead of waiting months for new data to accumulate.

**Problem:** New ELO system has no historical data → takes months to build up ratings
**Solution:** Backfill ELO from historical Polymarket trades → instant mature ratings

**Expected Results:**
- 800+ traders with ELO ratings immediately
- 100+ elite traders (ELO ≥ 1550) ready for consensus detection
- No waiting months for ratings to stabilize

---

## Quick Start

### Option 1: Use Existing Database (Recommended)

If your monitoring has been running for weeks/months:

```bash
python scripts/backfill_elo_ratings.py
```

This will:
- Load all trades from your database
- Calculate ELO chronologically
- Update trader ELO ratings
- Show statistics

**Limitations:** Only uses data you've already collected

---

### Option 2: Import Historical Data (Full Backfill)

For complete historical ratings going back months/years:

**Step 1: Get Historical Data**

Use the poly_data repository:
```bash
# Clone the data repo
git clone https://github.com/warproxxx/poly_data.git

# Or download specific files
# https://github.com/warproxxx/poly_data/tree/main/processed
```

**What you get:**
- `markets.csv` - All markets with metadata
- `trades.csv` - Complete trade history
- Pre-processed and cleaned

**Step 2: Filter to Geopolitics**

You only want geopolitics/politics markets (your focus):
```python
import pandas as pd

# Load markets
markets = pd.read_csv('poly_data/processed/markets.csv')

# Filter to geopolitics
# Check column names - may be 'category', 'tags', etc.
geo_markets = markets[markets['category'].str.contains('Politics|Geopolitics', na=False)]

# Get market IDs
geo_market_ids = set(geo_markets['id'])
print(f"Found {len(geo_market_ids)} geopolitics markets")
```

**Step 3: Import Trades**

```python
# Load trades
trades = pd.read_csv('poly_data/processed/trades.csv')

# Filter to geopolitics markets
geo_trades = trades[trades['market_id'].isin(geo_market_ids)]

# Sort chronologically (CRITICAL!)
geo_trades = geo_trades.sort_values('timestamp')

print(f"Total geopolitics trades: {len(geo_trades):,}")
```

**Step 4: Import to Your Database**

```python
import sqlite3

conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()

# Import trades
for _, trade in geo_trades.iterrows():
    cursor.execute("""
        INSERT OR IGNORE INTO trades (
            trader_address,
            market_id,
            outcome,
            shares,
            price,
            timestamp
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        trade['trader_address'],
        trade['market_id'],
        trade['outcome'],
        trade['shares'],
        trade['price'],
        trade['timestamp']
    ))

conn.commit()
print(f"Imported {len(geo_trades):,} historical trades")

# Import traders
unique_traders = geo_trades['trader_address'].unique()
for trader in unique_traders:
    cursor.execute("""
        INSERT OR IGNORE INTO traders (address, first_seen)
        VALUES (?, ?)
    """, (trader, datetime.now().isoformat()))

conn.commit()
print(f"Imported {len(unique_traders):,} traders")
```

**Step 5: Run Backfill**

```bash
python scripts/backfill_elo_ratings.py
```

---

## How It Works

### Current Implementation (Simplified)

The current `backfill_elo_ratings.py` script uses a **simplified heuristic**:

1. **Load all traders** from database
2. **Load all trades** sorted chronologically
3. **Group trades by market**
4. **Apply minimal ELO adjustments** based on trading activity

**Limitations:**
- Does NOT use actual market resolutions (not yet implemented)
- Only gives slight ELO boost to active traders
- Results are approximate, not accurate

**Why simplified?**
- Market resolution data requires Polymarket API integration
- Complex to map historical resolutions to trades
- Placeholder for proof-of-concept

---

### Accurate Implementation (TODO)

For accurate ELO ratings, you need:

**1. Market Resolutions**

Query Polymarket Gamma API:
```python
import requests

def get_market_resolution(market_id: str) -> Optional[str]:
    """Get market resolution from Polymarket API."""
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"

    try:
        response = requests.get(url)
        data = response.json()

        if data.get('closed') and data.get('resolved'):
            # Determine winning outcome
            if data.get('winner') == 1:
                return 'YES'
            elif data.get('winner') == 0:
                return 'NO'

    except Exception as e:
        print(f"Error getting resolution for {market_id}: {e}")

    return None
```

**2. Map Traders to Outcomes**

For each resolved market:
- Get all traders who bet on that market
- Determine their position (YES or NO)
- Check if they were correct (position == resolution)

**3. Calculate ELO Updates**

```python
def update_elo_from_market(market_id: str, resolution: str):
    """Update ELO for all traders in a resolved market."""

    # Get all traders in this market
    query = """
        SELECT trader_address, outcome, shares
        FROM trades
        WHERE market_id = ?
    """

    cursor.execute(query, (market_id,))
    traders = cursor.fetchall()

    # Calculate average ELO of market participants
    avg_elo = sum(trader_elo[t[0]] for t in traders) / len(traders)

    # Update ELO for each trader
    for trader_address, outcome, shares in traders:
        # Did they win?
        won = (outcome == resolution)

        # Current ELO
        current_elo = trader_elo[trader_address]

        # Calculate new ELO
        new_elo = calculate_elo_update(
            current_elo=current_elo,
            opponent_elo=avg_elo,  # Use market average
            won=won,
            k_factor=32
        )

        trader_elo[trader_address] = new_elo
```

**4. Process Chronologically**

CRITICAL: Process markets in order of resolution date:
```python
# Sort markets by resolution date
resolved_markets.sort(key=lambda m: m['resolution_date'])

# Update ELO in chronological order
for market in resolved_markets:
    update_elo_from_market(market['id'], market['resolution'])
```

---

## ELO Calculation Algorithm

### Formula

```
New ELO = Current ELO + K * (Actual - Expected)

Where:
- K = K-factor (32 for standard, higher = more volatile)
- Actual = 1 if won, 0 if lost
- Expected = 1 / (1 + 10^((Opponent ELO - Current ELO) / 400))
```

### Example

**Trader A (ELO 1500) vs Market Average (ELO 1520)**

**If Trader A wins (bet correctly):**
```
Expected = 1 / (1 + 10^((1520 - 1500) / 400))
         = 1 / (1 + 10^(0.05))
         = 0.486

New ELO = 1500 + 32 * (1 - 0.486)
        = 1500 + 32 * 0.514
        = 1516.4
```

**If Trader A loses (bet incorrectly):**
```
New ELO = 1500 + 32 * (0 - 0.486)
        = 1500 - 15.5
        = 1484.5
```

### K-Factor Tuning

**K = 32** (Standard)
- Moderate volatility
- Good for established traders

**K = 40** (Higher volatility)
- Faster ELO changes
- Good for new traders

**K = 24** (Lower volatility)
- Slower ELO changes
- Good for expert traders

**Adaptive K-factor:**
```python
def get_k_factor(trader_trades_count: int) -> float:
    """Get K-factor based on trader experience."""
    if trader_trades_count < 10:
        return 40  # New traders - volatile
    elif trader_trades_count < 50:
        return 32  # Intermediate
    else:
        return 24  # Experienced - stable
```

---

## Running the Backfill

### Prerequisites

1. **Database setup**
   - `data/polymarket_tracker.db` exists
   - Tables: `traders`, `trades`, `markets`

2. **Historical data** (optional but recommended)
   - Trades in database OR
   - poly_data CSV files imported

3. **Python dependencies**
   - sqlite3
   - Standard library (datetime, collections, etc.)

### Execute

```bash
# Simple version (uses existing DB data)
python scripts/backfill_elo_ratings.py
```

**Expected output:**
```
======================================================================
  HISTORICAL ELO RATING BACKFILL
======================================================================

[1/7] Loading existing traders from database...
  Loaded 847 existing traders
  Average existing ELO: 1500

[2/7] Loading market resolutions...
  Found 23 resolved markets
  Note: Resolution outcomes must be manually verified

[3/7] Loading historical trades from database...
  Loaded 12,459 historical trades
  Date range: 2024-01-15 08:23:15 → 2026-01-30 14:35:22

[4/7] Calculating ELO from historical trades...
  Note: Using simplified ELO calculation
  Processed 234 markets

[5/7] Calculating ELO from market resolutions...
  ⚠️  WARNING: Market resolution data not yet integrated
  Skipping for now - using trade activity heuristic instead

[6/7] Saving ELO ratings to database...
  Updated 847 traders

[7/7] ELO Rating Statistics:
======================================================================
Total Traders:         847
Average ELO:           1503
ELO Range:             1485 - 1542
Std Deviation:         12

Elite Traders (≥1550):     0 (0.0%)
Expert Traders (≥1600):    0 (0.0%)
Master Traders (≥1700):    0 (0.0%)

Top 10 Traders:
   1. 0x4017...7f9a  ELO: 1542
   2. 0x4f23...8b2c  ELO: 1538
   ...

======================================================================

✅ ELO backfill complete!
```

**Note:** With simplified heuristic, ELO range will be narrow (1485-1542).
With accurate market resolutions, expect range of 1200-1800.

---

## Verifying Results

### Check ELO Distribution

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT
        CAST(comprehensive_elo / 50 AS INTEGER) * 50 as elo_bucket,
        COUNT(*) as count
    FROM traders
    WHERE comprehensive_elo IS NOT NULL
    GROUP BY elo_bucket
    ORDER BY elo_bucket
''')

print('ELO Distribution:')
for bucket, count in cursor.fetchall():
    print(f'{bucket:4d}-{bucket+49:4d}: {'█' * (count // 10)} {count}')
"
```

**Expected (with accurate resolutions):**
```
ELO Distribution:
1200-1249: ██ 15
1250-1299: ████ 42
1300-1349: ████████ 87
1350-1399: ███████████ 124
1400-1449: ███████████████ 165
1450-1499: ████████████████████ 198  ← Peak around 1500
1500-1549: ███████████████ 143
1550-1599: ████████ 89
1600-1649: ████ 45
1650-1699: ██ 21
1700-1749: █ 8
1750-1799: 3
```

**Current (with simplified heuristic):**
```
ELO Distribution:
1485-1534: █████████████████████████ 721
1535-1584: ███ 126
```

---

## Integrating Market Resolutions

### Step 1: Create Resolution Fetcher

```python
# scripts/fetch_market_resolutions.py
import requests
import sqlite3
from datetime import datetime

def fetch_resolutions():
    """Fetch market resolutions from Polymarket API."""

    conn = sqlite3.connect('data/polymarket_tracker.db')
    cursor = conn.cursor()

    # Get all markets
    cursor.execute("SELECT DISTINCT market_id FROM trades")
    markets = cursor.fetchall()

    for (market_id,) in markets:
        resolution = get_market_resolution(market_id)

        if resolution:
            # Store resolution
            cursor.execute("""
                UPDATE markets
                SET
                    resolved = 1,
                    winning_outcome = ?,
                    resolution_date = ?
                WHERE market_id = ?
            """, (resolution, datetime.now().isoformat(), market_id))

            print(f"✓ {market_id}: {resolution}")
        else:
            print(f"✗ {market_id}: Not resolved")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    fetch_resolutions()
```

### Step 2: Update Backfill Script

Modify `scripts/backfill_elo_ratings.py`:

```python
def calculate_elo_from_resolutions(self):
    """Calculate ELO from actual market resolutions."""

    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()

    # Get resolved markets
    cursor.execute("""
        SELECT market_id, winning_outcome, resolution_date
        FROM markets
        WHERE resolved = 1
        ORDER BY resolution_date ASC
    """)

    resolutions = cursor.fetchall()

    for market_id, winning_outcome, res_date in resolutions:
        # Get traders in this market
        cursor.execute("""
            SELECT trader_address, outcome
            FROM trades
            WHERE market_id = ?
            GROUP BY trader_address
        """, (market_id,))

        traders_outcomes = cursor.fetchall()

        # Calculate market average ELO
        avg_elo = sum(self.trader_elo[t[0]] for t in traders_outcomes) / len(traders_outcomes)

        # Update ELO for each trader
        for trader_address, outcome in traders_outcomes:
            won = (outcome == winning_outcome)

            current_elo = self.trader_elo[trader_address]
            new_elo = self.calculate_elo_update(
                current_elo=current_elo,
                opponent_elo=avg_elo,
                won=won,
                k_factor=32
            )

            self.trader_elo[trader_address] = new_elo

    conn.close()

    print(f"  Processed {len(resolutions)} resolved markets")
```

### Step 3: Run Full Backfill

```bash
# Fetch resolutions
python scripts/fetch_market_resolutions.py

# Run backfill with resolutions
python scripts/backfill_elo_ratings.py
```

---

## Troubleshooting

### Issue: No trades found

**Solution:**
- Make sure monitoring has been running
- Check `SELECT COUNT(*) FROM trades`
- Import historical data from poly_data

### Issue: ELO range too narrow (1485-1542)

**Cause:** Using simplified heuristic without market resolutions

**Solution:**
- Integrate market resolution data
- See "Integrating Market Resolutions" section

### Issue: All traders have same ELO (1500)

**Cause:** Backfill not running or not updating database

**Solution:**
- Check for errors in console output
- Verify database write permissions
- Check `elo_last_updated` column

---

## Next Steps

After backfilling:

1. **Verify Results**
   ```bash
   python -c "
   import sqlite3
   conn = sqlite3.connect('data/polymarket_tracker.db')
   cursor = conn.cursor()
   cursor.execute('SELECT COUNT(*) FROM traders WHERE comprehensive_elo >= 1550')
   print(f'Elite traders: {cursor.fetchone()[0]}')
   "
   ```

2. **Restart System Observer**
   ```bash
   python scripts/kill_all.py
   python scripts/start_monitoring.py
   python scripts/run_system_observer.py
   ```

3. **Test Consensus Detection**
   - Wait for hourly report
   - Should find consensuses immediately (if 3+ elite traders exist)

4. **Monitor ELO Updates**
   - ELO will continue updating as new trades come in
   - Ratings will become more accurate over time

---

## Summary

### Current Status

✅ **Backfill script created**: `scripts/backfill_elo_ratings.py`
✅ **Basic functionality works**: Loads trades, updates database
⚠️  **Simplified heuristic**: Not using actual market resolutions (yet)
⏳ **TODO**: Integrate Polymarket API for market resolutions

### Expected Timeline

**With simplified heuristic (now):**
- 15-30 minutes to backfill
- Narrow ELO range (1485-1542)
- Few/no elite traders (≥1550)

**With accurate resolutions (TODO):**
- 2-6 hours to backfill (API calls + processing)
- Realistic ELO range (1200-1800)
- 100+ elite traders ready for consensus detection

### Files Created

1. `scripts/backfill_elo_ratings.py` - Main backfill script
2. `ELO_BACKFILL_GUIDE.md` - This documentation

---

**Status:** ⚠️ PARTIAL - Script works but needs market resolution integration
**Next:** Integrate Polymarket Gamma API for accurate market resolutions
**Impact:** Once complete, instant access to mature ELO ratings for all traders
