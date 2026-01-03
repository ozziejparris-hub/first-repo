# ANALYSIS TOOLS COMPATIBILITY MATRIX

**Generated:** 2025-12-04
**Purpose:** Understand which tools can run simultaneously, which have dependencies, and how to optimize analysis workflows

---

## QUICK REFERENCE: PARALLEL vs SEQUENTIAL

### ✓ CAN RUN IN PARALLEL (Completely Independent)

These tools can run simultaneously with no conflicts:

- `weighted_consensus_system.py`
- `trader_performance_analysis.py`
- `trading_behavior_analysis.py`
- `consensus_divergence_detector.py`
- `trader_specialization_analysis.py`
- `regret_analysis.py` ⚠️ (CPU-intensive)
- `calibration_analysis.py` ⚠️ (CPU-intensive)
- `risk_adjusted_returns.py` ⚠️ (CPU-intensive)

**Why:** All tools only READ from database (no write conflicts). SQLite allows concurrent reads.

**⚠️ CPU Note:** Regret/Calibration/Risk-adjusted tools are computationally expensive. Running all 3 simultaneously may slow down your system. Consider running 1-2 at a time for faster completion.

---

### → MUST RUN SEQUENTIALLY (Has Dependencies)

These tools require outputs from other tools:

#### Dependency Chain 1: Correlation → Copy-Trade → Confidence

```
1. correlation_matrix.py
      ↓ (exports high_correlation_pairs)
2. copy_trade_detector.py
      ↓ (exports validate_signal_independence)
3. market_confidence_meter.py
```

**Option A: Run Sequentially**
```bash
python analysis/correlation_matrix.py
python analysis/copy_trade_detector.py
python analysis/market_confidence_meter.py
```

**Option B: Run Together** (copy_trade_detector imports correlation_matrix directly)
```bash
python analysis/copy_trade_detector.py  # Runs correlation internally
python analysis/market_confidence_meter.py
```

**Recommendation:** Use Option B for efficiency. `copy_trade_detector.py` will automatically run correlation analysis and use cached results.

---

## DETAILED COMPATIBILITY MATRIX

### Database Access Patterns

| Tool | Read Operations | Write Operations | Locking Risk |
|------|----------------|------------------|--------------|
| weighted_consensus_system.py | ✓ trades, markets | ✗ None | None |
| trader_performance_analysis.py | ✓ trades, markets | ✗ None | None |
| trading_behavior_analysis.py | ✓ trades, markets | ✗ None | None |
| correlation_matrix.py | ✓ trades, markets | ✗ None | None |
| copy_trade_detector.py | ✓ trades, markets | ✗ None | None |
| market_confidence_meter.py | ✓ trades, markets | ✗ None | None |
| consensus_divergence_detector.py | ✓ trades, markets | ✗ None | None |
| trader_specialization_analysis.py | ✓ trades, markets | ✗ None | None |
| regret_analysis.py | ✓ trades, markets | ✗ None | None |
| calibration_analysis.py | ✓ trades, markets | ✗ None | None |
| risk_adjusted_returns.py | ✓ trades, markets | ✗ None | None |
| analysis_scheduler.py | ✗ None (orchestrator) | ✗ None | None |

**Conclusion:** ✅ **ZERO DATABASE LOCKING CONFLICTS** - All tools can run simultaneously from database perspective.

---

### Code Dependencies

| Tool | Imports from Other Analysis Tools | Is Imported By |
|------|-----------------------------------|----------------|
| weighted_consensus_system.py | None ⚠️ (Opportunity) | None |
| trader_performance_analysis.py | None | None |
| trading_behavior_analysis.py | None | None |
| correlation_matrix.py | None | ✓ copy_trade_detector.py |
| copy_trade_detector.py | ✓ correlation_matrix.py | ✓ market_confidence_meter.py |
| market_confidence_meter.py | ✓ copy_trade_detector.py | None |
| consensus_divergence_detector.py | None | None |
| trader_specialization_analysis.py | None | None |
| regret_analysis.py | None ⚠️ (Opportunity) | None |
| calibration_analysis.py | None ⚠️ (Opportunity) | None |
| risk_adjusted_returns.py | None ⚠️ (Opportunity) | None |
| analysis_scheduler.py | Executes all (subprocess) | None |

