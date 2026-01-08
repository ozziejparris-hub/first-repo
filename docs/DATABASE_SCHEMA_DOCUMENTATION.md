# Database Schema Documentation
*Generated: 2026-01-06 18:15*

## Overview

The Polymarket Trader Tracker uses a SQLite database to track trades, markets, traders, and positions. The database consists of 4 main tables with 12 indexes for optimized queries.

**Database File:** `data/polymarket_tracker.db`

---

## Database Statistics

- **Total trades:** 15,674
- **Total markets:** 213,461
- **Resolved markets:** 2,366
- **Pending markets:** 211,095
- **Total traders:** 34,614
- **Tracked positions:** 8,591

**Trade Distribution:**
- BUY trades: 12,473 (79.6%)
- SELL trades: 3,201 (20.4%)

**Primary Category:** Geopolitics (100% of trades are geopolitics-filtered)

---

## Table Schemas

### traders

**Purpose:** Track individual trader statistics, performance metrics, and ELO ratings

**Schema:**
```sql
CREATE TABLE traders (
    address TEXT PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    successful_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    total_volume REAL DEFAULT 0.0,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_flagged BOOLEAN DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    avg_roi REAL DEFAULT 0,
    total_invested REAL DEFAULT 0,
    closed_positions INTEGER DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    comprehensive_elo REAL DEFAULT 1500,
    base_category_elo REAL DEFAULT 1500,
    elo_last_updated TIMESTAMP DEFAULT NULL,
    behavioral_modifier REAL DEFAULT 1.0,
    advanced_modifier REAL DEFAULT 1.0,
    pnl_modifier REAL DEFAULT 1.0
)
```

**Column Details:**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| address | TEXT | NO (PK) | Trader's Ethereum wallet address (0x...) |
| total_trades | INTEGER | YES | Total number of trades executed |
| successful_trades | INTEGER | YES | Number of winning trades |
| win_rate | REAL | YES | Percentage of winning trades (0.0-1.0) |
| total_volume | REAL | YES | Total dollar volume traded |
| first_seen | TIMESTAMP | YES | First time trader was observed |
| last_updated | TIMESTAMP | YES | Last time trader stats were updated |
| is_flagged | BOOLEAN | YES | Flag for notable traders |
| realized_pnl | REAL | YES | P&L from closed positions |
| unrealized_pnl | REAL | YES | P&L from open positions |
| total_pnl | REAL | YES | Total P&L (realized + unrealized) |
| avg_roi | REAL | YES | Average return on investment |
| total_invested | REAL | YES | Total amount invested |
| closed_positions | INTEGER | YES | Number of closed positions |
| open_positions | INTEGER | YES | Number of currently open positions |
| comprehensive_elo | REAL | YES | Overall ELO rating (starts at 1500) |
| base_category_elo | REAL | YES | Base ELO for category (starts at 1500) |
| elo_last_updated | TIMESTAMP | YES | Last ELO calculation timestamp |
| behavioral_modifier | REAL | YES | Behavioral pattern modifier (default 1.0) |
| advanced_modifier | REAL | YES | Advanced metrics modifier (default 1.0) |
| pnl_modifier | REAL | YES | P&L-based modifier (default 1.0) |

**Sample Row:**
```
address: 0x46b6820bf82ca3a118623491e452d7e5f7cb128d
total_trades: 78
successful_trades: 0
win_rate: 0.0
total_volume: 982.46
first_seen: 2025-11-20 21:01:52
last_updated: 2025-11-20 21:01:52.320838
is_flagged: 0
realized_pnl: 0.0
unrealized_pnl: 0.0
total_pnl: 0.0
avg_roi: 0.0
total_invested: 0.0
closed_positions: 0
open_positions: 0
comprehensive_elo: 1500.0
base_category_elo: 1500.0
elo_last_updated: None
behavioral_modifier: 1.0
advanced_modifier: 1.0
pnl_modifier: 1.0
```

**Relationships:**
- Referenced by trades.trader_address (FOREIGN KEY)
- Referenced by positions.trader_address (FOREIGN KEY)

