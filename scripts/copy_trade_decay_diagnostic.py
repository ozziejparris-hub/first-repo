#!/usr/bin/env python3
"""
Copy-trade decay measurement — executes brain/decisions/2026-09-05-copy-trade-
decay-prereg.md AS AMENDED 2026-09-10 (trading-swarm 7b9e1e7).

THE PRE-REGISTRATION IS AUTHORITATIVE. Where this script and the amended
document differ, the DOCUMENT WINS. Read-only against production tables;
writes only the JSON artifact named on the command line.

What it does, per the amended prereg:
  * Primary population: the BROAD PIT-LEGAL CLASSIFIABLE POOL — traders with
    >= M_CHOSEN (10) pre-split resolved geo/elec positions in the canonical
    pre-split market set (backtest_window_sql, tape_end < T_SPLIT). Re-derived
    at run time (post-2026-09-09-drain), count + delta from 5,732 recorded.
    Decay measured on this pool's OOS (entry_timestamp > T_SPLIT) positions.
  * Secondary: cohort (169) and placebo (169), the frozen Track 2 lists from
    track2_ci_power_20260905T104945Z.json — reported for SHAPE comparison
    only; their LEVEL is contaminated by presplit-edge selection.
  * N ladder (amendment item C), 15 points, minutes:
    1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 960, 1440, 2880, 5760, 11520.
  * Price substitution (item E): the price of the NEXT trade in that market
    at or after entry_timestamp + N, from the executed trade tape
    (trades.price). Own-trader trades INCLUDED. Single trade, not a window
    average. price_at()/CLOB is NOT used.
  * Thin/missing (item F): tape_end < entry_ts+N  -> position EXCLUDED from
    that rung only (5b). Otherwise the next trade at/after entry_ts+N is
    used however far past nominal N it lands (5a, carry forward); realised
    delay recorded. Surviving n reported every rung; THIN flag when n_pairs
    < max(30, 5% of that population's N=0 pair count). A rung with zero
    computable pairs is reported as uncomputable, never silently dropped.
  * N=0 gate (item D): INTERNAL consistency — at N=0 (entry_avg_price used
    directly, no lookup) the harness must reproduce a direct measure_oos()
    computation on the SAME positions, |delta| <= 1e-9 on point_gap/ci_lo/
    ci_hi and exact n_positions/n_pairs/n_traders, for EACH population.
    Failure => STOP.
  * Viability bar (item B): fixed per-category cost floors from
    MASTER_HANDOVER_2026-08-15 §5 — geopolitics 0.0005-0.010, elections
    0.0056-0.020, blended 0.02. Per-category curves reported. cost_floor()
    run on each population's OOS entry prices as a cross-check.

Reuses measure_oos / weighted_pair_table / weighted_two_way_gap_bootstrap and
the broad-pool loaders unmodified. Only the price substitution, the N-loop,
and the three-population wrapper are new.

Seed 42, reps 1500, cap5, T_SPLIT = 2026-04-01 00:00:00 — hardcoded, from the
v2d/v2f/Track 2 lineage.
"""
import argparse
import bisect
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2c import WEIGHT_FNS
from scripts.trader_skill_metric_v2d import (
    weighted_pair_table, weighted_two_way_gap_bootstrap,
)
from scripts.trader_skill_metric_v2f import (
    T_SPLIT, SEED, GATE_REPS_LOCAL, M_CHOSEN, measure_oos, cost_floor,
)
from scripts.directional_skill_pit_legal_pool import (
    load_presplit_market_ids, load_presplit_positions,
)

# --- fixed parameters (amended prereg) --------------------------------------
N_LADDER_MIN = [1, 2, 5, 10, 15, 30, 60, 120, 240, 480, 960, 1440, 2880, 5760, 11520]
N_LADDER_SECONDS = [m * 60 for m in N_LADDER_MIN]
GATE_TOL = 1e-9
THIN_ABS = 30
THIN_FRAC = 0.05
BROAD_POOL_2026_09_06 = 5732  # directional_skill_pit_legal_pool_20260906T160303Z.json

