#!/usr/bin/env python3
"""
Polygon Wallet Lookup

Queries the Etherscan V2 API (Polygon chain, chainid=137) to retrieve:
  - True wallet creation date (first-ever transaction)
  - True USDC funding source (first USDC transfer to wallet)

Used to enrich insider_signals with on-chain provenance data that is
unavailable from Polymarket's trade history alone.

Usage:
    python scripts/polygon_wallet_lookup.py                        # test two known addresses
    python scripts/polygon_wallet_lookup.py --address 0xABC...    # single wallet lookup
    python scripts/polygon_wallet_lookup.py --enrich               # enrich all NULL rows in DB
    python scripts/polygon_wallet_lookup.py --enrich --dry-run    # preview without DB writes
    python scripts/polygon_wallet_lookup.py --market <market_id>  # cluster funding check
"""

import sys
import time
import sqlite3
import logging
import argparse
import json
import urllib.request
import urllib.parse
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 137                                                        # Polygon PoS
RATE_LIMIT = 5                                                        # calls/sec (free tier)
USDC_POLYGON = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"          # native USDC on Polygon

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"
ENV_FILE = Path.home() / ".env_trading"


# ── API key loading ────────────────────────────────────────────────────────────

def _load_api_key() -> str:
    """Load ETHERSCAN_API_KEY from environment or ~/.env_trading."""
    import os
    key = os.environ.get("ETHERSCAN_API_KEY")
    if key:
        return key

    if not ENV_FILE.exists():
        raise RuntimeError(
            f"~/.env_trading not found and ETHERSCAN_API_KEY not set in environment. "
            "Add ETHERSCAN_API_KEY=<your_key> to ~/.env_trading."
        )

    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if line.startswith("ETHERSCAN_API_KEY="):
            return line.split("=", 1)[1].strip()

    raise RuntimeError(
        "ETHERSCAN_API_KEY not found in ~/.env_trading. "
        "Add: ETHERSCAN_API_KEY=<your_key>"
    )


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_enrichment_columns(conn: sqlite3.Connection):
    """Add wallet provenance columns to insider_signals if not present (migration-safe)."""
    for col_sql in [
        "ALTER TABLE insider_signals ADD COLUMN wallet_creation_date TEXT DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN true_wallet_age_days INTEGER DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN funding_wallet TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass  # column already exists
    conn.commit()


def _ensure_trader_wallet_columns(conn: sqlite3.Connection):
    """Add wallet provenance columns to traders table if not present (migration-safe)."""
    for col_sql in [
        "ALTER TABLE traders ADD COLUMN wallet_creation_date TEXT DEFAULT NULL",
        "ALTER TABLE traders ADD COLUMN true_wallet_age_days INTEGER DEFAULT NULL",
        "ALTER TABLE traders ADD COLUMN funding_wallet TEXT DEFAULT NULL",
        "ALTER TABLE traders ADD COLUMN is_contract_wallet BOOLEAN DEFAULT NULL",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass  # column already exists
    conn.commit()


# ── Etherscan API calls ────────────────────────────────────────────────────────

def get_wallet_first_transaction(address: str) -> dict | None:
    """
    Query Etherscan for the oldest normal transaction on this Polygon wallet.

    Returns:
        {
          "address": str,
          "first_tx_timestamp": int,       # unix epoch
          "first_tx_date": str,            # ISO-8601 UTC
          "first_tx_hash": str,
          "funding_wallet": str,           # lowercase 'from' address
          "is_contract_wallet": bool,      # True if Gnosis Safe / execTransaction
          "wallet_age_days": int,          # days from first tx to now
          "source": "etherscan_polygon"
        }
    Returns None if no transactions found or on API error.
    """
    api_key = _load_api_key()
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    params = urllib.parse.urlencode({
        "chainid": CHAIN_ID,
        "module": "account",
        "action": "txlist",
        "address": address,
        "page": 1,
        "offset": 1,
        "sort": "asc",
        "apikey": api_key,
    })

    try:
        with urllib.request.urlopen(f"{BASE_URL}?{params}", timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error(f"[etherscan] txlist request failed for {address}: {e}")
        return None

    if data.get("status") != "1" or not data.get("result"):
        msg = data.get("message", "")
        if msg == "No transactions found":
            logger.info(f"[etherscan] no transactions for {address}")
        else:
            logger.error(f"[etherscan] txlist error for {address}: {msg}")
        return None

    tx = data["result"][0]
    first_ts = int(tx.get("timeStamp", 0))
    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat()

    fn_name = tx.get("functionName", "")
    is_contract = "execTransaction" in fn_name or "Safe" in fn_name

    return {
        "address": address,
        "first_tx_timestamp": first_ts,
        "first_tx_date": first_dt,
        "first_tx_hash": tx.get("hash", ""),
        "funding_wallet": tx.get("from", "").lower(),
        "is_contract_wallet": is_contract,
        "wallet_age_days": (now_ts - first_ts) // 86400,
        "source": "etherscan_polygon",
    }


def get_wallet_usdc_funding_source(address: str) -> dict | None:
    """
    Query Etherscan for the first native USDC (Polygon) transfer into this wallet.
    This is the true economic funding source — more reliable than the first tx.

    Returns:
        {
          "address": str,
          "first_usdc_timestamp": int,
          "first_usdc_date": str,          # ISO-8601 UTC
          "usdc_funding_wallet": str,      # lowercase sender
          "usdc_amount": float,            # USDC (6-decimal adjusted)
          "source": "etherscan_polygon"
        }
    Returns None if no USDC transfers found or on API error.
    """
    api_key = _load_api_key()

    params = urllib.parse.urlencode({
        "chainid": CHAIN_ID,
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDC_POLYGON,
        "address": address,
        "page": 1,
        "offset": 1,
        "sort": "asc",
        "apikey": api_key,
    })

    try:
        with urllib.request.urlopen(f"{BASE_URL}?{params}", timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error(f"[etherscan] tokentx request failed for {address}: {e}")
        return None

    if data.get("status") != "1" or not data.get("result"):
        msg = data.get("message", "")
        if msg == "No transactions found":
            logger.info(f"[etherscan] no USDC transfers for {address}")
        else:
            logger.error(f"[etherscan] tokentx error for {address}: {msg}")
        return None

    tx = data["result"][0]
    first_ts = int(tx.get("timeStamp", 0))
    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat()

    usdc_amount = int(tx.get("value", 0)) / 1_000_000.0  # USDC has 6 decimals

    return {
        "address": address,
        "first_usdc_timestamp": first_ts,
        "first_usdc_date": first_dt,
        "usdc_funding_wallet": tx.get("from", "").lower(),
        "usdc_amount": round(usdc_amount, 2),
        "source": "etherscan_polygon",
    }


# ── Bulk enrichment ────────────────────────────────────────────────────────────

def enrich_insider_signals(db_path: str = DB_PATH, dry_run: bool = False) -> int:
    """
    Enrich all insider_signals rows where wallet_creation_date IS NULL.

    For each wallet:
      1. get_wallet_first_transaction → wallet_creation_date, true_wallet_age_days
      2. get_wallet_usdc_funding_source → funding_wallet (preferred over first-tx funder)

    Rate-limited to RATE_LIMIT calls/sec (0.2s sleep between calls).
    Returns count of rows updated (or that would be updated in dry_run mode).
    """
    conn = _connect(db_path)
    _ensure_enrichment_columns(conn)

    cur = conn.cursor()
    cur.execute("""
        SELECT id, trader_address, trade_timestamp
        FROM insider_signals
        WHERE wallet_creation_date IS NULL
    """)
    rows = cur.fetchall()

    if not rows:
        logger.info("[enrich] no rows need enrichment")
        conn.close()
        return 0

    logger.info(f"[enrich] enriching {len(rows)} signal(s)...")
    updated = 0

    for row in rows:
        sig_id = row["id"]
        address = row["trader_address"]
        trade_ts_str = row["trade_timestamp"]

        tx_info = get_wallet_first_transaction(address)
        time.sleep(1.0 / RATE_LIMIT)  # 0.2s between calls — free tier cap

        usdc_info = get_wallet_usdc_funding_source(address)
        time.sleep(1.0 / RATE_LIMIT)

        if tx_info is None and usdc_info is None:
            logger.warning(f"[enrich] no on-chain data for {address} (signal {sig_id})")
            continue

        wallet_creation_date = tx_info["first_tx_date"] if tx_info else None
        true_age = None

        if tx_info and trade_ts_str:
            try:
                creation_dt = datetime.fromisoformat(tx_info["first_tx_date"])
                trade_dt = datetime.fromisoformat(trade_ts_str)
                # Strip timezone for naive comparison
                if creation_dt.tzinfo is not None:
                    creation_dt = creation_dt.replace(tzinfo=None)
                if trade_dt.tzinfo is not None:
                    trade_dt = trade_dt.replace(tzinfo=None)
                true_age = max(0, (trade_dt - creation_dt).days)
            except Exception as e:
                logger.warning(f"[enrich] age calc failed for {address}: {e}")

        # USDC funding wallet preferred; fall back to first-tx from-address
        funding_wallet = None
        if usdc_info:
            funding_wallet = usdc_info.get("usdc_funding_wallet")
        elif tx_info:
            funding_wallet = tx_info.get("funding_wallet")

        if dry_run:
            logger.info(
                f"[dry-run] signal {sig_id} {address[:10]}... "
                f"created={wallet_creation_date} age={true_age}d funded_by={funding_wallet}"
            )
            updated += 1
            continue

        try:
            conn.execute("""
                UPDATE insider_signals
                SET wallet_creation_date = ?,
                    true_wallet_age_days  = ?,
                    funding_wallet        = ?
                WHERE id = ?
            """, (wallet_creation_date, true_age, funding_wallet, sig_id))
            conn.commit()
            updated += 1
            logger.info(
                f"[enrich] updated signal {sig_id}: {address[:10]}... "
                f"created={wallet_creation_date} age={true_age}d"
            )
        except sqlite3.OperationalError as e:
            logger.error(f"[enrich] DB write failed for signal {sig_id}: {e}")

    conn.close()
    return updated


# ── Pool C backfill ───────────────────────────────────────────────────────────

def backfill_pool_c_wallet_ages(db_path: str = DB_PATH, dry_run: bool = False) -> dict:
    """
    Backfill true wallet creation dates for all Pool C traders
    (geo_accuracy_pool = 1) who don't have wallet_creation_date yet.

    Adds columns to traders table if not exist:
    - wallet_creation_date TEXT DEFAULT NULL
    - true_wallet_age_days INTEGER DEFAULT NULL
    - funding_wallet TEXT DEFAULT NULL
    - is_contract_wallet BOOLEAN DEFAULT NULL

    Rate limit: 0.2s between API calls (5/sec max)
    Reports progress every 50 traders.
    """
    conn = _connect(db_path)
    _ensure_trader_wallet_columns(conn)

    cur = conn.cursor()
    cur.execute("""
        SELECT address
        FROM traders
        WHERE geo_accuracy_pool = 1
          AND wallet_creation_date IS NULL
        ORDER BY geo_elo DESC
    """)
    rows = cur.fetchall()
    total = len(rows)

    if not total:
        logger.info("[backfill-pool-c] all Pool C traders already enriched")
        conn.close()
        return {"found": 0, "updated": 0, "skipped": 0, "dry_run": dry_run}

    logger.info(f"[backfill-pool-c] {total} Pool C trader(s) need wallet enrichment")

    if dry_run:
        logger.info("[backfill-pool-c] *** DRY RUN — no API calls or DB writes ***")
        # Sample up to 5 addresses so the caller can sanity-check
        samples = [r["address"] for r in rows[:5]]
        for addr in samples:
            logger.info(f"[dry-run] would enrich: {addr}")
        conn.close()
        return {"found": total, "updated": 0, "skipped": 0, "dry_run": True}

    updated = 0
    skipped = 0

    for i, row in enumerate(rows, 1):
        address = row["address"]

        tx_info = get_wallet_first_transaction(address)
        time.sleep(1.0 / RATE_LIMIT)

        usdc_info = get_wallet_usdc_funding_source(address)
        time.sleep(1.0 / RATE_LIMIT)

        if tx_info is None and usdc_info is None:
            logger.warning(f"[backfill-pool-c] no on-chain data for {address}")
            skipped += 1
        else:
            wallet_creation_date = tx_info["first_tx_date"] if tx_info else None
            true_wallet_age_days = tx_info["wallet_age_days"] if tx_info else None
            is_contract_wallet = tx_info["is_contract_wallet"] if tx_info else None

            funding_wallet = None
            if usdc_info:
                funding_wallet = usdc_info.get("usdc_funding_wallet")
            elif tx_info:
                funding_wallet = tx_info.get("funding_wallet")

            try:
                conn.execute("""
                    UPDATE traders
                    SET wallet_creation_date = ?,
                        true_wallet_age_days  = ?,
                        funding_wallet        = ?,
                        is_contract_wallet    = ?
                    WHERE address = ?
                """, (wallet_creation_date, true_wallet_age_days,
                      funding_wallet, is_contract_wallet, address))
                conn.commit()
                updated += 1
                logger.info(
                    f"[backfill-pool-c] {address[:12]}... "
                    f"created={wallet_creation_date} age={true_wallet_age_days}d "
                    f"funded_by={funding_wallet} contract={is_contract_wallet}"
                )
            except sqlite3.OperationalError as e:
                logger.error(f"[backfill-pool-c] DB write failed for {address}: {e}")
                skipped += 1

        if i % 50 == 0:
            logger.info(
                f"[backfill-pool-c] progress: {i}/{total} processed, "
                f"{updated} updated, {skipped} skipped"
            )

    conn.close()
    logger.info(f"[backfill-pool-c] done: {updated} updated, {skipped} skipped / {total} total")
    return {"found": total, "updated": updated, "skipped": skipped, "dry_run": False}


# ── Cluster funding analysis ───────────────────────────────────────────────────

def check_cluster_shared_funding(market_id: str, db_path: str = DB_PATH) -> dict:
    """
    For all insider_signals in a given market_id, group wallets by shared funding_wallet.
    Two or more trader wallets sharing a funding source = strong cluster correlation signal
    (common controller or coordinated funding).

    Returns dict with group breakdown. Run --enrich first if funding_wallet is NULL.
    """
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, trader_address, funding_wallet, position_size, trade_timestamp
        FROM insider_signals
        WHERE market_id = ?
        ORDER BY trade_timestamp
    """, (market_id,))
    all_rows = cur.fetchall()

    cur.execute("""
        SELECT id, trader_address, funding_wallet, position_size, trade_timestamp
        FROM insider_signals
        WHERE market_id = ?
          AND funding_wallet IS NOT NULL
        ORDER BY trade_timestamp
    """, (market_id,))
    enriched_rows = cur.fetchall()
    conn.close()

    if not enriched_rows:
        return {
            "market_id": market_id,
            "total_signals": len(all_rows),
            "wallets_with_funding_data": 0,
            "shared_funding_groups": [],
            "cluster_signal": False,
            "note": "No wallets with funding_wallet data — run --enrich first",
        }

    funder_map: dict = defaultdict(list)
    for row in enriched_rows:
        funder_map[row["funding_wallet"]].append({
            "signal_id": row["id"],
            "trader_address": row["trader_address"],
            "position_size": row["position_size"],
            "trade_timestamp": row["trade_timestamp"],
        })

    shared_groups = [
        {
            "funding_wallet": funder,
            "wallet_count": len(wallets),
            "combined_position": round(sum(w["position_size"] or 0.0 for w in wallets), 2),
            "wallets": wallets,
        }
        for funder, wallets in funder_map.items()
        if len(wallets) >= 2
    ]
    shared_groups.sort(key=lambda g: g["wallet_count"], reverse=True)

    return {
        "market_id": market_id,
        "total_signals": len(all_rows),
        "wallets_with_funding_data": len(enriched_rows),
        "shared_funding_groups": shared_groups,
        "cluster_signal": len(shared_groups) > 0,
    }


# ── CLI helpers ────────────────────────────────────────────────────────────────

def _print_wallet_summary(address: str):
    """Run both lookups for one address and print a formatted summary."""
    print(f"\n{'='*60}")
    print(f"  WALLET: {address}")
    print(f"{'='*60}")

    print("\n[1/2] First transaction (wallet creation)...")
    tx_info = get_wallet_first_transaction(address)
    if tx_info:
        print(f"  Created      : {tx_info['first_tx_date']}")
        print(f"  Age          : {tx_info['wallet_age_days']} days")
        print(f"  First tx     : {tx_info['first_tx_hash'][:20]}...")
        print(f"  Funded from  : {tx_info['funding_wallet']}")
        print(f"  Gnosis Safe  : {tx_info['is_contract_wallet']}")
    else:
        print("  No transactions found on Polygon")

    time.sleep(1.0 / RATE_LIMIT)

    print("\n[2/2] First USDC transfer...")
    usdc_info = get_wallet_usdc_funding_source(address)
    if usdc_info:
        print(f"  First USDC   : {usdc_info['first_usdc_date']}")
        print(f"  Amount       : ${usdc_info['usdc_amount']:,.2f}")
        print(f"  USDC funder  : {usdc_info['usdc_funding_wallet']}")
    else:
        print("  No USDC transfers found on Polygon")

    time.sleep(1.0 / RATE_LIMIT)
    print()


def main():
    parser = argparse.ArgumentParser(description="Polygon wallet lookup via Etherscan V2")
    parser.add_argument("--address", help="Single wallet address to look up")
    parser.add_argument("--enrich", action="store_true",
                        help="Enrich all insider_signals rows with NULL wallet_creation_date")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview enrichment without writing to DB")
    parser.add_argument("--market",
                        help="Check shared funding sources for all signals in a market_id")
    parser.add_argument("--backfill-pool-c", action="store_true",
                        help="Backfill wallet creation dates for all Pool C (geo_accuracy_pool=1) traders")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database")
    args = parser.parse_args()

    if args.address:
        _print_wallet_summary(args.address)

    if args.enrich:
        print(f"\n{'='*60}")
        print("  ENRICHING INSIDER SIGNALS — WALLET PROVENANCE")
        if args.dry_run:
            print("  *** DRY RUN — no writes ***")
        print(f"{'='*60}\n")
        updated = enrich_insider_signals(db_path=args.db, dry_run=args.dry_run)
        print(f"\n[enrich] Done. {updated} signal(s) updated.")

    if args.market:
        print(f"\n{'='*60}")
        print(f"  CLUSTER FUNDING CHECK — {args.market[:20]}...")
        print(f"{'='*60}\n")
        result = check_cluster_shared_funding(args.market, db_path=args.db)
        print(json.dumps(result, indent=2, default=str))

    if args.backfill_pool_c:
        print(f"\n{'='*60}")
        print("  BACKFILL POOL C — WALLET AGES VIA ETHERSCAN")
        if args.dry_run:
            print("  *** DRY RUN — no API calls or DB writes ***")
        print(f"{'='*60}\n")
        result = backfill_pool_c_wallet_ages(db_path=args.db, dry_run=args.dry_run)
        print(f"\n[backfill-pool-c] Result: {json.dumps(result, indent=2)}")

    if not any([args.address, args.enrich, args.market, args.backfill_pool_c]):
        # Default: test on the two known insider signal addresses
        print("\nRunning test on two known insider signal addresses...\n")
        test_addresses = [
            "0x53e55bc7cb3d67ad177c023ce891ad076a9d6177",  # signal ID 3
            "0x39fb70130977938f4f6d5cfe5e9fced522e332c7",  # signal ID 4
        ]
        for addr in test_addresses:
            _print_wallet_summary(addr)


if __name__ == "__main__":
    main()
