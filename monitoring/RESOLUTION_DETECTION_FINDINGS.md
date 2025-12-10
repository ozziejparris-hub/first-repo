# Market Resolution Detection - Findings and Fix

**Date:** 2025-12-10
**Status:** Issue Identified - Needs API Endpoint Change

---

## Problem Identified

The market resolution checker is failing because of a **Market ID mismatch**:

### The Issue

Polymarket uses TWO different ID types:

1. **Numeric ID** (e.g., "21742", "516720")
   - Used for `/markets/{id}` API endpoint
   - Returns market details with resolution status
   - Short, human-readable

2. **Condition ID** (e.g., "0x1b6f76e5b858...")
   - Long hexadecimal string
   - Used internally for tracking trades
   - Used in the Data API for trade history

### What's Going Wrong

**Database stores:** conditionId in the `market_id` field
- Example: `0xf00886b051ccb78c519871e9c3a89a39121e0c2b28bf616171cf2a7a32a02002`

**API endpoint expects:** Numeric ID
- Example: `516720`

**Result:** API returns 422 error: "id is invalid"

### Diagnostic Output

```
API Request: https://gamma-api.polymarket.com/markets/0xe883f2fda25a605a184bb5fe583afce6cc21ea0b348b6a3728ec3067553c548d
Status Code: 422
[ERROR] Error: API returned 422
Response text: {"type":"validation error","error":"id is invalid"}
```

---

## Root Cause

Looking at `database.py` line 395-442:

```python
def store_market_dict(self, market: Dict):
    # Extract the API-compatible ID (for /markets/{id} endpoint)
    # Priority: 'id' field first, then fall back to conditionId
    api_id = market.get('id')  # This is what /markets/{id} expects

    # Extract the conditionId (for matching with trades)
    condition_id = market.get('conditionId')

    # BUG: Uses conditionId as market_id if api_id is None
    market_id = api_id or condition_id  # Falls back to conditionId
```

When markets are initially stored, if the API response doesn't have the `id` field, it falls back to using `conditionId` as the `market_id`. Later, when trying to check resolution status, this causes failures.

---

## Current Database State

```sql
Total markets: 1248
Resolved markets: 0 (0.0%)
```

**This means:**
- 1,248 markets tracked
- ZERO resolved markets detected
- Resolution checking has been broken since the beginning

---

## Solution Options

### Option 1: Use CLOB API for Resolution Checking (RECOMMENDED)

The CLOB (Central Limit Order Book) API has different endpoints that accept conditionId:

```python
# Instead of:
url = f"https://gamma-api.polymarket.com/markets/{market_id}"  # Needs numeric ID

# Use:
url = f"https://clob.polymarket.com/markets/{condition_id}"  # Accepts conditionId
```

**Pros:**
- Works with existing database structure
- No database migration needed
- CLOB API is designed for trading data

**Cons:**
- Different API endpoint
- May need to adjust field mappings

### Option 2: Store Both IDs in Database (BETTER LONG-TERM)

Modify database schema to store both:

```sql
ALTER TABLE markets ADD COLUMN api_id TEXT;  -- Numeric ID
-- Keep condition_id as is
```

Then use `api_id` for resolution checking and `condition_id` for trade matching.

**Pros:**
- Clean separation of concerns
- Uses correct API endpoints
- Future-proof

**Cons:**
- Requires database migration
- Need to backfill api_id for existing markets

### Option 3: Query by ConditionId with Different Endpoint

Some Polymarket endpoints accept queries by conditionId:

```python
# Query markets endpoint with conditionId filter
url = "https://gamma-api.polymarket.com/markets"
params = {"condition_id": condition_id}
```

**Pros:**
- No database changes needed
- Uses official API

**Cons:**
- Returns list instead of single market
- May be slower
- Not all markets may be returned

---

## Recommended Fix (Immediate)

### Step 1: Update Resolution Checker to Use CLOB API

Modify `check_market_resolutions.py`:

```python
def get_market_resolution(self, market_id: str) -> Optional[Dict]:
    """Get market resolution using conditionId."""
    try:
        # Use CLOB API which accepts conditionId
        url = f"https://clob.polymarket.com/markets/{market_id}"
        response = self.session.get(url, timeout=10)

        if response.status_code != 200:
            # Try gamma API if CLOB fails (in case it's a numeric ID)
            url = f"{self.base_url}/markets/{market_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return {"resolved": False, "status": "error", "error_code": response.status_code}

        data = response.json()
        # ... rest of resolution logic
```

