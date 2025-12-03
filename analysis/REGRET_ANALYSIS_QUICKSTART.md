# Regret Analysis - Quick Start Guide

## What is Regret Analysis?

**Regret** measures how much money a trader left on the table compared to perfect decision-making with hindsight.

```
Regret = Optimal Return - Actual Return

Lower Regret = Better Trader
```

## Installation

```bash
# Install required packages
pip install pandas numpy matplotlib seaborn

# Or install all project dependencies
pip install -r requirements.txt
```

## Quick Commands

### Analyze One Trader
```bash
python analysis/regret_analysis.py --trader 0x1234...
```

### Analyze All Traders
```bash
python analysis/regret_analysis.py --all
```

### Generate Full Report
```bash
python analysis/regret_analysis.py --report --visualize
```

### Custom Output Location
```bash
python analysis/regret_analysis.py --report --output reports/my_report.txt
```

## Understanding the Output

### Key Metrics

| Metric | What It Means | Good Value |
|--------|---------------|------------|
| **Total Regret** | $ left on table | Lower is better |
| **Regret Rate** | % of optimal missed | < 30% is good |
| **Actual Return** | Real profit/loss | Higher is better |
| **Optimal Return** | Max possible profit | Comparison baseline |
| **Win Rate** | % winning trades | > 60% is good |

### Performance Ratings

| Regret Rate | Rating | Meaning |
|-------------|--------|---------|
| 0-20% | ⭐⭐⭐⭐⭐ EXCELLENT | Near-perfect |
| 20-40% | ⭐⭐⭐⭐ GOOD | Above average |
| 40-60% | ⭐⭐⭐ AVERAGE | Room to improve |
| 60-80% | ⭐⭐ BELOW AVERAGE | Significant regret |
| 80%+ | ⭐ POOR | Major opportunity cost |

## Example Output

```
📊 PERFORMANCE SUMMARY:
  Resolved Markets: 15
  Total Trades: 47
  Total Invested: $12,500

💰 RETURNS:
  Actual Return: $2,450 (ROI: 19.6%)
  Optimal Return: $3,800 (ROI: 30.4%)

😔 REGRET METRICS:
  Total Regret: $1,350
  Regret Rate: 35.5%
  Rating: GOOD ⭐⭐⭐⭐

🏆 RANKING:
  #23 out of 149 traders
```

## Visualizations Generated

1. **Regret Distribution** - How traders compare overall
2. **Actual vs Optimal** - Performance scatter plot
3. **Top Traders** - Best performers by lowest regret
4. **Regret Rate Distribution** - Percentage comparison

All saved to `analysis/output/` directory.

## Test with Mock Data

```bash
# Run test to verify everything works
python analysis/test_regret_analysis.py
```

## Troubleshooting

### "No resolved markets found"
➜ **Wait for markets to resolve**. Monitoring system needs time to collect outcomes.

### "No module named 'pandas'"
➜ **Run**: `pip install pandas numpy matplotlib seaborn`

### "Trader has no trades in resolved markets"
➜ **Check**: Trader address is correct and they traded in resolved markets.

## Use Cases

### 🔍 Find Best Traders
```bash
python analysis/regret_analysis.py --all --report
# Look at top 10 in report output
```

### 📊 Track Your Performance
```bash
python analysis/regret_analysis.py --trader YOUR_ADDRESS
```

### 📈 Weekly Reports
```bash
python analysis/regret_analysis.py --all --report --visualize
```

### 🎯 Copy Trading Research
```bash
python analysis/regret_analysis.py --all --visualize
# Check actual_vs_optimal.png for best performers
```

## What Causes High Regret?

❌ Poor timing (buying at bad prices)
❌ Wrong predictions (backing losers)
❌ Overcaution (too small positions)
❌ Inconsistency (mixing good and bad bets)

## What Causes Low Regret?

✅ Good entry points
✅ Correct predictions
✅ Optimal position sizing
✅ Consistent discipline

## Important Notes

- **Requires resolved markets** - Can't analyze active markets
- **Sample size matters** - More markets = more reliable
- **Perfect information bias** - Optimal assumes best prices were available
- **Read-only** - Doesn't modify your database
- **No fees included** - Doesn't account for transaction costs

## Next Steps

1. ✅ Install dependencies
2. ✅ Run test script
3. ⏳ Wait for markets to resolve
4. 📊 Run first analysis
5. 🔄 Schedule regular reports

## More Information

- Full documentation: `REGRET_ANALYSIS_README.md`
- Test examples: `test_regret_analysis.py`
- Main script: `regret_analysis.py`

---

**Ready to analyze?** Run `python analysis/regret_analysis.py --help` for all options.