**Indexes:**
- `idx_traders_comprehensive_elo` - For ranking queries
- `idx_traders_elo_updated` - For finding traders needing ELO updates

---

### trades

**Purpose:** Record all individual trade transactions

**Schema:**
```sql
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    trader_address TEXT,
    market_id TEXT,
    market_title TEXT,
    market_category TEXT,
    outcome TEXT,
    shares REAL,
    price REAL,
    side TEXT,
    timestamp TIMESTAMP,
    notified BOOLEAN DEFAULT 0,
    completed BOOLEAN DEFAULT 0,
    was_successful BOOLEAN,
    outcome_bet TEXT,
    trade_result TEXT DEFAULT 'pending',
    FOREIGN KEY (trader_address) REFERENCES traders(address)
)
```

**Column Details:**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| trade_id | TEXT | NO (PK) | Unique trade identifier (transaction hash) |
| trader_address | TEXT | YES | Ethereum address of trader (FK to traders) |
| market_id | TEXT | YES | Market identifier (condition ID) |
| market_title | TEXT | YES | Human-readable market question |
| market_category | TEXT | YES | Market category (e.g., "Geopolitics") |
| outcome | TEXT | YES | Outcome being traded (e.g., "Yes", "No") |
| shares | REAL | YES | Number of shares traded |
| price | REAL | YES | Price per share (0.0-1.0) |
| side | TEXT | YES | Trade direction ("BUY" or "SELL") |
| timestamp | TIMESTAMP | YES | When trade occurred |
| notified | BOOLEAN | YES | Whether Telegram notification sent |
| completed | BOOLEAN | YES | Whether trade is complete |
| was_successful | BOOLEAN | YES | Whether trade was profitable (after resolution) |
| outcome_bet | TEXT | YES | Outcome that was bet on |
| trade_result | TEXT | YES | Result status ("pending", "win", "loss") |

**Sample Row:**
```
trade_id: 0xc19837b3e5f3989dfd4da75ef568af9f97e4685d665faa828b3c928cdb8bbe3a
trader_address: 0x0c36bdedfbe0282ad9583bb30e4d2f0683d074df
market_id: 0xef5880e94212f24f17d45b756c9aa42bc7d39c3feda659fc22417adae5e22d00
market_title: Will Catalin Drula be the next Mayor of Bucharest?
market_category: Geopolitics
outcome: No
shares: 12.0
price: 0.89
side: BUY
timestamp: 2025-11-20 21:10:39
notified: 1
completed: 0
was_successful: None
outcome_bet: None
trade_result: pending
```

**Relationships:**
- Foreign key to traders(address) via trader_address
- Links to markets(market_id) via market_id (no FK constraint)
- Referenced by positions via trade IDs

**Indexes:**
- `idx_trades_market_result` - For market resolution queries
- `idx_trades_trader_result` - For trader performance queries
- `idx_market_has_trades` - For finding markets with trades

**Trade Side Distribution:**
- BUY: 12,473 (79.6%)
- SELL: 3,201 (20.4%)

---

### markets

**Purpose:** Store market metadata and resolution status

**Schema:**
```sql
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,
    title TEXT,
    category TEXT,
    end_date TIMESTAMP,
    resolved BOOLEAN DEFAULT 0,
    winning_outcome TEXT,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolution_date TIMESTAMP,
    condition_id TEXT,
    api_id TEXT
)
```

**Column Details:**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| market_id | TEXT | NO (PK) | Primary market identifier (API ID or condition ID) |
| title | TEXT | YES | Market question text |
| category | TEXT | YES | Market category |
| end_date | TIMESTAMP | YES | Market closing date |
| resolved | BOOLEAN | YES | Whether market outcome is determined |
| winning_outcome | TEXT | YES | Winning outcome (if resolved) |
| last_checked | TIMESTAMP | YES | Last time market was checked for resolution |
| resolution_date | TIMESTAMP | YES | When market was resolved |
| condition_id | TEXT | YES | Polymarket condition ID (for matching trades) |
| api_id | TEXT | YES | Polymarket API ID (for /markets/{id} endpoint) |

