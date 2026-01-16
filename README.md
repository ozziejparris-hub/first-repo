# Polymarket Trader Tracker

Real-time monitoring and ELO rating system for successful traders on Polymarket prediction markets.

## Features

- **Real-time Trader Monitoring** - Track successful trader activity every 15 minutes
- **6-Dimension ELO Rating System** - Comprehensive trader skill evaluation
- **AI-Powered System Observer** - Intelligent health monitoring with Mistral/Ollama
- **Telegram Notifications** - Instant alerts for elite trader activity
- **P&L Tracking** - FIFO position tracking and profit/loss analysis
- **Advanced Analytics** - Calibration, behavioral patterns, network effects

## Quick Start

### 1. Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID
```

### 2. Setup Telegram Bot

```bash
# Get your Telegram chat ID
python scripts/get_telegram_chat_id.py
```

Add to `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 3. Start Monitoring

**Windows:**
```bash
run_tracker.bat
```

**Linux/Mac:**
```bash
python -m monitoring.main
```

## Documentation

### Quick Reference
- 👉 **[QUICK_START_CONTEXT.md](QUICK_START_CONTEXT.md)** - 5-minute orientation for new developers
- 📖 **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** - Comprehensive project overview (500+ lines)

### Setup & Operation
- **[SETUP.md](docs/SETUP.md)** - Complete installation and configuration guide
- **[MONITORING.md](docs/MONITORING.md)** - How the monitoring system works
- **[ELO_SYSTEM.md](docs/ELO_SYSTEM.md)** - ELO rating system explained
- **[SYSTEM_OBSERVER.md](docs/SYSTEM_OBSERVER.md)** - AI-powered health monitoring
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues and solutions

### Recent Changes
- **[BUGFIX_SUMMARY.md](BUGFIX_SUMMARY.md)** - 3 critical bugs fixed (Jan 2026)
- **[SCHEMA_FIXES_APPLIED.md](SCHEMA_FIXES_APPLIED.md)** - Schema compatibility fixes
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Project reorganization (2026-01-03)

## Common Commands

```bash
# Start monitoring
python -m monitoring.main

# View top traders
python scripts/view_trader_rankings.py

# Recalculate ELO ratings
python scripts/recalculate_comprehensive_elo.py

# Start observer
python scripts/run_system_observer.py
```

## Project Structure

```
first-repo/
├── monitoring/       # Core monitoring system
├── analysis/         # ELO & analytics
├── scripts/          # Utility scripts
├── docs/             # Documentation
├── data/             # Database files
├── reports/          # Generated reports
└── archive/          # Historical docs
```

## Recent Updates

### 2026-01-15/16: Behavioral ELO Integration & Complete Optimization Series
- ✅ **5 Permanent Optimizations Applied:** Sample filter, ROI calibration, timing quality, difficulty caching, adaptive weights
- ✅ Implemented behavioral ELO modifiers (Kelly criterion + patience + timing quality)
- ✅ **Fixed 7 critical bugs:** API resolution, method calls, CSV import, emoji encoding, Telegram rate limit infinite loop
- ✅ Schema compatibility fixes (timing uses relative entry positions - no migration needed)
- ✅ Performance optimizations (market difficulty caching - 5x faster, 18x at scale)
- ✅ Future-proofing (adaptive weights auto-scale when new dimensions added)
- ✅ **Monitoring system fix:** Added retry limits (max 3 attempts) and 30-min cooldown to prevent rate limit freezes
- ✅ Repository cleanup (consolidated 17 docs, created 9 comprehensive guides)
- ✅ **Correlation improvement: 0.135 → 0.345 (2.6x improvement, target achieved)**
- ✅ **Coverage: 98.8% of traders with all 3 behavioral dimensions**
- ✅ **Performance: Integration 8% faster (10m20s → 9m32s), 18x at 213K scale**
- ✅ **Zero maintenance required - all permanent enhancements**
- ✅ **Expected final correlation: 0.39-0.44 when monitoring populates P&L**

See [COMPLETE_OPTIMIZATION_SERIES.md](COMPLETE_OPTIMIZATION_SERIES.md) for optimizations overview, [TELEGRAM_RATE_LIMIT_FIX.md](TELEGRAM_RATE_LIMIT_FIX.md) for monitoring fix, or individual docs: [BUGFIX_SUMMARY.md](BUGFIX_SUMMARY.md), [OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md), [TIMING_QUALITY_ENHANCEMENT.md](TIMING_QUALITY_ENHANCEMENT.md), [PERFORMANCE_OPTIMIZATION.md](PERFORMANCE_OPTIMIZATION.md), [ADAPTIVE_WEIGHT_SYSTEM.md](ADAPTIVE_WEIGHT_SYSTEM.md), and [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).

### 2026-01-03: Project Reorganization
- Consolidated 52 markdown files into 7 focused docs
- Moved all scripts to `scripts/` directory
- Fixed Telegram bot conflicts (send-only mode)

See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for details.

## Support

For help:
1. Check [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
2. Review [SETUP.md](docs/SETUP.md)
3. Check `logs/monitoring.log`

---

**Status:** Production-Ready with Active Development
**Last Updated:** 2026-01-15
**Version:** 2.1 (Behavioral ELO Integration)
