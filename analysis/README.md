# Polymarket Trader Analysis System

**Complete analysis suite for tracking and evaluating Polymarket trader performance.**

---

## 📖 Documentation

### Primary Documentation
👉 **[README_MASTER.md](README_MASTER.md)** - Complete analysis system guide
Comprehensive documentation covering all 12 analysis tools, workflows, and best practices.

👉 **[UNIFIED_ELO_SYSTEM.md](UNIFIED_ELO_SYSTEM.md)** - ELO rating system technical reference
Deep dive into the 6-dimensional ELO rating system with behavioral analysis.

---

## 🚀 Quick Start

### Check Data Sufficiency
```bash
python analysis/analysis_scheduler.py --mode check
```

### Run Basic Analysis
```bash
# Trader performance (win rates, ROI)
python analysis/trader_performance_analysis.py

# Trading behavior (patterns, styles)
python analysis/trading_behavior_analysis.py
```

### Run Full Analysis Suite
```bash
# Orchestrates all 12 tools
python analysis/analysis_scheduler.py --mode full
```

---

## 🧰 Key Analysis Tools

### Performance & Behavior (5 tools)
- **trader_performance_analysis.py** - Win rates, ROI, P&L
- **trading_behavior_analysis.py** - Patterns, styles, behavioral metrics
- **correlation_matrix.py** - Trading pattern correlations
- **weighted_consensus_system.py** - ELO-weighted predictions
- **trader_specialization_analysis.py** - Category-specific expertise

### Relationship Detection (3 tools)
- **copy_trade_detector.py** - Leader-follower relationships
- **market_confidence_meter.py** - Consensus strength analysis
- **consensus_divergence_detector.py** - Contrarian opportunities

### Advanced Metrics (3 tools)
- **regret_minimization_analysis.py** - Game theory regret
- **calibration_analysis.py** - Forecasting accuracy
- **risk_adjusted_returns.py** - Sharpe ratios, volatility

### Rating System (1 tool)
- **unified_elo_system.py** - 6-dimensional ELO with behavioral modifiers

---

## 📊 Key Metrics

### ELO Rating System (6 Dimensions)
1. **Base ELO** - Category-specific skill ratings
2. **Behavioral** - Kelly alignment + Patience + Timing
3. **Advanced** - Calibration + Execution quality
4. **Network** - Independence check
5. **Contrarian** - Anti-consensus bonus
6. **P&L** - Real profit/loss performance

**Total Range:** 800-2400 ELO points (1500 starting)

### Current Performance
- **Traders Tracked:** 1,957
- **Resolved Markets:** 2,480 (1.2% of 213K)
- **Correlation Target:** 0.35-0.50 (from 0.135 baseline)
- **Elite Accuracy Target:** 55-70%

---

## 📁 Reports Generated

All analysis outputs saved to:
- `analysis/output/` - Individual tool outputs
- `reports/` - Unified reports and CSVs

### Main Report Types
- Trader rankings (by ELO, win rate, ROI)
- Behavioral profiles (trading styles, patterns)
- Relationship networks (correlations, copy trading)
- Market predictions (consensus, divergence)
- Performance metrics (calibration, risk-adjusted returns)

---

## 🔄 Typical Workflow

### Daily Quick Check
```bash
# Check recent activity
python analysis/trader_performance_analysis.py  # Select: Last 7 days

# Review top performers
python scripts/view_trader_rankings.py
```

### Weekly Comprehensive Analysis
```bash
# Generate all metrics
python analysis/analysis_scheduler.py --mode full

# Update ELO ratings
python scripts/integrate_behavioral_elo.py

# Validate results
python scripts/simulation/verify_elo_rankings.py --verbose
```

### Monthly Deep Dive
```bash
# All-time performance
python analysis/trader_performance_analysis.py  # Select: All time

# Export and analyze CSVs
python scripts/update_database_from_csvs.py

# Run validation suite
python tests/test_behavioral_integration.py
```

---

## 🎯 Data Requirements

### Minimum Thresholds
- **Resolved Markets:** 10+ (for ELO/win rates)
- **Active Traders:** 20+ (for correlations)
- **Total Trades:** 100+ (for patterns)

### Recommended
- **Resolved Markets:** 50+ (better accuracy)
- **Active Traders:** 50+ (richer network analysis)
- **Total Trades:** 1,000+ (clear behavioral patterns)

---

## 🛠️ Integration with Main System

### How It Works
```
Monitoring System (monitoring/main.py)
    ↓ (writes every 15 minutes)
Database (data/polymarket_tracker.db)
    ↓ (read-only access)
Analysis Tools (analysis/*.py)
    ↓ (generate)
CSV Reports (reports/*.csv)
    ↓ (imported via)
Database Updates (scripts/update_database_from_csvs.py)
    ↓ (used by)
ELO Integration (scripts/integrate_behavioral_elo.py)
    ↓ (produces)
Final Rankings & Telegram Alerts
```

---

## 📚 Additional Documentation

### Root Documentation
- **[PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md)** - Complete project overview
- **[QUICK_START_CONTEXT.md](../QUICK_START_CONTEXT.md)** - Quick reference for new Claude instances
- **[BUGFIX_SUMMARY.md](../BUGFIX_SUMMARY.md)** - Recent bug fixes (Jan 2026)

### Technical Documentation
- **[docs/ELO_SYSTEM.md](../docs/ELO_SYSTEM.md)** - ELO methodology
- **[docs/SETUP.md](../docs/SETUP.md)** - Installation and configuration
- **[docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md)** - Common issues

---

## ⚙️ Performance Notes

### Execution Speed
| Tool | Speed | API Calls |
|------|-------|-----------|
| Behavior Analysis | < 2 min | None |
| Performance Analysis | 1-5 min | 1 per market |
| ELO Calculation | 5-15 min | None |
| Full Suite | 30-60 min | Varies |

### Database Access
- All tools use **read-only** connections
- Safe to run while monitoring is active
- No interference with data collection
- Parallel execution supported

---

## 🆘 Troubleshooting

### Common Issues

**"Database not found"**
→ Wait for monitoring script to collect trades first

**"No resolved markets"**
→ Markets haven't closed yet (normal for recent data)

**"Insufficient data for analysis"**
→ Run: `python analysis/analysis_scheduler.py --mode check`

**ELO calculation hanging**
→ Fixed in recent updates. Update to latest version.

**Missing behavioral metrics**
→ Run analysis scripts and import CSVs:
```bash
python analysis/trading_behavior_analysis.py
python scripts/update_database_from_csvs.py
```

---

## 🔗 Quick Links

- **Main System**: [monitoring/main.py](../monitoring/main.py)
- **Database Schema**: [docs/DATABASE_SCHEMA_DOCUMENTATION.md](../docs/DATABASE_SCHEMA_DOCUMENTATION.md)
- **Integration Scripts**: [scripts/](../scripts/)
- **Test Suite**: [tests/](../tests/)
- **Archived Docs**: [archive/](../archive/)

---

**For complete details, see [README_MASTER.md](README_MASTER.md)**

**Last Updated:** 2026-01-15 (Post behavioral ELO integration and repository cleanup)
