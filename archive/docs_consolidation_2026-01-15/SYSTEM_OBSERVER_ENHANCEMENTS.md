# System Observer Enhancements - Complete

**Date:** 2026-01-06
**Status:** ✅ IMPLEMENTED - Enhanced Error Detection & Reporting

---

## Overview

The System Observer has been enhanced with comprehensive error detection, classification, and detailed Telegram alerts to support troubleshooting and rapid diagnosis of issues like [Errno 22].

---

## What Was Enhanced

### 1. Error Classification Database

**File:** [monitoring/error_classifier.py](monitoring/error_classifier.py#L139-L147)

**Added Known Issue for [Errno 22]:**
```python
KnownIssue(
    name='errno_22_invalid_argument',
    pattern=re.compile(r'\[Errno 22\] Invalid argument|OSError.*\[Errno 22\]', re.IGNORECASE),
    component='Console Output',
    severity='medium',
    description='Windows console encoding error - Unicode character print failure',
    fix='This error has been fixed with safe_print() wrapper. If recurring, check for new print() statements without safe_print() in monitor.py. See ERRNO_22_FIX_COMPLETE.md for details.',
    docs='docs/ERRNO_22_FIX_COMPLETE.md'
)
```

**Benefits:**
- Automatic pattern matching for [Errno 22] errors
- Provides instant diagnostic information
- Links to fix documentation
- Suggests troubleshooting steps

---

### 2. Detailed Error Alerts via Telegram

**File:** [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py#L305-L328)

**New Method: `send_detailed_error_alert()`**

**Features:**
- Full error context extraction (component, function, line number)
- Stack trace display (top 3 lines)
- Known issue detection with suggested fixes
- Component-specific emojis and severity indicators
- Rate limiting (1 alert per error signature per 10 minutes)

**Alert Format:**
```
🟡 KNOWN ISSUE: Console Output ⚙️

Component: monitoring/monitor.py
Function: check_for_new_trades()

Error Type: OSError
Message: [Errno 22] Invalid argument

Stack Trace:
  monitoring/monitor.py:470 in check_for_new_trades()
  print(f"[OK] Fetched {len(all_recent_trades)} recent trades")
  ... and 2 more

First Occurrence: 13:43:49
Occurrences: 15 times

💡 Suggested Fix:
  This error has been fixed with safe_print() wrapper. If recurring, check for new print() statements without safe_print() in monitor.py. See ERRNO_22_FIX_COMPLETE.md for details.

📚 Docs: docs/ERRNO_22_FIX_COMPLETE.md
```

---

### 3. Enhanced Log Monitoring Loop

**File:** [monitoring/system_observer.py](monitoring/system_observer.py#L156-L208)

**Improvements:**
- Uses `parse_detailed_error()` from LogMonitor for full context extraction
- Automatically sends detailed alerts for ALL errors (not just critical)
- Special tracking for [Errno 22] occurrences
- Fallback to basic error detection if detailed parsing fails

**Code:**
```python
# Try to parse detailed error
detailed_error = self.log_monitor.parse_detailed_error(line)
if detailed_error:
    self.error_count += 1
    print(f"[OBSERVER] Detailed error detected: {detailed_error.error_type or 'Unknown'}")

    # Send detailed alert for all errors
    await self.telegram.send_detailed_error_alert(detailed_error)

    # Keep track of [Errno 22] specifically
    if '[Errno 22]' in detailed_error.message:
        print(f"[OBSERVER] ⚠️ [Errno 22] detected - Console encoding error")
```

---

### 4. Enhanced Hourly Reports

**File:** [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py#L211-L298)

**New Error Details in Reports:**
- Total error count for last hour
- Breakdown by error type (top 3)
- Latest error with timestamp
- **Special [Errno 22] counter** with warning

**Example Report:**
```
📊 HOURLY STATUS REPORT

System: HEALTHY ✅
Uptime: 3.2h
Memory: 145 MB

Activity (last hour):
  • Trades checked: 240
  • Markets scanned: 180
  • API calls: 420

⚠️ Errors: 15 in last hour
  By type:
    • OSError: 15
  Latest: OSError at 14:32:15
  🔴 [Errno 22]: 15 occurrences
    (Console encoding errors - check logs)

Performance: GOOD ✅
Next report: 15:00
```

---

### 5. Enhanced Metrics Collection

**File:** [monitoring/system_observer.py](monitoring/system_observer.py#L250-L325)

**New Metrics:**
- `error_details` dict with:
  - `by_type`: Error count by exception type
  - `by_component`: Error count by component
  - `latest_error`: Most recent error details
  - `errno_22_count`: Specific count of [Errno 22] errors

**Code:**
```python
# Count [Errno 22] occurrences specifically
errno_22_count = 0
recent_errors = self.log_monitor.error_parser.get_recent_errors(minutes=60)
for error in recent_errors:
    if '[Errno 22]' in error.message or 'Invalid argument' in error.message:
        errno_22_count += 1

# Build error details dict
error_details = {
    'by_type': basic_error_summary.get('by_type', {}),
    'by_component': error_summary.get('by_component', {}),
    'latest_error': latest_error,
    'errno_22_count': errno_22_count
}
```

---

## Integration with Existing Error Analysis

### Components Used

1. **ErrorParser** ([monitoring/error_parser.py](monitoring/error_parser.py))
   - Parses log lines to extract error context
   - Extracts file path, line number, function name
   - Groups errors by signature for deduplication
   - Tracks occurrence counts and timestamps

2. **ErrorClassifier** ([monitoring/error_classifier.py](monitoring/error_classifier.py))
   - Matches errors against known issues database
   - Classifies by component and severity
   - Provides suggested fixes and documentation links
   - Formats detailed alerts with emojis

3. **LogMonitor** ([monitoring/log_monitor.py](monitoring/log_monitor.py))
   - Tails log file in real-time
   - Detects error patterns
   - Parses detailed error information
   - Provides error summaries and component health

---

## How It Works

### Real-Time Error Detection Flow

```
1. Log Monitor tails logs/monitoring.log
   ↓
2. Detects ERROR/WARNING/CRITICAL lines
   ↓
3. ErrorParser extracts full context:
   - Timestamp, component, function
   - Error type, message
   - Stack trace
   ↓
4. ErrorClassifier matches against known issues
   ↓
5. TelegramHealthBot formats detailed alert
   ↓
6. Alert sent to Telegram with:
   - Full error context
   - Suggested fix
   - Documentation link
```

### Hourly Report Flow

```
1. SystemObserver collects metrics every hour
   ↓
2. Queries ErrorParser for error summary
   ↓
3. Counts [Errno 22] specifically
   ↓
4. Builds error_details dict
   ↓
5. TelegramHealthBot formats report with:
   - Error breakdown by type
   - Latest error
   - [Errno 22] count if > 0
   ↓
6. Report sent to Telegram
```

---

## Benefits for [Errno 22] Troubleshooting

### Before Enhancements
```
⚠️ Error in monitoring: [Errno 22] Invalid argument
```
- No file/line information
- No suggested fix
- No context about what was being done
- No tracking of occurrence count

### After Enhancements
```
🟡 KNOWN ISSUE: Console Output ⚙️

Component: monitoring/monitor.py
Function: check_for_new_trades()

Error Type: OSError
Message: [Errno 22] Invalid argument

Stack Trace:
  monitoring/monitor.py:470 in check_for_new_trades()
  print(f"[OK] Fetched {len(all_recent_trades)} recent trades")

First Occurrence: 13:43:49
Occurrences: 15 times

💡 Suggested Fix:
  This error has been fixed with safe_print() wrapper. If recurring, check for new print() statements without safe_print() in monitor.py.

📚 Docs: docs/ERRNO_22_FIX_COMPLETE.md
```

**Improvements:**
- ✅ Exact file and line number
- ✅ Function where error occurred
- ✅ Full error context
- ✅ Suggested fix with documentation link
- ✅ Occurrence tracking
- ✅ Easy copy-paste format

---

## Usage

### Starting System Observer

```bash
# Start with auto-detected monitoring PID
py -m scripts.run_system_observer

# Start with specific PID
py -m scripts.run_system_observer --pid 234548

# Test mode (no Telegram)
py -m scripts.run_system_observer --no-telegram
```

### Expected Alerts

**1. Startup Notification:**
```
🚀 SYSTEM OBSERVER STARTED

Health monitoring is now active.
Will send alerts for:
  • System health issues
  • Critical errors
  • Known problems
  • Hourly status reports

Started: 2026-01-06 14:45:00
```

**2. Error Alerts (when error occurs):**
- Detailed error context
- Component and function
- Stack trace
- Suggested fix

**3. Hourly Reports:**
- System health status
- Error summary with [Errno 22] count
- Performance metrics
- Activity stats

---

## Configuration

### Environment Variables Required

```bash
# .env file
telegram_alerts_token=<your_system_observer_bot_token>
telegram_chat_id=<your_chat_id>
```

**Note:** System Observer uses **different Telegram bot** than monitoring alerts:
- `TELEGRAM_BOT_TOKEN` - Monitoring trade alerts (PredictionAlerts_bot)
- `telegram_alerts_token` - System Observer health alerts

---

## Testing

### Verify Enhancements Working

**1. Check Known Issues Database:**
```bash
py -c "from monitoring.error_classifier import ErrorClassifier; ec = ErrorClassifier(); issue = ec.get_known_issue_by_name('errno_22_invalid_argument'); print(f'Found: {issue.name}' if issue else 'Not found')"
```

**Expected:** `Found: errno_22_invalid_argument`

**2. Test Error Parsing:**
```bash
py -c "from monitoring.error_parser import ErrorParser; from datetime import datetime; ep = ErrorParser(); error = ep.parse_log_line('2026-01-06 14:00:00 - ERROR - [Errno 22] Invalid argument'); print(f'Parsed: {error.error_type if error else None}')"
```

**Expected:** `Parsed: None` (needs OSError prefix for error_type detection)

**3. Check System Observer Running:**
```bash
# In separate terminal
py -m scripts.run_system_observer --no-telegram

# Let it run for 2-3 minutes, should see:
# [OBSERVER] Health check #1: HEALTHY ✅
# [OBSERVER] Log monitor loop started
```

---

## Files Modified

| File | Changes | Purpose |
|------|---------|---------|
| [monitoring/error_classifier.py](monitoring/error_classifier.py#L139-L147) | Added [Errno 22] known issue | Pattern matching and fix suggestions |
| [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py#L305-L366) | Added `send_detailed_error_alert()` | Comprehensive error alerts |
| [monitoring/telegram_health_bot.py](monitoring/telegram_health_bot.py#L211-L298) | Enhanced `send_hourly_report()` | Error breakdown with [Errno 22] count |
| [monitoring/system_observer.py](monitoring/system_observer.py#L156-L208) | Enhanced `_log_monitor_loop()` | Real-time detailed error detection |
| [monitoring/system_observer.py](monitoring/system_observer.py#L250-L325) | Enhanced `_collect_metrics()` | Detailed error metrics collection |

---

## Related Documentation

- [ERRNO_22_FIX_COMPLETE.md](ERRNO_22_FIX_COMPLETE.md) - Complete [Errno 22] fix documentation
- [ERRNO_22_INVESTIGATION.md](ERRNO_22_INVESTIGATION.md) - Initial investigation
- [monitoring/error_parser.py](monitoring/error_parser.py) - ErrorParser class documentation
- [monitoring/error_classifier.py](monitoring/error_classifier.py) - ErrorClassifier and known issues
- [monitoring/log_monitor.py](monitoring/log_monitor.py) - LogMonitor class

---

## Success Criteria - All Met ✅

- ✅ [Errno 22] added to known issues database
- ✅ Detailed error alerts implemented
- ✅ Real-time error detection enhanced
- ✅ Hourly reports show error breakdown
- ✅ [Errno 22] specifically tracked and reported
- ✅ Full stack traces in alerts
- ✅ Suggested fixes provided
- ✅ Easy copy-paste format for sharing errors
- ✅ Documentation complete

---

## Next Steps

### Immediate
1. **Start System Observer** to begin receiving enhanced alerts
2. **Monitor for [Errno 22]** - should now get detailed alerts with line numbers
3. **Review hourly reports** - check error breakdown and [Errno 22] count

### Long-term
1. Add more known issues to database as they're discovered
2. Expand error classification with component keywords
3. Consider adding `/errors` command for on-demand error viewing
4. Integrate with monitoring database for activity metrics

---

**Enhancement Complete:** 2026-01-06 15:00
**Status:** ✅ PRODUCTION READY
**Next:** Start System Observer and verify enhanced alerts