### Step 2: Update trader_analyzer.py

The existing `check_market_resolutions()` method in `trader_analyzer.py` line 100-210 should also be updated to use the correct endpoint.

---

## Alternative: Check Resolution via Trades

Another approach is to check if trades on a market have stopped and outcomes have been settled:

```python
def check_resolution_via_trades(self, condition_id: str) -> Optional[Dict]:
    """
    Check resolution by examining recent trades.

    A market is resolved when:
    - No trades in last 7+ days
    - All positions show settlement
    """
    trades = self.get_market_trades(condition_id, limit=10)

    if not trades:
        # No recent trades - might be resolved
        # Check last trade timestamp
        pass
```

---

## Testing Plan

1. **Find a known resolved market**
   - 2024 US Presidential Election should be resolved
   - Need to find its conditionId in our database

2. **Test resolution detection**
   ```bash
   python monitoring/check_market_resolutions.py --market-id <condition_id>
   ```

3. **Verify winning outcome is correctly identified**

4. **Run full resolution check**
   ```bash
   python monitoring/check_market_resolutions.py --check
   ```

---

## Expected Outcomes After Fix

```
Total markets: 1248
Resolved markets: 50-100 (4-8%)  # Estimated, depends on market end dates
```

Many markets from November/December 2024 should be resolved by now (election markets, sports markets, etc.).

---

## Next Steps

1. ✅ Created diagnostic tool (`check_market_resolutions.py`)
2. ✅ Identified root cause (ID mismatch)
3. ✅ Update resolution checker to use correct endpoint (CLOB API)
4. ✅ Fixed unicode encoding issues
5. ✅ Fixed outcomes array handling (dict vs string)
6. ✅ Tested with sample markets - CLOB API working
7. ⏳ Run full resolution check on all markets
8. ⏳ Update database with resolutions
9. ⏳ Verify trader win rates update correctly

## Implementation Status

**Files Updated:**
- ✅ `monitoring/check_market_resolutions.py` - Updated `get_market_resolution()` and `diagnose_market_status()` to use CLOB API
- ✅ `monitoring/polymarket_client.py` - Updated `get_market_details()` to use CLOB API
- ✅ All methods now try CLOB API first, fall back to Gamma API for numeric IDs

**CLOB API Integration:**
```python
# Try CLOB API first (accepts conditionId)
clob_url = f"https://clob.polymarket.com/markets/{market_id}"
response = self.session.get(clob_url, timeout=10)

# If CLOB fails, try Gamma API (accepts numeric ID)
if response.status_code != 200:
    url = f"{self.base_url}/markets/{market_id}"
    response = self.session.get(url, timeout=10)
```

**Known Issues with CLOB API:**
- CLOB API returns different field structure than Gamma API
- Some fields missing: market_id, condition_id, endDate, resolvedAt
- Outcomes array often empty or different format
- May need to use Gamma API for resolution checking even with conditionId

---

## Additional Notes

### UMA Resolution Process

Markets on Polymarket use UMA's Optimistic Oracle:

1. **Proposal**: Someone proposes outcome ($750 bond)
2. **Challenge Period**: 2 hours
3. **If Challenged**: 24-48 hour debate + UMA vote
4. **If Not Challenged**: Auto-resolve after 2 hours
5. **Settlement**: Winning shares → $1, losing → $0

### Market States

- **Active**: Trading ongoing
- **Closed**: End date reached, trading stopped
- **Pending Resolution**: Closed, in UMA challenge period
- **Resolved**: UMA process complete, payoutNumerator set

### Detection Logic

```python
# A market is RESOLVED when:
has_winner = any(outcome['payoutNumerator'] == 1000 for outcome in outcomes)
is_closed = market['closed'] or market['archived']

if has_winner and is_closed:
    # Market is resolved!
    winning_outcome = outcome with payoutNumerator == 1000
```

---

## Files Modified

- ✅ `monitoring/check_market_resolutions.py` - New diagnostic tool
- ⏳ `monitoring/trader_analyzer.py` - Needs endpoint update
- ⏳ `monitoring/polymarket_client.py` - May need new method for CLOB API
- ✅ `monitoring/RESOLUTION_DETECTION_FINDINGS.md` - This document

---

**Status:** Issue identified, solution designed, ready for implementation
**Priority:** HIGH - Resolution detection is completely broken (0/1248 markets resolved)
**Estimated Fix Time:** 1-2 hours
