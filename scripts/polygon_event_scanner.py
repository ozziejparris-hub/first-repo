"""
Scan Polymarket CTF Exchange OrderFilled events directly from Polygon blockchain
using eth_getLogs. Bypasses the Data API's 2-3 day rolling window for full
historical maker/taker coverage going back to V2 genesis (April 28, 2026).

warproxxx/poly_data approach: read events directly from the exchange contract,
not from transaction receipts.
"""

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# --- Constants ---

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"

_env_path = os.path.expanduser("~/.env_trading")
ALCHEMY_RPC: str = ""
with open(_env_path) as _f:
    for _line in _f:
        _line = _line.strip()
        if _line.startswith("POLYGON_RPC_URL="):
            ALCHEMY_RPC = _line.split("=", 1)[1].strip()
            break

if not ALCHEMY_RPC:
    raise RuntimeError("POLYGON_RPC_URL not found in ~/.env_trading")

V2_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"

# Confirmed via receipt inspection (block 82038104): OrderFilled events are emitted by
# 0xC5d563A36AE78145C45a50134d48A1215220f80a (CTF Exchange V1, binary markets).
# 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982e is the Neg Risk CTF Exchange — different
# event topic, not scanned here.
V1_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"

# V2 OrderFilled: topic1=orderHash, topic2=maker(indexed), topic3=taker(indexed)
V2_ORDER_FILLED = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"

# V1 OrderFilled: topic1=orderHash, topic2=maker(indexed), topic3=taker(indexed)
V1_ORDER_FILLED = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"

# V2 genesis block (Polymarket migrated 2026-04-28)
# Polygon mainnet block ~86.28M on April 28; use 86_000_000 as conservative lower bound.
V2_GENESIS_BLOCK = 86_000_000  # 0x51F1B40 — safely before V2 launch

# V1 lookback: ~6 months at 2s/block
V1_LOOKBACK_BLOCKS = 12_960_000

# Alchemy free tier: max 10 blocks per eth_getLogs call.
# Upgrade to PAYG (https://alchemy.com) for 2000 blocks/call (200x faster).
# Override via --block-chunk on the CLI.
BLOCK_CHUNK = 10
RATE_LIMIT_SLEEP = 0.1   # seconds between RPC calls


# --- RPC helper ---

def _rpc_call(method: str, params: list) -> Optional[object]:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        ALCHEMY_RPC,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        time.sleep(RATE_LIMIT_SLEEP)
        if "error" in data:
            print(f"  [RPC ERROR] {method}: {data['error']}")
            return None
        return data.get("result")
    except Exception as e:
        print(f"  [RPC ERROR] {method}: {e}")
        time.sleep(RATE_LIMIT_SLEEP)
        return None


# --- DB helpers ---

def _get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# --- Block timestamp cache (module-level, persists across scan_trader calls) ---

_block_ts_cache: dict = {}


def _get_block_timestamp(block_number: int) -> Optional[int]:
    if block_number in _block_ts_cache:
        return _block_ts_cache[block_number]
    result = _rpc_call("eth_getBlockByNumber", [hex(block_number), False])
    if result and "timestamp" in result:
        ts = int(result["timestamp"], 16)
        _block_ts_cache[block_number] = ts
        return ts
    return None


# --- Function 1: get_current_block ---

def get_current_block() -> int:
    """Call eth_blockNumber via Alchemy RPC. Returns current block as int."""
    result = _rpc_call("eth_blockNumber", [])
    if result is None:
        raise RuntimeError("Failed to fetch current block number from RPC")
    return int(result, 16)


# --- Function 2: get_logs_for_trader ---

def get_logs_for_trader(
    trader_address: str,
    exchange: str,
    topic: str,
    from_block: int,
    to_block: int,
) -> list:
    """
    Call eth_getLogs for trader as maker (topic2) and as taker (topic3).
    Returns combined list of log dicts with role='maker' or role='taker' added.
    Handles rate limiting and errors gracefully.
    """
    print(f"  [get_logs_for_trader] from={from_block} to={to_block} "
          f"range={to_block - from_block + 1} exchange=...{exchange[-6:]}", flush=True)
    padded = "0x000000000000000000000000" + trader_address[2:].lower()
    results = []

    # Maker: trader in topic2
    maker_logs = _rpc_call("eth_getLogs", [{
        "address": exchange,
        "topics": [topic, None, padded],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }])
    if maker_logs:
        for log in maker_logs:
            log["role"] = "maker"
        results.extend(maker_logs)

    # Taker: trader in topic3
    taker_logs = _rpc_call("eth_getLogs", [{
        "address": exchange,
        "topics": [topic, None, None, padded],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }])
    if taker_logs:
        for log in taker_logs:
            log["role"] = "taker"
        results.extend(taker_logs)

    return results


