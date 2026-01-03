# Polymarket Trader Tracker - Monitoring System

How the real-time monitoring system works.

## Overview

The monitoring system tracks successful traders on Polymarket prediction markets, evaluates their trades, calculates ELO ratings, and sends Telegram notifications about elite trader activity.

**Core Flow:**
1. Poll Polymarket API for new trades every 15 minutes
2. Filter for geopolitical markets only
3. Track trader activity and positions
4. Detect market resolutions
5. Evaluate trade outcomes (won/lost)
6. Calculate comprehensive ELO ratings
7. Send Telegram alerts for elite traders

## Architecture

```
┌────────────────────┐       ┌──────────────────┐
│   Polymarket API   │──────>│  Market Filter   │
└────────────────────┘       └──────────────────┘
                                      │
                                      ▼
                             ┌──────────────────┐
                             │   Monitor Loop   │
                             │  (Every 15 min)  │
                             └──────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
       ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
       │  Database   │        │  ELO Bridge │        │  Telegram   │
       │   SQLite    │        │   System    │        │   Alerts    │
       └─────────────┘        └─────────────┘        └─────────────┘
```

## Key Components

### 1. Main Entry Point

**File:** `monitoring/main.py`

```bash
# Start monitoring
python -m monitoring.main
```

**What it does:**
- Loads configuration from `.env`
- Initializes database
- Initializes Telegram bots
- Starts monitoring loop

### 2. Monitor Loop

**File:** `monitoring/monitor.py`

**Class:** `PolymarketMonitor`

**Main cycle (every 15 minutes):**
1. Check for resolved markets
2. Evaluate trades as won/lost
3. Update trader statistics
4. Calculate ELO ratings
5. Send Telegram notifications

**Key methods:**
- `initial_scan()` - First run: populate database
- `monitoring_cycle()` - Main loop
- `check_for_resolutions()` - Detect resolved markets
- `process_resolved_market()` - Evaluate trades

### 3. Market Filtering

**File:** `monitoring/polymarket_client.py` (via database)

**Geopolitical categories monitored:**
- Politics
- World
- News

**Minimum requirements:**
- Active (not closed)
- Not archived
- Has trading activity

### 4. Database Layer

**File:** `monitoring/database.py`

**Class:** `Database`

**Tables:**

**`markets`** - Market information
- `condition_id` (primary key)
- `title`, `description`
- `category`
- `end_date_iso`, `resolved`, `winning_outcome`

**`trades`** - Trade history
- `trader_address` (indexed)
- `market_id`, `outcome`, `side` (buy/sell)
- `shares`, `price`, `timestamp`
- `outcome_won`, `outcome_lost` (after resolution)

**`traders`** - Trader profiles and statistics
- `address` (primary key)
- `total_trades`, `total_volume`
- `trades_won`, `trades_lost`, `win_rate`
- `comprehensive_elo` (6-dimension rating)

**`trader_positions`** - Current positions
- `trader_address`, `market_id`, `outcome`
- `shares`, `avg_price`
- Updated via FIFO matching

### 5. ELO Integration

**File:** `monitoring/elo_bridge.py`

**Class:** `ELOBridge`

**Connects monitoring system to analysis/unified_elo_system.py**

**Two modes:**

**Quick Update** (during monitoring cycle):
- Calculates 4/6 ELO dimensions
- Uses cached behavioral/advanced metrics
- Skips expensive network/contrarian analysis
- Target: <10 seconds for 50-100 traders

**Full Update** (on-demand or daily):
- Calculates all 6/6 ELO dimensions
- Fresh metrics for everything
- Includes network and contrarian analysis
- Target: <15 minutes for all traders

**Performance optimization:**
- Base ELO cached for 1 hour (avoids recalculating 1,946+ markets)
- Behavioral analysis cached
- Only P&L recalculated fresh each cycle

### 6. Position Tracking

**File:** `monitoring/position_tracker.py`

**Class:** `PositionTracker`

**FIFO matching algorithm:**
- Buys increase position
- Sells reduce position (oldest first)
- Tracks average entry price
- Calculates realized P&L

**Example:**
```
Buy 100 @ $0.50
Buy 50 @ $0.60
Sell 75 @ $0.70

Position: 75 shares @ $0.53 avg
P&L: +$15.00 (75 shares × $0.20)
```

### 7. Telegram Notifications

**File:** `monitoring/telegram_bot.py`

**Class:** `TelegramNotifier`

**Send-only mode** (no polling, no conflicts):
- Simple Bot instance
- Sends trade alerts
- No command handling

**Rate limiting:**
- 5-minute cooldown per trader
- Prevents notification spam

**File:** `monitoring/telegram_elo_bot.py`

**Class:** `ELOTelegramBot`

**Features:**
- Elite trader alerts (top 10 by ELO)
- Market momentum tracking
- Contrarian signal detection
- Large position alerts
- Win streak notifications

## Running the System

### Start Monitoring

**Windows:**
```bash
run_tracker.bat
```

**Linux/Mac:**
```bash
python -m monitoring.main
```

**Expected output:**
```
🚀 Starting Polymarket Monitor...
✅ Telegram bot initialized (send-only mode, no polling)
✅ ELO bot active (send-only mode, no polling conflicts)
🎯 Betting intelligence features enabled:
   - Elite trader alerts (top 10)
   - Market momentum tracking
   - Contrarian signal detection
   - Large position alerts
   - Win streak notifications
Performing initial scan...
```

### Stop Monitoring

**Ctrl+C** or kill the process:

```bash
# Windows
taskkill /F /IM python.exe

# Linux/Mac
pkill -f "monitoring.main"
```

## Configuration

### Environment Variables

