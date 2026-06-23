"""
Label every trade in the DB as maker or taker using Polygon RPC transaction receipts.
This is the definitive LP filter for geo_elo — takers are directional, makers are LPs.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitoring.column_definitions as cd

# --- Constants ---

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"

_env_path = os.path.expanduser("~/.env_trading")
with open(_env_path) as _f:
    for _line in _f:
        _line = _line.strip()
        if _line.startswith("POLYGON_RPC_URL="):
            ALCHEMY_RPC = _line.split("=", 1)[1]
            break

EXCHANGE_CONTRACT = "0xe111180000d2663c0091e4f400237545b87b996b"
ORDER_FILLED_TOPIC = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"

V1_EXCHANGE = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
V1_ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"

RATE_LIMIT_SLEEP = 0.1


# --- DB helpers ---

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _apply_migrations():
    """Idempotently add transaction_hash and is_taker columns to trades."""
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trades)")
    existing = {row[1] for row in cursor.fetchall()}

    if "transaction_hash" not in existing:
        cursor.execute("ALTER TABLE trades ADD COLUMN transaction_hash TEXT DEFAULT NULL")
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_tx_hash
            ON trades(transaction_hash)
            WHERE transaction_hash IS NOT NULL AND transaction_hash != ''
        """)
        print("[MIGRATION] Added transaction_hash column + unique index")

    if "is_taker" not in existing:
        cursor.execute("ALTER TABLE trades ADD COLUMN is_taker BOOLEAN DEFAULT NULL")
        print("[MIGRATION] Added is_taker column")

    conn.commit()
    conn.close()


# --- Function 1: get_transaction_receipt ---

def get_transaction_receipt(tx_hash: str) -> Optional[dict]:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_getTransactionReceipt",
        "params": [tx_hash],
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        ALCHEMY_RPC,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data.get("result")
        time.sleep(RATE_LIMIT_SLEEP)
        return result
    except Exception as e:
        print(f"  [RPC ERROR] {tx_hash[:20]}... — {e}")
        time.sleep(RATE_LIMIT_SLEEP)
        return None


# --- Function 2: extract_maker_taker ---

def extract_maker_taker(receipt: dict, trader_address: str) -> Optional[str]:
    """
    Return 'taker', 'maker', or None based on OrderFilled log topics.

    topic0 = event signature
    topic1 = orderHash  (indexed)
    topic2 = maker      (indexed)
    topic3 = taker      (indexed)

    Checks both V1 and V2 CTF Exchange logs.
    Exchange contract as taker = intermediary sub-event — skip.
    """
    trader = trader_address.lower()
    v2_exchange = EXCHANGE_CONTRACT.lower()
    v1_exchange = V1_EXCHANGE.lower()
    v2_topic = ORDER_FILLED_TOPIC.lower()
    v1_topic = V1_ORDER_FILLED_TOPIC.lower()

    logs = receipt.get("logs", [])

    is_taker_in_tx = False
    is_maker_in_tx = False

    for log in logs:
        topics = log.get("topics", [])
        if not topics:
            continue
        topic0 = topics[0].lower()

        if topic0 == v2_topic:
            exchange = v2_exchange
        elif topic0 == v1_topic:
            exchange = v1_exchange
        else:
            continue

        if len(topics) < 4:
            continue

        maker_addr = "0x" + topics[2][-40:]
        taker_addr = "0x" + topics[3][-40:]

        # Real taker = not the exchange contract itself (intermediary sub-event)
        real_taker = taker_addr.lower() != exchange

        if taker_addr.lower() == trader and real_taker:
            is_taker_in_tx = True

        if maker_addr.lower() == trader:
            is_maker_in_tx = True

    if is_taker_in_tx:
        return "taker"
    if is_maker_in_tx:
        return "maker"
    return None


# --- Function 3: backfill_maker_taker ---

