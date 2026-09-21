# Polymarket Trader Monitoring System — Claude Code Context

## What This Is

Real-time Polymarket prediction market monitoring system that:
- Polls the Polymarket API every 15 minutes to track traders (198,699 as of 2026-09-13; the "~87,000" figure below and elsewhere in this file is a stale April 2026 snapshot — verify row counts before relying on any number in this file, see "Known Documentation Gaps" below)
- Calculates 6-dimensional ELO ratings; behavioral analysis (Kelly criterion, patience metrics, market difficulty/timing) is still **computed** but contributes **zero** to the score — `W_BEH=0.0`, tested and found null, decided 2026-07-12 (Stage 0b), not a bug
- Sends Telegram alerts for the geo/elec pending-backlog condition and health-check degradation; the "elite trader activity" (LEGENDARY-tier) alert this line used to describe was retired/silenced 2026-09-09 ("final Telegram cut")
- **[DORMANT INTENT — not currently wired, do not delete]** AI-powered health monitoring via a local LLM (Mistral/Ollama) is a wanted capability, not live. Two prior attempts exist and are both dead: `monitoring/ai_analyzer.py`'s `AIAnalyzer`/`OllamaClient` (zero callers anywhere) and `monitoring/main.py`'s separate Pydantic-AI-via-Ollama agent (dead because `main.py` itself is not the live entrypoint — see Key Modules below). `system_observer.py` itself contains no reference to Ollama, Mistral, or AIAnalyzer today. Local-LLM/agentic work is planned as a dedicated effort, expected to live mainly in trading-swarm — see `brain/decisions/2026-09-13-built-never-connected-sweep.md`.

**Stack:** Python 3.10+, SQLite, systemd services, Telegram Bot API, Polymarket REST API

---

## Database

| Property | Value |
|----------|-------|
| **Location** | `data/polymarket_tracker.db` (symlinked at `monitoring/polymarket_tracker.db`) |
| **Size** | ~21 GB (as of 2026-09-13; the "~1.6 GB / April 2026" figure previously here was stale by ~19GB — check `ls -lh` rather than trust a number in this file) |
| **Tables** | `traders` (198,699 rows), `trades` (14,460,577 rows), `markets` (878,646 rows), `positions` (9,661,891 rows) — all as of 2026-09-13, all previously understated here by 2-9x |

**WARNING: Do not delete or overwrite the database.** It contains 6+ months of trade history that cannot be recovered from the API. Before any operation that writes to the DB, take a backup: `python scripts/backup_database.py`.

---

## Services (systemd)

Two systemd services run the production system:

| Service | Description |
|---------|-------------|
| `polymarket-monitoring` | Core 15-minute monitor loop |
| `polymarket-observer` | Health monitor (watches the monitoring service). Despite the name, this does **not** currently do AI-powered analysis — see "Known Documentation Gaps" |

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
# check_processes.py and check_monitoring.py have moved to scripts/archive/
# and are broken from there (hardcoded project-root path assumption breaks
# one directory deeper) -- not runnable as documented. Use instead:
sudo systemctl status polymarket-monitoring polymarket-observer
python scripts/check_processes.py   # NOT RUNNABLE — see note above
python scripts/check_monitoring.py  # NOT RUNNABLE — see note above
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
| `scripts/check_processes.py` | **NOT RUNNABLE** — moved to `scripts/archive/`, broken from there (see note above); use `systemctl status` instead |
| `scripts/backup_database.py` | Creates timestamped DB backup |
| `scripts/view_trader_rankings.py` | Prints current ELO leaderboard |
| `scripts/view_pnl_performance.py` | Shows P&L stats |
| ~~`scripts/integrate_behavioral_elo.py`~~ | **DELETED** 2026-07-12 (`61adaf5`, "Stage 0c — delete dead Writer C", deliberate decision, well documented) — do not reference as runnable |
| `scripts/update_database_from_csvs.py` | **NOT RUNNABLE** — moved to `scripts/archive/`, not confirmed to still function from there |
| `scripts/recalculate_comprehensive_elo.py` | Recalculates all ELO scores |
| `scripts/daily_maintenance.py` | Daily cleanup and backfill tasks (Step 0: update_research_exclusions) |
| `scripts/update_research_exclusions.py` | Propagates `research_excluded` flag — runs as Step 0 of daily_maintenance before any ELO work |

### Key Modules

