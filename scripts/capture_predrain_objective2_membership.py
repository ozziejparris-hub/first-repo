#!/usr/bin/env python3
"""
Capture the Objective-2 (out-of-sample thesis test) cohort + placebo MEMBERSHIP
and per-trader post-split positions as a pre-drain baseline.

Step 2 of 3 of the geo pending-results drain (2026-09-09-geo-drain-blast-radius.md
Part 5). READ-ONLY. Writes ONE JSON artifact under data/characterizations/.
Never passes --persist to anything, never writes any metric_v2f_* table.

WHY THIS EXISTS: metric_v2f_oos_result stores only aggregate counts
(n_positions / n_traders / point_gap / CI). The trader-level membership of the
120-trader cohort and 110-trader placebo has NEVER been persisted -- the named
mechanism behind the 2026-08-16 UNREPRODUCIBLE verdict. Once the drain flips
pending -> won/lost on pre-split geo/elec trades, build_presplit_cohort() and
match_control() produce different sets and the pre-drain membership cannot be
reconstructed by any means. This is the only opportunity to capture it.

Calls build_presplit_cohort(), match_control(), measure_oos() imported UNCHANGED
from trader_skill_metric_v2f.py, at the same SEED. match_control() was made
deterministic on 2026-09-06 (first-repo 42b14fc: sorted() every set-derived
sequence), so this capture is reproducible from SEED alone -- PYTHONHASHSEED is
recorded anyway for the record.

The stored metric_v2f_oos_result row is hashed before and after and asserted
byte-identical.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import (
    T_SPLIT, SEED, M_CHOSEN, EFFECT_BAR, GATE_REPS_LOCAL, SPEC_VERSION,
    build_presplit_cohort, match_control, measure_oos,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "characterizations")

# measure_oos()'s exact position-loading query (trader_skill_metric_v2f.py:339-350),
# reused here to dump the per-trader rows measure_oos aggregates away.
OOS_POSITIONS_SQL = """
    SELECT p.trader_address, p.market_id, p.outcome, p.entry_avg_price,
           p.entry_timestamp, t.trade_result
    FROM positions p
    JOIN markets m ON m.market_id = p.market_id
    JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
    WHERE m.category IN ('Geopolitics', 'Elections')
      AND p.entry_avg_price IS NOT NULL
      AND t.trade_result IN ('won', 'lost')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND p.trader_address IN ({ph})
      AND p.entry_timestamp > ?
