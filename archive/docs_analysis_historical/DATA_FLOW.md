# DATA FLOW ARCHITECTURE

**Generated:** 2025-12-04
**Purpose:** Visual representation of how data flows through the Polymarket trader tracking system

---

## SYSTEM OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         POLYMARKET API                                  │
│                    (External Data Source)                               │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ API calls
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      DATA COLLECTION LAYER                              │
│                      (monitor.py / scraper)                             │
│                                                                         │
│  - Fetches active markets                                              │
│  - Tracks trader positions                                             │
│  - Records trades (trader, market, outcome, shares, price, timestamp)  │
│  - Updates market resolutions                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ INSERT INTO
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATABASE: polymarket_tracker.db                      │
│                         (SQLite)                                        │
│                                                                         │
│  TABLE: trades                                                          │
│  ├─ trade_id (TEXT, PRIMARY KEY)                                       │
│  ├─ trader_address (TEXT, INDEXED)                                     │
│  ├─ market_id (TEXT, INDEXED)                                          │
│  ├─ outcome (TEXT: 'Yes' or 'No')                                      │
│  ├─ shares (REAL)                                                       │
│  ├─ price (REAL: 0.0 - 1.0)                                            │
│  ├─ side (TEXT: 'buy' or 'sell')                                       │
│  ├─ timestamp (TEXT, ISO format)                                       │
│  └─ market_title (TEXT)                                                │
│                                                                         │
│  TABLE: markets                                                         │
│  ├─ market_id (TEXT, PRIMARY KEY)                                      │
│  ├─ condition_id (TEXT, for joining with trades)                       │
│  ├─ title (TEXT)                                                        │
│  ├─ category (TEXT)                                                     │
│  ├─ resolved (INTEGER: 0 or 1)                                         │
│  ├─ winning_outcome (TEXT: 'Yes' or 'No', NULL if unresolved)          │
│  └─ resolution_date (TEXT, ISO format)                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ SELECT queries (read-only)
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
                    ▼                            ▼
        ┌───────────────────────┐   ┌───────────────────────┐
        │   ANALYSIS LAYER      │   │   RELATIONSHIP        │
        │   (Independent Tools) │   │   ANALYSIS LAYER      │
        └───────────────────────┘   └───────────────────────┘
                    │                            │
                    │                            │
                    └────────────┬───────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   INTEGRATION LAYER    │
                    │   (Future: ELO System) │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   OUTPUT LAYER         │
                    │   (Reports, CSV, JSON) │
                    └────────────────────────┘
```

---

## DETAILED DATA FLOW BY COMPONENT

### 1. BASIC PERFORMANCE METRICS FLOW

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  trader_performance_analysis.py
│  - markets       │                      │
└──────────────────┘                      │
                                          ▼
                                 ┌─────────────────────┐
                                 │  CALCULATIONS       │
                                 │                     │
                                 │  For each trader:   │
                                 │  ├─ Win rate        │
                                 │  ├─ Total volume    │
                                 │  ├─ Avg trade size  │
                                 │  ├─ Total P&L       │
                                 │  ├─ ROI             │
                                 │  └─ Combined score  │
                                 └─────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────────┐
                                 │  OUTPUT             │
                                 │                     │
                                 │  - CSV report       │
                                 │  - Console output   │
                                 │  - Trader rankings  │
                                 └─────────────────────┘
```

**Key Queries:**
```sql
-- Get all trades for resolved markets
SELECT t.*, m.winning_outcome
FROM trades t
INNER JOIN markets m ON t.market_id = m.condition_id
WHERE m.resolved = 1

-- Calculate P&L per trade
-- If outcome matches winning_outcome: profit = payout - cost
-- If outcome differs: loss = -cost
```

---

