#!/usr/bin/env python3
"""
Pre-drain manifest: every trade row the geo pending-results drain would touch.

Step 2 of 3 (2026-09-09-geo-drain-blast-radius.md Part 5). READ-ONLY. Writes ONE
JSON artifact under data/characterizations/. Modifies nothing.

Rows = the check_pending_geo predicate (scripts/audit_invariants.py:305-311):
  trade_result = 'pending' AND markets.resolved = 1 AND gap-clean
  AND markets.category IN ('Geopolitics','Elections')

Per row: trade_id, trader_address, market_id, timestamp, trade_result,
data_source; the derived position_id where the trade is a position's
entry_trade_ids[0]; and a pre/post-split label by the MARKET's tape_end
(MAX(trades.timestamp) for that market) against T_split = 2026-04-01.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

T_SPLIT = "2026-04-01"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "characterizations")


def _git_commit(repo_dir):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = conn.cursor()

    # 1. the pending set (check_pending_geo predicate)
    cur.execute("""
        CREATE TEMP TABLE pend AS
        SELECT tr.trade_id, tr.trader_address, tr.market_id, tr.timestamp,
               tr.trade_result, tr.data_source
        FROM trades tr JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trade_result = 'pending' AND m.resolved = 1
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND m.category IN ('Geopolitics','Elections')
    """)
    cur.execute("CREATE INDEX ix_pend_tid ON pend(trade_id)")
    cur.execute("CREATE INDEX ix_pend_mid ON pend(market_id)")
    (n_rows,) = cur.execute("SELECT COUNT(*) FROM pend").fetchone()

    # live check_pending_geo count, same predicate, for the match assertion
    (live_count,) = cur.execute("""
        SELECT COUNT(*) FROM trades tr JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trade_result = 'pending' AND m.resolved = 1
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND m.category IN ('Geopolitics','Elections')
    """).fetchone()

    # 2. tape_end per involved market (MAX trade ts on that market, DB-wide)
    cur.execute("""
        CREATE TEMP TABLE pend_te AS
        SELECT p.market_id, MAX(t.timestamp) AS tape_end
        FROM (SELECT DISTINCT market_id FROM pend) p
        JOIN trades t ON t.market_id = p.market_id
        GROUP BY p.market_id
    """)
    cur.execute("CREATE INDEX ix_pte ON pend_te(market_id)")

    # 3. position_id(s) where the pending trade is a position's entry_trade_ids[0].
    # A trade CAN be entry_trade_ids[0] of more than one position row (rare data
    # oddity), so this is aggregated to a list -- the manifest stays exactly one
    # row per pending trade_id.
    entry_map = {}
    for tid, pid in cur.execute("""
        SELECT json_extract(p.entry_trade_ids, '$[0]') AS trade_id, p.position_id
        FROM positions p
        WHERE json_extract(p.entry_trade_ids, '$[0]') IN (SELECT trade_id FROM pend)
    """).fetchall():
        entry_map.setdefault(tid, []).append(pid)

    rows = cur.execute(f"""
        SELECT p.trade_id, p.trader_address, p.market_id, p.timestamp,
               p.trade_result, p.data_source,
               te.tape_end,
               CASE WHEN te.tape_end < '{T_SPLIT}' THEN 'pre_split' ELSE 'post_split' END AS split_side
        FROM pend p
        LEFT JOIN pend_te te ON te.market_id = p.market_id
    """).fetchall()

    manifest = []
    for tid, addr, mid, tstamp, tr, ds, tape_end, side in rows:
        pids = sorted(entry_map.get(tid, []))
        manifest.append(dict(
            trade_id=tid, trader_address=addr, market_id=mid, timestamp=tstamp,
            trade_result=tr, data_source=ds,
            position_id=(pids[0] if pids else None),
            position_ids=pids,
            is_position_entry=bool(pids),
            market_tape_end=tape_end, split_side=side,
        ))

    n_multi_pos = sum(1 for m in manifest if len(m["position_ids"]) > 1)
    n_entry = sum(1 for m in manifest if m["is_position_entry"])
    n_pre = sum(1 for m in manifest if m["split_side"] == "pre_split")
    n_post = sum(1 for m in manifest if m["split_side"] == "post_split")
    n_pre_entry = sum(1 for m in manifest if m["split_side"] == "pre_split" and m["position_id"])
    n_post_entry = sum(1 for m in manifest if m["split_side"] == "post_split" and m["position_id"])
    distinct_traders = len({m["trader_address"] for m in manifest})
    distinct_markets = len({m["market_id"] for m in manifest})

    conn.close()

    generated_at = datetime.now(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"predrain_geo_drain_manifest_{ts}.json")

    doc = dict(
        spec="capture_predrain_geo_drain_manifest",
        purpose="pre-drain manifest: every trade row the geo pending-results drain would touch",
        generated_at=generated_at,
        script_commit=_git_commit(repo_dir),
        db_path=os.path.abspath(args.db),
        t_split=T_SPLIT,
        predicate="trade_result='pending' AND markets.resolved=1 AND gap-clean AND "
                  "category IN ('Geopolitics','Elections')",
        counts=dict(
            manifest_rows=len(manifest),
            distinct_pending_trade_ids=n_rows,
            live_check_pending_geo=live_count,
            matches_live=(len(manifest) == live_count == n_rows),
            distinct_traders=distinct_traders,
            distinct_markets=distinct_markets,
            position_entry_rows=n_entry,
            trades_that_are_entry_of_multiple_positions=n_multi_pos,
            pre_split_rows=n_pre, post_split_rows=n_post,
            pre_split_position_entry_rows=n_pre_entry,
            post_split_position_entry_rows=n_post_entry,
        ),
        manifest=manifest,
    )

    assert len(manifest) == n_rows == live_count, \
        f"manifest integrity: len(manifest)={len(manifest)} n_rows={n_rows} live={live_count}"

    os.makedirs(args.out_dir, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=2, default=str)

    print(f"manifest_rows={len(manifest)}  distinct_pending_trade_ids={n_rows}  "
          f"live_check_pending_geo={live_count}  matches={len(manifest) == live_count == n_rows}")
    print(f"distinct_traders={distinct_traders} distinct_markets={distinct_markets}")
    print(f"position_entry_rows={n_entry}  multi_position_entry_trades={n_multi_pos}  "
          f"pre_split={n_pre} (entry {n_pre_entry})  post_split={n_post} (entry {n_post_entry})")
    print(f"[json] {out_path}")


if __name__ == "__main__":
    main()