**`.env` file:**
```env
# Polymarket API (optional)
POLYMARKET_API_KEY=your_key_here

# Telegram (required for alerts)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Monitoring Interval

**File:** `monitoring/monitor.py`

```python
MONITORING_INTERVAL = 900  # 15 minutes in seconds
```

### Market Categories

**File:** `monitoring/polymarket_client.py` (database filter)

Edit geopolitical category list in code or use database queries.

### Rate Limiting

**File:** `monitoring/telegram_bot.py`

```python
self.notification_cooldown = 300  # 5 minutes
```

## Utility Scripts

### View Trader Rankings

```bash
python scripts/view_trader_rankings.py
```

Shows top traders by comprehensive ELO rating.

### View Trader Statistics

```bash
python scripts/view_trader_stats.py [trader_address]
```

Shows detailed stats for specific trader.

### View P&L Performance

```bash
python scripts/view_pnl_performance.py
```

Shows profit/loss performance of tracked traders.

### Check ELO Status

```bash
python scripts/check_elo_status.py
```

Verifies ELO integration is working.

### Test Monitoring Integration

```bash
python scripts/test_monitoring_integration_trigger.py
```

Tests ELO calculation triggered by monitoring cycle.

### Recalculate ELO Ratings

```bash
python scripts/recalculate_comprehensive_elo.py
```

Force full ELO recalculation for all traders.

### Recalculate Trader Stats

```bash
python scripts/recalculate_trader_stats.py
```

Rebuild trader statistics from trade history.

## How Market Resolution Works

### Detection

Every monitoring cycle:
1. Query database for unresolved markets
2. Check Polymarket API for resolution status
3. Store winning outcome in database
4. Mark market as resolved

### Trade Evaluation

For each resolved market:
1. Fetch all trades for that market
2. Compare trade outcome vs winning outcome
3. Update `outcome_won` or `outcome_lost` in trades table
4. Update trader statistics (win rate)

### Position Settlement

1. Calculate final P&L for positions
2. Mark positions as closed
3. Store realized gains/losses

### ELO Update

1. Build positions from trades (FIFO)
2. Calculate comprehensive ELO via ELOBridge
3. Store in `traders.comprehensive_elo` column

## Performance

### Monitoring Cycle Timing

**Target:** <10 seconds per cycle

**Actual (with 50-100 active traders):**
- Market resolution check: ~2s
- Trade evaluation: ~1s
- Position updates: ~1s
- ELO calculation (quick): ~5s
- **Total: ~9s**

**Bottleneck:** ELO base rating recalculation (~200s if not cached)

**Solution:** Cache base ELO for 1 hour (see [ELO_PERFORMANCE_OPTIMIZATION.md](../ELO_PERFORMANCE_OPTIMIZATION.md))

### Database Size

**Typical growth:**
- 100 traders × 50 trades each = 5,000 trade records
- ~500 KB database size
- Lightweight and fast

### Memory Usage

**Typical:** 50-100 MB for monitoring process

## Error Handling

### API Errors

**Polymarket API down:**
- Monitoring continues
- Logs error
- Retries next cycle

**Rate limiting:**
- Exponential backoff implemented
- Waits before retry

### Database Errors

**Lock timeout:**
- Monitoring has write priority
- Retries after brief delay

**Corruption:**
- Auto-backup before migrations
- Backups in `data/backups/`

### Telegram Errors

**Bot conflict (FIXED):**
- Both bots in send-only mode
- No polling = no conflicts

**Send failure:**
- Logged but doesn't stop monitoring
- Retries on next alert

## Telegram Alerts

### Trade Alerts

**Single trade:**
```
🚨 New Trade Alert!

Trader: 0x1234567890abcd...
Volume: $5,432.10 (87 trades)

Market: Will Trump win 2024?
Outcome: Yes
Side: BUY
Shares: 250.00
Price: $0.6543
Time: 2026-01-03 14:32:15
```

**Multiple trades (bundled):**
```
🚨 5 New Trades!

Trader: 0x1234567890abcd...
Volume: $5,432.10 (87 trades)

Trade 1:
  Market: Will Trump win 2024?
  Yes BUY 250.0 @ $0.654

Trade 2:
  Market: Will Ukraine join NATO?
  No SELL 100.0 @ $0.345
...
```

### Elite Trader Alerts

```
🏆 ELITE TRADER ALERT

Trader: 0x1234...
Rank: #5 (ELO: 1847)
Recent win streak: 5 trades
Win rate: 68.5%
Total volume: $125,432.50
```

### Market Momentum

```
📈 MARKET MOMENTUM

Market: Will Trump win 2024?
Volume surge: +450% (24h)
Price movement: $0.45 → $0.67
Elite traders active: 8
```

## Monitoring Best Practices

### 1. Let It Run Continuously

Don't stop/start frequently - let it build up trade history.

### 2. Check Telegram Regularly

Alerts happen in real-time as trades occur.

### 3. Weekly ELO Recalculation

Run full ELO update weekly:
```bash
python scripts/recalculate_comprehensive_elo.py
```

### 4. Monitor Disk Space

Database grows slowly but check if running long-term.

### 5. Keep Dependencies Updated

```bash
pip install -r requirements.txt --upgrade
```

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed solutions.

**Common issues:**
- Telegram conflicts → Fixed (both bots send-only)
- Slow ELO calculation → Use caching (already implemented)
- Database locks → Only run one monitoring instance
- No notifications → Check Telegram token/chat ID in `.env`

## Related Documentation

- [SETUP.md](SETUP.md) - Installation and configuration
- [ELO_SYSTEM.md](ELO_SYSTEM.md) - How ELO ratings work
- [SYSTEM_OBSERVER.md](SYSTEM_OBSERVER.md) - AI-powered health monitoring
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [API.md](API.md) - Data structures and API docs
