#!/usr/bin/env python3
"""
TRANCHE 1 -- live re-derivation of the expected answer, immediately before
the write (2026-08-21-discovery-gap-closure-prereg.md SS C tranche 1).

This is a fresh copy of step1_verification_v2/q2_census_precheck.py,
unmodified in logic -- same predicate (2026-08-20-discovery-gap-sizing-
prereg.md SS3), same imports of the unmodified backfill_market_dates.py
functions (_fetch_by_clob, _extract_clob_resolution) and the unmodified
mark_market_resolved(), same dry_run=True / read-only DB connection. Run
again today, in a distinctly-named location, per SS G reproducibility (do
not overwrite step 1's original verification artifact; do not treat
203/98/16 as a constant -- re-derive live).

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

    print(f"[TRANCHE1-DRYRUN] Freshly re-derived Q2/tranche-1 census population: {len(rows)}")

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

        clob_response = None
        for cid in filter(None, dict.fromkeys([condition_id, market_id])):
            resp_data = _fetch_by_clob(session, cid)
            if resp_data is not None:
                clob_response = resp_data
                break

        if clob_response is None:
            tally["no_clob_response"] += 1
            detail.append({"market_id": market_id, "classification": "no_clob_response"})
            time.sleep(0.25)
            continue

        classification, winner = _extract_clob_resolution(clob_response)
        tally[classification] += 1

        row_detail = {"market_id": market_id, "classification": classification, "winner": winner}

        if classification == "resolved":
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
            print(f"[TRANCHE1-DRYRUN] {i}/{len(rows)} — {tally}")

        time.sleep(0.25)

    print(f"\n[TRANCHE1-DRYRUN] Final tally: {tally}")
    print(f"[TRANCHE1-DRYRUN] mark_market_resolved (dry_run=True) on 'resolved' classification: "
          f"accepted={accepted}, rejected={rejected}")
    print(f"[TRANCHE1-DRYRUN] reason breakdown: {reasons}")
    determinate = tally["resolved"] + tally["open"]
    total_classifiable = determinate + tally["indeterminate"]
    if total_classifiable:
        print(f"[TRANCHE1-DRYRUN] indeterminate rate (of classifiable, excl. no_clob_response): "
              f"{tally['indeterminate']}/{total_classifiable} = {tally['indeterminate']/total_classifiable:.1%}")

    out_path = Path(__file__).parent / "tranche1_dryrun_precheck_result.json"
    with open(out_path, "w") as f:
        json.dump({
            "population_n": len(rows),
            "tally": tally,
            "mark_market_resolved_dry_run": {"accepted": accepted, "rejected": rejected, "reasons": reasons},
            "detail": detail,
        }, f, indent=2)
    print(f"[TRANCHE1-DRYRUN] Wrote {out_path}")


if __name__ == "__main__":
    main()
