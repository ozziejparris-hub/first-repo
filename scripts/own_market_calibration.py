#!/usr/bin/env python3
"""
Own-market calibration, and where this project's traders sit in it.

PREMISE TEST. Read-only. No selector, no cohort, no placebo. Never passes
--persist; writes only the JSON artifact named on the command line.

Every prior project measurement is ENTRY-WEIGHTED (edge = won - entry_price over
positions actually taken). This is PRICE-WEIGHTED: across all markets at price p
(at a fixed lead time before the market stopped trading), what fraction resolve
YES. Different quantity.

PART 1 — calibration of the canonical population's own markets
  Population: all resolved, gap-clean Geopolitics/Elections markets
  (monitoring.column_definitions.backtest_window_sql, tape_end-anchored),
  restricted to binary winning_outcome in ('Yes','No').
  Price: the trade-tape price of the LAST trade at or before (tape_end - h),
  for a fixed ladder of lead times h, normalised to P(Yes)
  (p_yes = price if the trade's outcome is 'Yes' else 1 - price). See
  PRICE_DEFINITION below for the justification and the ambiguity it resolves.
  Curves: realised YES rate per price decile, with a two-way clustered
  bootstrap CI (clustered on event_cluster_labels.cluster_id AND on market).
  Also: a logistic recalibration slope per lead-time stratum (y ~ sigmoid(b0
  + b1*logit(p_yes))), comparable to arXiv 2602.19520's 0.99 -> 1.32; and
  everything split per category (Geopolitics vs Elections).
  Deviations reported in EDGE units (realised rate - p_yes) so they compare
  directly to the cost floors (geo 0.0005-0.010, elec 0.0056-0.020).

PART 2 — overlay OOS entry density on the Part 1 grid.

PART 3 — GATED. Only runs if a Part 1 deviation's CI excludes the relevant
  cost floor in >=1 cell. Conditions calibration on directionally-skilled-
  trader PRESENCE (a conditioning variable on mispricing, NOT a copy signal
  -- the 2026-09-10 copy-decay result stands: there is no edge to inherit
  from a trader's entry; this asks only whether their presence MARKS a
  mispriced market, which is actionable at one's own entry price).

Seed 42, reps 1500. T_SPLIT = 2026-04-01 00:00:00.
"""
import argparse
import bisect
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, GATE_REPS_LOCAL
from monitoring.column_definitions import backtest_window_sql

VERY_EARLY = "2000-01-01 00:00:00"
REPS = GATE_REPS_LOCAL  # 1500
EPS = 0.01  # logit clip

# --- fixed bucket boundaries (justified in the decision doc from the data's
#     own tape-duration distribution: p25 tape ~16h, median ~6d, p75 ~31d,
#     p90 ~88d; 14.9% of markets never reach 1h) --------------------------
PRICE_BUCKETS = [round(x / 10, 1) for x in range(0, 10)]        # deciles
HORIZONS_HOURS = [0.5, 3.0, 12.0, 72.0, 336.0, 1080.0]          # ~0.5h,3h,12h,3d,14d,45d
HORIZON_LABELS = ["h0.5h", "h3h", "h12h", "h3d", "h14d", "h45d"]
# TTR-at-entry bands for Part 2, each bracketing one horizon above
TTR_BANDS = [(0.0, 1.0), (1.0, 6.0), (6.0, 24.0), (24.0, 168.0), (168.0, 720.0), (720.0, 1e12)]
TTR_BAND_LABELS = ["0-1h", "1-6h", "6-24h", "1-7d", "7-30d", ">30d"]

COST_FLOORS = {
    "Geopolitics": {"lo": 0.0005, "hi": 0.010},
    "Elections":   {"lo": 0.0056, "hi": 0.020},
}

OOS_RESULT_SHA_EXPECTED = "021be40a87df48c1f37efb8265f223b005c9c50bca8e32ee1bcb134fe074cd4e"

