# Calibration Analysis Tool - Comprehensive Guide

## Overview

The Calibration Analysis Tool measures how accurately traders' probability estimates match reality. This is a fundamental metric in forecasting quality that goes beyond simple win/loss records.

**Key Question**: When a trader bets at 70% confidence, do they actually win ~70% of the time?

## Core Concepts

### What is Calibration?

**Calibration** measures the alignment between predicted probabilities and actual outcomes:
- **Perfect calibration**: Predicted probabilities exactly match actual win rates
- **Over-confident**: Predicting higher probabilities than warranted (e.g., betting 80% but winning 60%)
- **Under-confident**: Predicting lower probabilities than warranted (e.g., betting 60% but winning 80%)

### Brier Score

The **Brier Score** is the gold standard for measuring forecasting accuracy:

```
Brier Score = (1/N) × Σ(predicted_probability - actual_outcome)²
```

- **Range**: 0 (perfect) to 2 (worst possible)
- **0.25**: Baseline for random predictions
- **< 0.15**: Excellent (top-tier forecasters)
- **< 0.25**: Good (reliable predictions)
- **> 0.25**: Needs improvement

### Expected Calibration Error (ECE)

ECE measures average deviation from perfect calibration:

```
ECE = Σ |predicted - actual| × (count / total)
```

Lower ECE means better calibration across all probability ranges.

## Installation

The tool uses the same dependencies as the regret analysis tool:

```bash
# Already installed if you ran regret analysis
pip install pandas numpy matplotlib seaborn scipy
```

Or:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Commands

**Analyze a specific trader:**
```bash
python analysis/calibration_analysis.py --trader 0x1234567890abcdef...
```

**Analyze all traders:**
```bash
python analysis/calibration_analysis.py --all
```

**Generate comprehensive report:**
```bash
python analysis/calibration_analysis.py --report
```

**Show top 20 best-calibrated traders:**
```bash
python analysis/calibration_analysis.py --top 20
```

**Full analysis with visualizations:**
```bash
python analysis/calibration_analysis.py --all --visualize
```

### Command-Line Options

| Option | Description |
|--------|-------------|
| `--trader ADDRESS` | Analyze a specific trader |
| `--all` | Analyze all traders |
| `--report` | Generate comprehensive comparison report |
| `--visualize` | Create and save visualization plots |
| `--top N` | Show top N best-calibrated traders |
| `--output PATH` | Custom path for report (default: analysis/output/calibration_report.txt) |
| `--db PATH` | Custom database path (default: data/polymarket_tracker.db) |

## Output Metrics

### Per-Trader Metrics

1. **Brier Score**: Overall forecasting accuracy (0-2, lower is better)
2. **Expected Calibration Error (ECE)**: Average calibration deviation
3. **Maximum Calibration Error (MCE)**: Worst calibration bucket
4. **Confidence Bias**: Over/under-confidence percentage
5. **Average Predicted Probability**: Mean of all predictions
6. **Actual Win Rate**: Percentage of correct predictions
7. **Calibration Curve**: Predicted vs actual by probability bucket
8. **Category-Specific Scores**: Brier score per market category

### Example Output

```
================================================================================
CALIBRATION ANALYSIS FOR TRADER: 0x1234...
================================================================================

📊 PREDICTION SUMMARY:
  Resolved Markets Participated: 48
  Total Predictions Analyzed: 156

🎯 BRIER SCORE: 0.187 (Good - below 0.25 threshold)
  Rank: #12 out of 149 traders (lower is better)

📈 CALIBRATION QUALITY:
  Expected Calibration Error (ECE): 0.043
  Maximum Calibration Error (MCE): 0.089

🧠 CONFIDENCE BIAS: Slightly Over-Confident
  Predicted probability: 67.2% (average)
  Actual win rate: 63.5%
  Confidence bias: +3.7% (predicting too high)

📊 CALIBRATION BY PROBABILITY BUCKET:
Bucket    Predicted  Actual   Count  Error      Status
----------------------------------------------------------------------
50-60%      55.2%    52.8%     23    2.4%      ✓ Good
60-70%      65.1%    61.3%     42    3.8%      ✓ Good
70-80%      74.8%    66.2%     31    8.6%      ⚠ Over-confident
80-90%      84.3%    78.1%     18    6.2%      ⚠ Over-confident
90-100%     94.2%    88.9%      9    5.3%      ⚠ Over-confident

💡 INTERPRETATION:
  This trader is generally well-calibrated but tends to be over-confident
  in high-probability predictions (70%+). Consider reducing confidence in
  "sure thing" bets.

🏆 CALIBRATION BY CATEGORY:
  Geopolitics          Brier = 0.164 (Excellent) ✓
  Crypto               Brier = 0.201 (Good) ✓
  Economics            Brier = 0.245 (Fair) ⚠

  💡 RECOMMENDATION: Focus on Geopolitics markets where calibration is strongest.
```

