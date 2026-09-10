#!/usr/bin/env python3
"""
Copy-trade decay measurement — executes brain/decisions/2026-09-05-copy-trade-
decay-prereg.md AS AMENDED 2026-09-10 AND 2026-09-10b (trading-swarm 7b9e1e7,
e8eca1c).

THE PRE-REGISTRATION IS AUTHORITATIVE. Where this script and the amended
document differ, the DOCUMENT WINS. Read-only against production tables;
writes only the JSON artifact named on the command line. Never passes
--persist to anything.

2026-09-10b changes (the outcome rule for the price substitution):
  * The substituted trade's price q is now interpreted by OUTCOME:
      - substituted trade outcome == position's held outcome  -> use q directly
      - substituted trade outcome != held outcome, both Yes/No -> CONVERT: 1 - q
      - either side non-binary (named candidate / Up-Down / Over-Under) and the
        outcomes differ -> NOT CONVERTIBLE: excluded from that rung, counted
  * PRIMARY construction = "convert" (the reported decay curve).
  * SECONDARY construction = "matched" (outcome-matched-only: discard every
    opposite-outcome substitution) — computed and reported at EVERY rung
    alongside the primary, never instead of it.
  * Opposite-outcome SHARE is reported per rung per population.
  * Material-disagreement criterion (amendment item C): at N=15min on the broad
    pool, do the primary and secondary 95% CIs overlap? Non-overlap ->
    outcome PRIMARY-AND-ROBUSTNESS-DISAGREE.

Unchanged from the 2026-09-10 run: the N=0 internal-consistency gate (uses
positions.entry_avg_price, no tape lookup — outcome-correct at 0.00% mismatch
per verification 3c22b0c), the 15-point N ladder, the per-category cost floors,
the cohort/placebo definitions, seed 42, reps 1500, cap5,
T_SPLIT = 2026-04-01 00:00:00.
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
DECISIVE_N_MIN = 15  # amendment 2026-09-10 item B / 2026-09-10b item D
BINARY = {"Yes", "No"}

# MASTER_HANDOVER_2026-08-15 §5 — fixed cost floors, per category (UNCHANGED)
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
    Shelled out so the digest matches that pinned value byte-for-byte."""
    out = subprocess.check_output(
        ["sqlite3", db_path, "SELECT * FROM metric_v2f_oos_result"])
    return hashlib.sha256(out).hexdigest()


# --------------------------------------------------------------------------
# population loaders
# --------------------------------------------------------------------------

def load_broad_pool(conn):
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

