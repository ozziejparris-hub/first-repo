# Trader Performance Analysis Tool

## Overview

`trader_performance_analysis.py` analyzes trader performance by calculating actual win rates and ROI based on resolved Polymarket markets.

## Features

### 1. Win Rate Calculation
- Checks which markets have resolved (closed/ended)
- Determines winning outcome for each resolved market
- Calculates win rate: `(winning_trades / total_resolved_trades) × 100`
- Only counts trades on markets that have actually resolved

### 2. ROI (Return on Investment)
- **Winning trades**: `profit = shares × (1 - purchase_price)`
- **Losing trades**: `loss = shares × purchase_price`
- **ROI**: `(total_profit / total_invested) × 100`

### 3. Performance Reports
- **Top 10 by Win Rate**: Traders with highest % of winning trades (min 10 resolved trades)
- **Top 10 by ROI**: Traders with best return on investment
- **Top 10 by Combined Score**: Balanced metric (50% win rate + 50% ROI)

### 4. Statistics
- Average win rate across all qualified traders
- Median ROI
- Total trades analyzed
- Percentage of resolved markets

### 5. CSV Export
- Full trader rankings saved to timestamped CSV files
- Includes all metrics: trades, win rate, P&L, ROI, volume

## Usage

### Run Analysis

```bash
python trader_performance_analysis.py
```

### Select Time Period

When prompted, choose:
1. **Last 7 days** - Recent performance
2. **Last 30 days** - Monthly performance
3. **All time** - Complete history (default)
4. **All periods** - Run all three analyses sequentially

### Example Output

```
======================================================================
TRADER PERFORMANCE ANALYSIS
Analyzing all time
======================================================================

📊 Loading trades from database...
Found 1,523 total trades
Analyzing 149 unique traders...

Checking resolution status for 87 markets...
Progress: 87/87 markets checked ✓
Found 23 resolved markets (26.4%)

Progress: 149/149 traders analyzed ✓

======================================================================
PERFORMANCE REPORT
======================================================================

Qualified traders (≥10 resolved trades): 12

📈 OVERALL STATISTICS:
   Total trades analyzed: 1,523
   Resolved trades: 234 (15.4%)
   Average win rate: 62.45%
   Median ROI: 18.32%
   Total P&L: $12,345.67

======================================================================
🏆 TOP 10 TRADERS BY WIN RATE
======================================================================
Rank  Address         Win Rate    W-L         Resolved    ROI
----------------------------------------------------------------------
1     0x7a9b2c4...    78.26%     18-5            23        24.56%
2     0x3f8e1d2...    75.00%     15-5            20        19.83%
3     0x9c4a7b3...    71.43%     20-8            28        31.22%
...

======================================================================
💰 TOP 10 TRADERS BY ROI (Return on Investment)
======================================================================
Rank  Address         ROI         P&L             Win Rate    Resolved
--------------------------------------------------------------------------
1     0x9c4a7b3...    31.22%     $2,456.78       71.43%          28
2     0x7a9b2c4...    24.56%     $1,892.34       78.26%          23
...

✅ Report saved to: trader_performance_alltime_20251112.csv
   Total traders: 149
   Timestamp: 2025-11-12 14:32:15
```

## How It Works

