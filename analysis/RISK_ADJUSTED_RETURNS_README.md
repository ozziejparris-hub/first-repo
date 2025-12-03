# Risk-Adjusted Returns Analysis

## Overview

The Risk-Adjusted Returns Analysis tool measures trader performance while accounting for the risk taken to achieve those returns. This is crucial for distinguishing skilled traders from lucky ones - a trader with modest returns and low volatility may actually be more skilled than one with higher returns but extreme risk-taking.

## What is Risk-Adjusted Performance?

**Key Concept**: Raw returns don't tell the whole story. Two traders might both make 50% returns, but if one achieves this with consistent 2% daily gains while the other has wild swings from -30% to +80%, they have very different skill levels and sustainability.

Risk-adjusted metrics normalize performance by volatility, drawdowns, and other risk factors to reveal true skill.

## Core Metrics

### 1. **Sharpe Ratio**

**Formula**: `(Average Return - Risk-Free Rate) / Standard Deviation of Returns`

**Meaning**: Return per unit of total risk (volatility).

**Interpretation**:
- **< 0.0**: Losing money, underperforming risk-free rate
- **0.0 - 1.0**: Positive but modest risk-adjusted returns
- **1.0 - 2.0**: Good risk-adjusted performance
- **2.0 - 3.0**: Excellent - consistent skilled trader
- **> 3.0**: Exceptional - elite performance (rare)

**Example**:
```
Trader A: 30% return, 15% volatility → Sharpe = 2.0 (Excellent)
Trader B: 30% return, 50% volatility → Sharpe = 0.6 (Modest)
```
Both made 30%, but Trader A did it much more consistently.

### 2. **Sortino Ratio**

**Formula**: `(Average Return - Risk-Free Rate) / Downside Deviation`

**Meaning**: Like Sharpe, but only penalizes downside volatility (losses). Upside volatility is good!

**Why it matters**: A trader with big wins and small losses has high upside volatility but low downside risk - Sortino captures this better than Sharpe.

**Interpretation**: Generally higher than Sharpe. A Sortino >> Sharpe indicates positive skew (asymmetric returns favoring wins).

### 3. **Calmar Ratio**

**Formula**: `Average Annual Return / Maximum Drawdown`

**Meaning**: Return per unit of worst-case loss.

**Interpretation**:
- **< 1.0**: Returns don't justify the drawdown risk
- **1.0 - 3.0**: Acceptable drawdown relative to returns
- **3.0 - 5.0**: Good - recovers well from losses
- **> 5.0**: Excellent - minimal drawdowns

**Example**:
```
Trader A: 40% return, 10% max drawdown → Calmar = 4.0 (Good)
Trader B: 40% return, 50% max drawdown → Calmar = 0.8 (Poor)
```

### 4. **Maximum Drawdown**

**Definition**: Largest peak-to-trough decline in portfolio value.

**Meaning**: "What's the worst that happened to this trader?"

**Interpretation**:
- **< 10%**: Excellent risk control
- **10% - 25%**: Good, manageable drawdowns
- **25% - 50%**: Significant risk, concerning
- **> 50%**: Extreme risk, potential blow-up

**Important**: Also track duration - a 30% drawdown lasting 2 days is very different from one lasting 6 months.

### 5. **Value at Risk (VaR)**

**Definition**: Maximum expected loss at a given confidence level.

**Variants**:
- **95% VaR**: "95% of the time, I won't lose more than this"
- **99% VaR**: "99% of the time, I won't lose more than this"

**Interpretation**: Risk budgeting tool. If 95% VaR = $100, expect to lose more than $100 in 1 out of 20 trades.

### 6. **Distribution Statistics**

#### Skewness
**Meaning**: Asymmetry of return distribution.

- **Negative skew** (< -0.5): More extreme losses than wins (bad)
- **Symmetric** (-0.5 to +0.5): Balanced distribution
- **Positive skew** (> +0.5): More extreme wins than losses (good)

#### Kurtosis
**Meaning**: Tail risk / extreme event frequency.

