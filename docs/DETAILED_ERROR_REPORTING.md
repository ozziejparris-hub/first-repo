# Detailed Component-Specific Error Reporting - Implementation Guide

**Date:** 2026-01-04
**Status:** ✅ Phase 1-4 Complete, Phase 5 Pending
**Priority:** High

## Overview

Enhanced the System Observer with detailed, component-specific error reporting and diagnostics. The system can now identify WHICH component failed, WHAT the error was, and HOW to fix it.

## Implementation Status

### ✅ Phase 1: Enhanced Error Parsing (COMPLETE)

**Created:** `monitoring/error_parser.py`

**Capabilities:**
- Parses full error context from log lines
- Extracts component name, function, error type
- Captures multi-line stack traces
- Extracts trader addresses, market IDs, trade IDs
- Groups related errors by signature
- Tracks occurrences and first/last seen times

**Key Classes:**
```python
@dataclass
class ErrorDetail:
    timestamp: datetime
    level: str  # ERROR, WARNING, CRITICAL
    component: Optional[str]
    function: Optional[str]
    error_type: Optional[str]
    message: str
    stack_trace: List[str]
    context: Dict  # trader_address, market_id, trade_id
    occurrences: int
    first_seen: datetime
    last_seen: datetime

class ErrorParser:
    def parse_log_line(line: str) -> Optional[ErrorDetail]
    def parse_multiline_error(lines: List[str]) -> Optional[ErrorDetail]
    def get_recent_errors(minutes: int) -> List[ErrorDetail]
    def get_errors_by_component(minutes: int) -> Dict[str, List[ErrorDetail]]
    def get_top_errors(limit: int, minutes: int) -> List[Tuple[str, ErrorDetail]]
    def get_error_summary(minutes: int) -> Dict
```

### ✅ Phase 2: Error Classification (COMPLETE)

**Created:** `monitoring/error_classifier.py`

**Capabilities:**
- Matches errors against known issues database
- Provides suggested fixes
- Links to relevant documentation
- Categorizes by component and severity
- Formats detailed alert messages

**Known Issues Database:**
- `elo_method_not_found` - Method name mismatch in ELO analyzer
- `correlation_stuck` - Correlation matrix stuck at 99%
- `database_locked` - Multiple processes accessing database
- `position_matching_failed` - FIFO position matching error
- `ollama_not_running` - Ollama/Mistral AI service unavailable
- `mistral_model_missing` - Mistral model not downloaded
- `telegram_unauthorized` - Invalid bot token
- `telegram_chat_id_missing` - Chat ID not configured
- `market_resolution_not_found` - Market resolution data unavailable
- `calibration_no_data` - Insufficient data for calibration
- `api_rate_limit` - Polymarket API rate limit exceeded
- `memory_high` - High memory usage detected

**Key Classes:**
```python
@dataclass
class KnownIssue:
    name: str
    pattern: re.Pattern
    component: str
    severity: str  # critical, high, medium, low
    description: str
    fix: str
    docs: str

class ErrorClassifier:
    def classify_error(error: ErrorDetail) -> Dict
    def format_error_alert(error: ErrorDetail, classification: Dict) -> str
    def get_component_emoji(component: str) -> str
    def get_severity_emoji(severity: str) -> str
```

### ✅ Phase 3: Enhanced Log Monitor (COMPLETE)

**Modified:** `monitoring/log_monitor.py`

**New Methods:**
```python
def parse_detailed_error(line: str) -> Optional[ErrorDetail]
def get_detailed_error_summary(minutes: int) -> Dict
def get_component_health(minutes: int) -> Dict
def get_formatted_error_alerts(minutes: int) -> List[str]
def clear_old_errors(hours: int)
```

**Integration:**
- Uses `ErrorParser` for detailed context extraction
- Uses `ErrorClassifier` for known issue matching
- Provides component-specific health status
- Generates formatted alerts ready for Telegram

### ✅ Phase 4: Component-Specific Health Checks (COMPLETE)

**Modified:** `monitoring/health_checker.py`

**Existing Checks:**
- ✅ Process alive
- ✅ Database accessible
- ✅ Last activity
- ✅ Memory usage
- ✅ Error rate

**New Component Checks (Added):**

1. **`check_elo_system()`** - Tests ELO system functionality
   - Import unified_elo_system module
   - Initialize UnifiedELOSystem
   - Retrieve sample trader data
   - Calculate base ELO (lightweight test)

2. **`check_position_tracker()`** - Tests position matching
   - Import position_tracker module
   - Initialize PositionTracker
   - Query trade data
   - Perform basic FIFO matching

3. **`check_market_filter()`** - Tests market filtering
   - Import market_filter module
   - Verify keyword filtering
   - Test Ollama connectivity (optional)
   - Check Mistral model availability (optional)

4. **`check_database_operations()`** - Tests database operations
   - Verify database file exists
   - Check WAL mode enabled
   - Test read operations
   - Test write operations
   - Measure query performance

