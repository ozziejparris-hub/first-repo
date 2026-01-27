# Comprehensive System Diagnostics

**Date:** 2026-01-27
**Status:** Fully Implemented
**Purpose:** Deep system health monitoring across all components

---

## Overview

The System Observer has been enhanced with comprehensive diagnostic capabilities that monitor and diagnose issues across:

1. **ELO Calculation Pipeline** - Coverage, correlation, distribution
2. **Analysis Tools** - Script integrity and syntax validation
3. **Database Health** - Integrity, locks, orphaned data
4. **Data Quality** - Freshness, resolution rates, ROI sanity
5. **Performance Monitoring** - Query speed, growth rate, activity levels

### Architecture

```
System Observer
  ├── Health Check Loop (60s) - Basic process monitoring
  ├── Log Monitor Loop - Real-time error detection
  ├── Hourly Report Loop - Regular status updates
  ├── ELO Update Loop (10m) - Auto ELO integration
  └── Comprehensive Diagnostic Loop (6h) - Deep health checks ← NEW
```

---

## Diagnostic Components

### 1. ELO System Diagnostics

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `ELOSystemDiagnostics` class

**Checks:**

#### ELO Coverage
- Traders with ELO ratings vs qualified traders (30+ trades)
- **Expected:** >50% coverage
- **Warning:** 50-80% coverage
- **Critical:** <50% coverage

#### Behavioral Metrics Coverage
- Traders with Kelly alignment, patience, timing scores
- **Expected:** >20% coverage
- **Warning:** 5-20% coverage
- **Critical:** <5% coverage

#### ROI Data Quality
- Traders with valid ROI percentages
- **Expected:** >20% coverage (needed for ELO updates)
- **Warning:** 10-20% coverage
- **Critical:** <1% coverage

#### ELO Distribution Sanity
- Min/max/average ELO values
- **Expected:** Range 500+ points, average 1300-1600
- **Warning:** Unusual average (<1000 or >2000)
- **Critical:** Range <100 points

#### ELO Correlation
- Reads from `.last_elo_verification` file
- **Expected:** r > 0.40
- **Warning:** r = 0.35-0.40
- **Critical:** r < 0.30

**Example Output:**
```python
{
    'status': 'WARNING',
    'issues': [],
    'warnings': ['Moderate ELO coverage: 65.3%'],
    'metrics': {
        'elo_coverage': 0.653,
        'behavioral_coverage': 0.156,
        'roi_coverage': 0.231,
        'traders_with_elo': 245,
        'qualified_traders': 375
    }
}
```

### 2. Analysis Tools Checker

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `check_analysis_tools()` method

**Checks:**

#### Required Scripts
- `analysis/trading_behavior_analysis.py`
- `analysis/calculate_weighted_metrics.py`
- `analysis/trader_performance_analysis.py`
- `scripts/integrate_behavioral_elo.py`
- `scripts/simulation/verify_elo_rankings.py`

#### Validation
- File exists
- Python syntax valid (compiles without errors)
- No import errors (basic check)

**Statuses:**
- `OK` - File exists and compiles
- `MISSING` - File not found
- `SYNTAX_ERROR` - Python syntax error
- `ERROR` - Other compilation error

**Example Output:**
```python
{
    'status': 'HEALTHY',
    'issues': [],
    'tools': [
        {'name': 'Behavioral Analysis', 'status': 'OK'},
        {'name': 'Weighted Metrics', 'status': 'OK'},
        {'name': 'Performance Analysis', 'status': 'OK'},
        {'name': 'ELO Integration', 'status': 'OK'},
        {'name': 'ELO Verification', 'status': 'OK'}
    ]
}
```

### 3. Database Integrity Checker

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `check_database_integrity()` method

**Checks:**

#### Required Tables
- `traders`, `trades`, `markets`, `positions`, `monitoring_status`
- **Critical** if any table missing

#### Data Consistency
- Orphaned trades (trades referencing non-existent traders)
- Orphaned positions (positions referencing non-existent traders)
- **Warning** if orphaned records found

#### Invalid Data
- Traders with NULL/empty addresses
- **Critical** if invalid trader records found

#### Database Size
- Total size in MB
- **Warning** if >10 GB

#### Database Locks
- Attempts immediate transaction
- **Critical** if database is locked

**Example Output:**
```python
{
    'status': 'WARNING',
    'issues': [],
    'warnings': ['1,234 trades reference non-existent traders'],
    'metrics': {
        'db_size_mb': 245.3,
        'db_locked': False,
        'tables_ok': 5
    }
}
```

### 4. Data Quality Checker

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `check_data_quality()` method

**Checks:**

