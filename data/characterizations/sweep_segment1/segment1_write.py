#!/usr/bin/env python3
"""
SEGMENT 1 -- THE WRITE (2026-08-21-discovery-gap-closure-prereg.md,
2e1bb34 as amended, SS C segmented execution model).

Reads the FIXED, pre-materialized segment list (segment1_list.json,
103,000 markets, SS C predicate minus tranche 2's 5,000-market sample,
ORDER BY market_id ASC) -- never re-queries live, for the same
resume-drift reasons tranche 2 fixed its sample upfront.

Imports ACCEPTED_REASONS and atomicity_count directly from
tranche2_execution/tranche2_write.py (first-repo 6061a5a, the fixed
driver) -- reused, not redefined, so this segment runs under the exact
same corrected four-item whitelist without copying it and risking drift.
tranche2_write.py itself is not modified.

Batches of 500, atomic checkpoint (write-to-temp-then-os.replace) after
each, to data/checkpoints/segment1_checkpoint.json. Resumable against the
fixed list via a persisted resolved_market_ids skip-list (same defect-2
fix as tranche 2 -- populated whenever a reason is in ACCEPTED_REASONS,
not just on a fresh "written").

Abort conditions per the amended SS C, batch and cumulative tracked
separately, each with its own n=100 floor -- same logic as
tranche2_write.py's batch-4-onward behavior. ADDITIONALLY, specific to
the segmented model: after every batch, if the current UTC time is within
30 minutes of the next 06:00:00 UTC daily_maintenance fire, stop cleanly
at that batch boundary rather than starting another batch.

Uses the unmodified _get_connection, _fetch_by_clob,
_extract_clob_resolution (scripts/backfill_market_dates.py) and
mark_market_resolved (monitoring/resolution_writer.py). Unconditional
conn.commit() after every accepted write, same defensive stance as every
driver in this arc.

Pacing: 0.25s/call.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tranche2_execution"))

from scripts.backfill_market_dates import _get_connection, _fetch_by_clob, _extract_clob_resolution
from monitoring.resolution_writer import mark_market_resolved
from tranche2_write import ACCEPTED_REASONS, atomicity_count  # noqa: E402 -- reused, unmodified

import requests

SLEEP = 0.25
BATCH_SIZE = 500
CUMULATIVE_FLOOR = 100
BATCH_FLOOR = 100
MAINTENANCE_STOP_MARGIN = timedelta(minutes=30)

SEGMENT_LIST_PATH = Path(__file__).parent / "segment1_list.json"
CHECKPOINT_PATH = REPO_ROOT / "data" / "checkpoints" / "segment1_checkpoint.json"


def next_maintenance_fire(now: datetime) -> datetime:
    """Next 06:00:00 UTC, today if not yet passed, else tomorrow."""
    candidate = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


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
    os.replace(tmp_path, CHECKPOINT_PATH)


def main():
    with open(SEGMENT_LIST_PATH) as f:
        segment_doc = json.load(f)
    segment = segment_doc["segment"]
    print(f"[SEGMENT1-WRITE] Loaded fixed segment list: {len(segment)} markets")

    conn = _get_connection()

    pre_atomicity = atomicity_count(conn)
    print(f"[SEGMENT1-WRITE] Pre-write check_resolution_write_atomicity: {pre_atomicity}")
    if pre_atomicity != 0:
        print("[SEGMENT1-WRITE] ABORT CONDITION fired BEFORE any write. Not proceeding.")
        conn.close()
        sys.exit(2)

    checkpoint = load_checkpoint()
    if checkpoint is not None:
        print(f"[SEGMENT1-WRITE] RESUMING from checkpoint: batches_completed="
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
        print("[SEGMENT1-WRITE] No checkpoint found -- starting fresh.")
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

    n_batches = (len(segment) + BATCH_SIZE - 1) // BATCH_SIZE
    aborted = False
    abort_reason = None
    maintenance_stopped = False
    batch_pace_history = []

    for batch_num in range(batches_completed, n_batches):
        now = datetime.now(timezone.utc)
        fire = next_maintenance_fire(now)
        if fire - now <= MAINTENANCE_STOP_MARGIN:
            print(f"[SEGMENT1-WRITE] *** MAINTENANCE-WINDOW STOP: {fire.isoformat()} is within "
                  f"{MAINTENANCE_STOP_MARGIN} of now ({now.isoformat()}). Stopping cleanly at this "
                  f"batch boundary, not starting batch {batch_num + 1}. ***")
            maintenance_stopped = True
            break

        batch_slice = segment[batch_num * BATCH_SIZE: (batch_num + 1) * BATCH_SIZE]
        print(f"\n[SEGMENT1-WRITE] === Batch {batch_num + 1}/{n_batches} "
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
                        print(f"[SEGMENT1-WRITE] *** sqlite3 exception on write for {market_id}: {e} ***")
                        if "resolved cannot transition" in str(e):
                            aborted = True
                            abort_reason = f"ABORT CONDITION (trigger): trg_resolved_no_unresolve fired on {market_id}: {e}"
                            break
                        raise

                    conn.commit()

                    if result.accepted:
                        cum_accepted += 1
                    else:
                        cum_rejected += 1
                    if result.reason in ACCEPTED_REASONS:
                        resolved_ids.add(market_id)
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
            print(f"[SEGMENT1-WRITE] Aborted mid-batch {batch_num + 1}: {abort_reason}")
            break

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

        print(f"[SEGMENT1-WRITE] Batch {batches_completed}/{n_batches} done: "
              f"fresh={batch_fresh_attempted} skipped={batch_skipped} tally={batch_tally} "
              f"batch_indet_rate={batch_indet_rate:.1%} "
              f"[{'EVALUATED' if batch_classifiable >= BATCH_FLOOR else 'BELOW FLOOR'}] "
              f"cum_indet_rate={cum_indet_rate:.1%} "
              f"[{'EVALUATED' if cum_classifiable >= CUMULATIVE_FLOOR else 'BELOW FLOOR'}] "
              f"avg_pace={avg_pace:.3f}s/call atomicity={cur_atomicity}")

        write_checkpoint({
            "segment_size": len(segment),
            "batches_completed": batches_completed,
            "cumulative_processed": cumulative_processed,
            "resolved_market_ids": sorted(resolved_ids),
            "cumulative_tally": cum_tally,
            "cumulative_accepted": cum_accepted,
            "cumulative_rejected": cum_rejected,
            "cumulative_reasons": cum_reasons,
            "per_batch_history": per_batch_history,
            "elapsed_seconds_cumulative": cumulative_elapsed,
            "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        print(f"[SEGMENT1-WRITE] Checkpoint written: {CHECKPOINT_PATH}")

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

    status = "ABORTED" if aborted else ("MAINTENANCE-STOPPED" if maintenance_stopped else
                                         ("COMPLETE" if batches_completed >= n_batches else "STOPPED (incomplete)"))
    print(f"\n[SEGMENT1-WRITE] {status}")
    if aborted:
        print(f"[SEGMENT1-WRITE] Abort reason: {abort_reason}")
    print(f"[SEGMENT1-WRITE] Batches completed: {batches_completed}/{n_batches}")
    print(f"[SEGMENT1-WRITE] Cumulative processed: {cumulative_processed}/{len(segment)}")
    print(f"[SEGMENT1-WRITE] Cumulative tally: {cum_tally}")
    print(f"[SEGMENT1-WRITE] Cumulative accepted={cum_accepted} rejected={cum_rejected}")
    print(f"[SEGMENT1-WRITE] Cumulative reasons: {cum_reasons}")
    print(f"[SEGMENT1-WRITE] Cumulative elapsed: {cumulative_elapsed:.1f}s")

    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