### 2. BEHAVIORAL ANALYSIS FLOW

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  trading_behavior_analysis.py
│  - markets       │                      │
└──────────────────┘                      │
                                          ▼
                                 ┌─────────────────────────────────┐
                                 │  PATTERN ANALYSIS               │
                                 │                                 │
                                 │  1. Betting Patterns:           │
                                 │     └─ Group by trader          │
                                 │        ├─ Calculate bet sizes   │
                                 │        ├─ Std deviation         │
                                 │        └─ Consistency score     │
                                 │                                 │
                                 │  2. Diversification:            │
                                 │     └─ Count unique markets     │
                                 │        ├─ Market distribution   │
                                 │        └─ Concentration %       │
                                 │                                 │
                                 │  3. Activity Frequency:         │
                                 │     └─ Analyze timestamps       │
                                 │        ├─ Trades per day        │
                                 │        ├─ Most active times     │
                                 │        └─ Activity trend         │
                                 │                                 │
                                 │  4. Style Classification:       │
                                 │     └─ Combine above metrics    │
                                 │        └─ Assign trading style  │
                                 └─────────────────────────────────┘
                                          │
                                          ▼
                                 ┌─────────────────────┐
                                 │  OUTPUT             │
                                 │                     │
                                 │  - CSV report       │
                                 │  - Trader profiles  │
                                 │  - Style categories │
                                 └─────────────────────┘
```

**Key Transformations:**
```
trades → group by trader_address → calculate statistics → classify style
```

---

### 3. CORRELATION & COPY-TRADING FLOW (INTEGRATED)

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  correlation_matrix.py
│  - markets       │                      │
└──────────────────┘                      │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  PAIRWISE CORRELATION CALCULATION   │
                            │                                     │
                            │  For each trader pair (A, B):       │
                            │  ├─ Market Overlap (30%):           │
                            │  │  └─ Jaccard similarity           │
                            │  ├─ Outcome Agreement (50%):        │
                            │  │  └─ % same outcome chosen        │
                            │  ├─ Timing Similarity (20%):        │
                            │  │  └─ Temporal overlap             │
                            │  └─ Combined Score: 0.0 - 1.0       │
                            └─────────────────────────────────────┘
                                          │
                                          ├─→ CSV export
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  export_for_integration()           │
                            │                                     │
                            │  Returns Dict:                      │
                            │  {                                  │
                            │    'correlation_matrix': [...],     │
                            │    'high_correlation_pairs': [      │
                            │       (trader_a, trader_b, score),  │
                            │       ...                           │
                            │    ],                               │
                            │    'independent_traders': [...]     │
                            │  }                                  │
                            └─────────────────────────────────────┘
                                          │
                                          │ IMPORT & USE
                                          ▼
┌──────────────────┐         ┌──────────────────────────────────────┐
│   DATABASE       │─SELECT─→│  copy_trade_detector.py              │
│  - trades        │         │                                      │
└──────────────────┘         │  __init__():                         │
                             │    self.correlation_analyzer = ...   │
                             │    corr_data = export_for_integration│
                             │    self.high_corr_pairs = corr_data  │
                             └──────────────────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  TIME-LAG ANALYSIS                  │
                            │                                     │
                            │  For each high-corr pair:           │
                            │  ├─ Time Consistency (40%):         │
                            │  │  └─ % follower trades within     │
                            │  │     time window after leader     │
                            │  ├─ Outcome Matching (30%):         │
                            │  │  └─ Same Yes/No choice           │
                            │  ├─ Order Preservation (20%):       │
                            │  │  └─ Sequential similarity        │
                            │  ├─ Volume Correlation (10%):       │
                            │  │  └─ Bet size correlation         │
                            │  └─ Copy Score: 0.0 - 1.0           │
                            │                                     │
                            │  If copy_score > 0.65:              │
                            │    → Leader-Follower relationship   │
                            └─────────────────────────────────────┘
                                          │
                                          ├─→ CSV export
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  validate_signal_independence()     │
                            │                                     │
                            │  Input: market_id, trader_addresses │
                            │  Returns: (is_independent, score)   │
                            │                                     │
                            │  Logic:                             │
                            │  - Check if any traders are in      │
                            │    copy relationships               │
                            │  - Discount follower signals        │
                            │  - Return independence validation   │
                            └─────────────────────────────────────┘
                                          │
                                          │ IMPORT & USE
                                          ▼
┌──────────────────┐         ┌──────────────────────────────────────┐
│   DATABASE       │─SELECT─→│  market_confidence_meter.py          │
│  - trades        │         │                                      │
└──────────────────┘         │  For each market:                    │
                             │  1. Get all traders on market        │
                             │  2. Call validate_signal_independence│
                             │  3. If independent:                  │
                             │     └─ Use all trader signals        │
                             │  4. If not independent:              │
                             │     └─ Filter out copy-traders       │
                             │  5. Aggregate weighted predictions   │
                             │  6. Return confidence score          │
                             └──────────────────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  OUTPUT                             │
                            │                                     │
                            │  - Market confidence scores         │
                            │  - Independent trader counts        │
                            │  - Consensus probabilities          │
                            └─────────────────────────────────────┘
```

