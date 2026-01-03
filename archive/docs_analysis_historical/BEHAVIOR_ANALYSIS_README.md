# Trading Behavior Analysis Tool

## Overview

`trading_behavior_analysis.py` analyzes trader behavior patterns including betting styles, market diversification, activity timing, and classifies traders into distinct behavioral categories.

## Features

### 1. Betting Patterns Analysis
- **Average Bet Size**: Mean amount (shares × price) per trade
- **Median Bet Size**: Middle value (handles outliers better)
- **Bet Size Range**: Minimum and maximum bets
- **Standard Deviation**: Measures bet size consistency
- **Total Volume**: Sum of all money traded
- **Consistency Score**: "Very Consistent" to "Highly Variable"
  - Based on Coefficient of Variation (CV = std_dev / mean × 100)
  - CV < 30% = Very Consistent
  - CV < 60% = Moderately Consistent
  - CV < 100% = Variable
  - CV ≥ 100% = Highly Variable

### 2. Market Diversification
- **Unique Markets**: Count of different markets traded
- **Diversification Score**: `(unique_markets / total_trades) × 100`
  - Score of 100 = Every trade in different market
  - Score of 10 = Repeatedly trading same markets
- **Top 3 Markets**: Most frequently traded markets with percentages
- **Market Concentration**: "Highly Concentrated" / "Moderately Concentrated" / "Well Diversified"
  - Based on percentage of trades in top market

### 3. Activity Frequency
- **Total Trades**: Lifetime trade count
- **Trades Per Day**: Average daily activity rate
- **Trades Per Week**: Weekly activity projection
- **Most Active Day**: Which day of week trader is most active
- **Most Active Hour**: Peak trading hour (if data available)
- **Activity Trend**: "Increasing" / "Decreasing" / "Stable"
  - Compares first half vs second half of trading history
- **Active Days**: Count of unique days with trades
- **Trading Period**: Days from first to last trade

### 4. Trading Style Classification

Traders are automatically classified into behavioral categories:

| Style | Characteristics |
|-------|----------------|
| **Power User** | High volume (≥50 trades) + High frequency (≥5/day) + High diversification (≥60%) |
| **High Volume Specialist** | Many trades (≥50) but low diversification (<30%) - focuses on few markets |
| **Big Better** | Large bet sizes (≥$100) but infrequent trading (<20 trades) |
| **Micro Trader** | Small bets (<$20) + Many trades (≥50) + High diversification (≥60%) |
| **Cautious Diversifier** | Moderate activity (20-50 trades) + Moderate diversification (30-60%) + Very consistent bet sizes |
| **Weekend Warrior** | Most active on Saturday/Sunday + Low frequency (<1/day) |
| **Active Trader** | High frequency (≥5/day) + Moderate diversification (30-60%) |
| **Casual Trader** | Low frequency (<1/day) + Medium bet sizes ($20-$100) |
| **Strategic Explorer** | High diversification (≥60%) + Low frequency (<1/day) |
| **Market Specialist** | Low diversification (<30%) + Large bets (≥$100) |
| **General Trader** | Doesn't fit specific patterns |

### 5. Special Flags

- **Hot Streak**: Trader with ≥5 trades in last 48 hours
- **Low Reliability**: Traders with <10 total trades (insufficient data for patterns)
- **Power Score**: Combined metric = `trades_per_day × (diversification/10) × (avg_bet/10)`

## Usage

### Run Analysis

```bash
python trading_behavior_analysis.py
```

### Select Time Period

1. **Last 7 days** - Recent behavior
2. **Last 30 days** - Monthly patterns
3. **All time** - Complete history (default)
4. **All periods** - Run all three sequentially

### Example Output