**⚠️ Opportunities:** Tools marked with ⚠️ could benefit from integration but currently run standalone. See [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4 for integration recommendations.

---

### Resource Usage Profiles

| Tool | Speed | CPU | Memory | Best Time to Run |
|------|-------|-----|--------|------------------|
| weighted_consensus_system.py | Fast | Low | Low | Anytime |
| trader_performance_analysis.py | Fast | Low | Low | Anytime |
| trading_behavior_analysis.py | Fast | Low | Medium | Anytime |
| correlation_matrix.py | Medium | Medium | Medium | Off-hours or with other fast tools |
| copy_trade_detector.py | Medium | Medium | Medium | After correlation or off-hours |
| market_confidence_meter.py | Fast | Low | Low | After copy-trade |
| consensus_divergence_detector.py | Fast | Low | Low | Anytime |
| trader_specialization_analysis.py | Fast | Low | Low | Anytime |
| regret_analysis.py | **Slow** | **High** | Medium | Overnight or dedicated analysis time |
| calibration_analysis.py | **Slow** | **High** | Medium | Overnight or dedicated analysis time |
| risk_adjusted_returns.py | **Slow** | **High** | Medium | Overnight or dedicated analysis time |
| analysis_scheduler.py | N/A | N/A | N/A | Orchestrator only |

**Legend:**
- **Fast:** < 1 minute for 100+ traders
- **Medium:** 1-10 minutes for 100+ traders
- **Slow:** 10+ minutes for 100+ traders (iterates all traders × all resolved markets)

---

## RECOMMENDED WORKFLOWS

### Workflow 1: Quick Overview (< 5 minutes)

**Purpose:** Get basic trader stats fast

**Run in parallel:**
```bash
python analysis/trader_performance_analysis.py &
python analysis/trading_behavior_analysis.py &
python analysis/trader_specialization_analysis.py &
wait
```

**Output:** Win rates, ROI, trading patterns, category preferences

**Use case:** Daily quick checks, initial trader screening

---

### Workflow 2: Relationship Analysis (5-15 minutes)

**Purpose:** Understand trader relationships and copy-trading

**Run sequentially:**
```bash
python analysis/copy_trade_detector.py  # Includes correlation internally
python analysis/market_confidence_meter.py
```

**Output:** Correlation clusters, leader-follower relationships, market confidence scores

**Use case:** Detect copy-trading, weight market predictions, identify independent traders

---

### Workflow 3: Advanced Metrics (30-60 minutes)

**Purpose:** Deep skill analysis with game theory, calibration, risk-adjusted returns

**Option A: Run 1 at a time for fastest individual completion**
```bash
python analysis/regret_analysis.py --all --visualize
python analysis/calibration_analysis.py --all --visualize
python analysis/risk_adjusted_returns.py --all --visualize
```

**Option B: Run 2 in parallel to maximize CPU usage**
```bash
# Terminal 1
python analysis/regret_analysis.py --all --visualize

# Terminal 2 (simultaneously)
python analysis/calibration_analysis.py --all --visualize

# After both complete:
python analysis/risk_adjusted_returns.py --all --visualize
```

**Output:** Regret rates, Brier scores, Sharpe ratios, comprehensive trader skill assessment

**Use case:** Weekly comprehensive analysis, trader ranking, ELO system input (future)

---

### Workflow 4: Complete Analysis (60-90 minutes)

**Purpose:** Run everything for comprehensive insights

**Phase 1: Fast tools in parallel (< 5 min)**
```bash
python analysis/trader_performance_analysis.py &
python analysis/trading_behavior_analysis.py &
python analysis/consensus_divergence_detector.py &
python analysis/trader_specialization_analysis.py &
wait
```

**Phase 2: Relationship analysis sequentially (10-15 min)**
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

**Use case:** Weekly/monthly comprehensive reports, system evaluation, new market launches

---

## CONFLICT RESOLUTION

### Metric Calculation Conflicts

**Issue:** Multiple tools calculate similar metrics (e.g., "win rate")

| Metric | Calculated By | Notes |
|--------|---------------|-------|
| Win Rate | trader_performance_analysis, regret_analysis, calibration_analysis, risk_adjusted_returns | May have slight differences in denominator |
| ROI/Return | trader_performance_analysis (simple), risk_adjusted_returns (portfolio) | Different calculation methods |
| Category Performance | trader_specialization_analysis (volume), calibration_analysis (Brier scores) | Different dimensions |

**Resolution:**
- **Win Rate:** Use result from your primary tool (all should be similar)
- **ROI:** Use `trader_performance_analysis` for quick overview, `risk_adjusted_returns` for accurate risk-adjusted metrics
- **Category:** Use `trader_specialization_analysis` for "where does trader focus?", use `calibration_analysis` for "where is trader accurate?"

**Future:** See AUDIT_REPORT.md Phase 6 for standardization recommendations.

---

### Output File Conflicts

**Issue:** Some tools may overwrite each other's output files

**Solution:** All tools write to unique filenames:
- regret_analysis.py → `analysis/output/regret_report.txt`, `regret_distribution.png`, etc.
- calibration_analysis.py → `analysis/output/calibration_report.txt`, `brier_distribution.png`, etc.
- risk_adjusted_returns.py → `analysis/output/risk_adjusted_report.txt`, `equity_curve.png`, etc.

**✓ No conflicts** - Each tool has its own namespace

---

## INTEGRATION OPPORTUNITIES

### Currently Integrated ✓

1. **correlation_matrix.py → copy_trade_detector.py**
   - Method: `export_for_integration()`
   - Data: High correlation pairs, independent traders
   - Status: ✅ Working

2. **copy_trade_detector.py → market_confidence_meter.py**
   - Method: `validate_signal_independence()`
   - Data: Independence validation for trader signals
   - Status: ✅ Working

### Recommended Integrations (Not Yet Implemented)

3. **calibration_analysis.py → weighted_consensus_system.py**
   - Method: Weight trader predictions by Brier scores
   - Benefit: More accurate ELO ratings
   - Priority: HIGH

4. **copy_trade_detector.py → weighted_consensus_system.py**
   - Method: Filter out copy-traders from ELO calculation
   - Benefit: ELO reflects genuine skill
   - Priority: HIGH

5. **risk_adjusted_returns.py → weighted_consensus_system.py**
   - Method: Adjust ELO K-factor by Sharpe ratio
   - Benefit: Stable ratings for consistent traders
   - Priority: MEDIUM

6. **calibration_analysis.py → market_confidence_meter.py**
   - Method: Weight predictions by Brier scores
   - Benefit: More accurate confidence scores
   - Priority: MEDIUM

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) Phase 4 for detailed integration implementations.