| Module | Purpose |
|--------|---------|
| `monitoring/main_telegram_safe.py` | Core monitor orchestrator — this is the module `scripts/start_monitoring.py` actually imports and runs. `monitoring/main.py` exists but is **not** the live entrypoint (superseded; referenced today only by an archived test) — do not confuse the two |
| `monitoring/monitor.py` | `PolymarketMonitor` class — the 15-min loop |
| `monitoring/database.py` | All SQLite operations |
| `monitoring/position_tracker.py` | FIFO P&L tracking |
| `monitoring/telegram_health_bot.py` | Send-only Telegram notifications — `TelegramHealthBot`, actually instantiated by `system_observer.py`. `monitoring/telegram_bot.py`'s `TelegramNotifier` class is the **old interactive/polling bot, dead code since the Jan-2026 send-only redesign** — do not use as the reference for current Telegram behavior |
| `monitoring/system_observer.py` | Health monitoring / alerting logic. **Does not currently include AI/Ollama analysis** — see the dormant-intent note above |
| `analysis/unified_elo_system.py` | 6-dimensional ELO engine |
| `analysis/trading_behavior_analysis.py` | Kelly, patience, timing analysis |
| `analysis/analysis_scheduler.py` | Schedules periodic analysis runs |

---

## Environment & Config

- Env vars loaded from `/home/parison/.env_trading` (referenced in systemd unit files)
- `config/elo_update_settings.json` exists but has **zero programmatic readers anywhere in the codebase** — editing it currently has no effect. Its `telegram_notifications` block (`enabled`/`send_leaderboard`/`hourly_mini_leaderboard`: all `true`) also **contradicts** actual behavior — those features were hardcoded silent 2026-09-09. Treat this file as non-authoritative until/unless something reads it again.
- Telegram config in `config/telegram_bot_config.py` (not `monitoring/telegram_bot_config.py` — that path does not exist)

---

## Current System State (as of April 30 2026)

**[STALE — this section was written 2026-04-30 and has not been re-verified since. Several figures below (e.g. the research_excluded pool size) are known to be far out of date — e.g. the "857 traders" clean-pool figure below was 43,176 as of 2026-09-13. Treat every number in this section as historical, not current, unless independently re-checked.]**

**Server migration complete.** The 48-hour parallel run (started April 18, completed ~April 20) finished successfully. Both services are running on the new server.

**Trade gap on record:** The monitoring service was effectively down April 7–18 2026 (near-zero trade collection: 1–6 trades/day vs 500+ normal). Markets resolving during this window have incomplete trade data. These are flagged in the `markets` table with `trade_gap_flag = 1`. Exclude them from time-series analysis:
```sql
AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
```

**ELO recalculation schedule — SUPERSEDED 2026-09-21, no longer automatic.** This line previously said full recalculation runs automatically every Sunday at 03:00 UTC via `polymarket-sunday-elo.timer` → `scripts/run_sunday_elo.sh` → `scripts/recalculate_comprehensive_elo.py`; that timer was stopped and disabled 2026-09-21 (reversible — see Important Warning 6 below). `daily_maintenance.py` (06:00 UTC daily including Sundays) still does **not** perform the full recalculation itself, unchanged. Last full recalculation: 2026-09-20 (the frozen values now archived — Warning 6). Last *manual* full recalculation before that: April 30 2026.

**April 30 2026 audit findings (applied):**

- **`research_excluded` clean pool is 857 traders** (not 6,829 or 9,993 — earlier figures included traders whose exclusion flags had not been propagated). `update_research_exclusions.py` now runs as Step 0 of `daily_maintenance.py` before any ELO work, ensuring the flag is always current before analysis begins. Always filter research queries with `AND tr.research_excluded = 0`.
- **`trade_gap_flag` filter applied in base ELO calculation** — the gap period (Apr 7–18) is now excluded upstream in the ELO pipeline, not just in ad-hoc queries.
- **Analysis modules returning real data** — calibration, risk, and regret analysis modules were previously returning neutral 1.0× multipliers due to a missing initialisation step. This is fixed; ELO modifier scores now reflect actual trader behaviour.
- **WAL mode is permanent** — `PRAGMA journal_mode=WAL` is set on connection. Do not remove. Required for concurrent reads during live monitoring.

---

## Important Warnings

