# Polymarket Trader Intelligence System

## Purpose
Track and analyze Polymarket prediction market traders to identify profitable, skilled traders through a comprehensive ELO rating system. Primary use case: Detect "smart money consensus" when multiple elite traders take the same position.

## Core Objective
Enable profitable betting by following consensus positions of proven money-making traders (ELO ≥ 1550).

---

## System Components

### Monitoring System
- **File:** `scripts/start_monitoring.py`
- **Purpose:** Continuously polls Polymarket API for new trades from tracked traders
- **Frequency:** 15-minute cycles
- **Output:** Updates `trades` table with new activity

### P&L Worker
- **Component:** Background thread in monitoring
- **Purpose:** Calculates realized profit/loss and ROI for closed positions
- **Progress:** Runs continuously, processes 20 traders per batch
- **Current State:** ~37-50% coverage

### System Observer
- **File:** `scripts/run_system_observer.py`
- **Purpose:** Health monitoring and trader intelligence alerts
- **Features:**
  - Hourly status reports
  - High-value trade alerts ($1k+, ELO ≥ 1550)
  - Consensus detection (3+ elite traders betting same way within 24h)
  - Exit consensus detection (2+ elite traders exiting within 6h)
  - Weekly performance summaries (Sunday 20:00)
- **Alerts:** Via Telegram

### ELO Rating System
- **File:** `analysis/unified_elo_system.py` (4472 lines)
- **Purpose:** Calculate trader skill ratings
- **Algorithm:** ROI-first multi-dimensional rating
- **Components:**
  - Base ELO: Win/loss with ROI-adjusted scores (~40% weight)
  - P&L Multiplier: 0.40x–2.50x based on realized profits (~45% — DOMINANT, applied first)
  - Behavioral Bonus: ±100 pts for Kelly alignment, patience, timing (~8%)
  - Other Modifiers: Activity style (0.92–1.12x), advanced metrics (0.85–1.15x), network quality (0.0–1.25x), contrarian value (0.90–1.30x) (~7%)

### Telegram Health Bot
- **File:** `monitoring/telegram_health_bot.py`
- **Purpose:** Format and send alerts to Telegram

---

## Database Schema

**Location:** `data/polymarket_tracker.db` (SQLite, WAL mode)

### traders
| Column | Type | Description |
|--------|------|-------------|
| `address` | TEXT PK | Wallet address |
| `comprehensive_elo` | REAL | Final ELO after all modifiers |
| `roi_percentage` | REAL | Average ROI across closed positions |
| `total_pnl` | REAL | Total realized profit/loss |
| `closed_positions` | INTEGER | Number of closed positions |
| `is_flagged` | INTEGER | 1 = tracked elite trader |
| `first_seen` | TIMESTAMP | When first tracked |
| `last_active` | TIMESTAMP | Most recent trade |

### trades
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | |
| `trader_address` | TEXT FK | |
| `market_id` | TEXT FK | |
| `outcome` | TEXT | 'YES' or 'NO' |
| `shares` | REAL | Negative = sell |
| `price` | REAL | Per share (0–1) |
| `timestamp` | TIMESTAMP | |

### trader_stats
| Column | Type | Description |
|--------|------|-------------|
| `trader_address` | TEXT FK | |
| `total_roi_pct` | REAL | Average ROI across closed positions |
| `realized_pnl` | REAL | Total profit/loss from closed positions |
| `closed_positions` | INTEGER | |
| `win_rate` | REAL | % of profitable closed positions |

### markets
| Column | Type | Description |
|--------|------|-------------|
| `market_id` | TEXT PK | |
| `title` | TEXT | Market question |
| `category` | TEXT | 'Politics', 'Crypto', 'Sports', etc. |
| `resolved` | BOOLEAN | Whether market has resolved |
| `winning_outcome` | TEXT | 'YES' or 'NO' if resolved |