**Sample Resolved Market:**
```
market_id: 0x9b946f54f3428aafc308c33aa04a943fe13a011bdac9a9b66e1ba16c416ca256
title: Will Kim Kardashian and Kanye West divorce before Jan 1, 2021?
category: Pop-Culture
end_date: 2021-01-02T00:00:00Z
resolved: 1
winning_outcome: No
last_checked: 2025-12-11 15:15:05.889436
resolution_date: 2025-12-11 15:15:05.889434
condition_id: 0x9b946f54f3428aafc308c33aa04a943fe13a011bdac9a9b66e1ba16c416ca256
api_id: 19
```

**Sample Pending Market:**
```
market_id: 0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9
title: Will Joe Biden get Coronavirus before the election?
category: US-current-affairs
end_date: 2020-11-04T00:00:00Z
resolved: 0
winning_outcome: None
last_checked: 2025-12-11 11:00:40.941163
resolution_date: None
condition_id: 0xe3b423dfad8c22ff75c9899c4e8176f628cf4ad4caa00481764d320e7415f7a9
api_id: 12
```

**Relationships:**
- Referenced by trades via market_id (no FK constraint)
- Referenced by positions via market_id (no FK constraint)

**Indexes:**
- `idx_markets_condition_id` - For fast condition ID lookups
- `idx_markets_api_id` - For API ID lookups

**Important Notes:**
- Polymarket uses TWO ID types:
  - `api_id`: For `/markets/{id}` API endpoint (e.g., "21742")
  - `condition_id`: For matching trades (hex string like "0x1b6f76e5...")
- Some markets have both IDs, some only have one
- The system stores both for maximum compatibility

---

### positions

**Purpose:** Track FIFO-matched trading positions for P&L calculation

**Schema:**
```sql
CREATE TABLE positions (
    position_id TEXT PRIMARY KEY,
    trader_address TEXT NOT NULL,
    market_id TEXT NOT NULL,
    market_title TEXT,
    outcome TEXT NOT NULL,

    -- Entry (BUY trades)
    entry_shares REAL NOT NULL,
    entry_avg_price REAL NOT NULL,
    entry_total_cost REAL NOT NULL,
    entry_timestamp TIMESTAMP NOT NULL,
    entry_trade_ids TEXT,

    -- Exit (SELL trades)
    exit_shares REAL,
    exit_avg_price REAL,
    exit_total_received REAL,
    exit_timestamp TIMESTAMP,
    exit_trade_ids TEXT,

    -- P&L Metrics
    realized_pnl REAL,
    roi_percent REAL,
    holding_period_hours REAL,

    -- Position Status
    status TEXT NOT NULL,
    remaining_shares REAL,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (trader_address) REFERENCES traders(address)
)
```

**Column Details:**

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| position_id | TEXT | NO (PK) | Unique position identifier |
| trader_address | TEXT | NO | Trader's wallet address (FK) |
| market_id | TEXT | NO | Market identifier |
| market_title | TEXT | YES | Market question text |
| outcome | TEXT | NO | Outcome position is for |
| entry_shares | REAL | NO | Total shares bought |
| entry_avg_price | REAL | NO | Average entry price |
| entry_total_cost | REAL | NO | Total cost of entry |
| entry_timestamp | TIMESTAMP | NO | When position was opened |
| entry_trade_ids | TEXT | YES | JSON array of entry trade IDs |
| exit_shares | REAL | YES | Total shares sold |
| exit_avg_price | REAL | YES | Average exit price |
| exit_total_received | REAL | YES | Total received from exit |
| exit_timestamp | TIMESTAMP | YES | When position was closed |
| exit_trade_ids | TEXT | YES | JSON array of exit trade IDs |
| realized_pnl | REAL | YES | Realized profit/loss |
| roi_percent | REAL | YES | Return on investment % |
| holding_period_hours | REAL | YES | Time position was held |
| status | TEXT | NO | Position status ("open", "closed", "partial") |
| remaining_shares | REAL | YES | Shares still held |
| created_at | TIMESTAMP | YES | Position creation timestamp |
| last_updated | TIMESTAMP | YES | Last update timestamp |

