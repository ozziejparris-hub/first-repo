# Locked PID File Fix - System Observer Auto-Detection

## Problem

System Observer was getting "Permission denied" when trying to read the monitoring PID file because the file is exclusively locked by the monitoring process.

**Error:**
```
PermissionError: [Errno 13] Permission denied: 'data/.monitoring.pid'
```

**Root Cause:**
- Monitoring process locks `data/.monitoring.pid` exclusively using `msvcrt.locking()`
- Exclusive lock prevents other processes from reading the file (Windows behavior)
- System Observer couldn't auto-detect monitoring PID
- Resulted in "No PID provided" warnings in health alerts

---

## Solution

Made System Observer **resilient to locked PID files** with multi-tier fallback:

### Detection Strategy

1. **Try PID file first** - Attempt to read locked file
2. **Catch permission error** - Handle gracefully if locked
3. **Fall back to process search** - Use `find_monitoring_process()`
4. **Report result** - Clear messaging about detection method

### Code Implementation

**File:** [scripts/run_system_observer.py](scripts/run_system_observer.py#L141-L177)

**New logic:**
```python
if monitoring_pid is None:
    print("[OBSERVER] No PID provided, attempting auto-detection...")

    # Try to read from PID file first (may be locked)
    monitoring_pid_file = Path('data/.monitoring.pid')

    if monitoring_pid_file.exists():
        try:
            # Try to read PID (may fail if exclusively locked)
            with open(monitoring_pid_file, 'r') as f:
                monitoring_pid = int(f.read().strip())
            print(f"[OBSERVER] Read monitoring PID from file: {monitoring_pid}")
        except (PermissionError, OSError):
            # File is locked, fall back to process search
            print(f"[OBSERVER] PID file locked (expected), searching processes...")
            monitoring_pid = find_monitoring_process()
        except (ValueError, FileNotFoundError):
            # Corrupt file, fall back to process search
            print("[OBSERVER] PID file corrupt, searching processes...")
            monitoring_pid = find_monitoring_process()
    else:
        # No PID file, search processes
        print("[OBSERVER] PID file not found, searching processes...")
        monitoring_pid = find_monitoring_process()
```

---

## How It Works

### Scenario 1: File Readable (Unlikely on Windows)
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] Read monitoring PID from file: 44648
```

### Scenario 2: File Locked (Expected on Windows)
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file locked (expected), searching processes...
[OBSERVER] Found monitoring process: PID 44648
```

### Scenario 3: No PID File
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file not found, searching processes...
[OBSERVER] Found monitoring process: PID 44648
```

### Scenario 4: Process Not Found
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file locked (expected), searching processes...
[OBSERVER] Warning: Could not find monitoring process
[OBSERVER] Health checks will be limited

Continue anyway? (y/n):
```

---

## Benefits

### Before Fix

❌ Permission denied error on Windows
❌ System Observer couldn't auto-detect monitoring PID
❌ Health alerts showed "No PID provided" warnings
❌ Process/memory stats unavailable
❌ Confusing error messages

### After Fix

✅ Gracefully handles locked PID files
✅ Auto-detection works on Windows and Unix
✅ Health alerts show correct process stats
✅ Clear messaging about detection method
✅ Multiple fallback strategies

---

## Testing

### Test 1: Normal Startup

```bash
# Terminal 1
python scripts/start_monitoring.py

# Terminal 2
python scripts/run_system_observer.py
```

**Expected output (Terminal 2):**
```
[OK] Acquired singleton lock (PID: 12345)

[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file locked (expected), searching processes...
[OBSERVER] Found monitoring process: PID 44648

======================================================================
  SYSTEM HEALTH OBSERVER
======================================================================
```

**Success criteria:**
- ✅ No permission errors
- ✅ PID detected automatically
- ✅ Clear status messages

### Test 2: Health Alerts

After both systems running, health alerts should show:

```
🔧 System Health Report

Monitoring Process:
├─ Status: Running
├─ PID: 44648
├─ Memory: 145.2 MB
├─ CPU: 0.5%
└─ Uptime: 12.3 minutes
```

**Success criteria:**
- ✅ Shows PID (not "No PID provided")
- ✅ Shows memory/CPU stats
- ✅ No warnings about missing PID

---

## Why Windows Exclusive Locks Block Reads

On Windows, `msvcrt.locking(file, LK_NBLCK, 1)` creates an **exclusive lock** that:
- Prevents other processes from reading the file
- Prevents other processes from writing the file
- Is released when file handle is closed

**Why we can't use shared locks:**
- Windows `msvcrt` module doesn't expose shared lock API
- Alternative: Use `win32file` module (requires `pywin32` dependency)
- Our solution: Graceful fallback to process search

---

## Alternative Approaches Considered

### Option 1: Use Shared Locks (Rejected)
**Approach:** Use `win32file.LockFileEx()` for shared read locks
**Problem:** Requires `pywin32` dependency
**Decision:** Rejected - adds heavy dependency

### Option 2: Separate Read-Only PID File (Rejected)
**Approach:** Write PID to two files - one locked, one readable
**Problem:** Duplicate state, complexity
**Decision:** Rejected - over-engineering

### Option 3: Resilient Fallback (Selected ✅)
**Approach:** Try file read, catch error, fall back to process search
**Benefits:**
- No new dependencies
- Works on all platforms
- Simple, maintainable
- Clear error handling

---

## Process Search Method

When PID file is locked, System Observer uses `find_monitoring_process()`:

```python
def find_monitoring_process() -> Optional[int]:
    """Find the monitoring process PID by searching running processes."""
    try:
        for proc in psutil.process_iter(['pid', 'cmdline']):
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'start_monitoring.py' in cmdline or \
               ('python' in cmdline.lower() and 'monitoring' in cmdline and
                'observer' not in cmdline):
                return proc.info['pid']
    except Exception:
        pass
    return None
```

**Searches for:**
- Processes running `start_monitoring.py`
- Processes with "monitoring" in command line (but not "observer")

**Reliable because:**
- Uses `psutil` (cross-platform)
- Checks actual process command lines
- Excludes System Observer itself

---

## Files Modified

1. [scripts/run_system_observer.py](scripts/run_system_observer.py#L141-L177) - Added resilient PID detection with fallback

---

## Success Criteria

✅ System Observer starts without permission errors
✅ Auto-detection works on Windows and Unix
✅ Health alerts show correct process stats
✅ Clear messaging about detection method
✅ No new dependencies required

---

## Related Documentation

- [PROPER_FIXES_IMPLEMENTED.md](PROPER_FIXES_IMPLEMENTED.md) - Main implementation details
- [QUICK_START.md](QUICK_START.md) - Quick reference guide
- [ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md) - Original root cause analysis

---

**Implementation Date:** 2026-01-30
**Issue:** Permission denied when reading locked PID file
**Solution:** Resilient multi-tier PID detection with fallback
**Status:** ✅ COMPLETE
**Impact:** System Observer now auto-detects monitoring PID on all platforms
