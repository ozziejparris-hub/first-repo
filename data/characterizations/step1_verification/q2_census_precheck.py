#!/usr/bin/env python3
"""
Read-only correctness pre-check for discovery-gap-closure step 1
(2026-08-21-discovery-gap-closure-prereg.md SS B.c).

Runs the MODIFIED backfill_market_dates.py's own functions
(_fetch_by_clob, _extract_clob_resolution) against a freshly re-derived
317-market Q2 census population (predicate:
2026-08-20-discovery-gap-sizing-prereg.md SS3). Additionally exercises
mark_market_resolved(dry_run=True) for every market the new branch would
classify "resolved", to confirm accept/reject behaviour, WITHOUT any
production write (dry_run=True throughout; no --persist, no .commit()
outside of a read-only connection).

This does NOT touch backfill()'s own --geo-only/--limit candidate query at
all (that population currently yields zero matches, see the branch-split
diff artifact) -- it feeds the 317 known market_ids directly into the same
extraction/classification functions the real script now uses, since the
script has no native "run against this explicit list" mode.

Read-only: opens the DB via a mode=ro URI connection. Writes nothing.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.backfill_market_dates import _fetch_by_clob, _extract_clob_resolution
from monitoring.resolution_writer import mark_market_resolved

import requests

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT m.market_id, m.condition_id
        FROM markets m
        JOIN (SELECT DISTINCT market_id FROM trades) t ON t.market_id = m.market_id
        WHERE (m.resolved = 0 OR m.resolved IS NULL)
          AND m.resolution_date IS NULL AND m.end_date IS NULL
          AND m.category IN ('Elections','Geopolitics')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """).fetchall()

    print(f"[Q2-PRECHECK] Freshly re-derived Q2 census population: {len(rows)}")

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    tally = {"resolved": 0, "open": 0, "indeterminate": 0, "no_clob_response": 0}
    accepted = 0
    rejected = 0
    reasons = {}
    detail = []

    for i, row in enumerate(rows, 1):
        market_id = row["market_id"]
        condition_id = row["condition_id"]

        market_data = None
        for cid in filter(None, dict.fromkeys([condition_id, market_id])):
            market_data = _fetch_by_clob(session, cid)
            if market_data:
                break

        if not market_data:
            tally["no_clob_response"] += 1
            detail.append({"market_id": market_id, "classification": "no_clob_response"})
            time.sleep(0.25)
            continue

        classification, winner = _extract_clob_resolution(market_data)
        tally[classification] += 1

        row_detail = {"market_id": market_id, "classification": classification, "winner": winner}

        if classification == "resolved":
            # Read-only: dry_run=True means mark_market_resolved() computes
            # and returns its decision but performs no write.
            result = mark_market_resolved(
                conn, market_id,
                winning_outcome=winner,
                resolution_event_time=None,
                evidence_source="clob",
                evidence_detail="token.winner",
                dry_run=True,
            )
            if result.accepted:
                accepted += 1
            else:
                rejected += 1
            reasons[result.reason] = reasons.get(result.reason, 0) + 1
            row_detail["mmr_accepted"] = result.accepted
            row_detail["mmr_reason"] = result.reason

        detail.append(row_detail)

        if i % 50 == 0:
            print(f"[Q2-PRECHECK] {i}/{len(rows)} — {tally}")

        time.sleep(0.25)

    print(f"\n[Q2-PRECHECK] Final tally: {tally}")
    print(f"[Q2-PRECHECK] mark_market_resolved (dry_run=True) on 'resolved' classification: "
          f"accepted={accepted}, rejected={rejected}")
    print(f"[Q2-PRECHECK] reason breakdown: {reasons}")

    out_path = Path(__file__).parent / f"q2_census_precheck_result.json"
    with open(out_path, "w") as f:
        json.dump({
            "population_n": len(rows),
            "tally": tally,
            "mark_market_resolved_dry_run": {"accepted": accepted, "rejected": rejected, "reasons": reasons},
            "detail": detail,
        }, f, indent=2)
    print(f"[Q2-PRECHECK] Wrote {out_path}")


if __name__ == "__main__":
    main()