**Sample Position:**
```
position_id: 0x30cecd_0x6d1ed3_No_1763969365
trader_address: 0x30cecdf29f069563ea21b8ae94492e41e53a6b2b
market_id: 0x6d1ed397657b875e9908b33609df303fe66938fe2a7af7f36c39fb45b3b0a1c7
market_title: Will Z.ai have the best AI model at the end of November 2025?
outcome: No
entry_shares: 123.32
entry_avg_price: 0.999
entry_total_cost: 123.197
entry_timestamp: 2025-11-24T07:29:25
entry_trade_ids: ["0x2e2355284e584a8cd85244ff8acf0aeb7074a9aaf92f85456f8cd3b0700f2a15"]
exit_shares: None
exit_avg_price: None
exit_total_received: None
exit_timestamp: None
exit_trade_ids: []
realized_pnl: None
roi_percent: None
holding_period_hours: None
status: open
remaining_shares: 123.32
created_at: 2025-12-12 12:55:05
last_updated: 2025-12-12 12:55:05
```

**Relationships:**
- Foreign key to traders(address) via trader_address
- Links to markets via market_id (no FK constraint)
- Links to trades via trade IDs in JSON arrays

**Indexes:**
- `idx_positions_trader` - For trader's positions lookup
- `idx_positions_market` - For market positions lookup
- `idx_positions_status` - For filtering by status
- `idx_positions_trader_status` - Combined trader+status queries
- `idx_positions_trader_market` - Combined trader+market queries

**Position Types:**
- **Open:** Active position with shares held
- **Closed:** Fully exited position
- **Partial:** Partially closed position

---

## Key Code Insights

### Database.add_trade() Method

**Purpose:** Insert a new trade into the database

**Signature:**
```python
def add_trade(self, trade_id: str, trader_address: str, market_id: str,
              market_title: str, market_category: str, outcome: str,
              shares: float, price: float, side: str, timestamp: datetime,
              outcome_bet: str = None) -> bool
```

**Parameters:**
- `trade_id` (str): Unique transaction hash
- `trader_address` (str): Trader's Ethereum address
- `market_id` (str): Market identifier (condition ID)
- `market_title` (str): Human-readable market question
- `market_category` (str): Market category
- `outcome` (str): Outcome being traded
- `shares` (float): Number of shares
- `price` (float): Price per share (0.0-1.0)
- `side` (str): "BUY" or "SELL"
- `timestamp` (datetime): Trade timestamp
- `outcome_bet` (str, optional): Outcome bet on (defaults to outcome)

**Returns:** `bool` - True if inserted, False if trade already exists

**Key Logic:**
- Uses `INSERT` with IntegrityError handling for duplicates
- Defaults `outcome_bet` to `outcome` if not provided
- Auto-closes connection after insert
- Uses `@retry_on_locked` decorator for database lock handling

---

### Database.store_market_dict() Method

**Purpose:** Store market information from Polymarket API response

**Key Logic:**
- Handles BOTH `id` (API ID) and `conditionId` fields
- Prioritizes `api_id` for primary market_id
- Falls back to `conditionId` if `api_id` not available
- Checks for existing markets before inserting
- Extracts end_date from various formats (timestamp, ISO string)
- Detects pre-resolved markets via `closed` or `archived` flags

**Important:** Polymarket uses two ID systems:
1. **API ID** (`id` field): For `/markets/{id}` endpoint (numeric like "21742")
2. **Condition ID** (`conditionId`): For matching trades (hex string)

The database stores both for maximum compatibility.

---

### Database.update_market_resolution() Method

**Purpose:** Mark a market as resolved with winning outcome

**Parameters:**
- `market_id` (str): Market identifier
- `winning_outcome` (str): Winning outcome ("Yes", "No", or specific outcome name)

**Updates:**
- Sets `resolved = 1`
- Sets `winning_outcome`
- Sets `resolution_date` to current timestamp
- Updates `last_checked` timestamp

---

### Database.add_or_update_trader() Method

**Purpose:** Insert or update trader statistics

**Key Logic:**
- Uses `INSERT ... ON CONFLICT DO UPDATE` (upsert pattern)
- Updates all trader stats atomically
- Sets `last_updated` timestamp
- Allows flagging traders as notable

