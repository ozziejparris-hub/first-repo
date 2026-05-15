# Integration Contract — Polymarket Trader Monitoring System

**Version:** 1.3
**Date:** 2026-05-15
**Audience:** Agents and scripts querying or writing trader metadata

---

## Section 1 — Purpose

This document is the authoritative reference for any agent or script that reads from or writes to the `traders` table. It defines the column set, semantics, valid values, and population rules so that downstream consumers do not need to reverse-engineer the schema from Python source.

If a column is not listed here, treat it as internal-implementation detail and do not depend on it.

---

## Section 2 — Database Overview

| Property | Value |
|----------|-------|
| **File** | `data/polymarket_tracker.db` (symlink: `monitoring/polymarket_tracker.db`) |
| **Engine** | SQLite 3, WAL mode (permanent — do not disable) |
| **Size** | ~1.6 GB as of April 2026 |
| **Tables** | `traders`, `trades`, `markets`, `positions` |
| **Trader rows** | 87,063+ |
| **Trade rows** | 1M+ |

Research queries must always include:
```sql
AND tr.research_excluded = 0
AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
```

---

## Section 3 — Core Traders Table Columns

These columns form the stable contract. All have existed since v1.0 unless noted.

| Column | Type | Default | Nullable | Description |
|--------|------|---------|----------|-------------|
| `address` | TEXT | — | NO (PK) | Trader's Ethereum wallet address (`0x…40 hex chars`) |
| `total_trades` | INTEGER | 0 | YES | Total trades executed by this trader |
| `successful_trades` | INTEGER | 0 | YES | Trades resolved as wins |
| `win_rate` | REAL | 0.0 | YES | `successful_trades / total_trades` (0.0–1.0) |
| `total_volume` | REAL | 0.0 | YES | Cumulative dollar volume traded |
| `first_seen` | TIMESTAMP | `CURRENT_TIMESTAMP` | YES | Earliest observation of this address |
| `last_updated` | TIMESTAMP | `CURRENT_TIMESTAMP` | YES | Last stats update |
| `is_flagged` | BOOLEAN | 0 | YES | 1 = notable trader; drives Telegram alerts |
| `realized_pnl` | REAL | 0 | YES | P&L from closed positions (FIFO matched) |
| `unrealized_pnl` | REAL | 0 | YES | Mark-to-market P&L on open positions |
| `total_pnl` | REAL | 0 | YES | `realized_pnl + unrealized_pnl` |
| `avg_roi` | REAL | 0 | YES | Average ROI across closed positions |
| `total_invested` | REAL | 0 | YES | Total capital deployed |
| `closed_positions` | INTEGER | 0 | YES | Count of fully closed positions |
| `open_positions` | INTEGER | 0 | YES | Count of currently open positions |
| `comprehensive_elo` | REAL | 1500 | YES | Overall 6-dimensional ELO rating |
| `base_category_elo` | REAL | 1500 | YES | Category-specific ELO baseline |
| `elo_last_updated` | TIMESTAMP | NULL | YES | Timestamp of last ELO recalculation |
| `behavioral_modifier` | REAL | 1.0 | YES | ELO multiplier for behavioural patterns |
| `advanced_modifier` | REAL | 1.0 | YES | ELO multiplier for advanced metrics |
| `pnl_modifier` | REAL | 1.0 | YES | ELO multiplier for P&L performance |
| `kelly_alignment_score` | REAL | NULL | YES | Kelly criterion alignment (0.0–1.0) |
| `patience_score` | REAL | NULL | YES | Holding-period patience metric |
| `timing_score` | REAL | NULL | YES | Entry/exit timing quality (intentionally neutral — see Section 7) |
| `weighted_win_rate` | REAL | NULL | YES | Win rate weighted by market difficulty |
| `roi_percentage` | REAL | NULL | YES | ROI as a percentage value |
| `resolved_trades_count` | INTEGER | NULL | YES | Count of trades with resolved market outcomes |
| `pnl_last_updated` | TIMESTAMP | NULL | YES | Timestamp of last P&L recalculation |
| `pnl_update_priority` | INTEGER | 0 | YES | Internal queue priority for P&L worker |
| `username` | TEXT | NULL | YES | Polymarket display name if available |
| `wash_trade_suspect` | BOOLEAN | 0 | NO | 1 = flagged by wash-trade detector |
| `bot_suspect` | BOOLEAN | 0 | NO | 1 = flagged as likely automated |
| `specialist_category` | TEXT | NULL | YES | Category trader specialises in |
| `specialisation_ratio` | REAL | NULL | YES | Fraction of trades in specialist category |
| `copyable_edge` | BOOLEAN | NULL | YES | 1 = trader has signal worth mirroring |
| `research_excluded` | BOOLEAN | 0 | NO | 1 = exclude from research/ELO queries; propagated by `update_research_exclusions.py` |

---

## Section 4 — Other Tables (Reference)

Full schemas for `trades`, `markets`, and `positions` are in `docs/DATABASE_SCHEMA_DOCUMENTATION.md`. Key cross-table fields that agents commonly join:

| Join | Left key | Right key | Purpose |
|------|----------|-----------|---------|
| traders → trades | `traders.address` | `trades.trader_address` | Trade history per trader |
| traders → positions | `traders.address` | `positions.trader_address` | P&L positions per trader |
| trades → markets | `trades.market_id` | `markets.market_id` | Market metadata for trade |

---

## Section 4b — Additional Trader Columns

These columns were added after v1.1 and are not in the DATABASE_SCHEMA_DOCUMENTATION. They extend the traders table with discovery provenance and classification metadata.

### `discovery_source`

