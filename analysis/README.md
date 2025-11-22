# Polymarket Trader Analysis Tools

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