# --- Function 3: scan_trader ---

def scan_trader(
    trader_address: str,
    db_conn: sqlite3.Connection,
    from_block: int = None,
    to_block: int = None,
    dry_run: bool = False,
    block_chunk: int = BLOCK_CHUNK,
) -> dict:
    """
    Scan all OrderFilled events for trader_address across both V1 and V2 exchanges.
    Chunks block range into BLOCK_CHUNK segments.
    Matches events to DB trades and updates transaction_hash + is_taker.
    """
    current = get_current_block()
    to_block = to_block or current

    v2_from = from_block if from_block is not None else V2_GENESIS_BLOCK
    v1_from = from_block if from_block is not None else max(0, current - V1_LOOKBACK_BLOCKS)

    stats = {
        "events_found": 0,
        "maker_events": 0,
        "taker_events": 0,
        "trades_matched": 0,
        "trades_updated": 0,
        "block_range": [v2_from, to_block],
    }

    cursor = db_conn.cursor()

    exchanges = [
        (V2_EXCHANGE, V2_ORDER_FILLED, v2_from, "V2"),
        (V1_EXCHANGE, V1_ORDER_FILLED, v1_from, "V1"),
    ]

    for exchange, topic, ex_from, label in exchanges:
        if ex_from > to_block:
            continue  # exchange not yet deployed relative to to_block
        chunk_start = ex_from
        while chunk_start <= to_block:
            chunk_end = min(chunk_start + block_chunk - 1, to_block)
            logs = get_logs_for_trader(trader_address, exchange, topic, chunk_start, chunk_end)

            if logs:
                # Prefetch timestamp for first block in this chunk; cache handles the rest
                first_block_num = int(logs[0].get("blockNumber", "0x0"), 16)
                _get_block_timestamp(first_block_num)

                for log in logs:
                    tx_hash = log.get("transactionHash") or log.get("transaction_hash", "")
                    block_num = int(log.get("blockNumber", "0x0"), 16)
                    role = log.get("role", "maker")
                    is_taker = 1 if role == "taker" else 0

                    stats["events_found"] += 1
                    if role == "taker":
                        stats["taker_events"] += 1
                    else:
                        stats["maker_events"] += 1

                    block_ts = _get_block_timestamp(block_num)
                    trade_id = None

                    # Match 1: exact transaction hash
                    if tx_hash:
                        cursor.execute("""
                            SELECT trade_id FROM trades
                            WHERE LOWER(trader_address) = LOWER(?)
                              AND transaction_hash = ?
                            LIMIT 1
                        """, (trader_address, tx_hash))
                        row = cursor.fetchone()
                        if row:
                            trade_id = row[0]
                            stats["trades_matched"] += 1

                    # Match 2: fuzzy timestamp ±30 seconds, no hash yet
                    if trade_id is None and block_ts:
                        cursor.execute("""
                            SELECT trade_id FROM trades
                            WHERE LOWER(trader_address) = LOWER(?)
                              AND ABS(strftime('%s', timestamp) - ?) < 30
                              AND (transaction_hash IS NULL OR transaction_hash = '')
                            LIMIT 1
                        """, (trader_address, block_ts))
                        row = cursor.fetchone()
                        if row:
                            trade_id = row[0]
                            stats["trades_matched"] += 1

                    if trade_id is not None:
                        if not dry_run:
                            try:
                                cursor.execute("""
                                    UPDATE trades SET
                                      transaction_hash = ?,
                                      is_taker = ?
                                    WHERE trade_id = ?
                                """, (tx_hash, is_taker, trade_id))
                                db_conn.commit()
                                stats["trades_updated"] += 1
                            except sqlite3.IntegrityError:
                                # Unique index violation — hash already on another trade
                                pass
                        else:
                            stats["trades_updated"] += 1  # would-update count

            chunk_start = chunk_end + 1

    return stats


# --- Function 4: scan_pool_c ---

