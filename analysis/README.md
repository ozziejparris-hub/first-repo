# Polymarket Analysis Tools

This directory contains analysis tools for examining trader behavior and performance on Polymarket.

## Available Tools

### 1. trader_performance_analysis.py
Analyzes actual trading performance based on market outcomes.

**What it does:**
- Calculates win rates from resolved markets
- Computes ROI (Return on Investment) with real P&L
- Ranks traders by performance metrics
- Identifies most profitable traders

**Usage:**
```bash
python trader_performance_analysis.py
```
Or from root:
```bash
python run_analysis.py  # Select option 1
```

**Requirements:**
- Database in `/data/polymarket_tracker.db`
- Markets that have resolved (may take days/weeks)
- Optional: POLYMARKET_API_KEY in `.env` for market resolution checks

**Output:**
- Console report with top performers
- CSV file in `/reports/` directory

📖 [Full Documentation](ANALYSIS_README.md)

---

### 2. trading_behavior_analysis.py
Analyzes trading patterns, habits, and behavioral characteristics.

**What it does:**
- Examines betting patterns (bet sizes, consistency)
- Calculates market diversification
- Tracks activity frequency and timing
- Classifies traders into 11 behavioral categories

**Usage:**
```bash
python trading_behavior_analysis.py
```
Or from root:
```bash
python run_analysis.py  # Select option 2
```

**Requirements:**
- Database in `/data/polymarket_tracker.db`
- Trade history data (works with any amount of data)

**Output:**
- Console report with leaderboards
- CSV file in `/reports/` directory

📖 [Full Documentation](BEHAVIOR_ANALYSIS_README.md)

---

## Testing & Demos

### test_analysis_demo.py
Interactive demonstration of performance analysis calculations.

**Shows:**
- P&L calculation examples
- Win rate and ROI formulas
- Sample trader rankings

**Usage:**
```bash
python test_analysis_demo.py
```
No database required - pure calculation demo.

---

### test_behavior_demo.py
Interactive demonstration of behavior analysis calculations.

**Shows:**
- Betting pattern calculations
- Diversification scoring
- Activity frequency metrics
- Trading style classification logic

**Usage:**
```bash
python test_behavior_demo.py
```
No database required - pure calculation demo.

---

### test_market_filtering.py
Tests the crypto/sports market exclusion logic.

**Tests:**
- Crypto market detection (Bitcoin, XRP, Ethereum)
- Sports market detection (NBA, NFL, Super Bowl)
- Elon Musk tweet markets
- Legitimate geopolitics markets

**Usage:**
```bash
python test_market_filtering.py
```

---

## Quick Start

### Step 1: Collect Data
Make sure the monitoring system is running:
```bash
# From root directory
python run_monitoring.py
# Or
python monitoring/main.py
```

### Step 2: Wait for Data
- **Behavior analysis**: Works immediately once trades are collected
- **Performance analysis**: Requires markets to resolve (days to weeks)

### Step 3: Run Analysis
```bash
# Interactive menu (recommended)
python ../run_analysis.py

# Or run specific tool directly
python trader_performance_analysis.py
python trading_behavior_analysis.py
```

### Step 4: Check Results
Reports are saved to `/reports/` directory with timestamps:
- `trader_performance_alltime_20251112.csv`
- `trading_behavior_alltime_20251112.csv`

---

## Time Period Options

Both analysis tools offer:
1. Last 7 days
2. Last 30 days
3. All time (default)
4. All periods (sequential)

---

## Output Directories

```
/
├── data/
│   └── polymarket_tracker.db      # Source database (read-only)
├── reports/
│   ├── trader_performance_*.csv   # Performance analysis results
│   └── trading_behavior_*.csv     # Behavior analysis results
└── analysis/
    ├── *.py                        # Analysis scripts (you are here)
    └── *.md                        # Documentation
```

---

## Troubleshooting

### "Database not found"
```
❌ Error: polymarket_tracker.db not found in /data/
```
**Solution:** Run the monitoring system first to collect trades

### "No resolved markets"
**Cause:** Markets haven't closed yet (normal for recent data)
**Solution:**
- Use behavior analysis instead (works without resolved markets)
- Wait for markets to resolve
- Check older data if available

### "No traders with enough trades"
**Cause:** Need more data collection time
**Solution:**
- Let monitoring run longer
- Use longer time period (all time vs 7 days)
- Lower minimum trade thresholds in code

---

## Documentation

- [ANALYSIS_README.md](ANALYSIS_README.md) - Performance Analysis Guide
- [BEHAVIOR_ANALYSIS_README.md](BEHAVIOR_ANALYSIS_README.md) - Behavior Analysis Guide
- [ANALYSIS_TOOLS_OVERVIEW.md](ANALYSIS_TOOLS_OVERVIEW.md) - Combined Overview

---

## Combined Workflow

1. **Run Monitoring** (collects data)
   ```bash
   python ../run_monitoring.py
   ```

2. **Analyze Behavior** (after ~500 trades collected)
   ```bash
   python trading_behavior_analysis.py
   ```
   Learn: Who are the power users? What are typical bet sizes?

3. **Analyze Performance** (after markets resolve)
   ```bash
   python trader_performance_analysis.py
   ```
   Learn: Who actually wins? What's the typical ROI?

4. **Cross-Reference** (compare both analyses)
   - Do "Power Users" have better win rates?
   - Are "Big Bettors" more profitable?
   - Does diversification improve ROI?

---

## Development

All analysis tools:
- ✅ Use read-only database access
- ✅ Safe to run while monitoring is active
- ✅ No external dependencies beyond standard library
- ✅ Export results to `/reports/` directory
- ✅ Include progress indicators
- ✅ Handle missing data gracefully

---

## Questions?

See the full documentation files for detailed information:
- Performance metrics and calculations
- Behavior classification logic
- CSV output formats
- API usage and limitations
- Example insights and findings

Happy analyzing! 📊