- **Negative kurtosis** (< -1.0): Thin tails, fewer extremes
- **Normal** (-1.0 to +1.0): Normal distribution-like
- **Positive kurtosis** (> +1.0): Fat tails, more extreme events

## Installation

Ensure dependencies are installed:

```bash
pip install -r requirements.txt
```

Required packages:
- pandas
- numpy
- matplotlib
- seaborn
- scipy

## Usage

### 1. Analyze a Specific Trader

```bash
python analysis/risk_adjusted_returns.py --trader 0x1234567890abcdef...
```

**Output**:
```
================================================================================
RISK-ADJUSTED RETURNS ANALYSIS: 0x1234...
================================================================================

Period: 2024-01-15 to 2024-12-03
Total Trades: 147
Resolved Markets: 89

📊 RETURNS:
  Total Return: $12,450.00 (+45.2%)
  Avg Return/Trade: $140.00 (+38.7%)
  Median Return: $95.50

📈 WIN/LOSS:
  Win Rate: 62.9%
  Wins: 56 | Losses: 33
  Avg Win: $425.50
  Avg Loss: $-285.00
  Win/Loss Ratio: 1.49x

⚡ RISK-ADJUSTED METRICS:
  Sharpe Ratio: 2.347 (Excellent ⭐)
  Sortino Ratio: 3.891
  Calmar Ratio: 4.520

🎲 RISK METRICS:
  Volatility: 19.3%
  Downside Volatility: 11.7%
  Max Drawdown: 10.0% (lasted 14 days)
    Period: 2024-08-15 to 2024-08-29
  Current Drawdown: 0.0%

📉 VALUE AT RISK:
  VaR (95%): $125.00 per trade
  VaR (99%): $210.00 per trade

📐 DISTRIBUTION STATS:
  Skewness: 0.843 (Right-skewed: more extreme wins)
  Kurtosis: 0.234 (Normal tail risk)
```

### 2. Compare All Traders

```bash
python analysis/risk_adjusted_returns.py --all
```

Ranks all traders by Sharpe ratio with key metrics.

### 3. Top N Traders

```bash
python analysis/risk_adjusted_returns.py --top 20
```

Show top 20 traders by risk-adjusted performance.

### 4. Time Window Analysis

```bash
# Last 30 days
python analysis/risk_adjusted_returns.py --trader 0xABC... --window 30

# Last 90 days
python analysis/risk_adjusted_returns.py --trader 0xABC... --window 90

# Last 180 days
python analysis/risk_adjusted_returns.py --trader 0xABC... --window 180
```

Analyze performance over specific time windows to detect recent changes in skill/strategy.

### 5. Generate Report with Visualizations

```bash
python analysis/risk_adjusted_returns.py --report --visualize
```

Creates comprehensive report file and generates 4 visualization types.

## Visualizations

### 1. Equity Curve with Drawdown

**Two-panel chart**:
- Top: Cumulative portfolio value over time
- Bottom: Drawdown percentage (distance from peak)

**Use**: Visualize growth trajectory and identify difficult periods.

![Equity Curve Example](equity_curve_example.png)

### 2. Return Distribution

**Histogram** of per-trade returns with:
- Normal distribution overlay
- 95% and 99% VaR markers
- Mean and median lines

**Use**: Understand return profile and tail risks.

### 3. Risk-Return Scatter

**Scatter plot** of all traders:
- X-axis: Volatility (risk)
- Y-axis: Average return
- Color: Sharpe ratio (blue = low, red = high)
- Size: Number of trades

**Use**: Compare traders and identify efficient vs inefficient performers.

### 4. Top Traders Bar Chart

**Horizontal bar chart** of top N traders by Sharpe ratio with:
- Bar length: Sharpe ratio
- Bar color: Gradient by rank

**Use**: Quick visual ranking of best risk-adjusted performers.

## Interpretation Guide

### Identifying Skilled Traders

