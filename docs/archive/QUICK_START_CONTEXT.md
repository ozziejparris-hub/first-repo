# Quick Start Context for New Claude Instances

**Purpose:** Rapid orientation guide for AI assistants helping with this project
**Last Updated:** 2026-01-15
**Read Time:** 5 minutes

---

## What Is This Project?

A **real-time Polymarket prediction market monitoring system** that tracks trader activity, calculates sophisticated ELO ratings, and identifies elite traders using behavioral analysis and machine learning.

**Core Goal:** Help users identify and follow skilled Polymarket traders by analyzing trading behavior, win rates, and market timing.

---

## Current Project State

### ✅ Operational Systems
- **Monitoring**: Tracks 1,957 traders, 997K+ trades, 2,480 resolved markets (15min intervals)
- **ELO System**: 6-dimensional comprehensive scoring with behavioral modifiers
- **Database**: SQLite with 742MB of data, optimized queries
- **Telegram Bot**: Send-only mode for elite trader notifications
- **AI Observer**: Mistral-powered health monitoring

### 🔨 Recent Work (Jan 2026)
- ✅ Behavioral ELO Integration (Kelly criterion, patience metrics)
- ✅ Fixed 3 critical bugs (API resolution, method calls, CSV import)
- ✅ Schema compatibility fixes (timing quality disabled, volume calculated)
- ✅ Performance optimizations (ELO calculation no longer hangs)
- ✅ Repository cleanup and documentation consolidation

### 📊 Key Metrics
- **Correlation**: 0.135 → 0.35-0.50 (2.5x-3.7x improvement expected)
- **Elite Accuracy**: 27.3% → 55-70% (target)
- **Resolved Markets**: 2,480 / 213K total (1.2%)
- **Database Size**: 742 MB

---

## File Structure Overview

```
first-repo/
├── monitoring/          # Core monitoring system (15min intervals)
│   ├── main.py         # Main orchestrator
│   ├── database.py     # SQLite operations
│   ├── telegram_bot.py # Notifications (send-only)
│   └── position_tracker.py # FIFO P&L tracking
│
├── analysis/           # Analysis tools and ELO system
│   ├── unified_elo_system.py      # 6-dimensional ELO engine
│   ├── trading_behavior_analysis.py # Kelly, patience, timing
│   ├── calculate_weighted_metrics.py # Market difficulty
│   ├── trader_performance_analysis.py # ROI, win rates
│   └── README_MASTER.md # Complete analysis guide
│
├── scripts/            # Integration and maintenance scripts
│   ├── integrate_behavioral_elo.py # Main integration orchestrator
│   ├── update_database_from_csvs.py # CSV import utility
│   ├── update_database_schema.py # Schema migration
│   └── simulation/     # Testing and validation
│
├── data/               # SQLite database (not in git)
│   └── polymarket_tracker.db # Main database (742MB)
│
├── docs/               # Core documentation
│   ├── SETUP.md       # Installation guide
│   ├── MONITORING.md  # How monitoring works
│   └── ELO_SYSTEM.md  # ELO methodology
│
├── reports/            # Generated analysis CSVs
├── paper_trading/      # Validation system (ready, not active)
└── archive/            # Historical docs (52 files archived)
```

---

## Key Documentation Files

### For Understanding Project State
1. **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)** (500+ lines) - Comprehensive project overview
2. **[README.md](README.md)** - High-level introduction
3. **[BUGFIX_SUMMARY.md](BUGFIX_SUMMARY.md)** - Recent bug fixes (Jan 2026)
4. **[SCHEMA_FIXES_APPLIED.md](SCHEMA_FIXES_APPLIED.md)** - Schema compatibility fixes

### For Technical Implementation
5. **[analysis/README_MASTER.md](analysis/README_MASTER.md)** - Complete analysis tools guide
6. **[analysis/UNIFIED_ELO_SYSTEM.md](analysis/UNIFIED_ELO_SYSTEM.md)** - ELO technical reference
7. **[docs/SETUP.md](docs/SETUP.md)** - Installation and configuration
8. **[docs/DATABASE_SCHEMA_DOCUMENTATION.md](docs/DATABASE_SCHEMA_DOCUMENTATION.md)** - Database structure

### For Troubleshooting
9. **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** - Common issues
10. **[ALL_FIXES_VERIFIED.md](ALL_FIXES_VERIFIED.md)** - Verification results

---

## Recent Changes (What Just Happened)

### Phase 1-8: Behavioral ELO Integration ✅
**Goal:** Improve correlation from 0.135 to 0.45-0.65