5. **`check_telegram_bots()`** - Tests Telegram connectivity
   - Verify bot token configured
   - Verify chat ID configured
   - Test telegram module import
   - Validate bot token (optional network call)

**Integration:**
- Updated `check_all()` to include component checks
- All component results included in health report
- Component failures reflected in overall status

### 🔄 Phase 5: Enhanced Alerts & Reports (PENDING)

**File:** `monitoring/telegram_health_bot.py`

**To Add:**
```python
async def send_component_error_alert(error_details: ErrorDetail, classification: Dict):
    """Send detailed component-specific error alert"""
    # Use ErrorClassifier.format_error_alert()
    # Include suggested fixes
    # Link to documentation

async def send_hourly_report_enhanced(metrics: Dict, component_health: Dict):
    """Enhanced hourly report with component breakdown"""
    # Show health by component
    # Top errors by component
    # Performance trends
```

## Example Output

### Current Alert (Before Enhancement):
```
⚠️ SYSTEM HEALTH WARNING
Issues detected:
  • errors: 3 errors in last 10m
```

### Enhanced Alert (After Implementation):
```
🟠 KNOWN ISSUE: ELO System 🎯

Component: analysis/risk_adjusted_analysis.py
Function: calculate_advanced_metrics_multiplier()
Trader: 0x5248313...d28aa2

Error Type: AttributeError
Message: 'RiskAdjustedAnalyzer' object has no attribute 'analyze_all_traders'

Stack Trace:
  monitoring/elo_bridge.py:342 in quick_elo_update_for_traders()
  analysis/unified_elo_system.py:517 in calculate_elo_ratings()
  analysis/risk_adjusted_analysis.py:89 in calculate_advanced_metrics_multiplier()

First Occurrence: 21:15:34
Occurrences: 3 times

💡 Suggested Fix:
  Update method call to use correct API. Check analyzer class for available methods.

📚 Docs: docs/ELO_SYSTEM.md
```

### Enhanced Hourly Report:
```
📊 HOURLY STATUS REPORT

System: HEALTHY ✅
Uptime: 1.0h
Memory: 4 MB

Component Health:
  ✅ ELO System: Healthy
  ✅ Position Tracker: Healthy
  ✅ Market Filter: Healthy
  ⚠️  Database: Slow queries (avg 250ms)
  ✅ Telegram Bots: Healthy

Errors by Component (last hour):
  • ELO System: 3 errors (AttributeError in risk_adjusted_analysis)
  • Database: 1 warning (lock timeout)

Top Errors:
  1. risk_adjusted_analysis.py:89 - AttributeError (3x)
  2. database.py:234 - OperationalError (1x)

Performance Trends:
  • ELO calculation time: 6.2s avg (up 15% from baseline)
  • Database queries: 0.25s avg (up 40% from baseline)

Next report: 22:00
```

## Usage Examples

### Parse Error from Log Line
```python
from monitoring.log_monitor import LogMonitor

monitor = LogMonitor('logs/monitoring.log')

# Parse single line
line = "2026-01-04 21:15:34 - ERROR - [ELO] AttributeError: 'RiskAdjustedAnalyzer' object has no attribute 'analyze_all_traders'"
error = monitor.parse_detailed_error(line)

if error:
    print(f"Component: {error.component}")
    print(f"Error Type: {error.error_type}")
    print(f"Message: {error.message}")
```

### Get Component Health
```python
# Get health status by component
component_health = monitor.get_component_health(minutes=60)

for component, health in component_health.items():
    print(f"{component}: {health['status']} ({health['error_count']} errors)")
```

### Get Formatted Alerts
```python
# Get ready-to-send alerts
alerts = monitor.get_formatted_error_alerts(minutes=10)

for alert in alerts:
    print(alert)
    print("=" * 70)
```

### Classify Error
```python
from monitoring.error_classifier import ErrorClassifier

classifier = ErrorClassifier()

# Classify error
classification = classifier.classify_error(error)

print(f"Component: {classification['component']}")
print(f"Severity: {classification['severity']}")
print(f"Known Issue: {classification['known_issue']}")
print(f"Fix: {classification['suggested_fix']}")
print(f"Docs: {classification['relevant_docs']}")
```

## Testing

### Test Error Parsing
```python
# Test with sample error line
test_line = """2026-01-04 21:15:34 - ERROR - [ELO] AttributeError in risk_adjusted_analysis.py: 'RiskAdjustedAnalyzer' object has no attribute 'analyze_all_traders'
Trader: 0x5248313731287b61d714ab9df655442d6ed28aa2"""

monitor = LogMonitor()
error = monitor.parse_detailed_error(test_line)

assert error.component == 'ELO'
assert error.error_type == 'AttributeError'
assert 'trader_address' in error.context
```

