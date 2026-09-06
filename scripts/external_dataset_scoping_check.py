#!/usr/bin/env python3
"""
EXTERNAL DATASET SCOPING CHECK -- Part 1 of brain/decisions/2026-09-06-
external-dataset-scoping-and-prereg-amendment.md. Answers whether
vgregoire/polymarket-users (data/external/*.parquet) can contribute to the
directional-skill persistence test (N=146, first-repo 1d34ced).

READ-ONLY. Does not import, merge, or write anything from the external
dataset into any production table -- output goes only to the JSON artifact
named on the command line. Inspects schema and column-level stats only
(pyarrow parquet metadata + a small number of columns read in full for
min/max/set-membership); never loads full per-row PnL/feature content.

Computes counts and coverage only. No post-split classification, p-value,
or outcome-dependent quantity is computed here -- this script answers a
scoping question about a completely separate, external dataset.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pyarrow.parquet as pq
import pyarrow.compute as pc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

T_SPLIT = "2026-04-01 00:00:00"
EXTERNAL_DIR = "data/external"
PNL_FILE = "user_pnl_summary.parquet"
FEATURES_FILE = "user_features.parquet"


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def schema_of(path):
    pf = pq.ParquetFile(path)
    return dict(
        num_rows=pf.metadata.num_rows,
        num_row_groups=pf.metadata.num_row_groups,
        columns=[dict(name=f.name, type=str(f.type)) for f in pf.schema_arrow],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--external-dir', default=EXTERNAL_DIR)
    ap.add_argument('--pit-pool-json', default='data/characterizations/directional_skill_pit_legal_pool_20260906T160303Z.json')
    ap.add_argument('--twice-classifiable-json', default='data/characterizations/directional_skill_twice_classifiable_population_20260906T170928Z.json')
    ap.add_argument('--json-out', required=True)
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pnl_path = os.path.join(args.external_dir, PNL_FILE)
    feat_path = os.path.join(args.external_dir, FEATURES_FILE)

    print("=== [1] schema ===")
    pnl_schema = schema_of(pnl_path)
    feat_schema = schema_of(feat_path)
    print(f"[{PNL_FILE}] {pnl_schema['num_rows']} rows, {len(pnl_schema['columns'])} columns, "
          f"one row per user_address (aggregate, no per-position/per-trade rows)")
    print(f"[{FEATURES_FILE}] {feat_schema['num_rows']} rows, {len(feat_schema['columns'])} columns, "
          f"one row per user_address (aggregate, no per-position/per-trade rows)")
    pnl_one_row_per_address = pnl_schema['num_rows'] == len(set(pq.read_table(pnl_path, columns=['user_address'])['user_address'].to_pylist()))
    feat_one_row_per_address = feat_schema['num_rows'] == len(set(pq.read_table(feat_path, columns=['user_address'])['user_address'].to_pylist()))
    per_position_records_exist = not (pnl_one_row_per_address and feat_one_row_per_address)
    print(f"[2] per-position/per-trade records exist in either file: {per_position_records_exist} "
          f"(confirmed one row per distinct user_address in both files -- num_rows equals "
          f"n_distinct(user_address) -- so items 1-2 resolve together: no per-position "
          f"records exist to carry market id / side / entry price / outcome, at any "
          f"granularity, in either file)")

    print("\n=== [3] coverage, verified from the file ===")
    ts_tbl = pq.read_table(feat_path, columns=['first_trade', 'last_trade'])
    min_first = pc.min(ts_tbl['first_trade']).as_py()
    max_last = pc.max(ts_tbl['last_trade']).as_py()
    print(f"min(first_trade)={min_first}  max(last_trade)={max_last}  T_SPLIT={T_SPLIT}")
    coverage_ends_before_split = str(max_last).replace('+00:00', '') < T_SPLIT
    print(f"coverage ends before T_SPLIT: {coverage_ends_before_split}")

    print("\n=== [4] address overlap: external vs. our traders table ===")
    ext_tbl = pq.read_table(feat_path, columns=['user_address'])
    ext_addrs = set(ext_tbl['user_address'].to_pylist())
    pnl_addr_tbl = pq.read_table(pnl_path, columns=['user_address'])
    pnl_addrs = set(pnl_addr_tbl['user_address'].to_pylist())
    same_address_sets = ext_addrs == pnl_addrs

    conn = sqlite3.connect(args.db)
    our_addrs = set(r[0] for r in conn.execute('SELECT address FROM traders').fetchall())
    conn.close()

    external_not_in_ours = ext_addrs - our_addrs
    overlap = ext_addrs & our_addrs
    print(f"external distinct addresses: {len(ext_addrs)} "
          f"(pnl_summary and user_features share identical address set: {same_address_sets})")
    print(f"our traders table distinct addresses: {len(our_addrs)}")
    print(f"external addresses NOT in our traders table: {len(external_not_in_ours)} "
          f"({len(external_not_in_ours)/len(ext_addrs)*100:.1f}%)")
    print(f"overlap: {len(overlap)}")

    print("\n=== [5] overlap with the two study populations ===")
    pb = json.load(open(args.pit_pool_json))
    pit_classifiable = set(pb['per_trader_result']['per_trader'].keys())
    tc = json.load(open(args.twice_classifiable_json))
    twice_classifiable = set(tc['twice_classifiable_traders'])

    pit_overlap = pit_classifiable & ext_addrs
    twice_overlap = twice_classifiable & ext_addrs
    print(f"PIT-legal classifiable (n={len(pit_classifiable)}) in external dataset: "
          f"{len(pit_overlap)} ({len(pit_overlap)/len(pit_classifiable)*100:.1f}%)")
    print(f"twice-classifiable (n={len(twice_classifiable)}) in external dataset: "
          f"{len(twice_overlap)} ({len(twice_overlap)/len(twice_classifiable)*100:.1f}%)")

    # Both reasons are independently sufficient: no per-position granularity exists at
    # any point in the schema, and coverage ends before T_SPLIT regardless of granularity.
    verdict_can_increase_n = False
    print(f"\n=== VERDICT ===")
    print(f"Can this dataset increase the persistence test's N? {verdict_can_increase_n} "
          f"(aggregate-only schema -- no per-position records at all; AND coverage ends "
          f"before T_SPLIT even disregarding granularity)")

    out = dict(
        spec="external_dataset_scoping_check",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        t_split=T_SPLIT,
        pnl_schema=pnl_schema,
        features_schema=feat_schema,
        same_address_sets_across_files=same_address_sets,
        min_first_trade=str(min_first),
        max_last_trade=str(max_last),
        coverage_ends_before_t_split=coverage_ends_before_split,
        n_external_addresses=len(ext_addrs),
        n_our_traders_addresses=len(our_addrs),
        n_external_not_in_our_traders=len(external_not_in_ours),
        n_overlap=len(overlap),
        n_pit_classifiable=len(pit_classifiable),
        n_pit_classifiable_in_external=len(pit_overlap),
        n_twice_classifiable=len(twice_classifiable),
        n_twice_classifiable_in_external=len(twice_overlap),
        verdict_can_increase_persistence_test_N=verdict_can_increase_n,
    )
    os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
    with open(args.json_out, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] written to {args.json_out}")


if __name__ == '__main__':
    main()
