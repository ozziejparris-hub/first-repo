# Automated ELO Update System

**Date:** 2026-01-26
**Status:** Fully Implemented & Ready
**Purpose:** Eliminate manual commands for ELO updates and analysis

---

## Overview

The System Observer now includes **automated ELO integration** that:
- ✅ Monitors P&L coverage automatically
- ✅ Triggers ELO updates when needed (every 24h or 100+ closed positions)
- ✅ Runs integration pipeline automatically
- ✅ Generates and sends leaderboards to Telegram
- ✅ Provides hourly mini-leaderboards (top 5 traders)

**Result:** You run ONE command and everything happens automatically.

---

## What Was Added

### 1. Auto ELO Update Loop

**File:** [monitoring/system_observer.py](monitoring/system_observer.py)

**New methods:**
- `_elo_update_loop()` - Checks every 10 minutes if update needed
- `_check_elo_update_needed()` - Determines trigger conditions
- `_run_elo_integration()` - Runs integration pipeline
- `_generate_leaderboard()` - Formats top 20 traders
- `_send_elo_update_notification()` - Sends results to Telegram
- `_get_top_traders()` - Gets top traders for hourly reports
- `_get_pnl_stats()` - Gets P&L coverage stats

**Update Triggers:**
```python
# ELO update triggers automatically when:
1. P&L coverage reaches 20%+ (first time)
2. 100+ closed positions available (first time)
3. 24 hours since last update
```

### 2. Enhanced Hourly Reports

**File:** [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py)

**Added to hourly status:**
```
📊 HOURLY STATUS REPORT

System: HEALTHY ✅
Uptime: 3.5h
Memory: 245 MB

Activity (last hour):
  • Trades checked: 15
  • API calls: 42

💰 P&L Coverage:
  • Traders with ROI: 256
  • Closed positions: 1,234

🏆 Top 5 Traders:
1. `0xdeb2f7...` ELO: 4523 ROI: +87.3%
2. `0xa1b2c3...` ELO: 4201 ROI: +65.1%
3. `0x9f8e7d...` ELO: 3987 ROI: +52.8%
4. `0x6c5d4e...` ELO: 3756 ROI: +48.2%
5. `0x3b2a1c...` ELO: 3654 ROI: +41.7%

Performance: GOOD ✅
Next report: 14:00
```

### 3. Full ELO Update Notifications

**When ELO system updates, you receive:**
```
✅ ELO System Updated

📊 Correlation: r = 0.456
⏰ Updated: 13:45

🏆 TOP 20 TRADERS (ELO Rankings)

🥇 `0xdeb2f7...cf1`
   ELO: **4523** | ROI: +87.3% | WR: 68.5%
   Trades: 6,631

🥈 `0xa1b2c3...d4e`
   ELO: **4201** | ROI: +65.1% | WR: 71.2%
   Trades: 4,523

🥉 `0x9f8e7d...c6b`
   ELO: **3987** | ROI: +52.8% | WR: 66.8%
   Trades: 3,987

[... 17 more traders ...]

_Updated: 2026-01-26 13:45_
```

### 4. Unified Launcher

**File:** [scripts/start_everything.bat](scripts/start_everything.bat)

**One command starts everything:**
```batch
scripts\start_everything.bat
```

Opens 2 terminal windows:
1. **Monitoring System** - Tracks trades, updates P&L (every 15 min)
2. **System Observer** - Health checks + Auto ELO (every 10 min check)

### 5. Configuration File

**File:** [config/elo_update_settings.json](config/elo_update_settings.json)

```json
{
  "auto_updates_enabled": true,
  "update_triggers": {
    "min_pnl_coverage": 0.20,
    "min_closed_positions": 100,
    "max_hours_between_updates": 24
  },
  "telegram_notifications": {
    "enabled": true,
    "send_leaderboard": true,
    "leaderboard_top_n": 20,
    "hourly_mini_leaderboard": true,
    "mini_leaderboard_top_n": 5
  }
}
```

---

## How It Works

### Startup (You Run ONE Command)
```bash
scripts\start_everything.bat
```

### Immediate
- Terminal 1 opens: Monitoring system starts
- Terminal 2 opens: System Observer starts
- Telegram: "🚀 SYSTEM OBSERVER STARTED"

### Every 10 Minutes
Observer checks:
```python
# Is ELO update needed?
if (coverage >= 20% and first_time) or
   (24_hours_passed) or
   (100+ closed positions and first_time):

    # Run ELO integration
    run('python scripts/integrate_behavioral_elo.py')

    # Run verification
    run('python scripts/simulation/verify_elo_rankings.py')

    # Generate leaderboard
    leaderboard = generate_top_20()

    # Send to Telegram
    send_notification(correlation, leaderboard)
```

### Every Hour
Observer sends status report:
- System health
- Activity metrics
- P&L coverage
- **Top 5 mini-leaderboard**
- Error summary

### Every 24 Hours (Max)
ELO integration runs automatically:
1. Integrates behavioral ELO
2. Verifies rankings
3. Calculates correlation
4. Generates full top 20 leaderboard
5. Sends to Telegram

---

## What You Experience

### Old Workflow (Before)
```bash
# You had to run manually:
py -m monitoring.main                          # Terminal 1
py scripts/run_system_observer.py              # Terminal 2

# Then check if ELO update needed:
py scripts/test_position_tracker.py
# If needed:
py scripts/integrate_behavioral_elo.py
py scripts/simulation/verify_elo_rankings.py

# Repeat manually every day
```

### New Workflow (Now)
```bash
# You run ONCE:
scripts\start_everything.bat

# Then forget it - everything happens automatically!
```

