#!/usr/bin/env python3
"""
TRANCHE 1 -- RESUME from row 26 (2026-08-21-discovery-gap-closure-prereg.md,
7614ed7, as amended 2026-08-22 -- SS C, minimum-sample floor + batch/
cumulative separation).

Continues tranche1_write.py's paused run (2026-08-22-tranche1-execution.md,
first-repo 43e268b): 16 writes landed, paused at row 25/317 on a batch/
cumulative-conflated 10% check. This script fixes that conflation per the
amendment and continues.

BATCH vs CUMULATIVE, as amended:
  - Condition 2 (batch, 10%, n>=100 floor) is evaluated over the LAST
    COMPLETED batch. Tranche 1's total population (317) is smaller than
    the standard 500-row batch size (SS C, Batching and resumability) --
    tranche 1 will therefore NEVER produce a completed 500-row batch.
    Condition 2 is consequently never evaluable for tranche 1 and is not
    checked here -- not silently omitted, explicitly not applicable, and
    reported as such.
  - Condition 3 (cumulative, 20%, n>=100 floor) is evaluated over the
    WHOLE RUN TO DATE -- i.e. across BOTH script invocations of tranche 1
    (the 25 rows already processed by tranche1_write.py, plus every row
    this script processes), since tranche 1 is one continuous logical
    execution split across two script runs. This script therefore SEEDS
    its cumulative counters with run 1's final tally before processing
    any new row, rather than starting fresh. Condition 3 is the sole live
    guard protecting this run.

Uses the UNMODIFIED functions from scripts/backfill_market_dates.py
(_get_connection, _fetch_by_clob, _extract_clob_resolution) and
monitoring/resolution_writer.py (mark_market_resolved) -- imported, not
reimplemented, not edited. backfill_market_dates.py's own assertion-branch
commit gap (conditional on a usable end-date) remains worked around
defensively here via an unconditional conn.commit() after every accepted
write, exactly as in tranche1_write.py -- that file is not modified.

Pacing: 0.25s/call per SS C.
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
CUMULATIVE_FLOOR = 100

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

# Carried forward from tranche1_write.py's run (2026-08-22-tranche1-execution.md
# S3S5, first-repo 43e268b, tranche1_write_result.json) -- NOT re-derived, per
# the task's "state carried forward, do not redo" instruction.
RUN1_PROCESSED = 25
RUN1_TALLY = {"resolved": 16, "open": 6, "indeterminate": 0, "no_clob_response": 3}
RUN1_ACCEPTED = 16
RUN1_REJECTED = 0
RUN1_REASONS = {"written": 16}


def atomicity_count(conn):
    return conn.execute(ATOMICITY_QUERY).fetchone()[0]


def main():
    conn = _get_connection()

    pre_atomicity = atomicity_count(conn)
    print(f"[TRANCHE1-RESUME] Pre-write check_resolution_write_atomicity: {pre_atomicity}")
    if pre_atomicity != 0:
        print("[TRANCHE1-RESUME] ABORT CONDITION 4 fired BEFORE any write. Not proceeding.")
        conn.close()
        sys.exit(2)

    rows = conn.execute(TRANCHE1_QUERY).fetchall()
    remaining_n = len(rows)
    expected_remaining = 317 - RUN1_PROCESSED - (RUN1_TALLY["resolved"] - RUN1_TALLY["resolved"])
    # The 16 already-written rows left the candidate set by construction
    # (their resolution_date/end_date are no longer both NULL); the 6 open
    # + 3 no_clob_response from run 1 remain candidates. Confirm, don't assume:
    expected_remaining = 317 - RUN1_TALLY["resolved"]
    print(f"[TRANCHE1-RESUME] Tranche 1 population re-derived at resume time: {remaining_n} "
          f"(expected 317 - {RUN1_TALLY['resolved']} already-resolved = {expected_remaining})")
    if remaining_n != expected_remaining:
        print(f"[TRANCHE1-RESUME] *** MISMATCH: re-derived population ({remaining_n}) != "
              f"expected ({expected_remaining}). Reporting, not assuming the expected figure. ***")

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    # Seed cumulative counters with run 1's results -- condition 3 spans
    # the whole tranche-1 execution, not just this invocation.
    tally = dict(RUN1_TALLY)
    accepted = RUN1_ACCEPTED
    rejected = RUN1_REJECTED
    reasons = dict(RUN1_REASONS)
    processed_total = RUN1_PROCESSED

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
                    print(f"[TRANCHE1-RESUME] *** sqlite3 exception on write for {market_id}: {e} ***")
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

        processed_total += 1
        call_elapsed = time.time() - call_start
        call_times.append(call_elapsed)

        if i % CHECK_EVERY == 0 or i == remaining_n:
            determinate = tally["resolved"] + tally["open"]
            indet_total = tally["indeterminate"] + tally["no_clob_response"]
            classifiable = determinate + indet_total
            cum_indet_rate = (indet_total / classifiable) if classifiable else 0.0

            non_written = {r: c for r, c in reasons.items() if r != "written"}
            non_written_rate = (sum(non_written.values()) / accepted) if accepted else 0.0

            recent_pace = sum(call_times[-CHECK_EVERY:]) / len(call_times[-CHECK_EVERY:])

            cur_atomicity = atomicity_count(conn)

            floor_note = (f"cum_n={classifiable}>={CUMULATIVE_FLOOR} EVALUATED"
                          if classifiable >= CUMULATIVE_FLOOR
                          else f"cum_n={classifiable}<{CUMULATIVE_FLOOR} BELOW FLOOR, recorded only")

            print(f"[TRANCHE1-RESUME] {i}/{remaining_n} (processed_total={processed_total}/317) — "
                  f"tally={tally} accepted={accepted} rejected={rejected} reasons={reasons} "
                  f"cum_indet_rate={cum_indet_rate:.1%} [{floor_note}] "
                  f"recent_pace={recent_pace:.3f}s/call atomicity={cur_atomicity} "
                  f"[condition 2 (batch) N/A -- tranche 1 < 500-row batch size, never completes a batch]")

            if cur_atomicity != 0:
                aborted = True
                abort_reason = f"ABORT CONDITION 4: check_resolution_write_atomicity = {cur_atomicity} at row {i}"
                break
            if classifiable >= CUMULATIVE_FLOOR and cum_indet_rate > 0.20:
                aborted = True
                abort_reason = (f"ABORT CONDITION 3 (cumulative >20%, floor met n={classifiable}): "
                                 f"cum_indet_rate={cum_indet_rate:.1%} at row {i}")
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

    print(f"\n[TRANCHE1-RESUME] {'ABORTED' if aborted else 'COMPLETE'}")
    if aborted:
        print(f"[TRANCHE1-RESUME] Abort reason: {abort_reason}")
    print(f"[TRANCHE1-RESUME] This-run processed: {len(detail)}/{remaining_n}")
    print(f"[TRANCHE1-RESUME] Combined (both runs) processed: {processed_total}/317")
    print(f"[TRANCHE1-RESUME] Combined tally: {tally}")
    print(f"[TRANCHE1-RESUME] Combined mark_market_resolved: accepted={accepted}, rejected={rejected}")
    print(f"[TRANCHE1-RESUME] Combined reason breakdown: {reasons}")
    print(f"[TRANCHE1-RESUME] elapsed (this invocation): {elapsed_total:.1f}s")

    out_path = Path(__file__).parent / "tranche1_resume_result.json"
    with open(out_path, "w") as f:
        json.dump({
            "remaining_population_n": remaining_n,
            "this_run_processed": len(detail),
            "combined_processed": processed_total,
            "aborted": aborted,
            "abort_reason": abort_reason,
            "combined_tally": tally,
            "combined_mark_market_resolved": {"accepted": accepted, "rejected": rejected, "reasons": reasons},
            "elapsed_seconds_this_invocation": elapsed_total,
            "this_run_detail": detail,
        }, f, indent=2, default=str)
    print(f"[TRANCHE1-RESUME] Wrote {out_path}")

    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