---

### Position Tracking

**File:** `monitoring/position_tracker.py`

**Purpose:** Implements FIFO (First-In-First-Out) position matching for accurate P&L calculation

**Key Features:**
- Matches SELL trades against oldest BUY trades
- Calculates realized P&L for closed positions
- Tracks partial position closes
- Stores entry/exit trade IDs for audit trail
- Calculates ROI and holding period

**Referenced by:**
- ELO system for performance metrics
- Trader statistics updates
- P&L reporting

---

### ELO System Requirements

**File:** `analysis/unified_elo_system.py`

**UnifiedELOSystem expects:**

**From trades table:**
- `trader_address` - Trader identifier
- `market_id` - Market identifier
- `outcome` - Outcome traded
- `shares` - Position size
- `price` - Entry/exit price
- `side` - BUY or SELL
- `timestamp` - Trade timing
- `trade_result` - Win/loss status (after resolution)

**From markets table:**
- `market_id` - Market identifier
- `category` - Market category
- `resolved` - Whether market is resolved
- `winning_outcome` - Winning outcome

**From traders table:**
- `address` - Trader identifier
- `comprehensive_elo` - Current ELO rating
- `base_category_elo` - Category-specific ELO
- `behavioral_modifier` - Behavioral pattern modifier
- `advanced_modifier` - Advanced metrics modifier
- `pnl_modifier` - P&L-based modifier
- `total_pnl` - Total profit/loss
- `avg_roi` - Average ROI

**ELO Dimensions:**
1. **Comprehensive ELO** - Overall rating (starts at 1500)
2. **Base Category ELO** - Category-specific rating
3. **Behavioral Modifier** - Adjusts for trading patterns
4. **Advanced Modifier** - Adjusts for advanced metrics
5. **PnL Modifier** - Adjusts for profit/loss performance

---

## Data Patterns Observed

### Trade Distribution
- **BUY trades:** 12,473 (79.6%)
- **SELL trades:** 3,201 (20.4%)

**Interpretation:** Most traders are accumulating positions, with fewer exits. This is typical of prediction markets where traders hold until resolution.

### Market Categories
- **Primary:** Geopolitics (100% of current trades)

**Note:** The system is configured to filter for geopolitics markets only. Other categories exist in the database but are not actively monitored.

### Sample Trade Sequence

**Trader:** `0x000d257d2dc7616fea...`

```
1. Will José Antonio Kast win the Chilean presidential election?
   Outcome: Yes, Shares: 2106.76, Price: 0.967, Side: BUY
   Timestamp: 2025-12-06 00:44:21

2. Will Donald Trump be TIME's Person of the Year for 2025?
   Outcome: No, Shares: 8000.0, Price: 0.94, Side: BUY
   Timestamp: 2025-12-06 00:44:53

3. Trump declassifies UFO files in 2025?
   Outcome: Yes, Shares: 2284.73, Price: 0.894, Side: BUY
   Timestamp: 2025-12-08 18:03:39

4. Trump declassifies UFO files in 2025?
   Outcome: Yes, Shares: 8098.38, Price: 0.918, Side: BUY
   Timestamp: 2025-12-08 18:03:47

5. Trump declassifies UFO files in 2025?
   Outcome: Yes, Shares: 13027.04, Price: 0.988, Side: BUY
   Timestamp: 2025-12-09 21:58:22
```

**Pattern Observations:**
- Trader accumulates large positions (2000-13000 shares)
- Focuses on political outcomes
- Multiple entries on same market (averaging in)
- High-conviction bets (prices 0.89-0.99)

---

## Critical Fields for Simulation

### Must Match Exactly

#### 1. trades table
**Required fields:**
- `trade_id` (TEXT, unique) - Transaction hash format: "0x[64 hex chars]"
- `trader_address` (TEXT) - Ethereum address: "0x[40 hex chars]"
- `market_id` (TEXT) - Condition ID: "0x[64 hex chars]"
- `market_title` (TEXT) - Question text
- `market_category` (TEXT) - Category (e.g., "Geopolitics")
- `outcome` (TEXT) - "Yes", "No", or outcome name
- `shares` (REAL) - Positive number
- `price` (REAL) - Between 0.0 and 1.0
- `side` (TEXT) - "BUY" or "SELL"
- `timestamp` (TIMESTAMP) - ISO format datetime