---

## PERFORMANCE OPTIMIZATION TIPS

### 1. Run Fast Tools First
Get quick insights while slow tools are running:
```bash
# Get basic stats immediately
python analysis/trader_performance_analysis.py

# Start slow tool in background
python analysis/calibration_analysis.py --all &

# View basic results while calibration runs
cat analysis/output/performance_report.txt
```

### 2. Use Multiprocessing for Independent Tools
```bash
# Run 4 independent tools simultaneously
python analysis/regret_analysis.py --all &
python analysis/calibration_analysis.py --all &
python analysis/trader_performance_analysis.py &
python analysis/trading_behavior_analysis.py &
wait
echo "All complete!"
```

### 3. Incremental Updates (Future Enhancement)
Currently all tools recalculate everything. Future optimization:
- Track last analyzed timestamp per trader
- Only recalculate traders with new trades
- Estimated speedup: 10-100x for daily updates

### 4. Filter to Specific Traders
Instead of `--all`, analyze specific traders:
```bash
# Fast: Analyze only top 10 traders by volume
python analysis/calibration_analysis.py --top 10

# Fast: Analyze specific trader
python analysis/regret_analysis.py --trader 0x1234567890abcdef
```

---

## SCHEDULER CONFIGURATION

### Current analysis_scheduler.py Status
⚠️ **Needs updating** - Does not include new tools (regret, calibration, risk-adjusted)