## Visualizations

The tool generates four types of plots when using `--visualize`:

### 1. Calibration Curve (Reliability Diagram)

The most important visualization for understanding calibration:

- **Perfect calibration**: Points lie on the diagonal line
- **Over-confident**: Points below the diagonal
- **Under-confident**: Points above the diagonal
- **Point size**: Number of predictions in that bucket
- **Error bars**: 95% confidence intervals

**Interpretation:**
- Close to diagonal = well-calibrated
- Systematic deviation = bias
- Large error bars = insufficient data

### 2. Brier Score Distribution

Histogram showing Brier scores across all traders:

- **Green region**: Excellent (< 0.15)
- **Yellow region**: Good (0.15-0.25)
- **Red region**: Needs improvement (> 0.25)
- **Your position**: Shows where target trader falls

### 3. Confidence Bias Scatter

2D plot of predicted probability vs actual win rate:

- **Diagonal line**: Perfect calibration
- **Above diagonal**: Under-confident
- **Below diagonal**: Over-confident
- **Point size**: Number of predictions
- **Color**: Confidence bias magnitude

### 4. Top Traders Chart

Horizontal bar chart of best-calibrated traders:

- Sorted by Brier score (lowest/best first)
- Color-coded by performance tier
- Shows value labels for exact scores

All plots are saved to `analysis/output/` at 300 DPI for publication quality.

## How Calibration is Calculated

### Step 1: Extract Implied Probabilities

For each trade:
```python
if outcome == 'Yes':
    predicted_probability = price
    actual_outcome = 1 if market_winner == 'Yes' else 0
else:  # No
    predicted_probability = 1 - price
    actual_outcome = 1 if market_winner == 'No' else 0
```

**Example:**
- Bought YES at $0.65 → predicted probability = 0.65 (65%)
- Bought NO at $0.35 → predicted probability = 0.65 (65%)

### Step 2: Calculate Brier Score

```python
brier_score = mean([(pred - actual)² for pred, actual in predictions])
```

**Example:**
- Prediction: 0.65, Actual: 1 (won) → Error² = (0.65-1)² = 0.1225
- Prediction: 0.65, Actual: 0 (lost) → Error² = (0.65-0)² = 0.4225
- Average = (0.1225 + 0.4225) / 2 = 0.2725

### Step 3: Create Calibration Curve

1. Bin predictions into buckets (0-10%, 10-20%, ..., 90-100%)
2. For each bucket:
   - Calculate average predicted probability
   - Calculate actual win rate (% correct)
3. Plot predicted vs actual

**Perfect calibration example:**
- 60-70% bucket: Predicted 65%, Actual 67% ✓ (close)
- 80-90% bucket: Predicted 85%, Actual 84% ✓ (close)

**Over-confident example:**
- 70-80% bucket: Predicted 75%, Actual 60% ✗ (over-confident)

### Step 4: Calculate ECE

```python
ece = sum([
    abs(pred - actual) * (count / total)
    for pred, actual, count in calibration_curve
])
```

## Performance Benchmarks

### Brier Score Interpretation

| Brier Score | Rating | Description |
|-------------|--------|-------------|
| 0.00 - 0.10 | **Superforecaster** | Top 2% - extraordinary accuracy |
| 0.10 - 0.15 | **Excellent** | Top 10% - very reliable |
| 0.15 - 0.25 | **Good** | Above average - solid predictions |
| 0.25 - 0.35 | **Fair** | Average - room for improvement |
| 0.35+ | **Poor** | Below average - needs work |