**Key Integration Points:**
1. correlation_matrix exports data via `export_for_integration()`
2. copy_trade_detector imports correlation_matrix and uses exported data
3. copy_trade_detector exports validation via `validate_signal_independence()`
4. market_confidence_meter imports copy_trade_detector and uses validation

**This is the ONLY existing cross-tool integration in the system.**

---

### 4. REGRET ANALYSIS FLOW

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  regret_analysis.py
│  - markets       │ (WHERE resolved = 1)
└──────────────────┘                      │
                                          ▼
                            ┌──────────────────────────────────┐
                            │  FOR EACH TRADER:                │
                            │                                  │
                            │  1. Get all trades in resolved   │
                            │     markets                      │
                            │     └─ Group by market_id        │
                            │                                  │
                            │  2. For each market:             │
                            │     ├─ Calculate actual return   │
                            │     │  └─ Track net position     │
                            │     │     (buys add, sells sub)  │
                            │     │  └─ Payout if position     │
                            │     │     matches winner         │
                            │     │                            │
                            │     ├─ Calculate optimal return  │
                            │     │  └─ Find best price for    │
                            │     │     winning outcome        │
                            │     │  └─ Max profit possible    │
                            │     │                            │
                            │     └─ Regret = optimal - actual │
                            │                                  │
                            │  3. Aggregate across markets:    │
                            │     ├─ Total regret              │
                            │     ├─ Regret rate %             │
                            │     └─ Avg regret per trade      │
                            └──────────────────────────────────┘
                                          │
                                          ▼
                            ┌──────────────────────────────────┐
                            │  OUTPUT                          │
                            │                                  │
                            │  RegretMetrics:                  │
                            │  ├─ actual_return                │
                            │  ├─ optimal_return               │
                            │  ├─ total_regret                 │
                            │  ├─ regret_rate (%)              │
                            │  ├─ win_rate                     │
                            │  └─ total_invested               │
                            │                                  │
                            │  Outputs:                        │
                            │  ├─ CSV/JSON reports             │
                            │  ├─ Visualizations               │
                            │  └─ Trader rankings              │
                            └──────────────────────────────────┘
```

**Key Calculation:**
```
Optimal Return = capital / best_price_for_winning_outcome
Actual Return = Σ(position_shares × payout) - cost
Regret = Optimal Return - Actual Return
Regret Rate % = (Regret / Optimal Return) × 100
```

---

### 5. CALIBRATION ANALYSIS FLOW

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  calibration_analysis.py
│  - markets       │ (INNER JOIN on condition_id, WHERE resolved = 1)
└──────────────────┘                      │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  FOR EACH TRADER:                   │
                            │                                     │
                            │  1. Extract implied probabilities:  │
                            │     For each trade:                 │
                            │     ├─ If outcome = 'Yes':          │
                            │     │  predicted_prob = price       │
                            │     └─ If outcome = 'No':           │
                            │        predicted_prob = 1 - price   │
                            │                                     │
                            │  2. Get actual outcomes:            │
                            │     ├─ Join with markets table      │
                            │     ├─ Check winning_outcome        │
                            │     └─ actual = 1 if correct, 0 if not│
                            │                                     │
                            │  3. Calculate Brier Score:          │
                            │     brier = (1/N) × Σ(pred - actual)²│
                            │     └─ Range: 0 (perfect) to 2      │
                            │                                     │
                            │  4. Create calibration curve:       │
                            │     ├─ Bin predictions (0-10%, etc) │
                            │     ├─ For each bin:                │
                            │     │  ├─ avg_predicted             │
                            │     │  ├─ actual_win_rate           │
                            │     │  └─ count                     │
                            │     └─ Perfect = diagonal line      │
                            │                                     │
                            │  5. Calculate ECE:                  │
                            │     ECE = Σ|pred - actual| × count/N│
                            │                                     │
                            │  6. Detect confidence bias:         │
                            │     bias = avg_predicted - actual   │
                            │                                     │
                            │  7. Analyze by category:            │
                            │     └─ Brier score per category     │
                            └─────────────────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  OUTPUT                             │
                            │                                     │
                            │  CalibrationMetrics:                │
                            │  ├─ brier_score                     │
                            │  ├─ expected_calibration_error      │
                            │  ├─ max_calibration_error           │
                            │  ├─ confidence_bias                 │
                            │  ├─ calibration_curve               │
                            │  └─ category_scores                 │
                            │                                     │
                            │  Outputs:                           │
                            │  ├─ CSV/JSON reports                │
                            │  ├─ Calibration curve plots         │
                            │  └─ Brier distribution              │
                            └─────────────────────────────────────┘
```