**Data types:**
- IDs: TEXT (hex strings starting with "0x")
- Amounts: REAL (floating point)
- Booleans: INTEGER (0 or 1)
- Timestamps: TEXT (ISO 8601 format)

**Constraints:**
- `trade_id` must be unique (PRIMARY KEY)
- `price` must be 0.0-1.0
- `side` must be "BUY" or "SELL"
- `trader_address` must exist in traders table (FOREIGN KEY)

#### 2. markets table
**Required fields:**
- `market_id` (TEXT, unique) - Primary identifier
- `title` (TEXT) - Market question
- `category` (TEXT) - Market category
- `end_date` (TIMESTAMP, nullable) - Market close date
- `resolved` (BOOLEAN) - 0 or 1
- `winning_outcome` (TEXT, nullable) - Winning outcome if resolved

**Resolution fields:**
- `resolution_date` - When market was resolved
- `condition_id` - For matching trades
- `api_id` - For API lookups

**Constraints:**
- `market_id` must be unique (PRIMARY KEY)
- If `resolved = 1`, must have `winning_outcome`
- If `resolved = 1`, should have `resolution_date`

#### 3. traders table
**Required fields:**
- `address` (TEXT, unique) - Ethereum address
- `total_trades` (INTEGER) - Count of trades
- `total_volume` (REAL) - Dollar volume
- `comprehensive_elo` (REAL) - ELO rating (default 1500)

**Constraints:**
- `address` must be unique (PRIMARY KEY)
- `total_trades` must be >= 0
- `comprehensive_elo` typically 800-2200

### Optional/Derived Fields

**trades table:**
- `notified` - Set by notification system
- `completed` - Set by position tracker
- `was_successful` - Set after market resolution
- `trade_result` - Derived from market resolution

**traders table:**
- `successful_trades` - Calculated from resolved trades
- `win_rate` - Calculated: successful_trades / total_trades
- `realized_pnl` - Calculated from closed positions
- `unrealized_pnl` - Calculated from open positions
- `total_pnl` - Sum of realized + unrealized
- ELO modifiers - Calculated by ELO system

**positions table:**
- All fields calculated by position tracker
- Not required for basic simulation

---

## Simulation Requirements Summary

To create a perfect simulation, must generate:

### 1. ✅ Trades
**Exact fields needed:**
```python
{
    'trade_id': '0x' + 64_hex_chars,
    'trader_address': '0x' + 40_hex_chars,
    'market_id': '0x' + 64_hex_chars,
    'market_title': 'Market question text',
    'market_category': 'Geopolitics',
    'outcome': 'Yes' or 'No',
    'shares': float (positive),
    'price': float (0.0-1.0),
    'side': 'BUY' or 'SELL',
    'timestamp': datetime,
    'outcome_bet': 'Yes' or 'No' (optional, defaults to outcome)
}
```

### 2. ✅ Markets
**Exact fields needed:**
```python
{
    'market_id': '0x' + 64_hex_chars,
    'title': 'Market question',
    'category': 'Geopolitics',
    'end_date': datetime or None,
    'resolved': 0 or 1,
    'winning_outcome': 'Yes'/'No'/None,
    'condition_id': '0x' + 64_hex_chars,
    'api_id': str (optional)
}
```

### 3. ✅ Traders
**Exact fields needed:**
```python
{
    'address': '0x' + 40_hex_chars,
    'total_trades': int (>= 0),
    'total_volume': float (>= 0),
    'comprehensive_elo': float (default 1500),
    'base_category_elo': float (default 1500)
}
```

### 4. ✅ Relationships
**Must maintain:**
- Every trade must reference an existing trader (via trader_address)
- Every trade should reference an existing market (via market_id)
- Trade IDs must be globally unique
- Market IDs must be globally unique
- Trader addresses must be globally unique

---

## Questions for Implementation

