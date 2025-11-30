# Resolution Tracking Debug Logging - Added Nov 30, 2025

## Summary
Added comprehensive debug logging to `check_market_resolutions()` to diagnose why 0 markets have been resolved in 10 days.

## Changes Made

### 1. Enhanced `monitoring/trader_analyzer.py` (lines 100-231)

#### Added Verbose Logging:
- **Progress tracking**: Shows which market is being checked (every 10 markets + first 3)
- **Market details**: Displays market ID and title
- **API response inspection**: Shows all keys returned by API for first 3 markets
- **Resolution status**: Logs `closed`, `archived`, `active`, `status`, `resolved` fields
- **Outcomes analysis**: Detailed logging of all outcomes and their `payoutNumerator` values
- **Error handling**: Full stack trace for first 3 API failures

#### Added Statistics Tracking:
```
- Total unresolved markets in DB
- Markets checked via API
- API failures
- No data returned count
- Markets marked as closed/archived
- Markets with outcomes data
- Markets with winning outcome
- Markets updated in database
```

#### Sample Output (Next Resolution Check):
```
======================================================================
[RESOLUTION CHECK] Starting resolution check...
======================================================================
[RESOLUTION CHECK] Found 139 unresolved markets to check

[RESOLUTION] Checking market 1/139: Will Trump win the 2024 election...
[RESOLUTION] Market ID: 0x1234567890abcdef...
[RESOLUTION DEBUG] API returned data with keys: ['id', 'question', 'closed', 'archived', 'outcomes', ...]
[RESOLUTION DEBUG] Market data sample: {
[RESOLUTION DEBUG]   'closed': False
[RESOLUTION DEBUG]   'archived': False
[RESOLUTION DEBUG]   'status': 'active'
[RESOLUTION DEBUG] }
[RESOLUTION DEBUG] Closed: False, Archived: False
[RESOLUTION DEBUG] Market still active (not closed/archived)

[RESOLUTION] Checking market 10/139: ...
...

======================================================================
[RESOLUTION CHECK] Summary:
======================================================================
  Total unresolved markets in DB: 139
  Markets checked via API: 139
  API failures: 0
  No data returned: 0
  Markets marked as closed/archived: 0
  Markets with outcomes data: 0
  Markets with winning outcome: 0
  Markets updated in database: 0
======================================================================
[RESOLUTION] ℹ️  No resolved markets found this check (normal if markets are long-dated)
======================================================================
```

### 2. Enhanced `monitoring/monitor.py` (lines 520-542)

#### Added Pre-Check Logging:
- Shows current cycle number
- Displays total markets in DB
- Displays currently resolved markets count
- Shows result summary after check

#### Sample Output:
```
🎯 Periodic resolution check (cycle #10)...
[MONITOR] Current DB state: 139 total markets, 0 resolved

[Resolution check output here...]

[MONITOR] No new resolutions found (markets are long-dated)
```

## What This Will Show

When the next resolution check runs (~2.5 hours from now), you'll see:

1. **If API is working**: Check "Markets checked via API" vs "API failures"
2. **If data is returned**: Check "No data returned" count
3. **If markets are closed**: Check "Markets marked as closed/archived"
4. **If outcomes exist**: Check "Markets with outcomes data"
5. **If winners are detected**: Check "Markets with winning outcome"

## Diagnosis Guide

### Scenario 1: All markets return no data
```
Markets checked via API: 0
No data returned: 139
```
**Issue**: Market IDs in database don't match API format
**Fix**: Check market ID field name (conditionId vs id vs market_id)

### Scenario 2: API fails for all markets
```
Markets checked via API: 139
API failures: 139
```
**Issue**: API endpoint or authentication problem
**Fix**: Check API endpoint URL and API key

### Scenario 3: Markets closed but no outcomes
```
Markets marked as closed/archived: 5
Markets with outcomes data: 0
```
**Issue**: API not returning outcomes field
**Fix**: Need to use different API endpoint for outcome data

### Scenario 4: Markets have outcomes but no winner
```
Markets with outcomes data: 5
Markets with winning outcome: 0
```
**Issue**: Detection logic not finding payoutNumerator = 1000
**Fix**: Check if API uses different field for winners

### Scenario 5: All markets still active (most likely)
```
Markets marked as closed/archived: 0
```
**Result**: Normal! Geopolitics markets take weeks/months to resolve
**Action**: Wait for markets to close naturally

## Next Steps After Logging Output

1. **Wait for next resolution check** (runs every 10 cycles = ~2.5 hours)
2. **Review the detailed output** in monitoring logs
3. **Identify which scenario matches** from diagnosis guide above
4. **Apply appropriate fix** based on scenario
5. **If all markets are active**: This is normal, continue monitoring

## Testing Immediately (Optional)

You can trigger a resolution check manually without waiting:

```bash
cd monitoring
python -c "
from database import Database
from polymarket_client import PolymarketClient
from trader_analyzer import TraderAnalyzer
import os
from dotenv import load_dotenv

load_dotenv('../.env')
api_key = os.getenv('POLYMARKET_API_KEY')

db = Database()
client = PolymarketClient(api_key)
analyzer = TraderAnalyzer(db, client)

print('Running manual resolution check...')
newly_resolved = analyzer.check_market_resolutions()
print(f'Result: {newly_resolved} markets resolved')
"
```

## Expected Timeline

- **Next automatic check**: 2.5 hours from now (cycle #10, #20, #30, etc.)
- **First debug output**: Will show for first 3 markets + every 10th market
- **Full summary**: Printed after all markets checked

## Files Modified

1. `monitoring/trader_analyzer.py` - Added 90+ lines of debug logging
2. `monitoring/monitor.py` - Added pre-check statistics logging

No functional changes - only diagnostic logging added!
