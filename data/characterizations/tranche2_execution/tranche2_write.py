#!/usr/bin/env python3
"""
TRANCHE 2 -- THE WRITE (2026-08-21-discovery-gap-closure-prereg.md,
7614ed7 as amended, SS C tranche 2).

Reads the FIXED, pre-materialized 5,000-market sample
(tranche2_sample_5000.json, drawn once by tranche2_sample_materialize.py,
seed=20260821) -- never re-samples, per pre-flight question 2's
resolution: re-deriving the sample after a kill would draw a different
set from the now-smaller live population, invalidating the kill-and-
resume test.

Processes in 500-row batches (fixed slices of the persisted list, in list
order -- 10 batches total). After each batch: atomic checkpoint
(write-to-temp-then-os.rename) to data/checkpoints/tranche2_checkpoint.json,
recording cumulative + per-batch counts, the set of market_ids already
successfully written (used to skip on resume -- so a restart never
re-attempts an already-resolved market, not even as a harmless no-op),
last market_id processed, and observed pacing.

Resumable: on start, loads the checkpoint if present and skips any
market_id already in its `resolved_market_ids` set. Batch boundaries are
fixed slices of the persisted list; a restart re-enters the batch it was
interrupted in and skips already-resolved rows within it, freshly
attempting the rest.

Abort conditions (SS C, as amended -- n=100 floor, batch and cumulative
tracked SEPARATELY):
  - Batch-level (condition 2, 10%, n>=100 floor): evaluated over rows
    FRESHLY attempted in the current batch during this invocation (not
    skipped-because-already-resolved rows). Batch size is 500, so the
    floor is always cleared for a batch with any meaningful fresh-attempt
    volume.
  - Cumulative (condition 3, 20%, n>=100 floor): evaluated over the whole
    persisted, cross-restart cumulative tally.
  - trg_resolved_no_unresolve fires -> HARD ABORT (caught via try/except).
  - check_resolution_write_atomicity non-zero -> HARD ABORT.
  - Any mark_market_resolved() reason other than "written" or the
    untagged-legacy-improvement variant, above 1% of processed rows ->
    PAUSE. (Per pre-flight question 1, this population excludes
    already-resolved rows by construction, same as tranche 1 -- the
    untagged-legacy branch is not expected to fire here either, but is
    permitted, unlike a same-rank disagreement, which is not.)
  - Observed pacing > 1.0s/call sustained over 2 consecutive batches ->
    PAUSE.

Uses the UNMODIFIED functions from scripts/backfill_market_dates.py
(_get_connection, _fetch_by_clob, _extract_clob_resolution) and
monitoring/resolution_writer.py (mark_market_resolved). An explicit
conn.commit() follows every accepted write, unconditionally -- same
defensive choice as tranche1_write.py/tranche1_resume.py, for the same
reason (backfill_market_dates.py's own assertion-branch commit is
conditional on a usable end-date being present; not modified here).

Pacing: 0.25s/call.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.backfill_market_dates import _get_connection, _fetch_by_clob, _extract_clob_resolution
from monitoring.resolution_writer import mark_market_resolved

import requests

SLEEP = 0.25
BATCH_SIZE = 500
CUMULATIVE_FLOOR = 100
BATCH_FLOOR = 100

SAMPLE_PATH = Path(__file__).parent / "tranche2_sample_5000.json"
CHECKPOINT_PATH = Path(__file__).resolve().parents[3] / "data" / "checkpoints" / "tranche2_checkpoint.json"

ATOMICITY_QUERY = """
    SELECT COUNT(*) FROM markets
    WHERE resolution_recorded_at IS NOT NULL AND resolution_evidence_source IS NULL
