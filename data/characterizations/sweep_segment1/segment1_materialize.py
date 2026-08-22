#!/usr/bin/env python3
"""
SEGMENT 1 of the full discovery-gap sweep -- materialize the exact
market_id list, ONCE, before the write.

2026-08-21-discovery-gap-closure-prereg.md (2e1bb34, as amended) SS C:
segmented execution model, ORDER BY market_id for deterministic batch
boundaries. Unlike tranche 2 (a seeded random SAMPLE of the population),
segment 1 WALKS the population in scan order (market_id ascending) --
but the same seed/resume-drift reasoning that led tranche 2 to
materialize its sample upfront (2026-08-22-tranche2-execution.md
pre-flight question 2) applies here too: market_id is not correlated
with insertion order (market_id values are opaque hex condition
identifiers), so a live re-query after a restart could admit newly-
inserted markets or drop others near the LIMIT boundary, shifting which
markets are "in" segment 1 between invocations. Materializing the exact
list upfront removes that ambiguity, at negligible cost (one query, one
committed JSON artifact), consistent with this arc's own established
convention.

Population: SS C's own predicate, EXCLUDING the 5,000 tranche-2 sample
market_ids (already processed this arc; re-attempting them here would
just re-derive results already known, not exercise new candidates).
ORDER BY market_id ASC, LIMIT 103000 (segment size derived from the
maintenance-window runway at write time, see the deliverable).

Read-only: opens the DB via a mode=ro URI connection. Writes nothing to
the DB. Writes only the segment-list JSON artifact.
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"
TRANCHE2_SAMPLE_PATH = Path(__file__).resolve().parents[1] / "tranche2_execution" / "tranche2_sample_5000.json"

SEGMENT_SIZE = 103000


def main():
    with open(TRANCHE2_SAMPLE_PATH) as f:
        tranche2_sample = json.load(f)
    exclude_ids = [e["market_id"] for e in tranche2_sample["sample"]]
    print(f"[SEGMENT1-MATERIALIZE] Excluding {len(exclude_ids)} tranche-2 sample market_ids")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" for _ in exclude_ids)
    query = f"""
        SELECT market_id, condition_id
        FROM markets
        WHERE (resolved = 0 OR resolved IS NULL)
          AND (end_date IS NULL OR resolution_date IS NULL)
          AND market_id NOT IN ({placeholders})
        ORDER BY market_id ASC
        LIMIT ?
    """
    rows = conn.execute(query, exclude_ids + [SEGMENT_SIZE]).fetchall()
    print(f"[SEGMENT1-MATERIALIZE] Drew {len(rows)} markets (target {SEGMENT_SIZE})")

    # Also report the full excluded-population count for the record.
    full_pop = conn.execute("""
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
    """).fetchone()[0]
    still_candidate_from_t2 = conn.execute(f"""
        SELECT COUNT(*) FROM markets
        WHERE market_id IN ({placeholders})
          AND (resolved = 0 OR resolved IS NULL) AND (end_date IS NULL OR resolution_date IS NULL)
    """, exclude_ids).fetchone()[0]
    print(f"[SEGMENT1-MATERIALIZE] SS C predicate population (unexcluded): {full_pop}")
    print(f"[SEGMENT1-MATERIALIZE] Of the excluded tranche-2 sample, still-candidate: {still_candidate_from_t2}")

    segment_list = [{"market_id": r["market_id"], "condition_id": r["condition_id"]} for r in rows]

    out_path = Path(__file__).parent / "segment1_list.json"
    with open(out_path, "w") as f:
        json.dump({
            "segment_size_target": SEGMENT_SIZE,
            "segment_size_actual": len(segment_list),
            "ss_c_predicate_population_unexcluded": full_pop,
            "tranche2_sample_still_candidate_excluded": still_candidate_from_t2,
            "order_by": "market_id ASC",
            "query": query.strip(),
            "segment": segment_list,
        }, f, indent=2)
    print(f"[SEGMENT1-MATERIALIZE] Wrote {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
