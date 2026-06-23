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
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitoring.column_definitions as cd

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

# Polygon block-time constants for timestamp→block estimation
POLYGON_GENESIS_TIMESTAMP = 1590824836  # Polygon mainnet genesis, May 30 2020
POLYGON_GENESIS_BLOCK = 0
POLYGON_BLOCKS_PER_SECOND = 1.0 / 2.1
BLOCK_WINDOW_BUFFER = 50_000  # ~29 hours; pad either side of activity window

# Starting chunk size for eth_getLogs calls; adapts down automatically on timeout.
# Alchemy PAYG supports up to 2000 blocks/call; free tier is capped at 10.
# Override via --block-chunk on the CLI.
BLOCK_CHUNK = 500
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
            print(f"  [RPC ERROR] {method}: {data['error']}", flush=True)
            return None
        return data.get("result")
    except Exception as e:
        print(f"  [RPC ERROR] {method}: {e}", flush=True)
        time.sleep(RATE_LIMIT_SLEEP)
        return None


def _rpc_call_raw(method: str, params: list) -> dict:
    """Returns the full JSON-RPC response dict; never raises. 'error' key present on failure."""
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
        return data
    except Exception as e:
        time.sleep(RATE_LIMIT_SLEEP)
        return {"error": {"code": -1, "message": str(e)}}


_TIMEOUT_PATTERN = re.compile(r'\[0x[0-9a-f]+,\s*0x([0-9a-f]+)\]')


def _fetch_logs(params: dict) -> tuple[list, int]:
    """
    Call eth_getLogs with adaptive timeout retry.
    Returns (logs, effective_to_block).
    On -32000 timeout, extracts suggested toBlock from the error message, retries,
    and returns the smaller effective range so the caller can adapt its chunk size.
    """
    from_block = int(params["fromBlock"], 16)
    to_block = int(params["toBlock"], 16)

    resp = _rpc_call_raw("eth_getLogs", [params])
    if "result" in resp:
        return resp["result"], to_block

    error = resp.get("error", {})
    if error.get("code") == -32000 and "Query timeout exceeded" in error.get("message", ""):
        match = _TIMEOUT_PATTERN.search(error["message"])
        if match:
            suggested_to = int(match.group(1), 16)
            working_chunk = suggested_to - from_block + 1
            old_chunk = to_block - from_block + 1
            print(f"  [ADAPTIVE] chunk reduced from {old_chunk} to {working_chunk} due to timeout",
                  flush=True)
            retry_params = dict(params, toBlock=hex(suggested_to))
            retry_resp = _rpc_call_raw("eth_getLogs", [retry_params])
            if "result" in retry_resp:
                return retry_resp["result"], suggested_to
            error = retry_resp.get("error", {})

    print(f"  [RPC ERROR] eth_getLogs: {error}", flush=True)
    return [], to_block


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


# --- Function 1b: get_trader_block_range ---

def get_trader_block_range(
    trader_address: str,
    db_conn: sqlite3.Connection,
    exchange_genesis: int,
    current_block: int,
) -> tuple[int, int]:
    """
    Derive a targeted block scan window from the trader's DB trade history.
    Converts first/last trade timestamps to estimated Polygon block numbers,
    adds BLOCK_WINDOW_BUFFER on each side, then clamps to [exchange_genesis, current_block].
    Falls back to (exchange_genesis, current_block) when trader has no trades in DB.
    """
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT MIN(strftime('%s', timestamp)), MAX(strftime('%s', timestamp)) "
        "FROM trades WHERE LOWER(trader_address) = LOWER(?)",
        (trader_address,)
    )
    row = cursor.fetchone()
    if row is None or row[0] is None:
        return exchange_genesis, current_block

    first_ts = int(row[0])
    last_ts = int(row[1])
    est_first = int(POLYGON_GENESIS_BLOCK + (first_ts - POLYGON_GENESIS_TIMESTAMP) * POLYGON_BLOCKS_PER_SECOND)
    est_last = int(POLYGON_GENESIS_BLOCK + (last_ts - POLYGON_GENESIS_TIMESTAMP) * POLYGON_BLOCKS_PER_SECOND)

    from_block = max(exchange_genesis, est_first - BLOCK_WINDOW_BUFFER)
    to_block = min(current_block, est_last + BLOCK_WINDOW_BUFFER)
    return from_block, to_block


# --- Function 2: get_logs_for_trader ---

