#!/usr/bin/env python3
"""
SEGMENT 4 of the full discovery-gap sweep -- materialize the exact
market_id list, ONCE, before the write.

2026-08-21-discovery-gap-closure-prereg.md (23630ee, as amended) SS C:
segmented execution model, ORDER BY market_id for deterministic batch
boundaries -- same rationale as segment3_materialize.py: market_id is not
correlated with insertion order, so a live re-query after a restart could
admit newly-inserted markets or drop others near the LIMIT boundary --
materializing the exact list upfront removes that ambiguity.

Population: SS C's own predicate, combo/parlay carve-out applied directly
in SQL (LENGTH(market_id)=64 AND SUBSTR(market_id,37) = 28 zeros), drawn
live from the current-state population -- same approach as segment 3.

EXCLUDING everything already processed by this arc to date, via explicit
market_id sets (not a live re-derivation):
  - tranche2_sample_5000.json: all 5,000 sampled ids
  - segment1_list.json[:6000]: the 6,000 segment 1 actually walked
  - segment2_list.json: all 60,500 entries (segment 2 ran to full
    completion)
  - segment3_list.json: all 93,000 entries (segment 3 ran to full
    completion, 186/186 batches, per
    brain/decisions/2026-08-25-post-segment3-status.md)
  Union: 164,500 ids (verified this session: 5000+6000+60500+93000, zero
  overlap among the four sets by construction -- each prior segment's own
  materialize step excluded everything before it the same way).

  Tranche 1 (~123 of 326 walked markets still open/indeterminate/
  no_clob_response) remains NOT list-excluded, same accepted caveat as
  segment 2 and segment 3: no fixed id enumeration survives from tranche
  1's live, category-scoped query to exclude by. mark_market_resolved()'s
  resolved=0 guard makes any re-attempt idempotent and harmless.

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
SEGMENT3_LIST_PATH = Path(__file__).resolve().parents[1] / "sweep_segment3" / "segment3_list.json"

# Sized from live runway arithmetic this session (see the deliverable),
# NOT inherited from any prior segment's size. 133 batches x 500 = 66,500,
# floored from a 27,987s write budget (35,187s runway to the 2026-08-26
# 06:00:00Z maintenance fire, minus a 7,200s target margin) at segment 3's
# measured 0.419597s/market rate.
SEGMENT_SIZE = 66500

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

    with open(SEGMENT3_LIST_PATH) as f:
        segment3_doc = json.load(f)
    segment3_ids = [e["market_id"] for e in segment3_doc["segment"]]

    exclude_ids = sorted(set(tranche2_ids) | set(segment1_walked_ids) | set(segment2_ids) | set(segment3_ids))
    print(f"[SEGMENT4-MATERIALIZE] Excluding {len(exclude_ids)} already-processed ids "
          f"(tranche2={len(tranche2_ids)}, segment1_walked={len(segment1_walked_ids)}, "
          f"segment2={len(segment2_ids)}, segment3={len(segment3_ids)}, union={len(exclude_ids)})")

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
    print(f"[SEGMENT4-MATERIALIZE] Drew {len(rows)} markets (target {SEGMENT_SIZE})")

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

    print(f"[SEGMENT4-MATERIALIZE] SS C predicate population (raw, unexcluded): {ss_c_raw}")
    print(f"[SEGMENT4-MATERIALIZE] combo/parlay cohort within raw population: {combo_count}")
    print(f"[SEGMENT4-MATERIALIZE] post-carveout population: {post_carveout}")
    print(f"[SEGMENT4-MATERIALIZE] final candidate population (post-carveout, post-exclusion): {final_pop}")

    segment_list = [{"market_id": r["market_id"], "condition_id": r["condition_id"]} for r in rows]

    out_path = Path(__file__).parent / "segment4_list.json"
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
    print(f"[SEGMENT4-MATERIALIZE] Wrote {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