### Step 1: Load Trades
Reads all trades from `polymarket_tracker.db` (read-only, doesn't modify database)

### Step 2: Check Market Resolutions
For each unique market:
- Queries Polymarket API for market details
- Checks if market is `closed` or `archived`
- Determines winning outcome (if resolved)
- Caches results to avoid duplicate API calls

### Step 3: Calculate Performance
For each trader:
- Groups all their trades
- For resolved markets only:
  - Checks if they bet on winning side
  - Calculates actual profit/loss
  - Tracks total invested amount
- Calculates win rate and ROI

### Step 4: Generate Reports
- Filters traders with ≥10 resolved trades (configurable)
- Ranks by win rate, ROI, and combined score
- Displays formatted tables
- Exports to CSV with timestamp

## Important Notes

### Market Resolution
- **Resolved markets**: Closed/archived markets with determined winner
- **Unresolved markets**: Still active or closed without clear winner
- Only resolved markets count toward win rate and ROI

### Minimum Trade Requirement
Default: **10 resolved trades** to qualify for rankings
- Ensures statistical significance
- Filters out lucky one-time traders
- Can be adjusted in code: `min_resolved_trades = 10`

### P&L Calculation
```python
# Winning trade example:
# Bought 100 shares of "Yes" at $0.65
# Market resolved to "Yes"
invested = 100 × 0.65 = $65
payout = 100 × 1.00 = $100
profit = $100 - $65 = $35

# Losing trade example:
# Bought 100 shares of "Yes" at $0.65
# Market resolved to "No"
invested = 100 × 0.65 = $65
payout = $0
loss = -$65
```

### CSV Output Columns
- Rank
- Trader Address (full)
- Total Trades (all trades)
- Resolved Trades (used for calculations)
- Winning Trades
- Losing Trades
- Win Rate (%)
- Total P&L ($)
- Total Invested ($)
- Total Volume ($)
- ROI (%)
- Combined Score

## Performance

- **API Calls**: One per unique market (with caching)
- **Rate Limiting**: 0.1s delay between market checks
- **Database**: Read-only access, no modifications
- **Typical Runtime**:
  - 50 markets: ~10-15 seconds
  - 200 markets: ~30-45 seconds
  - 500 markets: ~1-2 minutes

## Limitations

### 1. Resolution Detection
Some markets may not have clear resolution data in API. The script:
- Checks multiple fields (`payoutNumerator`, `resolved`, `winningOutcome`)
- Falls back to "unresolved" if unclear
- May miss some resolved markets with incomplete data

### 2. Buy vs Sell Complexity
Current implementation handles:
- **Buy trades**: Wins if bought outcome won
- **Sell trades**: Wins if sold outcome lost

Does NOT handle:
- Complex multi-outcome markets
- Partial position closures
- Average price tracking across multiple buys/sells

### 3. Time Lag
- Markets may resolve after your database snapshot
- Run analysis periodically for updated results
- Re-running is safe (uses cached resolutions)

## Troubleshooting

### "Database not found"
```
❌ Error: polymarket_tracker.db not found
```
**Solution**: Wait for monitoring script to collect trades first

### "No traders with enough resolved trades"
```
⚠️ No traders with enough resolved trades for analysis
```
**Causes**:
- Most markets are still unresolved (normal for recent data)
- Time period too short (try "All time")
- Minimum threshold too high

**Solutions**:
- Let monitoring run longer to collect more data
- Wait for markets to resolve (can take days/weeks)
- Lower `min_resolved_trades` in code

### API Errors
```
Error fetching market abc123: 403 Forbidden
```
**Cause**: API key missing or invalid
**Solution**: Check `.env` file has valid `POLYMARKET_API_KEY`

### Slow Performance
**Causes**: Many unique markets to check
**Solutions**:
- Reduce `days_filter` to analyze recent data only
- First run is slowest (builds cache)
- Subsequent runs use cached resolutions

## Integration with Monitoring

This script is designed to work alongside `main.py`:

1. **main.py**: Runs continuously, collects trades
2. **trader_performance_analysis.py**: Run periodically to analyze performance

**Recommended Schedule**:
- Run analysis weekly to check trader performance
- Markets typically resolve within days to weeks
- More frequent analysis won't show much change (markets need time to resolve)

## Future Enhancements

Potential improvements:
- [ ] Track performance over time (trend analysis)
- [ ] Market category performance (geopolitics vs sports)
- [ ] Visualizations (charts, graphs)
- [ ] Alert on high-performing new traders
- [ ] Export to Google Sheets
- [ ] Web dashboard
- [ ] Position tracking (average entry price)
- [ ] Sharpe ratio calculation
- [ ] Risk-adjusted returns

## Questions?

The script includes extensive error handling and progress indicators. If you encounter issues:

1. Check database exists and has trades
2. Verify API key in `.env`
3. Ensure markets have had time to resolve
4. Check output for specific error messages