### Confidence Bias Guidelines

| Bias | Rating | Action |
|------|--------|--------|
| -10% to +10% | **Well-Calibrated** | Maintain current approach |
| +10% to +20% | **Slightly Over-Confident** | Be more cautious |
| +20%+ | **Over-Confident** | Significantly reduce confidence |
| -10% to -20% | **Slightly Under-Confident** | Can be more aggressive |
| -20%- | **Under-Confident** | Missing opportunities |

## Comparison to Regret Analysis

| Aspect | Regret Analysis | Calibration Analysis |
|--------|----------------|---------------------|
| **Measures** | Profit optimization | Probability accuracy |
| **Question** | How much $ left on table? | Are predictions accurate? |
| **Best Value** | 0 (no regret) | 0 (perfect calibration) |
| **Uses** | Trading strategy | Forecasting quality |
| **Good For** | ROI optimization | Probability assessment |

**Use Both Together:**
- Low regret + good calibration = Excellent trader
- Low regret + poor calibration = Lucky (not sustainable)
- High regret + good calibration = Good forecaster, bad timing
- High regret + poor calibration = Needs fundamental improvement

## Use Cases

### 1. Identify Skilled Forecasters

```bash
python analysis/calibration_analysis.py --top 20 --report
```

Look for traders with:
- Brier score < 0.20
- Large sample size (50+ predictions)
- Low confidence bias
- Good calibration curve

### 2. Self-Assessment

```bash
python analysis/calibration_analysis.py --trader YOUR_ADDRESS --visualize
```

Use results to:
- Identify overconfident patterns
- Find categories where you're well-calibrated
- Adjust probability estimates
- Improve decision-making process

### 3. Copy Trading Selection

```bash
python analysis/calibration_analysis.py --all --visualize
```

Prefer traders with:
- Brier < 0.25 (minimum threshold)
- ECE < 0.10 (good calibration)
- Sufficient data (30+ predictions)
- Calibration in relevant categories

### 4. Research Analysis

```bash
python analysis/calibration_analysis.py --report --output research/calibration_study.txt
```

Study patterns:
- Relationship between calibration and profitability
- Category-specific calibration differences
- Evolution of calibration over time
- Common calibration errors

## Statistical Considerations

### Minimum Sample Size

- **Per trader**: 10 predictions minimum
- **Per bucket**: 10 predictions for reliability
- **Confidence intervals**: Shown for buckets with < 30 predictions

### Binomial Confidence Intervals

For each calibration bucket:
```python
se = sqrt(p * (1-p) / n)
ci = 1.96 * se  # 95% confidence interval
```

Small samples have wide confidence intervals.

### Edge Cases Handled

1. **Extreme probabilities** (< 1% or > 99%): Filtered out
2. **Multiple trades per market**: Each trade counted separately
3. **Insufficient data**: Clear warnings and flags
4. **Zero predictions**: Returns None with warning

## Limitations

1. **Requires resolved markets**: Can't analyze active markets
2. **Sample size dependent**: More predictions = more reliable metrics
3. **Price as proxy**: Assumes trade price = true belief
4. **Market efficiency**: Assumes prices reflect fair probabilities
5. **No time weighting**: All predictions weighted equally
6. **Binary outcomes**: Designed for Yes/No markets

## Advanced Topics

### Brier Score Decomposition

The Brier score can be decomposed into:
1. **Reliability**: How well-calibrated predictions are
2. **Resolution**: Ability to distinguish outcomes
3. **Uncertainty**: Inherent difficulty of predictions

### Calibration by Time Period

Track calibration evolution:
- Early career vs experienced
- Different market conditions
- Learning curve analysis

### Comparative Analysis

Compare traders by:
- Same category (e.g., politics experts)
- Same time period
- Similar volume levels

## Integration with Monitoring System

### Data Flow

```
Monitoring System → Collects trades & resolutions
         ↓
  Database (polymarket_tracker.db)
         ↓
Calibration Analysis → Measures forecasting accuracy
         ↓
  Reports & Visualizations
```

### Complementary Tools

