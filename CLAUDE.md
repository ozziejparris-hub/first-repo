# Polymarket Trader Monitoring System — Claude Code Context

## What This Is

Real-time Polymarket prediction market monitoring system that:
- Polls the Polymarket API every 15 minutes to track ~1,957 traders
- Calculates 6-dimensional ELO ratings with behavioral analysis (Kelly criterion, patience metrics, market difficulty weighting)
- Sends Telegram alerts for elite trader activity
- Runs AI-powered health monitoring via Mistral/Ollama (system observer)

**Stack:** Python 3.10+, SQLite, systemd services, Telegram Bot API, Polymarket REST API

---

## Database

| Property | Value |
|----------|-------|
| **Location** | `data/polymarket_tracker.db` (symlinked at `monitoring/polymarket_tracker.db`) |
| **Size** | ~1.6 GB (as of April 2026) |
| **Tables** | `traders` (1,957 rows), `trades` (997K+ rows), `markets` (213K rows), `positions` |

**WARNING: Do not delete or overwrite the database.** It contains 6+ months of trade history that cannot be recovered from the API. Before any operation that writes to the DB, take a backup: `python scripts/backup_database.py`.

---

## Services (systemd)

Two systemd services run the production system:

| Service | Description |
|---------|-------------|
| `polymarket-monitoring` | Core 15-minute monitor loop |
| `polymarket-observer` | AI health monitor (watches the monitoring service) |

### Common Commands

```bash
# Status
sudo systemctl status polymarket-monitoring
sudo systemctl status polymarket-observer

# Logs (live tail)
sudo journalctl -u polymarket-monitoring -f
sudo journalctl -u polymarket-observer -f

# Start / Stop / Restart
sudo systemctl start polymarket-monitoring
sudo systemctl stop polymarket-monitoring
sudo systemctl restart polymarket-monitoring

sudo systemctl start polymarket-observer
sudo systemctl stop polymarket-observer
sudo systemctl restart polymarket-observer
```

### Checking what's running (Python)

```bash
python scripts/check_processes.py   # Shows PID status, CPU/memory
python scripts/check_monitoring.py  # Quick health check
```

### Stop everything at once

```bash
python scripts/kill_all.py   # Stops all monitoring + observer processes, cleans PID files
```

---

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/start_monitoring.py` | Starts monitoring with PID locking (use this, not direct module) |
| `scripts/run_system_observer.py` | Starts health observer |
| `scripts/kill_all.py` | Stops all processes cleanly |
| `scripts/check_processes.py` | Shows running process status |
| `scripts/backup_database.py` | Creates timestamped DB backup |
| `scripts/view_trader_rankings.py` | Prints current ELO leaderboard |
| `scripts/view_pnl_performance.py` | Shows P&L stats |
| `scripts/integrate_behavioral_elo.py` | Runs full ELO re-integration pipeline |
| `scripts/update_database_from_csvs.py` | Imports analysis CSV results to DB |
| `scripts/recalculate_comprehensive_elo.py` | Recalculates all ELO scores |
| `scripts/daily_maintenance.py` | Daily cleanup and backfill tasks |

### Key Modules

| Module | Purpose |
|--------|---------|
| `monitoring/main.py` | Core monitor orchestrator |
| `monitoring/monitor.py` | `PolymarketMonitor` class — the 15-min loop |
| `monitoring/database.py` | All SQLite operations |
| `monitoring/position_tracker.py` | FIFO P&L tracking |
| `monitoring/telegram_bot.py` | Send-only Telegram notifications |
| `monitoring/system_observer.py` | AI health monitoring logic |
| `analysis/unified_elo_system.py` | 6-dimensional ELO engine |
| `analysis/trading_behavior_analysis.py` | Kelly, patience, timing analysis |
| `analysis/analysis_scheduler.py` | Schedules periodic analysis runs |

---

## Environment & Config

- Env vars loaded from `/home/parison/.env_trading` (referenced in systemd unit files)
- Config overrides in `config/elo_update_settings.json`
- Telegram config in `monitoring/telegram_bot_config.py`

---

## Current System State (as of April 18 2026)

**Server migration in progress.** A 48-hour parallel run started April 18 2026, with both the old and new server environments running simultaneously to validate the migration.

**Do not stop the monitoring service or observer without first checking whether the parallel run is still active.** Stopping either service mid-parallel-run could invalidate the comparison data and require restarting the 48-hour window from scratch.

To check parallel run status before stopping anything, confirm with the user or check recent logs for any `[PARALLEL]` / `[MIGRATION]` markers:

```bash
sudo journalctl -u polymarket-monitoring --since "2026-04-18" | grep -i "parallel\|migration\|server"
```

---

## Important Warnings

1. **Don't delete `data/polymarket_tracker.db`** — irreplaceable historical data, no API recovery path.
2. **Don't stop services during the parallel run** (underway as of April 18 2026) without confirming the 48-hour window has completed.
3. **Don't run duplicate monitoring processes** — the system uses PID file locking, but force-killing and restarting can leave stale locks. Always use `scripts/kill_all.py` to stop cleanly.
4. **Timing quality is intentionally disabled** — the `created_at` column doesn't exist in the markets table; all traders receive a neutral timing score. Don't re-enable it without adding the column first.
5. **Telegram is send-only** — no webhooks, no polling. Conflicts were fixed in Jan 2026; don't reintroduce webhook mode.

---

## Architecture Summary

```
Polymarket API
    ↓ (every 15 min)
monitoring/monitor.py  →  monitoring/database.py (SQLite)
    ↓                            ↓
monitoring/telegram_bot.py   analysis/ (ELO, behavioral, P&L)
    ↓
Telegram alerts (elite traders only)

monitoring/system_observer.py  →  Mistral/Ollama (local)
    ↓
Telegram health alerts
```

---

## Useful One-Liners

```bash
# Check DB size
ls -lh data/polymarket_tracker.db

# Count trades in DB
sqlite3 data/polymarket_tracker.db "SELECT COUNT(*) FROM trades;"

# Top 10 traders by ELO
python scripts/view_trader_rankings.py | head -20

# Check if monitoring is catching up after downtime
sudo journalctl -u polymarket-monitoring --since "1 hour ago" | tail -50

# Run full analysis pipeline (takes 5-15 min)
python scripts/integrate_behavioral_elo.py
```
