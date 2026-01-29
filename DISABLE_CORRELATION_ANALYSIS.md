# Disable Correlation Matrix Analysis

**Date:** 2026-01-28
**Issue:** Correlation matrix calculation stuck on 8.9M trader pairs
**Status:** Analysis of issue + solutions provided

---

## Problem Analysis

### Current Situation

**File:** `analysis/correlation_matrix.py`

This is a **standalone analysis script** (not part of System Observer) that calculates correlations between all trader pairs.

**Current numbers:**
- Total active traders: ~4,220
- Total pairs to calculate: 8,902,090 (4220 × 4219 / 2)
- Estimated completion time: **10+ days**
- Progress: Stuck at 8,885,800/8,902,090

### Why It's So Slow

The script calculates 3 correlation metrics for EVERY trader pair:
1. Market overlap (30% weight)
2. Outcome agreement (50% weight)
3. Timing similarity (20% weight)

**Complexity:** O(n²) where n = number of traders

| Traders | Pairs | Estimated Time |
|---------|-------|----------------|
| 100 | 4,950 | ~5 minutes |
| 500 | 124,750 | ~2 hours |
| 1,000 | 499,500 | ~12 hours |
| 2,000 | 1,999,000 | ~2 days |
| **4,220** | **8,902,090** | **10+ days** |

---

## Solution 1: Stop the Running Process

If correlation analysis is currently running:

### Windows
```bash
# Find the process
tasklist | findstr python

# Look for python.exe running correlation_matrix.py
# Note the PID

# Kill it
taskkill /PID <PID> /F
```

### Alternative (if you don't know PID)
```bash
# Kill ALL Python processes (WARNING: stops monitoring too!)
taskkill /IM python.exe /F

# Then restart only monitoring
python -m monitoring
```

---

## Solution 2: Prevent It From Running Again

The correlation script is a standalone tool that must be manually invoked. It's NOT called automatically by:
- System Observer
- Monitoring loop
- Background worker

**It only runs when you explicitly call:**
```bash
python analysis/correlation_matrix.py
```

**To prevent accidental execution:**

**Option A: Rename the file**
```bash
mv analysis/correlation_matrix.py analysis/correlation_matrix.py.DISABLED
```

**Option B: Add early exit at top of main()**

**File:** `analysis/correlation_matrix.py`

**At line ~450 (start of main function), add:**
```python
def main():
    """Main entry point for correlation matrix analysis."""

    # DISABLED: Too expensive for large trader sets (4000+ traders)
    # Calculating 8.9M pairs would take 10+ days
    # Use top-100 mode instead (see solution below)
    print("="*70)
    print("CORRELATION MATRIX ANALYSIS DISABLED")
    print("="*70)
    print()
    print("Current traders: ~4,220")
    print("Total pairs: 8,902,090")
    print("Estimated time: 10+ days")
    print()
    print("To analyze correlations, use top-100 mode:")
    print("  python analysis/correlation_matrix.py --top-n 100")
    print()
    print("This calculates only 4,950 pairs (~5 minutes)")
    print("="*70)
    return  # EXIT EARLY

    # Original code below...
    parser = argparse.ArgumentParser(...)
```

---

## Solution 3: Top-N Mode (Recommended Alternative)

Instead of analyzing ALL traders, analyze only top performers.

### Add Top-N Argument

**File:** `analysis/correlation_matrix.py`

**In main(), add this argument (around line 460):**
```python
parser.add_argument('--top-n', type=int, default=None,
                   help='Analyze only top N traders by ELO (default: all)')
```

**Then modify trader selection (around line 480):**
```python
# BEFORE (analyzes ALL traders):
cursor.execute("""
    SELECT DISTINCT trader_address
    FROM trades
    WHERE timestamp > datetime('now', '-30 days')
""")

# AFTER (analyzes top N traders):
if args.top_n:
    print(f"[FILTER] Analyzing top {args.top_n} traders only...")
    cursor.execute("""
        SELECT address
        FROM traders
        WHERE composite_elo IS NOT NULL
        ORDER BY composite_elo DESC
        LIMIT ?
    """, (args.top_n,))
else:
    cursor.execute("""
        SELECT DISTINCT trader_address
        FROM trades
        WHERE timestamp > datetime('now', '-30 days')
    """)

trader_addresses = [row[0] for row in cursor.fetchall()]
print(f"[TRADERS] Analyzing {len(trader_addresses)} traders...")

total_pairs = len(trader_addresses) * (len(trader_addresses) - 1) // 2
print(f"[PAIRS] Will calculate {total_pairs:,} correlations")

# Warn if too many
if total_pairs > 50000:
    print(f"[WARNING] This will take a LONG time ({total_pairs:,} pairs)")
    print(f"[WARNING] Consider using --top-n 100 for faster results")
    response = input("Continue anyway? (yes/no): ")
    if response.lower() != 'yes':
        print("[CANCELLED] Exiting...")
        return
```

### Usage Examples

