#!/usr/bin/env python3
"""
Calculate and update geo_elo and geo_directionality_score for traders.

Incremental by default:
  - Traders where geo_elo IS NULL and have 5+ qualifying geo trades
  - Traders where actual qualifying trade count > stored geo_resolved_trades_count

--full-recalc: recalculate all traders with geo_elo IS NOT NULL (Pool C)
--dry-run: report what would change without writing to DB

Algorithm (market-implied probability ELO):
  Qualifying trades: market_category IN ('Geopolitics','Elections'),
    trade_result IN ('won','lost'), trade_gap_flag IS NULL OR 0,
    JOIN on trades.market_id = markets.market_id
  expected_score = price  (Yes trades)  or  1 - price  (No trades)
  actual_score   = 1 (won) or 0 (lost)
  K = 32 (<20 geo trades so far), 24 (20-50), 16 (>50)
  Starting ELO = 1500, process trades timestamp ASC
  Minimum 5 qualifying trades to receive geo_elo

geo_directionality_score:
  Per market: abs(yes_capital - no_capital) / (yes_capital + no_capital)
    where capital = price * shares
  Average across all qualifying geo markets
  Minimum 3 distinct markets
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")

GEO_ELO_LEGENDARY = 2175.0
ELO_START = 1500.0
MIN_TRADES_FOR_ELO = 5
MIN_MARKETS_FOR_DIRECTIONALITY = 3

# Pool C SQL (mirrors update_research_exclusions.py)
POOL_C_RESET_SQL = "UPDATE traders SET geo_accuracy_pool = 0"
POOL_C_POPULATE_SQL = """
UPDATE traders
SET geo_accuracy_pool = 1
WHERE geo_elo IS NOT NULL
  AND geo_resolved_trades_count >= 10
  AND geo_directionality_score IS NOT NULL
  AND bot_type IS NULL
  AND (wash_trade_suspect = 0 OR wash_trade_suspect IS NULL)
  AND (bot_suspect = 0 OR bot_suspect IS NULL)
