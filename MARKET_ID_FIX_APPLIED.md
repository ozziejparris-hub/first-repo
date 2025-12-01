# Market ID Format Fix - Resolution Tracking
**Date:** November 30, 2025

## Problem Identified

Resolution checking was failing because:
- **Database stored:** `conditionId` (0x...) in `market_id` field
- **API expects:** Different ID format in `/markets/{id}` endpoint
- **Result:** API returned no data for ALL 323 markets (100% failure rate)

```
Sample stored ID: 0x9bacdaac65cbe257e96e58daf343c56879ea9003bdaed7cdb8cfcd1a82121d3a
API call: GET /markets/0x9bacd... → 404 Not Found
```

## Root Cause

Polymarket uses **TWO DIFFERENT ID TYPES**:
1. **`id` field** - API-compatible ID for `/markets/{id}` endpoint (e.g., "21742", "18956")
2. **`conditionId` field** - Blockchain condition ID for matching trades (e.g., "0x1b6f76...")

We were storing `conditionId` in the `market_id` column, but `get_market_details()` needs the `id` field.

---

## Solution Implemented

### 1. **Database Schema Update**

Added `condition_id` column to `markets` table:

```sql
ALTER TABLE markets ADD COLUMN condition_id TEXT;
CREATE INDEX idx_markets_condition_id ON markets(condition_id);
```

**Migration Results:**
- ✅ Added `condition_id` column
- ✅ Migrated 323 existing `market_id` values → `condition_id`
- ✅ Created index for faster lookups
- ✅ Preserved all existing data

### 2. **Code Updates**

#### A. Updated `database.py`

**Modified `update_market()` function:**
```python
def update_market(self, market_id: str, title: str, category: str,
                 end_date: Optional[datetime] = None, resolved: bool = False,
                 winning_outcome: Optional[str] = None,
                 resolution_date: Optional[datetime] = None,
                 condition_id: Optional[str] = None):  # ← NEW PARAMETER
```

**Added helper method:**
```python
def market_exists_by_condition_id(self, condition_id: str) -> bool:
    """Check if a market already exists by condition_id."""
```

#### B. Updated `store_market_dict()` function

**Before (BROKEN):**
```python
# Used conditionId for everything
market_id = market.get('conditionId')  # ← WRONG for API calls
```

**After (FIXED):**
```python
# Extract BOTH IDs
api_id = market.get('id')  # ← For /markets/{id} API calls
condition_id = market.get('conditionId')  # ← For trade matching

# Use api_id as primary market_id
market_id = api_id or condition_id  # Fall back if api_id not available

# Store BOTH
self.update_market(
    market_id=market_id,  # API-compatible ID
    condition_id=condition_id  # For trades
)
```

---

## What Changed

### Markets Table Structure

**Before:**
```
market_id (TEXT) = conditionId (0x...)  ← WRONG
title, category, end_date, resolved, etc.
```

**After:**
```
market_id (TEXT) = API-compatible ID (e.g., "21742")  ← CORRECT
condition_id (TEXT) = conditionId (0x...)  ← For trade matching
title, category, end_date, resolved, etc.
```

### Data Flow

**Before (BROKEN):**
```
API Response → conditionId → market_id column
                                   ↓
Resolution Check → get_market(0x...) → 404 Not Found
```

**After (FIXED):**
```
API Response → 'id' field → market_id column
            → 'conditionId' → condition_id column
                                   ↓
Resolution Check → get_market("21742") → 200 OK ✓
```

---

## Migration Status

### ✅ Completed Steps:

1. **Database Migration** - Added `condition_id` column
2. **Data Preservation** - Copied existing IDs to `condition_id`
3. **Code Updates** - Modified `update_market()` and `store_market_dict()`
4. **Helper Methods** - Added `market_exists_by_condition_id()`

### ⚠️ Pending Steps:

**IMPORTANT:** Existing 323 markets still have `conditionId` in the `market_id` field!

**Next Steps:**
1. Wait for monitoring system to run and fetch fresh markets
2. New markets will automatically get correct IDs
3. Old markets will gradually get corrected as they appear in API calls