Use alongside:
- **Regret Analysis**: Profit optimization
- **ELO System**: Relative skill ranking
- **Win Rate**: Simple success metric

## Troubleshooting

### "No resolved markets found"

**Cause**: Database has no markets with known outcomes
**Solution**: Wait for monitoring system to collect resolutions

### "Trader has insufficient predictions"

**Cause**: Trader has < 10 trades in resolved markets
**Solution**: Wait for more market resolutions or analyze different trader

### "No module named 'scipy'"

**Cause**: Missing scipy package
**Solution**: `pip install scipy` or `pip install -r requirements.txt`

### Very high Brier scores (> 0.50)

**Possible causes:**
- Trader consistently betting against winners
- Extreme over/under-confidence
- Data quality issues
- Small sample size

### Calibration curve doesn't make sense

**Check:**
- Sample sizes per bucket (need 10+ for reliability)
- Market resolution data quality
- Trade timestamp vs resolution timing

## References

### Academic Background

- **Brier, G. W. (1950)**: "Verification of forecasts expressed in terms of probability"
- **Murphy, A. H. (1973)**: "A new vector partition of the probability score"
- **Gneiting & Raftery (2007)**: "Strictly proper scoring rules"

### Forecasting Resources

- **Good Judgment Project**: Superforecasting research
- **Metaculus**: Calibration tools for prediction markets
- **FiveThirtyEight**: Applied calibration analysis

### Related Concepts

- **Proper scoring rules**: Incentive-compatible metrics
- **Logarithmic score**: Alternative to Brier score
- **Spherical score**: Another proper scoring rule

## Best Practices

### For Traders

1. **Track your calibration** regularly
2. **Focus on categories** where you're well-calibrated
3. **Adjust confidence** based on bias patterns
4. **Seek diverse markets** for better calibration data
5. **Compare to baselines** (random = 0.25 Brier)

### For Researchers

1. **Report sample sizes** always
2. **Use confidence intervals** for small samples
3. **Control for categories** when comparing traders
4. **Consider time periods** (market conditions vary)
5. **Check for data quality** issues

### For Copy Trading

1. **Require minimum data** (50+ predictions)
2. **Check recent calibration** (last 3 months)
3. **Verify across categories** you care about
4. **Combine with other metrics** (regret, ELO)
5. **Monitor ongoing** (calibration can drift)

## Future Enhancements

Potential improvements:
- [ ] Time-weighted calibration (recent vs historical)
- [ ] Category-specific calibration curves
- [ ] Confidence interval visualization
- [ ] Calibration evolution over time
- [ ] Comparison against market consensus
- [ ] Logarithmic score as alternative metric
- [ ] Multi-outcome market support
- [ ] Real-time calibration monitoring

## Example: Interpreting Results

### Scenario 1: Excellent Trader

```
Brier Score: 0.12
ECE: 0.025
Confidence Bias: +1.2%
```

**Interpretation**: Top-tier forecaster with outstanding calibration. Very reliable probability estimates.

**Action**: High priority for copy trading.

### Scenario 2: Over-Confident Trader

```
Brier Score: 0.32
ECE: 0.15
Confidence Bias: +18.5%
```

**Interpretation**: Consistently over-estimates win probabilities. Bets too aggressively.

**Action**: If this is you, reduce confidence levels. If copy trading, avoid or use lower stake sizes.

### Scenario 3: Well-Calibrated but Unlucky

```
Brier Score: 0.22
ECE: 0.04
Confidence Bias: -1.1%
Win Rate: 48%
```

**Interpretation**: Good calibration but slightly below 50% win rate. May just need more time.

**Action**: Good candidate if sample size increases and pattern holds.

## Conclusion

Calibration analysis is essential for:
- ✅ Measuring true forecasting skill
- ✅ Identifying over/under-confidence
- ✅ Improving probability estimates
- ✅ Selecting reliable traders to follow
- ✅ Complementing profit-based metrics

A well-calibrated trader is worth following, even if their profit optimization (regret analysis) isn't perfect yet - good calibration indicates true skill that can be refined.

---

**Last Updated**: December 2025
**Version**: 1.0.0
**Companion Tool**: [Regret Analysis](REGRET_ANALYSIS_README.md)
