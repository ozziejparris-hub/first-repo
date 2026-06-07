# Smart Money Consensus Detection

## Overview

Detects when multiple elite traders (ELO ≥ 1550) take the same position on a market, providing a much stronger trading signal than individual trades.

**Implementation Date:** 2026-01-30
**Status:** ✅ COMPLETE

---

## Why This Matters

### Individual Trade Alert
```
🎯 Trader 0x4017... bet $15k on YES
```
**Signal strength:** 🔥 Moderate
**Confidence:** One trader could be wrong

### Consensus Alert
```
🎯 7 elite traders all bet YES within 12 hours
   Combined: $45k
```
**Signal strength:** 🔥🔥🔥 Very Strong
**Confidence:** Unlikely all 7 are wrong

**Key Insight:** When multiple skilled, independent traders independently come to the same conclusion, the signal is exponentially stronger.

---

## Features Implemented

### 1. Consensus Entry Detection ✅

**Triggers when:**
- 3+ traders with ELO ≥ 1550
- All take same position (YES or NO)
- Within last 24 hours

**Alert Format:**
```
🎯 SMART MONEY CONSENSUS DETECTED

📊 Market: "Will Trump win the 2024 election?"
🎲 Position: YES
👥 Elite Traders: 7
💰 Combined Size: $45,230

Top Traders:
  • 0x4017...7f9a (ELO: 1598)
  • 0x4f23...8b2c (ELO: 1579)
  • 0xcc3e...1d4a (ELO: 1578)
  • 0x51d2...9e3b (ELO: 1576)
  • 0x3ae9...2f5c (ELO: 1565)
  • ...and 2 more

⏰ Time Window: 2026-01-30 08:15 → 2026-01-30 14:23

🔗 Market: https://polymarket.com/event/...

💡 Signal Strength: 🔥🔥🔥 VERY STRONG
```

**Signal Strength Levels:**
- **3 traders** = 🔥 MODERATE
- **4 traders** = 🔥🔥 STRONG
- **5+ traders** = 🔥🔥🔥 VERY STRONG

---

### 2. Consensus Exit Detection ✅

**Triggers when:**
- 2+ traders with ELO ≥ 1550
- All selling positions (negative shares)
- Within last 6 hours

**Alert Format:**
```
🚨 SMART MONEY EXIT DETECTED

📊 Market: "Bitcoin above $100k by March?"
🎲 Position: YES
👥 Elite Traders Exiting: 4
📉 Shares Sold: 12,450

Sellers:
  • 0x4017...7f9a (ELO: 1598)
  • 0xcc3e...1d4a (ELO: 1578)
  • 0x51d2...9e3b (ELO: 1576)
  • 0x7a8b...4c2d (ELO: 1562)

⚠️ Signal: Elite traders taking profits or cutting losses

🔗 Market: https://polymarket.com/event/...
```

**Why this matters:** When skilled traders simultaneously exit a position, it often signals:
- They've hit profit targets
- New information changed their thesis
- Market conditions have changed
- Early warning of trend reversal

---

### 3. Weekly Consensus Summary ✅

**Added to weekly reports (Sunday 20:00):**
```
📈 WEEKLY PERFORMANCE SUMMARY

[... existing sections ...]

🎯 Strongest Consensuses This Week:
1. "Will Trump win 2024 election?"
   YES - 7 elite traders | $45,230 volume
2. "Fed rate cut in March?"
   NO - 5 elite traders | $28,950 volume
3. "Bitcoin above $100k by Q2?"
   YES - 4 elite traders | $19,340 volume
```

**Shows:**
- Top 3 consensus positions from the last 7 days
- Minimum 3 elite traders required
- Sorted by trader count, then volume

---

## Implementation Details

### File Modified
[monitoring/system_observer.py](monitoring/system_observer.py)

### New Methods Added

**1. `_check_consensus_positions()` (Lines 996-1103)**
- Runs every hour
- Searches last 24 hours for consensus entries
- Prevents duplicate alerts with in-memory tracking

**2. `_check_consensus_exits()` (Lines 1113-1188)**
- Runs every hour
- Searches last 6 hours for consensus exits
- Tracks alerted exits to prevent spam

**3. Helper Methods:**
- `_already_alerted_consensus()` - Check if consensus already alerted
- `_mark_consensus_alerted()` - Mark consensus as alerted
- `_already_alerted_exit()` - Check if exit already alerted
- `_mark_exit_alerted()` - Mark exit as alerted

**4. Weekly Summary Enhancement (Lines 962-978)**
- Added consensus query to existing `_send_weekly_summary()`
- Displays top 3 consensuses from last 7 days

### Scheduling
```python
# In hourly report loop (_hourly_report_loop)
await self._check_high_value_trades()
await self._check_consensus_positions()  # NEW
await self._check_consensus_exits()      # NEW
await self.telegram.send_hourly_report(metrics)
```

**Frequency:** Every hour alongside hourly reports

