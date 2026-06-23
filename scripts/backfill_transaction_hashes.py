"""
Backfill transaction_hash for Pool C and LEGENDARY traders by fetching trade
history from the Polymarket Data API and matching against DB trades.

The Data API returns recent trades only (~last few days). Run this daily
to capture transaction hashes for newly ingested trades before they age out.
"""

import argparse
import importlib.util
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitoring.column_definitions as cd

# --- Constants ---

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"
DATA_API_URL = "https://data-api.polymarket.com"
RATE_LIMIT_SLEEP = 0.2  # seconds between API calls
API_PAGE_SIZE = 500      # Data API hard max per page

_session = requests.Session()
_session.headers["User-Agent"] = "PolymarketTracker/1.0"
_session.headers["Accept"] = "application/json"


# --- DB helpers ---

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# --- Function 1: fetch_trader_transactions ---

def fetch_trader_transactions(
    trader_address: str,
    data_api_url: str = DATA_API_URL,
    limit: int = 1000,
) -> list:
    """
    Fetch all available trades for a trader from the Polymarket Data API.
    Paginates in increments of 500 until fewer than a full page is returned
    or a 400/error is encountered. The API only retains a rolling recent window
    (~3-7 days), so older trades will not appear.
    """
    all_trades = []
    offset = 0

    while True:
        page_size = min(API_PAGE_SIZE, limit - len(all_trades)) if limit else API_PAGE_SIZE
        if page_size <= 0:
            break

        url = f"{data_api_url}/trades"
        try:
            resp = _session.get(
                url,
                params={"user": trader_address, "limit": page_size, "offset": offset},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"  [API ERROR] {trader_address[:16]}... offset={offset}: {e}")
            break

        if resp.status_code == 400:
            # Hard offset cap from the API
            break
        if resp.status_code != 200:
            print(f"  [API ERROR] {trader_address[:16]}... status={resp.status_code}")
            break

        page = resp.json()
        if not isinstance(page, list) or not page:
            break

        all_trades.extend(page)
        time.sleep(RATE_LIMIT_SLEEP)

        if len(page) < page_size:
            # Last page — stop paginating
            break

        offset += page_size

    return all_trades


# --- Function 2: backfill_trader_hashes ---

def backfill_trader_hashes(
    trader_address: str,
    db_conn: sqlite3.Connection,
    data_api_url: str = DATA_API_URL,
    dry_run: bool = False,
) -> dict:
    """
    Fetch trades from the Data API for one trader, match against DB rows
    that are missing transaction_hash, and write hashes back to the DB.
    """
    stats = {"fetched": 0, "matched": 0, "updated": 0, "skipped": 0}

    api_trades = fetch_trader_transactions(trader_address, data_api_url)
    stats["fetched"] = len(api_trades)

    if not api_trades:
        return stats

    cursor = db_conn.cursor()

    for trade in api_trades:
        tx_hash = trade.get("transactionHash") or trade.get("transaction_hash")
        if not tx_hash:
            stats["skipped"] += 1
            continue

        cond_id = trade.get("conditionId")
        outcome = trade.get("outcome")
        price = trade.get("price")
        size = trade.get("size")
        ts_unix = trade.get("timestamp")

        if None in (cond_id, outcome, price, size, ts_unix):
            stats["skipped"] += 1
            continue

        # Match against DB: conditionId → market_id, fuzzy price/size/timestamp
        cursor.execute("""
            SELECT trade_id FROM trades
            WHERE trader_address = ?
              AND market_id = ?
              AND outcome = ?
              AND ABS(price - ?) < 0.0001
              AND ABS(shares - ?) < 0.001
              AND ABS(strftime('%s', timestamp) - ?) < 2
              AND (transaction_hash IS NULL OR transaction_hash = '')
            LIMIT 1
        """, (trader_address, cond_id, outcome, price, size, ts_unix))

        row = cursor.fetchone()
        if not row:
            stats["skipped"] += 1
            continue

        stats["matched"] += 1
        trade_id = row[0]

        if not dry_run:
            try:
                cursor.execute(
                    "UPDATE trades SET transaction_hash = ? WHERE trade_id = ?",
                    (tx_hash, trade_id),
                )
                db_conn.commit()
                stats["updated"] += 1
            except sqlite3.IntegrityError:
                # Unique index violation — hash already assigned to another trade
                stats["skipped"] += 1
        else:
            stats["updated"] += 1  # count as "would update" in dry-run

    return stats