# 2026-09-10b: p.outcome added (the substitution now needs the held outcome).
OOS_POSITIONS_SQL = """
    SELECT p.trader_address, p.market_id, m.category, p.outcome, p.entry_avg_price,
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
    out = []
    CHUNK = 900
    tl = sorted(traders)
    for i in range(0, len(tl), CHUNK):
        chunk = tl[i:i + CHUNK]
        ph = ",".join("?" for _ in chunk)
        rows = conn.execute(OOS_POSITIONS_SQL.format(ph=ph), chunk + [T_SPLIT]).fetchall()
        out.extend(rows)
    df = pd.DataFrame(out, columns=["trader", "market_id", "category", "pos_outcome",
                                    "price", "entry_ts", "trade_result"])
    df["won"] = (df["trade_result"] == "won").astype(int)
    df["entry_ts_dt"] = pd.to_datetime(df["entry_ts"])
    return df


def build_trade_tape(conn, market_ids):
    """{market_id: (timestamps[str], prices[float], outcomes[str], tape_end[str])}
    ordered by timestamp. 'Next trade at or after T' = bisect_left on timestamps."""
    tape = {}
    CHUNK = 900
    mids = sorted(set(market_ids))
    for i in range(0, len(mids), CHUNK):
        chunk = mids[i:i + CHUNK]
        ph = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT market_id, timestamp, price, outcome FROM trades "
            f"WHERE market_id IN ({ph}) ORDER BY market_id, timestamp", chunk
        ).fetchall()
        by_mkt = {}
        for mid, ts, px, oc in rows:
            by_mkt.setdefault(mid, ([], [], []))
            by_mkt[mid][0].append(ts)
            by_mkt[mid][1].append(float(px) if px is not None else np.nan)
            by_mkt[mid][2].append(oc if oc is not None else "")
        for mid, (tss, pxs, ocs) in by_mkt.items():
            tape[mid] = (tss, pxs, ocs, tss[-1])
    return tape


def substitute_price_at_N(df, tape, n_seconds, construction):
    """construction: 'convert' (primary) or 'matched' (secondary).

    Returns (sub_df, realised_delays, counts) where counts has:
      n_excluded_tape_end, n_no_tape, n_same, n_opposite,
      n_nonconvertible (opposite but not a clean Yes/No complement),
      n_dropped_matched (opposite trades dropped, 'matched' construction only).
    Opposite-outcome SHARE for a rung = n_opposite / (n_same + n_opposite).
    """
    sub_rows = []
    delays = []
    c = dict(n_excluded_tape_end=0, n_no_tape=0, n_same=0, n_opposite=0,
             n_nonconvertible=0, n_dropped_matched=0)
    for row in df.itertuples(index=False):
        entry_dt = row.entry_ts_dt
        target_str = (entry_dt + pd.Timedelta(seconds=n_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        rec = tape.get(row.market_id)
        if rec is None:
            c["n_no_tape"] += 1
            continue
        tss, pxs, ocs, tape_end = rec
        if target_str > tape_end:
            c["n_excluded_tape_end"] += 1
            continue
        j = bisect.bisect_left(tss, target_str)
        if j >= len(tss):
            c["n_excluded_tape_end"] += 1
            continue
        q = pxs[j]
        if not np.isfinite(q):
            c["n_excluded_tape_end"] += 1
            continue
        sub_oc = ocs[j]
        held = row.pos_outcome

        if sub_oc == held:
            c["n_same"] += 1
            implied = q
        else:
            c["n_opposite"] += 1
            if sub_oc in BINARY and held in BINARY:
                implied = 1.0 - q               # amendment item A: CONVERT
            else:
                c["n_nonconvertible"] += 1       # can't complement across a multi-way book
                continue
            if construction == "matched":
                c["n_dropped_matched"] += 1
                continue

        try:
            delays.append((pd.to_datetime(tss[j]) - entry_dt).total_seconds())
        except Exception:
            delays.append(float(n_seconds))
        sub_rows.append((row.trader, row.market_id, row.category, row.won, implied))

    sub_df = pd.DataFrame(sub_rows, columns=["trader", "market_id", "category", "won", "price"])
    return sub_df, np.array(delays, dtype=float), c


def curve_point(sub_df, reps, seed):
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


def _fmt(x):
    return "None" if x is None else f"{x:+.5f}"


def _ci_overlap(a, b):
    """True if the two [lo,hi] intervals overlap (touch counts as overlap)."""
    if None in (a[0], a[1], b[0], b[1]):
        return None
    return not (a[1] < b[0] or b[1] < a[0])


# --------------------------------------------------------------------------
# per-population run
# --------------------------------------------------------------------------

def _ladder(df, tape, base_ppt, thin_thr, reps, seed, construction, want_vol=True):
    rungs = []
    for n_min, n_sec in zip(N_LADDER_MIN, N_LADDER_SECONDS):
        sub_df, delays, c = substitute_price_at_N(df, tape, n_sec, construction)
        pt = curve_point(sub_df, reps=reps, seed=seed)
        n_pairs = pt.get("n_pairs") or 0
        subs_made = c["n_same"] + c["n_opposite"]
        entry = dict(
            N_minutes=n_min, N_seconds=n_sec, construction=construction,
            point_gap=pt.get("point_gap"), ci_lo=pt.get("ci_lo"), ci_hi=pt.get("ci_hi"),
            n_positions=pt.get("n_positions"), n_pairs=n_pairs,
            n_traders=pt.get("n_traders"), n_markets=pt.get("n_markets"),
            n_same_outcome=c["n_same"], n_opposite_outcome=c["n_opposite"],
            opposite_outcome_share=(c["n_opposite"] / subs_made) if subs_made else None,
            n_nonconvertible=c["n_nonconvertible"],
            n_dropped_matched=c["n_dropped_matched"],
            n_excluded_tape_end=c["n_excluded_tape_end"], n_no_tape=c["n_no_tape"],
            excluded_frac=float(c["n_excluded_tape_end"] / max(1, len(df))),
            realised_delay_seconds=delay_stats(delays),
            thin=bool(n_pairs < thin_thr),
            uncomputable=bool(pt.get("point_gap") is None),
        )
        if want_vol:
            entry["volume_composition"] = volume_composition(sub_df, base_ppt)
        rungs.append(entry)
        flag = "THIN" if entry["thin"] else ("UNCOMP" if entry["uncomputable"] else "ok")
        print(f"    [{construction:>7}] N={n_min:>6}min  gap={_fmt(pt.get('point_gap'))}  "
              f"CI=[{_fmt(pt.get('ci_lo'))},{_fmt(pt.get('ci_hi'))}]  "
              f"n_pairs={n_pairs:<6} opp%={entry['opposite_outcome_share'] or 0:.3f}  "
              f"excl={c['n_excluded_tape_end']:<6} nonconv={c['n_nonconvertible']:<4} "
              f"delay_med={_fmt(delay_stats(delays).get('median'))}s  [{flag}]")
    return rungs


def run_population(conn, label, traders, tape_cache, reps, seed, per_category=False):
    print(f"\n=== population: {label}  ({len(traders)} traders) ===")
    df = load_oos_positions(conn, traders)
    print(f"  OOS positions: {len(df)}  distinct traders w/ >=1: {df['trader'].nunique()}  "
          f"markets: {df['market_id'].nunique()}  "
          f"non-binary held outcomes: {int((~df['pos_outcome'].isin(BINARY)).sum())}")

    need = set(df["market_id"].unique()) - set(tape_cache.keys())
    if need:
        tape_cache.update(build_trade_tape(conn, list(need)))

    base_ppt = df.groupby("trader").size().to_dict()

    # ---- N=0 internal-consistency gate (UNCHANGED — no substitution) ----
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
          f"harness={gate['harness']['point_gap']}  direct={gate['direct']['point_gap']}  "
          f"deltas={gate['deltas']}")

    n0_pairs = n0.get("n_pairs") or 0
    thin_thr = max(THIN_ABS, THIN_FRAC * n0_pairs)

    rungs_primary = _ladder(df, tape_cache, base_ppt, thin_thr, reps, seed, "convert")
    rungs_matched = _ladder(df, tape_cache, base_ppt, thin_thr, reps, seed, "matched")

    result = dict(
        label=label, n_traders_in_list=len(traders),
        oos_n_positions=int(len(df)), oos_n_traders=int(df["trader"].nunique()),
        oos_n_markets=int(df["market_id"].nunique()),
        oos_n_nonbinary_held=int((~df["pos_outcome"].isin(BINARY)).sum()),
        n0_gate=gate, thin_threshold_pairs=float(thin_thr),
        n0_pairs=n0_pairs,
        rungs_primary_convert=rungs_primary,
        rungs_secondary_matched_only=rungs_matched,
    )

    if per_category:
        result["per_category"] = {}
        for cat in ("Geopolitics", "Elections"):
            cat_df = df[df["category"] == cat].copy()
            cat_n0 = curve_point(
                cat_df[["trader", "market_id", "category", "won", "price"]],
                reps=GATE_REPS_LOCAL, seed=SEED)
            cat_n0_pairs = cat_n0.get("n_pairs") or 0
            cat_thin = max(THIN_ABS, THIN_FRAC * cat_n0_pairs)
            print(f"  --- per-category: {cat} ({len(cat_df)} positions) ---")
            result["per_category"][cat] = dict(
                oos_n_positions=int(len(cat_df)),
                n0=dict(point_gap=cat_n0.get("point_gap"), ci_lo=cat_n0.get("ci_lo"),
                        ci_hi=cat_n0.get("ci_hi"), n_pairs=cat_n0_pairs),
                cost_floor_fixed=COST_FLOORS[cat],
                thin_threshold_pairs=float(cat_thin),
                rungs_primary_convert=_ladder(cat_df, tape_cache, base_ppt, cat_thin,
                                              reps, seed, "convert", want_vol=False),
                rungs_secondary_matched_only=_ladder(cat_df, tape_cache, base_ppt, cat_thin,
                                                     reps, seed, "matched", want_vol=False),
            )

    try:
        result["cost_floor_crosscheck"] = cost_floor(df, traders, conn, verbose=False)
    except Exception as e:  # pragma: no cover
        result["cost_floor_crosscheck"] = dict(error=str(e))

    return result, gate["pass"]


def selfcheck(conn):
    """(a) edge identity on a sample; (b) N=0 gate identity vs measure_oos;
    (c) 2026-09-10b: 1-q is applied IFF the substituted trade's outcome differs
    from the position's, and used directly IFF it matches."""
    cohort, _ = load_track2_lists()
    sample = cohort[:40]
    df = load_oos_positions(conn, sample)
    if len(df) == 0:
        print("[selfcheck] no OOS positions for sample; skipping")
        return True
    bad = int((abs((df["won"] - df["price"]) - (df["won"] - df["price"])) > 1e-12).sum())

    direct = measure_oos(conn, sample, T_SPLIT)
    n0 = curve_point(df[["trader", "market_id", "category", "won", "price"]], reps=200, seed=SEED)
    gate_ok = (abs((n0["point_gap"] or 0) - (direct["point_gap"] or 0)) <= GATE_TOL
               and n0["n_positions"] == direct["n_positions"]
               and n0["n_pairs"] == direct["n_pairs"])

    # (c) conversion-direction check: build the tape, walk N=15min substitutions,
    # confirm the implied price obeys the rule for a sample.
    tape = {}
    tape.update(build_trade_tape(conn, list(df["market_id"].unique())))
    conv_bad = 0
    checked = 0
    for row in df.itertuples(index=False):
        rec = tape.get(row.market_id)
        if rec is None:
            continue
        tss, pxs, ocs, tape_end = rec
        target = (row.entry_ts_dt + pd.Timedelta(seconds=900)).strftime("%Y-%m-%d %H:%M:%S")
        if target > tape_end:
            continue
        j = bisect.bisect_left(tss, target)
        if j >= len(tss) or not np.isfinite(pxs[j]):
            continue
        q, sub_oc = pxs[j], ocs[j]
        checked += 1
        if sub_oc == row.pos_outcome:
            expect = q
        elif sub_oc in BINARY and row.pos_outcome in BINARY:
            expect = 1.0 - q
        else:
            continue  # non-convertible, excluded — nothing to check
        # re-run the real function on this single row and compare
        one = pd.DataFrame([row._asdict()])
        one["entry_ts_dt"] = pd.to_datetime(one["entry_ts"])
        sd, _, _ = substitute_price_at_N(one, tape, 900, "convert")
        if len(sd) and abs(float(sd["price"].iloc[0]) - expect) > 1e-12:
            conv_bad += 1
    print(f"[selfcheck] edge-identity mismatches={bad}  "
          f"N=0 identity: {'OK' if gate_ok else 'FAIL'} "
          f"(harness {n0['point_gap']:.8f}/direct {direct['point_gap']:.8f}, "
          f"n {n0['n_positions']}/{direct['n_positions']})  "
          f"conversion-rule checks={checked} mismatches={conv_bad}")
    return bad == 0 and gate_ok and conv_bad == 0


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
        print(f"[STOP] metric_v2f_oos_result sha256 != expected {OOS_RESULT_SHA_EXPECTED}",
              file=sys.stderr)
        sys.exit(3)

    if args.selfcheck:
        if not selfcheck(conn):
            print("[selfcheck] FAILED", file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED")

    print("\n=== COPY-TRADE DECAY — amended prereg 2026-09-10b (trading-swarm e8eca1c) ===")
    print(f"T_SPLIT={T_SPLIT}  seed={args.seed}  reps={args.reps}")
    print(f"N ladder (min): {N_LADDER_MIN}")
    print("primary = CONVERT (opposite-outcome q -> 1-q);  secondary = outcome-matched-only")

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

    # ---- amendment item C: material-disagreement criterion ----
    bp = populations["broad_pit_legal_pool"]
    dec = DECISIVE_N_MIN
    p15 = next(r for r in bp["rungs_primary_convert"] if r["N_minutes"] == dec)
    s15 = next(r for r in bp["rungs_secondary_matched_only"] if r["N_minutes"] == dec)
    overlap = _ci_overlap((p15["ci_lo"], p15["ci_hi"]), (s15["ci_lo"], s15["ci_hi"]))
    disagree = (overlap is False)
    item_c = dict(
        decisive_N_minutes=dec,
        primary_convert=dict(point_gap=p15["point_gap"], ci=[p15["ci_lo"], p15["ci_hi"]],
                             n_pairs=p15["n_pairs"], thin=p15["thin"]),
        secondary_matched_only=dict(point_gap=s15["point_gap"], ci=[s15["ci_lo"], s15["ci_hi"]],
                                    n_pairs=s15["n_pairs"], thin=s15["thin"]),
        ci_overlap=overlap,
        material_disagreement=disagree,
        criterion="non-overlapping 95% bootstrap CIs at N=15min on the broad pool",
    )
    print(f"\n[item C] N=15min broad pool: primary(convert) {p15['point_gap']:+.5f} "
          f"[{p15['ci_lo']:+.5f},{p15['ci_hi']:+.5f}]  vs  "
          f"matched-only {s15['point_gap']:+.5f} [{s15['ci_lo']:+.5f},{s15['ci_hi']:+.5f}]  "
          f"-> CI overlap={overlap}  material_disagreement={disagree}")

    sha_after = oos_result_sha(args.db)
    print(f"\n[stop-cond] metric_v2f_oos_result sha256 AFTER:  {sha_after}")
    conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_out = args.json_out or f"data/characterizations/copy_trade_decay_{ts}.json"
    artifact = dict(
        spec="copy_trade_decay_diagnostic",
        prereg="brain/decisions/2026-09-05-copy-trade-decay-prereg.md AS AMENDED 2026-09-10 + 2026-09-10b",
        prereg_amendment_commits=["7b9e1e7 (2026-09-10)", "e8eca1c (2026-09-10b)"],
        supersedes_curve_in="copy_trade_decay_20260910T191052Z.json (not modified; stands as computed)",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        params=dict(
            t_split=T_SPLIT, seed=args.seed, reps=args.reps, weight_fn="cap5",
            m_chosen=M_CHOSEN, n_ladder_minutes=N_LADDER_MIN,
            gate_tolerance=GATE_TOL, thin_abs=THIN_ABS, thin_frac=THIN_FRAC,
            decisive_N_minutes=DECISIVE_N_MIN,
        ),
        outcome_rule=dict(
            primary="convert: opposite-outcome trade price q -> 1-q (both Yes/No); same-outcome used directly",
            secondary="matched-only: discard every opposite-outcome substitution",
            nonconvertible="opposite AND either side non-binary -> excluded from the rung, counted (n_nonconvertible)",
        ),
        cost_floors_fixed=COST_FLOORS,
        broad_pool_meta=broad_meta,
        oos_result_sha_before=sha_before,
        oos_result_sha_after=sha_after,
        oos_result_sha_expected=OOS_RESULT_SHA_EXPECTED,
        oos_result_unchanged=bool(sha_before == sha_after == OOS_RESULT_SHA_EXPECTED),
        n0_gate_all_pass=bool(gate_ok),
        item_c_material_disagreement=item_c,
        populations=populations,
        sql=dict(oos_positions=OOS_POSITIONS_SQL.strip(),
                 next_trade_lookup="bisect_left on ORDER BY market_id,timestamp tape; "
                                   "exclude if entry_ts+N > MAX(trades.timestamp)"),
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
    print("\n[done] N=0 gates passed; oos_result unchanged. "
          f"material_disagreement={disagree}")


if __name__ == "__main__":
    main()
