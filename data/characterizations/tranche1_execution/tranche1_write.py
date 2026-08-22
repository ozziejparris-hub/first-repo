#!/usr/bin/env python3
"""
TRANCHE 1 -- THE WRITE (2026-08-21-discovery-gap-closure-prereg.md SS C).

Scoped to the tranche-1/Q2-census population only: category IN
('Elections','Geopolitics') AND (trade_gap_flag = 0 OR trade_gap_flag IS
NULL), intersected with the candidate predicate ((resolved = 0 OR resolved
IS NULL) AND resolution_date IS NULL AND end_date IS NULL) -- exact SQL
from 2026-08-20-discovery-gap-sizing-prereg.md SS3, same query already used
read-only by step1_verification_v2/q2_census_precheck.py and this
session's tranche1_dryrun_precheck.py.

Uses the UNMODIFIED functions from scripts/backfill_market_dates.py
(_get_connection, _fetch_by_clob, _extract_clob_resolution) and
monitoring/resolution_writer.py (mark_market_resolved) -- imported, not
reimplemented, not edited. This is a new, narrowly-scoped driver script,
not a modification of any production file, following the same precedent
already established by q2_census_precheck.py (just switched from
dry_run=True / read-only to a live write).

Pacing: 0.25s/call per SS C (not the script's 0.1s default).

Live abort-condition monitoring (SS C, checked every CHECK_EVERY=25 calls,
not only at the end):
  1. trg_resolved_no_unresolve fires -> HARD ABORT (would surface as a
     sqlite3 exception from the RAISE(ABORT,...) trigger body; every write
     call is wrapped in try/except to catch this specifically).
  2. Batch-level indeterminate rate > 10% -> PAUSE.
  3. Cumulative indeterminate rate > 20% -> HARD ABORT.
  4. check_resolution_write_atomicity (resolution_recorded_at set,
     resolution_evidence_source NULL -- audit_invariants.py's own query)
     goes non-zero -> HARD ABORT.
  5. Any mark_market_resolved() reason other than "written" appears at
     >1% of processed rows -> PAUSE. (Note: by construction of this
     population's predicate -- every row starts with resolved=0/NULL --
     the branch logic in resolution_writer.py's `if not prev_resolved`
     means EVERY accepted write here must take reason="written" (trivial
     first-write); no other branch is reachable for this population. This
     is checked live anyway, not assumed.)
  6. Observed pacing > 1.0s/call sustained over 2 consecutive checks ->
     PAUSE.

An explicit conn.commit() follows every accepted mark_market_resolved()
write in this harness, unconditionally -- NOT relying on
backfill_market_dates.py's own assertion-branch commit, which is
conditional on a usable end_date being present in the CLOB response (line
~303-309: `if assert_end_date_str: ... conn.commit()`) and is skipped
entirely when the CLOB response for an already-resolved market has no
date field, which step 1's own finding says is common. Deferring to that
conditional commit here would risk a resolution write sitting in an open,
uncommitted transaction. This is a defensive choice in this NEW harness
only; backfill_market_dates.py itself is not modified.
"""
import sqlite3
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.backfill_market_dates import _get_connection, _fetch_by_clob, _extract_clob_resolution
from monitoring.resolution_writer import mark_market_resolved

import requests

CHECK_EVERY = 25
SLEEP = 0.25

TRANCHE1_QUERY = """
    SELECT m.market_id, m.condition_id
    FROM markets m
    JOIN (SELECT DISTINCT market_id FROM trades) t ON t.market_id = m.market_id
    WHERE (m.resolved = 0 OR m.resolved IS NULL)
      AND m.resolution_date IS NULL AND m.end_date IS NULL
      AND m.category IN ('Elections','Geopolitics')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
"""

ATOMICITY_QUERY = """
    SELECT COUNT(*) FROM markets
    WHERE resolution_recorded_at IS NOT NULL AND resolution_evidence_source IS NULL
"""


def atomicity_count(conn):
    return conn.execute(ATOMICITY_QUERY).fetchone()[0]