#### Trade Data Freshness
- Time since last trade
- **Warning:** 1-2 hours
- **Critical:** >2 hours (monitoring may be stopped)

#### Market Resolution Rate
- Resolved markets / total markets
- **Expected:** 1-2%
- **Warning:** <0.1%

#### Position Closing Rate
- Closed positions / total positions
- **Expected:** >0.1% (if 100+ positions exist)
- **Critical:** <0.1% with 100+ positions

#### Duplicate Trades
- Same trader, market, outcome, shares, price, timestamp
- **Warning:** >100 duplicates

#### ROI Sanity Checks
- Min/max/average ROI percentages
- **Critical:** ROI < -100% or > 1000%
- **Warning:** Average ROI outside -10% to +20% range

**Example Output:**
```python
{
    'status': 'HEALTHY',
    'issues': [],
    'warnings': [],
    'metrics': {
        'hours_since_last_trade': 0.3,
        'resolution_rate': 0.015,
        'position_close_rate': 0.023
    }
}
```

### 5. Performance Monitor

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `PerformanceMonitor` class

**Tracks:**

#### Query Performance
- Time to execute `SELECT COUNT(*) FROM trades`
- **Issue:** >1 second average

#### Database Growth
- Size increase over 6 hours
- **Issue:** <100 KB growth (database not growing)

#### Activity Levels
- Trades per hour
- Positions updated per hour
- **Issue:** <10 trades/hour after 2 hours of monitoring

**Metrics History:**
- Keeps last 24 hours of metrics
- Analyzes trends over time

**Example Output:**
```python
{
    'timestamp': datetime(2026, 1, 27, 14, 30),
    'query_time_ms': 45.2,
    'db_size_mb': 245.8,
    'trades_per_hour': 127,
    'positions_updated_per_hour': 45
}
```

### 6. Fix Suggestion Engine

**File:** [monitoring/diagnostics.py](monitoring/diagnostics.py) - `FixSuggestionEngine` class

**Purpose:** Provide specific fix commands for detected issues

**Example Mappings:**

| Issue Pattern | Fix Suggestion |
|--------------|---------------|
| "No trades in X hours" | 1. Check if Polymarket API is down<br>2. Restart monitoring if API is up |
| "ROI data CRITICAL" | Wait 24-48h for monitoring to collect P&L data |
| "Low ELO coverage" | Run: `py scripts/integrate_behavioral_elo.py` |
| "Database is LOCKED" | 1. Close DB Browser<br>2. Stop duplicate monitoring processes |
| "reference non-existent" | Run: `py scripts/quick_fixes/clean_orphaned_records.py` |
| "Slow database queries" | 1. Add indexes<br>2. Vacuum database<br>3. Consider WAL mode |

**Method:**
```python
fix = FixSuggestionEngine.get_fix_for_issue(issue)
# Returns specific fix command or suggestion
```

---

## Diagnostic Execution

### Automatic Execution

**Schedule:**
- First diagnostic: 1 hour after observer startup
- Subsequent diagnostics: Every 6 hours

**Triggered by:**
- `_comprehensive_diagnostic_loop()` in System Observer

**Process:**
1. Run all diagnostic checks
2. Compile overall status (HEALTHY/WARNING/CRITICAL)
3. Send Telegram report
4. If CRITICAL: Send additional alert
5. Collect performance metrics
6. Detect performance issues

### Manual Execution

Run diagnostics programmatically:

```python
from monitoring.diagnostics import ELOSystemDiagnostics

# Initialize
diagnostics = ELOSystemDiagnostics('data/polymarket_tracker.db')

# Run full diagnostic
report = diagnostics.run_full_diagnostic()

print(f"Status: {report['overall_status']}")
print(f"Issues: {len(report['issues'])}")
print(f"Warnings: {len(report['warnings'])}")
```

---

## Telegram Reports

### Healthy System

```
✅ SYSTEM DIAGNOSTIC REPORT

Overall Status: HEALTHY
Time: 2026-01-27 18:00

📊 Component Health:
✅ Elo System
✅ Analysis Tools
✅ Database
✅ Data Quality

📈 Key Metrics:
  • ELO coverage: 85.3%
  • ROI coverage: 42.1%
  • DB size: 245 MB
  • Last trade: 0.2h ago
```

### System with Warnings

