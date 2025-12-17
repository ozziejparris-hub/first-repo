# System Health Observer - User Guide

## Overview

The System Health Observer is an AI-powered watchdog that monitors your Polymarket monitoring system 24/7. It detects issues, sends alerts, and provides real-time insights into system health.

## Features

### 🏥 Health Monitoring
- **Process Alive Check**: Ensures monitoring is running
- **Database Accessibility**: Verifies database queries work
- **Activity Tracking**: Detects if system is stuck (>20min no activity)
- **Memory Usage**: Warns if memory exceeds 500MB
- **Error Rate**: Monitors error frequency in logs

### 📊 Real-time Log Analysis
- Tail logs continuously (like `tail -f`)
- Detect ERROR and CRITICAL messages
- Identify known issues:
  - Stuck correlation matrix calculations
  - No market resolutions for extended periods
  - ELO calculation errors
  - Database lock issues

### 📱 Telegram Alerts
- ⚠️ Health warnings (degraded performance)
- ❌ Critical errors (system failures)
- 🔧 Known issue detection (with suggested fixes)
- 📊 Hourly status reports
- 🚀 Startup/shutdown notifications

### 📈 Performance Tracking
- Trades checked per hour
- API call frequency
- Database query times
- ELO update rates

## Installation

### Prerequisites
- Python 3.7+
- Telegram bot token (use existing PredictionAlerts_bot)
- Required packages:
  ```bash
  pip install psutil python-telegram-bot python-dotenv
  ```

### Configuration

Add to your `.env` file:
```env
telegram_alerts_token=your_bot_token_here
telegram_chat_id=your_chat_id_here
```

## Usage

### Starting the Observer

**Option 1: Auto-detect monitoring process**
```bash
python scripts/run_system_observer.py
```

**Option 2: Specify monitoring PID**
```bash
# Find monitoring PID first
ps aux | grep monitor.py

# Then run observer with PID
python scripts/run_system_observer.py --pid 12345
```

**Option 3: Test mode (no Telegram)**
```bash
python scripts/run_system_observer.py --no-telegram
```

### Running as Background Service

**Linux/Mac:**
```bash
# Using nohup
nohup python scripts/run_system_observer.py > observer.log 2>&1 &

# Using screen
screen -S observer
python scripts/run_system_observer.py
# Ctrl+A, D to detach
```

**Windows:**
```powershell
# Using Start-Process
Start-Process python -ArgumentList "scripts\run_system_observer.py" -WindowStyle Hidden
```

### Stopping the Observer

```bash
# Find observer PID
ps aux | grep run_system_observer.py

# Stop gracefully (sends shutdown notification)
kill -SIGINT <observer_pid>

# Or just Ctrl+C if running in foreground
```

## Telegram Message Examples

### Health Warning
```
⚠️ SYSTEM HEALTH WARNING

Issues detected:
  • memory: Memory usage high: 487.2 MB (>500MB)
  • activity: Last activity 12m ago (>5m)

Process: 12345 (python)
Memory: 487.2 MB
Last activity: 12m ago
Recent errors: 3 in last 10m

Status: WARNING
Time: 2025-12-14 15:45:23
```

### Error Alert
```
❌ ERROR DETECTED

Type: generic_error
Severity: ERROR

Message:
ERROR - ELO calculation failed for trader 0x5248313731287b61d714ab9df655442d6ed28aa2:
'RiskAdjustedAnalyzer' object has no attribute 'analyze_all_traders'

Time: 2025-12-14 15:45:23
```

### Known Issue Alert
```
🔧 KNOWN ISSUE DETECTED

Issue: Correlation matrix calculation stuck
Type: correlation_stuck

Details:
  • progress: 16590050/16666651
  • progress_pct: 99.5%
  • stuck_count: 5

Suggested action:
  Consider restarting with --skip-correlation

Time: 2025-12-14 15:45:23
```

### Hourly Status Report
```
📊 HOURLY STATUS REPORT

System: HEALTHY ✅
Uptime: 4.2h
Memory: 342 MB

Activity (last hour):
  • Trades checked: 156
  • Markets scanned: 1,243
  • ELO updates: 23
  • API calls: 2,847

Errors: 0 ✅
Performance: GOOD ✅
Next report: 16:45
```

## Architecture

### Components

1. **HealthChecker** (`monitoring/health_checker.py`)
   - Performs system health checks
   - Returns health status: healthy, warning, critical

2. **LogMonitor** (`monitoring/log_monitor.py`)
   - Tails log files in real-time
   - Detects error patterns
   - Identifies known issues

3. **TelegramHealthBot** (`monitoring/telegram_health_bot.py`)
   - Sends formatted alerts via Telegram
   - Rate limiting (prevents spam)
   - Multiple alert types

4. **SystemObserver** (`monitoring/system_observer.py`)
   - Main orchestrator
   - Runs three async loops:
     - Health check loop (every 60s)
     - Log monitor loop (continuous)
     - Hourly report loop (every hour)

### Data Flow

