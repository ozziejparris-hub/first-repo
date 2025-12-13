# Monitoring → Unified ELO Integration

**Complete Guide to Automated Comprehensive Trader Ratings**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [How It Works](#how-it-works)
4. [Installation & Setup](#installation--setup)
5. [Usage](#usage)
6. [Utility Scripts](#utility-scripts)
7. [Monitoring & Troubleshooting](#monitoring--troubleshooting)
8. [Performance Tuning](#performance-tuning)
9. [Technical Details](#technical-details)

---

## Overview

### The Problem (Before Integration)

The prediction market tracker had **two separate, disconnected systems**:

1. **Monitoring System** (`monitoring/*.py`)
   - Collected trades from successful traders
   - Tracked market resolutions
   - Evaluated trades as won/lost
   - Calculated win rates
   - ❌ **Did NOT calculate comprehensive trader ratings**

2. **Unified ELO System** (`analysis/unified_elo_system.py`)
   - Sophisticated 6-dimension trader rating system
   - Analyzed trading behavior, calibration, network effects
   - ❌ **Was NEVER called automatically**
   - ❌ **Ratings were stale and manual**

**Result**: Traders had basic win rates but no comprehensive skill ratings.

### The Solution (After Integration)

**Automated, Real-Time, 6-Dimension Trader Evaluation**

Now when markets resolve:
1. Monitoring detects resolution ✅
2. Trades are evaluated (won/lost) ✅
3. Trader statistics updated (win rate) ✅
4. **NEW**: Positions built automatically ✅
5. **NEW**: Comprehensive ELO calculated ✅
6. **NEW**: Ratings stored in database ✅

**Result**: Every trader has a continuously updated comprehensive skill rating.

---

## Architecture

### Two-Tiered Update System

```
┌─────────────────────────────────────────────────────────────┐
│                    MONITORING CYCLE                         │
│                   (Every 15 minutes)                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Check for resolved markets                             │
│  2. Evaluate trades (won/lost)                             │
│  3. Update trader statistics (win rate)                    │
│  4. [NEW] Build positions (FIFO matching)                  │
│  5. [NEW] Quick ELO update (4/6 dimensions)                │
│      - Base category ELO ✓                                 │
│      - Behavioral modifiers (cached) ✓                     │
│      - Advanced metrics (cached) ✓                         │
│      - P&L modifiers (fresh) ✓                             │
│      - Network analysis (skipped for speed) ✗              │
│      - Contrarian analysis (skipped for speed) ✗           │
│  6. [NEW] Store in database                                │
│                                                             │
│  Performance Target: <10 seconds for 50-100 traders        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    DAILY DEEP ANALYSIS                      │
│                    (Scheduled via cron)                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Full ELO Recalculation (6/6 dimensions)                   │
│      - Base category ELO ✓                                 │
│      - Behavioral modifiers (fresh) ✓                      │
│      - Advanced metrics (fresh) ✓                          │
│      - P&L modifiers (fresh) ✓                             │
│      - Network analysis (fresh, expensive) ✓               │
│      - Contrarian analysis (fresh, expensive) ✓            │
│                                                             │
│  Performance Target: <15 minutes for all traders           │
└─────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌──────────────────┐
│   Monitoring     │
│   System         │
│                  │
│  - monitor.py    │
│  - trader_       │
│    analyzer.py   │
└────────┬─────────┘
         │
         │ (market resolutions detected)
         │
         ▼
┌──────────────────┐
│  Trade Evaluator │
│                  │
│  Marks trades as │
│  won/lost        │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐         ┌──────────────────┐
│   ELO Bridge     │◄────────┤  Unified ELO     │
│                  │         │  System          │
│  Orchestrates    │         │                  │
│  integration     │         │  6-dimension     │
└────────┬─────────┘         │  rating engine   │
         │                   └──────────────────┘
         │
         ▼
┌──────────────────┐         ┌──────────────────┐
│  Position        │         │   Database       │
│  Tracker         │────────►│                  │
│                  │         │  Stores ELO      │
│  FIFO matching   │         │  ratings         │
└──────────────────┘         └──────────────────┘
```

---

## How It Works

### Phase 1: Market Resolution (Automatic)

**Trigger**: Market resolves on Polymarket

**Flow**:
```python
# In trader_analyzer.py (monitoring cycle)
newly_resolved = check_market_resolutions()

if newly_resolved > 0:
    # Evaluate trades
    eval_results = evaluator.batch_evaluate_resolved_markets()

    # Update statistics
    stats_calculator.recalculate_all_flagged_traders()

    # [NEW] Update positions and ELO
    affected_traders = db.get_traders_with_recent_evaluated_trades(hours=24)

    elo_bridge = UnifiedELOMonitoringBridge(db)

    # Build positions
    position_results = elo_bridge.update_positions_for_traders(affected_traders)

    # Calculate quick ELO
    elo_results = elo_bridge.quick_elo_update_for_traders(affected_traders)
```

**Output** (in monitoring logs):
```
[POST-RESOLUTION] Updating positions and ELO ratings...
  Found 127 traders with recently evaluated trades
  Position update: 45 closed, 12 created
  ELO update: 127 traders updated (avg: 1587.3)
  Top trader: 0x52483137... (ELO: 1892.5)
```

### Phase 2: Daily Recalculation (Scheduled)

**Trigger**: Cron job (daily at 2 AM)

**Command**:
```bash
python scripts/recalculate_comprehensive_elo.py
```

**What It Does**:
- Recalculates ALL 6 dimensions (including expensive Network + Contrarian)
- Refreshes all caches
- Updates entire database
- Takes 5-15 minutes

---

## Installation & Setup

### Prerequisites

✅ Python 3.8+
✅ Virtual environment activated
✅ All dependencies installed (`pip install -r requirements.txt`)
✅ Database initialized (`data/polymarket_tracker.db`)

### Step 1: Database Migration

```bash
# Run migration to add comprehensive ELO fields
python scripts/migrate_add_comprehensive_elo.py
```

**Expected Output**:
```
======================================================================
  COMPREHENSIVE ELO MIGRATION
======================================================================
Database: data/polymarket_tracker.db
Size: 117,805,056 bytes

Creating backup: data/polymarket_tracker.db.backup_YYYYMMDD_HHMMSS
[OK] Backup created successfully

Adding comprehensive ELO fields...
[OK] Added traders.comprehensive_elo
[OK] Added traders.base_category_elo
[OK] Added traders.elo_last_updated
[OK] Added traders.behavioral_modifier
[OK] Added traders.advanced_modifier
[OK] Added traders.pnl_modifier

[OK] Created index: idx_traders_comprehensive_elo
[OK] Created index: idx_traders_elo_updated

======================================================================
  MIGRATION COMPLETE!
======================================================================
```

### Step 2: Initial ELO Calculation

```bash
# Run full recalculation (will take 5-15 minutes)
python scripts/recalculate_comprehensive_elo.py
```

### Step 3: Verify Integration

```bash
# Check status
python scripts/check_elo_status.py

# Run end-to-end test
python scripts/test_end_to_end_integration.py

# View rankings
python scripts/view_trader_rankings.py
```

### Step 4: Schedule Daily Recalculation

**On Linux/Mac** (crontab):
```bash
# Edit crontab
crontab -e

# Add line (runs at 2 AM daily):
0 2 * * * cd /path/to/first-repo && .venv/bin/python scripts/recalculate_comprehensive_elo.py >> logs/elo_recalc.log 2>&1
```

**On Windows** (Task Scheduler):
1. Open Task Scheduler
2. Create Basic Task
3. Name: "Daily ELO Recalculation"
4. Trigger: Daily at 2:00 AM
5. Action: Start a program
   - Program: `C:\path\to\.venv\Scripts\python.exe`
   - Arguments: `scripts\recalculate_comprehensive_elo.py`
   - Start in: `C:\path\to\first-repo`

---

## Usage

### Viewing Rankings

**Simple view** (top 20):
```bash
python scripts/view_trader_rankings.py
```

**Top 50**:
```bash
python scripts/view_trader_rankings.py --limit 50
```

**Detailed view with modifiers**:
```bash
python scripts/view_trader_rankings.py --detailed
```

**Filter by minimum ELO**:
```bash
python scripts/view_trader_rankings.py --min-elo 1600
```

**Export to CSV**:
```bash
python scripts/view_trader_rankings.py --limit 100 --export rankings.csv
```

### Checking Status

```bash
python scripts/check_elo_status.py
```

**Output**:
```
======================================================================
  ELO INTEGRATION STATUS
======================================================================

[DATABASE SCHEMA]
  [OK] comprehensive_elo
  [OK] base_category_elo
  [OK] elo_last_updated
  [OK] behavioral_modifier
  [OK] advanced_modifier
  [OK] pnl_modifier

[ELO COVERAGE]
  Total flagged traders: 5563
  Traders with ELO: 5563
  Coverage: 100.0%

[RECENT UPDATES]
  Updated in last 24 hours: 127
  Most recent update: 2025-12-13 14:23:45

[ELO STATISTICS]
  Average comprehensive ELO: 1587.3
  Average base ELO: 1523.8
  Average multiplier: 1.042x
  Range: 1234.5 - 1892.5

[OVERALL STATUS]
  [OK] Database schema: OK
  [OK] ELO coverage: 100.0%
  [OK] Recent activity: 127 updates in 24h
```

### Manual Recalculation

```bash
# Full recalculation (6/6 dimensions, 5-15 minutes)
python scripts/recalculate_comprehensive_elo.py
```

---

## Utility Scripts

### 1. `recalculate_comprehensive_elo.py`

**Purpose**: Daily full recalculation with all 6 dimensions

**When to use**:
- Daily (via cron)
- After major data updates
- When you want fresh Network/Contrarian analysis

**Runtime**: 5-15 minutes for ~5000 traders

### 2. `view_trader_rankings.py`

**Purpose**: Display top traders by comprehensive ELO

**Options**:
- `--limit N` - Show top N traders (default: 20)
- `--min-elo X` - Filter by minimum ELO
- `--detailed` - Show modifier breakdown
- `--export FILE` - Export to CSV

**Example Output**:
```
Rank  Address              Comp ELO    Base ELO    Change    Win%    Trades
1     0x52483137...        1892.5      1823.4      +69.1     68.2    156
2     0xf247584e...        1867.3      1789.2      +78.1     72.5    203
3     0x20c16b6c...        1834.7      1801.5      +33.2     65.9    142
```

### 3. `test_end_to_end_integration.py`

**Purpose**: Comprehensive integration test

**What it tests**:
- Bridge initialization
- Position building
- Quick ELO updates
- Database storage
- Rankings retrieval

**Runtime**: 30-60 seconds

### 4. `check_elo_status.py`

**Purpose**: Quick health check

**What it shows**:
- Database schema status
- ELO coverage percentage
- Recent update activity
- ELO statistics (avg, range)

**Runtime**: <1 second

---

## Monitoring & Troubleshooting

### Monitoring Log Messages

**Look for these in monitoring output**:

**Success**:
```
[POST-RESOLUTION] Updating positions and ELO ratings...
  Found 127 traders with recently evaluated trades
  Position update: 45 closed, 12 created
  ELO update: 127 traders updated (avg: 1587.3)
  Top trader: 0x52483137... (ELO: 1892.5)
```

**Warning** (non-fatal):
```
[WARN] ELO update failed (continuing): [error message]
```

This means monitoring continues but ELO wasn't updated. Check logs.

### Common Issues

#### Issue 1: "No traders with ELO"

**Symptom**:
```
[WARN] No traders found with comprehensive ELO
Run: python scripts/recalculate_comprehensive_elo.py
```

**Cause**: Initial recalculation not run yet

**Fix**:
```bash
python scripts/recalculate_comprehensive_elo.py
```

#### Issue 2: "ELO coverage: 0%"

**Symptom**:
```
[WARN] ELO coverage: 0% (run recalculation)
```

**Cause**: Database has schema but no calculated ELO values

**Fix**:
```bash
python scripts/recalculate_comprehensive_elo.py
```

#### Issue 3: "Recent activity: None"

**Symptom**:
```
[WARN] Recent activity: None (monitoring may be offline)
```

**Cause**: No markets have resolved recently, OR monitoring not running

**Fix**:
- Check if monitoring is running
- Check when last market resolved
- Wait for next resolution (automatic)

#### Issue 4: Import Errors

**Symptom**:
```
ModuleNotFoundError: No module named 'unified_elo_system'
```

**Cause**: Python path not set correctly

**Fix**:
Make sure you're running from project root:
```bash
cd /path/to/first-repo
python scripts/recalculate_comprehensive_elo.py
```

---

## Performance Tuning

### Current Performance Targets

| Operation | Target | Typical |
|-----------|--------|---------|
| Quick ELO update (50 traders) | <10s | 5-8s |
| Quick ELO update (100 traders) | <15s | 10-12s |
| Full recalculation (5000 traders) | <15min | 8-12min |
| Position building (100 traders) | <5s | 2-3s |

### Optimization Options

#### 1. Adjust Cache TTL

**File**: `monitoring/elo_bridge.py`

**Current**: 24-hour cache for ELO system

**To increase**:
```python
self._elo_cache_ttl = timedelta(hours=48)  # 48-hour cache
```

**Effect**: Faster quick updates, but modifiers updated less frequently

#### 2. Reduce Full Recalculation Frequency

**Current**: Daily (recommended)

**Alternative**: Weekly
```bash
# Crontab - run at 2 AM every Sunday
0 2 * * 0 cd /path/to/first-repo && python scripts/recalculate_comprehensive_elo.py
```

**Effect**: Less server load, but Network/Contrarian analysis less current

#### 3. Batch Size for Quick Updates

**Current**: All traders with recent evaluations (typically 50-150)

**If too slow**, modify `trader_analyzer.py`:
```python
# Instead of all affected traders
affected_traders = db.get_traders_with_recent_evaluated_trades(hours=24)

# Only top N by trading volume
affected_traders = affected_traders[:50]  # Limit to 50
```

---

## Technical Details

### Database Schema

**New columns in `traders` table**:

```sql
CREATE TABLE traders (
    -- Existing columns
    address TEXT PRIMARY KEY,
    total_trades INTEGER,
    win_rate REAL,
    ...

    -- New comprehensive ELO columns
    comprehensive_elo REAL DEFAULT 1500,        -- Final rating (all 6 dimensions)
    base_category_elo REAL DEFAULT 1500,        -- Base ELO from resolutions
    elo_last_updated TIMESTAMP,                 -- Last update time
    behavioral_modifier REAL DEFAULT 1.0,       -- Consistency/diversity multiplier
    advanced_modifier REAL DEFAULT 1.0,         -- Calibration/risk multiplier
    pnl_modifier REAL DEFAULT 1.0              -- P&L quality multiplier
);

CREATE INDEX idx_traders_comprehensive_elo ON traders(comprehensive_elo DESC);
CREATE INDEX idx_traders_elo_updated ON traders(elo_last_updated DESC);
```

### ELO Calculation Formula

**Comprehensive ELO** = Base ELO × Behavioral × Advanced × P&L × Network × Contrarian

**Quick Mode** (4/6 dimensions):
```python
comprehensive_elo = (
    base_category_elo *
    behavioral_modifier *  # Cached (24h)
    advanced_modifier *     # Cached (24h)
    pnl_modifier           # Fresh calculation
)
# Network and Contrarian skipped for speed
```

**Full Mode** (6/6 dimensions):
```python
comprehensive_elo = (
    base_category_elo *
    behavioral_modifier *   # Fresh calculation
    advanced_modifier *     # Fresh calculation
    network_modifier *      # Fresh calculation (expensive)
    contrarian_modifier *   # Fresh calculation (expensive)
    pnl_modifier           # Fresh calculation
)
```

### Integration Points

**File**: `monitoring/trader_analyzer.py`

**Line**: ~259-299

**Trigger**: After trade evaluation in `check_market_resolutions()`

```python
# After statistics update
if eval_results['total_trades'] > 0:
    stats_calculator.recalculate_all_flagged_traders(verbose=True)

    # [NEW] ELO Integration
    try:
        from .elo_bridge import UnifiedELOMonitoringBridge

        affected_traders = self.db.get_traders_with_recent_evaluated_trades(hours=24)

        if affected_traders:
            elo_bridge = UnifiedELOMonitoringBridge(self.db)

            # Position building
            position_results = elo_bridge.update_positions_for_traders(
                affected_traders, verbose=False
            )

            # Quick ELO update
            elo_results = elo_bridge.quick_elo_update_for_traders(
                affected_traders, verbose=False
            )

            # Log results
            print(f"  ELO update: {elo_results['traders_updated']} traders updated")

    except Exception as e:
        # Non-fatal: monitoring continues
        print(f"  [WARN] ELO update failed (continuing): {e}")
```

---

## API Reference

### Database Methods

```python
# Get traders needing ELO update
traders = db.get_traders_with_recent_evaluated_trades(hours=24)
# Returns: List[str] of trader addresses
```

### ELO Bridge Methods

```python
from monitoring.elo_bridge import UnifiedELOMonitoringBridge

bridge = UnifiedELOMonitoringBridge(db)

# Update positions
results = bridge.update_positions_for_traders(
    trader_addresses=['0x123...', '0x456...'],
    verbose=False
)
# Returns: {
#     'traders_processed': int,
#     'total_positions_created': int,
#     'total_positions_closed': int,
#     'errors': List[str],
#     'duration_seconds': float
# }

# Quick ELO update (4/6 dimensions)
results = bridge.quick_elo_update_for_traders(
    trader_addresses=['0x123...', '0x456...'],
    verbose=False,
    force_refresh=False
)
# Returns: {
#     'traders_updated': int,
#     'traders_failed': int,
#     'avg_elo': float,
#     'top_traders': List[Dict],
#     'errors': List[str],
#     'duration_seconds': float
# }

# Full ELO recalculation (6/6 dimensions)
results = bridge.full_elo_recalculation(
    verbose=True,
    force_refresh=True
)
# Returns: {
#     'traders_updated': int,
#     'traders_failed': int,
#     'avg_elo': float,
#     'top_traders': List[Dict],
#     'errors': List[str],
#     'duration_seconds': float
# }

# Get trader rankings
rankings = bridge.get_trader_ranking(
    limit=100,
    min_elo=1500.0
)
# Returns: List[Dict] with trader data
```

---

## Support

### Quick Links

- **Audit Document**: `docs/MONITORING_ELO_INTEGRATION_AUDIT.md`
- **Design Document**: `docs/MONITORING_ELO_INTEGRATION_DESIGN.md`
- **Test Results**: `docs/PHASE_2_TEST_RESULTS.md`
- **This Guide**: `docs/MONITORING_ELO_INTEGRATION.md`

### Checklist for New Users

1. ✅ Run database migration
2. ✅ Run initial full recalculation
3. ✅ Verify with `check_elo_status.py`
4. ✅ Test with `test_end_to_end_integration.py`
5. ✅ Schedule daily recalculation (cron)
6. ✅ Monitor logs for ELO updates

---

**Last Updated**: 2025-12-13
**Version**: 1.0
**Status**: Production Ready ✅