**Key Transformations:**
```
Trade price → Implied probability → Compare to actual outcome → Brier score
Then: Bin probabilities → Compare predicted vs actual per bin → Calibration curve
```

---

### 6. RISK-ADJUSTED RETURNS FLOW

```
┌──────────────────┐
│   DATABASE       │
│  - trades        │──SELECT─→  risk_adjusted_returns.py
│  - markets       │ (WHERE resolved = 1)
└──────────────────┘                      │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  FOR EACH TRADER:                   │
                            │                                     │
                            │  1. Get trade returns:              │
                            │     For each trade:                 │
                            │     ├─ Calculate P&L                │
                            │     ├─ Track cumulative portfolio   │
                            │     ├─ Identify peak values         │
                            │     └─ Calculate drawdown           │
                            │                                     │
                            │  2. Calculate return distribution:  │
                            │     ├─ Mean return                  │
                            │     ├─ Std deviation (volatility)   │
                            │     ├─ Downside deviation           │
                            │     ├─ Skewness                     │
                            │     └─ Kurtosis                     │
                            │                                     │
                            │  3. Calculate Sharpe Ratio:         │
                            │     sharpe = (mean - rf) / std_dev  │
                            │                                     │
                            │  4. Calculate Sortino Ratio:        │
                            │     sortino = (mean - rf) /         │
                            │               downside_std_dev      │
                            │                                     │
                            │  5. Calculate Max Drawdown:         │
                            │     ├─ Track running maximum        │
                            │     ├─ Calculate % decline          │
                            │     └─ Measure duration             │
                            │                                     │
                            │  6. Calculate Calmar Ratio:         │
                            │     calmar = mean / max_drawdown    │
                            │                                     │
                            │  7. Calculate VaR & CVaR:           │
                            │     ├─ VaR 95% = 5th percentile     │
                            │     ├─ VaR 99% = 1st percentile     │
                            │     └─ CVaR = mean of tail losses   │
                            └─────────────────────────────────────┘
                                          │
                                          ▼
                            ┌─────────────────────────────────────┐
                            │  OUTPUT                             │
                            │                                     │
                            │  RiskMetrics (20+ fields):          │
                            │  ├─ sharpe_ratio                    │
                            │  ├─ sortino_ratio                   │
                            │  ├─ calmar_ratio                    │
                            │  ├─ maximum_drawdown_pct            │
                            │  ├─ volatility                      │
                            │  ├─ var_95, var_99                  │
                            │  ├─ win_rate, loss_rate             │
                            │  └─ total_return_pct                │
                            │                                     │
                            │  Outputs:                           │
                            │  ├─ CSV/JSON reports                │
                            │  ├─ Equity curve with drawdown      │
                            │  ├─ Return distribution             │
                            │  └─ Risk-return scatter             │
                            └─────────────────────────────────────┘
```

**Key Calculations:**
```
Returns → Mean, Std Dev → Sharpe = (Mean - RF) / Std Dev
Returns → Downside Std Dev → Sortino = (Mean - RF) / Downside Std Dev
Portfolio Values → Peak, Trough → Max Drawdown = (Peak - Trough) / Peak
Returns Distribution → 5th Percentile → VaR 95%
```

---

## FUTURE INTEGRATION: ELO SYSTEM DATA FLOW

**Current State:** ELO system is standalone

**Proposed Integration:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                   INTEGRATED ELO RATING SYSTEM                      │
│                   (weighted_consensus_system.py)                    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ Reads trader predictions
                                  ▼
