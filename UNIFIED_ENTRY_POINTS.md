# Unified Entry Points - Standard Way to Run the System

**Date:** 2026-01-27
**Status:** Implemented
**Purpose:** Simplify system startup with ONE standard command

---

## The Problem We Solved

**Before:** Multiple confusing ways to start monitoring:
- ❌ `python monitoring/main.py`
- ❌ `python monitoring/main_telegram_safe.py`
- ❌ `scripts\restart_monitoring_telegram_safe.bat`
- ❌ `scripts\start_everything.bat`

**Issues:**
- System Observer couldn't reliably find monitoring process
- No standard entry point
- Confusion about which command to use

---

## The Solution

**After:** ONE standard way for everything:

```bash
# Start complete system (RECOMMENDED)
scripts\start_everything.bat

# Or manually start components
python -m monitoring              # Standard monitoring entry point
python scripts/run_system_observer.py  # System observer
```

---

## How It Works

### Standard Entry Point: `python -m monitoring`

**File:** [monitoring/__main__.py](monitoring/__main__.py)

When you run `python -m monitoring`, Python looks for `__main__.py` in the monitoring package and executes it.

**What it does:**
1. Loads the telegram-safe main function
2. Starts monitoring in safe mode (no Telegram messages)
3. Writes PID file to `data/.monitoring.pid`
4. Runs position tracking every 15 minutes

**Code:**
```python
#!/usr/bin/env python3
"""
Polymarket Monitoring System - Standard Entry Point

Run with: python -m monitoring
"""

import asyncio
from monitoring.main_telegram_safe import main

if __name__ == '__main__':
    asyncio.run(main())
```

### PID File System

**Purpose:** Let System Observer find the monitoring process reliably

**Location:** `data/.monitoring.pid`

**How it works:**

**1. Monitoring writes PID on startup:**
```python
# In main_telegram_safe.py
pid_file = Path('data/.monitoring.pid')
pid_file.write_text(str(os.getpid()))
print(f"[OK] PID file created: {pid_file} (PID: {os.getpid()})")
```

**2. Monitoring cleans up PID on shutdown:**
```python
# In main_telegram_safe.py (finally block)
if pid_file.exists():
    pid_file.unlink()
    logger.info("PID file cleaned up")
```

**3. Observer reads PID to find monitoring:**
```python
# In system_observer.py
def find_monitoring_process():
    # Try PID file first (fast and reliable)
    pid_file = Path('data/.monitoring.pid')
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        if psutil.pid_exists(pid):
            return pid

    # Fallback: Search for process by command line
    # (looks for patterns like '-m monitoring')
```

**Benefits:**
- ✅ Fast (no process scanning needed)
- ✅ Reliable (exact PID, not guessing)
- ✅ Works with any entry point (main.py, __main__.py, etc.)
- ✅ Self-cleaning (deleted on shutdown)

### Unified Launcher: `start_everything.bat`

**File:** [scripts/start_everything.bat](scripts/start_everything.bat)

**What it does:**
1. Starts monitoring using `python -m monitoring` (standard entry point)
2. Waits 3 seconds for monitoring to initialize
3. Starts System Observer
4. Both run in separate terminal windows

**Updated command:**
```batch
REM Start monitoring in new window (using standard entry point)
echo [1/2] Starting Monitoring System (Telegram-safe, position tracking enabled)...
START "Polymarket Monitoring" cmd /k "cd /d %~dp0\.. && py -m monitoring"
timeout /t 3 /nobreak >nul

REM Start system observer in new window
echo [2/2] Starting System Observer...
START "System Observer + Auto ELO" cmd /k "py scripts/run_system_observer.py"
```

---

## Startup Process

### Step-by-Step

**1. User runs:** `scripts\start_everything.bat`

**2. Terminal 1 opens - Monitoring:**
```
======================================================================
  TELEGRAM-SAFE POLYMARKET MONITORING
  NO Telegram messages from monitoring
  Position tracking: ENABLED
  All notifications via System Observer
======================================================================

[MONITOR] [OK] Running without Telegram (safe mode)
[OK] Telegram-safe mode confirmed - NO messages will be sent
[OK] PID file created: data\.monitoring.pid (PID: 12345)

Starting Polymarket Monitor...
[OK] Initial scan complete. Flagged 27 traders.
[OK] Monitor started successfully

======================================================================
  MONITORING CYCLE #1
  2026-01-27 15:30:00
======================================================================
```