# --- Function 3: run_backfill ---

def run_backfill(
    db_path: str = DB_PATH,
    dry_run: bool = False,
    tier: str = "legendary",
) -> dict:
    """
    Process all traders in the specified tier.

    tier='legendary': geo_elo_active >= 2175 AND research_excluded = 0
    tier='pool_c':    geo_accuracy_pool = 1
    tier='all':       all traders (very slow — not recommended)
    """
    conn = _get_conn()

    if tier == "legendary":
        sql = f"SELECT address FROM traders WHERE geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND research_excluded = 0 ORDER BY geo_elo_active DESC"
    elif tier == "pool_c":
        sql = "SELECT address FROM traders WHERE geo_accuracy_pool = 1 ORDER BY geo_elo DESC NULLS LAST"
    else:
        sql = "SELECT address FROM traders ORDER BY ROWID"

    traders = [row[0] for row in conn.execute(sql).fetchall()]
    print(f"[BACKFILL] tier={tier} dry_run={dry_run} — {len(traders)} traders to process")

    totals = {"fetched": 0, "matched": 0, "updated": 0, "skipped": 0, "traders": 0}

    for i, address in enumerate(traders, 1):
        stats = backfill_trader_hashes(address, conn, dry_run=dry_run)
        totals["fetched"] += stats["fetched"]
        totals["matched"] += stats["matched"]
        totals["updated"] += stats["updated"]
        totals["skipped"] += stats["skipped"]
        totals["traders"] += 1

        if stats["fetched"] > 0 or stats["matched"] > 0:
            verb = "Would update" if dry_run else "Updated"
            print(f"  [{i}/{len(traders)}] {address[:20]}... "
                  f"fetched={stats['fetched']} matched={stats['matched']} {verb}={stats['updated']}")
        elif i % 10 == 0:
            print(f"  [{i}/{len(traders)}] processed (running: fetched={totals['fetched']} matched={totals['matched']})")

    conn.close()

    print(f"\n[BACKFILL DONE] traders={totals['traders']} fetched={totals['fetched']} "
          f"matched={totals['matched']} updated={totals['updated']}")

    if not dry_run and totals["updated"] > 0:
        print(f"\n[MAKER/TAKER] Running polygon_maker_taker backfill on {totals['updated']} newly hashed trades...")
        _run_maker_taker_backfill(limit=10000)

    return totals


def _run_maker_taker_backfill(limit: int = 10000):
    """Import and invoke backfill_maker_taker from polygon_maker_taker.py."""
    script_dir = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "polygon_maker_taker",
        script_dir / "polygon_maker_taker.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.backfill_maker_taker(dry_run=False, limit=limit)
    print(f"[MAKER/TAKER] {result}")


# --- Stats ---

def show_stats():
    conn = _get_conn()

    def q(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    total = q("SELECT COUNT(*) FROM trades")
    with_hash = q("SELECT COUNT(*) FROM trades WHERE transaction_hash IS NOT NULL AND transaction_hash != ''")
    without_hash = total - with_hash

    leg_total = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0
    """)
    leg_with = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0
          AND t.transaction_hash IS NOT NULL AND t.transaction_hash != ''
    """)

    pool_c_total = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_accuracy_pool = 1
    """)
    pool_c_with = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_accuracy_pool = 1
          AND t.transaction_hash IS NOT NULL AND t.transaction_hash != ''
    """)

    conn.close()

    print("\n[TX HASH COVERAGE]")
    print(f"  All trades:          {total:,} total | {with_hash:,} with hash ({100*with_hash//total if total else 0}%)")
    print(f"  No hash yet:         {without_hash:,}")
    print(f"\n  LEGENDARY trades:    {leg_total:,} total | {leg_with:,} with hash")
    print(f"  Pool C trades:       {pool_c_total:,} total | {pool_c_with:,} with hash")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="Backfill transaction_hash for Pool C / LEGENDARY traders via Polymarket Data API"
    )
    parser.add_argument("--tier", choices=["legendary", "pool_c", "all"], default="legendary",
                        help="Trader tier to process (default: legendary)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and match but do not write to DB")
    parser.add_argument("--stats", action="store_true",
                        help="Show current transaction_hash coverage stats")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    run_backfill(dry_run=args.dry_run, tier=args.tier)


if __name__ == "__main__":
    main()
