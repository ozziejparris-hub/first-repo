# Simulation Framework

Tools for testing and validating the ELO rating system using simulated trader data.

## Scripts

### seed_test_data.py
Generates realistic test data with skill-based traders.

**Usage:**
```bash
# Generate test data from config
py scripts/simulation/seed_test_data.py experiments/configs/config_simulation.json

# Clear previous simulation data first
py scripts/simulation/seed_test_data.py experiments/configs/config_simulation.json --clear-simulation
```

**Features:**
- Creates traders with known skill levels (elite, good, average, poor)
- Generates realistic trade volumes and frequencies
- Creates resolved markets for ELO validation
- Validates data quality after seeding

### calculate_elo_simple.py
Calculates ELO ratings using simplified algorithm optimized for simulation data.

**Usage:**
```bash
# Calculate ELO and display results
py scripts/simulation/calculate_elo_simple.py

# Use custom K-factor
py scripts/simulation/calculate_elo_simple.py --k-factor 24

# Export to CSV
py scripts/simulation/calculate_elo_simple.py --export-csv results/elo_rankings.csv
```

**Features:**
- Simple ELO calculation without expensive modifiers
- Displays top/bottom 10 traders
- Analyzes correlation between skill and ELO
- Exports rankings to CSV

### verify_elo_rankings.py
Automated validation of ELO system accuracy.

**Usage:**
```bash
# Run all validation tests
py scripts/simulation/verify_elo_rankings.py --simulation-age-days 7

# Use custom threshold
py scripts/simulation/verify_elo_rankings.py --threshold 0.6

# Export validation report
py scripts/simulation/verify_elo_rankings.py --export results/validation_report.json
```

**Validation Tests:**
1. Elite ranking (>60% win rate in top 20%)
2. Poor ranking (<45% win rate in bottom 50%)
3. ELO spread (200-800 points)
4. Correlation (r >= 0.5)
5. Bucket separation (monotonic decrease)

### analyze_simulation_correlation.py
Quick correlation analysis for simulation traders only.

**Usage:**
```bash
py scripts/simulation/analyze_simulation_correlation.py
```

### optimize_parameters.py
Find optimal K-factor for ELO system.

**Usage:**
```bash
# Test K-factors from 16 to 40
py scripts/simulation/optimize_parameters.py --k-range 16 40

# Optimize for specific metric
py scripts/simulation/optimize_parameters.py --optimize-for correlation

# Export optimization report
py scripts/simulation/optimize_parameters.py --export results/optimization_report.json
```

### backtest_strategy.py
Test trading strategies on simulation data with resolved outcomes.

**Usage:**
```bash
# Test single strategy
py scripts/simulation/backtest_strategy.py --strategy follow_top_n --top-n 10

# Test with different confidence threshold
py scripts/simulation/backtest_strategy.py --strategy follow_top_n --top-n 10 --min-confidence 0.7

# Test all strategies
py scripts/simulation/backtest_strategy.py --all-strategies

# Export results
py scripts/simulation/backtest_strategy.py --all-strategies --export results/backtest_report.json
```

**Strategies:**
1. Follow Top N ELO - Copy trades from highest-rated traders
2. Weighted Consensus - (coming soon)
3. Contrarian - (coming soon)

**Metrics Tracked:**
- Win rate - % of trades that won
- ROI - Return on investment
- Total P&L - Absolute profit/loss
- Sharpe ratio - Risk-adjusted returns
- Max drawdown - Largest losing streak

### analyze_predictions.py
Analyze ELO prediction errors to identify improvement opportunities.

**Usage:**
```bash
# Full analysis
py scripts/simulation/analyze_predictions.py

# Focus on specific analysis
py scripts/simulation/analyze_predictions.py --focus false_positives
py scripts/simulation/analyze_predictions.py --focus market_difficulty

# Export report
py scripts/simulation/analyze_predictions.py --export results/analysis_report.json
```

**Analysis Types:**
1. False Positives - High ELO, low actual performance
2. False Negatives - Low ELO, high actual performance
3. Market Difficulty - Which markets hardest to predict
4. Confusion Matrix - Predicted vs actual skill tiers

**Metrics Analyzed:**
- Error patterns in misranked traders
- Market difficulty by elite trader success rate
- Prediction accuracy by skill tier
- Common failure modes

### compare_systems.py
A/B test different ELO configurations to find optimal system.

**Usage:**
```bash
# Compare K-factors
py scripts/simulation/compare_systems.py --compare k_factors

# Compare simple vs full
py scripts/simulation/compare_systems.py --compare simple_vs_full

# Run all comparisons
py scripts/simulation/compare_systems.py --all

# Export results
py scripts/simulation/compare_systems.py --all --export results/comparison_report.json
```

**Comparison Types:**
1. K-Factor Comparison - Test different volatility settings (24 vs 32 vs 40)
2. Simple vs Full - Basic ELO vs modifiers (not yet implemented)

**Metrics Compared:**
- Correlation (win rate ↔ ELO)
- Elite accuracy (>60% win rate in top 20%)
- Poor accuracy (<45% win rate in bottom 50%)
- Confusion matrix accuracy
- Combined score (weighted average)

## Workflow

### Complete ELO Validation Workflow

1. **Generate test data:**
   ```bash
   py scripts/simulation/seed_test_data.py experiments/configs/config_simulation.json --clear-simulation
   ```

2. **Calculate ELO ratings:**
   ```bash
   py scripts/simulation/calculate_elo_simple.py --k-factor 24
   ```

3. **Verify ELO accuracy:**
   ```bash
   py scripts/simulation/verify_elo_rankings.py --simulation-age-days 7
   ```

4. **Optimize parameters:**
   ```bash
   py scripts/simulation/optimize_parameters.py --k-range 16 40 --optimize-for combined
   ```

## Configuration

See [experiments/configs/](../../experiments/configs/) for example configurations:
- `config_simulation.json` - Production config (80% resolved markets)
- `config_quick.json.example` - Fast testing
- `config_stress.json.example` - Large-scale stress testing
