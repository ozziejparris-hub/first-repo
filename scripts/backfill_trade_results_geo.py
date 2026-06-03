#!/usr/bin/env python3
"""
Backfill pending trade results for ALL traders on resolved Geopolitics/Elections markets.

evaluate_new_trader_results.py only processes is_flagged=1 traders. After the category
backfill reclassified ~11K markets, many traders have trade_result='pending' on resolved
geo/elections markets. This script fixes that gap regardless of is_flagged status.
"""

import sys
import os
import argparse
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'polymarket_tracker.db')
BATCH_SIZE = 1000


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    conn.row_factory = sqlite3.Row
    return conn


def evaluate_trade(outcome_bet: str | None, side: str, winning_outcome: str) -> str:
    """Return 'won', 'lost', or 'invalid' using the same logic as TradeEvaluator."""
    if not outcome_bet:
        return 'invalid'
    trade_outcome = str(outcome_bet).strip().lower()
    winner = str(winning_outcome).strip().lower()
    if not trade_outcome or not winner:
        return 'invalid'
    if (side or 'buy').strip().lower() == 'buy':
        return 'won' if trade_outcome == winner else 'lost'
    else:  # sell
        return 'won' if trade_outcome != winner else 'lost'


def fetch_pending_trades(conn: sqlite3.Connection, limit: int | None) -> list[dict]:
    sql = """
        SELECT
            t.trade_id,
            t.trader_address,
            t.outcome_bet,
            t.side,
            m.winning_outcome
        FROM trades t
        JOIN markets m ON m.condition_id = t.market_id
        WHERE (t.trade_result = 'pending' OR t.trade_result IS NULL)
          AND m.resolved = 1
          AND m.winning_outcome IS NOT NULL
          AND m.winning_outcome NOT IN ('unknown', '')
          AND m.category IN ('Geopolitics', 'Elections')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND t.timestamp <= datetime('now')
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor = conn.cursor()
    cursor.execute(sql)
    return [dict(row) for row in cursor.fetchall()]


def run(db_path: str, dry_run: bool, limit: int | None) -> None:
    conn = get_connection(db_path)

    print(f"Fetching pending trades on resolved Geo/Elections markets...")
    trades = fetch_pending_trades(conn, limit)
    total = len(trades)
    print(f"Found {total} pending trades to evaluate.")

    if total == 0:
        conn.close()
        return

    counts = {'won': 0, 'lost': 0, 'invalid': 0}
    traders_seen: set[str] = set()

    if dry_run:
        for trade in trades:
            result = evaluate_trade(trade['outcome_bet'], trade['side'], trade['winning_outcome'])
            counts[result] += 1
            traders_seen.add(trade['trader_address'])
        print(f"\n[DRY RUN] Would write: won={counts['won']}, lost={counts['lost']}, invalid={counts['invalid']}")
        print(f"[DRY RUN] Traders affected: {len(traders_seen)}")
        conn.close()
        return

    cursor = conn.cursor()
    processed = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = trades[batch_start: batch_start + BATCH_SIZE]
        for trade in batch:
            result = evaluate_trade(trade['outcome_bet'], trade['side'], trade['winning_outcome'])
            cursor.execute(
                "UPDATE trades SET trade_result = ? WHERE trade_id = ?",
                (result, trade['trade_id'])
            )
            counts[result] += 1
            traders_seen.add(trade['trader_address'])
            processed += 1

        conn.commit()
        print(f"  Batch committed: {processed}/{total} trades processed "
              f"(won={counts['won']}, lost={counts['lost']}, invalid={counts['invalid']})")

    # Update geo_resolved_trades_count for all affected traders
    print(f"\nUpdating geo_resolved_trades_count for {len(traders_seen)} traders...")
    placeholders = ','.join('?' * len(traders_seen))
    cursor.execute(f"""
        UPDATE traders
        SET geo_resolved_trades_count = (
            SELECT COUNT(DISTINCT tr2.market_id)
            FROM trades tr2
            JOIN markets m ON m.condition_id = tr2.market_id
            WHERE tr2.trader_address = traders.address
              AND tr2.trade_result IN ('won', 'lost')
              AND m.category IN ('Geopolitics', 'Elections')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
        )
        WHERE address IN ({placeholders})
    """, list(traders_seen))
    conn.commit()

    conn.close()

    print(f"\nDone.")
    print(f"  Total evaluated : {processed}")
    print(f"  Won             : {counts['won']}")
    print(f"  Lost            : {counts['lost']}")
    print(f"  Invalid         : {counts['invalid']}")
    print(f"  Traders updated : {len(traders_seen)}")


def main():
    parser = argparse.ArgumentParser(
        description="Backfill trade results for all traders on resolved Geo/Elections markets."
    )
    parser.add_argument('--dry-run', action='store_true',
                        help="Print counts without writing to DB.")
    parser.add_argument('--limit', type=int, default=None,
                        help="Cap number of trades fetched (for testing).")
    args = parser.parse_args()

    run(DB_PATH, dry_run=args.dry_run, limit=args.limit)


if __name__ == '__main__':
    main()