### positions
| Column | Type | Description |
|--------|------|-------------|
| `position_id` | TEXT PK | |
| `trader_address` | TEXT | |
| `market_id` | TEXT | |
| `outcome` | TEXT | |
| `entry_shares` | REAL | |
| `entry_avg_price` | REAL | Average entry price |
| `entry_total_cost` | REAL | Capital deployed |
| `exit_total_received` | REAL | Proceeds from sale |
| `realized_pnl` | REAL | Profit/loss (closed only) |
| `roi_percent` | REAL | |
| `status` | TEXT | 'open', 'closed', 'partially_closed' |
| `remaining_shares` | REAL | For partial closes |
| `open_cost_basis` | REAL | Cost of remaining open shares |

### monitoring_status
| Column | Type | Description |
|--------|------|-------------|
| `component` | TEXT PK | 'monitoring', 'observer', etc. |
| `last_activity` | TIMESTAMP | Used for health checks |
| `status` | TEXT | |

---

## Project Layout

```
first-repo/
├── monitoring/
│   ├── monitor.py                  # Main monitoring loop
│   ├── position_tracker.py         # P&L calculation (match_trades_for_trader, calculate_trader_pnl)
│   ├── system_observer.py          # Health monitoring & intelligence alerts
│   ├── telegram_health_bot.py      # Telegram alert formatting & sending
│   ├── health_checker.py           # Activity threshold checks
│   ├── database.py                 # DB connection wrapper
│   └── elo_rating.py               # Legacy ELO (deprecated — use unified_elo_system.py)
│
├── analysis/
│   └── unified_elo_system.py       # Current ELO rating system (all components)
│
├── scripts/
│   ├── start_monitoring.py         # Launch monitoring (with file lock)
│   ├── run_system_observer.py      # Launch observer (with file lock)
│   ├── kill_all.py                 # Stop all processes
│   ├── check_processes.py          # View running processes
│   └── backfill_elo_ratings.py     # Backfill historical ELO
│
├── data/
│   └── polymarket_tracker.db       # SQLite database
│
├── .mcp/
│   └── config.json                 # MCP SQLite configuration (mcp-server-sqlite-npx)
│
├── PROJECT_CONTEXT.md              # This file
├── ELO_SYSTEM_ANALYSIS.md          # Full ELO component breakdown with test cases
├── ELO_BACKFILL_GUIDE.md           # Guide for historical ELO backfill
├── TRADER_INTELLIGENCE_UPGRADE.md  # Observer feature documentation
└── CONSENSUS_DETECTION.md          # Consensus detection documentation
```

---

## Coding Conventions

### Database Access
```python
import sqlite3
conn = sqlite3.connect('data/polymarket_tracker.db')
cursor = conn.cursor()
# ... queries ...
conn.commit()
conn.close()
```

### Trader Address Format
- Full: `0x4017a8c3b92d1f5e8a7c9d2e6f4b8a1c3d5e7f9a`
- Short display: `0x4017...7f9a` (first 6 + last 4 chars)

### ELO Thresholds
- Average: ~1500
- Elite:   ≥ 1550 (used for consensus detection)
- Expert:  ≥ 1600
- Master:  ≥ 1700

### Consensus Detection Parameters
- Minimum traders: 3 (entry), 2 (exit)
- Minimum ELO: 1550
- Time window: 24 hours (entries), 6 hours (exits)
- Signal strength: 3 traders = 🔥 MODERATE, 4 = 🔥🔥 STRONG, 5+ = 🔥🔥🔥 VERY STRONG

### Activity Thresholds (health checks)
- HEALTHY:  < 180 minutes since last activity
- WARNING:  180–240 minutes
- CRITICAL: > 240 minutes

### File Locking (prevent duplicate processes)
All entry-point scripts use OS-level locking:
```python
# Windows
import msvcrt
lock_file = open('data/.monitoring.lock', 'w')
msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

# Unix
import fcntl
fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
```

### P&L Calculation
- Realized P&L: from fully/partially closed positions only
- Unrealized drag: `open_cost_basis * 0.5` applied as downside proxy (no live prices)
- Combined for profit modifier: `adjusted_pnl = realized_pnl - (open_cost_basis * 0.5)`
- ROI modifier: closed trades only (unaffected by unrealized drag)