def scan_pool_c(
    db_path: str = DB_PATH,
    dry_run: bool = False,
    tier: str = "legendary",
    block_chunk: int = BLOCK_CHUNK,
    from_block: int = None,
) -> dict:
    """
    Scan all traders in the specified tier for OrderFilled events.

    tier='legendary': traders WHERE geo_elo >= 2175 AND research_excluded = 0
    tier='pool_c':    traders WHERE geo_accuracy_pool = 1
    """
    print(f"[DEBUG] scan_pool_c() starting: tier={tier} dry_run={dry_run} "
          f"block_chunk={block_chunk} from_block={from_block}", flush=True)
    print(f"[DEBUG] connecting to DB: {db_path}", flush=True)
    conn = _get_conn(db_path)
    print("[DEBUG] DB connected, querying traders...", flush=True)

    if tier == "legendary":
        sql = """
            SELECT address FROM traders
            WHERE geo_elo >= 2175 AND research_excluded = 0
            ORDER BY geo_elo DESC
        """
    else:  # pool_c
        sql = """
            SELECT address FROM traders
            WHERE geo_accuracy_pool = 1
            ORDER BY geo_elo DESC NULLS LAST
        """

    traders = [row[0] for row in conn.execute(sql).fetchall()]
    print(f"[SCAN] tier={tier} dry_run={dry_run} — {len(traders)} traders to process", flush=True)
    print(f"[SCAN] block_chunk={block_chunk} "
          f"({'free tier' if block_chunk <= 10 else 'PAYG tier'})", flush=True)

    # Fetch once — all traders scan to the same tip
    print("[DEBUG] fetching current block via RPC...", flush=True)
    current = get_current_block()
    print(f"[SCAN] current block: {current} (0x{current:x})", flush=True)

    scan_from = from_block if from_block is not None else V2_GENESIS_BLOCK
    v2_range = current - scan_from
    v1_range = V1_LOOKBACK_BLOCKS if from_block is None else min(V1_LOOKBACK_BLOCKS, current - scan_from)
    # Estimate RPC calls (2 calls per chunk × 2 exchanges × traders)
    v2_chunks = v2_range // block_chunk + 1
    v1_chunks = v1_range // block_chunk
    est_calls = len(traders) * (v2_chunks + v1_chunks) * 2
    est_hours = est_calls * RATE_LIMIT_SLEEP / 3600
    print(f"[SCAN] from_block={scan_from} (explicit={from_block is not None})", flush=True)
    print(f"[SCAN] estimated RPC calls: ~{est_calls:,} (~{est_hours:.1f} hours at {RATE_LIMIT_SLEEP}s/call)", flush=True)

    totals = {
        "traders": 0,
        "events_found": 0,
        "maker_events": 0,
        "taker_events": 0,
        "trades_matched": 0,
        "trades_updated": 0,
    }

    for i, address in enumerate(traders, 1):
        stats = scan_trader(address, conn, from_block=from_block, to_block=current, dry_run=dry_run, block_chunk=block_chunk)

        totals["traders"] += 1
        totals["events_found"] += stats["events_found"]
        totals["maker_events"] += stats["maker_events"]
        totals["taker_events"] += stats["taker_events"]
        totals["trades_matched"] += stats["trades_matched"]
        totals["trades_updated"] += stats["trades_updated"]

        if stats["events_found"] > 0 or stats["trades_matched"] > 0:
            verb = "would_update" if dry_run else "updated"
            print(f"  [{i}/{len(traders)}] {address[:20]}... "
                  f"events={stats['events_found']} "
                  f"(M={stats['maker_events']} T={stats['taker_events']}) "
                  f"matched={stats['trades_matched']} {verb}={stats['trades_updated']}", flush=True)
        elif i % 5 == 0:
            print(f"  [{i}/{len(traders)}] {address[:20]}... no events — "
                  f"running: events={totals['events_found']} matched={totals['trades_matched']}", flush=True)

    conn.close()

    print(f"\n[SCAN DONE] traders={totals['traders']} "
          f"events={totals['events_found']} "
          f"(maker={totals['maker_events']} taker={totals['taker_events']}) "
          f"matched={totals['trades_matched']} updated={totals['trades_updated']}", flush=True)

    if not dry_run and totals["trades_updated"] > 0:
        _call_maker_taker_stats()

    return totals


def _call_maker_taker_stats():
    script_dir = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        "polygon_maker_taker",
        script_dir / "polygon_maker_taker.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.get_maker_taker_stats()


# --- Function 5: get_scanner_state ---