┌──────────────────┐         ┌─────────────────────────────────────────┐
│   DATABASE       │─SELECT─→│  ELO CALCULATION WITH INTEGRATIONS      │
│  - trades        │         │                                         │
│  - markets       │         │  For each trader prediction:            │
└──────────────────┘         │                                         │
                             │  1. Base Accuracy:                      │
                             │     └─ Did prediction match outcome?    │
                             │                                         │
                             │  2. CALIBRATION WEIGHT:                 │
          ┌─────────────────→│     ├─ Import CalibrationAnalyzer      │
          │                  │     ├─ Get trader Brier score           │
          │                  │     └─ weight = 2.0 - brier_score       │
          │                  │        (low Brier = high weight)        │
          │                  │                                         │
          │                  │  3. COPY-TRADER FILTER:                 │
          │  ┌──────────────→│     ├─ Import CopyTradeDetector        │
          │  │               │     ├─ Check if follower                │
          │  │               │     └─ If follower: weight = 0          │
          │  │               │        (don't count copy-traders)       │
          │  │               │                                         │
          │  │               │  4. ADAPTIVE K-FACTOR:                  │
          │  │  ┌───────────→│     ├─ Import RiskAdjustedAnalyzer     │
          │  │  │            │     ├─ Get trader Sharpe ratio          │
          │  │  │            │     └─ k_factor = f(sharpe)             │
          │  │  │            │        High Sharpe → low K (stable)     │
          │  │  │            │        Low Sharpe → high K (volatile)   │
          │  │  │            │                                         │
          │  │  │            │  5. EXECUTION QUALITY:                  │
          │  │  │  ┌────────→│     ├─ Import RegretAnalyzer            │
          │  │  │  │         │     ├─ Get trader regret rate           │
          │  │  │  │         │     └─ modifier = f(regret_rate)        │
          │  │  │  │         │        Low regret → bonus                │
          │  │  │  │         │        High regret → penalty             │
          │  │  │  │         │                                         │
          │  │  │  │         │  6. CALCULATE ELO ADJUSTMENT:           │
          │  │  │  │         │     new_rating = old_rating +           │
          │  │  │  │         │       k_factor ×                        │
          │  │  │  │         │       weight ×                          │
          │  │  │  │         │       modifier ×                        │
          │  │  │  │         │       (actual - expected)               │
          │  │  │  │         └─────────────────────────────────────────┘
          │  │  │  │                       │
          │  │  │  │                       ▼
          │  │  │  │         ┌─────────────────────────────────────────┐
          │  │  │  │         │  OUTPUT                                 │
          │  │  │  │         │                                         │
          │  │  │  │         │  Enhanced ELO Ratings:                  │
          │  │  │  │         │  ├─ Weighted by forecasting accuracy   │
          │  │  │  │         │  ├─ Filtered for copy-traders          │
          │  │  │  │         │  ├─ Adaptive volatility                │
          │  │  │  │         │  └─ Execution quality adjusted         │
          │  │  │  │         │                                         │
          │  │  │  │         │  Composite Skill Score:                 │
          │  │  │  │         │  ├─ 50 pts: Calibration (Brier)        │
          │  │  │  │         │  ├─ 25 pts: Risk-Adjusted (Sharpe)     │
          │  │  │  │         │  ├─ 15 pts: Execution (Regret)         │
          │  │  │  │         │  └─ 10 pts: Consensus (ELO)            │
          │  │  │  │         │     Total: 0-100 unified score         │
          │  │  │  │         └─────────────────────────────────────────┘
          │  │  │  │
          │  │  │  └─────── regret_analysis.py
          │  │  │            (regret_rate for execution quality)
          │  │  │
          │  │  └────────── risk_adjusted_returns.py
          │  │               (sharpe_ratio for K-factor)
          │  │
          │  └─────────────  copy_trade_detector.py
          │                  (filter followers)
          │
          └────────────────  calibration_analysis.py
                             (brier_score for weighting)
```

**Status:** This integration does NOT exist yet. See AUDIT_REPORT.md Phase 4 for implementation details.

---

## DATA DEPENDENCIES SUMMARY

### Current Dependencies (Implemented ✓)

```
correlation_matrix.py
    └─→ Exports: high_correlation_pairs, independent_traders
        └─→ Used by: copy_trade_detector.py
            └─→ Exports: validate_signal_independence()
                └─→ Used by: market_confidence_meter.py
```

### Recommended Dependencies (Not Yet Implemented)

```
calibration_analysis.py
    └─→ Should export: trader Brier scores
        └─→ Should be used by:
            ├─→ weighted_consensus_system.py (weight predictions)
            ├─→ market_confidence_meter.py (weight predictions)
            └─→ consensus_divergence_detector.py (weight divergence)

risk_adjusted_returns.py
    └─→ Should export: trader Sharpe ratios
        └─→ Should be used by:
            └─→ weighted_consensus_system.py (adaptive K-factor)

regret_analysis.py
    └─→ Should export: trader regret rates
        └─→ Should be used by:
            └─→ weighted_consensus_system.py (execution quality modifier)

copy_trade_detector.py
    └─→ Should export: follower addresses
        └─→ Should be used by:
            └─→ weighted_consensus_system.py (filter from ELO)
```

---

## OUTPUT DATA FORMATS

### CSV Format (Standard Across Tools)

```csv
trader_address,metric1,metric2,metric3,...
0x1234...,value1,value2,value3,...
0x5678...,value1,value2,value3,...
```

**Files Generated:**
- `analysis/output/performance_report.csv`
- `analysis/output/behavior_analysis.csv`
- `analysis/output/regret_analysis.csv`
- `analysis/output/calibration_analysis.csv`
- `analysis/output/risk_adjusted_returns.csv`
- `analysis/output/correlation_matrix.csv`
- `analysis/output/copy_relationships.csv`

### JSON Format (For Integration)

```json
{
  "trader_address": "0x1234...",
  "timestamp": "2025-12-04T10:30:00Z",
  "tool": "calibration_analysis",
  "metrics": {
    "brier_score": 0.18,
    "ece": 0.04,
    "confidence_bias": 2.5,
    ...
  }
}
```

### Visualization Outputs (PNG)

- `analysis/output/regret_distribution.png`
- `analysis/output/actual_vs_optimal.png`
- `analysis/output/calibration_curve_0x1234.png`
- `analysis/output/brier_distribution.png`
- `analysis/output/equity_curve_0x1234.png`
- `analysis/output/risk_return_scatter.png`

---

## PERFORMANCE CONSIDERATIONS

### Database Query Patterns

**Fast Queries (< 1 second):**
```sql
-- Get trader trades
SELECT * FROM trades WHERE trader_address = ?

-- Get resolved markets
SELECT * FROM markets WHERE resolved = 1
```

**Medium Queries (1-10 seconds):**
```sql
-- Get all trades for resolved markets (JOIN)
SELECT t.*, m.winning_outcome
FROM trades t
INNER JOIN markets m ON t.market_id = m.condition_id
WHERE m.resolved = 1
```

**Slow Queries (10+ seconds):**
```sql
-- Get all pairwise trader overlaps (Cartesian product)
SELECT DISTINCT t1.trader_address, t2.trader_address
FROM trades t1
CROSS JOIN trades t2
WHERE t1.trader_address != t2.trader_address
  AND t1.market_id = t2.market_id
```

### Optimization Strategies

1. **Indexing:**
   ```sql
   CREATE INDEX idx_trader ON trades(trader_address);
   CREATE INDEX idx_market ON trades(market_id);
   CREATE INDEX idx_resolved ON markets(resolved);
   ```

2. **Caching:**
   - Cache resolved market list (changes infrequently)
   - Cache trader list (changes infrequently)
   - Cache correlation matrix (expensive to compute)

3. **Incremental Updates:**
   - Track `last_analyzed` timestamp per trader
   - Only recalculate traders with new trades since last_analyzed
   - Estimated speedup: 10-100x

4. **Parallel Processing:**
   - All tools are read-only → can run simultaneously
   - Use multiprocessing for CPU-bound tasks
   - Process traders in parallel (trader analysis is independent)

---

## SUMMARY

**Current Data Flow Characteristics:**
- ✓ Clean separation: Database → Analysis → Output
- ✓ Read-only analysis tools (no conflicts)
- ✓ One active integration: correlation → copy-trade → confidence
- ✓ Comprehensive coverage: 12 analysis dimensions

**Future Enhancement Opportunities:**
- ⚠️ Add ELO integration with advanced metrics
- ⚠️ Standardize output formats (unified JSON schema)
- ⚠️ Implement result caching
- ⚠️ Add incremental update system
- ⚠️ Create unified trader dashboard

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) and [COMPATIBILITY_MATRIX.md](./COMPATIBILITY_MATRIX.md) for detailed recommendations.