"""


def _git_commit(repo_dir):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def _oos_result_hash(conn):
    rows = conn.execute(
        "SELECT kind, n_positions, n_traders, point_gap, ci_lo, ci_hi, "
        "spec_version, generated_at, generator_commit FROM metric_v2f_oos_result ORDER BY kind"
    ).fetchall()
    blob = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest(), rows


def _per_trader_positions(conn, traders):
    if not traders:
        return {}, dict(n_positions=0, n_traders=0)
    tl = sorted(traders)
    ph = ",".join("?" for _ in tl)
    rows = conn.execute(OOS_POSITIONS_SQL.format(ph=ph), tl + [T_SPLIT]).fetchall()
    out = {}
    for trader, market_id, outcome, price, entry_ts, trade_result in rows:
        out.setdefault(trader, []).append(dict(
            market_id=market_id, outcome=outcome, entry_avg_price=price,
            entry_timestamp=entry_ts, trade_result=trade_result,
            won=1 if trade_result == "won" else 0,
        ))
    summary = dict(n_positions=len(rows), n_traders=len(out))
    return out, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyhashseed = os.environ.get("PYTHONHASHSEED", "(unset -- randomized per process)")

    conn = db_connect(args.db)

    hash_before, rows_before = _oos_result_hash(conn)
    print(f"[guard] metric_v2f_oos_result sha256 BEFORE: {hash_before}")

    print(f"=== build_presplit_cohort(T_SPLIT={T_SPLIT}) ===")
    pd_data = build_presplit_cohort(conn, T_SPLIT, verbose=args.verbose)
    elig_pool = pd_data["elig_pool"]          # DataFrame: trader, n_pairs, ci_lo_t, ...
    intersection = pd_data["intersection"]    # DataFrame: the cohort
    profile = pd_data["profile"]

    elig_traders = sorted(set(elig_pool["trader"]))
    oos_cohort = sorted(set(intersection["trader"]))
    print(f"  elig_pool (n_pairs >= {M_CHOSEN}): {len(elig_traders)} traders")
    print(f"  intersection cohort (sig95 AND edge >= {EFFECT_BAR}): {len(oos_cohort)} traders")

    control_cohort = sorted(match_control(profile, set(oos_cohort), set(elig_traders),
                                          seed=SEED, verbose=args.verbose))
    print(f"  matched placebo (match_control, seed={SEED}): {len(control_cohort)} traders")

    cohort_res = measure_oos(conn, oos_cohort, T_SPLIT, verbose=True, label="cohort")
    placebo_res = measure_oos(conn, control_cohort, T_SPLIT, verbose=True, label="placebo")

    cohort_pos, cohort_pos_sum = _per_trader_positions(conn, oos_cohort)
    placebo_pos, placebo_pos_sum = _per_trader_positions(conn, control_cohort)
    print(f"  cohort post-split positions: {cohort_pos_sum}")
    print(f"  placebo post-split positions: {placebo_pos_sum}")

    hash_after, rows_after = _oos_result_hash(conn)
    print(f"[guard] metric_v2f_oos_result sha256 AFTER:  {hash_after}")
    oos_unchanged = (hash_before == hash_after)
    if not oos_unchanged:
        print("[guard] FATAL: metric_v2f_oos_result CHANGED during this read-only capture.",
              file=sys.stderr)
        conn.close()
        sys.exit(2)
    print("[guard] metric_v2f_oos_result byte-identical before/after -- OK")

    # elig_pool per-trader stats (n_pairs / ci_lo_t / shrunk_mean where present)
    elig_records = elig_pool.to_dict(orient="records")
    intersection_records = intersection.to_dict(orient="records")

    generated_at = datetime.now(timezone.utc).isoformat()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"predrain_objective2_membership_{ts}.json")

    result = dict(
        spec="capture_predrain_objective2_membership",
        purpose="pre-drain baseline: Objective-2 cohort/placebo membership + per-trader "
                "post-split positions (never previously persisted)",
        generated_at=generated_at,
        script_commit=_git_commit(repo_dir),
        db_path=os.path.abspath(args.db),
        params=dict(t_split=T_SPLIT, seed=SEED, m_chosen=M_CHOSEN, effect_bar=EFFECT_BAR,
                    gate_reps_local=GATE_REPS_LOCAL, spec_version=SPEC_VERSION),
        determinism=dict(
            match_control_deterministic_since="first-repo 42b14fc (2026-09-06)",
            pythonhashseed=pyhashseed,
            note="match_control() sorts every set-derived sequence, so output is fixed by "
                 "SEED alone; PYTHONHASHSEED recorded for completeness only.",
        ),
        oos_result_guard=dict(
            sha256_before=hash_before, sha256_after=hash_after,
            unchanged=oos_unchanged, stored_rows=rows_before,
        ),
        elig_pool=dict(n=len(elig_traders), traders=elig_traders, per_trader=elig_records),
        cohort=dict(
            n=len(oos_cohort), traders=oos_cohort,
            intersection_per_trader=intersection_records,
            measure_oos=cohort_res,
            post_split_positions_summary=cohort_pos_sum,
            post_split_positions=cohort_pos,
        ),
        placebo=dict(
            n=len(control_cohort), traders=control_cohort,
            measure_oos=placebo_res,
            post_split_positions_summary=placebo_pos_sum,
            post_split_positions=placebo_pos,
        ),
    )

    os.makedirs(args.out_dir, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    conn.close()

    print("\n=== SUMMARY ===")
    print(f"  elig_pool         : {len(elig_traders)}")
    print(f"  cohort            : {len(oos_cohort)}  measure_oos gap={cohort_res.get('point_gap')} "
          f"CI=[{cohort_res.get('ci_lo')},{cohort_res.get('ci_hi')}] "
          f"n_pos={cohort_res.get('n_positions')} n_surv={cohort_res.get('n_surviving_traders')}")
    print(f"  placebo           : {len(control_cohort)}  measure_oos gap={placebo_res.get('point_gap')} "
          f"CI=[{placebo_res.get('ci_lo')},{placebo_res.get('ci_hi')}] "
          f"n_pos={placebo_res.get('n_positions')} n_surv={placebo_res.get('n_surviving_traders')}")
    print(f"  oos_result guard  : unchanged={oos_unchanged}")
    print(f"\n[json] {out_path}")


if __name__ == "__main__":
    main()