| Property | Value |
|----------|-------|
| **Type** | TEXT |
| **Default** | `'live_feed'` |
| **Nullable** | YES |

Tracks how the trader was first ingested into the database.

| Value | Meaning |
|-------|---------|
| `'live_feed'` | Trader appeared organically in the 15-minute monitoring loop |
| `'leaderboard'` | Trader was discovered via `discover_leaderboard_traders.py` during the Sunday maintenance run |
| `'manual_watchlist'` | Trader was explicitly added via `add_watched_trader.py` |

Populated by: `discover_leaderboard_traders.py` (sets `'leaderboard'`) and `add_watched_trader.py` (sets `'manual_watchlist'`). The monitoring loop inserts with the `'live_feed'` default.

Use this column to segment traders by how they entered the system — e.g., leaderboard-sourced traders have different volume characteristics than organic live-feed traders.

---

### `watched`

| Property | Value |
|----------|-------|
| **Type** | INTEGER |
| **Default** | 0 |
| **Nullable** | YES |

Marks traders that are priority-monitored regardless of ELO or trade count thresholds.

| Value | Meaning |
|-------|---------|
| `0` | Standard monitoring rules apply |
| `1` | Trader is on the manual watchlist; always alert on activity |

Populated by: `add_watched_trader.py`. Watched traders are **exempt from `is_flagged` sync** (same exemption as leaderboard-sourced traders) so manual watchlist assignments survive the daily `update_research_exclusions` pass.

---

### `elo_period1_cutoff`

| Property | Value |
|----------|-------|
| **Type** | REAL |
| **Default** | NULL |
| **Nullable** | YES |

Point-in-time ELO snapshot captured at the RQ1.1 analysis cutoff date. Used to measure ELO trajectory: `comprehensive_elo - elo_period1_cutoff` gives the drift since the baseline.

NULL means the trader either did not exist at the cutoff date or has not yet been included in an RQ1.1 snapshot run.

Do **not** use this column as a substitute for `comprehensive_elo` in live ranking queries.

---

### `bot_type`

| Property | Value |
|----------|-------|
| **Type** | TEXT |
| **Default** | NULL |
| **Nullable** | YES |

Classifier for non-human trading artifacts. Only set when a trader is positively identified as a specific bot category; NULL means the trader is considered a clean human trader (or unclassified).

| Value | Meaning |
|-------|---------|
| `'LP_ARTIFACT'` | Liquidity-provider artefact address — trades are mechanically generated, not predictive |
| `'ARB_BOT'` | Arbitrage bot — exploits price discrepancies, not market prediction |
| `'THIN_SAMPLE_ARTIFACT'` | Statistical artefact from a tiny sample of trades; ELO not meaningful |
| `NULL` | Clean trader — include in research queries |

Agents running ELO analysis or leaderboard rankings should filter `WHERE bot_type IS NULL` (or equivalently rely on `research_excluded = 0`, which incorporates bot-type exclusions).

---

## Section 5 — ELO System Interface

The `UnifiedELOSystem` (`analysis/unified_elo_system.py`) reads and writes the following trader columns:

**Reads:** `address`, `comprehensive_elo`, `base_category_elo`, `behavioral_modifier`, `advanced_modifier`, `pnl_modifier`, `total_pnl`, `avg_roi`, `research_excluded`

**Writes:** `comprehensive_elo`, `base_category_elo`, `elo_last_updated`, `behavioral_modifier`, `advanced_modifier`, `pnl_modifier`, `kelly_alignment_score`, `patience_score`, `timing_score`, `weighted_win_rate`

Full recalculation runs every Sunday via `daily_maintenance.py`. Last manual run: 2026-04-30.

---

## Section 6 — Standard Research Query Filters

Always apply these filters in research and analysis queries:

```sql
-- Exclude non-human / low-quality traders
AND tr.research_excluded = 0

-- Exclude trade-gap period (monitoring was down 2026-04-07 to 2026-04-18)
AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)

-- Exclude bot-type artefacts (belt-and-suspenders; research_excluded covers this)
AND tr.bot_type IS NULL
```

The clean research pool is **857 traders** (as of 2026-04-30 audit). The `research_excluded` flag is propagated by `update_research_exclusions.py`, which runs as Step 0 of `daily_maintenance.py`.

---

## Section 7 — Critical Warnings

1. **`timing_score` is intentionally neutral (1.0).** The `markets.created_at` column does not exist. All traders receive a neutral timing score. Do not re-enable timing scoring without adding that column first.
2. **`research_excluded` must be current before ELO work.** Always run `update_research_exclusions.py` first (Step 0) — otherwise the clean pool count will be wrong.
3. **Watched and leaderboard traders are exempt from `is_flagged` sync.** Do not apply bulk `is_flagged = 0` resets to traders where `watched = 1` or `discovery_source = 'leaderboard'`.
4. **`elo_period1_cutoff` is read-only after snapshot.** Do not overwrite it during routine ELO recalculations.
5. **WAL mode is permanent.** `PRAGMA journal_mode=WAL` is set on every connection. Do not remove.

---

## Section 8 — Change Log

| Date | Change | Affected consumers |
|------|--------|-------------------|
| 2026-05-15 | `traders.discovery_source`, `traders.watched`, `traders.elo_period1_cutoff`, `traders.bot_type` columns documented | Agents querying trader metadata |
| 2026-04-30 | `research_excluded` propagation fixed; clean pool confirmed at 857 traders; `trade_gap_flag` filter applied upstream in ELO pipeline | ELO system, research queries |
| 2026-04-18 | Server migration complete; WAL mode confirmed permanent | All consumers |
| 2026-01-15 | Initial integration contract v1.0 drafted; core traders schema documented | All consumers |

---

*End of Integration Contract v1.3*
