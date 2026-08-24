#!/usr/bin/env python3
"""
SEGMENT 3 of the full discovery-gap sweep -- materialize the exact
market_id list, ONCE, before the write.

2026-08-21-discovery-gap-closure-prereg.md (23630ee, as amended) SS C:
segmented execution model, ORDER BY market_id for deterministic batch
boundaries. Same rationale as segment1_materialize.py: market_id is not
correlated with insertion order, so a live re-query after a restart could
admit newly-inserted markets or drop others near the LIMIT boundary --
materializing the exact list upfront removes that ambiguity.

Population: SS C's own predicate, with the combo/parlay carve-out applied
DIRECTLY IN SQL this time (LENGTH(market_id)=64 AND SUBSTR(market_id,37)
= 28 zeros), not as a post-filter on a fixed prior list the way segment 2
did it -- segment 3 draws from the live, current-state population, not a
segment-1-list-derived tail, so there is no upstream list to post-filter.

EXCLUDING everything already processed by this arc to date, via explicit
market_id sets (not a live re-derivation, since some of those runs used
predicates now stale against the current resolved-flag state):
  - tranche2_sample_5000.json: all 5,000 sampled ids
  - segment1_list.json[:6000]: the first 6,000 entries segment 1 actually
    walked (batches 1-12 before it paused on the combo/parlay finding) --
    NOT the full 103,000-entry list, since the un-walked tail (indices
    6000-102999) still contains real, un-attempted candidates that
    segment 2 only partially consumed (60,500 of the tail's 81,792
    combo-filtered candidates -- 21,292 remain un-walked and must stay
    eligible here).
  - segment2_list.json: all 60,500 entries -- segment 2 ran to full
    completion (121/121 batches), so every one of these was walked.
  - Tranche 1 (203 resolved, ~123 left open/indeterminate/no_clob_response
    of 326 walked) is NOT list-excluded here: tranche 1 queried live
    (category-scoped, joined against `trades`) rather than materializing
    a fixed list, so no exact id enumeration survives to exclude by. The
    ~123 still-unresolved tranche-1 markets remain live SS-C candidates
    and may reappear in this segment's list. This is accepted, not
    silently ignored: mark_market_resolved()'s own resolved=0 guard makes
    a re-attempt idempotent and harmless (at most a few dozen redundant
    CLOB calls out of 93,000), not a correctness risk. Named explicitly
    per the task's own instruction to state what could not be done as
    specified rather than paper over it.

Read-only: opens the DB via a mode=ro URI connection. Writes nothing to
the DB. Writes only the segment-list JSON artifact.
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"
TRANCHE2_SAMPLE_PATH = Path(__file__).resolve().parents[1] / "tranche2_execution" / "tranche2_sample_5000.json"
SEGMENT1_LIST_PATH = Path(__file__).resolve().parents[1] / "sweep_segment1" / "segment1_list.json"
SEGMENT2_LIST_PATH = Path(__file__).resolve().parents[1] / "sweep_segment2" / "segment2_list.json"

SEGMENT_SIZE = 93000

COMBO_PARLAY_PREDICATE = (
    "LENGTH(market_id) = 64 AND SUBSTR(market_id, 37) = '0000000000000000000000000000'"
)


def main():
    with open(TRANCHE2_SAMPLE_PATH) as f:
        tranche2_sample = json.load(f)
    tranche2_ids = [e["market_id"] for e in tranche2_sample["sample"]]

    with open(SEGMENT1_LIST_PATH) as f:
        segment1_doc = json.load(f)
    segment1_walked_ids = [e["market_id"] for e in segment1_doc["segment"][:6000]]

    with open(SEGMENT2_LIST_PATH) as f:
        segment2_doc = json.load(f)
    segment2_ids = [e["market_id"] for e in segment2_doc["segment"]]

    exclude_ids = sorted(set(tranche2_ids) | set(segment1_walked_ids) | set(segment2_ids))
    print(f"[SEGMENT3-MATERIALIZE] Excluding {len(exclude_ids)} already-processed ids "
          f"(tranche2={len(tranche2_ids)}, segment1_walked={len(segment1_walked_ids)}, "
          f"segment2={len(segment2_ids)}, union={len(exclude_ids)})")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" for _ in exclude_ids)
    query = f"""
        SELECT market_id, condition_id
        FROM markets
        WHERE (resolved = 0 OR resolved IS NULL)
          AND (end_date IS NULL OR resolution_date IS NULL)
          AND NOT ({COMBO_PARLAY_PREDICATE})
          AND market_id NOT IN ({placeholders})
        ORDER BY market_id ASC
        LIMIT ?
    """
    rows = conn.execute(query, exclude_ids + [SEGMENT_SIZE]).fetchall()
    print(f"[SEGMENT3-MATERIALIZE] Drew {len(rows)} markets (target {SEGMENT_SIZE})")

    ss_c_raw = conn.execute("""
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
    """).fetchone()[0]
    combo_count = conn.execute(f"""
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
          AND ({COMBO_PARLAY_PREDICATE})
    """).fetchone()[0]
    post_carveout = ss_c_raw - combo_count
    final_pop = conn.execute(f"""
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
          AND NOT ({COMBO_PARLAY_PREDICATE})
          AND market_id NOT IN ({placeholders})
    """, exclude_ids).fetchone()[0]

    print(f"[SEGMENT3-MATERIALIZE] SS C predicate population (raw, unexcluded): {ss_c_raw}")
    print(f"[SEGMENT3-MATERIALIZE] combo/parlay cohort within raw population: {combo_count}")
    print(f"[SEGMENT3-MATERIALIZE] post-carveout population: {post_carveout}")
    print(f"[SEGMENT3-MATERIALIZE] final candidate population (post-carveout, post-exclusion): {final_pop}")

    segment_list = [{"market_id": r["market_id"], "condition_id": r["condition_id"]} for r in rows]

    out_path = Path(__file__).parent / "segment3_list.json"
    with open(out_path, "w") as f:
        json.dump({
            "segment_size_target": SEGMENT_SIZE,
            "segment_size_actual": len(segment_list),
            "ss_c_predicate_population_raw": ss_c_raw,
            "combo_carveout_count": combo_count,
            "post_carveout_population": post_carveout,
            "final_candidate_population": final_pop,
            "excluded_ids_count": len(exclude_ids),
            "order_by": "market_id ASC",
            "query": query.strip(),
            "segment": segment_list,
        }, f, indent=2)
    print(f"[SEGMENT3-MATERIALIZE] Wrote {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