```
┌─────────────────────┐
│  Monitoring System  │
│    (monitor.py)     │
└──────────┬──────────┘
           │
           │ PID, Logs, DB
           ▼
┌─────────────────────────────────────┐
│      System Observer                │
│  ┌─────────────────────────────┐  │
│  │  Health Checker             │  │
│  │  • Process alive            │  │
│  │  • Database accessible      │  │
│  │  • Activity check           │  │
│  │  • Memory usage             │  │
│  │  • Error rate               │  │
│  └─────────────┬───────────────┘  │
│                │                   │
│  ┌─────────────▼───────────────┐  │
│  │  Log Monitor                │  │
│  │  • Tail logs                │  │
│  │  • Detect errors            │  │
│  │  • Known issues             │  │
│  └─────────────┬───────────────┘  │
│                │                   │
│  ┌─────────────▼───────────────┐  │
│  │  Telegram Bot               │  │
│  │  • Health alerts            │  │
│  │  • Error alerts             │  │
│  │  • Hourly reports           │  │
│  └─────────────────────────────┘  │
└──────────────┬──────────────────────┘
               │
               ▼
        ┌──────────────┐
        │   Telegram   │
        │ PredictionAlerts_bot │
        └──────────────┘
```

## Troubleshooting

### Observer won't start

**Problem**: "ERROR: Telegram credentials not found in .env"

**Solution**: Add credentials to `.env`:
```env
telegram_alerts_token=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
telegram_chat_id=123456789
```

**Problem**: "Could not find monitoring process"

**Solution**:
- Ensure monitoring is running: `ps aux | grep monitor.py`
- Provide PID manually: `--pid <PID>`
- Or continue without PID (limited health checks)

### Not receiving Telegram messages

**Problem**: No alerts appearing in Telegram

**Checks**:
1. Verify bot token is correct: `telegram_alerts_token` in `.env`
2. Verify chat ID is correct: `telegram_chat_id` in `.env`
3. Check bot has permission to send messages to that chat
4. Look for errors in observer output: `[TELEGRAM] Error sending message`

**Rate Limiting**: Observer rate-limits alerts to prevent spam:
- Health warnings: 1 per 10 minutes
- Error alerts: 1 per 5 minutes
- Known issues: 1 per issue type per 15 minutes

### High memory usage warnings

**Problem**: Getting repeated memory warnings

**Solution**:
1. Check actual monitoring process memory: `ps aux | grep monitor.py`
2. If legitimately high, consider:
   - Reducing cache sizes
   - Restarting monitoring periodically
   - Investigating memory leaks

### False positives

**Problem**: Getting alerts for non-issues

**Solution**: Adjust thresholds in `health_checker.py`:
```python
# Memory threshold (line ~234)
if memory_mb < 500:  # Increase if needed
    status = 'healthy'
```

## Advanced Configuration

### Customizing Health Check Intervals

Edit `system_observer.py`:
```python
# Health check interval (line ~110)
await asyncio.sleep(60)  # Change from 60s to your preference

# Hourly report interval (line ~189)
if (now - self.last_hourly_report).total_seconds() >= 3600:  # Change from 3600s (1h)
```

### Adding Custom Error Patterns

Edit `log_monitor.py`:
```python
self.error_patterns = {
    'generic_error': re.compile(r'ERROR.*', re.IGNORECASE),
    'critical': re.compile(r'CRITICAL.*', re.IGNORECASE),
    # Add your custom patterns:
    'my_pattern': re.compile(r'MyCustomError.*'),
}
```

### Adding Custom Known Issues

Edit `log_monitor.py`:
```python
self.known_issues = {
    'my_issue': {
        'pattern': re.compile(r'My issue pattern'),
        'description': 'Description of the issue',
        'action': 'What to do about it'
    }
}
```

## Best Practices

### 1. Run Observer Alongside Monitoring
Always run the observer when running the monitoring system:
```bash
# Terminal 1: Start monitoring
python -m monitoring.monitor

# Terminal 2: Start observer
python scripts/run_system_observer.py
```

### 2. Monitor the Observer
The observer itself should be monitored:
```bash
# Check if observer is running
ps aux | grep run_system_observer

# View observer logs
tail -f observer.log
```

### 3. Respond to Alerts Promptly
- 🟢 **Healthy**: No action needed
- 🟡 **Warning**: Monitor closely, prepare to intervene
- 🔴 **Critical**: Immediate action required

### 4. Review Hourly Reports
Use hourly reports to:
- Track system performance trends
- Identify recurring issues
- Plan maintenance windows

### 5. Test Regularly
Run observer in test mode to verify functionality:
```bash
python scripts/run_system_observer.py --no-telegram
```

## Future Enhancements (Phase 2)

Planned features for Phase 2:
- 🤖 AI-powered anomaly detection (Mistral/Ollama)
- 📈 Performance trend analysis
- 🔮 Predictive alerting (predict failures before they happen)
- 📊 Web dashboard for visualizations
- 🔧 Auto-remediation (restart stuck processes)
- 📝 Detailed health reports (daily/weekly summaries)

## Support

For issues or questions:
1. Check this guide first
2. Review observer logs
3. Check Telegram bot logs
4. Verify environment configuration

## License

Part of the Polymarket Monitoring System.
