# Polymarket Trader Tracker - Setup Guide

Complete installation and configuration guide.

## Prerequisites

- Python 3.8 or higher
- Git
- Telegram account (for notifications)
- Polymarket API access (optional, for enhanced features)

## Installation

### 1. Clone Repository

```bash
git clone <repository-url>
cd first-repo
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

**Core Dependencies:**
- `python-telegram-bot` - Telegram notifications
- `requests` - API calls
- `sqlite3` - Database (included with Python)
- `pandas` - Data analysis
- `numpy` - Numerical computation

**Optional (for AI Observer - Phase 2):**
- Ollama/Mistral installed locally for AI analysis

### 3. Configure Environment Variables

#### Create .env File

```bash
cp .env.example .env
```

#### Required Configuration

Edit `.env` and add your credentials:

```env
# Polymarket API (OPTIONAL - for enhanced market data)
POLYMARKET_API_KEY=your_polymarket_api_key_here

# Telegram Bot (REQUIRED for notifications)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

### 4. Set Up Telegram Bot

#### Get Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` command
3. Follow prompts to create your bot
4. Copy the API token provided
5. Add token to `.env` as `TELEGRAM_BOT_TOKEN`

#### Get Your Chat ID

```bash
python scripts/get_telegram_chat_id.py
```

1. Run the script above
2. Send any message to your bot in Telegram
3. The script will display your chat ID
4. Add it to `.env` as `TELEGRAM_CHAT_ID`

### 5. Database Setup

The database is created automatically on first run:

```bash
python -m monitoring.main
```

**Database location:** `data/polymarket_tracker.db`

**Tables created:**
- `markets` - Market information
- `trades` - Trade history
- `traders` - Trader profiles and statistics
- `trader_positions` - Current positions
- `baselines` - Performance baselines (Observer)

## Polymarket API Setup (Optional)

### Current Status

The Polymarket Gamma API (`https://gamma-api.polymarket.com`) **requires authentication** as of November 2025.

### Getting API Access

#### Option 1: Official Polymarket API Key