def get_logs_for_trader(
    trader_address: str,
    exchange: str,
    topic: str,
    from_block: int,
    to_block: int,
) -> tuple[list, int]:
    """
    Call eth_getLogs for trader as maker (topic2) and as taker (topic3).
    Returns (combined_logs, effective_to_block).
    effective_to_block < to_block when a timeout forced a smaller range;
    the caller should adapt its chunk size and resume from effective_to_block + 1.
    """
    print(f"  [get_logs_for_trader] from={from_block} to={to_block} "
          f"range={to_block - from_block + 1} exchange=...{exchange[-6:]}", flush=True)
    padded = "0x000000000000000000000000" + trader_address[2:].lower()
    results = []

    # Maker: trader in topic2
    maker_logs, effective_to = _fetch_logs({
        "address": exchange,
        "topics": [topic, None, padded],
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    })
    for log in maker_logs:
        log["role"] = "maker"
    results.extend(maker_logs)

    # Taker: trader in topic3 — honour effective_to from maker to skip a known-bad range
    taker_logs, taker_effective_to = _fetch_logs({
        "address": exchange,
        "topics": [topic, None, None, padded],
        "fromBlock": hex(from_block),
        "toBlock": hex(effective_to),
    })
    if taker_effective_to < effective_to:
        effective_to = taker_effective_to
    for log in taker_logs:
        log["role"] = "taker"
    results.extend(taker_logs)

    return results, effective_to


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
    Chunks block range into block_chunk segments.
    Matches events to DB trades and updates transaction_hash + is_taker.
    When from_block is None, derives a targeted window from the trader's DB activity.
    """
    current = get_current_block()
    to_block_cap = to_block or current

    if from_block is not None:
        v1_from, v1_to = from_block, to_block_cap
        v2_from, v2_to = max(V2_GENESIS_BLOCK, from_block), to_block_cap
        skip_v1 = False
        skip_v2 = v2_from > v2_to
    else:
        v2_from, v2_to = get_trader_block_range(trader_address, db_conn, V2_GENESIS_BLOCK, current)
        v1_from, v1_to = get_trader_block_range(trader_address, db_conn, 0, current)
        v2_to = min(v2_to, to_block_cap)
        v1_to = min(v1_to, to_block_cap)
        skip_v2 = v2_from > v2_to
        skip_v1 = v1_from > V2_GENESIS_BLOCK

    v1_blocks = max(0, v1_to - v1_from + 1) if not skip_v1 else 0
    v2_blocks = max(0, v2_to - v2_from + 1) if not skip_v2 else 0
    chunks_v1 = (v1_blocks + block_chunk - 1) // block_chunk if v1_blocks > 0 else 0
    chunks_v2 = (v2_blocks + block_chunk - 1) // block_chunk if v2_blocks > 0 else 0
    total_chunks = chunks_v1 + chunks_v2
    est_minutes = total_chunks * 2 * RATE_LIMIT_SLEEP / 60

    if skip_v1:
        print(f"[SCAN_TRADER] {trader_address} V1: SKIP (first trade after V2 genesis)", flush=True)
    else:
        print(f"[SCAN_TRADER] {trader_address} V1: blocks {v1_from}..{v1_to} ({v1_blocks:,} blocks)", flush=True)
    if skip_v2:
        print(f"[SCAN_TRADER] {trader_address} V2: SKIP (last trade before V2 genesis)", flush=True)
    else:
        print(f"[SCAN_TRADER] {trader_address} V2: blocks {v2_from}..{v2_to} ({v2_blocks:,} blocks)", flush=True)
    print(f"[SCAN_TRADER] estimated chunks: {total_chunks} (~{est_minutes:.1f} min)", flush=True)

    active_ranges = []
    if not skip_v1:
        active_ranges.append((v1_from, v1_to))
    if not skip_v2:
        active_ranges.append((v2_from, v2_to))
    block_range = (
        [min(r[0] for r in active_ranges), max(r[1] for r in active_ranges)]
        if active_ranges else [0, 0]
    )

    stats = {
        "events_found": 0,
        "maker_events": 0,
        "taker_events": 0,
        "trades_matched": 0,
        "trades_updated": 0,
        "block_range": block_range,
    }

    cursor = db_conn.cursor()

    exchanges = []
    if not skip_v2:
        exchanges.append((V2_EXCHANGE, V2_ORDER_FILLED, v2_from, v2_to, "V2"))
    if not skip_v1:
        exchanges.append((V1_EXCHANGE, V1_ORDER_FILLED, v1_from, v1_to, "V1"))

    chunk_num = 0
    for exchange, topic, ex_from, ex_to, label in exchanges:
        chunk_start = ex_from
        while chunk_start <= ex_to:
            chunk_end = min(chunk_start + block_chunk - 1, ex_to)
            logs, effective_end = get_logs_for_trader(trader_address, exchange, topic, chunk_start, chunk_end)
            if effective_end < chunk_end:
                block_chunk = effective_end - chunk_start + 1
            chunk_end = effective_end

            chunk_num += 1
            if chunk_num % 50 == 0:
                print(f"[PROGRESS] chunk {chunk_num}/{total_chunks} | "
                      f"blocks {chunk_start}-{chunk_end} | "
                      f"events_so_far={stats['events_found']}", flush=True)

            if logs:
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
        sql = f"""
            SELECT address FROM traders
            WHERE geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND research_excluded = 0
            ORDER BY geo_elo_active DESC
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

    leg_total = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0
    """)
    leg_labeled = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0
          AND t.is_taker IS NOT NULL
    """)
    leg_taker = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0 AND t.is_taker = 1
    """)
    leg_maker = q(f"""
        SELECT COUNT(*) FROM trades t
        JOIN traders tr ON t.trader_address = tr.address
        WHERE tr.geo_elo_active >= {cd.GEO_ELO_LEGENDARY} AND tr.research_excluded = 0 AND t.is_taker = 0
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

    print("\n[SCANNER STATE]", flush=True)
    print(f"  Total trades:          {total_trades:,}", flush=True)
    print(f"  Labeled (is_taker):    {labeled:,} ({label_pct}%)", flush=True)
    print(f"    Taker:               {taker_count:,} ({taker_pct}%)", flush=True)
    print(f"    Maker:               {maker_count:,} ({maker_pct}%)", flush=True)
    print(f"  Unlabeled:             {unlabeled:,}", flush=True)
    print(f"\n  LEGENDARY (geo_elo >= 2175, research_excluded=0):", flush=True)
    print(f"    Total trades:        {leg_total:,}", flush=True)
    print(f"    Labeled:             {leg_labeled:,} ({leg_label_pct}%)", flush=True)
    print(f"    Taker:               {leg_taker:,}", flush=True)
    print(f"    Maker:               {leg_maker:,}", flush=True)

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
                        help=f"Blocks per eth_getLogs call (default: {BLOCK_CHUNK}; "
                             f"adapts down on timeout; PAYG supports up to 2000)")
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