"""


def _k_factor(trades_processed: int) -> int:
    if trades_processed < 20:
        return 32
    elif trades_processed <= 50:
        return 24
    else:
        return 16


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _find_traders_to_update(conn, full_recalc: bool) -> list:
    if full_recalc:
        rows = conn.execute("""
            SELECT DISTINCT t.address
            FROM traders t
            WHERE t.geo_elo IS NOT NULL
              AND t.bot_type IS NULL
              AND (t.wash_trade_suspect = 0 OR t.wash_trade_suspect IS NULL)
              AND (t.bot_suspect = 0 OR t.bot_suspect IS NULL)
        """).fetchall()
        return [r[0] for r in rows]

    # Case 1: no geo_elo yet but 5+ qualifying trades exist
    new_traders = conn.execute("""
        SELECT t.address
        FROM traders t
        JOIN trades tr ON tr.trader_address = t.address
        JOIN markets m ON m.market_id = tr.market_id
        WHERE t.geo_elo IS NULL
          AND t.bot_type IS NULL
          AND (t.wash_trade_suspect = 0 OR t.wash_trade_suspect IS NULL)
          AND (t.bot_suspect = 0 OR t.bot_suspect IS NULL)
          AND m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
          AND tr.timestamp <= datetime('now')
        GROUP BY t.address
        HAVING COUNT(tr.trade_id) >= ?
    """, (MIN_TRADES_FOR_ELO,)).fetchall()

    # Case 2: existing geo_elo but actual count > stored count
    stale_traders = conn.execute("""
        SELECT t.address
        FROM traders t
        JOIN trades tr ON tr.trader_address = t.address
        JOIN markets m ON m.market_id = tr.market_id
        WHERE t.geo_elo IS NOT NULL
          AND t.bot_type IS NULL
          AND (t.wash_trade_suspect = 0 OR t.wash_trade_suspect IS NULL)
          AND (t.bot_suspect = 0 OR t.bot_suspect IS NULL)
          AND m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
          AND tr.timestamp <= datetime('now')
        GROUP BY t.address
        HAVING COUNT(DISTINCT tr.market_id) > COALESCE(t.geo_resolved_trades_count, 0)
    """).fetchall()

    seen = set()
    result = []
    for r in list(new_traders) + list(stale_traders):
        addr = r[0]
        if addr not in seen:
            seen.add(addr)
            result.append(addr)
    return result


def _fetch_qualifying_trades(conn, address: str) -> list:
    """All qualifying geo trades for a trader, ordered timestamp ASC."""
    return conn.execute("""
        SELECT tr.outcome_bet, tr.price, tr.trade_result, tr.market_id, tr.shares, tr.timestamp
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trader_address = ?
          AND m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
          AND tr.timestamp <= datetime('now')
        ORDER BY tr.timestamp ASC
    """, (address,)).fetchall()


def _compute_geo_elo(trades: list) -> float:
    elo = ELO_START
    for i, row in enumerate(trades):
        outcome_bet = row[0]
        price = row[1] or 0.0
        trade_result = row[2]
        expected = price if outcome_bet == 'Yes' else (1.0 - price)
        actual = 1.0 if trade_result == 'won' else 0.0
        elo += _k_factor(i) * (actual - expected)
        max_elo_at_step = 1500.0 + ((i + 1) * 150.0)
        if elo > max_elo_at_step:
            elo = max_elo_at_step
    return elo


def _compute_geo_directionality(trades: list):
    """
    Per market: abs(yes_capital - no_capital) / (yes_capital + no_capital).
    Returns None if fewer than MIN_MARKETS_FOR_DIRECTIONALITY distinct markets.
    """
    market_capital = {}
    for row in trades:
        outcome_bet = row[0]
        price = row[1] or 0.0
        market_id = row[3]
        shares = row[4] or 0.0
        if market_id not in market_capital:
            market_capital[market_id] = {'Yes': 0.0, 'No': 0.0}
        capital = price * shares
        if outcome_bet == 'Yes':
            market_capital[market_id]['Yes'] += capital
        else:
            market_capital[market_id]['No'] += capital

    if len(market_capital) < MIN_MARKETS_FOR_DIRECTIONALITY:
        return None

    scores = []
    for cap in market_capital.values():
        total = cap['Yes'] + cap['No']
        if total > 0:
            scores.append(abs(cap['Yes'] - cap['No']) / total)

    if len(scores) < MIN_MARKETS_FOR_DIRECTIONALITY:
        return None

    return sum(scores) / len(scores)


def _compute_geo_elo_active(geo_elo: float, last_trade_ts) -> float:
    """
    Apply time-decay to geo_elo based on days since last qualifying geo trade.
    Formula: geo_elo * (0.5 ^ (days_dormant / 180.0))
    A trader active today gets ~full score. 180 days dormant = 50% score.
    """
    if last_trade_ts is None or geo_elo is None:
        return None
    try:
        from datetime import datetime, timezone
        ts = last_trade_ts.replace('Z', '+00:00').replace(' ', 'T')
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_dormant = (datetime.now(timezone.utc) - last).days
        decay = 0.5 ** (days_dormant / 180.0)
        return round(geo_elo * decay, 4)
    except Exception as e:
        import sys
        print(f"[geo_elo_active] parse error for ts={last_trade_ts!r}: {e}", file=sys.stderr)
        return None


def _refresh_pool_c(conn) -> int:
    with conn:
        conn.execute(POOL_C_RESET_SQL)
        count = conn.execute(POOL_C_POPULATE_SQL).rowcount
    return count


def main():
    parser = argparse.ArgumentParser(description="Update geo_elo and geo_directionality_score")
    parser.add_argument("--full-recalc", action="store_true",
                        help="Force recalculation for all traders with geo_elo IS NOT NULL (Pool C)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing to DB")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = _get_connection()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mode = "DRY RUN — " if args.dry_run else ""
    recalc = "full recalc" if args.full_recalc else "incremental"
    print(f"[geo_elo] {mode}{recalc} — {now_str}")

    try:
        conn.execute("ALTER TABLE traders ADD COLUMN geo_elo_active REAL")
    except sqlite3.OperationalError:
        pass

    traders = _find_traders_to_update(conn, args.full_recalc)
    print(f"[geo_elo] Traders to update: {len(traders)}")

    if not traders:
        print("[geo_elo] Nothing to update.")
        if not args.dry_run:
            pool_c = _refresh_pool_c(conn)
            legendary = conn.execute(
                "SELECT COUNT(*) FROM traders WHERE geo_elo >= ? AND geo_accuracy_pool = 1",
                (GEO_ELO_LEGENDARY,)
            ).fetchone()[0]
            active_legendary = conn.execute(
                "SELECT COUNT(*) FROM traders WHERE geo_elo_active >= ? AND geo_accuracy_pool = 1",
                (GEO_ELO_LEGENDARY,)
            ).fetchone()[0]
            print(f"[geo_elo] Pool C (geo_accuracy_pool): {pool_c} traders")
            print(f"[geo_elo] LEGENDARY (geo_elo >= {GEO_ELO_LEGENDARY:.0f}): {legendary} traders")
            print(f"[geo_elo] LEGENDARY active (geo_elo_active >= {GEO_ELO_LEGENDARY:.0f}): {active_legendary} traders")
        conn.close()
        return

    updated = 0
    skipped_thin = 0
    updates = []

    for address in traders:
        trades = _fetch_qualifying_trades(conn, address)
        n = len(trades)

        if n < MIN_TRADES_FOR_ELO:
            skipped_thin += 1
            continue

        geo_elo = _compute_geo_elo(trades)
        directionality = _compute_geo_directionality(trades)
        last_any_trade = conn.execute("""
            SELECT MAX(tr.timestamp)
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trader_address = ?
            AND tr.market_category IN ('Geopolitics', 'Elections')
            AND tr.timestamp <= datetime('now')
        """, (address,)).fetchone()[0]
        geo_elo_active = _compute_geo_elo_active(geo_elo, last_any_trade)

        distinct_markets = len(set(row[3] for row in trades))
        updates.append((geo_elo, directionality, distinct_markets, geo_elo_active, address))
        updated += 1

        if args.dry_run and updated <= 5:
            tier = ("LEGENDARY" if geo_elo >= 2175 else
                    "ELITE" if geo_elo >= 1800 else
                    "QUALIFIED" if geo_elo >= 1500 else "BELOW_QUALIFIED")
            dir_str = f"{directionality:.3f}" if directionality is not None else "N/A"
            active_str = f"{geo_elo_active:.1f}" if geo_elo_active is not None else "N/A"
            print(f"  {address[:12]}… geo_elo={geo_elo:.1f} active={active_str} ({tier}) dir={dir_str} n={n}")

    if args.dry_run:
        if updated > 5:
            print(f"  … and {updated - 5} more")
        print(f"[geo_elo] DRY RUN complete — would update {updated} traders, "
              f"skip {skipped_thin} (< {MIN_TRADES_FOR_ELO} qualifying trades)")
        conn.close()
        return

    if updates:
        with conn:
            conn.executemany("""
                UPDATE traders
                SET geo_elo                    = ?,
                    geo_directionality_score   = ?,
                    geo_resolved_trades_count  = ?,
                    geo_elo_active             = ?
                WHERE address = ?
            """, updates)

    # Second pass: update geo_elo_active for ALL traders with geo_elo,
    # including those skipped by the thin-trade guard.
    # geo_elo_active only needs geo_elo + last trade timestamp — independent of trade count.
    all_geo_traders = conn.execute("""
        SELECT address, geo_elo FROM traders
        WHERE geo_elo IS NOT NULL
        AND bot_type IS NULL
        AND (wash_trade_suspect = 0 OR wash_trade_suspect IS NULL)
        AND (bot_suspect = 0 OR bot_suspect IS NULL)
    """).fetchall()

    active_updates = []
    for address, geo_elo in all_geo_traders:
        last_any_trade = conn.execute("""
            SELECT MAX(tr.timestamp)
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            WHERE tr.trader_address = ?
            AND tr.market_category IN ('Geopolitics', 'Elections')
            AND tr.timestamp <= datetime('now')
        """, (address,)).fetchone()[0]
        geo_elo_active = _compute_geo_elo_active(geo_elo, last_any_trade)
        if geo_elo_active is not None:
            active_updates.append((geo_elo_active, address))

    if active_updates:
        with conn:
            conn.executemany(
                "UPDATE traders SET geo_elo_active = ? WHERE address = ?",
                active_updates
            )
        print(f"[geo_elo] geo_elo_active updated: {len(active_updates)} traders")

    pool_c = _refresh_pool_c(conn)
    legendary = conn.execute(
        "SELECT COUNT(*) FROM traders WHERE geo_elo >= ? AND geo_accuracy_pool = 1",
        (GEO_ELO_LEGENDARY,)
    ).fetchone()[0]

    active_legendary = conn.execute(
        "SELECT COUNT(*) FROM traders WHERE geo_elo_active >= ? AND geo_accuracy_pool = 1",
        (GEO_ELO_LEGENDARY,)
    ).fetchone()[0]

    conn.close()

    print(f"[geo_elo] Updated : {updated} traders")
    if skipped_thin:
        print(f"[geo_elo] Skipped : {skipped_thin} traders (< {MIN_TRADES_FOR_ELO} qualifying trades)")
    print(f"[geo_elo] Pool C (geo_accuracy_pool): {pool_c} traders")
    print(f"[geo_elo] LEGENDARY (geo_elo >= {GEO_ELO_LEGENDARY:.0f}): {legendary} traders")
    print(f"[geo_elo] LEGENDARY active (geo_elo_active >= {GEO_ELO_LEGENDARY:.0f}): {active_legendary} traders")


if __name__ == "__main__":
    main()