```
⚠️ SYSTEM DIAGNOSTIC REPORT

Overall Status: WARNING
Time: 2026-01-27 20:15

⚠️ WARNINGS (3):
  • [ELO_SYSTEM] Moderate ELO coverage: 65.3%
  • [DATABASE] 1,234 trades reference non-existent traders
  • [DATA_QUALITY] Low market resolution: 0.8%

📊 Component Health:
⚠️ Elo System
✅ Analysis Tools
⚠️ Database
⚠️ Data Quality

📈 Key Metrics:
  • ELO coverage: 65.3%
  • ROI coverage: 18.5%
  • DB size: 312 MB
  • Last trade: 0.5h ago
```

### Critical Issues Detected

```
🚨 SYSTEM DIAGNOSTIC REPORT

Overall Status: CRITICAL
Time: 2026-01-27 22:45

🚨 CRITICAL ISSUES (2):
  • [DATA_QUALITY] No trades in 3.5 hours (monitoring may be stopped)
  • [ELO_SYSTEM] ROI data CRITICAL: 0.2% coverage (need 20%+)

⚠️ WARNINGS (1):
  • [DATABASE] Database very large: 10,245 MB

📊 Component Health:
🚨 Elo System
✅ Analysis Tools
⚠️ Database
🚨 Data Quality

📈 Key Metrics:
  • ELO coverage: 45.2%
  • ROI coverage: 0.2%
  • DB size: 10,245 MB
  • Last trade: 3.5h ago

🔧 FIX RECOMMENDATIONS:

Issue 1: No trades in 3.5 hours (monitoring may be stopped)
Fix: 1. Check if Polymarket API is down
     2. Restart monitoring if API is up

Issue 2: ROI data CRITICAL: 0.2% coverage (need 20%+)
Fix: Wait 24-48h for monitoring to collect P&L data

Issue 3: Database very large: 10,245 MB
Fix: No specific fix available - investigate manually

_Copy/paste these commands to fix issues_
```

**Additional Alert:**
```
🚨 CRITICAL SYSTEM ISSUES DETECTED

Check diagnostic report above for details and fixes!
```

---

## Quick Fix Scripts

Located in [scripts/quick_fixes/](scripts/quick_fixes/)

### 1. Clean Orphaned Records

**Script:** [clean_orphaned_records.py](scripts/quick_fixes/clean_orphaned_records.py)

**Usage:**
```bash
python scripts/quick_fixes/clean_orphaned_records.py
```

**What it does:**
- Deletes trades without corresponding traders
- Deletes positions without corresponding traders
- Reports number of records cleaned

**Safe:** Yes, only removes invalid data

### 2. Vacuum Database

**Script:** [vacuum_database.py](scripts/quick_fixes/vacuum_database.py)

**Usage:**
```bash
python scripts/quick_fixes/vacuum_database.py
```

**What it does:**
- Reclaims unused space
- Defragments database
- Runs ANALYZE for query optimization
- Reports space saved

**Safe:** Yes, but close other DB connections first

**Duration:** 2-10 minutes for large databases

### 3. Rebuild Indexes

**Script:** [rebuild_indexes.py](scripts/quick_fixes/rebuild_indexes.py)

**Usage:**
```bash
python scripts/quick_fixes/rebuild_indexes.py
```

**What it does:**
- Reindexes all tables
- Improves query performance
- Reports progress

**Safe:** Yes

---

## Integration with System Observer

### Initialization

The diagnostic engine is initialized in [monitoring/system_observer.py](monitoring/system_observer.py):

```python
# Initialize diagnostic engines
self.diagnostics = ELOSystemDiagnostics(db_path=self.db_path)
self.performance_monitor = PerformanceMonitor(db_path=self.db_path)
self.fix_engine = FixSuggestionEngine()
```

### Background Task

Diagnostic loop runs as a background task:

```python
tasks = [
    asyncio.create_task(self._health_check_loop()),
    asyncio.create_task(self._log_monitor_loop()),
    asyncio.create_task(self._hourly_report_loop()),
    asyncio.create_task(self._elo_update_loop()),
    asyncio.create_task(self._comprehensive_diagnostic_loop())  # NEW
]
```

### Startup Output

```
[OBSERVER] System Health Observer starting...
[OBSERVER] Monitoring PID: 12345
[OBSERVER] Telegram alerts: enabled
[OBSERVER] Health check interval: 60s
[OBSERVER] Hourly reports: enabled
[OBSERVER] Comprehensive diagnostics: every 6h  ← NEW
[OBSERVER] Auto ELO updates: enabled

[OBSERVER] Health check loop started
[OBSERVER] Log monitor loop started
[OBSERVER] Hourly report loop started
[OBSERVER] ELO update loop started
[OBSERVER] Comprehensive diagnostic loop started  ← NEW
```

---

## Benefits

### 1. Proactive Issue Detection
- Catches problems before they cause failures
- Identifies data quality issues early
- Detects performance degradation

