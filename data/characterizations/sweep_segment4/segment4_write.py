#!/usr/bin/env python3
"""
SEGMENT 4 -- THE WRITE (2026-08-21-discovery-gap-closure-prereg.md,
23630ee as amended, SS C segmented execution model + combo/parlay
carve-out).

Reads the FIXED, pre-materialized segment4 list (segment4_list.json,
66,500 markets) -- a live, current-state SS C query, combo/parlay
carve-out applied directly in SQL, excluding every market_id already
walked by tranche 2 (5,000), segment 1's first 6,000 walked entries,
segment 2's full 60,500, and segment 3's full 93,000 (union 164,500). See
segment4_materialize.py for the exact query.

THIS DRIVER IS IDENTICAL IN STRUCTURE TO segment3_write.py, WITH EXACTLY
ONE FUNCTIONAL CHANGE beyond path/segment-number constants:
CONFIRM-BEFORE-ABORT on the check_resolution_write_atomicity abort
condition (prereg §C condition 5), per
brain/decisions/2026-08-25-sweep-segment4.md.

Segment 3's post-run status check
(brain/decisions/2026-08-25-post-segment3-status.md, Part D.12) observed
check_resolution_write_atomicity read 0 -> 5 -> 0 across successive
queries, with a direct SELECT for the offending rows returning nothing --
a transient WAL-mode race against the live monitoring service's own
writes (a market caught between two non-atomic UPDATE statements),
self-healed within moments, not a real violation. As originally written,
condition 5 hard-aborts on ANY non-zero reading with no way to
distinguish that from a genuine, persistent atomicity break -- the exact
same defect class as tranche 1's original abort condition 2/3, which had
no n=100 floor and fired on ordinary sampling noise (see the prereg's own
2026-08-22 amendment, 4436119). A 10+ hour run should not die on a
race window that resolves itself before the next batch would even start.

Fix: on a non-zero reading, wait CONFIRM_DELAY (5s -- see rationale below)
and re-query once. Abort only if the SECOND reading is ALSO non-zero
(persisted, not transient). A single transient non-zero reading is logged
to the checkpoint's new `atomicity_transient_events` list and to stdout,
but is NOT fatal by itself.

CONFIRM_DELAY = 5s rationale: segment 3's own per-call latency (CLOB fetch
+ mark_market_resolved + commit) measured 0.140-0.225s throughout its
entire run (per-batch avg_pace_s_per_call); a single in-flight write pair
completes in well under 1s. 5s is a 20x-plus margin over that -- enough
for any single in-flight non-atomic write to finish and be visible to a
fresh connection.read, without meaningfully affecting a run measured in
hours (worst case, every one of 133 batches sees exactly one transient
reading: 133 x 5s = 665s = ~11 minutes against a ~7.75h budget with ~2h of
margin already built in).

THIS IS A STRUCTURAL CORRECTION TO §C CONDITION 5's EVALUATION LOGIC, NOT
A RELAXATION OF THE ABORT ITSELF: a persistent non-zero reading (both the
initial AND the confirming re-query non-zero) still HARD ABORTS exactly as
before. The pre-registration is NOT amended by this driver change --
brain/decisions/2026-08-25-sweep-segment4.md flags this explicitly as a
correction that should be reflected in the prereg's own §C table in a
future documentation-only amendment (same pattern as the tranche-1
n=100-floor amendment), not silently absorbed into a driver without a
paper trail.

Every other line of logic -- batching, pacing, the other abort conditions,
checkpointing, terminal-signal wiring (Fix 2), maintenance-window stop,
imports from tranche2_write.py -- is otherwise UNCHANGED from
segment3_write.py; only path constants (segment4 instead of segment3),
print prefixes, and the atomicity-check block differ.

Batch numbering: segment 4's batches (1-133) are a NEW, independent
sequence -- NOT a continuation of any prior segment's numbering.

Batches of 500, atomic checkpoint (write-to-temp-then-os.replace) after
each, to data/checkpoints/segment4_checkpoint.json. Resumable against the
fixed list via a persisted resolved_market_ids skip-list, populated
whenever a reason is in ACCEPTED_REASONS.

Abort conditions per the amended SS C, batch and cumulative tracked
separately, each with its own n=100 floor. Plus the segment-specific
maintenance-window check: stop cleanly at the next batch boundary if
within 30 minutes of the next 06:00:00 UTC daily_maintenance fire.

Uses the unmodified _get_connection, _fetch_by_clob,
_extract_clob_resolution (scripts/backfill_market_dates.py) and
mark_market_resolved (monitoring/resolution_writer.py). Unconditional
conn.commit() after every accepted write.

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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sweep_common"))

from scripts.backfill_market_dates import _get_connection, _fetch_by_clob, _extract_clob_resolution
from monitoring.resolution_writer import mark_market_resolved
from tranche2_write import ACCEPTED_REASONS, atomicity_count  # noqa: E402 -- reused, unmodified
from sweep_terminal_signal import write_terminal_marker, send_telegram_terminal  # noqa: E402

import requests

SLEEP = 0.25
BATCH_SIZE = 500
CUMULATIVE_FLOOR = 100
BATCH_FLOOR = 100
MAINTENANCE_STOP_MARGIN = timedelta(minutes=30)
ATOMICITY_CONFIRM_DELAY = 5.0  # seconds -- see module docstring for rationale

SEGMENT_LIST_PATH = Path(__file__).parent / "segment4_list.json"
CHECKPOINT_PATH = REPO_ROOT / "data" / "checkpoints" / "segment4_checkpoint.json"
TERMINAL_MARKER_PATH = REPO_ROOT / "data" / "checkpoints" / "segment4_terminal_marker.json"


def next_maintenance_fire(now: datetime) -> datetime:
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


def _emit_terminal(status, batches_completed, n_batches, cumulative_processed, cumulative_tally, reason=None):
    write_terminal_marker(
        TERMINAL_MARKER_PATH,
        status=status,
        batches_completed=batches_completed,
        n_batches=n_batches,
        cumulative_processed=cumulative_processed,
        cumulative_tally=cumulative_tally,
        reason=reason,
    )
    send_telegram_terminal(
        f"[SWEEP] segment4 {status}: {batches_completed}/{n_batches} batches, "
        f"{cumulative_processed} processed" + (f" -- {reason}" if reason else "")
    )


def main():
    with open(SEGMENT_LIST_PATH) as f:
        segment_doc = json.load(f)
    segment = segment_doc["segment"]
    print(f"[SEGMENT4-WRITE] Loaded fixed segment list: {len(segment)} markets "
          f"(combo/parlay cohort excluded in SQL at materialization time: "
          f"{segment_doc['combo_carveout_count']} excluded from a "
          f"{segment_doc['ss_c_predicate_population_raw']}-market raw SS C population)")

    conn = _get_connection()

    pre_atomicity = atomicity_count(conn)
    print(f"[SEGMENT4-WRITE] Pre-write check_resolution_write_atomicity: {pre_atomicity}")
    if pre_atomicity != 0:
        print("[SEGMENT4-WRITE] ABORT CONDITION fired BEFORE any write. Not proceeding.")
        conn.close()
        sys.exit(2)

    checkpoint = load_checkpoint()
    if checkpoint is not None:
        print(f"[SEGMENT4-WRITE] RESUMING from checkpoint: batches_completed="
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
        atomicity_transient_events = checkpoint.get("atomicity_transient_events", [])
    else:
        print("[SEGMENT4-WRITE] No checkpoint found -- starting fresh (segment 4 batch 1).")
        resolved_ids = set()
        cum_tally = {"resolved": 0, "open": 0, "indeterminate": 0, "no_clob_response": 0}
        cum_accepted = 0
        cum_rejected = 0
        cum_reasons = {}
        batches_completed = 0
        cumulative_processed = 0
        per_batch_history = []
        cumulative_elapsed = 0.0
        atomicity_transient_events = []

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    n_batches = (len(segment) + BATCH_SIZE - 1) // BATCH_SIZE
    aborted = False
    abort_reason = None
    maintenance_stopped = False
    batch_pace_history = []

    try:
        for batch_num in range(batches_completed, n_batches):
            now = datetime.now(timezone.utc)
            fire = next_maintenance_fire(now)
            if fire - now <= MAINTENANCE_STOP_MARGIN:
                print(f"[SEGMENT4-WRITE] *** MAINTENANCE-WINDOW STOP: {fire.isoformat()} is within "
                      f"{MAINTENANCE_STOP_MARGIN} of now ({now.isoformat()}). Stopping cleanly at this "
                      f"batch boundary, not starting batch {batch_num + 1}. ***")
                maintenance_stopped = True
                break

            batch_slice = segment[batch_num * BATCH_SIZE: (batch_num + 1) * BATCH_SIZE]
            print(f"\n[SEGMENT4-WRITE] === Batch {batch_num + 1}/{n_batches} "
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
                            print(f"[SEGMENT4-WRITE] *** sqlite3 exception on write for {market_id}: {e} ***")
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
                print(f"[SEGMENT4-WRITE] Aborted mid-batch {batch_num + 1}: {abort_reason}")
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

            # --- CONFIRM-BEFORE-ABORT (2026-08-25 amendment) ---
            # Prereg §C condition 5: check_resolution_write_atomicity non-zero
            # is a HARD ABORT. As originally written this could not
            # distinguish a genuine violation from a transient WAL-mode race
            # against the live monitoring service's own writes (observed
            # 0 -> 5 -> 0 across successive queries in segment 3's post-run
            # status check, self-healed, not a real violation -- see
            # brain/decisions/2026-08-25-post-segment3-status.md Part D.12).
            # Fix: on a non-zero reading, wait ATOMICITY_CONFIRM_DELAY and
            # re-query once. Abort only if the second reading is ALSO
            # non-zero. A single transient reading is logged, not fatal.
            cur_atomicity = atomicity_count(conn)
            if cur_atomicity != 0:
                print(f"[SEGMENT4-WRITE] *** check_resolution_write_atomicity non-zero ({cur_atomicity}) "
                      f"after batch {batch_num + 1}. "
                      f"Confirm-before-abort: waiting {ATOMICITY_CONFIRM_DELAY}s and re-querying "
                      f"before treating as fatal. ***")
                time.sleep(ATOMICITY_CONFIRM_DELAY)
                confirm_atomicity = atomicity_count(conn)
                if confirm_atomicity != 0:
                    aborted = True
                    abort_reason = (
                        f"ABORT CONDITION (atomicity, CONFIRMED PERSISTENT): "
                        f"check_resolution_write_atomicity = {cur_atomicity} then {confirm_atomicity} "
                        f"after batch {batch_num + 1} (non-zero on both the initial reading and the "
                        f"{ATOMICITY_CONFIRM_DELAY}s confirmation re-query)"
                    )
                else:
                    print(f"[SEGMENT4-WRITE] Atomicity re-check returned 0 -- TRANSIENT, not fatal. "
                          f"Logging and continuing.")
                    atomicity_transient_events.append({
                        "batch": batch_num + 1,
                        "first_reading": cur_atomicity,
                        "confirm_reading": confirm_atomicity,
                        "confirm_delay_s": ATOMICITY_CONFIRM_DELAY,
                        "detected_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })
                cur_atomicity = confirm_atomicity  # what gets logged in per-batch history below

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

            print(f"[SEGMENT4-WRITE] Batch {batches_completed}/{n_batches} done: "
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
                "atomicity_transient_events": atomicity_transient_events,
                "elapsed_seconds_cumulative": cumulative_elapsed,
                "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            print(f"[SEGMENT4-WRITE] Checkpoint written: {CHECKPOINT_PATH}")

            if aborted:
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
    except Exception as exc:
        conn.close()
        _emit_terminal(
            "EXCEPTION", batches_completed, n_batches, cumulative_processed, cum_tally,
            reason=f"{type(exc).__name__}: {exc}",
        )
        raise

    conn.close()

    status = "ABORTED" if aborted else ("MAINTENANCE-STOPPED" if maintenance_stopped else
                                         ("COMPLETE" if batches_completed >= n_batches else "STOPPED (incomplete)"))
    _emit_terminal(status, batches_completed, n_batches, cumulative_processed, cum_tally, reason=abort_reason)

    print(f"\n[SEGMENT4-WRITE] {status}")
    if aborted:
        print(f"[SEGMENT4-WRITE] Abort reason: {abort_reason}")
    print(f"[SEGMENT4-WRITE] Batches completed: {batches_completed}/{n_batches}")
    print(f"[SEGMENT4-WRITE] Cumulative processed: {cumulative_processed}/{len(segment)}")
    print(f"[SEGMENT4-WRITE] Cumulative tally: {cum_tally}")
    print(f"[SEGMENT4-WRITE] Cumulative accepted={cum_accepted} rejected={cum_rejected}")
    print(f"[SEGMENT4-WRITE] Cumulative reasons: {cum_reasons}")
    print(f"[SEGMENT4-WRITE] Atomicity transient events: {len(atomicity_transient_events)}")
    print(f"[SEGMENT4-WRITE] Cumulative elapsed: {cumulative_elapsed:.1f}s")

    sys.exit(1 if aborted else 0)


if __name__ == "__main__":
    main()