**What Was Done:**
1. Implemented Kelly criterion alignment scoring (position sizing intelligence)
2. Implemented patience metrics (trading frequency discipline)
3. Added market difficulty weighting (volatility + liquidity + activity + clarity)
4. Switched to ROI-based scoring (actual profit margins vs binary win/loss)
5. Added minimum sample filter (50+ resolved trades)
6. Fixed 3 critical bugs + schema compatibility issues
7. Optimized ELO calculation (no more hanging)

**Results:**
- Expected correlation: **0.35-0.50** (revised from 0.45-0.65 due to timing metric disabled)
- Timing quality: **Disabled** (missing `created_at` column in database)
- Kelly + patience: **Working perfectly** ✅
- 2,480 resolved markets found (was 0) ✅
- 50,000+ ELO rating updates (was 0) ✅

---

## Common Tasks

### Running the Full System
```bash
# Start monitoring (15min intervals)
python -m monitoring.main

# In separate terminal: Start AI observer
python scripts/run_system_observer.py
```

### Running Analysis & Integration
```bash
# 1. Generate behavioral analysis
python analysis/trading_behavior_analysis.py  # Choose option 3 (All time)

# 2. Calculate market difficulty
python analysis/calculate_weighted_metrics.py

# 3. Calculate ROI and performance
python analysis/trader_performance_analysis.py  # Choose option 3 (All time)

# 4. Import CSVs to database
python scripts/update_database_from_csvs.py

# 5. Run ELO integration
python scripts/integrate_behavioral_elo.py

# 6. View results
python scripts/view_trader_rankings.py
```

### Validation
```bash
# Run integration tests
python tests/test_behavioral_integration.py

# Verify ELO rankings
python scripts/simulation/verify_elo_rankings.py --verbose
```

---

## Known Issues & Limitations

### ⚠️ Schema Limitations
- **Missing Columns**: `created_at`, `resolved_at` in markets table
- **Impact**: Timing quality metric disabled (neutral 0.5 score for all traders)
- **Workaround**: Calculate volume from trades, use trade activity instead of market age

### ⚠️ Reduced Targets
- **Original**: 0.45-0.65 correlation, 70-75% elite accuracy
- **Revised**: 0.35-0.50 correlation, 55-70% elite accuracy
- **Reason**: Timing metric accounts for ~15-20% of improvement; without it, lower targets

### ✅ What Still Works
- Kelly alignment (40 ELO points) - position sizing intelligence
- Patience score (30 ELO points) - trading frequency discipline
- ROI-based scoring - better than binary win/loss
- Market difficulty - volatility + liquidity + activity + clarity
- Weighted win rate - difficulty-adjusted performance
- Minimum sample filter - 50+ resolved trades

---

## Database Schema Quick Reference

### Main Tables
```sql
-- traders (1,957 rows)
CREATE TABLE traders (
    address TEXT PRIMARY KEY,
    total_trades INTEGER,
    total_volume REAL,
    comprehensive_elo REAL,          -- Final ELO with behavioral modifiers
    kelly_alignment_score REAL,       -- Position sizing intelligence (0-1)
    patience_score REAL,              -- Trading frequency (0-1)
    timing_score REAL,                -- Market timing (disabled - all 0.5)
    weighted_win_rate REAL,           -- Difficulty-adjusted win % (0-100)
    roi_percentage REAL,              -- Return on investment % (-100 to +∞)
    resolved_trades_count INTEGER     -- # resolved trades (need 50+ to rank)
);

-- markets (213,000 rows, 2,480 resolved)
CREATE TABLE markets (
    market_id TEXT PRIMARY KEY,
    resolved INTEGER,                 -- 0 or 1
    winning_outcome TEXT,             -- 'yes' or 'no'
    difficulty_score REAL             -- 0-1 (harder = higher)
);

-- trades (997,399 rows)
CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    trader_address TEXT,
    market_id TEXT,
    side TEXT,                        -- 'buy' or 'sell'
    outcome TEXT,                     -- 'yes' or 'no'
    shares REAL,
    price REAL,
    timestamp TEXT
);

-- positions (FIFO tracking)
CREATE TABLE positions (
    position_id INTEGER PRIMARY KEY,
    trader_address TEXT,
    market_id TEXT,
    outcome TEXT,
    shares REAL,
    avg_price REAL
);
```

---

## API Integration

### Polymarket API
- **Base URL**: `https://clob.polymarket.com`
- **Authentication**: Read-only (no API key needed for public data)
- **Rate Limits**: 0.1s delay between calls
- **Reliability**: ⚠️ Unreliable for resolution data - use database instead

