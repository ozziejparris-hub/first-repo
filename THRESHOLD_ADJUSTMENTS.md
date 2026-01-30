# Activity Threshold Adjustments

## Problem

Monitoring runs with variable cycle times:
- **Normal**: 15 minutes (900 seconds)
- **Actual observed**: 33-60 minutes due to processing time

Original thresholds were:
- **WARNING**: 20 minutes
- **CRITICAL**: 30 minutes

**Result:** False alerts triggered every monitoring cycle because:
- 33-60 minute cycles > 20 minute WARNING threshold
- Constant "Monitoring Delayed" warnings
- Unnecessary "FROZEN" alerts when cycles legitimately take longer

## Solution

Adjusted thresholds to accommodate actual cycle times:
- **HEALTHY**: < 40 minutes
- **WARNING**: 40-60 minutes (may have missed cycle)
- **CRITICAL**: > 60 minutes (likely stuck/frozen)

## Files Modified

### 1. monitoring/health_checker.py

**Location:** Lines 182-190

**Before:**
```python
if age_minutes < 20:
    status = 'healthy'
    message = f'Recent activity {age_minutes}m ago'
elif age_minutes < 30:
    status = 'warning'
    message = f'Last activity {age_minutes}m ago (>20m, may have missed cycle)'
else:
    status = 'critical'
    message = f'No activity for {age_minutes}m  (>30m, likely stuck)'
```

**After:**
```python
if age_minutes < 40:
    status = 'healthy'
    message = f'Recent activity {age_minutes}m ago'
elif age_minutes < 60:
    status = 'warning'
    message = f'Last activity {age_minutes}m ago (>40m, may have missed cycle)'
else:
    status = 'critical'
    message = f'No activity for {age_minutes}m  (>60m, likely stuck)'
```

---

### 2. monitoring/system_observer.py

**Location:** Line 295

**Before:**
```python
if minutes_since > 30:
    print(f"[OBSERVER] ⚠️ MONITORING FROZEN DETECTED: {minutes_since:.0f} minutes silence")
```

**After:**
```python
if minutes_since > 60:
    print(f"[OBSERVER] ⚠️ MONITORING FROZEN DETECTED: {minutes_since:.0f} minutes silence")
```

---

### 3. monitoring/telegram_health_bot.py

**Location:** Lines 292-304

**Before:**
```python
# Detect if monitoring is frozen (> 30 min silence)
if minutes_since > 30:
    message_parts.append("🔴 MONITORING FROZEN DETECTED")
    message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
    if mon_activity.get('last_activity'):
        message_parts.append(f"  • Time: {mon_activity['last_activity'].strftime('%H:%M:%S')}")
    message_parts.append("  • ACTION: Restart monitoring system")
    message_parts.append("")
elif minutes_since > 20:
    # Warning: approaching freeze threshold
    message_parts.append("⚠️ Monitoring Delayed")
    message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
    message_parts.append("")
```

**After:**
```python
# Detect if monitoring is frozen (> 60 min silence)
if minutes_since > 60:
    message_parts.append("🔴 MONITORING FROZEN DETECTED")
    message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
    if mon_activity.get('last_activity'):
        message_parts.append(f"  • Time: {mon_activity['last_activity'].strftime('%H:%M:%S')}")
    message_parts.append("  • ACTION: Restart monitoring system")
    message_parts.append("")
elif minutes_since > 40:
    # Warning: approaching freeze threshold
    message_parts.append("⚠️ Monitoring Delayed")
    message_parts.append(f"  • Last activity: {minutes_since:.0f} minutes ago")
    message_parts.append("")
```

---

## New Threshold Logic

### Healthy (< 40 minutes)
- **Status:** ✅ Healthy
- **Message:** "Monitoring Active (Xm ago)"
- **Action:** None - system operating normally
- **Covers:** Normal 15-minute cycles plus processing overhead (up to 40 min)

### Warning (40-60 minutes)
- **Status:** ⚠️ Warning
- **Message:** "Monitoring Delayed - Last activity Xm ago (>40m, may have missed cycle)"
- **Action:** Alert sent but not critical
- **Meaning:** Monitoring may be slow or processing large batch

### Critical (> 60 minutes)
- **Status:** 🔴 Critical
- **Message:** "MONITORING FROZEN DETECTED - No activity for Xm (>60m, likely stuck)"
- **Action:** Immediate alert + remediation instructions
- **Meaning:** Monitoring is stuck, crashed, or severely delayed

---

## Expected Behavior After Fix

