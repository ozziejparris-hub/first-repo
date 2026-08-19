#!/usr/bin/env python3
"""
Live-DB inconsistency counts for the market-resolution write cluster
(markets.resolved / winning_outcome / resolution_date), characterized in
brain/decisions/2026-08-19-market-resolution-write-cluster.md.

Reports the four observable-consequence states named in that doc's Q4:
  1. resolved=1 with winning_outcome NULL/empty
  2. winning_outcome set (non-null/non-empty) with resolved=0
  3. resolution_date set with resolved=0
  4. resolved=1 with resolution_date NULL

Also breaks down state 1 by whether the affected markets carry the
__RESOLVED_NO_WINNER__-style signal (no-winner resolutions are a
legitimate, documented case in this cluster -- backfill_o16_tier1/tier2 --
though those write NULL winning_outcome directly rather than a sentinel
string in this schema, so state 1's count is NOT purely a defect count;
distinguishing the two is out of scope for this read-only census and is
flagged rather than attempted).

Read-only. Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

QUERIES = {
    "resolved_1_winning_outcome_null_or_empty": """
        SELECT COUNT(*) FROM markets
        WHERE resolved = 1 AND (winning_outcome IS NULL OR winning_outcome = '')
    """,
    "winning_outcome_set_resolved_0": """
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL)
          AND winning_outcome IS NOT NULL AND winning_outcome != ''
    """,
    "resolution_date_set_resolved_0": """
        SELECT COUNT(*) FROM markets
        WHERE (resolved = 0 OR resolved IS NULL)
          AND resolution_date IS NOT NULL
    """,
    "resolved_1_resolution_date_null": """
        SELECT COUNT(*) FROM markets
        WHERE resolved = 1 AND resolution_date IS NULL
    """,
}

BREAKDOWN_QUERIES = {
    "total_markets": "SELECT COUNT(*) FROM markets",
    "total_resolved_1": "SELECT COUNT(*) FROM markets WHERE resolved = 1",
    "total_resolved_0_or_null": "SELECT COUNT(*) FROM markets WHERE (resolved = 0 OR resolved IS NULL)",
    "resolved_1_geo_elec_winning_outcome_null": """
        SELECT COUNT(*) FROM markets
        WHERE resolved = 1 AND (winning_outcome IS NULL OR winning_outcome = '')
          AND category IN ('Geopolitics', 'Elections')
    """,
    "resolved_1_winning_outcome_null_by_data_source": None,  # filled programmatically
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    counts = {k: conn.execute(q).fetchone()[0] for k, q in QUERIES.items()}
    breakdown = {k: conn.execute(q).fetchone()[0] for k, q in BREAKDOWN_QUERIES.items() if q}

    by_source = conn.execute("""
        SELECT COALESCE(data_source, '(null)'), COUNT(*) FROM markets
        WHERE resolved = 1 AND (winning_outcome IS NULL OR winning_outcome = '')
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    breakdown["resolved_1_winning_outcome_null_by_data_source"] = dict(by_source)

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "counts": counts,
        "context_breakdown": breakdown,
        "note": "resolved_1_winning_outcome_null_or_empty is not purely a defect count -- "
                "some markets legitimately resolve with no winner (voided/all-zero-price "
                "markets); this schema has no distinct sentinel for that case, so a true "
                "defect vs. legitimate-no-winner split is not derivable from this query alone.",
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"resolution_write_inconsistency_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"resolved_1_winning_outcome_null_or_empty : {counts['resolved_1_winning_outcome_null_or_empty']}")
    print(f"winning_outcome_set_resolved_0           : {counts['winning_outcome_set_resolved_0']}")
    print(f"resolution_date_set_resolved_0            : {counts['resolution_date_set_resolved_0']}")
    print(f"resolved_1_resolution_date_null           : {counts['resolved_1_resolution_date_null']}")
    print(f"(context) total_markets={breakdown['total_markets']} "
          f"resolved_1={breakdown['total_resolved_1']} "
          f"resolved_0_or_null={breakdown['total_resolved_0_or_null']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