### Telegram Bot
- **Mode**: Send-only (no webhook)
- **Token**: In `.env` file
- **Notifications**: Elite trader alerts (top ELO performers)

---

## Tech Stack

- **Language**: Python 3.10+
- **Database**: SQLite3
- **AI**: Mistral/Ollama (system observer)
- **Libraries**: pandas, numpy, requests, python-telegram-bot
- **Testing**: pytest
- **Version Control**: Git

---

## Development Roadmap

### Immediate (Q1 2026)
1. Extend database schema (add `created_at` column) → Enable timing quality
2. Lower sample filter to 30+ resolved trades (vs 50+) → More qualified traders
3. Validate correlation improvement (run verify_elo_rankings.py)

### Future
4. Activate paper trading validation system
5. Add advanced behavioral metrics (bet sizing patterns, time-of-day)
6. API optimization (caching, rate limits)
7. Multi-model observer (Claude, GPT-4 ensemble)

---

## Quick Context Prompts

### For Bug Fixes
"I'm working on the Polymarket trader tracker. It uses a 6-dimensional ELO system with behavioral analysis (Kelly, patience, timing). We recently fixed 3 critical bugs and schema compatibility issues. The system tracks 1,957 traders with 997K trades. See PROJECT_OVERVIEW.md and BUGFIX_SUMMARY.md for details."

### For Feature Development
"This is a real-time Polymarket monitoring system with ELO ratings. The database has traders, trades, markets, and positions tables. Main monitoring runs every 15 minutes. Analysis scripts generate CSVs that are imported to database. See analysis/README_MASTER.md for tool details."

### For Analysis Questions
"The system calculates trader ELO using 6 dimensions: base ELO (category-specific), behavioral (Kelly + patience + timing), advanced metrics, network analysis, contrarian bonus, and P&L adjustment. Current correlation is 0.135; we're targeting 0.35-0.50 after behavioral integration. See SCHEMA_FIXES_APPLIED.md."

---

## Important Notes

### Don't Modify These While Running
- `data/polymarket_tracker.db` (monitoring writes to it every 15min)
- `.env` (contains Telegram credentials)
- `monitoring/main.py` (core loop)

### Safe to Run Anytime
- All `analysis/*.py` scripts (read-only)
- All `scripts/*.py` scripts (except schema updates)
- Test files in `tests/`

### Before Making Changes
1. Read PROJECT_OVERVIEW.md for current state
2. Check BUGFIX_SUMMARY.md for recent fixes
3. Review relevant tool documentation in analysis/ or docs/
4. Run tests after changes: `python tests/test_behavioral_integration.py`

---

## Success Metrics

### Data Quality
- ✅ 2,480 resolved markets found (not 0)
- ✅ 50,000+ ELO rating updates (not 0)
- ✅ 1,500+ traders with Kelly scores
- ✅ 1,500+ traders with patience scores
- ⚠️ Timing scores neutral (acceptable limitation)

### Performance
- 🎯 Correlation: 0.35-0.50 (target)
- 🎯 Elite accuracy: 55-70% (target)
- ✅ Processing time: 5-15 minutes (was hanging)
- ✅ No more database errors

---

## Questions to Ask Yourself

Before starting work on this project:

1. **Do I understand the current state?** → Read PROJECT_OVERVIEW.md
2. **What was recently changed?** → Read BUGFIX_SUMMARY.md + SCHEMA_FIXES_APPLIED.md
3. **Which system am I working on?** → Monitoring, Analysis, or Integration?
4. **What documentation exists?** → Check docs/ and analysis/ directories
5. **Are there known limitations?** → Check SCHEMA_FIXES_APPLIED.md "What Was Lost" section

---

## Common Mistakes to Avoid

❌ **Don't** query `created_at` or `resolved_at` columns (they don't exist)
❌ **Don't** expect timing quality to work (it's disabled)
❌ **Don't** trust Polymarket API for resolution data (use database)
❌ **Don't** run ELO calculation without optimization (will hang)
❌ **Don't** forget to import CSVs before running integration

✅ **Do** use database as source of truth for resolutions
✅ **Do** calculate volume from trades (`SUM(shares * price)`)
✅ **Do** pre-calculate expensive operations to avoid hanging
✅ **Do** run analysis → CSV export → database import → integration
✅ **Do** validate with tests after making changes

---

**For detailed information on any topic, refer to the [Documentation Index](#key-documentation-files) above.**

**Last Update:** 2026-01-15 (Post behavioral ELO integration and repository cleanup)