**3. Terminal 2 opens - System Observer (3 seconds later):**
```
[OBSERVER] System Health Observer starting...
[OBSERVER] Found monitoring process via PID file: PID=12345
[OBSERVER] Telegram alerts: enabled
[OBSERVER] Health check interval: 60s
[OBSERVER] Hourly reports: enabled
[OBSERVER] Comprehensive diagnostics: every 6h
[OBSERVER] Auto ELO updates: enabled

[OBSERVER] Health check loop started
[OBSERVER] Log monitor loop started
[OBSERVER] Hourly report loop started
[OBSERVER] ELO update loop started
[OBSERVER] Comprehensive diagnostic loop started
```

**4. Telegram notification (from Observer only):**
```
🚀 SYSTEM OBSERVER STARTED

Health monitoring is now active.
Will send alerts for:
  • System health issues
  • Critical errors
  • Known problems
  • Hourly status reports

Started: 2026-01-27 15:30:15
```

---

## Testing

### Run the Startup Test

```bash
python scripts/test_startup.py
```

**Expected Output:**
```
======================================================================
  STARTUP TEST
======================================================================

[1/4] Testing imports...
   ✅ monitoring package imports

[2/4] Testing monitoring entry point...
   ✅ Monitoring module is callable (python -m monitoring)

[3/4] Checking data directory...
   ✅ data/ directory exists

[4/4] Checking batch files...
   ✅ start_everything.bat exists
   ✅ Uses standard entry point (py -m monitoring)

======================================================================
  TEST COMPLETE
======================================================================

✅ System is ready to start!

To start the complete system, run:
   scripts\start_everything.bat
```

### Manual Testing

**Test 1: Standard entry point works:**
```bash
python -m monitoring
# Should start monitoring without errors
# Press Ctrl+C to stop
```

**Test 2: PID file is created:**
```bash
python -m monitoring &
cat data/.monitoring.pid  # Should show PID
tasklist | findstr <PID>  # Should show python.exe process
```

**Test 3: Observer finds monitoring:**
```bash
# In one terminal:
python -m monitoring

# In another terminal:
python scripts/run_system_observer.py
# Should show: "Found monitoring process via PID file: PID=xxxxx"
```

**Test 4: Complete system:**
```bash
scripts\start_everything.bat
# Should open 2 terminals
# Both should run without errors
# Check Telegram for observer startup message
```

---

## File Structure

### Entry Points

```
monitoring/
├── __main__.py              ← Standard entry (python -m monitoring)
├── main_telegram_safe.py    ← Actual implementation (imported by __main__)
└── monitor.py               ← Core monitoring class

scripts/
├── start_everything.bat     ← Unified launcher (RECOMMENDED)
├── run_system_observer.py   ← Observer entry point
└── test_startup.py          ← Startup verification test

data/
└── .monitoring.pid          ← PID file (created at runtime)
```

### What Each File Does

**[monitoring/__main__.py](monitoring/__main__.py)**
- Entry point for `python -m monitoring`
- Imports and runs `main()` from `main_telegram_safe.py`
- Makes monitoring a proper Python module

**[monitoring/main_telegram_safe.py](monitoring/main_telegram_safe.py)**
- Actual monitoring implementation
- Creates PID file on startup
- Cleans up PID file on shutdown
- Runs in telegram-safe mode (no messages from monitoring)

**[monitoring/monitor.py](monitoring/monitor.py)**
- Core `PolymarketMonitor` class
- Handles None telegram_token gracefully
- All telegram calls protected with `if self.telegram is not None`

**[monitoring/system_observer.py](monitoring/system_observer.py)**
- `find_monitoring_process()` function updated
- Reads PID file first (fast path)
- Falls back to process search if PID file missing
- Patterns updated for `-m monitoring` entry point

**[scripts/start_everything.bat](scripts/start_everything.bat)**
- Uses `py -m monitoring` instead of direct file path
- Standard, reliable entry point
- Opens 2 terminal windows

**[scripts/test_startup.py](scripts/test_startup.py)**
- Verifies system is ready to start
- Tests imports, entry points, directories
- Quick sanity check before running

---

## Migration Guide

### If You Were Using Old Entry Points

**Old command:** `python monitoring/main_telegram_safe.py`
**New command:** `python -m monitoring`

**Old command:** `scripts\restart_monitoring_telegram_safe.bat`
**New command:** `scripts\start_everything.bat`