1. Visit [Polymarket.com](https://polymarket.com)
2. Create an account or log in
3. Navigate to Developer/API settings
4. Generate an API key
5. Add to `.env` as `POLYMARKET_API_KEY`

#### Option 2: Use Polymarket's Official Python Client

```bash
pip install py-clob-client
```

This client handles authentication automatically.

#### Option 3: Public Data Only

The tracker can work with limited public data without an API key, but some features may be restricted.

## Configuration Options

### Market Filtering

Edit `monitoring/market_filter.py` to customize:

```python
# Geographic categories to monitor
GEOPOLITICAL_CATEGORIES = [
    'Politics',
    'World',
    'News'
]

# Minimum market volume (USD)
MIN_MARKET_VOLUME = 1000
```

### Notification Cooldown

Edit `monitoring/telegram_bot.py`:

```python
# Time between notifications for same trader (seconds)
self.notification_cooldown = 300  # 5 minutes
```

### ELO System Parameters

Edit `analysis/unified_elo_system.py`:

```python
# ELO K-factor (rating volatility)
self.k_factor = 32  # Higher = more volatile ratings

# Base ELO rating for new traders
self.base_elo = 1500
```

## Verification

### Test Database Connection

```bash
python scripts/check_schema.py
```

### Test Polymarket API

```bash
python scripts/test_polymarket.py
```

**Expected:** Lists of active markets or clear error messages

### Test Telegram Bot

```bash
python scripts/test_telegram_bot_integration.py
```

**Expected:** Test message sent to your Telegram chat

### Test ELO System

```bash
python scripts/test_elo_performance.py
```

**Expected:** ELO calculation performance metrics

## First Run

### Start Monitoring

```bash
# Windows
run_tracker.bat

# Linux/Mac
python -m monitoring.main
```

**Expected output:**
```
🚀 Starting Polymarket Monitor...
✅ Telegram bot initialized (send-only mode, no polling)
✅ ELO bot active (send-only mode, no polling conflicts)
🎯 Betting intelligence features enabled
Performing initial scan...
```

### Start System Observer (Optional)

```bash
# Windows
run_observer.bat

# Linux/Mac
python scripts/run_system_observer.py
```

**Expected output:**
```
[OBSERVER] Health Observer Starting...
[OBSERVER] ✓ Health checker initialized
[OBSERVER] ✓ Log monitor initialized
[OBSERVER] ✓ Telegram health bot initialized
```

## Directory Structure

After setup, your project should look like:

```
first-repo/
├── .env                    # Your configuration (DO NOT COMMIT)
├── .env.example           # Example configuration
├── requirements.txt        # Python dependencies
│
├── monitoring/            # Core monitoring system
│   ├── main.py           # Entry point
│   ├── monitor.py        # Main loop
│   ├── database.py       # Database layer
│   └── ...
│
├── analysis/             # ELO & analytics
│   ├── unified_elo_system.py
│   └── ...
│
├── scripts/              # Utility scripts
│   ├── get_telegram_chat_id.py
│   └── ...
│
├── docs/                 # Documentation
│   ├── SETUP.md         # This file
│   └── ...
│
├── data/                 # Database files
│   └── polymarket_tracker.db
│
├── reports/              # Generated reports
│   └── ...
│
└── logs/                 # Log files
    └── monitoring.log
```

## Common Setup Issues

### Issue: "No module named 'monitoring'"

**Cause:** Running script from wrong directory

**Solution:**
```bash
# Ensure you're in project root
cd first-repo
python -m monitoring.main
```

### Issue: "Chat ID not configured"

**Cause:** Missing `TELEGRAM_CHAT_ID` in `.env`

**Solution:**
```bash
python scripts/get_telegram_chat_id.py
# Add output to .env
```

### Issue: "Database locked"

**Cause:** Multiple instances running

**Solution:**
```bash
# Windows: Kill all python processes
taskkill /F /IM python.exe

# Linux/Mac
pkill -f python
```

### Issue: "403 Access Denied" from Polymarket API

**Cause:** API requires authentication

**Solution:**
1. Get API key from Polymarket
2. Add to `.env` as `POLYMARKET_API_KEY`
3. Or use public data only (limited features)

### Issue: Telegram "Conflict: terminated by other getUpdates request"

**Cause:** Multiple bot instances running (FIXED in recent update)

**Solution:**
- This should not occur anymore
- Both bots run in send-only mode (no polling)
- If it does occur: Kill all python processes and restart

## Post-Setup

### Next Steps

1. ✅ **Monitor trader activity** - Let it run and observe Telegram notifications
2. ✅ **Review ELO rankings** - Run `python scripts/view_trader_rankings.py`
3. ✅ **Check system health** - Start the observer for AI-powered monitoring
4. ✅ **Explore analytics** - See [ELO_SYSTEM.md](ELO_SYSTEM.md) for analysis tools

### Recommended Workflow

**Daily:**
- Check Telegram for elite trader alerts
- Review system health reports (if observer running)

**Weekly:**
- Review top trader rankings: `python scripts/view_trader_rankings.py`
- Check performance metrics: `python scripts/view_trader_stats.py`

**As Needed:**
- Run ELO analysis: `python scripts/run_analysis.py`
- Test ELO performance: `python scripts/test_elo_performance.py`
- Verify data integrity: `python scripts/verify_elo_correctness.py`

## Getting Help

- [MONITORING.md](MONITORING.md) - How the monitoring system works
- [ELO_SYSTEM.md](ELO_SYSTEM.md) - ELO rating system explained
- [SYSTEM_OBSERVER.md](SYSTEM_OBSERVER.md) - AI-powered health monitoring
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions
- [API.md](API.md) - API documentation and data structures

## Upgrading

### Pull Latest Changes

```bash
git pull origin main
```

### Update Dependencies

```bash
pip install -r requirements.txt --upgrade
```

### Database Migrations

Check `scripts/` for migration scripts:

```bash
# Example: Add new columns
python scripts/migrate_add_comprehensive_elo.py
```

### Backup Database

```bash
# Database automatically backs up on schema changes
# Manual backup:
cp data/polymarket_tracker.db data/polymarket_tracker.db.backup_$(date +%Y%m%d)
```

## Security Notes

- **Never commit `.env` file** (already in `.gitignore`)
- **Keep Telegram bot token private**
- **Rotate API keys periodically**
- **Database contains trader addresses** - keep backups secure

## Support

For issues not covered in this guide:
1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review GitHub issues (if repository is public)
3. Check Polymarket documentation: [docs.polymarket.com](https://docs.polymarket.com/)
