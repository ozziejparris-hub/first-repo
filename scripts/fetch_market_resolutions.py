#!/usr/bin/env python3
"""
Fetch Market Resolutions from Polymarket CLOB API

Queries the Polymarket CLOB API for resolution outcomes for all markets
that appear in our trades table and updates the markets table.

Key findings from API investigation:
  - CLOB endpoint: https://clob.polymarket.com/markets/{condition_id}
    Works with the hex market_id (condition_id) stored in our DB directly.
  - Returns tokens[].outcome ("Yes"/"No" or player/team name)
          and tokens[].winner (True/False)
  - This is the authoritative resolution source.
  - Gamma API (gamma-api.polymarket.com) does NOT reliably return resolvedOutcome.

Usage:
    python scripts/fetch_market_resolutions.py

    # Only fetch markets not yet in DB:
    python scripts/fetch_market_resolutions.py

    # Force re-check all (incl. already-resolved):
    python scripts/fetch_market_resolutions.py --force
"""

import sys
import sqlite3
import time
import argparse
import os
from pathlib import Path
from datetime import datetime

import requests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

CLOB_BASE = "https://clob.polymarket.com/markets"
REQUEST_DELAY = 0.15   # seconds between requests (~6-7 req/s, well within limits)
BATCH_PRINT = 50       # progress line every N markets
TIMEOUT = 12           # seconds per request


def fetch_resolution(session: requests.Session, market_id: str) -> dict | None:
    """
    Query CLOB API for a single market's resolution status.

    Returns:
        {
            'closed': bool,
            'winning_outcome': str | None,   # outcome name of winner, or None
        }
        or None on network error / non-200.
    """
    try:
        r = session.get(f"{CLOB_BASE}/{market_id}", timeout=TIMEOUT)
        if r.status_code == 404:
            return {'closed': False, 'winning_outcome': None}
        if r.status_code != 200:
            return None

        data = r.json()
        closed = bool(data.get('closed', False))

        winning_outcome = None
        tokens = data.get('tokens', [])
        if isinstance(tokens, list):
            for token in tokens:
                if isinstance(token, dict) and token.get('winner') is True:
                    winning_outcome = token.get('outcome')
                    break

        return {'closed': closed, 'winning_outcome': winning_outcome}

    except requests.exceptions.RequestException as e:
        print(f"\n  Network error for {market_id[:20]}...: {e}", flush=True)
        return None


def get_markets_to_fetch(conn: sqlite3.Connection, force: bool) -> list[tuple]:
    """
    Return list of (market_id,) for markets that appear in trades.

    If force=False (default): skip markets already marked resolved=1.
    If force=True: re-check all markets in trades.
    """
    cur = conn.cursor()
    if force:
        cur.execute("""
            SELECT DISTINCT t.market_id
            FROM trades t
            JOIN markets m ON t.market_id = m.market_id
            ORDER BY t.market_id
        """)
    else:
        cur.execute("""
            SELECT DISTINCT t.market_id
            FROM trades t
            JOIN markets m ON t.market_id = m.market_id
            WHERE m.resolved = 0 OR m.winning_outcome IS NULL
            ORDER BY t.market_id
        """)
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser(description='Fetch Polymarket market resolutions via CLOB API')
    parser.add_argument('--force', action='store_true',
                        help='Re-check all markets, including already-resolved ones')
    parser.add_argument('--db', default='data/polymarket_tracker.db',
                        help='Path to SQLite database (default: data/polymarket_tracker.db)')
    args = parser.parse_args()

    print("=" * 70)
    print("  POLYMARKET MARKET RESOLUTION FETCHER")
    print("=" * 70)
    print(f"  Database : {args.db}")
    print(f"  Mode     : {'Force re-check all' if args.force else 'Fetch unresolved only'}")
    print(f"  API      : {CLOB_BASE}")
    print()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")

    markets = get_markets_to_fetch(conn, args.force)
    total = len(markets)
    print(f"Markets to check: {total:,}")

    if total == 0:
        print("Nothing to do — all trade markets already have resolution data.")
        print("Use --force to re-check all markets.")
        conn.close()
        return

    session = requests.Session()
    session.headers.update({'User-Agent': 'PolymarketTracker/1.0'})

    resolved_new = 0      # newly resolved this run
    already_resolved = 0  # already in DB as resolved (only relevant with --force)
    unresolved = 0        # market not yet resolved
    errors = 0            # API failures

    print()
    start_time = time.time()

    for i, (market_id,) in enumerate(markets, 1):
        result = fetch_resolution(session, market_id)
        time.sleep(REQUEST_DELAY)

        if result is None:
            errors += 1
            # Brief back-off on error
            time.sleep(1.0)
            continue

        if result['closed'] and result['winning_outcome']:
            # Market resolved — write to DB
            cur = conn.cursor()
            cur.execute("""
                UPDATE markets
                SET resolved = 1,
                    winning_outcome = ?,
                    resolution_date = ?,
                    last_checked = ?
                WHERE market_id = ?
            """, (
                result['winning_outcome'],
                datetime.now().isoformat(),
                datetime.now().isoformat(),
                market_id,
            ))
            if cur.rowcount > 0:
                resolved_new += 1

            # Commit every 100 updates to avoid holding a large transaction
            if resolved_new % 100 == 0:
                conn.commit()
        else:
            unresolved += 1

        # Progress every BATCH_PRINT markets
        if i % BATCH_PRINT == 0 or i == total:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            print(
                f"  [{i:>5}/{total}]  resolved_new={resolved_new}  "
                f"unresolved={unresolved}  errors={errors}  "
                f"ETA={eta:.0f}s",
                flush=True
            )

    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    print()
    print("=" * 70)
    print(f"  COMPLETE in {elapsed:.0f}s")
    print(f"  Newly resolved markets written to DB : {resolved_new:,}")
    print(f"  Markets still unresolved             : {unresolved:,}")
    print(f"  API errors (skipped)                 : {errors:,}")
    print("=" * 70)

    if resolved_new > 0:
        print()
        print("Next step:")
        print("  python scripts/backfill_elo_ratings.py")


if __name__ == "__main__":
    main()
