#!/usr/bin/env python3
"""
Read-only before/after comparison for discovery-gap-closure step 3
(2026-08-21-discovery-gap-closure-prereg.md SS A step 3, SS B item 2's
step-3 clause).

batch_update_resolved_markets's own `test_mode=True` branch skips the
mark_market_resolved() call entirely (the whole `if not test_mode:` block
never runs) -- a naive before/after diff run in test_mode would show zero
difference regardless of whether resolution_event_time changed, since
neither run ever reaches the changed line. This harness instead replicates
the function's own matching logic (same SQL, same extract_winner call)
against the frozen resolved_markets_snapshot.json, and calls
mark_market_resolved(dry_run=True) TWICE per genuine candidate -- once
with resolution_event_time=None (the old, pre-step-3 behaviour) and once
with the modified code's _parse_closed_time(closedTime) (the new
behaviour) -- comparing the two written_value['resolution_date'] results
directly. dry_run=True means neither call writes to the DB; the read-only
connection is a further backstop.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.fast_resolution_check import FastResolutionChecker, _parse_closed_time
from monitoring.resolution_writer import mark_market_resolved

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"
SNAPSHOT = Path(__file__).parent / "resolved_markets_snapshot.json"


def main():
    with open(SNAPSHOT) as f:
        resolved_markets = json.load(f)
    print(f"[PRECHECK] Snapshot size: {len(resolved_markets)}")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    cursor = conn.cursor()

    checker = FastResolutionChecker.__new__(FastResolutionChecker)  # extract_winner needs no __init__ state

    already_resolved = 0
    not_found = 0
    no_winner = 0
    candidates = []

    for market_data in resolved_markets:
        condition_id = market_data.get('conditionId')
        api_id = str(market_data.get('id', ''))
        if not condition_id and not api_id:
            not_found += 1
            continue

        cursor.execute("""
            SELECT market_id, resolved FROM markets
            WHERE api_id = ? OR market_id = ? OR condition_id = ?
            LIMIT 1
        """, (api_id, condition_id, condition_id))
        result = cursor.fetchone()
        if not result:
            not_found += 1
            continue

        market_id, is_resolved = result
        if is_resolved:
            already_resolved += 1
            continue

        winner = checker.extract_winner(market_data)
        if not winner:
            no_winner += 1
            continue

        candidates.append((market_id, winner, market_data))

    print(f"[PRECHECK] already_resolved={already_resolved}, not_found={not_found}, "
          f"no_winner={no_winner}, genuine candidates={len(candidates)}")

    usable_closed_time = 0
    unusable_closed_time = 0
    identical = 0
    differ = 0
    diffs = []

    for market_id, winner, market_data in candidates:
        raw_closed_time = market_data.get('closedTime')
        parsed = _parse_closed_time(raw_closed_time)

        if parsed is not None:
            usable_closed_time += 1
        else:
            unusable_closed_time += 1

        before = mark_market_resolved(
            conn, market_id, winning_outcome=winner,
            resolution_event_time=None,
            evidence_source="gamma", evidence_detail="outcomePrices>=0.99",
            dry_run=True,
        )
        after = mark_market_resolved(
            conn, market_id, winning_outcome=winner,
            resolution_event_time=parsed,
            evidence_source="gamma", evidence_detail="outcomePrices>=0.99",
            dry_run=True,
        )

        # Everything except resolution_date must be byte-for-byte identical.
        assert before.accepted == after.accepted, f"{market_id}: accepted differs"
        assert before.reason == after.reason, f"{market_id}: reason differs"
        if before.written_value and after.written_value:
            assert before.written_value['resolved'] == after.written_value['resolved']
            assert before.written_value['winning_outcome'] == after.written_value['winning_outcome']
            assert before.written_value['resolution_evidence_source'] == after.written_value['resolution_evidence_source']

        before_rd = before.written_value['resolution_date'] if before.written_value else None
        after_rd = after.written_value['resolution_date'] if after.written_value else None

        if before_rd == after_rd:
            identical += 1
        else:
            differ += 1
            diffs.append({
                "market_id": market_id,
                "raw_closedTime": raw_closed_time,
                "before_resolution_date": str(before_rd),
                "after_resolution_date": str(after_rd),
            })

    print(f"\n[PRECHECK] usable closedTime: {usable_closed_time}/{len(candidates)}")
    print(f"[PRECHECK] unusable/absent closedTime: {unusable_closed_time}/{len(candidates)}")
    print(f"[PRECHECK] resolution_date IDENTICAL before/after: {identical}")
    print(f"[PRECHECK] resolution_date DIFFERS before/after: {differ}")

    out = {
        "snapshot_size": len(resolved_markets),
        "already_resolved": already_resolved,
        "not_found": not_found,
        "no_winner": no_winner,
        "genuine_candidates": len(candidates),
        "usable_closed_time": usable_closed_time,
        "unusable_closed_time": unusable_closed_time,
        "identical": identical,
        "differ": differ,
        "diffs": diffs,
    }
    out_path = Path(__file__).parent / "gamma_pass_closedtime_precheck_result.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"[PRECHECK] Wrote {out_path}")


if __name__ == "__main__":
    main()