### Recommended Schedule

**Daily (Fast Tools + Resolved Market Tools):**
- 00:00: Check for new market resolutions
- If new resolutions exist:
  - 00:05: `trader_performance_analysis.py`
  - 00:10: `trading_behavior_analysis.py`
  - 00:15: `copy_trade_detector.py`
  - 00:30: `regret_analysis.py --all` (only on resolved markets)

**Weekly (Comprehensive Analysis):**
- Sunday 02:00: `calibration_analysis.py --all --report --visualize`
- Sunday 03:00: `risk_adjusted_returns.py --all --report --visualize`
- Sunday 04:00: `correlation_matrix.py` (export updated correlations)
- Sunday 04:30: `weighted_consensus_system.py` (update ELO ratings)

**Real-time (Continuous):**
- `market_confidence_meter.py` on active markets (every hour)
- `consensus_divergence_detector.py` on active markets (every 4 hours)

---

## TESTING COMPATIBILITY

All tools include test suites that can run simultaneously:

```bash
# Run all tests in parallel (safe)
python analysis/test_regret_analysis.py &
python analysis/test_calibration_analysis.py &
python analysis/test_risk_adjusted_returns.py &
wait
echo "All tests complete!"
```

**✓ No conflicts** - Test scripts create separate temporary databases

---

## TROUBLESHOOTING

### "Database is locked" Error
**Unlikely with analysis tools** (all are read-only), but if it occurs:

**Solution:**
```bash
# Close all analysis tools
pkill -f "analysis/"

# Wait 5 seconds
sleep 5

# Restart with 1 tool at a time
python analysis/your_tool.py
```

### Slow Performance When Running Multiple Tools
**Symptom:** System freezes, tools take much longer than expected

**Solution:**
```bash
# Option 1: Run fewer tools simultaneously
# Instead of running 5 CPU-intensive tools:
python analysis/regret_analysis.py --all &
python analysis/calibration_analysis.py --all &
wait  # Wait for these 2 to complete
python analysis/risk_adjusted_returns.py --all

# Option 2: Use nice to lower priority
nice -n 10 python analysis/calibration_analysis.py --all
```

### Out of Memory Errors
**Symptom:** "MemoryError" or system swap thrashing

**Solution:**
```bash
# Run tools sequentially instead of parallel
python analysis/regret_analysis.py --all
python analysis/calibration_analysis.py --all
python analysis/risk_adjusted_returns.py --all

# Or: Analyze fewer traders at a time
python analysis/calibration_analysis.py --top 50
```

---

## SUMMARY

**✅ All tools can run in parallel** from a database locking perspective (all are read-only)

**⚠️ Some tools have sequential dependencies:**
- correlation_matrix → copy_trade_detector → market_confidence_meter

**💡 Best Practice:**
- Run fast tools anytime in parallel
- Run slow tools (regret/calibration/risk-adjusted) in pairs or overnight
- Follow dependency chain for relationship analysis
- Use recommended workflows for common use cases

**🚀 Future Optimization:**
- Result caching with incremental updates (10-100x speedup)
- ELO integration with advanced metrics (more accurate ratings)
- Unified trader dashboard (single comprehensive report)

See [AUDIT_REPORT.md](./AUDIT_REPORT.md) for detailed integration roadmap.
