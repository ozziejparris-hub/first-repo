# Regret Analysis Tool for Polymarket Traders

## Overview

The Regret Analysis Tool implements game theory concepts to measure trader performance by comparing actual returns against optimal returns with perfect hindsight.

**Regret = (Best possible return) - (Actual return)**

- **Low regret** = Near-optimal decision-making
- **High regret** = Money left on the table

## Concept

In game theory, "regret" quantifies how much better a player could have performed with perfect information. For Polymarket traders:

1. **Optimal Return**: The maximum profit possible by always betting on the eventual winner at the best available price
2. **Actual Return**: The profit/loss from the trader's actual decisions
3. **Regret**: The difference between these two values

This metric reveals not just whether a trader is profitable, but how efficiently they're capturing available opportunities.

## Installation

The tool requires additional Python packages for data analysis and visualization:

```bash
pip install pandas numpy matplotlib seaborn
```

Or install all project dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Commands

**Analyze a specific trader:**
```bash
python analysis/regret_analysis.py --trader 0x1234567890abcdef...
```

**Analyze all traders:**
```bash
python analysis/regret_analysis.py --all
```

**Generate comprehensive report:**
```bash
python analysis/regret_analysis.py --report
```

**Generate visualizations:**
```bash
python analysis/regret_analysis.py --all --visualize
```

**Combine options:**
```bash
python analysis/regret_analysis.py --all --report --visualize --output reports/regret_report.txt
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--trader ADDRESS` | Analyze a specific trader address |
| `--all` | Analyze all traders in database |
| `--report` | Generate comprehensive summary report |
| `--visualize` | Create visualization plots (saved to analysis/output/) |
| `--output PATH` | Custom path for text report (default: analysis/output/regret_report.txt) |
| `--db PATH` | Custom database path (default: data/polymarket_tracker.db) |

## Output Metrics

### Per-Trader Metrics

Each trader analysis includes:

1. **Resolved Markets Participated**: Number of markets with known outcomes
2. **Total Trades**: Count of all trades in resolved markets
3. **Total Invested**: Total capital deployed
4. **Actual Total Return**: Profit/loss from actual trades
5. **Optimal Total Return**: Maximum possible profit with perfect foresight
6. **Total Regret**: Dollar amount left on the table
7. **Average Regret per Trade**: Regret divided by number of trades
8. **Regret Rate**: Regret as percentage of optimal return
9. **Win Rate**: Percentage of profitable trades
10. **Rank**: Position among all analyzed traders

### Example Output

```
================================================================================
REGRET ANALYSIS FOR TRADER: 0x1234567890abcdef...
================================================================================

📊 PERFORMANCE SUMMARY:
  Resolved Markets Participated: 15
  Total Trades: 47
  Total Invested: $12,500.00

💰 RETURNS:
  Actual Total Return: $2,450.00
  Optimal Total Return: $3,800.00
  Actual ROI: 19.60%
  Optimal ROI: 30.40%

😔 REGRET METRICS:
  Total Regret: $1,350.00
  Average Regret per Trade: $28.72
  Regret Rate: 35.5%

🎯 WIN/LOSS RECORD:
  Winning Trades: 29
  Losing Trades: 18
  Win Rate: 61.7%

📈 INTERPRETATION:
  This trader left 35.5% of potential profits on the table.
  Performance Rating: GOOD - Above average performance

🏆 RANKING:
  Rank: #23 out of 149 traders
  (Lower regret is better)
```

## Visualizations

When using `--visualize`, the tool generates four plots:

### 1. Regret Distribution
Histogram showing the distribution of total regret across all traders.
- **X-axis**: Total regret ($)
- **Y-axis**: Number of traders
- **Red line**: Median regret

### 2. Actual vs Optimal Returns
Scatter plot comparing actual returns against optimal returns.
- **X-axis**: Optimal return ($)
- **Y-axis**: Actual return ($)
- **Diagonal line**: Perfect performance (0% regret)
- **Color**: Regret rate (%)

### 3. Top Traders by Lowest Regret
Horizontal bar chart showing the top 20 traders with the lowest regret.
- Best performers appear at the top
- Lower values = better performance

### 4. Regret Rate Distribution
Histogram showing the distribution of regret rates (%).
- **X-axis**: Regret rate (%)
- **Y-axis**: Number of traders
- **Red line**: Median regret rate

All plots are saved to `analysis/output/` directory as PNG files (300 DPI).

## Interpretation Guide

### Regret Rate Categories

| Regret Rate | Performance | Interpretation |
|-------------|-------------|----------------|
| < 20% | **EXCELLENT** | Near-optimal decision making |
| 20-40% | **GOOD** | Above average performance |
| 40-60% | **AVERAGE** | Moderate room for improvement |
| 60-80% | **BELOW AVERAGE** | Significant regret |
| > 80% | **POOR** | Substantial opportunity cost |

### What Causes High Regret?

1. **Poor Timing**: Entering positions at suboptimal prices
2. **Wrong Side**: Betting against eventual winners
3. **Overcaution**: Not sizing positions appropriately
4. **Inconsistency**: Mixing good and bad decisions

### What Indicates Low Regret?

1. **Good Entry Points**: Buying at favorable prices
2. **Correct Predictions**: Consistently backing winners
3. **Optimal Sizing**: Allocating capital efficiently
4. **Discipline**: Making rational, consistent decisions

