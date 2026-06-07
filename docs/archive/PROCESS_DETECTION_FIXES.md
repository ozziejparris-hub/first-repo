# Process Detection Fixes - System Observer

## Issues Found and Fixed

### Issue #1: PID Files Committed to Git ❌

**Problem:**
- `data/.monitoring.pid` and `data/.system_observer.pid` were tracked in git
- These are runtime files that should never be committed

**Impact:**
- Could cause permission issues
- Stale PIDs in repository
- Conflicts when switching branches

**Fix:**
```bash
# Remove from git tracking
git rm --cached data/.monitoring.pid data/.system_observer.pid

# Add to .gitignore
echo "data/*.pid" >> .gitignore
```

**Status:** ✅ FIXED
- PID files removed from git
- Added `data/*.pid` to [.gitignore](.gitignore#L44)

---

### Issue #2: Duplicate PID File Reading 🔄

**Problem:**
Two separate code paths trying to read the PID file:
1. `run_system_observer.py` lines 120-145 - Custom PID reading logic
2. `find_monitoring_process()` lines 2010-2031 - PID reading with error handling

**Result:**
- Two permission errors shown to user
- Confusing error messages
- Redundant code

**Example output:**
```
[OBSERVER] PID file locked (expected), searching processes...
[OBSERVER] Error reading PID file: [Errno 13] Permission denied
```

**Fix:**
Removed custom PID reading from `run_system_observer.py`, rely solely on `find_monitoring_process()`

**Before:**
```python
# run_system_observer.py
if monitoring_pid is None:
    # Try to read from PID file first...
    try:
        with open(monitoring_pid_file, 'r') as f:
            monitoring_pid = int(f.read().strip())
    except (PermissionError, OSError):
        # Fall back to find_monitoring_process()
        monitoring_pid = find_monitoring_process()
```

**After:**
```python
# run_system_observer.py
if monitoring_pid is None:
    print("[OBSERVER] No PID provided, attempting auto-detection...")
    # Use find_monitoring_process() which handles PID file reading
    monitoring_pid = find_monitoring_process()
```

**Status:** ✅ FIXED
- Removed duplicate logic from [scripts/run_system_observer.py](scripts/run_system_observer.py#L141-L149)
- Single source of truth: `find_monitoring_process()`

---

### Issue #3: Missing Search Pattern for New Entry Point ❌

**CRITICAL ISSUE**

**Problem:**
`find_monitoring_process()` was searching for old launch methods but not the new `start_monitoring.py`

**Search patterns (OLD):**
```python
patterns = [
    '-m monitoring',           # python -m monitoring (DEPRECATED)
    'monitoring.main',         # python -m monitoring.main
    'main_telegram_safe.py',   # python monitoring/main_telegram_safe.py
    'monitoring.__main__',     # python -m monitoring (module form)
    'monitor.py',              # python monitor.py
]
```

**Missing:** `'start_monitoring.py'` - our NEW standard entry point!

**Impact:**
- System Observer could NOT find monitoring process
- "Could not find monitoring process" warning every time
- Health alerts showed "No PID provided"
- Process/memory stats unavailable

**Fix:**
Added `start_monitoring.py` as the FIRST pattern (highest priority)

**After:**
```python
patterns = [
    'start_monitoring.py',     # python scripts/start_monitoring.py (NEW STANDARD)
    '-m monitoring',           # python -m monitoring (old method)
    'monitoring.main',         # python -m monitoring.main
    'main_telegram_safe.py',   # python monitoring/main_telegram_safe.py
    'monitoring.__main__',     # python -m monitoring (module form)
    'monitor.py',              # python monitor.py
]
```

**Status:** ✅ FIXED
- Updated [monitoring/system_observer.py](monitoring/system_observer.py#L2049-L2056)
- `start_monitoring.py` now first pattern checked

---

### Issue #4: Permission Error Messaging

**Problem:**
When PID file is locked (normal condition), error message was confusing:
```
[OBSERVER] Error reading PID file: [Errno 13] Permission denied
```

**Fix:**
Separate exception handler for `PermissionError` with clearer message:

**Before:**
```python
except (ValueError, IOError) as e:
    print(f"[OBSERVER] Error reading PID file: {e}")
```

**After:**
```python
except PermissionError:
    # File is locked by running monitoring process - this is expected!
    print(f"[OBSERVER] PID file is locked (monitoring is running), using process search...")
except (ValueError, IOError) as e:
    print(f"[OBSERVER] Error reading PID file: {e}")
```

**Status:** ✅ FIXED
- Better error messaging
- Users understand locked file is normal
- Clear indication fallback is happening

---

## How Detection Works Now

### Detection Flow

```
1. User runs: python scripts/run_system_observer.py
2. Observer calls: find_monitoring_process()
3. find_monitoring_process():
   ├─ Try reading data/.monitoring.pid
   │  ├─ File readable → verify PID → return PID
   │  ├─ PermissionError → "PID file locked" → continue to search
   │  └─ Other error → print error → continue to search
   └─ Search running processes:
      ├─ Look for 'start_monitoring.py' in command line
      ├─ Look for '-m monitoring' in command line
      ├─ Look for other patterns
      └─ Return first match (excluding observer itself)
```

### Expected Output (Normal Case)

**When PID file is locked (expected):**
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file is locked (monitoring is running), using process search...
[OBSERVER] Found monitoring process: PID=12345, cmd=python scripts/start_monitoring.py
```

**When PID file is readable:**
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] Found monitoring process via PID file: PID=12345
```

**When monitoring not running:**
```
[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file not found, searching for monitoring process...
[OBSERVER] Warning: Could not find monitoring process
[OBSERVER] Health checks will be limited

Continue anyway? (y/n):
```

---

## Testing Results

### Test 1: Start Both Systems

```bash
# Terminal 1
python scripts/start_monitoring.py

# Terminal 2
python scripts/run_system_observer.py
```

**Expected Output (Terminal 2):**
```
[OK] Acquired singleton lock (PID: 67890)

[OBSERVER] No PID provided, attempting auto-detection...
[OBSERVER] PID file is locked (monitoring is running), using process search...
[OBSERVER] Found monitoring process: PID=12345, cmd=python scripts/start_monitoring.py

======================================================================
  SYSTEM HEALTH OBSERVER
======================================================================
```

**Success Criteria:**
- ✅ Single "attempting auto-detection" message
- ✅ Clear "PID file is locked" message (not an error)
- ✅ Successfully finds monitoring PID
- ✅ No "Could not find" warnings

---

### Test 2: Health Alert Shows Process Stats

After both systems running, health alert should show:

```
🔧 System Health Report

Monitoring Process:
├─ Status: Running
├─ PID: 12345
├─ Memory: 145.2 MB
├─ CPU: 0.5%
└─ Uptime: 12.3 minutes
```

**Success Criteria:**
- ✅ Shows correct PID (12345, not "No PID provided")
- ✅ Shows memory/CPU stats
- ✅ No warnings about missing PID

---

## Files Modified

1. [.gitignore](.gitignore#L44) - Added `data/*.pid`
2. [monitoring/system_observer.py](monitoring/system_observer.py#L2049-L2056) - Added `start_monitoring.py` pattern
3. [monitoring/system_observer.py](monitoring/system_observer.py#L2030-L2033) - Improved PermissionError handling
4. [scripts/run_system_observer.py](scripts/run_system_observer.py#L141-L149) - Removed duplicate PID reading
5. Git: Removed `data/.monitoring.pid` and `data/.system_observer.pid` from tracking

---

## Summary

### Root Causes

1. ❌ PID files committed to git
2. 🔄 Duplicate PID file reading (two code paths)
3. ❌ Missing `start_monitoring.py` in search patterns
4. 📝 Confusing error messages for normal lock condition

### Fixes Applied

1. ✅ Removed PID files from git, added to .gitignore
2. ✅ Single PID detection path via `find_monitoring_process()`
3. ✅ Added `start_monitoring.py` as primary search pattern
4. ✅ Separate PermissionError handling with clear messaging

### Expected Results

- ✅ System Observer finds monitoring PID automatically
- ✅ Works with new `start_monitoring.py` entry point
- ✅ Clear, non-confusing messages
- ✅ Single detection attempt (no duplicates)
- ✅ Health alerts show correct process stats

---

**Implementation Date:** 2026-01-30
**Issues:** Process detection failing, confusing error messages, missing search pattern
**Solution:** Added start_monitoring.py pattern, removed duplicate logic, improved error handling
**Status:** ✅ ALL FIXES COMPLETE
**Impact:** System Observer now reliably detects monitoring process
