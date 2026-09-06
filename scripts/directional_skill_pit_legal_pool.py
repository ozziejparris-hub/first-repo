#!/usr/bin/env python3
"""
PIT-LEGAL SELECTION POOL -- directional-skill test restricted to positions in
markets whose tape_end falls BEFORE T_SPLIT. Executes brain/decisions/
2026-09-0X-discrepancy-pit-pool-power.md, Part B. Read-only against
production tables. Writes no metric_v2f_* or other production table --
output goes only to the JSON artifact named on the command line.

WHY THIS EXISTS: the 2026-09-05 directional-skill test's cohort/placebo
trader lists were themselves selected using PRE-split performance
(trader_skill_metric_v2f.build_presplit_cohort's sig95+edge-bar test), then
the directional (sign-flip) test was run on their POST-split positions. A
selector built directly from that POST-split directional-test output would
look ahead: it would use information (post-split directional classification)
that would not have been available at T_SPLIT. This script asks a different,
PIT-legal question: which traders show directional skill using ONLY
positions in markets that had already concluded (tape_end < T_SPLIT) --
information that genuinely existed before the split, for ANY trader with
qualifying pre-split activity, not the frozen cohort/placebo lists (reusing
those here would be circular: they were built from the same pre-split data
via a different test).

TAPE_END ANCHORING: this script calls monitoring.column_definitions.
backtest_window_sql() directly -- the project's own canonical population
definition (Section 6) -- rather than reimplementing the tape_end CTE a
third time. Reported finding (Part A/B write-up): directional_skill_
diagnostic.py's own load_post_split_positions() does NOT call this
canonical function; it filters on p.entry_timestamp > T_SPLIT (position
entry time), not tape_end (market conclusion time), and does not reference
column_definitions.py at all. trader_skill_metric_v2f.build_presplit_cohort()
DOES anchor on tape_end, but via its own build_tape_end_map() (v2d.py),
a separately-maintained duplicate of the same MAX(trades.timestamp)
computation -- also not a call to the canonical function. Neither existing
script uses backtest_window_sql(). This script is the first to call it
directly for this purpose; that is a deliberate choice for this task, not
a change to either existing script.

HARNESS: per_trader_and_aggregate(), sign_flip_null(), classify(),
bh_correction() are imported unchanged from directional_skill_diagnostic.py.
No harness function is modified. The only new code here is the position
loader (necessarily new: the harness's own loader filters on entry_timestamp,
not market membership in a tape_end-restricted set) and the distribution/
survival reporting Part B asks for.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, M_CHOSEN
from scripts.directional_skill_diagnostic import (
    load_post_split_positions, per_trader_and_aggregate,
    REPS, ALPHA,
)
from monitoring.column_definitions import backtest_window_sql

FLOOR_PVALUE = 1.0 / (REPS + 1)
VERY_EARLY = "2000-01-01 00:00:00"


def load_presplit_market_ids(conn, t_split):
    """Canonical pre-split market population: tape_end < t_split, via the
    project's own backtest_window_sql() (monitoring/column_definitions.py
    Section 6) -- resolved=1, Geopolitics/Elections, gap-clean, anchored on
    event-time (tape_end), not write-time (resolution_date)."""
    sql = backtest_window_sql(VERY_EARLY, t_split)
    rows = conn.execute(sql, {"window_start": VERY_EARLY, "window_end": t_split}).fetchall()
    market_ids = [r[0] for r in rows]
    tape_ends = {r[0]: r[4] for r in rows}  # market_id, title, condition_id, resolution_date, tape_end
    return market_ids, tape_ends


def load_presplit_positions(conn, market_ids):
    """Same structural filters as load_post_split_positions() (entry_avg_price
    not null, trade_result won/lost) but the windowing predicate is market
    membership in the tape_end-restricted set, not p.entry_timestamp. Category
    and gap-flag filters are already applied by backtest_window_sql() at the
    market level, not duplicated here."""
    placeholders = ",".join("?" for _ in market_ids)
    rows = conn.execute(f"""
        SELECT p.trader_address, p.market_id, p.entry_avg_price, p.entry_total_cost,
               p.entry_timestamp, t.trade_result
        FROM positions p
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE p.market_id IN ({placeholders})
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
    """, market_ids).fetchall()
    df = pd.DataFrame(rows, columns=['trader', 'market_id', 'price', 'cost', 'entry_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    df['edge'] = df['won'] - df['price']
    df['weighted_edge'] = df['edge'] * df['cost']
    return df


def distribution_stats(counts):
    arr = np.asarray(counts, dtype=float)
    return dict(
        n_traders=len(arr),
        median=float(np.median(arr)), mean=float(np.mean(arr)),
        p25=float(np.percentile(arr, 25)), p75=float(np.percentile(arr, 75)),
        p10=float(np.percentile(arr, 10)), p90=float(np.percentile(arr, 90)),
        max=int(arr.max()), min=int(arr.min()),
    )


def pvalue_diagnostics(per_trader):
    pvals = [v['p_value'] for v in per_trader.values()]
    n = len(pvals)
    if n == 0:
        return dict(n=0)
    arr = np.asarray(pvals)
    return dict(
        n=n,
        below_0_05=int((arr < 0.05).sum()), rate_0_05=float((arr < 0.05).mean()),
        below_0_01=int((arr < 0.01).sum()), rate_0_01=float((arr < 0.01).mean()),
        below_0_001=int((arr < 0.001).sum()), rate_0_001=float((arr < 0.001).mean()),
        distinct_pvalues=int(len(np.unique(arr))),
        pinned_at_floor=int(np.isclose(arr, FLOOR_PVALUE, atol=1e-9).sum()),
        pinned_at_floor_rate=float(np.isclose(arr, FLOOR_PVALUE, atol=1e-9).mean()),
    )


def selfcheck(df, n_samples=200, seed=7, verbose=True):
    """Re-derives weighted_edge for a random sample from (won, price, cost)
    and asserts exact match -- catches construction drift."""
    sample = df.sample(min(n_samples, len(df)), random_state=seed)
    mism = []
    for _, row in sample.iterrows():
        edge_expected = row['won'] - row['price']
        we_expected = edge_expected * row['cost']
        if abs(we_expected - row['weighted_edge']) > 1e-9:
            mism.append((row['trader'], row['market_id']))
    if verbose:
        print(f"[selfcheck] {len(sample)} positions re-derived, {len(mism)} mismatches")
    return len(sample), mism


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = db_connect(args.db)

    print(f"=== PIT-LEGAL MARKET POOL: tape_end < T_SPLIT={T_SPLIT} (via canonical backtest_window_sql) ===")
    market_ids, tape_ends = load_presplit_market_ids(conn, T_SPLIT)
    print(f"[markets] {len(market_ids)} Geopolitics/Elections resolved markets with tape_end < {T_SPLIT}")
    assert all(te < T_SPLIT for te in tape_ends.values()), \
        "SCOPING VIOLATION: a market with tape_end >= T_SPLIT leaked into the pre-split pool"
    print("[SCOPING OK] every market's tape_end predates T_SPLIT.\n")

    df = load_presplit_positions(conn, market_ids)
    all_traders = sorted(df['trader'].unique().tolist())
    print(f"[positions] {len(df)} pre-split resolved positions, {len(all_traders)} distinct traders with >=1")

    if args.selfcheck:
        n, mism = selfcheck(df, verbose=True)
        if mism:
            print(f"[selfcheck] FAILED: {len(mism)}/{n} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {n}/{n} match")

    counts = df.groupby('trader').size()
    dist = distribution_stats(counts.to_numpy())
    print(f"[distribution] median={dist['median']} mean={dist['mean']:.1f} "
          f"p25={dist['p25']} p75={dist['p75']} p10={dist['p10']} p90={dist['p90']} max={dist['max']}")

    n_clearing_min = int((counts >= M_CHOSEN).sum())
    print(f"[min-count] {n_clearing_min}/{len(all_traders)} traders clear n>={M_CHOSEN} "
          f"(M_CHOSEN, reused unchanged from the harness's own convention)")

    print("\n=== PER-TRADER + AGGREGATE (identical harness function, unmodified) ===")
    result = per_trader_and_aggregate(df, all_traders, "pit_legal_presplit", verbose=True)

    pdiag = pvalue_diagnostics(result['per_trader'])
    print(f"[pvalue diagnostics] n={pdiag['n']} distinct_pvalues={pdiag['distinct_pvalues']} "
          f"pinned_at_floor={pdiag['pinned_at_floor']} ({pdiag['pinned_at_floor_rate']*100:.1f}%)")

    raw_skilled_traders = [t for t, v in result['per_trader'].items() if v['skilled']]
    bh_skilled_traders = [t for t, v in result['per_trader'].items() if v['bh_significant']]
    print(f"[skilled sets] raw={len(raw_skilled_traders)} bh={len(bh_skilled_traders)}")

    print("\n=== SURVIVAL: any post-split resolved position ===")
    post_split_raw = load_post_split_positions(conn, raw_skilled_traders, T_SPLIT) if raw_skilled_traders else pd.DataFrame(columns=['trader'])
    post_split_bh = load_post_split_positions(conn, bh_skilled_traders, T_SPLIT) if bh_skilled_traders else pd.DataFrame(columns=['trader'])
    survivors_raw = sorted(post_split_raw['trader'].unique().tolist()) if len(post_split_raw) else []
    survivors_bh = sorted(post_split_bh['trader'].unique().tolist()) if len(post_split_bh) else []
    print(f"[survival] raw-skilled: {len(raw_skilled_traders)} qualified, {len(survivors_raw)} survived into post-split")
    print(f"[survival] bh-skilled: {len(bh_skilled_traders)} qualified, {len(survivors_bh)} survived into post-split")

    conn.close()

    out = dict(
        spec="directional_skill_pit_legal_pool",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        seed=SEED, reps=REPS, t_split=T_SPLIT, min_trades_per_trader=M_CHOSEN, alpha=ALPHA,
        n_presplit_markets=len(market_ids),
        n_presplit_positions=len(df),
        n_traders_any_presplit_position=len(all_traders),
        position_count_distribution=dist,
        n_clearing_min=n_clearing_min,
        per_trader_result=result,
        pvalue_diagnostics=pdiag,
        raw_skilled_traders=raw_skilled_traders,
        bh_skilled_traders=bh_skilled_traders,
        survival=dict(
            raw_qualified=len(raw_skilled_traders), raw_survived=len(survivors_raw),
            raw_survivors=survivors_raw,
            bh_qualified=len(bh_skilled_traders), bh_survived=len(survivors_bh),
            bh_survivors=survivors_bh,
        ),
    )

    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