def get_scanner_state(db_path: str = DB_PATH) -> dict:
    """
    Show current maker/taker coverage: labeled vs total, taker %, LEGENDARY breakdown.
    """
    conn = _get_conn(db_path)

    def q(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    total_trades = q("SELECT COUNT(*) FROM trades")
    labeled = q("SELECT COUNT(*) FROM trades WHERE is_taker IS NOT NULL")
    taker_count = q("SELECT COUNT(*) FROM trades WHERE is_taker = 1")
    maker_count = q("SELECT COUNT(*) FROM trades WHERE is_taker = 0")
    taker_pct = round(100 * taker_count / labeled, 1) if labeled else 0
    maker_pct = round(100 * maker_count / labeled, 1) if labeled else 0

    leg_total = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo >= 2175 AND tr.research_excluded = 0
    """)
    leg_labeled = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo >= 2175 AND tr.research_excluded = 0
          AND t.is_taker IS NOT NULL
    """)
    leg_taker = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo >= 2175 AND tr.research_excluded = 0 AND t.is_taker = 1
    """)
    leg_maker = q("""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo >= 2175 AND tr.research_excluded = 0 AND t.is_taker = 0
    """)

    conn.close()

    unlabeled = total_trades - labeled
    label_pct = round(100 * labeled / total_trades, 1) if total_trades else 0
    leg_label_pct = round(100 * leg_labeled / leg_total, 1) if leg_total else 0

    state = {
        "total_trades": total_trades,
        "labeled": labeled,
        "taker_count": taker_count,
        "maker_count": maker_count,
        "taker_pct": taker_pct,
        "maker_pct": maker_pct,
        "legendary_total": leg_total,
        "legendary_labeled": leg_labeled,
        "legendary_taker": leg_taker,
        "legendary_maker": leg_maker,
    }

    print("\n[SCANNER STATE]")
    print(f"  Total trades:          {total_trades:,}")
    print(f"  Labeled (is_taker):    {labeled:,} ({label_pct}%)")
    print(f"    Taker:               {taker_count:,} ({taker_pct}%)")
    print(f"    Maker:               {maker_count:,} ({maker_pct}%)")
    print(f"  Unlabeled:             {unlabeled:,}")
    print(f"\n  LEGENDARY (geo_elo >= 2175, research_excluded=0):")
    print(f"    Total trades:        {leg_total:,}")
    print(f"    Labeled:             {leg_labeled:,} ({leg_label_pct}%)")
    print(f"    Taker:               {leg_taker:,}")
    print(f"    Maker:               {leg_maker:,}")

    return state


# --- Main ---

def main():
    print("[DEBUG] main() starting", flush=True)
    print(f"[DEBUG] sys.argv: {sys.argv}", flush=True)
    parser = argparse.ArgumentParser(
        description="Scan Polygon blockchain for Polymarket CTF Exchange OrderFilled events"
    )
    parser.add_argument("--scan-trader", metavar="ADDRESS",
                        help="Scan a single trader address")
    parser.add_argument("--tier", choices=["legendary", "pool_c"],
                        help="Scan all traders in the given tier")
    parser.add_argument("--dry-run", action="store_true",
                        help="Find events and matches but do not write to DB")
    parser.add_argument("--stats", action="store_true",
                        help="Show current maker/taker coverage stats and exit")
    parser.add_argument("--from-block", type=lambda x: int(x, 0), metavar="N",
                        help="Override start block (decimal or 0x hex)")
    parser.add_argument("--to-block", type=lambda x: int(x, 0), metavar="N",
                        help="Override end block (decimal or 0x hex; default: current chain tip)")
    parser.add_argument("--block-chunk", type=int, default=BLOCK_CHUNK, metavar="N",
                        help=f"Blocks per eth_getLogs call (default: {BLOCK_CHUNK}=free tier; "
                             f"PAYG tier supports 2000)")
    args = parser.parse_args()

    if args.stats:
        get_scanner_state()
        return

    if args.scan_trader:
        conn = _get_conn()
        stats = scan_trader(
            args.scan_trader,
            conn,
            from_block=args.from_block,
            to_block=args.to_block,
            dry_run=args.dry_run,
            block_chunk=args.block_chunk,
        )
        conn.close()
        print(f"\n[RESULT] {stats}", flush=True)
        return

    if args.tier:
        scan_pool_c(dry_run=args.dry_run, tier=args.tier, block_chunk=args.block_chunk,
                    from_block=args.from_block)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