"""

ACCEPTED_REASONS = {
    "written",
    "written: existing value has no recorded evidence_source (pre-canonical), proposal accepted",
}


def atomicity_count(conn):
    return conn.execute(ATOMICITY_QUERY).fetchone()[0]


def load_checkpoint():
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return None


def write_checkpoint(state):
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CHECKPOINT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, CHECKPOINT_PATH)  # atomic on POSIX


def main():
    with open(SAMPLE_PATH) as f:
        sample_doc = json.load(f)
    sample = sample_doc["sample"]
    assert len(sample) == 5000, f"expected 5000-market fixed sample, got {len(sample)}"
    print(f"[TRANCHE2-WRITE] Loaded fixed sample: {len(sample)} markets, seed={sample_doc['seed']}")

    conn = _get_connection()

    pre_atomicity = atomicity_count(conn)
    print(f"[TRANCHE2-WRITE] Pre-write check_resolution_write_atomicity: {pre_atomicity}")
    if pre_atomicity != 0:
        print("[TRANCHE2-WRITE] ABORT CONDITION fired BEFORE any write. Not proceeding.")
        conn.close()
        sys.exit(2)

    checkpoint = load_checkpoint()
    if checkpoint is not None:
        print(f"[TRANCHE2-WRITE] RESUMING from checkpoint: batches_completed="
              f"{checkpoint['batches_completed']}, cumulative_processed={checkpoint['cumulative_processed']}, "
              f"resolved_so_far={len(checkpoint['resolved_market_ids'])}")
        resolved_ids = set(checkpoint["resolved_market_ids"])
        cum_tally = checkpoint["cumulative_tally"]
        cum_accepted = checkpoint["cumulative_accepted"]
        cum_rejected = checkpoint["cumulative_rejected"]
        cum_reasons = checkpoint["cumulative_reasons"]
        batches_completed = checkpoint["batches_completed"]
        cumulative_processed = checkpoint["cumulative_processed"]
        per_batch_history = checkpoint["per_batch_history"]
        cumulative_elapsed = checkpoint.get("elapsed_seconds_cumulative", 0.0)
    else:
        print("[TRANCHE2-WRITE] No checkpoint found -- starting fresh.")
        resolved_ids = set()
        cum_tally = {"resolved": 0, "open": 0, "indeterminate": 0, "no_clob_response": 0}
        cum_accepted = 0
        cum_rejected = 0
        cum_reasons = {}
        batches_completed = 0
        cumulative_processed = 0
        per_batch_history = []
        cumulative_elapsed = 0.0

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    n_batches = (len(sample) + BATCH_SIZE - 1) // BATCH_SIZE  # 10
    aborted = False
    abort_reason = None
    batch_pace_history = []

    for batch_num in range(batches_completed, n_batches):
        batch_slice = sample[batch_num * BATCH_SIZE: (batch_num + 1) * BATCH_SIZE]
        print(f"\n[TRANCHE2-WRITE] === Batch {batch_num + 1}/{n_batches} "
              f"({len(batch_slice)} markets in slice) ===")

        batch_tally = {"resolved": 0, "open": 0, "indeterminate": 0, "no_clob_response": 0}
        batch_fresh_attempted = 0
        batch_skipped = 0
        batch_call_times = []
        batch_t0 = time.time()
        last_market_id = None

        for entry in batch_slice:
            market_id = entry["market_id"]
            condition_id = entry["condition_id"]

            if market_id in resolved_ids:
                batch_skipped += 1
                continue

            call_start = time.time()

            clob_response = None
            for cid in filter(None, dict.fromkeys([condition_id, market_id])):
                resp_data = _fetch_by_clob(session, cid)
                if resp_data is not None:
                    clob_response = resp_data
                    break

            if clob_response is None:
                batch_tally["no_clob_response"] += 1
                cum_tally["no_clob_response"] += 1
            else:
                classification, winner = _extract_clob_resolution(clob_response)
                batch_tally[classification] += 1
                cum_tally[classification] += 1

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
                        print(f"[TRANCHE2-WRITE] *** sqlite3 exception on write for {market_id}: {e} ***")
                        if "resolved cannot transition" in str(e):
                            aborted = True
                            abort_reason = f"ABORT CONDITION (trigger): trg_resolved_no_unresolve fired on {market_id}: {e}"
                            break
                        raise

                    conn.commit()  # unconditional -- see module docstring

                    if result.accepted:
                        cum_accepted += 1
                        if result.reason == "written":
                            resolved_ids.add(market_id)
                    else:
                        cum_rejected += 1
                    cum_reasons[result.reason] = cum_reasons.get(result.reason, 0) + 1

            batch_fresh_attempted += 1
            cumulative_processed += 1
            last_market_id = market_id
            call_elapsed = time.time() - call_start
            batch_call_times.append(call_elapsed)

            time.sleep(SLEEP)

        batch_elapsed = time.time() - batch_t0
        cumulative_elapsed += batch_elapsed

        if aborted:
            print(f"[TRANCHE2-WRITE] Aborted mid-batch {batch_num + 1}: {abort_reason}")
            break

        # --- Post-batch checks ---
        batch_determinate = batch_tally["resolved"] + batch_tally["open"]
        batch_indet = batch_tally["indeterminate"] + batch_tally["no_clob_response"]
        batch_classifiable = batch_determinate + batch_indet
        batch_indet_rate = (batch_indet / batch_classifiable) if batch_classifiable else 0.0

        cum_determinate = cum_tally["resolved"] + cum_tally["open"]
        cum_indet = cum_tally["indeterminate"] + cum_tally["no_clob_response"]
        cum_classifiable = cum_determinate + cum_indet
        cum_indet_rate = (cum_indet / cum_classifiable) if cum_classifiable else 0.0

        non_accepted_reasons = {r: c for r, c in cum_reasons.items() if r not in ACCEPTED_REASONS}
        non_accepted_rate = (sum(non_accepted_reasons.values()) / cum_accepted) if cum_accepted else 0.0

        avg_pace = (sum(batch_call_times) / len(batch_call_times)) if batch_call_times else 0.0
        batch_pace_history.append(avg_pace)

        cur_atomicity = atomicity_count(conn)

        batches_completed = batch_num + 1
        per_batch_history.append({
            "batch": batches_completed,
            "fresh_attempted": batch_fresh_attempted,
            "skipped_already_resolved": batch_skipped,
            "tally": dict(batch_tally),
            "indet_rate": batch_indet_rate,
            "avg_pace_s_per_call": avg_pace,
            "elapsed_s": batch_elapsed,
            "last_market_id": last_market_id,
        })

        print(f"[TRANCHE2-WRITE] Batch {batches_completed}/{n_batches} done: "
              f"fresh={batch_fresh_attempted} skipped={batch_skipped} tally={batch_tally} "
              f"batch_indet_rate={batch_indet_rate:.1%} "
              f"[{'EVALUATED' if batch_classifiable >= BATCH_FLOOR else 'BELOW FLOOR'}] "
              f"cum_indet_rate={cum_indet_rate:.1%} "
              f"[{'EVALUATED' if cum_classifiable >= CUMULATIVE_FLOOR else 'BELOW FLOOR'}] "
              f"avg_pace={avg_pace:.3f}s/call atomicity={cur_atomicity}")

        # Persist checkpoint -- atomic write-to-temp-then-rename.
        write_checkpoint({
            "seed": sample_doc["seed"],
            "sample_size": len(sample),
            "batches_completed": batches_completed,
            "cumulative_processed": cumulative_processed,
            "resolved_market_ids": sorted(resolved_ids),
            "cumulative_tally": cum_tally,
            "cumulative_accepted": cum_accepted,
            "cumulative_rejected": cum_rejected,
            "cumulative_reasons": cum_reasons,
            "per_batch_history": per_batch_history,
            "elapsed_seconds_cumulative": cumulative_elapsed,
            "last_updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(f"[TRANCHE2-WRITE] Checkpoint written: {CHECKPOINT_PATH}")

        if cur_atomicity != 0:
            aborted = True
            abort_reason = f"ABORT CONDITION (atomicity): check_resolution_write_atomicity = {cur_atomicity} after batch {batches_completed}"
            break
        if cum_classifiable >= CUMULATIVE_FLOOR and cum_indet_rate > 0.20:
            aborted = True
            abort_reason = f"ABORT CONDITION 3 (cumulative >20%, floor met): cum_indet_rate={cum_indet_rate:.1%} after batch {batches_completed}"
            break
        if batch_classifiable >= BATCH_FLOOR and batch_indet_rate > 0.10:
            aborted = True
            abort_reason = f"ABORT CONDITION 2 (batch >10%, floor met): batch_indet_rate={batch_indet_rate:.1%} in batch {batches_completed}"
            break
        if non_accepted_rate > 0.01:
            aborted = True
            abort_reason = f"ABORT CONDITION 5: non-accepted reason rate={non_accepted_rate:.1%} after batch {batches_completed}: {non_accepted_reasons}"
            break
        if len(batch_pace_history) >= 2 and all(p > 1.0 for p in batch_pace_history[-2:]):
            aborted = True
            abort_reason = f"ABORT CONDITION 7 (pacing): last 2 batches averaged >1.0s/call: {batch_pace_history[-2:]}"
            break

    conn.close()

    print(f"\n[TRANCHE2-WRITE] {'ABORTED' if aborted else 'COMPLETE' if batches_completed >= n_batches else 'STOPPED (incomplete)'}")
    if aborted:
        print(f"[TRANCHE2-WRITE] Abort reason: {abort_reason}")
    print(f"[TRANCHE2-WRITE] Batches completed: {batches_completed}/{n_batches}")
    print(f"[TRANCHE2-WRITE] Cumulative processed: {cumulative_processed}/5000")
    print(f"[TRANCHE2-WRITE] Cumulative tally: {cum_tally}")
    print(f"[TRANCHE2-WRITE] Cumulative accepted={cum_accepted} rejected={cum_rejected}")
    print(f"[TRANCHE2-WRITE] Cumulative reasons: {cum_reasons}")
    print(f"[TRANCHE2-WRITE] Cumulative elapsed: {cumulative_elapsed:.1f}s")

    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
