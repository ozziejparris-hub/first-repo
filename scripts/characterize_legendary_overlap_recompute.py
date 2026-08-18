#!/usr/bin/env python3
"""
Recompute the LEGENDARY-overlap statistic printed by v2f.py:385 --
"overlap with LEGENDARY: {overlap}/{len(legendary)}" -- once against the
hardcoded predicate the six drift-flagged sites actually use (geo_elo >=
2175, characterized read-only in brain/decisions/2026-08-17-legendary-
gate-drift-probe.md) and once against the canonical cd.LEGENDARY_GATE_WHERE
(monitoring/column_definitions.py:123-128).

Read-only. Does not modify the six hardcoded sites, does not touch
cd.LEGENDARY_GATE_WHERE, does not re-run the v2f pipeline -- the cohort side
of the overlap (intersection_traders, Objective 1's sig-95 AND M>=10 AND
edge>=0.02 set) is read directly from its persisted table,
metric_v2f_intersection_cohort (295 rows, generated 2026-08-15T19:36:56Z,
commit eaeabbc -- the same run v2f.py:385 printed from), not recomputed.

Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")

# Verbatim from monitoring/column_definitions.py:123-128.
CANONICAL_LEGENDARY_WHERE = (
    "geo_elo_active >= 2175\n"
    "  AND geo_accuracy_pool = 1\n"
    "  AND research_excluded = 0\n"
    "  AND bot_type IS NULL"
)
# Verbatim from the six sites (v2.py:390, v2b.py:613, v2c.py:506, v2d.py:418,
# v2e.py:437, v2f.py:380) -- identical string in all six, confirmed by grep.
HARDCODED_LEGENDARY_WHERE = "geo_elo >= 2175"

SIX_SITES = [
    "scripts/trader_skill_metric_v2.py:390",
    "scripts/trader_skill_metric_v2b.py:613",
    "scripts/trader_skill_metric_v2c.py:506",
    "scripts/trader_skill_metric_v2d.py:418",
    "scripts/trader_skill_metric_v2e.py:437",
    "scripts/trader_skill_metric_v2f.py:380",
]


def fetch_set(conn, where_sql):
    return set(r[0] for r in conn.execute(f"SELECT address FROM traders WHERE {where_sql}"))


def fetch_cohort(conn):
    """v2f Objective-1 intersection cohort, persisted 2026-08-15T19:36:56Z
    (commit eaeabbc) -- exactly the `intersection_traders` set v2f.py:377-385
    computes and prints the LEGENDARY overlap against."""
    rows = conn.execute("SELECT trader, generated_at, generator_commit, spec_version "
                         "FROM metric_v2f_intersection_cohort").fetchall()
    traders = set(r[0] for r in rows)
    meta = dict(generated_at=rows[0][1], generator_commit=rows[0][2], spec_version=rows[0][3]) if rows else None
    return traders, meta


def decompose(conn, inflated_addresses):
    """For the 81-trader inflated set, count how many fail each of the four
    canonical conditions individually (holding the raw geo_elo>=2175 base
    fixed), and how many fail more than one simultaneously."""
    if not inflated_addresses:
        return dict(n_inflated=0)
    placeholders = ",".join("?" for _ in inflated_addresses)
    rows = conn.execute(f"""
        SELECT address, geo_elo_active, geo_accuracy_pool, research_excluded, bot_type
        FROM traders WHERE address IN ({placeholders})
    """, list(inflated_addresses)).fetchall()

    fails_active = fails_pool = fails_excluded = fails_bot = fails_multi = fails_any = 0
    per_trader = []
    for addr, geo_elo_active, pool, excluded, bot_type in rows:
        f_active = geo_elo_active is None or geo_elo_active < 2175
        f_pool = pool is None or pool != 1
        f_excl = excluded is None or excluded != 0
        f_bot = bot_type is not None
        n_fail = sum([f_active, f_pool, f_excl, f_bot])
        fails_active += f_active
        fails_pool += f_pool
        fails_excluded += f_excl
        fails_bot += f_bot
        if n_fail >= 1:
            fails_any += 1
        if n_fail >= 2:
            fails_multi += 1
        per_trader.append(dict(address=addr, fails_active_decay=f_active, fails_accuracy_pool=f_pool,
                                fails_research_excluded=f_excl, fails_bot_type=f_bot, n_conditions_failed=n_fail))

    return dict(
        n_inflated=len(inflated_addresses),
        fails_active_decay=fails_active,
        fails_accuracy_pool=fails_pool,
        fails_research_excluded=fails_excluded,
        fails_bot_type=fails_bot,
        fails_any_condition=fails_any,
        fails_multiple_conditions=fails_multi,
        n_canonical_survivors=len(inflated_addresses) - fails_any,
        per_trader=per_trader,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--out-dir', default=OUT_DIR)
    args = ap.parse_args()

    conn = db_connect(args.db)
    generated_at = datetime.now(timezone.utc).isoformat()

    cohort, cohort_meta = fetch_cohort(conn)
    legendary_inflated = fetch_set(conn, HARDCODED_LEGENDARY_WHERE)
    legendary_canonical = fetch_set(conn, CANONICAL_LEGENDARY_WHERE)

    overlap_inflated = cohort & legendary_inflated
    overlap_canonical = cohort & legendary_canonical

    decomp = decompose(conn, legendary_inflated)

    result = dict(
        generated_at=generated_at,
        db_path=os.path.abspath(args.db),
        six_sites=SIX_SITES,
        hardcoded_where=HARDCODED_LEGENDARY_WHERE,
        canonical_where=CANONICAL_LEGENDARY_WHERE,
        cohort_source_table="metric_v2f_intersection_cohort",
        cohort_meta=cohort_meta,
        n_cohort=len(cohort),
        inflated=dict(n_legendary=len(legendary_inflated), overlap=len(overlap_inflated),
                      overlap_fraction=len(overlap_inflated) / len(legendary_inflated) if legendary_inflated else None,
                      matches_handover_15_of_81=(len(overlap_inflated) == 15 and len(legendary_inflated) == 81)),
        canonical=dict(n_legendary=len(legendary_canonical), overlap=len(overlap_canonical),
                       overlap_fraction=len(overlap_canonical) / len(legendary_canonical) if legendary_canonical else None),
        decomposition=decomp,
        overlap_traders_inflated=sorted(overlap_inflated),
        overlap_traders_canonical=sorted(overlap_canonical),
        legendary_canonical_addresses=sorted(legendary_canonical),
    )

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"legendary_overlap_recompute_{ts}.json")
    with open(out_path, 'w') as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[written] {out_path}")

    summary = {k: v for k, v in result.items() if k not in
               ('overlap_traders_inflated', 'overlap_traders_canonical', 'legendary_canonical_addresses')}
    summary['decomposition'] = {k: v for k, v in decomp.items() if k != 'per_trader'}
    print(json.dumps(summary, indent=2, default=str))


if __name__ == '__main__':
    main()