1. **Don't delete `data/polymarket_tracker.db`** — irreplaceable historical data, no API recovery path.
2. **Don't run duplicate monitoring processes** — the system uses PID file locking, but force-killing and restarting can leave stale locks. Always use `scripts/kill_all.py` to stop cleanly.
3. **`created_at` still doesn't exist on `markets`, but timing quality is NOT neutral/disabled** — this line previously said all traders get a flat neutral score; that's no longer true. The computation was reworked to use existing trade timestamps instead of `created_at` (see `analysis/trading_behavior_analysis.py`, "works without created_at column"), and produces real per-trader variation today (34,906 distinct values across 44,652 traders with a score, as of 2026-09-13 — only 8,670 sit at the neutral 0.5). Separately, and unrelated to this: whatever timing_score computes does not currently affect the final ELO number at all, because `W_BEH=0.0` zeroes out the entire behavioral-bonus contribution (Stage 0b, 2026-07-12, decided and tested-null, not a bug).
4. **Telegram is send-only** — no webhooks, no polling. Conflicts were fixed in Jan 2026; don't reintroduce webhook mode.
5. **Trade gap April 7–18 2026** — markets resolving during this window are flagged `trade_gap_flag = 1`. Exclude from research with `AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)`.
6. **`timing_score`, `patience_score`, `kelly_alignment_score`, `behavioral_modifier`, `advanced_modifier` are FROZEN as of the 2026-09-20 Sunday recalc (2026-09-21 decision, trading-swarm `brain/decisions/2026-09-21-disable-sunday-elo-recalc.md`).** `polymarket-sunday-elo.timer` — the ONLY writer of these five columns; the daily `apply_full_elo_modifiers.py` step merely carries them forward unchanged, confirmed empirically — was stopped and disabled that day (reversible: `sudo systemctl enable --now polymarket-sunday-elo.timer`). **Do not treat these five columns as live** — a query against them today returns exactly what was true on 2026-09-20, not "current." A full point-in-time archive (203,677 rows, hash-verified) is committed at `data/characterizations/elo_behavioral_columns_archive_20260921T204800Z.json` (commit `41d68e5`). Everything else ELO-related — `geo_elo`, `geo_elo_active`, `comprehensive_elo` itself (still refreshed daily by the same `apply_full_elo_modifiers.py` step), tiers, Pool B/C, the LEGENDARY gate — is on the independent daily `update_geo_elo.py` path and is UNAFFECTED; do not confuse "ELO" as a blanket term here, see the decision doc for the full computation inventory.

---

## Known Documentation Gaps

This file is not self-verifying, and it has been wrong before — a 2026-09-13
sweep found **24 instances** of "built correctly, never connected" across
this codebase (dead entry points, live components polling dead pipelines,
computed-but-zero-weighted scores, alerts/config that silently don't do what
they claim), plus several outright false claims in this file itself
(corrected in this same edit — see `git log` on this file, 2026-09-13). Full
inventory: `brain/decisions/2026-09-13-built-never-connected-sweep.md` and
`.json` (trading-swarm, commit `c45fb45`); the documentation-correction pass
itself: `brain/decisions/2026-09-13-claude-md-correction.md`.

**Practical implication: do not trust an unverified claim in this file (or
any doc) about what reads what, what runs on what schedule, or what a config
file controls.** Grep for the actual caller/reader/cron entry before relying
on a stated behavior, especially for anything touching Telegram alerting,
scheduled analysis, or ELO scoring — those are where most of the 24 known
instances cluster.

---

## Architecture Summary

```
Polymarket API
    ↓ (every 15 min)
monitoring/monitor.py  →  monitoring/database.py (SQLite)
    ↓                            ↓
monitoring/telegram_health_bot.py   analysis/ (ELO, behavioral, P&L)
    ↓
Telegram alerts (geo/elec pending-backlog + health-check degradation;
the "elite traders" / LEGENDARY-tier alert this used to say was retired 2026-09-09)

monitoring/system_observer.py  →  [DORMANT INTENT, not wired] Mistral/Ollama (local)
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

# Run full ELO recalculation (takes 5-15 min)
# (scripts/integrate_behavioral_elo.py, previously documented here, was
# deleted 2026-07-12 -- 61adaf5, "Stage 0c -- delete dead Writer C")
python scripts/recalculate_comprehensive_elo.py
```

---

## Session Discipline

### Commit Protocol
At the end of every session that modifies any file, commit
before closing. Do not let changes accumulate as unstaged.

After any set of related changes:
  git add -A
  git commit -m "descriptive message covering all changes"
  git push origin main

Commit message format:
  "feat: ..." for new functionality
  "fix: ..." for bug fixes
  "refactor: ..." for restructuring
  "defensive: ..." for hardening/future-proofing
  "docs: ..." for documentation only

### Information Gathering vs Editing
These two types of prompts must be kept distinct:

INFORMATION GATHERING (no commits needed):
- Reading files, querying database, running diagnostics
- grep, cat, sqlite3 queries, tail logs
- Any prompt that starts with "check", "verify", "audit",
  "show me", "what is", "diagnose"
- Never commit after a pure information-gathering session

EDITING (always commit):
- Writing or modifying any .py, .md, .json, .sh file
- Any prompt that starts with "add", "fix", "update",
  "change", "create", "write", "patch", "refactor"
- Commit immediately after each logical group of changes
- Do not bundle unrelated edits into one commit

If unsure: if a file was modified, commit it.
