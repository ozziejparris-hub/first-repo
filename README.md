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

- **[SETUP.md](docs/SETUP.md)** - Complete installation and configuration guide
- **[MONITORING.md](docs/MONITORING.md)** - How the monitoring system works
- **[ELO_SYSTEM.md](docs/ELO_SYSTEM.md)** - ELO rating system explained
- **[SYSTEM_OBSERVER.md](docs/SYSTEM_OBSERVER.md)** - AI-powered health monitoring
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues and solutions
- **[MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)** - Recent reorganization changes (2026-01-03)

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

## Recent Updates (2026-01-03)

- Consolidated 52 markdown files into 7 focused docs
- Moved all scripts to `scripts/` directory
- Archived historical completion notes
- Fixed Telegram bot conflicts (send-only mode)
- Reorganized project structure for clarity

See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for details.

## Support

For help:
1. Check [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
2. Review [SETUP.md](docs/SETUP.md)
3. Check `logs/monitoring.log`

---

**Status:** Active Development
**Last Updated:** 2026-01-03
**Version:** 2.0 (Post-Reorganization)
