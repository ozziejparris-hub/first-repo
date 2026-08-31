#!/usr/bin/env python3
"""
scripts/measure_prefilter_coverage.py

Read-only coverage measurement for monitoring/relevance_prefilter.py over the
two Unknown-market populations.  Prints AGGREGATE COUNTS ONLY — never a single
market title — so a later validation-gate sample of pre-filter exclusions
(design §3.9, 200 markets hand-labelled) is not contaminated by anything this
script surfaced.

  - swept   Unknown : category='Unknown' AND resolution_evidence_source='clob'
  - unswept Unknown : category='Unknown' AND (resolved=0 OR resolved IS NULL)

For each population it reports EXCLUDE vs RESIDUAL counts, the per-family
EXCLUDE breakdown (first-matching family), the residual size, and the implied
LLM-stage cost (residual / 20 per batch * 27 s, per design §2.4).

Writes nothing to the DB.  Usage:  python3 scripts/measure_prefilter_coverage.py
"""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monitoring.relevance_prefilter import prefilter_family, FAMILIES

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"

POPULATIONS = {
    "swept Unknown (clob-resolved)":
        "category = 'Unknown' AND resolution_evidence_source = 'clob' "
        "AND title IS NOT NULL",
    "unswept Unknown (resolved=0/NULL)":
        "category = 'Unknown' AND (resolved = 0 OR resolved IS NULL) "
        "AND title IS NOT NULL",
}

BATCH = 20          # LLM titles per prompt   (design §2.4)
SEC_PER_BATCH = 27  # Qwen3-Coder seconds/batch (design §2.4)


def measure(conn, where):
    total = 0
    exclude = 0
    fam_counts = Counter()
    cur = conn.execute(f"SELECT title FROM markets WHERE {where}")
    for (title,) in cur:
        total += 1
        fam = prefilter_family(title)
        if fam is not None:
            exclude += 1
            fam_counts[fam] += 1
    return total, exclude, fam_counts


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] {DB_PATH} not found", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        for label, where in POPULATIONS.items():
            total, exclude, fam = measure(conn, where)
            residual = total - exclude
            pct_ex = exclude / total * 100 if total else 0.0
            print("=" * 70)
            print(f"  {label}")
            print("=" * 70)
            print(f"  total titles    : {total:>9,}")
            print(f"  EXCLUDE         : {exclude:>9,}   ({pct_ex:5.1f} %)")
            print(f"  RESIDUAL        : {residual:>9,}   ({100 - pct_ex:5.1f} %)")
            print(f"  --- EXCLUDE by family (first match) ---")
            for f in FAMILIES:
                c = fam.get(f, 0)
                share = c / exclude * 100 if exclude else 0.0
                print(f"    {f:<20} {c:>9,}   ({share:5.1f} % of EXCLUDE)")
            other = sum(v for k, v in fam.items() if k not in FAMILIES)
            if other:
                print(f"    {'<other>':<20} {other:>9,}")
            n_batches = -(-residual // BATCH)  # ceil
            hours = n_batches * SEC_PER_BATCH / 3600
            print(f"  --- implied LLM-stage cost (residual only) ---")
            print(f"    residual={residual:,}  -> {n_batches:,} batches of {BATCH}"
                  f"  -> ~{hours:.1f} h Qwen compute (+ one-time slug fetch)")
            print()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