✅ **Signs of Skill**:
- Sharpe ratio > 1.5
- Positive skewness (bigger wins than losses)
- Low maximum drawdown (< 20%)
- High Calmar ratio (> 3.0)
- Consistent returns over time
- Win rate > 55% with positive win/loss ratio

⚠️ **Red Flags**:
- High returns with extreme volatility (low Sharpe)
- Large maximum drawdowns (> 40%)
- Negative skewness (lottery ticket strategy)
- High kurtosis (frequent extreme events)
- Recent performance degradation

### Comparing Traders

**Scenario 1: Conservative vs Aggressive**

| Metric | Conservative | Aggressive |
|--------|-------------|------------|
| Total Return | 25% | 60% |
| Sharpe Ratio | 2.5 | 0.8 |
| Max Drawdown | 8% | 45% |
| **Verdict** | More skilled | Lucky/risky |

**Scenario 2: Consistency vs Volatility**

| Metric | Consistent | Volatile |
|--------|-----------|----------|
| Win Rate | 65% | 48% |
| Volatility | 12% | 38% |
| Sortino Ratio | 3.2 | 1.1 |
| **Verdict** | Superior | Unsustainable |

### Statistical Reliability

**Minimum Sample Sizes**:
- **20+ trades**: Minimum for basic analysis
- **50+ trades**: Reliable Sharpe/Sortino ratios
- **100+ trades**: Robust distribution statistics
- **200+ trades**: High confidence in all metrics

**Warning**: Small sample sizes can give misleading results. A trader with 10 trades and 2.5 Sharpe may just be lucky.

## Technical Details

### Return Calculation

```python
# For each trade:
capital_invested = shares * price

# If won:
profit = shares * 1.0 - capital  # $1 payout per share

# If lost:
profit = -capital  # Lost entire investment

# Return percentage:
return_pct = (profit / capital) * 100
```

### Sharpe Calculation

```python
returns = [r1, r2, r3, ...]  # List of return percentages
avg_return = mean(returns)
std_return = std_dev(returns)
sharpe = avg_return / std_return
```

Assumes risk-free rate = 0 (can be customized).

### Maximum Drawdown Calculation

```python
# Build equity curve
equity = [initial_capital]
for trade in trades:
    new_value = equity[-1] * (1 + return_pct / 100)
    equity.append(new_value)

# Find max drawdown
peak = equity[0]
max_dd = 0
for value in equity:
    if value > peak:
        peak = value
    dd = (peak - value) / peak
    max_dd = max(max_dd, dd)

max_drawdown_pct = max_dd * 100
```

### Value at Risk (VaR)

Two methods implemented:

**Historical VaR** (95%):
```python
returns_sorted = sorted(returns)
var_95 = returns_sorted[int(len(returns) * 0.05)]
```

**Parametric VaR** (assumes normal distribution):
```python
var_95 = mean(returns) - 1.645 * std_dev(returns)
var_99 = mean(returns) - 2.326 * std_dev(returns)
```

Tool uses historical VaR as it doesn't assume normality.

## Use Cases

### 1. Trader Performance Review

**Question**: "How good is my trading strategy?"

**Analysis**:
```bash
python analysis/risk_adjusted_returns.py --trader 0xMYADDRESS --report --visualize
```

**Look for**:
- Sharpe > 1.5 → Good strategy
- Max drawdown < 25% → Acceptable risk
- Positive skewness → Good asymmetry
- Upward sloping equity curve → Consistent growth

### 2. Portfolio Construction

**Question**: "Which traders should I allocate capital to?"

**Analysis**:
```bash
python analysis/risk_adjusted_returns.py --top 50
```

**Selection criteria**:
- High Sharpe ratio (> 1.5)
- Low correlation between traders (manual check)
- Minimum 50 trades each
- Recent performance stable (check with --window 90)

### 3. Strategy Degradation Detection

**Question**: "Is my strategy still working?"

**Analysis**:
```bash
# Compare full history vs recent
python analysis/risk_adjusted_returns.py --trader 0xADDR
python analysis/risk_adjusted_returns.py --trader 0xADDR --window 90
```