---

## Configuration Parameters

### Hardcoded (Can be adjusted in code)

**Consensus Entry:**
- Minimum traders: 3
- Minimum ELO: 1550
- Time window: 24 hours
- Only positive shares (buying)

**Consensus Exit:**
- Minimum traders: 2
- Minimum ELO: 1550
- Time window: 6 hours
- Only negative shares (selling)

**Weekly Summary:**
- Minimum traders: 3
- Time window: 7 days
- Limit: Top 3 consensuses

### To Adjust Thresholds

Edit [monitoring/system_observer.py](monitoring/system_observer.py):

**For stricter signals (fewer alerts, higher quality):**
```python
# Line ~1034: Change minimum traders
HAVING trader_count >= 4  # Instead of 3

# Line ~1026: Increase ELO requirement
WHERE t.comprehensive_elo >= 1600  # Instead of 1550
```

**For more frequent signals (more alerts, potentially noisier):**
```python
# Line ~1034: Lower minimum traders
HAVING trader_count >= 2  # Instead of 3

# Line ~1009: Extend time window
cutoff = datetime.now() - timedelta(hours=48)  # Instead of 24
```

---

## Database Queries

### Consensus Entry Query
```sql
SELECT
    tr.market_id,
    m.title as market_question,
    tr.outcome,
    COUNT(DISTINCT tr.trader_address) as trader_count,
    SUM(tr.shares * tr.price) as total_volume,
    GROUP_CONCAT(t.address || '|' || CAST(t.comprehensive_elo AS TEXT)) as traders,
    MIN(tr.timestamp) as first_trade,
    MAX(tr.timestamp) as last_trade
FROM trades tr
JOIN traders t ON tr.trader_address = t.address
LEFT JOIN markets m ON tr.market_id = m.market_id
WHERE
    t.comprehensive_elo >= 1550
    AND tr.timestamp >= ?  -- Last 24 hours
    AND tr.shares > 0      -- Only buys
GROUP BY tr.market_id, tr.outcome
HAVING trader_count >= 3
ORDER BY trader_count DESC, total_volume DESC
LIMIT 5
```

### Consensus Exit Query
```sql
SELECT
    tr.market_id,
    m.title as market_question,
    tr.outcome,
    COUNT(DISTINCT tr.trader_address) as sellers,
    SUM(ABS(tr.shares)) as shares_sold,
    GROUP_CONCAT(t.address || '|' || CAST(t.comprehensive_elo AS TEXT)) as traders
FROM trades tr
JOIN traders t ON tr.trader_address = t.address
LEFT JOIN markets m ON tr.market_id = m.market_id
WHERE
    t.comprehensive_elo >= 1550
    AND tr.timestamp >= ?  -- Last 6 hours
    AND tr.shares < 0      -- Only sells
GROUP BY tr.market_id, tr.outcome
HAVING sellers >= 2
ORDER BY sellers DESC
LIMIT 5
```

---

## Alert Deduplication

### In-Memory Tracking

Alerts are tracked using Python sets to prevent duplicates:

**For entries:**
```python
self._alerted_consensuses = set()
# Stores: "market_id_outcome" keys
# Example: "0x1234...abcd_YES"
```

**For exits:**
```python
self._alerted_exits = set()
# Stores: "market_id_outcome" keys
# Example: "0x1234...abcd_YES"
```

**Limitation:** Resets on System Observer restart

**Solution for persistent tracking (optional):**
Create database table:
```sql
CREATE TABLE consensus_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    alert_type TEXT,  -- 'entry' or 'exit'
    trader_count INTEGER,
    alerted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(market_id, outcome, alert_type)
);
```

Then query before sending alerts. Not implemented yet but can be added if needed.

---

## Testing

### Test 1: Manual Consensus Check

**Run in Python console:**
```python
from monitoring.system_observer import SystemObserver
import asyncio

observer = SystemObserver(
    telegram_token="YOUR_TOKEN",
    chat_id="YOUR_CHAT_ID",
    monitoring_pid=None
)

# Check for consensus entries
asyncio.run(observer._check_consensus_positions())

# Check for consensus exits
asyncio.run(observer._check_consensus_exits())
```

### Test 2: Verify Scheduling

**After restarting System Observer:**
```bash
python scripts/run_system_observer.py
```

**Wait for hourly report (on the hour)**

**Expected console output:**
```
[OBSERVER] Sending hourly status report...
[OBSERVER] Sent high-value trade alert for 0x4017... ($15,340)
[OBSERVER] Sent consensus alert: 0x1234...abcd YES (5 traders)
[OBSERVER] Sent exit alert: 0x5678...efgh NO (3 traders)
[OBSERVER] Weekly report sent successfully
```

### Test 3: Check Telegram

**Wait for next consensus to form naturally**

**Expected Telegram message:**
```
🎯 SMART MONEY CONSENSUS DETECTED
...
```

---

## Expected Behavior

### Hourly Cycle