**Your Telegram Experience:**
- **Every hour:** Status + top 5 traders
- **Every 24h (or when triggered):** Full top 20 leaderboard with correlation
- **Instant alerts:** Errors, health issues
- **Zero manual commands needed**

---

## Files Created/Modified

### Created
- [scripts/start_everything.bat](scripts/start_everything.bat) - Unified launcher
- [config/elo_update_settings.json](config/elo_update_settings.json) - ELO update config
- [AUTO_ELO_SYSTEM.md](AUTO_ELO_SYSTEM.md) - This documentation

### Modified
- [monitoring/system_observer.py](monitoring/system_observer.py) - Added ELO automation
  - `_elo_update_loop()` method (lines ~405-440)
  - `_check_elo_update_needed()` method (lines ~441-502)
  - `_run_elo_integration()` method (lines ~503-568)
  - `_generate_leaderboard()` method (lines ~569-617)
  - `_send_elo_update_notification()` method (lines ~618-635)
  - `_get_top_traders()` helper (lines ~270-302)
  - `_get_pnl_stats()` helper (lines ~303-330)

- [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py) - Enhanced reports
  - Added P&L stats section
  - Added top 5 mini-leaderboard to hourly reports

---

## Testing the System

### Step 1: Start Everything
```bash
scripts\start_everything.bat
```

**Expected:**
- 2 terminal windows open
- Telegram: "🚀 SYSTEM OBSERVER STARTED"

### Step 2: Wait for First Hour
After 1 hour, you'll receive:
```
📊 HOURLY STATUS REPORT
[... system stats ...]
🏆 Top 5 Traders:
[... mini leaderboard if traders have ELO ...]
```

### Step 3: Trigger ELO Update (Optional Manual Test)
If you want to force an ELO update immediately for testing:
```bash
# Temporarily modify _check_elo_update_needed() to return True
# Or wait 24 hours for automatic trigger
```

### Step 4: Verify Auto Updates
Check observer terminal output:
```
[OBSERVER] ELO update loop started
[OBSERVER] ELO update triggered
  - P&L coverage reached 22.5% (first time)

======================================================================
  RUNNING ELO INTEGRATION
======================================================================

[ELO] Integration complete
[ELO] Verification complete
```

Check Telegram:
```
✅ ELO System Updated

📊 Correlation: r = 0.456
⏰ Updated: 13:45

🏆 TOP 20 TRADERS (ELO Rankings)
[... full leaderboard ...]
```

---

## Configuration Options

Edit `config/elo_update_settings.json` to customize:

### Disable Auto Updates
```json
{
  "auto_updates_enabled": false
}
```

### Change Trigger Thresholds
```json
{
  "update_triggers": {
    "min_pnl_coverage": 0.15,        // 15% instead of 20%
    "min_closed_positions": 50,       // 50 instead of 100
    "max_hours_between_updates": 12   // 12h instead of 24h
  }
}
```

### Customize Leaderboards
```json
{
  "telegram_notifications": {
    "leaderboard_top_n": 30,          // Show top 30 instead of 20
    "mini_leaderboard_top_n": 10      // Show top 10 in hourly instead of 5
  }
}
```

---

## Success Criteria

- [x] System Observer has ELO update loop
- [x] Auto-triggers based on P&L coverage, time, or closed positions
- [x] Runs integration pipeline automatically
- [x] Generates leaderboards automatically
- [x] Sends Telegram notifications
- [x] Hourly reports include mini-leaderboard
- [x] Unified launcher script created
- [x] Configuration file with customizable triggers
- [ ] **User starts system and tests** ← ACTION REQUIRED

---

## Next Steps

**Immediate:**
1. Restart monitoring with position tracker fix:
   ```bash
   scripts\restart_monitoring_after_fix.bat
   ```

2. Wait for positions to populate (30 min - 1 hour)

3. Start complete system:
   ```bash
   scripts\start_everything.bat
   ```

**After 1 Hour:**
- Check Telegram for hourly report
- Verify P&L stats show coverage
- Verify top 5 mini-leaderboard appears

**After 24 Hours (or when triggered):**
- Check Telegram for full ELO update notification
- Verify correlation is displayed
- Verify top 20 leaderboard is formatted correctly
- Check that ROI-first rebalancing is reflected in rankings

---

## Troubleshooting

### ELO Update Not Triggering

**Check observer logs:**
```
[OBSERVER] ELO update loop started
# Should see this every 10 minutes if checking
```

**Check P&L coverage:**
```bash
py -c "import sqlite3; conn = sqlite3.connect('data/polymarket_tracker.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM traders WHERE total_trades >= 10'); total = cursor.fetchone()[0]; cursor.execute('SELECT COUNT(*) FROM traders WHERE total_trades >= 10 AND roi_percentage IS NOT NULL'); with_roi = cursor.fetchone()[0]; print(f'Coverage: {with_roi}/{total} = {with_roi/max(1,total)*100:.1f}%'); conn.close()"
```

**Force trigger by lowering threshold:**
Edit `_check_elo_update_needed()` to always return `True` temporarily.

### Leaderboard Shows "No traders with ELO ratings yet"

**Cause:** ELO integration hasn't run yet or failed.

**Solution:**
1. Check observer logs for integration errors
2. Manually run to test:
   ```bash
   py scripts/integrate_behavioral_elo.py
   ```
3. Check if traders have `comprehensive_elo` column populated

### Hourly Report Missing Top 5

**Cause:** No traders with ELO ratings yet.

**Solution:** Wait for first ELO update to complete (triggered automatically within 24h).

---

**STATUS:** System ready for deployment. Run unified launcher and monitor Telegram!

**END OF DOCUMENTATION**