### 1. How are market IDs generated?
**Pattern:** 64-character hex string (0x + 64 hex digits)
**Example:** `0xef5880e94212f24f17d45b756c9aa42bc7d39c3feda659fc22417adae5e22d00`
**For simulation:** Can use `hashlib.sha256()` or `secrets.token_hex(32)`

### 2. How are trade IDs generated?
**Pattern:** Transaction hash - 64-character hex string
**Example:** `0xc19837b3e5f3989dfd4da75ef568af9f97e4685d665faa828b3c928cdb8bbe3a`
**For simulation:** Can use `hashlib.sha256()` or `secrets.token_hex(32)`

### 3. What triggers market resolution?
**Based on code inspection:**
- Markets checked periodically via `get_unresolved_markets()`
- Resolution fetched from Polymarket API endpoint `/markets/{api_id}`
- Winning outcome extracted from API response
- `update_market_resolution()` called with winning outcome
- All trades for that market updated with `was_successful` status

### 4. How is FIFO position matching implemented?
**Based on position_tracker.py:**
- All BUY trades create or add to positions
- SELL trades matched against oldest open positions (FIFO)
- P&L calculated as: (exit_price - entry_price) * shares_sold
- Partial closes supported (remaining_shares tracked)
- Trade IDs stored in JSON arrays for audit trail

---

## Next Steps for Simulation

### 1. Create Seed Script
Generate realistic data matching these exact schemas:
- Generate unique hex IDs for trades, markets, traders
- Create interconnected trades referencing markets and traders
- Include mix of BUY/SELL (80/20 ratio)
- Set realistic prices (0.3-0.95 range for competitive markets)
- Include timestamps spanning realistic time period

### 2. Ensure FK Relationships
- Create all traders first
- Create all markets second
- Create trades last (referencing traders and markets)
- Validate all FK references exist

### 3. Generate Realistic Trade Sequences
- Multiple trades per trader (5-100 range)
- Multiple traders per market (10-1000 range)
- Realistic accumulation patterns (multiple BUYs)
- Some exit trades (SELLs) for ~20% of positions
- Coherent timestamps (chronological, realistic intervals)

### 4. Test with ELO System
- Feed simulated data to UnifiedELOSystem
- Verify ELO calculations run without errors
- Check that ELO ratings update correctly
- Validate modifiers are applied

### 5. Verify Monitoring System
- Import simulated data into test database
- Run monitoring components
- Verify position tracker processes trades
- Check that trader stats update correctly

---

## Database Maintenance Notes

### Backup Strategy
```bash
# Backup database
cp data/polymarket_tracker.db data/polymarket_tracker_backup_$(date +%Y%m%d).db

# Verify backup
sqlite3 data/polymarket_tracker_backup_*.db "SELECT COUNT(*) FROM trades;"
```

### Vacuum Database
```sql
-- Reclaim space after deletions
VACUUM;

-- Analyze for query optimization
ANALYZE;
```

### Check Database Integrity
```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

---

## Performance Optimization

### Current Indexes (12 total)
- **Markets:** condition_id, api_id
- **Trades:** market_result, trader_result, market_has_trades
- **Positions:** trader, market, status, trader_status, trader_market
- **Traders:** comprehensive_elo, elo_updated

### Query Patterns Optimized
- Find unresolved markets
- Get trader's trades
- Get market's trades
- Get positions by trader
- Get positions by market
- Get top traders by ELO
- Get traders needing ELO update

### Recommended Queries
```sql
-- Get trader's performance
SELECT * FROM traders WHERE address = ?;

-- Get trader's recent trades
SELECT * FROM trades
WHERE trader_address = ?
ORDER BY timestamp DESC
LIMIT 10;

-- Get market's trades
SELECT * FROM trades
WHERE market_id = ?
ORDER BY timestamp;

-- Get open positions
SELECT * FROM positions
WHERE trader_address = ? AND status = 'open';

-- Get top traders by ELO
SELECT address, comprehensive_elo, total_trades, win_rate
FROM traders
ORDER BY comprehensive_elo DESC
LIMIT 100;
```

---

*End of Documentation*