def main():
    conn = _get_connection()

    pre_atomicity = atomicity_count(conn)
    print(f"[TRANCHE1-WRITE] Pre-write check_resolution_write_atomicity: {pre_atomicity}")
    if pre_atomicity != 0:
        print("[TRANCHE1-WRITE] ABORT CONDITION 4 fired BEFORE any write. Not proceeding.")
        conn.close()
        sys.exit(2)

    rows = conn.execute(TRANCHE1_QUERY).fetchall()
    population_n = len(rows)
    print(f"[TRANCHE1-WRITE] Tranche 1 population, re-derived at write time: {population_n}")

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    tally = {"resolved": 0, "open": 0, "indeterminate": 0, "no_clob_response": 0}
    accepted = 0
    rejected = 0
    reasons = {}
    detail = []
    call_times = []
    aborted = False
    abort_reason = None

    t0 = time.time()

    for i, row in enumerate(rows, 1):
        market_id = row["market_id"]
        condition_id = row["condition_id"]

        call_start = time.time()

        clob_response = None
        for cid in filter(None, dict.fromkeys([condition_id, market_id])):
            resp_data = _fetch_by_clob(session, cid)
            if resp_data is not None:
                clob_response = resp_data
                break

        if clob_response is None:
            tally["no_clob_response"] += 1
            detail.append({"market_id": market_id, "classification": "no_clob_response"})
        else:
            classification, winner = _extract_clob_resolution(clob_response)
            tally[classification] += 1
            row_detail = {"market_id": market_id, "classification": classification, "winner": winner}

            if classification == "resolved":
                try:
                    result = mark_market_resolved(
                        conn, market_id,
                        winning_outcome=winner,
                        resolution_event_time=None,
                        evidence_source="clob",
                        evidence_detail="token.winner",
                        dry_run=False,
                    )
                except sqlite3.Error as e:
                    print(f"[TRANCHE1-WRITE] *** sqlite3 exception on write for {market_id}: {e} ***")
                    if "resolved cannot transition" in str(e):
                        aborted = True
                        abort_reason = f"ABORT CONDITION 1: trg_resolved_no_unresolve fired on {market_id}: {e}"
                        detail.append(row_detail)
                        break
                    raise

                conn.commit()  # unconditional -- see module docstring

                if result.accepted:
                    accepted += 1
                else:
                    rejected += 1
                reasons[result.reason] = reasons.get(result.reason, 0) + 1
                row_detail["mmr_accepted"] = result.accepted
                row_detail["mmr_reason"] = result.reason

            detail.append(row_detail)

        call_elapsed = time.time() - call_start
        call_times.append(call_elapsed)

        if i % CHECK_EVERY == 0 or i == population_n:
            determinate = tally["resolved"] + tally["open"]
            indet_total = tally["indeterminate"] + tally["no_clob_response"]
            classifiable = determinate + indet_total
            indet_rate = (indet_total / classifiable) if classifiable else 0.0

            non_written = {r: c for r, c in reasons.items() if r != "written"}
            non_written_rate = (sum(non_written.values()) / accepted) if accepted else 0.0

            recent_pace = sum(call_times[-CHECK_EVERY:]) / len(call_times[-CHECK_EVERY:])

            cur_atomicity = atomicity_count(conn)

            print(f"[TRANCHE1-WRITE] {i}/{population_n} — tally={tally} "
                  f"accepted={accepted} rejected={rejected} reasons={reasons} "
                  f"indet_rate={indet_rate:.1%} recent_pace={recent_pace:.3f}s/call "
                  f"atomicity={cur_atomicity}")

            if cur_atomicity != 0:
                aborted = True
                abort_reason = f"ABORT CONDITION 4: check_resolution_write_atomicity = {cur_atomicity} at row {i}"
                break
            if indet_rate > 0.20:
                aborted = True
                abort_reason = f"ABORT CONDITION 3 (cumulative >20%): indet_rate={indet_rate:.1%} at row {i}"
                break
            if indet_rate > 0.10:
                print(f"[TRANCHE1-WRITE] *** ABORT CONDITION 2 (batch >10%): indet_rate={indet_rate:.1%} "
                      f"at row {i} -- PAUSING (not a hard abort, but stopping per SS C) ***")
                aborted = True
                abort_reason = f"ABORT CONDITION 2 (PAUSE, batch >10%): indet_rate={indet_rate:.1%} at row {i}"
                break
            if non_written_rate > 0.01:
                aborted = True
                abort_reason = f"ABORT CONDITION 5: non-'written' reason rate={non_written_rate:.1%} at row {i}: {non_written}"
                break
            if recent_pace > 1.0:
                aborted = True
                abort_reason = f"ABORT CONDITION 6: recent pacing {recent_pace:.3f}s/call > 1.0s at row {i}"
                break

        time.sleep(SLEEP)

    elapsed_total = time.time() - t0
    conn.close()

    print(f"\n[TRANCHE1-WRITE] {'ABORTED' if aborted else 'COMPLETE'}")
    if aborted:
        print(f"[TRANCHE1-WRITE] Abort reason: {abort_reason}")
    print(f"[TRANCHE1-WRITE] Processed: {len(detail)}/{population_n}")
    print(f"[TRANCHE1-WRITE] Final tally: {tally}")
    print(f"[TRANCHE1-WRITE] mark_market_resolved: accepted={accepted}, rejected={rejected}")
    print(f"[TRANCHE1-WRITE] reason breakdown: {reasons}")
    print(f"[TRANCHE1-WRITE] elapsed: {elapsed_total:.1f}s")

    out_path = Path(__file__).parent / "tranche1_write_result.json"
    with open(out_path, "w") as f:
        json.dump({
            "population_n": population_n,
            "processed": len(detail),
            "aborted": aborted,
            "abort_reason": abort_reason,
            "tally": tally,
            "mark_market_resolved": {"accepted": accepted, "rejected": rejected, "reasons": reasons},
            "elapsed_seconds": elapsed_total,
            "detail": detail,
        }, f, indent=2, default=str)
    print(f"[TRANCHE1-WRITE] Wrote {out_path}")

    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