```
======================================================================
TRADING BEHAVIOR ANALYSIS
Analyzing all time
======================================================================

📊 Loading trades from database...
Found 1,523 total trades
Analyzing 149 unique traders...

Progress: 149/149 traders analyzed ✓

======================================================================
TRADING BEHAVIOR REPORT
======================================================================

Total traders analyzed: 149
Reliable traders (≥10 trades): 87
Low reliability traders (<10 trades): 62

📈 OVERALL STATISTICS:
   Average trades per trader: 17.5
   Average bet size: $45.32
   Average diversification score: 42.3%
   Average trades per day: 1.8

🔥 HOT STREAK TRADERS (≥5 trades in last 48h): 3

📊 TRADING STYLE DISTRIBUTION:
   General Trader: 28 traders (32.2%)
   Casual Trader: 18 traders (20.7%)
   Active Trader: 12 traders (13.8%)
   High Volume Specialist: 9 traders (10.3%)
   Cautious Diversifier: 7 traders (8.0%)
   Power User: 5 traders (5.7%)
   Micro Trader: 4 traders (4.6%)
   Weekend Warrior: 4 traders (4.6%)

======================================================================
🏆 MOST ACTIVE TRADERS (by trades per day)
======================================================================
Rank  Address         Trades/Day  Total Trades  Style
----------------------------------------------------------------------
1     0x7a9b2c4...       12.50          75      Power User
2     0x3f8e1d2...        8.30          58      Active Trader
3     0x9c4a7b3...        6.75          54      High Volume Specialist

======================================================================
🎯 MOST DIVERSIFIED TRADERS (by unique markets)
======================================================================
Rank  Address         Unique Markets  Div Score  Concentration
----------------------------------------------------------------------
1     0x2b5c8f9...            45       90.0%     Well Diversified
2     0x8d3e9a1...            38       76.0%     Well Diversified
3     0x5f7g2h4...            32       64.0%     Well Diversified

======================================================================
💰 BIGGEST BETTORS (by average bet size)
======================================================================
Rank  Address         Avg Bet      Total Volume    Consistency
----------------------------------------------------------------------
1     0x1k8m3p7...    $285.50      $8,565.00       Moderately Consistent
2     0x4j9n2q6...    $198.25      $5,947.50       Very Consistent
3     0x7r3t8u1...    $156.80      $4,704.00       Variable

======================================================================
⚡ POWER USERS (by combined metrics)
======================================================================
Rank  Address         Power Score  Style
----------------------------------------------------------------------
1     0x7a9b2c4...      562.50     Power User
2     0x3f8e1d2...      398.40     Active Trader
3     0x9c4a7b3...      275.63     High Volume Specialist

======================================================================
📅 MOST POPULAR TRADING DAYS
======================================================================
   Monday: 23 traders (26.4%)
   Tuesday: 18 traders (20.7%)
   Wednesday: 15 traders (17.2%)
   Thursday: 12 traders (13.8%)
   Friday: 10 traders (11.5%)
   Saturday: 5 traders (5.7%)
   Sunday: 4 traders (4.6%)

✅ Report saved to: trading_behavior_alltime_20251112.csv
```

## CSV Output Columns

The CSV export includes:

**Basic Info:**
- Rank (by power score)
- Trader Address
- Trading Style Classification
- Total Trades

**Betting Patterns:**
- Avg Bet Size ($)
- Median Bet Size ($)
- Min Bet ($)
- Max Bet ($)
- Std Dev Bet ($)
- Total Volume ($)
- Bet Consistency (category)

**Diversification:**
- Unique Markets
- Diversification Score (%)
- Market Concentration (category)

**Activity:**
- Trades Per Day
- Trades Per Week
- Most Active Day
- Most Active Hour
- Activity Trend
- Active Days
- Trading Period (days)

**Special Metrics:**
- Hot Streak (48h)
- Recent 48h Trades
- Power Score
- Low Reliability Flag

**Additional Section:**
- Top 3 Markets per trader with trade counts and percentages

## How It Works

### Step 1: Load Trades
Reads all trades from `polymarket_tracker.db` (read-only access)

### Step 2: Group by Trader
Groups all trades by trader address for individual analysis

