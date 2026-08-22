#!/usr/bin/env python3
"""
TRANCHE 2 -- materialize the fixed 5,000-market sample list, ONCE, before
any write (2026-08-21-discovery-gap-closure-prereg.md, 7614ed7, SS C
tranche 2).

Pre-flight question 2 resolved this session: SS C's resumability argument
(candidate set shrinks on success, so a restart re-derives and continues)
holds for the full sweep but NOT for a seeded sample -- after a kill, the
live candidate population is smaller, so re-deriving with the same seed
draws a DIFFERENT 5,000-row sample, and a kill-and-resume test against a
re-derived sample would validate a mechanism that does not behave as
claimed. This script draws the sample ONCE and persists the exact
market_id list as a durable, committed artifact; the driver
(tranche2_write.py) reads this fixed list and never re-samples.

Pre-flight question 1 resolved this session: SS C's OWN predicate is used
for the candidate population (the same one used throughout SS C's Pacing
and Batching sections: `(resolved = 0 OR resolved IS NULL) AND (end_date
IS NULL OR resolution_date IS NULL)`) -- NOT backfill_market_dates.py's
own literal query, which lacks the resolved filter. This means the
untagged-legacy-improvement branch remains structurally unreachable in
this sample, same as tranche 1 -- see the deliverable for the full
reasoning and where that branch's first production exercise will actually
happen instead.

Seed: random.seed(20260821), per SS C's own convention (matching this
project's fixed, documented seed for any sampling step). Population
ordered deterministically (ORDER BY market_id) before sampling, so the
draw is reproducible from this script alone if ever re-run against an
unchanged population.

Read-only: opens the DB via a mode=ro URI connection. Writes nothing to
the DB. Writes only the sample-list JSON artifact.
"""
import json
import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "polymarket_tracker.db"

CANDIDATE_QUERY = """
    SELECT market_id, condition_id
    FROM markets
    WHERE (resolved = 0 OR resolved IS NULL)
      AND (end_date IS NULL OR resolution_date IS NULL)
    ORDER BY market_id
"""

SAMPLE_SIZE = 5000
SEED = 20260821


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(CANDIDATE_QUERY).fetchall()
    population_n = len(rows)
    print(f"[TRANCHE2-SAMPLE] Candidate population (SS C predicate), live: {population_n}")

    random.seed(SEED)
    sample = random.sample(rows, SAMPLE_SIZE)
    print(f"[TRANCHE2-SAMPLE] Drew {len(sample)} markets, seed={SEED}")

    sample_list = [{"market_id": r["market_id"], "condition_id": r["condition_id"]} for r in sample]

    out_path = Path(__file__).parent / "tranche2_sample_5000.json"
    with open(out_path, "w") as f:
        json.dump({
            "seed": SEED,
            "population_n_at_draw_time": population_n,
            "sample_size": len(sample_list),
            "candidate_query": CANDIDATE_QUERY.strip(),
            "sample": sample_list,
        }, f, indent=2)
    print(f"[TRANCHE2-SAMPLE] Wrote {out_path}")
    conn.close()


if __name__ == "__main__":
    main()