```bash
# Top 100 traders (fast - 5 minutes)
python analysis/correlation_matrix.py --top-n 100

# Top 50 traders (very fast - 1 minute)
python analysis/correlation_matrix.py --top-n 50

# Top 20 traders (instant - 10 seconds)
python analysis/correlation_matrix.py --top-n 20

# All traders (DON'T DO THIS - 10+ days)
python analysis/correlation_matrix.py  # Will prompt for confirmation
```

### Performance Comparison

| Mode | Traders | Pairs | Time | Use Case |
|------|---------|-------|------|----------|
| Top 20 | 20 | 190 | 10s | Quick check |
| Top 50 | 50 | 1,225 | 1 min | Regular analysis |
| Top 100 | 100 | 4,950 | 5 min | Comprehensive elite traders |
| Top 500 | 500 | 124,750 | 2 hours | Deep analysis |
| **All (4220)** | 4,220 | 8,902,090 | **10+ days** | ❌ Not practical |

---

## Solution 4: Add Progress Saving (Resume Capability)

If you MUST analyze all traders, add checkpoint saving:

**File:** `analysis/correlation_matrix.py`

**In calculate_correlation_matrix() around line 250:**
```python
def calculate_correlation_matrix(self, trader_addresses, min_shared_markets=3):
    """Calculate correlation between all trader pairs."""

    # NEW: Load checkpoint if exists
    checkpoint_file = 'reports/correlation_checkpoint.json'
    if os.path.exists(checkpoint_file):
        print("[RESUME] Loading checkpoint...")
        with open(checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
            matrix = checkpoint.get('matrix', {})
            start_index = checkpoint.get('last_index', 0)
            print(f"[RESUME] Resuming from pair {start_index:,}")
    else:
        matrix = {}
        start_index = 0

    total_pairs = len(trader_addresses) * (len(trader_addresses) - 1) // 2
    pairs_calculated = len(matrix)

    # ... existing correlation logic ...

    for i in range(len(trader_addresses)):
        for j in range(i + 1, len(trader_addresses)):
            pair_index = i * len(trader_addresses) + j

            # NEW: Skip if before checkpoint
            if pair_index < start_index:
                continue

            # Calculate correlation
            # ... existing code ...

            pairs_calculated += 1

            # NEW: Save checkpoint every 1000 pairs
            if pairs_calculated % 1000 == 0:
                checkpoint = {
                    'matrix': matrix,
                    'last_index': pair_index,
                    'timestamp': datetime.now().isoformat()
                }
                with open(checkpoint_file, 'w') as f:
                    json.dump(checkpoint, f)
                print(f"[CHECKPOINT] Saved at {pairs_calculated:,}/{total_pairs:,} pairs")
```

**With checkpoints:**
- Can stop/resume anytime
- Progress saved every 1000 pairs
- No work lost if interrupted

---

## Solution 5: Disable in System Observer (If Integrated)

If correlation IS being called by System Observer (unlikely but possible):

**File:** `monitoring/system_observer.py`

**Search for these patterns:**
```python
# Look for:
from analysis.correlation_matrix import
correlation_matrix
calculate_correlation
TraderCorrelationMatrix
```

**If found, comment out:**
```python
# DISABLED: Correlation matrix too expensive
# from analysis.correlation_matrix import TraderCorrelationMatrix

# ... later in code ...

# DISABLED: Correlation matrix (8.9M pairs = 10+ days)
# self.calculate_correlations()

print("[OBSERVER] Correlation analysis disabled (use standalone tool if needed)")
```

---

## Recommended Action Plan

**Immediate:**
1. ✅ Kill running correlation process (if any)
2. ✅ Add early exit to correlation_matrix.py main()
3. ✅ Test that System Observer works normally

**Short-term:**
4. ✅ Add --top-n argument to correlation script
5. ✅ Run analysis on top 100 traders only
6. ✅ Add warning prompt for large datasets

**Long-term:**
7. ⏳ Add checkpoint/resume capability
8. ⏳ Optimize correlation algorithm (parallel processing)
9. ⏳ Consider sampling-based correlation for large sets

---

## Testing

After applying solution:

```bash
# Test 1: Verify System Observer works
python -m monitoring

# Should start normally in <10 seconds
# Should NOT show correlation messages

# Test 2: Run correlation on top 100 only
python analysis/correlation_matrix.py --top-n 100

# Should complete in ~5 minutes
# Should show progress: "Calculating 4,950 pairs..."

# Test 3: Try to run all-pairs (should warn)
python analysis/correlation_matrix.py

# Should show warning and prompt for confirmation
# Enter 'no' to cancel
```

---

## Summary

**Problem:**
- Correlation script stuck on 8.9M trader pairs
- Would take 10+ days to complete
- Not automatically called, must be manually invoked

**Solution:**
1. Stop running process (if any)
2. Add early exit to prevent accidental all-pairs analysis
3. Use top-100 mode instead (5 minutes vs 10 days)
4. Add checkpoints for long-running analyses

**Result:**
- System Observer unaffected
- Can still run correlation analysis on elite traders
- No more 10-day calculations

---

**Status:** Solutions provided - implement based on your needs

**Recommended:** Use Solution 2 (early exit) + Solution 3 (top-N mode)
