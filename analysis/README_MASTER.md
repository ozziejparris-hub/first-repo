# Polymarket Trader Analysis System - Complete Guide

**Last Updated:** 2025-12-04

---

## 📋 TABLE OF CONTENTS

1. [System Overview](#system-overview)
2. [Quick Start Guide](#quick-start-guide)
3. [Analysis Tools Catalog](#analysis-tools-catalog)
4. [Advanced Metrics Suite](#advanced-metrics-suite)
5. [Integration Architecture](#integration-architecture)
6. [Workflows & Best Practices](#workflows--best-practices)
7. [Troubleshooting](#troubleshooting)
8. [Documentation Index](#documentation-index)

---

## SYSTEM OVERVIEW

### What is This?

A comprehensive Polymarket trader tracking and analysis system consisting of **12 specialized analysis tools** that evaluate trader performance across multiple dimensions:

- **Basic Metrics:** Win rate, ROI, trading volume
- **Behavioral Analysis:** Trading patterns, diversification, activity frequency
- **Relationship Detection:** Trader correlations, copy-trading networks
- **Advanced Metrics:** Game theory regret, forecasting calibration, risk-adjusted returns
- **Rating System:** ELO-based trader skill ratings

### System Architecture

```
DATABASE (polymarket_tracker.db)
    ↓
12 ANALYSIS TOOLS (read-only, can run in parallel)
    ├─ Basic Performance & Behavior (5 tools)
    ├─ Relationship Analysis (3 tools) ← INTEGRATED
    ├─ Advanced Metrics (3 tools)
    └─ Rating System (1 tool)
    ↓
OUTPUTS (CSV, JSON, visualizations, reports)
```

### Key Features

✅ **Comprehensive Coverage:** 12 analysis dimensions from basic to advanced
✅ **Active Integration:** Correlation → Copy-Trade → Confidence (working)
✅ **Parallel Execution:** All tools can run simultaneously (read-only)
✅ **Test Coverage:** Comprehensive test suites for all advanced metrics
✅ **Rich Documentation:** 9 documentation files + 3 comprehensive audit docs

---

## QUICK START GUIDE

### 1. Check Your Data Status

Before running any analysis, verify you have sufficient data:

```bash
python analysis/analysis_scheduler.py --mode check
```

**Minimum Requirements:**
- Resolved Markets: 10+
- Active Traders: 20+
- Total Trades: 100+

### 2. Run Your First Analysis

**Option A: Fast Overview (< 5 minutes)**
```bash
# Basic trader performance
python analysis/trader_performance_analysis.py

# Trading behavior patterns
python analysis/trading_behavior_analysis.py
```

**Option B: Comprehensive Analysis (30-60 minutes)**
```bash
# Full system analysis (orchestrates all tools)
python analysis/analysis_scheduler.py --mode full
```

### 3. View Results

Reports are saved to:
- `analysis/output/` - Individual tool outputs
- `reports/` - Unified analysis reports

---

## ANALYSIS TOOLS CATALOG

### 🎯 BASIC PERFORMANCE & BEHAVIOR (5 Tools)

#### 1. trader_performance_analysis.py
**Purpose:** Calculate basic trader performance metrics
**Speed:** Fast (< 1 minute)

**Metrics Calculated:**
- Win rate (% of profitable trades)
- Total volume (sum of all bet sizes)
- Average trade size
- Total P&L (profit/loss)
- ROI (return on investment)
- Combined score (weighted win rate + ROI)

**Usage:**
```bash
python analysis/trader_performance_analysis.py
```

**Output:** CSV reports, console output, trader rankings

**When to Use:** Quick daily overview, initial trader screening

---

#### 2. trading_behavior_analysis.py
**Purpose:** Deep analysis of trading patterns and behavioral classification
**Speed:** Fast (< 2 minutes)
**File Size:** 728 lines

**Metrics Calculated:**

**Betting Patterns:**
- Average/median/min/max bet size
- Standard deviation and coefficient of variation
- Consistency classification (Very Consistent → Highly Variable)

**Market Diversification:**
- Unique markets traded
- Diversification score (%)
- Top market concentration
- Classification: Concentrated vs Diversified

**Activity Frequency:**
- Trades per day/week
- Most active day of week
- Most active hour
- Activity trend (Increasing/Stable/Decreasing)

**Trading Style Classification:**
- Power User (≥50 trades, ≥5/day, ≥60% diversification)
- High Volume Specialist (≥50 trades, <30% diversification)
- Big Better (≥$100 avg bet, <20 trades)
- Micro Trader (<$20 avg bet, ≥50 trades, ≥60% diversification)
- Weekend Warrior (active weekends, <1 trade/day)
- Market Specialist (<30% diversification)
- Casual Trader (default)

**Usage:**
```bash
python analysis/trading_behavior_analysis.py
```

**Output:** Comprehensive CSV with all metrics, trader style classifications

**When to Use:** Understanding trader psychology, identifying trading patterns, segmenting traders

---

#### 3. consensus_divergence_detector.py
**Purpose:** Detect when traders significantly disagree on market outcomes
**Speed:** Fast (< 1 minute)

**Functionality:**
- Analyzes divergence in trader predictions
- Identifies markets with high disagreement
- Flags potential market inefficiencies

**Usage:**
```bash
python analysis/consensus_divergence_detector.py
```

**Output:** Markets with high divergence, disagreement scores

**When to Use:** Finding markets with conflicting signals, identifying uncertainty

---

#### 4. trader_specialization_analysis.py
**Purpose:** Identify which categories traders specialize in
**Speed:** Fast (< 1 minute)

**Functionality:**
- Category-specific performance tracking
- Identifies trader expertise areas
- Calculates specialization scores per category

**Usage:**
```bash
python analysis/trader_specialization_analysis.py
```

**Output:** Category performance breakdown per trader

**When to Use:** Finding category experts, matching traders to market types

---

#### 5. market_confidence_meter.py
**Purpose:** Aggregate trader predictions with independence validation
**Speed:** Fast (< 1 minute)
**Integration:** ✓ Uses copy_trade_detector

**Functionality:**
- Aggregates trader signals for market outcomes
- Validates signal independence
- Weights predictions (can be enhanced with calibration scores)
- Calculates market confidence scores

**Usage:**
```bash
python analysis/market_confidence_meter.py
```

**Output:** Market confidence scores, weighted predictions

**When to Use:** Evaluating market sentiment, weighting trader consensus

---

### 🔗 RELATIONSHIP ANALYSIS (3 Tools - INTEGRATED)

#### 6. correlation_matrix.py
**Purpose:** Multi-dimensional trader-to-trader correlation analysis
**Speed:** Medium (5-10 minutes)
**File Size:** 787 lines
**Integration:** ✓ Exports to copy_trade_detector

**Core Calculations:**

**Pairwise Correlation (3 dimensions):**
- Market Overlap (30% weight): Jaccard similarity of markets
- Outcome Agreement (50% weight): % same outcomes chosen
- Timing Similarity (20% weight): Temporal overlap
- **Combined Score:** 0.0 (independent) to 1.0 (identical)

**Cluster Identification:**
- Uses networkx for graph-based clustering
- Flags suspicious patterns (correlation > 0.8)

**Independent Traders:**
- Finds traders with low correlation to others (< 0.25)
- Calculates independence scores

**Integration Export:**
```python
export_for_integration() returns:
{
    'correlation_matrix': [...],
    'high_correlation_pairs': [(trader_a, trader_b, score), ...],
    'independent_traders': [...]
}
```

**Usage:**
```bash
python analysis/correlation_matrix.py
```

**Output:**
- CSV correlation matrix
- JSON exports for integration
- Network graphs

**Interpretation:**
- 0.0-0.2: Independent (good for consensus)
- 0.2-0.4: Low correlation
- 0.4-0.6: Moderate correlation
- 0.6-0.8: High correlation (suspicious)
- 0.8-1.0: Very high (copy-trading likely)

**When to Use:** Understanding trader relationships, preparing for copy-trade detection

---

#### 7. copy_trade_detector.py
**Purpose:** Detect leader-follower copy-trading relationships with time-lag analysis
**Speed:** Medium (10-15 minutes)
**File Size:** 856 lines
**Integration:** ✓ Imports correlation_matrix, exports to confidence_meter

**Core Functionality:**

**Imports Correlation Data:**
```python
self.correlation_analyzer = TraderCorrelationMatrix(db_path)
corr_data = self.correlation_analyzer.export_for_integration()
self.high_corr_pairs = corr_data['high_correlation_pairs']
```
- **Efficiency:** Only analyzes high-correlation pairs (not all traders)

**Copy Score Calculation (4 dimensions):**
- Time Consistency (40%): % follower trades within time window after leader
- Outcome Matching (30%): Agreement on Yes/No choice
- Order Preservation (20%): Sequential trade order similarity
- Volume Correlation (10%): Bet size correlation
- **Combined Score:** 0.0 to 1.0

**Relationship Detection:**
- Determines leader vs follower (who trades first)
- Identifies leader→follower pairs (copy_score > 0.65)
- Builds copy-trading networks

**Front-Running Opportunities:**
- Identifies markets where leaders just bet
- Predicts where followers will copy
- Calculates timing windows

**Signal Independence Validation:**
```python
validate_signal_independence(market_id, traders_on_market) → (bool, float)
```
- **Used by:** market_confidence_meter.py
- **Purpose:** Discount copy-trader signals in consensus

**Usage:**
```bash
# Basic detection
python analysis/copy_trade_detector.py

# Adjust sensitivity
python analysis/copy_trade_detector.py --min-markets 5 --min-score 0.5

# Find recent opportunities
python analysis/copy_trade_detector.py --lookback-hours 24
```

**Output:**
- Copy relationships CSV (leader, follower, score, confidence)
- Copy networks (leaders with follower counts)
- Trader classifications (Leader/Follower/Mixed/Independent)
- Front-run opportunities
- Summary report

**Classification:**
- **LEADER:** Has 3+ followers
- **FOLLOWER:** Copies 1+ traders
- **MIXED:** Both leader and follower
- **INDEPENDENT:** No copy relationships

**When to Use:**
- Filtering out copy-traders from analysis
- Finding leaders worth following
- Detecting market manipulation
- Validating signal independence

---

### 🚀 ADVANCED METRICS SUITE (3 Tools)

#### 8. regret_analysis.py
**Purpose:** Game theory-based regret analysis measuring opportunity cost
**Speed:** Slow (20-30 minutes for all traders)
**File Size:** 897 lines
**Documentation:** [REGRET_ANALYSIS_README.md](./REGRET_ANALYSIS_README.md)

**Core Concept:**
```
Regret = (Best possible return with perfect foresight) - (Actual return)
Lower regret = Better decision-making under uncertainty
```

**Metrics Calculated:**

**RegretMetrics (11 fields):**
- `actual_return`: Total profit/loss achieved
- `optimal_return`: Best possible profit with perfect foresight
- `total_regret`: Dollar amount left on table
- `average_regret_per_trade`: Regret per trade
- `regret_rate`: (regret / optimal return) × 100 (percentage)
- `total_invested`: Capital deployed
- `total_trades`, `winning_trades`, `losing_trades`, `win_rate`
- `resolved_markets_count`

**Calculation Process:**
1. For each resolved market:
   - Calculate actual return (track net position, apply payout)
   - Find best price for winning outcome (before trader's last trade)
   - Calculate optimal return (max profit with that price)
   - Regret = optimal - actual
2. Aggregate across all markets

**Interpretation:**
- Regret Rate < 20%: **EXCELLENT** (near-optimal decisions)
- 20-40%: **GOOD** (above average)
- 40-60%: **AVERAGE** (moderate room for improvement)
- 60-80%: **BELOW AVERAGE**
- >80%: **POOR** (substantial opportunity cost)

**Usage:**
```bash
# Analyze specific trader
python analysis/regret_analysis.py --trader 0x1234567890abcdef

# Analyze all traders
python analysis/regret_analysis.py --all

# Full analysis with visualizations
python analysis/regret_analysis.py --all --report --visualize

# Custom output
python analysis/regret_analysis.py --all --output reports/my_regret_report.txt
```

**Visualizations:**
- Regret distribution histogram
- Actual vs Optimal scatter (colored by regret rate)
- Top traders by lowest regret
- Regret rate distribution

**Output:** CSV/JSON with regret metrics, comprehensive reports, 4 visualizations

**When to Use:**
- Evaluating execution quality (did trader get good prices?)
- Separating luck from skill
- Finding traders who optimize entry/exit
- Identifying high-regret traders who leave money on table

**Integration Opportunity:** Could feed into ELO system to reward low-regret traders

---

#### 9. calibration_analysis.py
**Purpose:** Measure forecasting accuracy - how well predicted probabilities match reality
**Speed:** Slow (30-40 minutes for all traders)
**File Size:** 1102 lines
**Documentation:** [CALIBRATION_ANALYSIS_README.md](./CALIBRATION_ANALYSIS_README.md)

**Core Concept:**
```
Perfect calibration: If you predict 70%, it should happen 70% of the time
Brier Score: Mean squared error of probability predictions (0 = perfect, 2 = worst)
```

**Metrics Calculated:**

**CalibrationMetrics (10 fields):**
- `brier_score`: Overall forecasting accuracy (0-2, lower better)
- `expected_calibration_error` (ECE): Avg deviation from perfect calibration
- `max_calibration_error` (MCE): Worst calibration bin
- `confidence_bias`: Tendency to over/under-estimate probabilities (%)
- `avg_predicted_prob`: Average probability predicted
- `actual_win_rate`: Actual success rate
- `calibration_curve`: List of (predicted, actual, count) per bin
- `category_scores`: Dict of category → Brier score
- `total_predictions`, `resolved_markets`

**Calculation Process:**
1. Extract implied probabilities from trades:
   - For YES trades: predicted_prob = price
   - For NO trades: predicted_prob = 1 - price
2. Compare to actual outcomes (1 if correct, 0 if wrong)
3. Calculate Brier score: (1/N) × Σ(predicted - actual)²
4. Create calibration curve (bin predictions into 10% buckets)
5. Calculate ECE: Σ|predicted - actual| × (count / total)
6. Detect bias: avg_predicted - actual_win_rate
7. Analyze by category

**Interpretation:**
- Brier < 0.15: **EXCELLENT** (top tier forecaster)
- Brier < 0.25: **GOOD**
- Brier > 0.25: **FAIR** (room for improvement)
- ECE < 0.05: Well-calibrated
- Confidence Bias:
  - ±2%: Perfect calibration
  - >5%: Over-Confident
  - <-5%: Under-Confident

**Usage:**
```bash
# Analyze specific trader
python analysis/calibration_analysis.py --trader 0x1234567890abcdef

# Analyze all traders
python analysis/calibration_analysis.py --all

# Show top 20 calibrated traders
python analysis/calibration_analysis.py --top 20

# Full analysis with visualizations
python analysis/calibration_analysis.py --all --report --visualize

# Custom output
python analysis/calibration_analysis.py --all --output reports/my_calibration.txt
```

**Visualizations:**
- Calibration curve (reliability diagram) with 95% confidence intervals
- Brier score distribution with threshold lines
- Confidence bias scatter (predicted vs actual)
- Top calibrated traders bar chart

**Output:** CSV/JSON with calibration metrics, comprehensive reports, 4 visualizations

**Category Analysis:**
Already calculates Brier score per market category - shows which categories trader forecasts accurately.

**When to Use:**
- Evaluating forecasting skill (separate from execution)
- Finding well-calibrated traders for weighting
- Identifying over-confident traders
- Category-specific expertise detection

**Integration Opportunity:**
- **HIGH PRIORITY**: Should feed into ELO system to weight predictions
- **MEDIUM PRIORITY**: Should feed into confidence_meter for better weighting

---

#### 10. risk_adjusted_returns.py
**Purpose:** Separate skill from luck by normalizing returns against risk
**Speed:** Slow (25-35 minutes for all traders)
**File Size:** ~900 lines
**Documentation:** [RISK_ADJUSTED_RETURNS_README.md](./RISK_ADJUSTED_RETURNS_README.md)

**Core Concept:**
```
Sharpe Ratio = Return per unit of total risk
Sortino Ratio = Return per unit of downside risk only
Separates consistent performers from lucky gamblers
```

**Metrics Calculated:**

**RiskMetrics (20+ fields):**

**Return Metrics:**
- `total_return_dollars`, `total_return_pct`
- `total_invested`, `final_portfolio_value`
- `win_rate`, `loss_rate`
- `avg_win_size`, `avg_loss_size`, `win_loss_ratio`

**Risk-Adjusted Ratios:**
- `sharpe_ratio`: (avg_return - rf_rate) / std_dev
- `sortino_ratio`: (avg_return - rf_rate) / downside_deviation
- `calmar_ratio`: avg_return / max_drawdown

**Risk Metrics:**
- `volatility`: Standard deviation of returns
- `maximum_drawdown_pct`: Largest peak-to-trough decline
- `max_drawdown_duration_days`: Longest drawdown period
- `var_95`, `var_99`: Value at Risk at 95%/99% confidence
- `cvar_95`, `cvar_99`: Conditional VaR (expected loss beyond VaR)
- `skewness`, `kurtosis`: Distribution statistics

**Extremes:**
- `best_trade_return`, `worst_trade_return`

**Calculation Process:**
1. Get all trade returns in resolved markets
2. Track cumulative portfolio value over time
3. Identify peaks and drawdowns
4. Calculate return distribution (mean, std dev, downside std dev)
5. Calculate Sharpe: (mean - rf) / std_dev
6. Calculate Sortino: (mean - rf) / downside_std_dev
7. Calculate max drawdown: largest % decline from peak
8. Calculate Calmar: mean / max_drawdown
9. Calculate VaR: 5th/1st percentile of return distribution
10. Calculate CVaR: mean of returns below VaR

**Interpretation:**
- **Sharpe Ratio:**
  - >1.0: Good
  - >2.0: Excellent
  - >3.0: Exceptional
- **Sortino > Sharpe:** Asymmetric returns (good - losses small, wins large)
- **Calmar > 1.0:** Good recovery from drawdowns
- **Max Drawdown < 20%:** Low risk
- **VaR 95%:** Expect to lose more than this 5% of the time

**Usage:**
```bash
# Analyze specific trader
python analysis/risk_adjusted_returns.py --trader 0x1234567890abcdef

# Analyze all traders
python analysis/risk_adjusted_returns.py --all

# Show top 10 by Sharpe ratio
python analysis/risk_adjusted_returns.py --top 10

# Full analysis with visualizations
python analysis/risk_adjusted_returns.py --all --report --visualize

# Custom rolling window
python analysis/risk_adjusted_returns.py --all --window 30

# Custom output
python analysis/risk_adjusted_returns.py --all --output reports/my_risk_report.txt
```

**Visualizations:**
- Equity curve with drawdown overlay
- Return distribution histogram with VaR lines
- Risk-return scatter plot (volatility vs return)
- Top traders comparison chart

**Output:** CSV/JSON with risk metrics, comprehensive reports, 4 visualizations

**When to Use:**
- Identifying truly skilled traders (high return + low risk)
- Distinguishing luck from skill
- Evaluating risk management quality
- Finding consistent performers

**Integration Opportunity:**
- **MEDIUM PRIORITY**: Should feed into ELO system for adaptive K-factor (Sharpe-based rating volatility)

---

### 🏆 RATING SYSTEM (1 Tool)

#### 11. weighted_consensus_system.py
**Purpose:** Core ELO-based trader rating system
**Speed:** Fast (< 5 minutes)
**File Size:** ~500 lines
**Status:** ⚠️ Standalone (NOT yet integrated with advanced metrics)

**Current Functionality:**
- Calculates trader ratings based on prediction accuracy in resolved markets
- Uses consensus-based weighting (wisdom of crowds)
- Adjusts ratings up for correct predictions, down for wrong ones
- Rating volatility based on number of markets participated in

**Current Inputs:**
- trades table: trader_address, market_id, outcome
- markets table: market_id, winning_outcome, resolved

**Current Limitations:**
- ✗ No consideration of prediction confidence (price paid)
- ✗ No adjustment for risk-taking behavior
- ✗ No filtering of copy-traders
- ✗ No weighting by calibration quality
- ✗ No differentiation between lucky and skilled traders

**Usage:**
```bash
python analysis/weighted_consensus_system.py
```

**Output:** Trader ELO ratings

**Integration Opportunities (HIGH PRIORITY):**

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4 for detailed implementation:

1. **Calibration Integration:** Weight predictions by Brier scores
2. **Copy-Trader Filtering:** Exclude followers from ELO calculations
3. **Risk-Adjusted K-Factor:** Adjust rating volatility by Sharpe ratio
4. **Regret-Based Penalties:** Reward low-regret execution quality
5. **Composite Skill Score:** Unified 0-100 score combining all dimensions

**When to Use:** Ranking traders by overall skill

---

### 🤖 AUTOMATION (1 Tool)

#### 12. analysis_scheduler.py
**Purpose:** Automated orchestration of analysis tools
**Speed:** Orchestrator (manages other tools)
**File Size:** ~300 lines
**Status:** ⚠️ Needs updating for new tools

**Current Functionality:**
- Schedules periodic execution of analysis scripts
- Manages timing and dependencies
- Checks data sufficiency before running

**Usage:**
```bash
# Check data status
python analysis/analysis_scheduler.py --mode check

# Run full analysis
python analysis/analysis_scheduler.py --mode full

# Quick incremental update
python analysis/analysis_scheduler.py --mode quick

# Force run without data checks
python analysis/analysis_scheduler.py --mode full --force
```

**Recommended Updates:**
- Add regret_analysis.py (daily after market resolutions)
- Add calibration_analysis.py (weekly comprehensive)
- Add risk_adjusted_returns.py (weekly comprehensive)
- Coordinate dependency chain: correlation → copy-trade → confidence

See [COMPATIBILITY_MATRIX.md](./COMPATIBILITY_MATRIX.md) for scheduling recommendations.

---

## INTEGRATION ARCHITECTURE

### Current Integration (Working ✓)

```
correlation_matrix.py
    └─→ export_for_integration()
        └─→ copy_trade_detector.py
            └─→ validate_signal_independence()
                └─→ market_confidence_meter.py
```

**Status:** ✅ Fully operational
**Benefit:** Efficient copy-trade detection, independent signal validation

### Recommended Integrations (Not Yet Implemented)

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4 for detailed implementations.

**HIGH PRIORITY:**

1. **calibration_analysis → weighted_consensus_system**
   - Weight trader predictions by Brier scores
   - **Benefit:** More accurate ELO ratings

2. **copy_trade_detector → weighted_consensus_system**
   - Filter out copy-traders from ELO calculation
   - **Benefit:** ELO reflects genuine skill

**MEDIUM PRIORITY:**

3. **risk_adjusted_returns → weighted_consensus_system**
   - Adjust ELO K-factor by Sharpe ratio
   - **Benefit:** Stable ratings for consistent traders

4. **calibration_analysis → market_confidence_meter**
   - Weight predictions by Brier scores
   - **Benefit:** More accurate confidence scores

**LOW PRIORITY:**

5. **regret_analysis → weighted_consensus_system**
   - Reward low-regret execution quality
   - **Benefit:** Combines forecasting + execution

### Composite Skill Score (Future)

Unified trader evaluation combining all dimensions:
- 50 points: Forecasting accuracy (Brier score)
- 25 points: Risk-adjusted returns (Sharpe ratio)
- 15 points: Execution quality (Regret rate)
- 10 points: Consensus accuracy (ELO rating)
- -10 points: Copy-trader penalty

**Total:** 0-100 unified skill score

---

## WORKFLOWS & BEST PRACTICES

### Workflow 1: Quick Daily Overview (< 5 min)

**Purpose:** Fast trader stats check

```bash
python analysis/trader_performance_analysis.py &
python analysis/trading_behavior_analysis.py &
python analysis/trader_specialization_analysis.py &
wait
```

**Output:** Win rates, ROI, trading patterns, category preferences

---

### Workflow 2: Relationship Analysis (10-20 min)

**Purpose:** Understand trader networks and copy-trading

```bash
python analysis/copy_trade_detector.py  # Includes correlation internally
python analysis/market_confidence_meter.py
```

**Output:** Correlation clusters, leader-follower pairs, market confidence scores

---

### Workflow 3: Advanced Metrics (30-60 min)

**Purpose:** Deep skill analysis

**Option A: One at a time (fastest individual completion)**
```bash
python analysis/regret_analysis.py --all --visualize
python analysis/calibration_analysis.py --all --visualize
python analysis/risk_adjusted_returns.py --all --visualize
```

**Option B: Two in parallel (maximize CPU)**
```bash
# Terminal 1
python analysis/regret_analysis.py --all --visualize

# Terminal 2 (simultaneously)
python analysis/calibration_analysis.py --all --visualize

# After both complete:
python analysis/risk_adjusted_returns.py --all --visualize
```

**Output:** Regret rates, Brier scores, Sharpe ratios, comprehensive skill assessment

---

### Workflow 4: Complete Weekly Analysis (60-90 min)

**Phase 1: Fast tools in parallel (< 5 min)**
```bash
python analysis/trader_performance_analysis.py &
python analysis/trading_behavior_analysis.py &
python analysis/consensus_divergence_detector.py &
python analysis/trader_specialization_analysis.py &
wait
```

**Phase 2: Relationship analysis (10-15 min)**
```bash
python analysis/copy_trade_detector.py
python analysis/market_confidence_meter.py
```

**Phase 3: Advanced metrics (2 at a time) (30-60 min)**
```bash
# Terminal 1
python analysis/regret_analysis.py --all --report --visualize

# Terminal 2
python analysis/calibration_analysis.py --all --report --visualize

# Wait for both, then:
python analysis/risk_adjusted_returns.py --all --report --visualize
```

**Phase 4: ELO system (5 min)**
```bash
python analysis/weighted_consensus_system.py
```

---

### Automated Scheduling Recommendations

**Daily (if new resolved markets):**
- 00:05: `trader_performance_analysis.py`
- 00:10: `trading_behavior_analysis.py`
- 00:15: `copy_trade_detector.py`
- 00:30: `regret_analysis.py --all`

**Weekly (comprehensive):**
- Sunday 02:00: `calibration_analysis.py --all --report --visualize`
- Sunday 03:00: `risk_adjusted_returns.py --all --report --visualize`
- Sunday 04:00: `correlation_matrix.py`
- Sunday 04:30: `weighted_consensus_system.py`

**Real-time (continuous):**
- Hourly: `market_confidence_meter.py`
- Every 4 hours: `consensus_divergence_detector.py`

---

## TROUBLESHOOTING

### "No resolved markets available yet"

**Symptom:** regret/calibration/risk-adjusted tools report no data

**Cause:** These tools require markets with known outcomes (resolved = 1)

**Solution:**
```bash
# Check database for resolved markets
python -c "
import sqlite3
conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM markets WHERE resolved = 1')
print(f'Resolved markets: {cursor.fetchone()[0]}')
conn.close()
"

# If 0: Wait for markets to resolve (monitoring system will update)
# If 10+: Safe to run advanced metrics
```

---

### Slow Performance

**Symptom:** Tools take much longer than expected

**Causes & Solutions:**

1. **Running too many CPU-intensive tools simultaneously**
   - **Solution:** Run regret/calibration/risk-adjusted tools 1-2 at a time

2. **Large database**
   - **Solution:** Use `--top N` flag to analyze fewer traders
   ```bash
   python analysis/calibration_analysis.py --top 50
   ```

3. **System resource constraints**
   - **Solution:** Lower process priority
   ```bash
   nice -n 10 python analysis/calibration_analysis.py --all
   ```

---

### "Database is locked" Error

**Symptom:** `sqlite3.OperationalError: database is locked`

**Cause:** Unlikely with analysis tools (all read-only), but could occur if monitoring system is writing

**Solution:**
```bash
# Check for other processes
ps aux | grep python

# Wait 5 seconds, try again
sleep 5
python analysis/your_tool.py
```

---

### Out of Memory Errors

**Symptom:** `MemoryError` or system swap thrashing

**Solution:**
```bash
# Run sequentially instead of parallel
python analysis/regret_analysis.py --all
python analysis/calibration_analysis.py --all
python analysis/risk_adjusted_returns.py --all

# Or: Analyze specific trader only
python analysis/calibration_analysis.py --trader 0x1234567890abcdef
```

---

### Inconsistent Metric Values

**Symptom:** Win rate differs between tools

**Cause:** Multiple tools calculate similar metrics independently

**Solution:** See [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 6 for standardization details

**Workaround:** Use primary tool for each metric:
- **Win Rate:** Any tool (should be similar)
- **ROI:** `trader_performance_analysis` for quick, `risk_adjusted_returns` for accurate
- **Category Performance:** `calibration_analysis` for accuracy metrics

---

## DOCUMENTATION INDEX

### Comprehensive Audit & Architecture (New!)

1. **[AUDIT_REPORT.md](./AUDIT_REPORT.md)** - Complete system audit
   - Phase 1: Discovery & Inventory (all 19 files cataloged)
   - Phase 2: Compatibility Analysis (parallel vs sequential)
   - Phase 3: Data Flow Mapping (ASCII diagrams)
   - Phase 4: Integration Opportunities (detailed implementations)
   - Phase 5: Gap Analysis (missing capabilities)
   - Phase 6: Conflict Resolution (metric standardization)
   - Phase 7: Recommendations (quick wins, long-term enhancements)

2. **[COMPATIBILITY_MATRIX.md](./COMPATIBILITY_MATRIX.md)** - Tool compatibility guide
   - Which tools can run in parallel
   - Which have sequential dependencies
   - Database locking analysis
   - Resource usage profiles
   - Recommended workflows
   - Performance optimization tips

3. **[DATA_FLOW.md](./DATA_FLOW.md)** - Data flow architecture
   - System overview diagrams
   - Detailed flow by component
   - Integration points
   - Future ELO integration architecture
   - Output data formats

### Tool-Specific Documentation

4. **[REGRET_ANALYSIS_README.md](./REGRET_ANALYSIS_README.md)** (~450 lines)
   - Metric explanations
   - Interpretation guidelines
   - Usage examples
   - Visualization descriptions
   - Troubleshooting
   - Comparison to other tools

5. **[CALIBRATION_ANALYSIS_README.md](./CALIBRATION_ANALYSIS_README.md)** (~500 lines)
   - Brier score details
   - Calibration curve interpretation
   - Usage examples
   - Confidence bias analysis
   - Category performance

6. **[RISK_ADJUSTED_RETURNS_README.md](./RISK_ADJUSTED_RETURNS_README.md)** (~450 lines)
   - Sharpe/Sortino/Calmar explanations
   - Interpretation benchmarks
   - Usage examples
   - Visualization guide
   - Comparison to simple ROI

7. **[BEHAVIOR_ANALYSIS_README.md](./BEHAVIOR_ANALYSIS_README.md)**
   - Trading style classifications
   - Betting pattern analysis
   - Diversification metrics

8. **[REGRET_ANALYSIS_QUICKSTART.md](./REGRET_ANALYSIS_QUICKSTART.md)**
   - Quick start guide for regret analysis

9. **[REGRET_CALCULATION_EXAMPLES.md](./REGRET_CALCULATION_EXAMPLES.md)**
   - Worked examples of regret calculations

### Legacy Documentation

10. **[ANALYSIS_TOOLS_OVERVIEW.md](./ANALYSIS_TOOLS_OVERVIEW.md)**
    - High-level overview (may be outdated)

11. **[ANALYSIS_README.md](./ANALYSIS_README.md)**
    - General analysis documentation (may be outdated)

---

## SYSTEM STATISTICS

**Total Python Files:** 19
- Core analysis tools: 12
- Test suites: 5
- Demo scripts: 3

**Total Documentation Files:** 12 (including this file)

**Total Lines of Code:** ~11,500+
- Largest tool: calibration_analysis.py (1102 lines)
- Smallest tool: consensus_divergence_detector.py (~400 lines)

**Integration Status:**
- Active integrations: 1 (correlation → copy-trade → confidence)
- Recommended integrations: 5 (see Phase 4)
- Future enhancements: 8+ (see Phase 7)

---

## NEXT STEPS

### For New Users

1. ✅ Read this README (you are here!)
2. ✅ Check data status: `python analysis/analysis_scheduler.py --mode check`
3. ✅ Run fast overview: Workflow 1 (< 5 min)
4. ✅ Explore outputs in `analysis/output/`
5. ✅ Read tool-specific documentation for deep dives

### For System Administrators

1. ✅ Review [AUDIT_REPORT.md](./AUDIT_REPORT.md) for complete system understanding
2. ✅ Review [COMPATIBILITY_MATRIX.md](./COMPATIBILITY_MATRIX.md) for scheduling
3. ✅ Update `analysis_scheduler.py` to include new tools
4. ✅ Consider implementing Phase 4 integrations (ELO + advanced metrics)

### For Developers

1. ✅ Review [DATA_FLOW.md](./DATA_FLOW.md) for architecture
2. ✅ Read [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4 for integration implementations
3. ✅ Consider creating `analysis/shared_metrics.py` for standardization
4. ✅ Consider implementing composite skill score

---

## GETTING HELP

**For Tool Usage Questions:**
- Check tool-specific README files
- Run tool with `--help` flag: `python analysis/tool_name.py --help`

**For System Architecture Questions:**
- Read [AUDIT_REPORT.md](./AUDIT_REPORT.md)
- Read [DATA_FLOW.md](./DATA_FLOW.md)

**For Performance Issues:**
- Check [COMPATIBILITY_MATRIX.md](./COMPATIBILITY_MATRIX.md) → Performance Optimization section
- Check this README → Troubleshooting section

**For Integration Questions:**
- Read [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4
- Review [DATA_FLOW.md](./DATA_FLOW.md) Integration section

---

## CONCLUSION

You have a **world-class trader analysis system** with:
- ✅ 12 specialized analysis tools covering all dimensions of trader evaluation
- ✅ Working integration architecture (correlation → copy-trade → confidence)
- ✅ Comprehensive test coverage for all advanced metrics
- ✅ Rich documentation (9 core docs + 3 audit docs)
- ✅ Clear roadmap for future enhancements

**The system is production-ready.** With recommended integrations (ELO + advanced metrics), it would be **best-in-class**.

**Happy analyzing! 📊🚀**