PRICE_DEFINITION = (
    "The trade-tape price of the LAST trade at or before (tape_end - h), for "
    "each lead time h in HORIZONS_HOURS, normalised to P(Yes) = price if the "
    "trade's outcome=='Yes' else 1-price. Chosen over (a) a fixed lead time "
    "before resolution_date -- resolution_date has ~11% impossible values "
    "(O-36); tape_end is 100%-coverage, zero negative-lag; and over (b) a "
    "volume-weighted window average -- median market has only 8 trades, so a "
    "window is mostly one price anyway and a VWAP would silently weight by an "
    "endogenous quantity. 'The market's price' is not one number for a market "
    "that traded for weeks: this fixes it as the last observable price at a "
    "stated lead time, which is exactly what a calibration-at-lead-time h "
    "measurement needs. A market contributes to horizon h iff it was trading "
    "at (tape_end - h), i.e. tape duration >= h."
)


def git_commit(repo_dir):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def oos_result_sha(db_path):
    out = subprocess.check_output(["sqlite3", db_path, "SELECT * FROM metric_v2f_oos_result"])
    return hashlib.sha256(out).hexdigest()


def _ts(s):
    return s.replace("T", " ")[:19]


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_population(conn):
    sql = backtest_window_sql(VERY_EARLY)
    rows = conn.execute(sql, {"window_start": VERY_EARLY}).fetchall()
    # market_id, title, condition_id, resolution_date, tape_end
    pop = {}
    for mid, title, cond, resdate, tape_end in rows:
        pop[mid] = dict(market_id=mid, tape_end=_ts(tape_end))
    # attach category + winning_outcome
    CH = 900
    mids = list(pop)
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, cat, wo in conn.execute(
            f"SELECT market_id, category, winning_outcome FROM markets WHERE market_id IN ({ph})", chunk):
            pop[mid]["category"] = cat
            pop[mid]["winning_outcome"] = wo
    n_all = len(pop)
    nonbinary = [m for m, d in pop.items() if d.get("winning_outcome") not in ("Yes", "No")]
    for m in nonbinary:
        del pop[m]
    for d in pop.values():
        d["y"] = 1 if d["winning_outcome"] == "Yes" else 0
    return pop, dict(n_canonical=n_all, n_nonbinary_excluded=len(nonbinary), n_used=len(pop))


def load_event_clusters(conn, market_ids):
    cl = {}
    CH = 900
    mids = sorted(market_ids)
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, cid in conn.execute(
            f"SELECT market_id, cluster_id FROM event_cluster_labels WHERE market_id IN ({ph})", chunk):
            cl[mid] = cid
    out = {}
    n_labelled = 0
    for mid in market_ids:
        if mid in cl:
            out[mid] = cl[mid]; n_labelled += 1
        else:
            out[mid] = f"solo::{mid}"
    return out, dict(n_labelled=n_labelled, n_solo=len(market_ids) - n_labelled)


def load_tape(conn, market_ids):
    tape = {}
    CH = 900
    mids = sorted(market_ids)
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, ts, px, oc in conn.execute(
            f"SELECT market_id, timestamp, price, outcome FROM trades WHERE market_id IN ({ph}) "
            f"ORDER BY market_id, timestamp", chunk):
            d = tape.setdefault(mid, ([], [], []))
            d[0].append(_ts(ts))
            d[1].append(float(px) if px is not None else np.nan)
            d[2].append(oc if oc is not None else "")
    return tape