## Technical Details

### How Optimal Return is Calculated

For each resolved market:

1. **Identify the winning outcome** (from market resolution)
2. **Find the best price** at which the winning outcome traded
3. **Calculate theoretical maximum profit**:
   ```
   Shares = Capital / Best_Price
   Payout = Shares × $1 (each winning share pays $1)
   Optimal_Profit = Payout - Capital
   ```
4. **Use trader's actual capital** invested in that market
5. **Respect timing constraints**: Only consider prices before trader's last trade

### How Actual Return is Calculated

For each trader's trades in a market:

1. **Track net positions**: Account for both BUYs and SELLs
2. **Calculate total cost**: Sum of all buy costs minus sell proceeds
3. **Determine payout**: Winning outcome shares × $1
4. **Calculate profit**: Payout - Total Cost

### Database Requirements

The tool requires:

1. **Resolved markets**: Markets with `resolved = 1` and a known `winning_outcome`
2. **Trade records**: Trader transactions with prices, shares, outcomes, and timestamps
3. **Market information**: Market IDs, titles, and resolution dates

## Data Requirements

### Minimum Data for Analysis

- At least **1 resolved market** in the database
- Traders must have **trades in resolved markets**
- Trade records must include:
  - Trader address
  - Market ID
  - Outcome (Yes/No)
  - Shares
  - Price
  - Side (BUY/SELL)
  - Timestamp

### When to Run Analysis

**Optimal times:**
- After markets resolve (wait for resolution data)
- Weekly or monthly for performance tracking
- Before making investment decisions (to identify best traders)

**Not useful when:**
- No markets have resolved yet
- Insufficient trade history
- All markets are still active

## Use Cases

### 1. Identifying Top Performers

Run `--all --report` to rank all traders by regret:

```bash
python analysis/regret_analysis.py --all --report
```

Traders with lowest regret are making the best decisions relative to available information.

### 2. Self-Assessment

Track your own performance:

```bash
python analysis/regret_analysis.py --trader YOUR_ADDRESS
```

Use regret metrics to identify areas for improvement.

### 3. Copy Trading Candidates

Find traders worth following:

```bash
python analysis/regret_analysis.py --all --visualize
```

Look for:
- Low regret rate (< 30%)
- High number of resolved markets (sample size)
- Consistent performance over time

### 4. Research and Analysis

Generate comprehensive reports for research:

```bash
python analysis/regret_analysis.py --report --output research/regret_study_$(date +%Y%m%d).txt
```

### 5. Monitoring System Integration

Incorporate into automated reporting:

```bash
# Weekly report generation
python analysis/regret_analysis.py --all --report --visualize --output reports/weekly_regret_$(date +%Y%m%d).txt
```

## Limitations

1. **Requires resolved markets**: Can't analyze active markets
2. **Hindsight bias**: Optimal return assumes perfect information
3. **Market liquidity**: Assumes best prices were actually available
4. **Transaction costs**: Does not account for fees or gas costs
5. **Timing constraints**: Only considers prices before trader's last trade
6. **Sample size**: More resolved markets = more reliable metrics

## Future Enhancements

Potential improvements:

- [ ] Regret over time charts (temporal analysis)
- [ ] Category-specific regret (e.g., politics vs sports)
- [ ] Comparison against market consensus
- [ ] Adjustment for market volatility
- [ ] Transaction cost incorporation
- [ ] Liquidity-adjusted optimal returns
- [ ] Multi-market portfolio regret
- [ ] Real-time regret monitoring dashboard

## Integration with Monitoring System

The regret analysis tool reads from the same database as the monitoring system:

```
monitoring/          # Collects trades and resolutions
    ├── main.py
    └── database.py

data/
    └── polymarket_tracker.db  # Shared database

analysis/           # Analyzes collected data
    ├── regret_analysis.py
    └── output/     # Generated reports and plots
```

**No conflicts**: Analysis is read-only and doesn't modify monitoring data.

## Troubleshooting

### "No resolved markets found"

**Solution**: Wait for markets to resolve. The monitoring system needs time to track market outcomes.

### "No data found for trader"

**Possible causes:**
- Trader has no trades in resolved markets
- Incorrect trader address
- Database not synced

**Solution**: Verify trader address and ensure monitoring system is running.

### "Import error: No module named 'pandas'"

**Solution**: Install analysis dependencies:
```bash
pip install pandas numpy matplotlib seaborn
```

### Visualization doesn't show

**Possible causes:**
- No display available (SSH session)
- Missing matplotlib backend

**Solution**: Plots are saved to `analysis/output/` even if display fails.

## Contributing

To add new features:

1. Add methods to `RegretAnalyzer` class for new metrics
2. Update `RegretMetrics` dataclass for new fields
3. Add visualization methods to `RegretVisualizer` class
4. Update CLI arguments in `main()` function

## References

- **Game Theory**: Von Neumann & Morgenstern, "Theory of Games and Economic Behavior"
- **Regret Minimization**: Savage, "The Foundations of Statistics"
- **Market Making**: Hanson, "Combinatorial Information Market Design"

## Contact & Support

For issues or questions:
- Check the main project README
- Review monitoring system documentation
- Verify database schema compatibility

---

**Last Updated**: December 2025
**Version**: 1.0.0