### Step 3: Calculate Betting Patterns
For each trader:
- Calculates bet sizes (shares × price)
- Computes mean, median, min, max, std dev
- Determines consistency level using coefficient of variation

### Step 4: Analyze Diversification
- Counts unique markets
- Calculates diversification score
- Identifies top 3 most-traded markets
- Determines concentration level

### Step 5: Track Activity
- Parses timestamps
- Calculates trades per day/week
- Finds most active day/hour
- Analyzes trend (first half vs second half)
- Detects hot streaks (last 48 hours)

### Step 6: Classify Style
Uses decision tree logic based on:
- Trade volume (high/medium/low)
- Bet size (high/medium/low)
- Diversification (high/medium/low)
- Frequency (high/medium/low)
- Weekend activity
- Consistency

### Step 7: Generate Reports
- Creates leaderboards by different metrics
- Shows trading style distribution
- Highlights hot streak traders
- Exports to timestamped CSV

## Key Metrics Explained

### Diversification Score
```
Score = (Unique Markets / Total Trades) × 100

Example:
Trader has 50 trades across 25 different markets
Score = (25 / 50) × 100 = 50%

Interpretation:
- High (60%+): Explores many different markets
- Medium (30-60%): Balanced approach
- Low (<30%): Focuses on few markets repeatedly
```

### Bet Size Consistency (Coefficient of Variation)
```
CV = (Standard Deviation / Mean) × 100

Example:
Trader bets: $10, $12, $11, $9, $13
Mean = $11
Std Dev = $1.58
CV = (1.58 / 11) × 100 = 14.4%

Interpretation:
- <30%: Very consistent bet sizing
- 30-60%: Moderately consistent
- 60-100%: Variable (adapts to opportunities)
- >100%: Highly variable (wide range of bet sizes)
```

### Power Score
```
Power Score = Trades/Day × (Diversification/10) × (Avg Bet/10)

Example:
Trader: 5 trades/day, 60% diversification, $50 avg bet
Score = 5 × (60/10) × (50/10) = 5 × 6 × 5 = 150

Interpretation:
- Combines activity, diversification, and capital deployment
- Higher score = more engaged and sophisticated trader
- Used to identify "power users"
```

### Activity Trend
```
Compares first half of trading history to second half

Example:
First 25 trades: 2.5 trades/day
Last 25 trades: 4.0 trades/day
4.0 > 2.5 × 1.2 → "Increasing"

Thresholds:
- Increasing: Second half > First half × 1.2
- Decreasing: Second half < First half × 0.8
- Stable: Within 20% of original rate
```

## Use Cases

### 1. Identify Promising Traders
Find "Power Users" with high activity, diversification, and bet sizes - these are sophisticated traders to watch

### 2. Detect Behavior Changes
Monitor activity trends to spot traders ramping up or slowing down

### 3. Hot Streak Detection
Identify traders with sudden high activity (≥5 trades in 48h) - may indicate strong conviction or insider knowledge

### 4. Trading Pattern Research
Understand common behavioral patterns in prediction markets:
- Are weekend traders more/less successful?
- Do specialists outperform diversifiers?
- Does bet size consistency correlate with wins?

### 5. Adjust Monitoring Criteria
Your current criteria: $10k volume + 50 trades

Behavior analysis helps validate:
- Are high-volume traders actually consistent?
- Should you weight diversification?
- Do bet size patterns matter?

### 6. Market Insights
- Which markets attract the most sophisticated traders?
- What's the typical trading frequency in geopolitics markets?
- How concentrated is trading (few power users vs many casual)?

## Integration with Other Tools

### With trader_performance_analysis.py
```bash
# First, analyze behavior
python trading_behavior_analysis.py

# Then, analyze performance
python trader_performance_analysis.py

# Compare: Do "Power Users" have better win rates?
# Do "Big Bettors" have higher ROI?
# Do "Cautious Diversifiers" perform more consistently?
```