### Key ELO Methods (unified_elo_system.py)
```python
system = UnifiedELOSystem(db_path='data/polymarket_tracker.db')

# Base ELO from historical win/loss
system.calculate_elo_ratings(verbose=True)

# Full rating with all modifiers
final_elo = system.get_trader_global_elo(
    trader_address='0x...',
    apply_behavioral=True,   # ±100 pts + 0.80–1.20x
    apply_advanced=True,     # 0.85–1.15x
    apply_network=True,      # 0.0–1.25x (excludes copy-traders)
    apply_contrarian=True,   # 0.90–1.30x
    apply_pnl=True           # 0.40–2.50x ← DOMINANT (applied first)
)
```

---

## ELO System: Critical Design Decisions

### ROI-First Architecture
The P&L multiplier is applied **before** all other modifiers to ensure profit performance has maximum multiplicative impact:
```
adjusted_elo = base_elo * pnl_multiplier * other_multipliers + behavioral_bonus
```

### P&L Multiplier Breakdown
```
profit_modifier  = f(realized_pnl)         # 0.50–1.40x (absolute $ made)
roi_modifier     = f(avg_roi)              # 0.40–2.50x ← dominant
quality_modifier = f(profitable_rate)      # 0.90–1.15x (win rate)
confidence       = f(closed_positions)     # 0.50–1.00 (sample size)

combined = profit_modifier * roi_modifier * quality_modifier
final    = 1.0 + (combined - 1.0) * confidence
final    = clamp(final, 0.40, 2.50)
```

### Verified Test Cases
| Profile | Win Rate | ROI | Final ELO | Assessment |
|---------|----------|-----|-----------|------------|
| High wins, negative ROI | 60% | -10% | ~1100 | POOR ✅ |
| Moderate wins, excellent ROI | 55% | +45% | ~3577 | EXCEPTIONAL ✅ |
| Elite wins, breakeven ROI | 75% | +2% | ~1817 | ABOVE AVG ✅ |
| Poor wins, catastrophic ROI | 30% | -60% | ~169 | CATASTROPHIC ✅ |

System correctly penalises unprofitable trading regardless of win rate.

---

## Success Metrics

### P&L Coverage
- Current: ~37–50%
- Target:  70%+ for reliable consensus signals
- Elite trader target: 100+ traders with ELO ≥ 1550

### Consensus Strategy
- Signal: 3+ elite traders bet same way within 24 hours
- Expected ROI: 30–50% (based on elite trader avg ROI of 35%+)

### ELO Accuracy
- Correctly identifies profitable traders (ROI > 30%) → high ELO
- Penalises unprofitable traders regardless of win rate
- Filters copy-traders via network quality multiplier (can exclude entirely)

---

## System Status (as of 2026-02-18)

### Working ✅
- Monitoring system running (15-minute cycles)
- P&L worker processing (~37–50% coverage)
- ELO system correctly prioritises profitability (ROI-first)
- Unrealized P&L drag applied via open_cost_basis (50% weight)
- System Observer sending Telegram alerts
- High-value trade alerts ($1k+, ELO ≥ 1550)
- Consensus entry/exit detection implemented
- Weekly performance summaries (Sunday 20:00)
- MCP database access configured (mcp-server-sqlite-npx, Node.js v24.13.1)
- Activity thresholds tuned (180/240 min — no false CRITICAL alerts)

### In Progress ⏳
- P&L coverage reaching 70%+ (needs ~5–7 more days of worker runtime)
- Historical ELO backfill (script exists; needs Polymarket Gamma API for market resolutions)

### TODO 📋
- Integrate Polymarket Gamma API for accurate market resolution data
- Run historical ELO backfill (one-time, 2–6 hours)
- Achieve 100+ elite traders (ELO ≥ 1550) for consensus strategy
- Deploy consensus betting strategy in production
- Monitor behavioral metric predictiveness (Kelly, patience, timing — currently ~8% weight)

---

## MCP Access

Database is accessible via MCP in this project. Config: `.mcp/config.json`

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "npx",
      "args": ["-y", "mcp-server-sqlite-npx",
               "c:\\Users\\Oscar\\Projects\\first-repo\\data\\polymarket_tracker.db"]
    }
  }
}
```

Node.js v24.13.1 installed at `C:\Program Files\nodejs\`. Requires a fresh terminal session to be on PATH.
