#!/usr/bin/env python3
"""
Phase 1 verification item 3, per 2026-08-21-discovery-gap-closure-prereg.md
(832198d, as amended): sample rows matched by the combo/parlay carve-out
predicate and check DIRECTLY against CLOB whether they return a usable
response -- do not infer from the absence of identifiers alone.

Predicate under test:
  LENGTH(market_id) = 64 AND SUBSTR(market_id, 37) = '0000000000000000000000000000'
  (last 28 of 64 hex characters are all zero)

Uses the unmodified _fetch_by_clob from scripts/backfill_market_dates.py --
not reimplemented. Read-only against the DB (mode=ro); makes real network
calls to the CLOB API (the same third-party endpoint every driver in this
arc has called), writes nothing to the database.
"""
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.backfill_market_dates import _fetch_by_clob

import requests

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"
SAMPLE_SIZE = 40
SEED = 20260822

CARVEOUT_PREDICATE = """
    (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
    AND LENGTH(market_id) = 64
    AND SUBSTR(market_id, 37) = '0000000000000000000000000000'
"""


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(f"""
        SELECT market_id, condition_id, title FROM markets WHERE {CARVEOUT_PREDICATE}
    """).fetchall()
    print(f"[CARVEOUT-VERIFY] Full carve-out population: {len(rows)}")

    random.seed(SEED)
    sample = random.sample(rows, SAMPLE_SIZE)
    print(f"[CARVEOUT-VERIFY] Sampled {len(sample)} rows, seed={SEED}")

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    results = []
    for row in sample:
        market_id = row["market_id"]
        condition_id = row["condition_id"]  # always None for this cohort, confirmed

        # Mirrors the driver's own identifier-selection logic exactly.
        response = None
        tried = []
        for cid in filter(None, dict.fromkeys([condition_id, market_id])):
            tried.append(cid)
            response = _fetch_by_clob(session, cid)
            if response is not None:
                break

        results.append({
            "market_id": market_id,
            "title": row["title"],
            "identifiers_tried": tried,
            "clob_response": response,
        })
        status = "USABLE RESPONSE" if response is not None else "no response (None)"
        print(f"[CARVEOUT-VERIFY] {market_id[:24]}... tried={tried} -> {status}")
        time.sleep(0.25)

    usable = sum(1 for r in results if r["clob_response"] is not None)
    print(f"\n[CARVEOUT-VERIFY] {usable}/{len(results)} returned a usable CLOB response")

    conn.close()
    return results, usable


if __name__ == "__main__":
    main()