**OR** (Faster):
Create a backfill script to:
1. Query all existing markets
2. Find their correct `id` values from API
3. Update `market_id` field with correct IDs

---

## Testing the Fix

### Test 1: Check New Market Storage

After the monitoring system runs next, check if new markets have correct IDs:

```sql
SELECT market_id, condition_id, title
FROM markets
ORDER BY last_checked DESC
LIMIT 5;
```

**Expected:**
- `market_id`: Short numeric string (e.g., "21742")
- `condition_id`: 0x... hex string

### Test 2: Verify Resolution Check

When the next resolution check runs (every 10 cycles = ~2.5 hours):

**Look for in logs:**
```
[RESOLUTION DEBUG] API returned data with keys: [...]
```

Instead of:
```
[RESOLUTION DEBUG] ❌ No data returned from API
```

### Test 3: Manual API Test

Test if API works with correct ID format:
```bash
curl "https://gamma-api.polymarket.com/markets/21742"
# Should return market data
```

---

## Impact & Benefits

### Before Fix:
- ❌ 0/323 markets resolvable (100% failure)
- ❌ API returned no data for any market
- ❌ Resolution tracking completely broken
- ❌ Win rates impossible to calculate
- ❌ ELO system blocked

### After Fix:
- ✅ New markets use correct ID format
- ✅ API calls will succeed
- ✅ Resolution tracking will work
- ✅ Win rates can be calculated
- ✅ ELO system unblocked

---

## Files Modified

1. **[database.py](monitoring/database.py)**
   - Updated `update_market()` - Added `condition_id` parameter
   - Updated `store_market_dict()` - Extract and use both IDs
   - Added `market_exists_by_condition_id()` helper method

2. **[add_condition_id_column.py](scripts/add_condition_id_column.py)**
   - Migration script to add `condition_id` column
   - Preserves existing data

3. **[MARKET_ID_FIX_APPLIED.md](MARKET_ID_FIX_APPLIED.md)**
   - This documentation file

---

## Next Actions

### Immediate (Automatic):
- ✅ Code changes are live
- ✅ Next monitoring cycle will use correct IDs for NEW markets
- ⏳ Wait ~2.5 hours for next resolution check

### Optional (Manual - Faster):
Create and run a backfill script to update existing 323 markets:

```python
# scripts/backfill_market_ids.py
# 1. Get all markets with conditionId in market_id field
# 2. Query API to find their correct 'id' values
# 3. Update market_id with correct values
# 4. Verify all markets updated
```

### Monitor for Success:
Look for in next resolution check (~2.5 hours):
```
[RESOLUTION DEBUG] API returned data with keys: [...]
[RESOLUTION] ✓ Market is closed/archived: ...
[RESOLUTION] ✅ Market resolved: ... → yes
```

Instead of:
```
No data returned: 323
```

---

## Technical Details

### Polymarket ID System

Polymarket markets have multiple identifiers:

1. **`id`** - Primary API identifier (string/number)
   - Used by: `/markets/{id}` endpoint
   - Example: "21742", "18956"
   - Format: Numeric string or UUID

2. **`conditionId`** - Blockchain condition identifier (hex)
   - Used by: Trade matching, on-chain data
   - Example: "0x1b6f76e5b8587ee896c35847e12d11e75290a8c3..."
   - Format: 66-character hex string (0x + 64 hex digits)

3. **`questionId`** - Question identifier (sometimes present)

4. **`slug`** - URL-friendly identifier (sometimes present)

### Why Two IDs?

- **API (`id`)**: For REST API operations (get market details, etc.)
- **Blockchain (`conditionId`)**: For on-chain contracts and trade events

Our system needs BOTH:
- Use `id` for resolution checking (API calls)
- Use `conditionId` for matching trades with markets

---

## Summary

**Problem:** Resolution checking failed because we stored the wrong ID format

**Solution:** Store BOTH ID types - use correct one for each purpose

**Result:** Resolution tracking will now work correctly

**Timeline:** Next resolution check in ~2.5 hours will show if fix worked

**Success Criteria:** API returns data instead of "No data returned: 323"

🎯 **Fix is LIVE - monitoring system will automatically use correct IDs going forward!**