def _hours_before(tape_end_str, hours):
    end = datetime.strptime(tape_end_str, "%Y-%m-%d %H:%M:%S")
    return (end - pd.Timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# clustered bootstrap (two-way: event cluster + market)
# --------------------------------------------------------------------------

def _bucket(p):
    if p is None or not np.isfinite(p):
        return None
    b = int(min(max(p, 0.0), 0.999999) * 10)
    return min(b, 9)


def clustered_rate_ci(df, reps, seed, statfn):
    """df has columns y, p_yes, ec (event cluster id), mkt (market id).
    Returns statfn(df) point + [lo,hi] via two-way multiplier bootstrap on
    (ec, mkt). statfn(df_or_weighted) must accept (y, p, w)."""
    y = df["y"].to_numpy().astype(float)
    p = df["p_yes"].to_numpy().astype(float)
    ec = df["ec"].astype("category")
    mk = df["mkt"].astype("category")
    ec_idx = ec.cat.codes.to_numpy()
    mk_idx = mk.cat.codes.to_numpy()
    n_ec = ec.cat.categories.size
    n_mk = mk.cat.categories.size
    point = statfn(y, p, np.ones_like(y))
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(reps):
        em = np.bincount(rng.integers(0, n_ec, n_ec), minlength=n_ec)
        mm = np.bincount(rng.integers(0, n_mk, n_mk), minlength=n_mk)
        w = em[ec_idx] * mm[mk_idx]
        if w.sum() <= 0:
            continue
        v = statfn(y, p, w.astype(float))
        if v is not None and np.isfinite(v):
            boot.append(v)
    boot = np.array(boot)
    if len(boot) < reps * 0.5:
        return point, None, None, len(boot)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return point, float(lo), float(hi), len(boot)


def _wrate(y, p, w):
    d = w.sum()
    return (w * y).sum() / d if d > 0 else None


def _wedge(y, p, w):
    d = w.sum()
    if d <= 0:
        return None
    return (w * y).sum() / d - (w * p).sum() / d


def _logit(x):
    x = np.clip(x, EPS, 1 - EPS)
    return np.log(x / (1 - x))


def _fit_logistic_slope(y, p, w):
    """Weighted MLE of b1 in  P(y=1) = sigmoid(b0 + b1 * logit(p)), by IRLS
    (Newton-Raphson, 2 params). Returns b1 or None (degenerate)."""
    ys = float((w * y).sum())
    ns = float(w.sum())
    if len(y) < 20 or ys <= 1 or (ns - ys) <= 1:
        return None
    x = _logit(p)
    if np.ptp(x) < 1e-6:
        return None
    X = np.column_stack([np.ones_like(x), x])
    b = np.array([0.0, 1.0])
    for _ in range(50):
        z = X @ b
        mu = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        s = np.clip(mu * (1.0 - mu), 1e-9, None)
        W = w * s
        grad = X.T @ (w * (y - mu))
        H = X.T @ (X * W[:, None])
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            return None
        b = b + step
        if not np.all(np.isfinite(b)):
            return None
        if np.max(np.abs(step)) < 1e-7:
            break
    b1 = float(b[1])
    if not np.isfinite(b1) or abs(b1) > 50:
        return None
    return b1


def slope_ci(df, reps, seed):
    y = df["y"].to_numpy().astype(float)
    p = df["p_yes"].to_numpy().astype(float)
    ec = df["ec"].astype("category"); mk = df["mkt"].astype("category")
    ec_idx = ec.cat.codes.to_numpy(); mk_idx = mk.cat.codes.to_numpy()
    n_ec = ec.cat.categories.size; n_mk = mk.cat.categories.size
    point = _fit_logistic_slope(y, p, np.ones_like(y))
    rng = np.random.default_rng(seed)
    boot = []
    ndeg = 0
    for _ in range(reps):
        em = np.bincount(rng.integers(0, n_ec, n_ec), minlength=n_ec)
        mm = np.bincount(rng.integers(0, n_mk, n_mk), minlength=n_mk)
        w = (em[ec_idx] * mm[mk_idx]).astype(float)
        b1 = _fit_logistic_slope(y, p, w)
        if b1 is None:
            ndeg += 1
            continue
        boot.append(b1)
    boot = np.array(boot)
    if len(boot) < reps * 0.5:
        return point, None, None, len(boot), ndeg
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return point, float(lo), float(hi), len(boot), ndeg


# --------------------------------------------------------------------------
# Part 1
# --------------------------------------------------------------------------

def snapshot_rows(pop, clusters, tape, hours):
    rows = []
    n_not_trading = 0
    n_bad_outcome = 0
    for mid, d in pop.items():
        rec = tape.get(mid)
        if rec is None:
            n_not_trading += 1
            continue
        tss, pxs, ocs = rec
        target = _hours_before(d["tape_end"], hours)
        j = bisect.bisect_right(tss, target) - 1
        if j < 0:
            n_not_trading += 1
            continue
        q = pxs[j]
        oc = ocs[j]
        if not np.isfinite(q):
            n_not_trading += 1
            continue
        if oc == "Yes":
            p_yes = q
        elif oc == "No":
            p_yes = 1.0 - q
        else:
            n_bad_outcome += 1
            continue
        rows.append(dict(mkt=mid, ec=clusters[mid], category=d["category"],
                         p_yes=float(min(max(p_yes, 0.0), 1.0)), y=d["y"]))
    return pd.DataFrame(rows), dict(n_not_trading=n_not_trading, n_bad_outcome=n_bad_outcome)


def calib_curve(df, reps, seed):
    out = []
    for b, lo in enumerate(PRICE_BUCKETS):
        sub = df[(df["p_yes"] >= lo) & (df["p_yes"] < lo + 0.1)]
        if b == 9:
            sub = df[(df["p_yes"] >= 0.9)]
        if len(sub) == 0:
            out.append(dict(bucket=b, price_lo=lo, price_hi=round(lo + 0.1, 1), n=0))
            continue
        rate, r_lo, r_hi, r_nb = clustered_rate_ci(sub, reps, seed + b, _wrate)
        edge, e_lo, e_hi, e_nb = clustered_rate_ci(sub, reps, seed + b, _wedge)
        out.append(dict(
            bucket=b, price_lo=lo, price_hi=round(lo + 0.1, 1),
            n=int(len(sub)), n_ec=int(sub["ec"].nunique()),
            p_yes_mean=float(sub["p_yes"].mean()),
            realised_yes_rate=float(rate), rate_ci=[r_lo, r_hi],
            deviation_edge=float(edge), deviation_ci=[e_lo, e_hi],
            thin=bool(len(sub) < 30),
        ))
    return out


def part1_stratum(df, reps, seed, floors):
    res = dict(n=int(len(df)), n_ec=int(df["ec"].nunique()))
    res["pooled_curve"] = calib_curve(df, reps, seed)
    s, slo, shi, snb, sdeg = slope_ci(df, reps, seed + 777)
    res["logit_slope_pooled"] = dict(slope=s, ci=[slo, shi], n_boot=snb, n_degenerate=sdeg)
    res["per_category"] = {}
    for cat in ("Geopolitics", "Elections"):
        cd = df[df["category"] == cat]
        if len(cd) == 0:
            res["per_category"][cat] = dict(n=0)
            continue
        cs, cslo, cshi, csnb, csdeg = slope_ci(cd, reps, seed + 888)
        res["per_category"][cat] = dict(
            n=int(len(cd)), n_ec=int(cd["ec"].nunique()),
            curve=calib_curve(cd, reps, seed + 100),
            logit_slope=dict(slope=cs, ci=[cslo, cshi], n_boot=csnb, n_degenerate=csdeg),
            cost_floor=floors[cat],
        )
    return res


def cells_beyond_floor(part1):
    """Cells (horizon x category x price bucket) whose deviation CI excludes
    +/- the category's cost-floor lower bound."""
    hits = []
    for hlabel, strat in part1.items():
        for cat, cd in strat.get("per_category", {}).items():
            if cd.get("n", 0) == 0:
                continue
            floor_lo = COST_FLOORS[cat]["lo"]
            for cell in cd["curve"]:
                ci = cell.get("deviation_ci")
                if not ci or ci[0] is None:
                    continue
                lo, hi = ci
                if lo > floor_lo or hi < -floor_lo:
                    hits.append(dict(horizon=hlabel, category=cat, bucket=cell["bucket"],
                                     price_lo=cell["price_lo"], n=cell["n"],
                                     deviation=cell["deviation_edge"], deviation_ci=ci,
                                     floor_lo=floor_lo, floor_hi=COST_FLOORS[cat]["hi"],
                                     also_beyond_floor_hi=bool(lo > COST_FLOORS[cat]["hi"]
                                                              or hi < -COST_FLOORS[cat]["hi"])))
    return hits


# --------------------------------------------------------------------------
# Part 2
# --------------------------------------------------------------------------

OOS_SQL = """
    SELECT p.market_id, p.outcome, p.entry_avg_price, p.entry_timestamp,
           p.entry_total_cost, t.trade_result
    FROM positions p
    JOIN markets m ON m.market_id = p.market_id
    JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
    WHERE m.category IN ('Geopolitics', 'Elections')
      AND p.entry_avg_price IS NOT NULL
      AND t.trade_result IN ('won', 'lost')
      AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
      AND m.winning_outcome IN ('Yes', 'No')
      AND p.entry_timestamp > ?
"""


def load_oos(conn, pop):
    rows = conn.execute(OOS_SQL, [T_SPLIT]).fetchall()
    out = []
    for mid, oc, eap, ets, cost, tr in rows:
        d = pop.get(mid)
        if d is None:
            continue
        if oc == "Yes":
            p_yes = eap
        elif oc == "No":
            p_yes = 1.0 - eap
        else:
            continue
        try:
            ttr_h = (datetime.strptime(d["tape_end"], "%Y-%m-%d %H:%M:%S")
                     - datetime.strptime(_ts(ets), "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0
        except Exception:
            continue
        if ttr_h < 0:
            continue
        won = 1 if tr == "won" else 0
        # entry-weighted edge is the PROJECT-STANDARD quantity: won (did the
        # trader's OWN outcome resolve true) minus the price of THAT outcome
        # (entry_avg_price), NOT minus the Yes-normalised price. p_yes is only
        # the bucketing axis, to align with Part 1's price-weighted grid.
        out.append(dict(mkt=mid, category=d["category"], p_yes=float(min(max(p_yes, 0), 1)),
                        ttr_h=ttr_h, cost=float(cost or 0.0), won=won,
                        entry_edge=won - float(eap)))
    return pd.DataFrame(out)


def part2_overlay(oos, part1):
    tot_vol = oos["cost"].sum()
    tot_n = len(oos)
    cells = []
    for bi, (blo, bhi) in enumerate(TTR_BANDS):
        band_lbl = TTR_BAND_LABELS[bi]
        hlabel = HORIZON_LABELS[bi]
        strat = part1.get(hlabel, {})
        band = oos[(oos["ttr_h"] >= blo) & (oos["ttr_h"] < bhi)]
        for pb, plo in enumerate(PRICE_BUCKETS):
            if pb == 9:
                cell = band[band["p_yes"] >= 0.9]
            else:
                cell = band[(band["p_yes"] >= plo) & (band["p_yes"] < plo + 0.1)]
            n = len(cell)
            vol = cell["cost"].sum()
            ew_edge = (np.average(cell["entry_edge"], weights=cell["cost"])
                       if n and cell["cost"].sum() > 0 else (cell["entry_edge"].mean() if n else None))
            # pooled Part1 deviation for this (horizon, price bucket)
            dev = None; dev_ci = None
            for c in strat.get("pooled_curve", []):
                if c["bucket"] == pb and c.get("n", 0) > 0:
                    dev = c.get("deviation_edge"); dev_ci = c.get("deviation_ci")
            cells.append(dict(
                ttr_band=band_lbl, horizon=hlabel, price_bucket=pb, price_lo=plo,
                n_positions=int(n), vol=float(vol),
                vol_frac=float(vol / tot_vol) if tot_vol else 0.0,
                n_frac=float(n / tot_n) if tot_n else 0.0,
                entry_weighted_edge=(float(ew_edge) if ew_edge is not None else None),
                calib_deviation=dev, calib_deviation_ci=dev_ci,
            ))
    # quantified overlap
    arr = [(c["vol_frac"], abs(c["calib_deviation"]) if c["calib_deviation"] is not None else None,
            c["calib_deviation_ci"]) for c in cells]
    vf = np.array([a for a, b, _ in arr if b is not None])
    ad = np.array([b for a, b, _ in arr if b is not None])
    overlap = {}
    if len(ad) > 2 and vf.sum() > 0:
        overlap["pearson_absdev_volfrac"] = float(np.corrcoef(ad, vf)[0, 1])
        overlap["vol_weighted_mean_absdev"] = float(np.sum(vf * ad) / np.sum(vf))
        overlap["plain_mean_absdev"] = float(ad.mean())
    # vol fraction sitting in cells whose Part1 deviation CI excludes +/- floor_lo
    floor_lo_by_cat = None  # pooled -> use the stricter (elections) and looser (geo) both
    vol_in_geo_hit = 0.0; vol_in_elec_hit = 0.0
    for c in cells:
        ci = c["calib_deviation_ci"]
        if not ci or ci[0] is None:
            continue
        lo, hi = ci
        if lo > COST_FLOORS["Geopolitics"]["lo"] or hi < -COST_FLOORS["Geopolitics"]["lo"]:
            vol_in_geo_hit += c["vol_frac"]
        if lo > COST_FLOORS["Elections"]["lo"] or hi < -COST_FLOORS["Elections"]["lo"]:
            vol_in_elec_hit += c["vol_frac"]
    overlap["vol_frac_in_cells_beyond_geo_floor_lo"] = float(vol_in_geo_hit)
    overlap["vol_frac_in_cells_beyond_elec_floor_lo"] = float(vol_in_elec_hit)
    return dict(total_oos_positions=int(tot_n), total_oos_volume=float(tot_vol),
                cells=cells, overlap=overlap)


# --------------------------------------------------------------------------
# Part 3 (gated)
# --------------------------------------------------------------------------

PIT_POOL_JSON = "data/characterizations/directional_skill_pit_legal_pool_20260906T160303Z.json"


def part3_skilled_presence(conn, pop, clusters, tape, part1_snapshots, reps, seed):
    d = json.load(open(PIT_POOL_JSON))
    skilled = set(d.get("raw_skilled_traders", []))
    skilled_bh = set(d.get("bh_skilled_traders", []))
    # which population markets have >=1 position by a skilled trader (any time)
    mids = sorted(pop)
    present_raw = set()
    present_bh = set()
    CH = 900
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, addr in conn.execute(
            f"SELECT DISTINCT market_id, trader_address FROM positions WHERE market_id IN ({ph})", chunk):
            if addr in skilled:
                present_raw.add(mid)
            if addr in skilled_bh:
                present_bh.add(mid)
    out = dict(
        n_skilled_raw=len(skilled), n_skilled_bh=len(skilled_bh),
        n_markets_skilled_present_raw=len(present_raw & set(pop)),
        n_markets_skilled_present_bh=len(present_bh & set(pop)),
        n_markets_total=len(pop),
        framing=("skilled-trader PRESENCE as a conditioning variable on market "
                 "mispricing, NOT a copy signal. The 2026-09-10 copy-decay result "
                 "stands: no demonstrable edge to inherit from a trader's entry. "
                 "This asks only whether their presence MARKS a mispriced market, "
                 "which is actionable at one's own entry price/time."),
        strata={},
    )
    for hlabel, snap_df in part1_snapshots.items():
        if snap_df is None or len(snap_df) == 0:
            continue
        sub = snap_df.copy()
        sub["skilled_present"] = sub["mkt"].isin(present_raw)
        blk = {}
        for flag, name in ((True, "skilled_present"), (False, "skilled_absent")):
            g = sub[sub["skilled_present"] == flag]
            if len(g) == 0:
                blk[name] = dict(n=0); continue
            s, slo, shi, snb, sdeg = slope_ci(g, reps, seed + (1 if flag else 2))
            blk[name] = dict(
                n=int(len(g)), n_ec=int(g["ec"].nunique()),
                base_yes_rate=float(g["y"].mean()),
                curve=calib_curve(g, reps, seed + (10 if flag else 20)),
                logit_slope=dict(slope=s, ci=[slo, shi], n_boot=snb, n_degenerate=sdeg),
                thin=bool(len(g) < 30),
            )
        out["strata"][hlabel] = blk
    return out


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------

def selfcheck(conn, pop, clusters, tape):
    """(a) p_yes normalisation identity on a sample; (b) a hand-computed
    calibration rate for one horizon/bucket matches the vectorised path;
    (c) logistic slope ~1.0 on a synthetic perfectly-calibrated sample."""
    df, meta = snapshot_rows(pop, clusters, tape, 0.5)
    # (a): every p_yes in [0,1]
    a_ok = bool(((df["p_yes"] >= 0) & (df["p_yes"] <= 1)).all())
    # (b): bucket 7 realised rate hand vs helper
    sub = df[(df["p_yes"] >= 0.7) & (df["p_yes"] < 0.8)]
    hand = float(sub["y"].mean()) if len(sub) else None
    helper = _wrate(sub["y"].to_numpy().astype(float), sub["p_yes"].to_numpy().astype(float),
                    np.ones(len(sub))) if len(sub) else None
    b_ok = (hand is None and helper is None) or (abs(hand - helper) < 1e-12)
    # (c): synthetic calibrated data -> slope ~1
    rng = np.random.default_rng(0)
    ps = rng.uniform(0.05, 0.95, 4000)
    ys = (rng.uniform(size=4000) < ps).astype(float)
    sl = _fit_logistic_slope(ys, ps, np.ones(4000))
    c_ok = sl is not None and 0.8 < sl < 1.2
    print(f"[selfcheck] p_yes-in-[0,1]={a_ok}  rate-identity={b_ok}  "
          f"synthetic-slope={sl:.3f} (expect ~1.0) ok={c_ok}")
    return a_ok and b_ok and c_ok


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = db_connect(args.db)

    sha_before = oos_result_sha(args.db)
    print(f"[stop-cond] metric_v2f_oos_result sha256 BEFORE: {sha_before}")
    if sha_before != OOS_RESULT_SHA_EXPECTED:
        print("[STOP] metric_v2f_oos_result sha256 != expected", file=sys.stderr)
        sys.exit(3)

    print("[load] population ...")
    pop, popmeta = load_population(conn)
    print(f"       canonical={popmeta['n_canonical']}  non-binary excluded={popmeta['n_nonbinary_excluded']}  "
          f"used={popmeta['n_used']}")
    clusters, clmeta = load_event_clusters(conn, list(pop))
    print(f"[load] event clusters: {clmeta['n_labelled']} labelled, {clmeta['n_solo']} solo")
    print("[load] trade tape ...")
    tape = load_tape(conn, list(pop))
    print(f"       tape for {len(tape)} markets")

    if args.selfcheck:
        if not selfcheck(conn, pop, clusters, tape):
            print("[selfcheck] FAILED", file=sys.stderr); sys.exit(1)
        print("[selfcheck] PASSED")

    # ---- Part 1 ----
    print("\n=== PART 1 — calibration ===")
    part1 = {}
    snapshots = {}
    for h, hlabel in zip(HORIZONS_HOURS, HORIZON_LABELS):
        df, meta = snapshot_rows(pop, clusters, tape, h)
        snapshots[hlabel] = df
        strat = part1_stratum(df, args.reps, args.seed, COST_FLOORS)
        strat["horizon_hours"] = h
        strat["snapshot_meta"] = meta
        part1[hlabel] = strat
        sp = strat["logit_slope_pooled"]
        print(f"  {hlabel:>6} (h={h}h): n={strat['n']:>5} ec={strat['n_ec']:>4}  "
              f"pooled slope={sp['slope']:.3f} CI=[{sp['ci'][0]},{sp['ci'][1]}]  "
              f"geoN={strat['per_category'].get('Geopolitics',{}).get('n',0)} "
              f"elecN={strat['per_category'].get('Elections',{}).get('n',0)}")

    hits = cells_beyond_floor(part1)
    print(f"\n[gate] cells with deviation CI beyond the category cost-floor lower bound: {len(hits)}")
    for hh in hits[:40]:
        print(f"   {hh['horizon']:>6} {hh['category']:<11} bucket{hh['bucket']} "
              f"[{hh['price_lo']:.1f},{hh['price_lo']+0.1:.1f})  dev={hh['deviation']:+.4f} "
              f"CI={hh['deviation_ci']}  n={hh['n']}  floor_lo={hh['floor_lo']}  "
              f"beyond_hi={hh['also_beyond_floor_hi']}")

    # ---- Part 2 ----
    print("\n=== PART 2 — entry-density overlay ===")
    oos = load_oos(conn, pop)
    part2 = part2_overlay(oos, part1)
    print(f"  OOS positions={part2['total_oos_positions']}  volume={part2['total_oos_volume']:.0f}")
    print(f"  overlap: {json.dumps(part2['overlap'], default=str)}")

    # ---- Part 3 (gated) ----
    part3 = None
    gate_open = len(hits) > 0
    if gate_open:
        print("\n=== PART 3 — calibration conditioned on directionally-skilled-trader PRESENCE ===")
        print("    (conditioning variable on mispricing, NOT a copy signal)")
        part3 = part3_skilled_presence(conn, pop, clusters, tape, snapshots, args.reps, args.seed)
        for hlabel, blk in part3["strata"].items():
            sp = blk.get("skilled_present", {}); sa = blk.get("skilled_absent", {})
            print(f"  {hlabel:>6}: present n={sp.get('n',0)} slope={sp.get('logit_slope',{}).get('slope')}  "
                  f"| absent n={sa.get('n',0)} slope={sa.get('logit_slope',{}).get('slope')}")
    else:
        print("\n=== PART 3 — NOT RUN (gate closed: no cell's deviation CI clears the cost floor) ===")

    sha_after = oos_result_sha(args.db)
    print(f"\n[stop-cond] metric_v2f_oos_result sha256 AFTER:  {sha_after}")
    conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_out = args.json_out or f"data/characterizations/own_market_calibration_{ts}.json"
    artifact = dict(
        spec="own_market_calibration",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        params=dict(t_split=T_SPLIT, seed=args.seed, reps=args.reps,
                    price_buckets=PRICE_BUCKETS, horizons_hours=HORIZONS_HOURS,
                    horizon_labels=HORIZON_LABELS, ttr_bands=TTR_BANDS,
                    ttr_band_labels=TTR_BAND_LABELS, logit_clip_eps=EPS,
                    cost_floors=COST_FLOORS),
        price_definition=PRICE_DEFINITION,
        anchor="tape_end (MAX(trades.timestamp)); NOT resolution_date (O-36: ~11% impossible values)",
        population_meta=popmeta, cluster_meta=clmeta,
        oos_result_sha_before=sha_before, oos_result_sha_after=sha_after,
        oos_result_unchanged=bool(sha_before == sha_after == OOS_RESULT_SHA_EXPECTED),
        part1=part1,
        part1_cells_beyond_floor=hits,
        gate_open=bool(gate_open),
        part2=part2,
        part3=part3,
    )
    os.makedirs(os.path.dirname(json_out), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(artifact, f, indent=2, default=str)
    print(f"[artifact] {json_out}")
    if sha_before != sha_after:
        print("[STOP] metric_v2f_oos_result CHANGED during the run.", file=sys.stderr)
        sys.exit(3)
    print(f"\n[done] gate_open={gate_open}  oos_result_unchanged=True")


if __name__ == "__main__":
    main()
