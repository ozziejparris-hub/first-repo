# Market ID Backfill Instructions

## Quick Summary

**Problem:** 323 existing markets have `conditionId` (0x...) in the `market_id` field
**Solution:** Backfill script queries Polymarket API to find correct market IDs
**Result:** Resolution tracking will work for ALL markets, not just new ones

---

## Pre-Flight Check

### 1. Check How Many Markets Need Fixing

```bash
python scripts/check_markets_needing_fix.py
```

**Expected Output:**
```
Markets needing fix: 323
Markets already correct: 0
Total markets: 323
```

### 2. Verify Environment

Make sure your `.env` file has:
```
POLYMARKET_API_KEY=your_key_here
```

---

## Running the Backfill

### Step 1: Dry Run (Preview Changes)

**ALWAYS run dry-run first** to see what will be updated:

```bash
python scripts/backfill_market_ids.py --dry-run
```

**What This Does:**
- Queries Polymarket API for each market
- Finds correct market_id using multiple strategies
- Shows what WOULD be updated (but doesn't update)
- Displays progress and statistics

**Expected Output:**
```
========================================================================
MARKET ID BACKFILL SCRIPT
========================================================================

[DRY RUN MODE] No changes will be made to the database

Step 1: Identifying markets that need fixing...
Found 323 markets with conditionId in market_id field

Step 2: Finding correct market IDs from API...
------------------------------------------------------------------------

[1/323] Processing: Ukraine joins NATO in 2025?...
  Old ID: 0x9bacdaac65cbe257e9... (conditionId)
  ✓ Found correct ID: 21742 (via title_match)
  ✓ Verified: API returns data for this ID
  Would update database: market_id = 21742

[2/323] Processing: Khamenei out as Supreme Leader...
  Old ID: 0x1b6f76e5b8587ee896... (conditionId)
  ✓ Found correct ID: 18956 (via title_match)
  ✓ Verified: API returns data for this ID
  Would update database: market_id = 18956

...

========================================================================
BACKFILL SUMMARY
========================================================================
Total markets processed: 323
Successfully updated: 310
Failed to update: 13
Skipped (already correct): 0
Skipped (other): 0

Success rate: 96.0%

[DRY RUN] Run without --dry-run to apply changes
========================================================================
```

### Step 2: Review the Dry Run Results

Check the output for:
- ✅ **Success rate** - Should be >90%
- ⚠️ **Failed updates** - Note which markets failed
- 🔍 **Sample updates** - Verify correct IDs are being found

### Step 3: Run the Actual Backfill

If dry-run looks good, run it for real:

```bash
python scripts/backfill_market_ids.py
```

**This will:**
- Update the database with correct market IDs
- Preserve condition_id for trade matching
- Display progress and final statistics
- Take ~5-10 minutes for 323 markets

### Step 4: Test the Results

After backfill completes, test that resolution checking works:

```bash
python scripts/backfill_market_ids.py --test
```

**What This Does:**
- Tests 5 sample markets
- Verifies API returns data for updated IDs
- Shows which fields are available

**Expected Output:**
```
========================================================================
TESTING SAMPLE MARKETS
========================================================================

Testing 5 sample markets:

1. Testing: Ukraine joins NATO in 2025?...
   Market ID: 21742
   ✓ SUCCESS! API returned data
   Keys available: ['id', 'question', 'outcomes', 'closed', 'archived']

2. Testing: Khamenei out as Supreme Leader...
   Market ID: 18956
   ✓ SUCCESS! API returned data
   Keys available: ['id', 'question', 'outcomes', 'closed', 'archived']

...

------------------------------------------------------------------------
Test Results: 5/5 markets returned data
========================================================================
```

---

## How the Backfill Works

### Finding Correct Market IDs

The script tries **3 strategies** to find the correct market_id:

#### Strategy 1: Title Match (Most Common)
```python
# Query active markets API
GET /markets?limit=100&closed=false

# Match by title or conditionId
for market in results:
    if market.title == stored_title:
        return market.id  # Found it!
```

#### Strategy 2: Direct conditionId (Sometimes Works)
```python
# Try fetching directly with conditionId
GET /markets/0x9bacdaac65cbe257e9...

# If it works, extract the correct id
return response.id
```

#### Strategy 3: Search Closed Markets
```python
# Query closed markets API
GET /markets?limit=100&closed=true

# Match by title or conditionId
for market in results:
    if market.title == stored_title:
        return market.id
```

### Update Process

For each market:
1. **Find** correct market_id using strategies above
2. **Verify** the ID works (test API call)
3. **Update** database:
   ```sql
   UPDATE markets
   SET market_id = '21742'
   WHERE condition_id = '0x9bacdaac...'
   ```

---

## Troubleshooting

### Issue: Script fails with "No module named 'requests'"

**Solution:** The monitoring system has requests installed. Run from monitoring environment:
```bash
# Activate your monitoring environment first
python scripts/backfill_market_ids.py --dry-run
```

### Issue: "No markets need fixing"

**Good news!** This means either:
- Backfill already completed successfully
- Monitoring has been running and storing correct IDs

**Verify:**
```bash
python scripts/check_markets_needing_fix.py
```

### Issue: Low success rate (<80%)

**Possible causes:**
1. API rate limiting - Add delays between requests
2. Markets deleted from Polymarket - Normal for old markets
3. API endpoint changed - Check Polymarket API docs

**Solution:**
- Markets that fail won't break anything
- They'll get updated when monitoring sees them again
- Resolution check will work for the ones that succeeded

### Issue: "POLYMARKET_API_KEY not found"

**Solution:**
```bash
# Check .env file exists
cat .env | grep POLYMARKET_API_KEY

# If missing, add it:
echo "POLYMARKET_API_KEY=your_key_here" >> .env
```

---

## What Gets Updated

### Before Backfill:

```sql
market_id              | condition_id          | title
---------------------- | --------------------- | ----------------------
0x9bacdaac65cbe257e9.. | 0x9bacdaac65cbe257e9..| Ukraine joins NATO...
```

❌ **Problem:** market_id is conditionId - API won't work

### After Backfill:

```sql
market_id | condition_id          | title
--------- | --------------------- | ----------------------
21742     | 0x9bacdaac65cbe257e9..| Ukraine joins NATO...
```

✅ **Fixed:** market_id is API-compatible - Resolution tracking works!

---

## Timeline & Expectations

### Dry Run:
- **Time:** ~5-10 minutes (0.2s per market × 323 markets)
- **API calls:** 600-900 (multiple strategies per market)
- **Safe:** Makes no changes

### Actual Backfill:
- **Time:** ~5-10 minutes
- **API calls:** 600-900
- **Updates:** 310+ markets (95%+ success rate)

### After Backfill:
- **Immediate:** Resolution tracking enabled for updated markets
- **Next check:** ~2.5 hours (next automatic resolution check)
- **Expected:** API returns data instead of 404 errors

---

## Verification

### Check Database After Backfill:

```bash
python scripts/check_markets_needing_fix.py
```

**Expected:**
```
Markets needing fix: 0-13 (only failures remain)
Markets already correct: 310+
Total markets: 323
```

### Check Resolution Logs:

Look for in next resolution check (~2.5 hours):

**Before Backfill:**
```
No data returned: 323
Markets checked via API: 323
```

**After Backfill:**
```
No data returned: 0-13
Markets checked via API: 323
Markets marked as closed/archived: 5-10
```

---

## Options

### Command Line Flags:

```bash
# Preview without changes
python scripts/backfill_market_ids.py --dry-run

# Run the backfill
python scripts/backfill_market_ids.py

# Backfill + test sample markets
python scripts/backfill_market_ids.py --test

# Custom database path
python scripts/backfill_market_ids.py --db-path /path/to/db
```

---

## FAQ

**Q: Will this break anything?**
A: No! It only updates the market_id field. condition_id stays the same for trade matching.

**Q: What if it fails for some markets?**
A: Normal! Some markets may be deleted or unavailable. Failed markets will be retried when monitoring sees them again.

**Q: Do I need to stop monitoring while running this?**
A: No, but it's safer to stop it to avoid database conflicts. The script is safe to run while monitoring is active.

**Q: How often should I run this?**
A: **Once only!** After this backfill, new markets will automatically get correct IDs.

**Q: What if I run it twice?**
A: Safe! It skips markets that already have correct format.

---

## Next Steps After Backfill

1. ✅ **Wait for next resolution check** (~2.5 hours)
2. ✅ **Check logs for API success** (should see data returned)
3. ✅ **Monitor for resolved markets** (first resolutions incoming!)
4. ✅ **Win rates will start calculating** (as markets resolve)
5. ✅ **ELO system will activate** (once enough resolutions)

---

## Summary

```bash
# Quick start:
python scripts/backfill_market_ids.py --dry-run  # Preview
python scripts/backfill_market_ids.py            # Apply
python scripts/backfill_market_ids.py --test     # Verify
```

**Expected Results:**
- 310+ markets updated (95%+ success rate)
- Resolution tracking enabled for ALL markets
- Next resolution check will show API success

🎯 **This completes the market ID fix - resolution tracking will finally work!**