def backfill_maker_taker(
    db_path: str = DB_PATH,
    dry_run: bool = False,
    limit: int = 1000,
) -> dict:
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT trade_id, trader_address, transaction_hash
        FROM trades
        WHERE is_taker IS NULL
          AND transaction_hash IS NOT NULL
          AND transaction_hash != ''
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    total = len(rows)
    print(f"[BACKFILL] {total} trades to process (dry_run={dry_run}, limit={limit})")

    stats = {
        "processed": 0,
        "taker_count": 0,
        "maker_count": 0,
        "not_found": 0,
        "errors": 0,
    }

    for i, (trade_id, trader_address, tx_hash) in enumerate(rows, 1):
        if i % 100 == 0:
            print(f"  [{i}/{total}] processed={stats['processed']} "
                  f"taker={stats['taker_count']} maker={stats['maker_count']} "
                  f"not_found={stats['not_found']} errors={stats['errors']}")

        receipt = get_transaction_receipt(tx_hash)
        if receipt is None:
            stats["errors"] += 1
            continue

        result = extract_maker_taker(receipt, trader_address)

        if dry_run:
            logs = receipt.get("logs", [])
            _known_topics = {ORDER_FILLED_TOPIC.lower(), V1_ORDER_FILLED_TOPIC.lower()}
            order_logs = [
                lg for lg in logs
                if lg.get("topics", []) and lg["topics"][0].lower() in _known_topics
            ]
            print(f"\n  trade_id:        {trade_id}")
            print(f"  trader_address:  {trader_address}")
            print(f"  tx_hash:         {tx_hash}")
            print(f"  OrderFilled logs found: {len(order_logs)}")
            for lg in order_logs:
                topics = lg.get("topics", [])
                if len(topics) >= 4:
                    maker = "0x" + topics[2][-40:]
                    taker = "0x" + topics[3][-40:]
                    print(f"    log_index={lg.get('logIndex')} maker={maker} taker={taker}")
            print(f"  Result: {result or 'not_found'}")

        stats["processed"] += 1
        if result == "taker":
            stats["taker_count"] += 1
        elif result == "maker":
            stats["maker_count"] += 1
        else:
            stats["not_found"] += 1

        if not dry_run and result is not None:
            conn = _get_conn()
            conn.execute(
                "UPDATE trades SET is_taker = ? WHERE trade_id = ?",
                (1 if result == "taker" else 0, trade_id),
            )
            conn.commit()
            conn.close()

    print(f"\n[BACKFILL DONE] {stats}")
    return stats


# --- Function 4: get_maker_taker_stats ---

def get_maker_taker_stats(db_path: str = DB_PATH) -> dict:
    conn = _get_conn()

    def q(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    total_labeled = q("SELECT COUNT(*) FROM trades WHERE is_taker IS NOT NULL")
    taker_count = q("SELECT COUNT(*) FROM trades WHERE is_taker = 1")
    maker_count = q("SELECT COUNT(*) FROM trades WHERE is_taker = 0")
    taker_pct = round(100 * taker_count / total_labeled, 1) if total_labeled else 0
    maker_pct = round(100 * maker_count / total_labeled, 1) if total_labeled else 0

    # Pool C breakdown (geo_accuracy_pool = 1)
    pool_c_taker = q("""
        SELECT COUNT(*) FROM trades t
        INNER JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_accuracy_pool = 1 AND t.is_taker = 1
    """)
    pool_c_maker = q("""
        SELECT COUNT(*) FROM trades t
        INNER JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_accuracy_pool = 1 AND t.is_taker = 0
    """)

    # LEGENDARY breakdown (geo_elo_active >= GEO_ELO_LEGENDARY, research_excluded = 0)
    leg_taker = q(f"""
        SELECT COUNT(*) FROM trades t
        INNER JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0 AND t.is_taker = 1
    """)
    leg_maker = q(f"""
        SELECT COUNT(*) FROM trades t
        INNER JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0 AND t.is_taker = 0
    """)

    conn.close()

    stats = {
        "total_labeled": total_labeled,
        "taker_count": taker_count,
        "maker_count": maker_count,
        "taker_pct": taker_pct,
        "maker_pct": maker_pct,
        "pool_c_taker": pool_c_taker,
        "pool_c_maker": pool_c_maker,
        "legendary_taker": leg_taker,
        "legendary_maker": leg_maker,
    }

    print("\n[MAKER/TAKER STATS]")
    print(f"  Total labeled:        {total_labeled:,}")
    print(f"  Taker:                {taker_count:,} ({taker_pct}%)")
    print(f"  Maker:                {maker_count:,} ({maker_pct}%)")
    print(f"\n  Pool C (geo_accuracy_pool=1):")
    print(f"    Taker:              {pool_c_taker:,}")
    print(f"    Maker:              {pool_c_maker:,}")
    print(f"\n  LEGENDARY (geo_elo_active >= 2175, research_excluded=0):")
    print(f"    Taker:              {leg_taker:,}")
    print(f"    Maker:              {leg_maker:,}")

    return stats


# --- Main ---

def main():
    _apply_migrations()

    parser = argparse.ArgumentParser(description="Label trades as maker/taker via Polygon RPC")
    parser.add_argument("--backfill", action="store_true", help="Backfill is_taker for unlabeled trades")
    parser.add_argument("--dry-run", action="store_true", help="Test on first N trades — no DB writes")
    parser.add_argument("--stats", action="store_true", help="Print current maker/taker stats")
    parser.add_argument("--limit", type=int, default=1000, help="Number of trades to process (default: 1000)")
    args = parser.parse_args()

    if args.stats:
        get_maker_taker_stats()
        return

    if args.dry_run:
        backfill_maker_taker(dry_run=True, limit=args.limit)
        return

    if args.backfill:
        backfill_maker_taker(dry_run=False, limit=args.limit)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