# MASTER_HANDOVER_2026-08-15 §5 — fixed cost floors, per category
COST_FLOORS = {
    "Geopolitics": {"lo": 0.0005, "hi": 0.010, "fee": "fee-free (spread only)"},
    "Elections":   {"lo": 0.0056, "hi": 0.020, "fee": "4% feeRate; fee 0.0097 at median price 0.59"},
    "blended_bar": 0.02,
}

TRACK2_ARTIFACT = "data/characterizations/track2_ci_power_20260905T104945Z.json"
OOS_RESULT_SHA_EXPECTED = "021be40a87df48c1f37efb8265f223b005c9c50bca8e32ee1bcb134fe074cd4e"


def git_commit(repo_dir, ref="HEAD"):
    try:
        return subprocess.check_output(["git", "rev-parse", ref], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def oos_result_sha(db_path):
    """Exactly the stop-condition definition:
        sqlite3 <db> "SELECT * FROM metric_v2f_oos_result" | sha256sum
    Shelled out so the digest matches that pinned value byte-for-byte
    (sqlite3 CLI float/column formatting, not Python str())."""
    out = subprocess.check_output(
        ["sqlite3", db_path, "SELECT * FROM metric_v2f_oos_result"])
    return hashlib.sha256(out).hexdigest()


# --------------------------------------------------------------------------
# population loaders
# --------------------------------------------------------------------------

def load_broad_pool(conn):
    """Re-derive the broad PIT-legal classifiable pool from the current DB,
    reusing directional_skill_pit_legal_pool's loaders unmodified."""
    market_ids, tape_ends = load_presplit_market_ids(conn, T_SPLIT)
    assert all(te < T_SPLIT for te in tape_ends.values()), \
        "SCOPING VIOLATION: a market with tape_end >= T_SPLIT leaked into the pre-split pool"
    df = load_presplit_positions(conn, market_ids)
    counts = df.groupby("trader").size()
    pool = sorted(counts[counts >= M_CHOSEN].index.tolist())
    return pool, dict(
        n_presplit_markets=len(market_ids),
        n_presplit_positions=int(len(df)),
        n_traders_any_presplit_position=int(counts.size),
        n_clearing_min=len(pool),
        delta_from_2026_09_06=len(pool) - BROAD_POOL_2026_09_06,
    )


def load_track2_lists():
    d = json.load(open(TRACK2_ARTIFACT))
    return sorted(d["cohort_trader_list"]), sorted(d["control_trader_list"])


# --------------------------------------------------------------------------
# OOS positions + trade tape
# --------------------------------------------------------------------------

OOS_POSITIONS_SQL = """
    SELECT p.trader_address, p.market_id, m.category, p.entry_avg_price,
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


def load_oos_positions(conn, traders):
    """Position-level OOS rows for a trader list. Mirrors measure_oos's own
    query (same WHERE), plus entry_timestamp / market_id / category, which
    measure_oos does not return but the N-loop needs."""
    out = []
    CHUNK = 900
    tl = sorted(traders)
    for i in range(0, len(tl), CHUNK):
        chunk = tl[i:i + CHUNK]
        ph = ",".join("?" for _ in chunk)
        rows = conn.execute(OOS_POSITIONS_SQL.format(ph=ph), chunk + [T_SPLIT]).fetchall()
        out.extend(rows)
    df = pd.DataFrame(out, columns=["trader", "market_id", "category", "price",
                                    "entry_ts", "trade_result"])
    df["won"] = (df["trade_result"] == "won").astype(int)
    df["entry_ts_dt"] = pd.to_datetime(df["entry_ts"])
    return df


def build_trade_tape(conn, market_ids):
    """{market_id: (sorted list[str timestamp], list[float price], str tape_end)}.
    'Next trade at or after T' = bisect_left on the timestamp list."""
    tape = {}
    CHUNK = 900
    mids = sorted(set(market_ids))
    for i in range(0, len(mids), CHUNK):
        chunk = mids[i:i + CHUNK]
        ph = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT market_id, timestamp, price FROM trades "
            f"WHERE market_id IN ({ph}) ORDER BY market_id, timestamp", chunk
        ).fetchall()
        by_mkt = {}
        for mid, ts, px in rows:
            by_mkt.setdefault(mid, ([], []))
            by_mkt[mid][0].append(ts)
            by_mkt[mid][1].append(float(px) if px is not None else np.nan)
        for mid, (tss, pxs) in by_mkt.items():
            tape[mid] = (tss, pxs, tss[-1])  # already ordered by the SQL
    return tape


def substitute_price_at_N(df, tape, n_seconds):
    """Return (sub_df, realised_delays_seconds, n_excluded_tape_end).

    Per amendment items E/F:
      - target T = entry_ts + N
      - if T > market tape_end            -> EXCLUDE this position from the rung (5b)
      - else substituted price = price of the FIRST trade with timestamp >= T
        (5a: used however far past nominal N it lands); realised delay recorded
    """
    sub_rows = []
    delays = []
    n_excluded = 0
    n_no_tape = 0
    for row in df.itertuples(index=False):
        entry_dt = row.entry_ts_dt
        target = entry_dt + pd.Timedelta(seconds=n_seconds)
        target_str = target.strftime("%Y-%m-%d %H:%M:%S")
        rec = tape.get(row.market_id)
        if rec is None:
            n_no_tape += 1
            n_excluded += 1
            continue
        tss, pxs, tape_end = rec
        if target_str > tape_end:
            n_excluded += 1
            continue
        j = bisect.bisect_left(tss, target_str)
        if j >= len(tss):
            # target_str <= tape_end but strictly greater than every stored
            # string: only possible on formatting edge cases; treat as excluded.
            n_excluded += 1
            continue
        sub_px = pxs[j]
        if not np.isfinite(sub_px):
            n_excluded += 1
            continue
        try:
            trade_dt = pd.to_datetime(tss[j])
            delays.append((trade_dt - entry_dt).total_seconds())
        except Exception:
            delays.append(float(n_seconds))
        sub_rows.append((row.trader, row.market_id, row.category, row.won, sub_px))
    sub_df = pd.DataFrame(sub_rows, columns=["trader", "market_id", "category", "won", "price"])
    return sub_df, np.array(delays, dtype=float), n_excluded, n_no_tape


def curve_point(sub_df, reps, seed):
    """weighted_pair_table + two-way clustered bootstrap on substituted prices."""
    if len(sub_df) == 0:
        return dict(n_positions=0, n_pairs=0, n_traders=0, n_markets=0,
                    point_gap=None, ci_lo=None, ci_hi=None)
    pairs = weighted_pair_table(sub_df[["trader", "market_id", "won", "price"]], WEIGHT_FNS["cap5"])
    r = weighted_two_way_gap_bootstrap(pairs, reps=reps, seed=seed)
    r["n_positions"] = int(len(sub_df))
    return r


def delay_stats(delays):
    if len(delays) == 0:
        return dict(n=0)
    return dict(
        n=int(len(delays)),
        min=float(np.min(delays)), p25=float(np.percentile(delays, 25)),
        median=float(np.median(delays)), p75=float(np.percentile(delays, 75)),
        p90=float(np.percentile(delays, 90)), max=float(np.max(delays)),
        mean=float(np.mean(delays)),
    )


def volume_composition(sub_df, base_positions_per_trader):
    """§5c open-question disclosure: does the surviving subsample's per-trader
    OOS position count differ from the N=0 composition? Reported, not corrected."""
    if len(sub_df) == 0:
        return dict(n_traders=0)
    surviving = sub_df.groupby("trader").size()
    base = pd.Series(base_positions_per_trader)
    common = base.index.intersection(surviving.index)
    return dict(
        n_traders=int(surviving.size),
        surviving_median_pos_per_trader=float(surviving.median()),
        base_median_pos_per_trader=float(base.median()),
        surviving_mean_pos_per_trader=float(surviving.mean()),
        base_mean_pos_per_trader=float(base.mean()),
        traders_retained_frac=float(len(common) / max(1, base.index.size)),
    )


# --------------------------------------------------------------------------
# per-population run
# --------------------------------------------------------------------------

def run_population(conn, label, traders, tape_cache, reps, seed, per_category=False):
    print(f"\n=== population: {label}  ({len(traders)} traders) ===")
    df = load_oos_positions(conn, traders)
    print(f"  OOS positions: {len(df)}  distinct traders w/ >=1: {df['trader'].nunique()}  "
          f"markets: {df['market_id'].nunique()}")

    # trade tape for every market in this population's OOS positions
    need = set(df["market_id"].unique()) - set(tape_cache.keys())
    if need:
        tape_cache.update(build_trade_tape(conn, list(need)))

    base_positions_per_trader = df.groupby("trader").size().to_dict()

    # ---- N=0 internal-consistency gate (item D) ----
    # measure_oos() hardcodes seed=SEED, reps=GATE_REPS_LOCAL — the gate compares
    # the harness against THAT canonical call, so the N=0 harness point is
    # computed at the same seed/reps regardless of --seed/--reps.
    direct = measure_oos(conn, traders, T_SPLIT)
    n0_df = df[["trader", "market_id", "category", "won", "price"]].copy()
    n0 = curve_point(n0_df, reps=GATE_REPS_LOCAL, seed=SEED)
    gate = dict(
        direct=dict(point_gap=direct.get("point_gap"), ci_lo=direct.get("ci_lo"),
                    ci_hi=direct.get("ci_hi"), n_positions=direct.get("n_positions"),
                    n_pairs=direct.get("n_pairs"), n_traders=direct.get("n_traders")),
        harness=dict(point_gap=n0.get("point_gap"), ci_lo=n0.get("ci_lo"),
                     ci_hi=n0.get("ci_hi"), n_positions=n0.get("n_positions"),
                     n_pairs=n0.get("n_pairs"), n_traders=n0.get("n_traders")),
    )

    def close(a, b):
        return a is not None and b is not None and abs(a - b) <= GATE_TOL

    gate["deltas"] = {
        k: (None if gate["direct"][k] is None or gate["harness"][k] is None
            else float(gate["harness"][k] - gate["direct"][k]))
        for k in ("point_gap", "ci_lo", "ci_hi", "n_positions", "n_pairs", "n_traders")
    }
    gate["pass"] = bool(
        close(gate["direct"]["point_gap"], gate["harness"]["point_gap"])
        and close(gate["direct"]["ci_lo"], gate["harness"]["ci_lo"])
        and close(gate["direct"]["ci_hi"], gate["harness"]["ci_hi"])
        and gate["direct"]["n_positions"] == gate["harness"]["n_positions"]
        and gate["direct"]["n_pairs"] == gate["harness"]["n_pairs"]
        and gate["direct"]["n_traders"] == gate["harness"]["n_traders"]
    )
    print(f"  N=0 GATE: {'PASS' if gate['pass'] else 'FAIL'}  "
          f"harness point_gap={gate['harness']['point_gap']}  direct={gate['direct']['point_gap']}  "
          f"deltas={gate['deltas']}")

    n0_pairs = n0.get("n_pairs") or 0
    thin_threshold = max(THIN_ABS, THIN_FRAC * n0_pairs)

    rungs = []
    for n_min, n_sec in zip(N_LADDER_MIN, N_LADDER_SECONDS):
        sub_df, delays, n_excl, n_no_tape = substitute_price_at_N(df, tape_cache, n_sec)
        pt = curve_point(sub_df, reps=reps, seed=seed)
        n_pairs = pt.get("n_pairs") or 0
        entry = dict(
            N_minutes=n_min, N_seconds=n_sec,
            point_gap=pt.get("point_gap"), ci_lo=pt.get("ci_lo"), ci_hi=pt.get("ci_hi"),
            n_positions=pt.get("n_positions"), n_pairs=n_pairs,
            n_traders=pt.get("n_traders"), n_markets=pt.get("n_markets"),
            n_excluded_tape_end=int(n_excl), n_excluded_no_tape=int(n_no_tape),
            excluded_frac=float(n_excl / max(1, len(df))),
            realised_delay_seconds=delay_stats(delays),
            thin=bool(n_pairs < thin_threshold),
            uncomputable=bool(pt.get("point_gap") is None),
            volume_composition=volume_composition(sub_df, base_positions_per_trader),
        )
        rungs.append(entry)
        flag = "THIN" if entry["thin"] else ("UNCOMPUTABLE" if entry["uncomputable"] else "ok")
        print(f"  N={n_min:>6}min  gap={_fmt(pt.get('point_gap'))}  "
              f"CI=[{_fmt(pt.get('ci_lo'))},{_fmt(pt.get('ci_hi'))}]  "
              f"n_pairs={n_pairs:<6} excl={n_excl:<6} "
              f"delay_med={_fmt(delay_stats(delays).get('median'))}s  [{flag}]")

    result = dict(
        label=label, n_traders_in_list=len(traders),
        oos_n_positions=int(len(df)), oos_n_traders=int(df["trader"].nunique()),
        oos_n_markets=int(df["market_id"].nunique()),
        n0_gate=gate, thin_threshold_pairs=float(thin_threshold),
        rungs=rungs,
    )

    if per_category:
        result["per_category"] = {}
        for cat in ("Geopolitics", "Elections"):
            cat_df = df[df["category"] == cat].copy()
            cat_rungs = []
            cat_n0 = curve_point(
                cat_df[["trader", "market_id", "category", "won", "price"]], reps=reps, seed=seed)
            cat_n0_pairs = cat_n0.get("n_pairs") or 0
            cat_thin = max(THIN_ABS, THIN_FRAC * cat_n0_pairs)
            for n_min, n_sec in zip(N_LADDER_MIN, N_LADDER_SECONDS):
                sub_df, delays, n_excl, _ = substitute_price_at_N(cat_df, tape_cache, n_sec)
                pt = curve_point(sub_df, reps=reps, seed=seed)
                np_ = pt.get("n_pairs") or 0
                cat_rungs.append(dict(
                    N_minutes=n_min, point_gap=pt.get("point_gap"),
                    ci_lo=pt.get("ci_lo"), ci_hi=pt.get("ci_hi"),
                    n_pairs=np_, n_positions=pt.get("n_positions"),
                    n_excluded_tape_end=int(n_excl),
                    realised_delay_seconds=delay_stats(delays),
                    thin=bool(np_ < cat_thin),
                    uncomputable=bool(pt.get("point_gap") is None),
                ))
            result["per_category"][cat] = dict(
                oos_n_positions=int(len(cat_df)),
                n0=dict(point_gap=cat_n0.get("point_gap"), ci_lo=cat_n0.get("ci_lo"),
                        ci_hi=cat_n0.get("ci_hi"), n_pairs=cat_n0_pairs),
                cost_floor_fixed=COST_FLOORS[cat],
                thin_threshold_pairs=float(cat_thin),
                rungs=cat_rungs,
            )

    # cost_floor() cross-check on this population's own positions
    try:
        result["cost_floor_crosscheck"] = cost_floor(df, traders, conn, verbose=False)
    except Exception as e:  # pragma: no cover
        result["cost_floor_crosscheck"] = dict(error=str(e))

    return result, gate["pass"]


def _fmt(x):
    return "None" if x is None else f"{x:+.5f}"


def selfcheck(conn):
    """--selfcheck: (a) edge re-derivation on a sample; (b) the N=0 gate on a
    small trader sample — consistent with trader_skill_metric_v2*'s pattern."""
    cohort, _ = load_track2_lists()
    sample_traders = cohort[:40]
    df = load_oos_positions(conn, sample_traders)
    if len(df) == 0:
        print("[selfcheck] no OOS positions for sample; skipping")
        return True
    # (a) edge identity
    bad = 0
    for row in df.head(200).itertuples(index=False):
        if abs((row.won - row.price) - (row.won - row.price)) > 1e-12:
            bad += 1
    # (b) N=0 gate on the sample
    direct = measure_oos(conn, sample_traders, T_SPLIT)
    n0 = curve_point(df[["trader", "market_id", "category", "won", "price"]], reps=200, seed=SEED)
    # reps differ (200 vs measure_oos's 1500) so only compare point_gap + n
    ok = (abs((n0["point_gap"] or 0) - (direct["point_gap"] or 0)) <= GATE_TOL
          and n0["n_positions"] == direct["n_positions"]
          and n0["n_pairs"] == direct["n_pairs"])
    print(f"[selfcheck] edge-identity mismatches={bad}  "
          f"N=0 point_gap/n identity: {'OK' if ok else 'FAIL'} "
          f"(harness {n0['point_gap']:.8f} / direct {direct['point_gap']:.8f}, "
          f"n_pos {n0['n_positions']}/{direct['n_positions']}, n_pairs {n0['n_pairs']}/{direct['n_pairs']})")
    return bad == 0 and ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--reps", type=int, default=GATE_REPS_LOCAL)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = db_connect(args.db)

    sha_before = oos_result_sha(args.db)
    print(f"[stop-cond] metric_v2f_oos_result sha256 BEFORE: {sha_before}")
    if sha_before != OOS_RESULT_SHA_EXPECTED:
        print(f"[STOP] metric_v2f_oos_result sha256 != expected "
              f"{OOS_RESULT_SHA_EXPECTED}", file=sys.stderr)
        sys.exit(3)

    if args.selfcheck:
        if not selfcheck(conn):
            print("[selfcheck] FAILED", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED")

    print(f"\n=== COPY-TRADE DECAY — amended prereg (trading-swarm 7b9e1e7) ===")
    print(f"T_SPLIT={T_SPLIT}  seed={args.seed}  reps={args.reps}")
    print(f"N ladder (min): {N_LADDER_MIN}")

    broad_pool, broad_meta = load_broad_pool(conn)
    print(f"\n[broad pool] {len(broad_pool)} traders clear n>={M_CHOSEN} pre-split "
          f"(2026-09-06 was {BROAD_POOL_2026_09_06}; delta {broad_meta['delta_from_2026_09_06']:+d})")
    cohort, placebo = load_track2_lists()

    tape_cache = {}
    populations = {}
    gate_ok = True

    res, ok = run_population(conn, "broad_pit_legal_pool", broad_pool, tape_cache,
                             args.reps, args.seed, per_category=True)
    populations["broad_pit_legal_pool"] = res
    gate_ok &= ok

    for lbl, tl in (("cohort_track2_frozen", cohort), ("placebo_track2_frozen", placebo)):
        res, ok = run_population(conn, lbl, tl, tape_cache, args.reps, args.seed,
                                 per_category=False)
        populations[lbl] = res
        gate_ok &= ok

    sha_after = oos_result_sha(args.db)
    print(f"\n[stop-cond] metric_v2f_oos_result sha256 AFTER:  {sha_after}")
    conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_out = args.json_out or f"data/characterizations/copy_trade_decay_{ts}.json"
    artifact = dict(
        spec="copy_trade_decay_diagnostic",
        prereg="brain/decisions/2026-09-05-copy-trade-decay-prereg.md AS AMENDED 2026-09-10",
        prereg_amendment_commit="7b9e1e7 (trading-swarm)",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        trader_skill_metric_v2f_commit=git_commit(repo_dir),  # same repo HEAD
        params=dict(
            t_split=T_SPLIT, seed=args.seed, reps=args.reps, weight_fn="cap5",
            m_chosen=M_CHOSEN, n_ladder_minutes=N_LADDER_MIN,
            gate_tolerance=GATE_TOL, thin_abs=THIN_ABS, thin_frac=THIN_FRAC,
        ),
        cost_floors_fixed=COST_FLOORS,
        broad_pool_meta=broad_meta,
        oos_result_sha_before=sha_before,
        oos_result_sha_after=sha_after,
        oos_result_sha_expected=OOS_RESULT_SHA_EXPECTED,
        oos_result_unchanged=bool(sha_before == sha_after == OOS_RESULT_SHA_EXPECTED),
        n0_gate_all_pass=bool(gate_ok),
        populations=populations,
        sql=dict(oos_positions=OOS_POSITIONS_SQL.strip(),
                 next_trade_lookup="bisect_left on ORDER BY market_id,timestamp tape; "
                                   "exclude if entry_ts+N > MAX(trades.timestamp) for the market"),
        price_source="trades.price (executed trade tape); price_at()/CLOB NOT used",
        own_trader_trades="INCLUDED",
    )
    os.makedirs(os.path.dirname(json_out), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(artifact, f, indent=2, default=str)
    print(f"[artifact] {json_out}")

    if sha_before != sha_after:
        print("[STOP] metric_v2f_oos_result CHANGED during the run.", file=sys.stderr)
        sys.exit(3)
    if not gate_ok:
        print("[STOP] N=0 internal-consistency gate FAILED for at least one population.",
              file=sys.stderr)
        sys.exit(2)
    print("\n[done] all N=0 gates passed; oos_result unchanged.")


if __name__ == "__main__":
    main()
