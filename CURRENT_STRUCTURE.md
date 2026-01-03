# Current Project Structure (Before Reorganization)

Generated: 2026-01-03

## Root Files Overview

### Documentation (Markdown Files)
| File | Size | Purpose | Status |
|------|------|---------|--------|
| README.md | 13KB | Main project overview | **KEEP - consolidate** |
| POLYMARKET_SETUP.md | 3.5KB | Setup instructions | **→ docs/SETUP.md** |
| SYSTEM_OBSERVER_GUIDE.md | 10.9KB | Observer system guide | **→ docs/SYSTEM_OBSERVER.md** |
| ELO_PERFORMANCE_OPTIMIZATION.md | 5.5KB | ELO optimization notes | **→ docs/ELO_SYSTEM.md** |
| TELEGRAM_CONFLICT_FIX_SUMMARY.md | 11.7KB | Telegram fix documentation | **→ docs/TROUBLESHOOTING.md** |
| TELEGRAM_FIX_TESTING.md | 6.3KB | Testing guide | **→ docs/TROUBLESHOOTING.md** |
| BACKFILL_COMPLETE.md | 5.4KB | Backfill completion notes | **→ archive/** |
| BACKFILL_INSTRUCTIONS.md | 10KB | Backfill instructions | **→ archive/** |
| ENHANCED_FILTERING_ADDED.md | 9.8KB | Feature notes | **→ archive/** |
| MARKET_ID_FIX_APPLIED.md | 8.2KB | Bug fix notes | **→ archive/** |
| REGRET_ANALYSIS_DELIVERY.md | 12.1KB | Analysis feature notes | **→ archive/** |
| RESOLUTION_DEBUG_LOGGING_ADDED.md | 6.1KB | Debug notes | **→ archive/** |
| RESOLUTION_FIX_COMPLETE.md | 7.7KB | Bug fix notes | **→ archive/** |
| SYSTEM_REVIEW_2025-11-30.md | 20KB | System review | **→ archive/** |

### Python Scripts (Root Level)
| File | Purpose | Status |
|------|---------|--------|
| agent_test.py | Test file | **→ scripts/** |
| analyze_market_categories.py | Market analysis | **→ scripts/** |
| debug_trade_detection.py | Debug script | **→ scripts/** |
| debug_trades.py | Debug script | **→ scripts/** |
| explore_events.py | Exploration script | **→ scripts/** |
| explore_markets.py | Exploration script | **→ scripts/** |
| get_telegram_chat_id.py | Telegram utility | **→ scripts/** |
| run_analysis.py | Analysis runner | **→ scripts/** |
| run_monitoring.py | Monitoring runner | **DELETE - use `python -m monitoring.main`** |
| test_data_api.py | API test | **→ scripts/** |
| test_filtering.py | Filter test | **→ scripts/** |
| test_polymarket.py | API test | **→ scripts/** |
| test_resolutions.py | Resolution test | **→ scripts/** |
| test_volume_tracking.py | Volume test | **→ scripts/** |

### Batch Files
| File | Purpose | Status |
|------|---------|--------|
| run_observer.bat | Start observer | **KEEP** |
| run_tracker.bat | Start monitoring | **KEEP** |

### Images/Charts
| File | Purpose | Status |
|------|---------|--------|
| equity_curve_0xAAAA1.png | Generated chart | **→ reports/** |
| return_dist_0xAAAA1.png | Generated chart | **→ reports/** |
| risk_return_scatter.png | Generated chart | **→ reports/** |
| top_traders_sharpe.png | Generated chart | **→ reports/** |

### Configuration Files
| File | Purpose | Status |
|------|---------|--------|
| .env | Environment variables | **KEEP** |
| .env.example | Example config | **KEEP** |
| .gitignore | Git ignore rules | **KEEP** |
| requirements.txt | Python dependencies | **KEEP** |

### Databases
| File | Purpose | Status |
|------|---------|--------|
| polymarket_tracker.db | Main database | **→ data/** |

## Directory Structure

### monitoring/ (Core Monitoring System)
**Status: Well organized, minimal changes needed**

#### Core System Files
- `__init__.py`, `__main__.py` - Package initialization ✅
- `main.py` - Entry point ✅
- `monitor.py` - Main monitoring loop ✅
- `database.py` - Database layer ✅
- `polymarket_client.py` - API client ✅

#### Telegram Integration
- `telegram_bot.py` - Main Telegram bot ✅
- `telegram_elo_bot.py` - ELO Telegram bot ✅
- `telegram_health_bot.py` - MISSING (referenced in docs) ❓
- `telegram_scheduler.py` - MISSING (referenced but disabled) ❓

#### ELO & Analysis Integration
- `elo_bridge.py` - ELO system bridge ✅
- `position_tracker.py` - Position tracking ✅

#### System Observer (Phase 1 & 2)
- `health_checker.py` - Health checks ✅
- `log_monitor.py` - Log analysis ✅
- `system_observer.py` - Observer orchestrator ✅
- `ai_analyzer.py` - AI analysis (Phase 2) ✅
- `ollama_client.py` - Ollama API wrapper ✅
- `performance_baselines.py` - Baseline learning ✅

#### Utility/Diagnostic Scripts
- `backfill_market_ids.py` - **→ scripts/**
- `check_closed_markets.py` - **→ scripts/**
- `check_market_resolutions.py` - **→ scripts/**
- `diagnose_resolution_matching.py` - **→ scripts/**
- `fast_resolution_check.py` - **→ scripts/**
- `refresh_markets.py` - **→ scripts/**
- `run_migration.py` - **→ scripts/**

#### Documentation
- `OFFICIAL_API_FIELDS_SUMMARY.md` - **→ docs/**
- `RESOLUTION_DETECTION_FINDINGS.md` - **→ archive/**
- `RESOLUTION_FIX_SUMMARY.md` - **→ archive/**

### analysis/ (ELO & Advanced Analytics)
**Status: HEAVILY DOCUMENTED, needs README consolidation**

#### Core Analysis Files
- `__init__.py` - Package initialization ✅
- `unified_elo_system.py` - Main ELO system ✅
- `analysis_scheduler.py` - Analysis scheduler ✅

#### Advanced Analysis Modules
- `calibration_analysis.py` - Calibration metrics ✅
- `consensus_divergence_detector.py` - Contrarian analysis ✅
- `composite_skill_score.py` - Composite scoring ✅
- `copy_trade_detector.py` - Copy trading detection ✅
- `correlation_matrix.py` - Correlation analysis ✅
- `market_confidence_meter.py` - Market confidence ✅
- `regret_analysis.py` - Regret analysis ✅
- `risk_adjusted_returns.py` - Risk metrics ✅
- `trader_behavior_analyzer.py` - Behavioral analysis ✅

#### Documentation (25 MD FILES!)
**URGENT: Too many READMEs**

##### Keep & Consolidate
- `README.md` - Main analysis README **→ docs/ELO_SYSTEM.md (merge)**
- `README_MASTER.md` - Master README **→ docs/ELO_SYSTEM.md (merge)**
- `ANALYSIS_README.md` - Analysis overview **→ docs/ELO_SYSTEM.md (merge)**
- `ANALYSIS_TOOLS_OVERVIEW.md` - Tools overview **→ docs/ELO_SYSTEM.md (merge)**
- `ELO_QUICKSTART.md` - Quick start **→ docs/ELO_SYSTEM.md (merge)**
- `ELO_UNIFICATION_SUMMARY.md` - ELO summary **→ docs/ELO_SYSTEM.md (merge)**
- `UNIFIED_ELO_SYSTEM.md` - System docs **→ docs/ELO_SYSTEM.md (merge)**

##### Archive (Historical/Completion Notes)
- `ADVANCED_METRICS_INTEGRATION.md` - **→ archive/**
- `ADVANCED_METRICS_SUMMARY.md` - **→ archive/**
- `AUDIT_REPORT.md` - **→ archive/**
- `BEHAVIORAL_ENHANCEMENT_SUMMARY.md` - **→ archive/**
- `BEHAVIORAL_INTEGRATION.md` - **→ archive/**
- `CACHING_IMPLEMENTATION.md` - **→ archive/**
- `CALIBRATION_ANALYSIS_README.md` - **→ archive/**
- `CATEGORY_BUG_FIX.md` - **→ archive/**
- `COMPATIBILITY_MATRIX.md` - **→ archive/**
- `COMPOSITE_SCORE_SUMMARY.md` - **→ archive/**
- `CONTRARIAN_INTEGRATION_SUMMARY.md` - **→ archive/**
- `DATA_FLOW.md` - **→ archive/**
- `NETWORK_ANALYSIS_INTEGRATION.md` - **→ archive/**
- `NETWORK_ANALYSIS_SUMMARY.md` - **→ archive/**
- `REGRET_ANALYSIS_QUICKSTART.md` - **→ archive/**
- `REGRET_ANALYSIS_README.md` - **→ archive/**
- `REGRET_CALCULATION_EXAMPLES.md` - **→ archive/**
- `RISK_ADJUSTED_RETURNS_README.md` - **→ archive/**
- `UTF8_FIX_SUMMARY.md` - **→ archive/**

### scripts/
**Status: Good organization, add root scripts here**

#### Migration Scripts
- `add_condition_id_column.py` ✅
- `backfill_market_ids.py` ✅
- `backfill_trade_results.py` ✅
- `build_positions_historical.py` ✅
- `migrate_add_comprehensive_elo.py` ✅
- `migrate_add_positions.py` ✅
- `migrate_add_trade_outcomes.py` ✅

#### Diagnostic Scripts
- `check_db_market_ids.py` ✅
- `check_elo_status.py` ✅
- `check_market_ids.py` ✅
- `check_markets_needing_fix.py` ✅
- `check_schema.py` ✅
- `diagnose_market_id_mismatch.py` ✅
- `investigate_resolutions.py` ✅

#### Test Scripts
- `test_api_id_format.py` ✅
- `test_calibration_fix.py` ✅
- `test_calibration_simple.py` ✅
- `test_comprehensive_stats.py` ✅
- `test_elo_caching.py` ✅
- `test_elo_integration_quick.py` ✅
- `test_elo_performance.py` ✅
- `test_end_to_end_integration.py` ✅
- `test_market_filtering.py` ✅
- `test_monitoring_integration_trigger.py` ✅
- `test_pnl_integration.py` ✅
- `test_pnl_simple.py` ✅
- `test_resolution_check.py` ✅
- `test_telegram_bot_integration.py` ✅
- `test_telegram_elo_bot.py` ✅
- `test_trade_evaluation.py` ✅
- `verify_elo_correctness.py` ✅
- `verify_telegram_fix.py` ✅

#### View/Report Scripts
- `view_pnl_performance.py` ✅
- `view_trader_rankings.py` ✅
- `view_trader_stats.py` ✅

#### Utility Scripts
- `recalculate_comprehensive_elo.py` ✅
- `recalculate_trader_stats.py` ✅
- `run_system_observer.py` ✅

### docs/
**Status: Exists but needs consolidation**

#### Current Files
- `API_RESOLUTION_STRUCTURE.md` - API docs **→ docs/API.md**
- `CALIBRATION_FIX_COMPLETION.md` - **→ archive/**
- `MONITORING_ELO_INTEGRATION.md` - **→ docs/MONITORING.md**
- `MONITORING_ELO_INTEGRATION_AUDIT.md` - **→ archive/**
- `MONITORING_ELO_INTEGRATION_DESIGN.md` - **→ docs/MONITORING.md**
- `PHASE_2_TEST_RESULTS.md` - **→ archive/**
- `PHASE_3_COMPLETION_REPORT.md` - **→ archive/**
- `PNL_INTEGRATION_SUMMARY.md` - **→ archive/**
- `POSITION_PNL_TRACKING.md` - **→ docs/MONITORING.md**
- `TELEGRAM_ELO_BOT_COMPLETION.md` - **→ archive/**
- `TELEGRAM_ELO_BOT_GUIDE.md` - **→ docs/MONITORING.md**
- `TELEGRAM_ELO_INTEGRATION_COMPLETE.md` - **→ archive/**
- `TRADER_STATISTICS_SYSTEM.md` - **→ docs/MONITORING.md**

### config/
**Status: Exists, verify contents**
- Files TBD

### data/
**Status: Good for database files**
- `polymarket_tracker.db` - Main database ✅

### reports/
**Status: Good for generated output**
- Generated reports, charts, caches ✅

## Issues Identified

### 1. README Explosion
- **25 markdown files in analysis/** alone
- **13 markdown files in docs/**
- **14 markdown files in root**
- **Total: 52 markdown files!**
- **Many are historical completion notes, not active documentation**

### 2. Misplaced Files
- **15+ Python scripts in root** should be in `scripts/`
- **8+ diagnostic scripts in monitoring/** should be in `scripts/`
- **Database file in root** should be in `data/`
- **Chart images in root** should be in `reports/`

### 3. Redundant Documentation
- Multiple READMEs covering same topics (ELO system, monitoring)
- Completion notes that could be archived (BACKFILL_COMPLETE, etc.)
- Historical integration summaries no longer needed for daily use

### 4. Missing Structure
- No clear entry point in root README
- Documentation scattered across 3 locations (root, docs/, analysis/)
- Hard to find "how to get started"

### 5. Duplicate/Similar Files
**Need Review:**
- `monitoring/backfill_market_ids.py` vs `scripts/backfill_market_ids.py`
- Multiple resolution checking scripts
- Multiple ELO test scripts

## Recommended Actions

### Immediate (Phase 1)
1. ✅ Create `archive/` directory
2. ✅ Move historical completion notes to archive
3. ✅ Move root Python scripts to `scripts/`
4. ✅ Move database to `data/`
5. ✅ Move images to `reports/`
6. ✅ Move monitoring diagnostic scripts to `scripts/`

### Documentation (Phase 2)
1. ✅ Consolidate analysis/ READMEs → `docs/ELO_SYSTEM.md`
2. ✅ Consolidate monitoring docs → `docs/MONITORING.md`
3. ✅ Create `docs/SETUP.md` from setup-related docs
4. ✅ Create `docs/SYSTEM_OBSERVER.md` from observer guide
5. ✅ Create `docs/TROUBLESHOOTING.md` from fix guides
6. ✅ Create `docs/API.md` from API docs
7. ✅ Rewrite root `README.md` as project overview with navigation

### Cleanup (Phase 3)
1. ✅ Review archive/ and confirm deletable
2. ✅ Remove duplicate files after verification
3. ✅ Update all import paths
4. ✅ Test all entry points still work
5. ✅ Create MIGRATION_GUIDE.md

## Statistics

- **Total Markdown Files**: 52
- **Files to Archive**: ~35 (historical notes)
- **Files to Keep**: ~17 (active docs)
- **Target Docs Structure**: 6-7 focused docs in `docs/`
- **Python Files to Move**: ~23 (from root + monitoring to scripts)
- **Estimated Cleanup**: ~40 file moves/consolidations

## Priority Level: HIGH

This reorganization will significantly improve:
- Discoverability (clear docs/ structure)
- Maintainability (less clutter)
- Onboarding (clear README + setup guide)
- Navigation (logical file organization)