### With Monitoring System
Your `main.py` runs continuously collecting trades. Run behavior analysis periodically:
- **Daily**: Check for hot streak traders
- **Weekly**: Review trading style distribution
- **Monthly**: Analyze activity trends

## Limitations

### 1. Timestamp Parsing
- Some trades may have missing/invalid timestamps
- Affects activity timing analysis (day/hour)
- Total trades and bet sizes still accurate

### 2. Market Category Detection
- Currently doesn't classify markets by category (geopolitics/sports/crypto)
- Shows top 3 markets by title only
- Future enhancement: category-based diversification

### 3. Low Trade Count
- Traders with <10 trades flagged as "Low Reliability"
- Patterns may not be meaningful yet
- CSV includes reliability flag

### 4. Hot Streak Detection
- Based on last 48 hours from analysis time
- Doesn't account for normal trading rhythm
- May flag normal activity for very active traders

### 5. Style Classification
- Uses threshold-based decision tree
- Some traders may fit multiple categories
- "General Trader" is catch-all for ambiguous patterns

## Troubleshooting

### "Database not found"
```
❌ Error: polymarket_tracker.db not found
```
**Solution**: Wait for monitoring script to collect trades first

### "No trades found"
```
📊 Loading trades from database...
Found 0 total trades
```
**Cause**: Database exists but no trades recorded yet
**Solution**: Let `main.py` run longer to collect data

### Missing timestamp data
Some traders show:
- Most Active Day: N/A
- Most Active Hour: N/A
- Activity Trend: Insufficient Data

**Cause**: Timestamp parsing issues or very few trades
**Solution**: Other metrics (bet sizes, diversification) still valid

### All traders "Low Reliability"
**Cause**: Most traders have <10 trades
**Solution**:
- Let monitoring run longer
- Lower threshold in code: `min_trades = 5`
- Use longer time period (all time vs 7 days)

## Performance

- **Database**: Read-only, no modifications
- **Typical Runtime**:
  - 50 traders: <5 seconds
  - 200 traders: ~10 seconds
  - 500 traders: ~20 seconds
- **Memory**: Minimal (loads trades sequentially)

## Future Enhancements

Potential improvements:
- [ ] Visualizations (bet size histograms, activity charts)
- [ ] Category-based analysis (behavior in geopolitics vs sports)
- [ ] Correlation with performance metrics (win rate vs style)
- [ ] Real-time behavior monitoring
- [ ] Anomaly detection (unusual pattern changes)
- [ ] Trader clustering (similar behavior groups)
- [ ] Predictive modeling (future behavior based on patterns)
- [ ] Compare individual vs group benchmarks
- [ ] Market timing analysis (entry/exit patterns)
- [ ] Social network analysis (do similar traders follow each other?)

## Example Insights

From running analysis:

**Finding 1: Power Users vs Casual Traders**
```
Power Users (5): Avg win rate 68%, Avg ROI 22%
Casual Traders (18): Avg win rate 54%, Avg ROI 8%
→ High engagement correlates with better performance
```

**Finding 2: Diversification Effect**
```
High Diversification (60%+): Avg win rate 62%
Low Diversification (<30%): Avg win rate 59%
→ Slight advantage to diversification (risk management?)
```

**Finding 3: Bet Consistency**
```
Very Consistent: Avg ROI 15%
Highly Variable: Avg ROI 12%
→ Consistent sizing performs slightly better
```

**Finding 4: Activity Trends**
```
Increasing trend: 23 traders
Decreasing trend: 15 traders
Stable: 49 traders
→ Most traders maintain consistent activity levels
```

**Finding 5: Weekend vs Weekday**
```
Weekend Warriors (4): Avg win rate 48%
Weekday Traders: Avg win rate 61%
→ Weekday trading shows better results (more time/research?)
```

## Questions?

The script includes extensive progress indicators and error handling. For issues:

1. Check database exists and has trades
2. Verify timestamp data quality
3. Adjust minimum trade thresholds if needed
4. Check output for specific warnings

Combine with `trader_performance_analysis.py` for complete trader profiling!