### Test Known Issue Matching
```python
classifier = ErrorClassifier()

# Create test error
error = ErrorDetail(
    timestamp=datetime.now(),
    level='ERROR',
    message="'RiskAdjustedAnalyzer' object has no attribute 'calculate_metric'"
)

classification = classifier.classify_error(error)

assert classification['known_issue'] == 'elo_method_not_found'
assert classification['severity'] == 'high'
assert 'Update method call' in classification['suggested_fix']
```

## Component Keywords

The error classifier uses these keywords to detect components:

- **ELO System:** elo, unified_elo, calibration, behavioral, risk_adjusted, network, contrarian, composite
- **Position Tracker:** position, fifo, pnl, p&l
- **Market Filter:** market_filter, keyword, ai, mistral, ollama
- **Trade Evaluator:** trade_evaluator, resolution, outcome
- **Database:** database, sqlite, sql, wal
- **Telegram Bot:** telegram, bot, notification
- **Polymarket API:** polymarket, api, clob
- **System Observer:** observer, health, monitoring

## Next Steps

### 1. Complete Component-Specific Health Checks

Add to `monitoring/health_checker.py`:
```python
async def check_all_components(self) -> Dict:
    """Run all component-specific health checks"""
    return {
        'elo_system': await self.check_elo_system(),
        'position_tracker': await self.check_position_tracker(),
        'market_filter': await self.check_market_filter(),
        'database_ops': await self.check_database_operations(),
        'telegram_bots': await self.check_telegram_bots()
    }
```

### 2. Enhance Telegram Alerts

Modify `monitoring/telegram_health_bot.py`:
```python
async def send_detailed_error_alert(self, error: ErrorDetail, classification: Dict):
    """Send formatted error alert with all details"""
    alert_text = self.error_classifier.format_error_alert(error, classification)
    await self.send_message(alert_text)
```

### 3. Update Hourly Reports

Modify `monitoring/system_observer.py` `_collect_metrics()`:
```python
# Get component health
component_health = self.log_monitor.get_component_health(minutes=60)

# Get detailed error summary
error_summary = self.log_monitor.get_detailed_error_summary(minutes=60)

# Include in metrics
metrics['component_health'] = component_health
metrics['error_details'] = error_summary
```

### 4. Create Test Script

Create `scripts/test_detailed_error_reporting.py`:
```python
#!/usr/bin/env python3
"""Test detailed error reporting system"""

# Test error parsing
# Test classification
# Test known issue matching
# Test component health
# Test formatted alerts
```

## Files Created/Modified

| File | Status | Purpose |
|------|--------|---------|
| `monitoring/error_parser.py` | ✅ Created | Parse errors with full context |
| `monitoring/error_classifier.py` | ✅ Created | Classify errors, match known issues |
| `monitoring/log_monitor.py` | ✅ Enhanced | Integrate error parser/classifier |
| `monitoring/health_checker.py` | ✅ Enhanced | Add component-specific checks |
| `scripts/test_component_health_checks.py` | ✅ Created | Test component checks |
| `monitoring/telegram_health_bot.py` | 🔄 Pending | Enhanced alert formatting |
| `monitoring/system_observer.py` | 🔄 Pending | Use enhanced reporting |
| `docs/DETAILED_ERROR_REPORTING.md` | ✅ Created | This document |

## Benefits

### Before
- ❌ Generic "3 errors detected" messages
- ❌ No component identification
- ❌ No suggested fixes
- ❌ Manual log diving required
- ❌ No error grouping

### After
- ✅ Specific component/function identification
- ✅ Error type and stack traces
- ✅ Suggested fixes for known issues
- ✅ Links to relevant documentation
- ✅ Trader/market context extraction
- ✅ Error grouping and occurrence tracking
- ✅ Component-specific health status

## Related Documentation

- [SYSTEM_OBSERVER.md](SYSTEM_OBSERVER.md) - System Observer overview
- [ELO_SYSTEM.md](ELO_SYSTEM.md) - ELO system details
- [DATABASE_LOCK_DEEP_FIX.md](DATABASE_LOCK_DEEP_FIX.md) - Database fixes
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Troubleshooting guide
- [LOGGING_FIX.md](LOGGING_FIX.md) - Logging configuration

---

**Implementation:** Phase 1-4 Complete (2026-01-04)
**Remaining:** Phase 5 (Enhanced alerts & reports - optional)
**Impact:** High - Dramatically improves error diagnostics and troubleshooting

## Phase 4 Summary

Successfully implemented 5 component-specific health checks:

1. ✅ **ELO System Check** - Tests ELO calculation pipeline
2. ✅ **Position Tracker Check** - Tests FIFO matching logic
3. ✅ **Market Filter Check** - Tests keyword + AI filtering
4. ✅ **Database Operations Check** - Tests WAL mode, read/write, performance
5. ✅ **Telegram Bots Check** - Tests configuration and connectivity

All checks integrated into `check_all()` method and return consistent format.

**Test Script:** `scripts/test_component_health_checks.py`

**Run Test:**
```bash
python scripts/test_component_health_checks.py
```