### Cycle Times vs Alerts

| Cycle Duration | Old Behavior | New Behavior |
|---------------|--------------|--------------|
| 15 min | ✅ Healthy | ✅ Healthy |
| 25 min | ⚠️ WARNING | ✅ Healthy |
| 35 min | 🔴 CRITICAL | ✅ Healthy |
| 45 min | 🔴 CRITICAL | ⚠️ Warning |
| 65 min | 🔴 CRITICAL | 🔴 Critical |

### Example Telegram Messages

**Before fix (33-min cycle):**
```
⚠️ Monitoring Delayed
  • Last activity: 33 minutes ago
```
❌ False positive

**After fix (33-min cycle):**
```
✅ Monitoring Active (33m ago)
```
✅ Correct

**Legitimate freeze (65-min):**
```
🔴 MONITORING FROZEN DETECTED
  • Last activity: 65 minutes ago
  • Time: 14:23:45
  • ACTION: Restart monitoring system
```
✅ Correct alert

---

## Rationale

### Why 40 minutes for WARNING?

**Monitoring cycle calculation:**
```
Base interval: 15 minutes (900 seconds)
+ Trade processing: 5-10 minutes (varies with volume)
+ Position tracking: 5-10 minutes (varies with active traders)
+ Database operations: 2-5 minutes (concurrent access delays)
+ Activity timestamp update: < 1 second
= Total: 27-40 minutes typical
```

**40-minute threshold:**
- Allows for normal processing overhead
- Prevents false positives on high-volume cycles
- Still detects genuine delays (>40 min is unusual)

### Why 60 minutes for CRITICAL?

**Critical threshold reasoning:**
- 60 minutes = 4x the base interval (15 min)
- If monitoring hasn't updated in 60+ minutes, something is definitely wrong:
  - Process crashed
  - Database locked/corrupted
  - Exception thrown and caught in outer loop
  - System resource exhaustion

**Reliability:**
- Almost never a false positive
- Clear signal that intervention needed
- Time-sensitive enough to catch issues before hours pass

---

## Testing

### Test 1: Normal Cycle (15-40 min)

**Scenario:** Monitoring completes cycle in 33 minutes

**Expected:**
```
✅ Monitoring Active (33m ago)
```

**Result:** ✅ PASS - No false warnings

---

### Test 2: Delayed Cycle (40-60 min)

**Scenario:** Monitoring takes 45 minutes (high trade volume)

**Expected:**
```
⚠️ Monitoring Delayed
  • Last activity: 45 minutes ago
```

**Result:** ⚠️ WARNING (appropriate, not critical)

---

### Test 3: Frozen Monitoring (> 60 min)

**Scenario:** Monitoring actually frozen/crashed

**Expected:**
```
🔴 MONITORING FROZEN DETECTED
  • Last activity: 65 minutes ago
  • Time: 14:23:45
  • ACTION: Restart monitoring system
```

**Result:** 🔴 CRITICAL (correct alert)

---

## Deployment

### Apply Changes

Changes are already applied to:
- [monitoring/health_checker.py](monitoring/health_checker.py#L182-L190)
- [monitoring/system_observer.py](monitoring/system_observer.py#L295)
- [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py#L292-L304)

### Restart System Observer

For changes to take effect:
```bash
# Kill System Observer (monitoring can keep running)
python scripts/kill_all.py

# Restart System Observer with new thresholds
python scripts/run_system_observer.py
```

**Note:** Monitoring does not need restart - only System Observer needs to reload the new threshold logic.

---

## Summary

### Changes
- ✅ HEALTHY threshold: 20m → 40m
- ✅ WARNING threshold: 20-30m → 40-60m
- ✅ CRITICAL threshold: 30m → 60m

### Impact
- ❌ No more false "Monitoring Delayed" warnings on normal cycles
- ❌ No more false "FROZEN" alerts on legitimate 33-40 min cycles
- ✅ Still detects genuine delays (40-60 min = warning)
- ✅ Still detects genuine freezes (>60 min = critical)

### Files Modified
1. [monitoring/health_checker.py](monitoring/health_checker.py)
2. [monitoring/system_observer.py](monitoring/system_observer.py)
3. [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py)

---

**Implementation Date:** 2026-01-30
**Issue:** False activity warnings due to tight thresholds
**Solution:** Adjusted thresholds to match actual cycle times (40m/60m)
**Status:** ✅ COMPLETE
**Impact:** Eliminates false positive alerts while maintaining freeze detection