**Why change?**
- ✅ Standard Python convention (`-m module`)
- ✅ Observer can find process reliably
- ✅ ONE command for everything
- ✅ Cleaner, more professional

### Do Old Commands Still Work?

**Yes, but not recommended:**

```bash
# This still works (but uses old method)
python monitoring/main_telegram_safe.py

# This is better (uses standard entry point)
python -m monitoring
```

**Problem with old method:**
- Observer may not find the process reliably
- No PID file created (depends on implementation)
- Inconsistent with Python standards

---

## Troubleshooting

### Observer Says "Could not find monitoring process"

**Cause 1:** Monitoring not started yet
- **Fix:** Wait 5 seconds after starting monitoring, then start observer

**Cause 2:** PID file missing
- **Fix:** Check `data/.monitoring.pid` exists
- Run: `python -m monitoring` (should create PID file)

**Cause 3:** Stale PID file
- **Fix:** Delete `data/.monitoring.pid` and restart monitoring

### PID File Not Created

**Cause:** Monitoring crashed before creating file
- **Fix:** Check error message in monitoring terminal
- Verify `.env` has `POLYMARKET_API_KEY`

### Two Monitoring Processes Running

**Cause:** Started monitoring twice
- **Fix:**
  ```bash
  taskkill /F /IM python.exe
  # Then start fresh:
  scripts\start_everything.bat
  ```

### "Module not found" Error

**Error:** `ModuleNotFoundError: No module named 'monitoring'`

**Cause:** Not running from project root
- **Fix:**
  ```bash
  cd c:\Users\Oscar\Projects\first-repo
  python -m monitoring
  ```

---

## Benefits Summary

### Before

❌ Multiple confusing entry points
❌ Observer can't find monitoring reliably
❌ No standard way to start system
❌ Manual process detection unreliable
❌ User confusion about which command to use

### After

✅ ONE standard entry point (`python -m monitoring`)
✅ PID file for reliable process detection
✅ Observer finds monitoring instantly
✅ Standard Python conventions
✅ ONE command for complete system (`start_everything.bat`)
✅ Easy to test and verify
✅ Clean, professional architecture

---

## Advanced Usage

### Custom Entry Point (if needed)

If you need to customize startup behavior:

```python
# custom_start.py
import asyncio
from monitoring.main_telegram_safe import main

async def custom_main():
    # Your custom logic here
    print("Custom startup logic")

    # Then run standard main
    await main()

if __name__ == '__main__':
    asyncio.run(custom_main())
```

### Programmatic Startup

Start monitoring from Python code:

```python
import asyncio
import subprocess

# Start monitoring
monitoring_proc = subprocess.Popen(['python', '-m', 'monitoring'])

# Start observer
observer_proc = subprocess.Popen(['python', 'scripts/run_system_observer.py'])

# Wait for both
monitoring_proc.wait()
observer_proc.wait()
```

### Docker/Systemd Integration

For production deployment:

```dockerfile
# Dockerfile
CMD ["python", "-m", "monitoring"]
```

```ini
# systemd service
[Service]
ExecStart=/usr/bin/python3 -m monitoring
WorkingDirectory=/app
```

---

## Files Modified Summary

### Created
- [scripts/test_startup.py](scripts/test_startup.py) - Startup verification test
- [UNIFIED_ENTRY_POINTS.md](UNIFIED_ENTRY_POINTS.md) - This documentation

### Modified
- [monitoring/__main__.py](monitoring/__main__.py) - Updated to use telegram-safe entry point
- [monitoring/main_telegram_safe.py](monitoring/main_telegram_safe.py) - Added PID file creation/cleanup
- [monitoring/system_observer.py](monitoring/system_observer.py) - Updated `find_monitoring_process()` to read PID file
- [scripts/start_everything.bat](scripts/start_everything.bat) - Changed to use `py -m monitoring`

---

## Next Steps

1. **Test the system:**
   ```bash
   python scripts/test_startup.py
   ```

2. **Start the complete system:**
   ```bash
   scripts\start_everything.bat
   ```

3. **Verify in Telegram:**
   - Should receive "🚀 SYSTEM OBSERVER STARTED" message
   - Wait 1 hour for first status report

4. **Check both terminals:**
   - Terminal 1: Monitoring cycles running
   - Terminal 2: Observer health checks running

---

**END OF DOCUMENTATION**

**Remember:** Always use `scripts\start_everything.bat` to start the complete system!
