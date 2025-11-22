# Polymarket Trader Analysis Tools

## Analysis Scheduler (Unified Orchestrator)

### Overview
The analysis scheduler orchestrates all 8 analysis tools in coordinated phases with data sufficiency checks and graceful degradation. This is your main entry point for running comprehensive analysis.

### Quick Start

**Check if you have enough data** (run this first):
```bash
python analysis/analysis_scheduler.py --mode check
```

**Run full analysis** (when you have sufficient data):
```bash
python analysis/analysis_scheduler.py --mode full
```

**Quick update** (incremental changes only):
```bash
python analysis/analysis_scheduler.py --mode quick
```

### Execution Phases

The scheduler runs in 4 coordinated phases:

**Phase 0: Data Sufficiency Check**
- Checks resolved markets (need 10+)
- Checks active traders (need 20+)
- Checks total trades (need 100+)
- Gracefully skips phases if insufficient

**Phase 1: Independent Analysis** (always runs)
- Trading Behavior Analysis
- Correlation Matrix

**Phase 2: Performance-Based** (needs resolved markets)
- Trader Performance Analysis
- Weighted Consensus System
- Trader Specialization Analysis

**Phase 3: Integration Analysis** (needs Phase 1 & 2)
- Copy Trade Detector
- Market Confidence Meter
- Consensus Divergence Detector

**Phase 4: Unified Reporting** (always runs)
- Generates master report
- Saves top opportunities
- Creates trader rankings

### Data Requirements

**Minimum Thresholds:**
- Resolved Markets: 10+ (for ELO/win rates)
- Active Traders: 20+ (for correlations)
- Total Trades: 100+ (for patterns)
- Shared Markets: 5+ (for correlation)

**Recommended:**
- Resolved Markets: 20+ (better accuracy)
- Active Traders: 30+ (richer network)
- Total Trades: 500+ (clear patterns)

### Reports Generated

Unified reports saved to `reports/` directory:
1. `unified_analysis_YYYYMMDD.txt` - Master report with all insights
2. `top_opportunities_YYYYMMDD.txt` - High-confidence actionable signals

Plus individual tool reports from each analysis tool.

### Usage Examples

```bash
# Check current data status (run weekly)
python analysis/analysis_scheduler.py --mode check

# Force run even without sufficient data (testing)
python analysis/analysis_scheduler.py --mode full --force

# Run without Telegram alerts
python analysis/analysis_scheduler.py --mode full --no-alerts

# Use custom database path
python analysis/analysis_scheduler.py --mode full --db-path /path/to/db
```

### Expected Output (Insufficient Data)

```
======================================================================
  PHASE 0: DATA SUFFICIENCY CHECK
======================================================================

📊 CURRENT DATA STATUS:
   Resolved Markets: 0 / 12 total
   Active Traders: 8
   Total Trades: 45
   Shared Markets: 3
   Avg Trades/Trader: 5.6

⚠️  INSUFFICIENT DATA FOR FULL ANALYSIS

❌ Missing Requirements:
   • Need 10+ resolved markets (currently: 0)
   • Need 20+ active traders (currently: 8)
   • Need 100+ total trades (currently: 45)

💡 Recommendations:
   ✓ Continue monitoring for 1-2 weeks
   ✓ Wait for markets to resolve
   ✓ Run weekly: python analysis/analysis_scheduler.py --mode check

📌 Limited analysis will be performed with available data.
```

---

## Individual Analysis Tools

The following tools can be run individually or are automatically orchestrated by the scheduler:

## 1. Correlation Matrix Analysis

### Overview
The correlation matrix tool analyzes trading pattern correlations between traders to detect copy trading networks, validate signal independence, and identify truly independent alpha traders.

### Quick Start
```bash
python analysis/correlation_matrix.py
```

### Reports Generated
All reports saved to `reports/` directory:
1. correlation_matrix_YYYYMMDD.csv - Full pairwise correlations
2. correlation_clusters_YYYYMMDD.csv - Identified clusters
3. independent_traders_YYYYMMDD.csv - Ranked independent traders
4. correlation_summary_YYYYMMDD.txt - Analysis summary

### Correlation Score Interpretation
- 0.0-0.2: Independent (good!)
- 0.2-0.4: Low correlation
- 0.4-0.6: Moderate correlation
- 0.6-0.8: High correlation (suspicious)
- 0.8-1.0: Very high correlation (copy trading likely)

---

## 2. Copy Trade Detector

### Overview
The copy trade detector identifies leader-follower relationships by analyzing time-lagged position copying. It detects WHO COPIES WHO and identifies front-run opportunities when leaders make new bets.

### Quick Start
```bash
python analysis/copy_trade_detector.py
```

### Advanced Options
```bash
# Adjust detection sensitivity
python analysis/copy_trade_detector.py --min-markets 5 --min-score 0.5

# Look for recent front-run opportunities
python analysis/copy_trade_detector.py --lookback-hours 24
```

### Reports Generated
All reports saved to `reports/` directory:
1. copy_relationships_YYYYMMDD.csv - Leader→follower pairs with scores
2. copy_networks_YYYYMMDD.csv - Leaders with their follower counts
3. trader_classifications_YYYYMMDD.csv - Leader/Follower/Independent labels
4. front_run_opportunities_YYYYMMDD.csv - Markets where leaders just bet
5. copy_trade_summary_YYYYMMDD.txt - Analysis summary

### Copy Score Interpretation
The copy score (0.0-1.0) is calculated from 4 weighted components:
- **Time Consistency (40%)**: How consistent is the lag between leader and follower?
- **Outcome Matching (30%)**: Do they bet on the same outcomes?
- **Order Preservation (20%)**: Does follower always trade after leader?
- **Volume Correlation (10%)**: Are their bet sizes similar?

**Score Thresholds:**
- 0.9-1.0: PERFECT copying (near-instant replication)
- 0.7-0.9: STRONG copying (reliable follower)
- 0.5-0.7: MODERATE copying (partial influence)
- Below 0.5: Not classified as copying

### Trader Classifications
- **LEADER**: Has 3+ followers (copy_score ≥ 0.5)
- **FOLLOWER**: Copies 1+ traders
- **MIXED**: Both a leader and a follower
- **INDEPENDENT**: No copy relationships detected

### Front-Run Opportunities
Identifies markets where:
1. A leader just made a bet
2. 3+ of their followers haven't copied yet
3. Within the typical lag window
4. High opportunity score (urgency × magnitude)