### 2. Specific Fix Guidance
- Exact commands to run
- Clear explanations of issues
- Links to quick-fix scripts

### 3. Comprehensive Coverage
- ELO system health
- Database integrity
- Data quality
- Performance monitoring
- Tool availability

### 4. Automated Reporting
- No manual checks needed
- Telegram notifications with full context
- Critical issues highlighted

### 5. Historical Tracking
- Performance metrics over time
- Trend analysis
- Early warning for degradation

---

## Maintenance Schedule

### Automatic (by Observer)
- **Every 6 hours:** Full diagnostic
- **Every hour:** Basic health + activity check
- **Every 10 minutes:** ELO update check

### Manual (as needed)
- **When prompted:** Run quick-fix scripts
- **Monthly:** Review diagnostic reports
- **Quarterly:** Check performance trends

---

## Troubleshooting

### Diagnostic Reports Not Received

**Check:**
1. Observer is running: `tasklist | findstr python`
2. Telegram credentials in `.env`
3. Observer logs for errors

**Fix:**
- Restart observer: `py scripts/run_system_observer.py`

### False Positive Issues

**Example:** "No trades in 2.5 hours" but monitoring is running

**Cause:** Polymarket API may have no new activity

**Action:** Wait for next hour, check if pattern continues

### Critical Issues Persist

**Example:** ROI data remains at 0.2% after 48 hours

**Check:**
1. Position tracking is enabled
2. Markets are resolving
3. Monitoring logs show P&L updates

**Fix:**
- Run position tracker test: `py scripts/test_position_tracker.py`
- Check monitoring logs: `logs/monitoring.log`

---

## Advanced Usage

### Custom Diagnostic Schedule

Modify diagnostic interval in [system_observer.py](monitoring/system_observer.py):

```python
# Change from 6 hours to 3 hours
if hours_since >= 3:  # Was: 6
    should_run = True
```

### Add Custom Checks

Extend `ELOSystemDiagnostics` class:

```python
def check_custom_metric(self) -> Dict:
    """Add your custom health check."""
    issues = []

    # Your check logic here

    return {
        'status': 'HEALTHY',
        'issues': issues,
        'metrics': {...}
    }

# Add to run_full_diagnostic()
results['custom'] = self.check_custom_metric()
```

### Filter Telegram Reports

Only send critical issues:

```python
# In _send_diagnostic_report()
if report['overall_status'] != 'CRITICAL':
    return  # Skip sending if not critical
```

---

## Files Modified/Created

### Created Files
1. [monitoring/diagnostics.py](monitoring/diagnostics.py) - Diagnostic engine classes
2. [scripts/quick_fixes/clean_orphaned_records.py](scripts/quick_fixes/clean_orphaned_records.py)
3. [scripts/quick_fixes/vacuum_database.py](scripts/quick_fixes/vacuum_database.py)
4. [scripts/quick_fixes/rebuild_indexes.py](scripts/quick_fixes/rebuild_indexes.py)
5. [scripts/quick_fixes/README.md](scripts/quick_fixes/README.md)
6. [COMPREHENSIVE_DIAGNOSTICS.md](COMPREHENSIVE_DIAGNOSTICS.md) - This documentation

### Modified Files
1. [monitoring/system_observer.py](monitoring/system_observer.py)
   - Added diagnostic engine imports (line 30)
   - Added diagnostic components to `__init__` (line 77-80)
   - Added `_comprehensive_diagnostic_loop()` method (line 816-872)
   - Added `_send_diagnostic_report()` method (line 874-940)
   - Added diagnostic task to background tasks (line 121)
   - Updated startup messages (line 108-109)

---

## Next Steps

1. **Run System Observer** with new diagnostics:
   ```bash
   py scripts/run_system_observer.py
   ```

2. **Wait for first diagnostic** (1 hour after startup)

3. **Review Telegram report** to see system health

4. **Address any issues** using provided fix commands

5. **Monitor trends** over multiple diagnostic cycles

---

## Success Criteria

- [x] ELO system diagnostics implemented
- [x] Analysis tools checker implemented
- [x] Database integrity checker implemented
- [x] Data quality checker implemented
- [x] Performance monitoring implemented
- [x] Fix suggestion engine implemented
- [x] Integrated into System Observer
- [x] Quick-fix scripts created
- [x] Documentation complete
- [ ] **User receives first diagnostic report** ← VALIDATION REQUIRED
- [ ] **User runs a quick-fix script** ← VALIDATION REQUIRED

---

**END OF DOCUMENTATION**

**Next Step:** Restart System Observer to enable comprehensive diagnostics, then wait 1 hour for first report.