**Red flags**:
- Sharpe dropping significantly in recent window
- Increasing max drawdown
- Decreasing win rate
- Strategy may need adjustment

### 4. Risk Budgeting

**Question**: "What's my downside risk?"

**Analysis**: Check VaR metrics

**Application**:
- 95% VaR = $150 → Size positions so worst 5% outcomes are acceptable
- Max drawdown = 30% → Ensure capital can withstand this loss
- Plan position sizing and stop-losses accordingly

### 5. Benchmarking

**Question**: "Am I above/below average?"

**Analysis**:
```bash
python analysis/risk_adjusted_returns.py --all
```

**Compare your metrics**:
- Your Sharpe vs median Sharpe
- Your max DD vs median max DD
- Your percentile ranking

## Comparison to Other Analysis Tools

### vs Regret Analysis

| Risk-Adjusted Returns | Regret Analysis |
|----------------------|-----------------|
| **Focus**: Risk management | **Focus**: Decision optimality |
| **Metric**: Sharpe, Sortino | **Metric**: Optimal vs actual returns |
| **Question**: "How consistent?" | **Question**: "How optimal?" |
| **Use**: Risk budgeting | **Use**: Strategy improvement |

**Use together**: A trader can have high regret (suboptimal timing) but good risk-adjusted returns (consistent execution). Both insights are valuable.

### vs Calibration Analysis

| Risk-Adjusted Returns | Calibration Analysis |
|----------------------|---------------------|
| **Focus**: Return profile | **Focus**: Probability assessment |
| **Metric**: Sharpe, drawdowns | **Metric**: Brier score, ECE |
| **Question**: "How risky?" | **Question**: "How accurate?" |
| **Use**: Performance eval | **Use**: Forecasting quality |

**Use together**: A well-calibrated trader (accurate probabilities) should also have good risk-adjusted returns (profitable execution). Calibration feeds into risk management.

## Troubleshooting

### Issue: "Insufficient trades for analysis"

**Cause**: Trader has fewer than 20 trades in resolved markets.

**Solution**: Wait for more market resolutions or use a longer time window.

### Issue: "No resolved markets available"

**Cause**: Database has no markets with known outcomes yet.

**Solution**: Ensure your monitoring system is tracking market resolutions. Check `markets` table for `resolved = 1` entries.

### Issue: Sharpe ratio is 0.0

**Cause**: All returns are identical (zero variance).

**Solution**: This is rare but can happen with very few trades. Need more data.

### Issue: Sortino ratio shows 0.0 or 999.0

**Cause**:
- **0.0**: No positive returns to evaluate
- **999.0**: No downside volatility (all trades won)

**Solution**: These are edge cases with small samples. Ignore if < 20 trades.

### Issue: Max drawdown shows 100%

**Cause**: Trader lost entire capital at some point (went to zero).

**Solution**: This is accurate but indicates extreme risk. Use with caution.

### Issue: Warnings about non-interactive backend

**Cause**: Matplotlib in non-GUI environment.

**Solution**: Plots are still saved correctly. This warning is cosmetic and can be ignored.

## Advanced Features

### Custom Time Windows

Specify any number of days:

```bash
python analysis/risk_adjusted_returns.py --trader 0xABC --window 45
```

Useful for:
- Quarterly reviews (90 days)
- Monthly reviews (30 days)
- Custom strategy testing periods

### Rolling Analysis (Future Enhancement)

Not yet implemented, but planned:

```bash
# 90-day rolling Sharpe ratio over time
python analysis/risk_adjusted_returns.py --trader 0xABC --rolling 90
```

Would show how risk-adjusted performance evolves over time.

### Multi-Trader Comparison (Current)

Already available via `--all` flag. Creates DataFrame with all traders for advanced analysis:

```python
from analysis.risk_adjusted_returns import RiskAdjustedAnalyzer

with RiskAdjustedAnalyzer() as analyzer:
    df = analyzer.compare_all_traders()

    # Custom filtering
    elite_traders = df[df['sharpe_ratio'] > 2.0]

    # Custom sorting
    by_calmar = df.sort_values('calmar_ratio', ascending=False)
```

