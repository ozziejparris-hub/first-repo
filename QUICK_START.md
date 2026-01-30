# Quick Start Guide - New Launch Commands

## Starting the System

### Start Monitoring (Required)
```bash
python scripts/start_monitoring.py
```

This starts the main monitoring system with:
- Atomic file locking (prevents duplicates)
- Single process execution
- Automatic PID management

### Start System Observer (Recommended)
```bash
python scripts/run_system_observer.py
```

This starts the health monitoring system with:
- Atomic file locking (prevents duplicates)
- Automatic monitoring PID detection
- Telegram health alerts
- Activity monitoring
- Error detection

**Note:** System Observer automatically detects the monitoring process PID, even when the PID file is locked

---

## Process Management

### Check What's Running
```bash
python scripts/check_processes.py
```

Shows:
- PID file status
- Running processes
- Memory/CPU usage
- Overall system health

### Stop Everything
```bash
python scripts/kill_all.py
```

Stops:
- All monitoring processes
- All observer processes
- Cleans up PID files

---

## Common Workflows

### Fresh Start
```bash
# Stop everything
python scripts/kill_all.py

# Start monitoring
python scripts/start_monitoring.py

# Start observer (in another terminal)
python scripts/run_system_observer.py

# Verify both running
python scripts/check_processes.py
```

### Check Status
```bash
python scripts/check_processes.py
```

### Restart Monitoring Only
```bash
# Kill all first (safest)
python scripts/kill_all.py

# Restart monitoring
python scripts/start_monitoring.py
```

---

## Error Messages

### "Monitoring already running"
**Meaning:** Another monitoring instance is active

**Solution:**
```bash
python scripts/kill_all.py
python scripts/start_monitoring.py
```

### "System Observer already running"
**Meaning:** Another observer instance is active

**Solution:**
```bash
python scripts/kill_all.py
python scripts/run_system_observer.py
```

---

## Important Notes

1. **Use the new commands** - `python scripts/start_monitoring.py` instead of `python -m monitoring`
2. **Check before starting** - Use `check_processes.py` to verify nothing is running
3. **Kill before restart** - Always use `kill_all.py` before restarting
4. **One instance only** - The system prevents duplicates automatically

---

## Deprecated Commands

❌ **Don't use:** `python -m monitoring`
✅ **Use instead:** `python scripts/start_monitoring.py`

**Why:**
- Old method creates launcher stub processes
- New method uses atomic file locking
- New method prevents all duplicate issues

---

## Need Help?

- Check processes: `python scripts/check_processes.py`
- Kill everything: `python scripts/kill_all.py`
- View this guide: `QUICK_START.md`
- Full details: `PROPER_FIXES_IMPLEMENTED.md`