Every hour, System Observer:
1. Checks for high-value trades (individual $1k+ trades)
2. ✅ **NEW:** Checks for consensus entries (3+ elite traders)
3. ✅ **NEW:** Checks for consensus exits (2+ elite traders selling)
4. Sends hourly report

### Weekly Summary

Every Sunday at 20:00, includes:
1. Top trader
2. Hottest markets
3. Your opportunities
4. ✅ **NEW:** Strongest consensuses (top 3 from last 7 days)

---

## Signal Quality Analysis

### Consensus Entry Examples

**Example 1: MODERATE Signal (3 traders)**
```
Market: "Will inflation exceed 3% in Q1?"
Position: YES
Traders: 3 elite (ELO 1550-1570)
Volume: $8,500
```
**Action:** Worth investigating, but verify with other sources

**Example 2: STRONG Signal (4 traders)**
```
Market: "Fed rate cut in March?"
Position: NO
Traders: 4 elite (ELO 1560-1590)
Volume: $18,400
```
**Action:** High confidence, consider following

**Example 3: VERY STRONG Signal (7 traders)**
```
Market: "Trump wins 2024 election?"
Position: YES
Traders: 7 elite (ELO 1550-1598)
Volume: $45,230
```
**Action:** Extremely high confidence, strong buy signal

---

## False Positives & Limitations

### Potential Issues

**1. Coordinated Trading**
- Multiple traders could be following same analysis source
- Not truly independent decisions
- Still valuable signal but less strong

**2. Herd Mentality**
- Later traders may be copying earlier ones
- Check time window - wider spacing = more independent

**3. Market Manipulation**
- Multiple accounts from same entity
- Mitigated by ELO requirement (hard to fake high ELO)

**4. Stale Alerts**
- Market conditions may have changed since consensus formed
- Always check current market state before trading

### Best Practices

✅ **Do:**
- Verify the consensus with current market data
- Check if any elite traders have exited since entry
- Look for exit signals before entering
- Combine with other analysis

❌ **Don't:**
- Blindly follow every consensus alert
- Ignore exit signals
- Trade without checking market fundamentals
- Over-leverage based on signals alone

---

## Deployment

### Apply Changes

Changes already applied to:
- [monitoring/system_observer.py](monitoring/system_observer.py)

### Restart System Observer

```bash
# Kill and restart System Observer
python scripts/kill_all.py
python scripts/start_monitoring.py
python scripts/run_system_observer.py
```

**Note:** Monitoring does NOT need restart - only System Observer

---

## Success Metrics

### After 24 Hours

Expected to see:
- ✅ At least 1-3 consensus entry alerts (depends on market activity)
- ✅ 0-2 consensus exit alerts (less frequent)
- ✅ Console logs showing consensus checks every hour

### After 1 Week

Expected to see:
- ✅ Weekly summary includes top 3 consensuses
- ✅ Multiple consensus alerts sent
- ✅ No duplicate alerts for same consensus

---

## Future Enhancements (Not Implemented)

### Possible Additions:

1. **Consensus Strength Tracking**
   - Track how consensus positions perform
   - Calculate win rate for consensus signals
   - Adjust thresholds based on historical accuracy

2. **Persistent Alert Tracking**
   - Database table for consensus alerts
   - Prevent duplicates across restarts
   - Historical consensus analysis

3. **Consensus Breakdown Alerts**
   - Alert when consensus falls apart (traders exit)
   - Track "consensus integrity" over time

4. **ELO-Weighted Consensus**
   - Weight by trader ELO (higher ELO = stronger signal)
   - 1 trader with ELO 1700 = 2 traders with ELO 1550

5. **Time-Window Analysis**
   - Alert if consensus forms rapidly (< 1 hour = stronger)
   - vs. slowly over 24 hours (weaker)

---

## Summary

### What Was Added

✅ **Consensus Entry Detection** - Alerts when 3+ elite traders take same position
✅ **Consensus Exit Detection** - Alerts when 2+ elite traders exit positions
✅ **Weekly Consensus Summary** - Top 3 consensuses in weekly report
✅ **Duplicate Prevention** - In-memory tracking to prevent alert spam

### Configuration

- Minimum ELO: 1550 (elite traders only)
- Entry threshold: 3+ traders within 24 hours
- Exit threshold: 2+ traders within 6 hours
- Signal strength: Moderate/Strong/Very Strong

### Files Modified

1. [monitoring/system_observer.py](monitoring/system_observer.py)
   - Added 4 new methods
   - Enhanced weekly summary
   - Integrated into hourly checks

### Impact

- **Stronger signals** than individual trades
- **Early warnings** when elite traders exit
- **Weekly insights** into market consensus
- **Better trading decisions** based on collective intelligence

---

**Implementation Date:** 2026-01-30
**Status:** ✅ COMPLETE AND READY FOR DEPLOYMENT
**Expected Result:** High-quality trading signals from smart money consensus
