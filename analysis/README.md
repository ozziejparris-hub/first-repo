# Polymarket Trader Analysis Tools

## Correlation Matrix Analysis

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