## Benchmark Guidelines

### Sharpe Ratio Benchmarks

Based on quantitative finance standards:

| Sharpe | Rating | Interpretation |
|--------|--------|---------------|
| < 0.0 | Poor | Losing money |
| 0.0 - 0.5 | Below Avg | Barely profitable |
| 0.5 - 1.0 | Average | Modest returns for risk |
| 1.0 - 1.5 | Good | Solid performance |
| 1.5 - 2.0 | Very Good | Strong skill |
| 2.0 - 3.0 | Excellent | Elite trader |
| > 3.0 | Exceptional | Top 1% (verify sample size) |

**Context**:
- Hedge funds: Sharpe 1.0-1.5 considered good
- Top quant funds: Sharpe 2.0-3.0
- Renaissance Medallion: ~3.0-7.0 (legendary)

### Maximum Drawdown Benchmarks

| Max DD | Rating | Risk Level |
|--------|--------|-----------|
| < 5% | Excellent | Very low risk |
| 5% - 10% | Good | Low risk |
| 10% - 20% | Acceptable | Moderate risk |
| 20% - 30% | Concerning | High risk |
| 30% - 50% | Poor | Very high risk |
| > 50% | Unacceptable | Extreme risk |

**Recovery time matters**: A 50% loss requires 100% gain to recover!

### Win Rate Benchmarks

**Important**: Win rate alone is meaningless without win/loss ratio.

| Win Rate | Win/Loss Ratio | Verdict |
|----------|---------------|---------|
| 40% | 3.0x | Profitable (rare big wins) |
| 50% | 1.5x | Profitable |
| 60% | 1.0x | Barely break-even |
| 70% | 0.5x | Losing (small wins, big losses) |

**Ideal**: High win rate (> 55%) AND positive win/loss ratio (> 1.2x)

## File Output

### Report File Format

When using `--report --output report.txt`:

```
================================================================================
RISK-ADJUSTED RETURNS ANALYSIS REPORT
Generated: 2024-12-03 14:30:00
================================================================================

SUMMARY STATISTICS (All Traders):
  Total Traders Analyzed: 156
  Median Sharpe Ratio: 0.85
  Median Max Drawdown: 18.3%
  Median Win Rate: 54.2%

TOP 10 TRADERS BY SHARPE RATIO:
  1. 0xABCD1234... - Sharpe: 2.847, Return: +65.2%, Trades: 89
  2. 0xEFGH5678... - Sharpe: 2.531, Return: +52.1%, Trades: 124
  ...

[Individual trader details follow...]
```

### Visualization Files

Saved to current directory or `--output` path:

- `equity_curve_{address}.png` - Equity curve with drawdown
- `return_dist_{address}.png` - Return distribution histogram
- `risk_return_scatter.png` - All traders scatter plot
- `top_traders.png` - Top N traders bar chart

## Integration with Existing System

This tool integrates with your Polymarket tracker database:

**Required tables**:
- `markets`: Must have `resolved = 1` and `winning_outcome` set
- `trades`: All trader transactions
- `traders`: Trader summaries (auto-populated)

**JOIN compatibility**: Uses `condition_id` for market-trade joins (already fixed in previous sessions).

## Next Steps

After running this analysis:

1. **Identify top performers**: Use `--top 20` to find skilled traders
2. **Understand risk profiles**: Review max drawdowns and VaR
3. **Check calibration**: Run calibration analysis on same traders
4. **Review regret**: Check if top Sharpe traders also have low regret
5. **Monitor over time**: Re-run analysis monthly to detect degradation

## Support

For issues or questions:
- Check troubleshooting section above
- Review test suite: `python analysis/test_risk_adjusted_returns.py`
- Check logs for detailed error messages

---

**Related Documentation**:
- [Regret Analysis README](REGRET_ANALYSIS_README.md)
- [Calibration Analysis README](CALIBRATION_ANALYSIS_README.md)
