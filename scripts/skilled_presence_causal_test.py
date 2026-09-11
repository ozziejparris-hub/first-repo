#!/usr/bin/env python3
"""
Is skilled-trader presence causal or compositional?

Tests the 2026-09-10 own-market-calibration Part 3 finding (see
brain/decisions/2026-09-10-own-market-calibration.md, trading-swarm repo):
markets where a PIT-legally-identified directionally-skilled trader took a
position carry a HIGHER logistic recalibration slope than markets where
none did, at every one of six lead times -- but present and absent CIs
overlap at every horizon (a consistent direction, not a per-horizon-
significant gap), and skilled-present markets are the MAJORITY (57.7%),
so the gap could be composition (size/activity/type), not skilled traders
marking mispriced markets.

FRAMING (carried from the 2026-09-10 doc, not revisited here): skilled-
trader presence is used strictly as a CONDITIONING VARIABLE on market
mispricing, evaluable at one's own entry price/time -- NOT a copy signal.
The 2026-09-10 copy-trade-decay result (no demonstrable edge to inherit
from a trader's entry, COLLAPSES-BEFORE-CADENCE) is not re-litigated or
re-run here.

PART 1 -- characterise skilled-present (5,619) vs skilled-absent (4,120)
  markets on observables, BEFORE any slope recomputation: n_trades,
  n_distinct_traders, volume, market lifetime, price-at-horizon, base
  rate, category mix, event-cluster (solo vs labelled) membership.
  STOP CONDITION: if base rate differs so grossly the comparison is
  confounded at the root, report and halt before Part 2.

PART 2 -- matched comparison. Greedy nearest-neighbour 1:1 match, WITHIN
  category, on standardised log(1+n_trades), log(1+n_distinct_traders),
  log(1+volume), log(1+lifetime_hours), with a caliper (unmatched pairs
  dropped rather than forced). Re-run the six-horizon slope comparison on
  the matched arms. NOT match_control() -- that function was built for
  TRADER matching (on log positions/markets/span) and is reused as-is in
  Part 3 below, where the problem genuinely is trader-activity matching;
  here the object being matched is a MARKET, on market-level size/
  composition features, which is a different feature space and a
  different distance problem, so a purpose-built match is used instead.
  STOP CONDITION: if the direction/magnitude collapses under matching,
  report and halt -- that is a complete finding (skilled presence is a
  size/activity proxy, not a mispricing marker).

PART 3 (GATED on Part 2 surviving) -- placebo: markets where a same-size
  (1,494), activity-matched-but-NOT-skill-selected set of traders, drawn
  from the PIT-legal classifiable pool via match_control() (a legitimate
  reuse here -- this genuinely is the trader-activity-matching problem
  match_control() was built for), took a position. Seed recorded.
  STOP CONDITION: if the placebo shows the same elevation, report and
  halt -- presence is about activity, not skill.

PART 4 (GATED on Part 3 surviving) -- deviation in edge units, per price
  bucket and lead time, for the surviving conditioning variable, against
  the category cost floors (geo 0.0005-0.010, elec 0.0056-0.020).

Read-only throughout. --persist not implemented/accepted. No canonical
definition, harness, or threshold modified. Does not touch or re-run the
copy-trade decay ladder. Does not restart any service.

Seed 42, reps 1500 (matching own_market_calibration.py / trader_skill_
metric_v2f.py conventions). T_SPLIT = 2026-04-01 00:00:00.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.own_market_calibration import (
    db_connect, load_population, load_event_clusters, load_tape,
    snapshot_rows, calib_curve, slope_ci,
    PRICE_BUCKETS, HORIZONS_HOURS, HORIZON_LABELS, COST_FLOORS,
    PIT_POOL_JSON, oos_result_sha, OOS_RESULT_SHA_EXPECTED, git_commit,
    _ts,
)
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, GATE_REPS_LOCAL, M_CHOSEN

REPS = GATE_REPS_LOCAL  # 1500

# Base-rate stop-condition threshold: a gap this large (percentage points)
# between arms' YES rate, with a binomial CI on the gap excluding zero
# by a wide margin, is treated as "confounded at the root". Set generously
# (project's own arms already span 20.9%-70.9% category base rates in
# other splits) so a routine few-point gap doesn't trip it, but a gap on
# that order does.
BASE_RATE_STOP_PP = 10.0

CALIPER = 1.0  # standardised 4-D Euclidean distance; see justification in doc


def base_market_features(conn, market_ids):
    """market_id -> n_trades, n_distinct_traders, volume (sum shares*price),
    first_trade_ts, from the trade tape. One pass, chunked."""
    feats = {}
    CH = 900
    mids = sorted(market_ids)
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, n_trades, n_dt, vol, first_ts in conn.execute(
            f"""SELECT market_id, COUNT(*), COUNT(DISTINCT trader_address),
                       SUM(COALESCE(shares,0) * COALESCE(price,0)), MIN(timestamp)
                FROM trades WHERE market_id IN ({ph}) GROUP BY market_id""", chunk):
            feats[mid] = dict(n_trades=int(n_trades), n_distinct_traders=int(n_dt),
                              volume=float(vol or 0.0), first_trade_ts=_ts(first_ts) if first_ts else None)
    return feats


def skilled_present_markets(conn, pop):
    d = json.load(open(PIT_POOL_JSON))
    skilled = set(d.get("raw_skilled_traders", []))
    mids = sorted(pop)
    present = set()
    CH = 900
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, addr in conn.execute(
            f"SELECT DISTINCT market_id, trader_address FROM positions WHERE market_id IN ({ph})", chunk):
            if addr in skilled:
                present.add(mid)
    return skilled, (present & set(pop))


# --------------------------------------------------------------------------
# PART 1 -- population characterisation
# --------------------------------------------------------------------------

def describe(series):
    s = pd.Series(series).astype(float)
    if len(s) == 0:
        return dict(n=0)
    return dict(n=int(len(s)), mean=float(s.mean()), median=float(s.median()),
                p10=float(s.quantile(0.10)), p25=float(s.quantile(0.25)),
                p75=float(s.quantile(0.75)), p90=float(s.quantile(0.90)))


def part1_characterise(mdf, snapshots):
    out = dict()
    present = mdf[mdf["present"]]
    absent = mdf[~mdf["present"]]
    out["n_present"] = int(len(present))
    out["n_absent"] = int(len(absent))

    for feat in ("n_trades", "n_distinct_traders", "volume", "lifetime_hours"):
        out[feat] = dict(present=describe(present[feat]), absent=describe(absent[feat]))

    # base rate -- the one that matters most
    yp = float(present["y"].mean()); ya = float(absent["y"].mean())
    npr = len(present); nab = len(absent)
    se = float(np.sqrt(yp * (1 - yp) / npr + ya * (1 - ya) / nab))
    gap_pp = (yp - ya) * 100.0
    out["base_rate"] = dict(
        present_yes_rate=yp, absent_yes_rate=ya, gap_pp=gap_pp,
        gap_se_pp=se * 100.0, gap_ci_pp=[gap_pp - 1.96 * se * 100.0, gap_pp + 1.96 * se * 100.0],
        stop_condition_threshold_pp=BASE_RATE_STOP_PP,
        stop_condition_tripped=bool(abs(gap_pp) >= BASE_RATE_STOP_PP and
                                     (gap_pp - 1.96 * se * 100.0) * (gap_pp + 1.96 * se * 100.0) > 0),
    )

    # category mix
    cat_tab = {}
    for cat in ("Geopolitics", "Elections"):
        cat_tab[cat] = dict(
            present=int((present["category"] == cat).sum()),
            absent=int((absent["category"] == cat).sum()),
        )
    out["category_mix"] = cat_tab
    out["category_mix_pct"] = {
        cat: dict(present_pct=100.0 * cat_tab[cat]["present"] / max(len(present), 1),
                  absent_pct=100.0 * cat_tab[cat]["absent"] / max(len(absent), 1))
        for cat in ("Geopolitics", "Elections")
    }

    # event-cluster: solo vs labelled
    out["cluster_membership"] = dict(
        present_solo=int(present["is_solo"].sum()), present_labelled=int((~present["is_solo"]).sum()),
        absent_solo=int(absent["is_solo"].sum()), absent_labelled=int((~absent["is_solo"]).sum()),
        present_solo_pct=100.0 * present["is_solo"].mean(),
        absent_solo_pct=100.0 * absent["is_solo"].mean(),
    )

    # price at each horizon, present vs absent
    out["price_by_horizon"] = {}
    for hlabel, snap in snapshots.items():
        s = snap.copy()
        s["present"] = s["mkt"].isin(set(present["mkt"]))
        out["price_by_horizon"][hlabel] = dict(
            present=describe(s.loc[s["present"], "p_yes"]),
            absent=describe(s.loc[~s["present"], "p_yes"]),
        )
    return out


# --------------------------------------------------------------------------
# PART 2 -- market-level matched comparison (purpose-built, not match_control)
# --------------------------------------------------------------------------

def match_markets(mdf, seed):
    """Greedy 1:1 nearest-neighbour match, WITHIN category, absent -> present,
    on z-scored log(1+n_trades), log(1+n_distinct_traders), log(1+volume),
    log(1+lifetime_hours). Caliper on standardised Euclidean distance;
    unmatched absent markets are dropped, not forced. Deterministic given
    seed (used only to fix match ORDER among absent markets, same
    determinism-safety pattern as trader_skill_metric_v2f.match_control:
    sort before shuffling with a seeded RNG, so no dependence on set/dict
    iteration order)."""
    feats = ["n_trades", "n_distinct_traders", "volume", "lifetime_hours"]
    rng = np.random.default_rng(seed)
    matched_present = []
    matched_absent = []
    distances = []
    per_category = {}
    for cat in sorted(mdf["category"].unique()):
        cd_ = mdf[mdf["category"] == cat]
        pres = cd_[cd_["present"]].copy()
        abse = cd_[~cd_["present"]].copy()
        if len(pres) == 0 or len(abse) == 0:
            per_category[cat] = dict(n_absent=len(abse), n_present_pool=len(pres), n_matched=0)
            continue
        X = np.column_stack([np.log1p(pd.concat([pres[f], abse[f]])) for f in feats])
        mu = X.mean(axis=0); sd = X.std(axis=0); sd[sd == 0] = 1.0
        Xp = (np.column_stack([np.log1p(pres[f]) for f in feats]) - mu) / sd
        Xa = (np.column_stack([np.log1p(abse[f]) for f in feats]) - mu) / sd
        abs_ids = abse["mkt"].tolist()
        pres_ids = pres["mkt"].tolist()
        order = list(range(len(abs_ids)))
        rng.shuffle(order)
        used = set()
        n_matched_cat = 0
        for oi in order:
            feat = Xa[oi]
            dists = np.linalg.norm(Xp - feat, axis=1)
            cand_order = np.argsort(dists)
            for ci in cand_order:
                if ci in used:
                    continue
                d = dists[ci]
                if d > CALIPER:
                    break  # sorted ascending: no closer candidate left either
                used.add(ci)
                matched_absent.append(abs_ids[oi])
                matched_present.append(pres_ids[ci])
                distances.append(float(d))
                n_matched_cat += 1
                break
        per_category[cat] = dict(n_absent=len(abse), n_present_pool=len(pres), n_matched=n_matched_cat)
    return dict(matched_present=matched_present, matched_absent=matched_absent,
                distances=distances, per_category=per_category)


def part2_matched(mdf, snapshots, match_result, reps, seed):
    mp = set(match_result["matched_present"])
    ma = set(match_result["matched_absent"])
    out = dict(
        n_matched_pairs=len(match_result["matched_present"]),
        caliper=CALIPER,
        per_category=match_result["per_category"],
        distance_summary=describe(match_result["distances"]) if match_result["distances"] else dict(n=0),
        balance=dict(),
        strata={},
    )
    # covariate balance pre/post match
    for feat in ("n_trades", "n_distinct_traders", "volume", "lifetime_hours"):
        pre_p = mdf.loc[mdf["present"], feat].mean()
        pre_a = mdf.loc[~mdf["present"], feat].mean()
        post_p = mdf.loc[mdf["mkt"].isin(mp), feat].mean()
        post_a = mdf.loc[mdf["mkt"].isin(ma), feat].mean()
        out["balance"][feat] = dict(pre_present=float(pre_p), pre_absent=float(pre_a),
                                    post_present=float(post_p), post_absent=float(post_a))
    post_yp = float(mdf.loc[mdf["mkt"].isin(mp), "y"].mean())
    post_ya = float(mdf.loc[mdf["mkt"].isin(ma), "y"].mean())
    out["balance"]["base_rate"] = dict(post_present=post_yp, post_absent=post_ya,
                                       post_gap_pp=(post_yp - post_ya) * 100.0)

    for hlabel, snap in snapshots.items():
        gp = snap[snap["mkt"].isin(mp)]
        ga = snap[snap["mkt"].isin(ma)]
        blk = {}
        for name, g in (("matched_present", gp), ("matched_absent", ga)):
            if len(g) == 0:
                blk[name] = dict(n=0); continue
            s, slo, shi, snb, sdeg = slope_ci(g, reps, seed + (1 if name == "matched_present" else 2))
            blk[name] = dict(n=int(len(g)), n_ec=int(g["ec"].nunique()),
                             base_yes_rate=float(g["y"].mean()),
                             logit_slope=dict(slope=s, ci=[slo, shi], n_boot=snb, n_degenerate=sdeg),
                             curve=calib_curve(g, reps, seed + (10 if name == "matched_present" else 20)))
        out["strata"][hlabel] = blk
    return out


def part2_survives(part2, part1_present_slope_by_h, part1_absent_slope_by_h):
    """Effect 'survives matching' iff, at a majority of horizons with usable
    n, the matched-present point slope still exceeds the matched-absent
    point slope (direction preserved) -- not requiring per-horizon CI
    significance, matching how the original effect was itself reported
    (consistent direction, overlapping CIs)."""
    n_dir_preserved = 0
    n_usable = 0
    detail = {}
    for hlabel, blk in part2["strata"].items():
        sp = blk.get("matched_present", {}).get("logit_slope", {}).get("slope")
        sa = blk.get("matched_absent", {}).get("logit_slope", {}).get("slope")
        if sp is None or sa is None:
            detail[hlabel] = dict(usable=False)
            continue
        n_usable += 1
        preserved = sp > sa
        if preserved:
            n_dir_preserved += 1
        detail[hlabel] = dict(usable=True, matched_present_slope=sp, matched_absent_slope=sa,
                              direction_preserved=bool(preserved), gap=sp - sa)
    survives = bool(n_usable > 0 and n_dir_preserved >= (n_usable + 1) // 2 + (0 if n_usable % 2 else 0)
                     and n_dir_preserved > n_usable / 2)
    return dict(survives=survives, n_horizons_usable=n_usable,
               n_horizons_direction_preserved=n_dir_preserved, detail=detail)


# --------------------------------------------------------------------------
# PART 3 (gated) -- placebo activity-matched, non-skill-selected trader set
# --------------------------------------------------------------------------

def part3_placebo(conn, pop, clusters, snapshots, skilled, reps, seed):
    from scripts.trader_skill_metric_v2f import match_control
    from scripts.directional_skill_pit_legal_pool import (
        load_presplit_market_ids, load_presplit_positions,
    )

    # Rebuild the SAME "PIT-legal classifiable pool" the skill-selection
    # artifact used -- NOT trader_skill_metric_v2f.build_presplit_cohort's
    # own elig_pool, which filters on n_PAIRS (compute_cap5_metric's EB-
    # shrinkage construct, a materially smaller population -- verified this
    # session: 3,037 traders, vs. n_positions >= M_CHOSEN's 5,732; 536 of
    # the 1,494 skilled traders are not even members of the pairs-pool).
    # directional_skill_pit_legal_pool.py's own classifiable definition is
    # positions (not pairs) in the tape_end<T_SPLIT canonical market set,
    # >= M_CHOSEN per trader -- reproduced here via its own loaders so the
    # draw population matches what actually produced the skilled cohort.
    market_ids, _ = load_presplit_market_ids(conn, T_SPLIT)
    pos = load_presplit_positions(conn, market_ids)
    n_pos = pos.groupby("trader").size()
    classifiable = set(n_pos[n_pos >= M_CHOSEN].index)
    n_classifiable_check = len(classifiable)

    profile = pos.groupby("trader").agg(
        n_positions=("market_id", "size"), n_markets=("market_id", "nunique")
    ).reset_index()
    activity = pos.groupby("trader")["entry_ts"].agg(["min", "max"]).reset_index()
    profile = profile.merge(activity, on="trader")

    missing_from_elig = skilled - classifiable
    placebo_traders = match_control(profile, skilled, classifiable, seed=seed, verbose=False)

    mids = sorted(pop)
    placebo_present = set()
    CH = 900
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, addr in conn.execute(
            f"SELECT DISTINCT market_id, trader_address FROM positions WHERE market_id IN ({ph})", chunk):
            if addr in placebo_traders:
                placebo_present.add(mid)
    placebo_present &= set(pop)

    out = dict(
        n_skilled=len(skilled),
        n_classifiable_pool=n_classifiable_check,
        n_skilled_not_in_elig_pool=len(missing_from_elig),
        n_placebo_traders=len(placebo_traders),
        n_markets_placebo_present=len(placebo_present),
        seed=seed,
        strata={},
    )
    for hlabel, snap in snapshots.items():
        s = snap.copy()
        s["placebo_present"] = s["mkt"].isin(placebo_present)
        blk = {}
        for flag, name in ((True, "placebo_present"), (False, "placebo_absent")):
            g = s[s["placebo_present"] == flag]
            if len(g) == 0:
                blk[name] = dict(n=0); continue
            sl, slo, shi, snb, sdeg = slope_ci(g, reps, seed + (3 if flag else 4))
            blk[name] = dict(n=int(len(g)), n_ec=int(g["ec"].nunique()),
                             base_yes_rate=float(g["y"].mean()),
                             logit_slope=dict(slope=sl, ci=[slo, shi], n_boot=snb, n_degenerate=sdeg))
        out["strata"][hlabel] = blk
    return out


def part3_survives(part3):
    """Placebo 'shows the same elevation' iff, at a majority of usable
    horizons, placebo-present slope also exceeds placebo-absent -- if so,
    presence (of ANY active-and-matched trader set) explains the gap and
    skilled presence is not doing anything specific."""
    n_dir = 0; n_usable = 0; detail = {}
    for hlabel, blk in part3["strata"].items():
        sp = blk.get("placebo_present", {}).get("logit_slope", {}).get("slope")
        sa = blk.get("placebo_absent", {}).get("logit_slope", {}).get("slope")
        if sp is None or sa is None:
            detail[hlabel] = dict(usable=False); continue
        n_usable += 1
        preserved = sp > sa
        if preserved:
            n_dir += 1
        detail[hlabel] = dict(usable=True, placebo_present_slope=sp, placebo_absent_slope=sa,
                              direction_preserved=bool(preserved))
    placebo_replicates = bool(n_usable > 0 and n_dir > n_usable / 2)
    return dict(placebo_shows_same_elevation=placebo_replicates,
               n_horizons_usable=n_usable, n_horizons_direction_preserved=n_dir, detail=detail)


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------

def selfcheck():
    ok = True
    # (a) describe() on a known series
    d = describe([1, 2, 3, 4, 5])
    ok &= (d["median"] == 3.0 and d["n"] == 5)
    # (b) match_markets: synthetic markets, absent should match nearest present
    rng = np.random.default_rng(0)
    n = 40
    df = pd.DataFrame(dict(
        mkt=[f"m{i}" for i in range(n)],
        category=["Geopolitics"] * n,
        n_trades=list(rng.integers(5, 500, n)),
        n_distinct_traders=list(rng.integers(2, 100, n)),
        volume=list(rng.uniform(100, 100000, n)),
        lifetime_hours=list(rng.uniform(1, 2000, n)),
        present=[i % 2 == 0 for i in range(n)],
        y=[0] * n,
    ))
    mr = match_markets(df, seed=0)
    ok &= (len(mr["matched_present"]) == len(mr["matched_absent"]))
    ok &= (len(mr["matched_present"]) <= (n // 2))
    ok &= (len(set(mr["matched_present"])) == len(mr["matched_present"]))  # no reuse
    print(f"[selfcheck] describe={d['median']==3.0}  "
          f"match_markets: pairs={len(mr['matched_present'])} no_reuse={len(set(mr['matched_present']))==len(mr['matched_present'])}")
    return ok


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--force-part3", action="store_true",
                     help="run Part 3 even if Part 2's direction-preserved gate looks closed (diagnostic only)")
    args = ap.parse_args()

    if args.selfcheck:
        ok = selfcheck()
        print("[selfcheck] " + ("PASSED" if ok else "FAILED"))
        if not ok:
            sys.exit(1)
        if not args.db:
            return

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = db_connect(args.db)

    sha_before = oos_result_sha(args.db)
    print(f"[stop-cond] metric_v2f_oos_result sha256 BEFORE: {sha_before}")
    if sha_before != OOS_RESULT_SHA_EXPECTED:
        print("[STOP] metric_v2f_oos_result sha256 != expected", file=sys.stderr)
        sys.exit(3)

    print("[load] population ...")
    pop, popmeta = load_population(conn)
    print(f"       used={popmeta['n_used']}")
    clusters, clmeta = load_event_clusters(conn, list(pop))
    print(f"[load] event clusters: {clmeta['n_labelled']} labelled, {clmeta['n_solo']} solo")
    print("[load] trade tape ...")
    tape = load_tape(conn, list(pop))
    print(f"       tape for {len(tape)} markets")
    print("[load] per-market base features (n_trades, n_distinct_traders, volume) ...")
    basefeats = base_market_features(conn, list(pop))

    print("[load] skilled-trader presence ...")
    skilled, present_mids = skilled_present_markets(conn, pop)
    print(f"       n_skilled={len(skilled)}  present_markets={len(present_mids)}/{len(pop)}")

    # ---- six-horizon snapshots (reused from own_market_calibration) ----
    print("[compute] six-horizon price snapshots ...")
    snapshots = {}
    for h, hlabel in zip(HORIZONS_HOURS, HORIZON_LABELS):
        df, meta = snapshot_rows(pop, clusters, tape, h)
        snapshots[hlabel] = df
        print(f"  {hlabel:>6}: n={len(df)}")

    # ---- market-level dataframe for Part 1 / Part 2 ----
    rows = []
    for mid, d in pop.items():
        bf = basefeats.get(mid, dict(n_trades=0, n_distinct_traders=0, volume=0.0, first_trade_ts=None))
        if bf["first_trade_ts"] is not None:
            lifetime_h = ((datetime.strptime(d["tape_end"], "%Y-%m-%d %H:%M:%S")
                          - datetime.strptime(bf["first_trade_ts"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600.0)
        else:
            lifetime_h = 0.0
        rows.append(dict(mkt=mid, category=d["category"], y=d["y"],
                         present=(mid in present_mids),
                         n_trades=bf["n_trades"], n_distinct_traders=bf["n_distinct_traders"],
                         volume=bf["volume"], lifetime_hours=max(lifetime_h, 0.0),
                         is_solo=str(clusters.get(mid, "")).startswith("solo::")))
    mdf = pd.DataFrame(rows)
    print(f"[market-df] n={len(mdf)}  present={int(mdf['present'].sum())}  absent={int((~mdf['present']).sum())}")

    # ============================= PART 1 =============================
    print("\n=== PART 1 -- population characterisation ===")
    part1 = part1_characterise(mdf, snapshots)
    br = part1["base_rate"]
    print(f"  base rate: present={br['present_yes_rate']:.3f}  absent={br['absent_yes_rate']:.3f}  "
          f"gap={br['gap_pp']:+.2f}pp  CI=[{br['gap_ci_pp'][0]:+.2f},{br['gap_ci_pp'][1]:+.2f}]pp  "
          f"STOP={br['stop_condition_tripped']}")
    for feat in ("n_trades", "n_distinct_traders", "volume", "lifetime_hours"):
        p = part1[feat]["present"]; a = part1[feat]["absent"]
        print(f"  {feat:>20}: present median={p.get('median'):.1f} mean={p.get('mean'):.1f}  |  "
              f"absent median={a.get('median'):.1f} mean={a.get('mean'):.1f}")
    print(f"  category mix (present%/absent%): {part1['category_mix_pct']}")
    print(f"  cluster: present_solo%={part1['cluster_membership']['present_solo_pct']:.1f}  "
          f"absent_solo%={part1['cluster_membership']['absent_solo_pct']:.1f}")

    stop_after_part1 = bool(br["stop_condition_tripped"])
    if stop_after_part1:
        print("\n[STOP] Part 1 base-rate gap trips the stop condition -- halting before Part 2.")

    part2 = None
    part2_gate = None
    part3 = None
    part3_gate = None
    part4 = None

    if not stop_after_part1:
        # ============================= PART 2 =============================
        print("\n=== PART 2 -- matched comparison ===")
        match_result = match_markets(mdf, seed=args.seed)
        for cat, cc in match_result["per_category"].items():
            print(f"  {cat}: absent={cc['n_absent']} present_pool={cc['n_present_pool']} matched={cc['n_matched']}")
        part2 = part2_matched(mdf, snapshots, match_result, args.reps, args.seed)
        for hlabel, blk in part2["strata"].items():
            sp = blk.get("matched_present", {}); sa = blk.get("matched_absent", {})
            print(f"  {hlabel:>6}: matched_present n={sp.get('n',0)} slope={sp.get('logit_slope',{}).get('slope')}  "
                  f"| matched_absent n={sa.get('n',0)} slope={sa.get('logit_slope',{}).get('slope')}")

        part2_gate = part2_survives(part2, None, None)
        print(f"\n[gate] Part 2 direction preserved at {part2_gate['n_horizons_direction_preserved']}/"
              f"{part2_gate['n_horizons_usable']} usable horizons -> survives={part2_gate['survives']}")

        if not part2_gate["survives"] and not args.force_part3:
            print("[STOP] Effect disappears/reverses under matching -- complete finding, halting before Part 3.")
        else:
            # ============================= PART 3 (gated) =============================
            print("\n=== PART 3 (gated) -- placebo activity-matched, non-skill-selected traders ===")
            part3 = part3_placebo(conn, pop, clusters, snapshots, skilled, args.reps, args.seed)
            print(f"  n_classifiable_pool={part3['n_classifiable_pool']}  "
                  f"n_skilled_not_in_pool={part3['n_skilled_not_in_elig_pool']}  "
                  f"n_placebo_traders={part3['n_placebo_traders']}  "
                  f"n_markets_placebo_present={part3['n_markets_placebo_present']}")
            for hlabel, blk in part3["strata"].items():
                pp = blk.get("placebo_present", {}); pa = blk.get("placebo_absent", {})
                print(f"  {hlabel:>6}: placebo_present n={pp.get('n',0)} slope={pp.get('logit_slope',{}).get('slope')}  "
                      f"| placebo_absent n={pa.get('n',0)} slope={pa.get('logit_slope',{}).get('slope')}")
            part3_gate = part3_survives(part3)
            print(f"\n[gate] placebo shows same elevation at {part3_gate['n_horizons_direction_preserved']}/"
                  f"{part3_gate['n_horizons_usable']} usable horizons -> "
                  f"placebo_replicates={part3_gate['placebo_shows_same_elevation']}")

            if part3_gate["placebo_shows_same_elevation"]:
                print("[STOP] Placebo shows the same elevation -- complete finding, halting before Part 4.")
            else:
                # ============================= PART 4 (gated) =============================
                print("\n=== PART 4 (gated) -- deviation in edge units vs cost floors (matched arms) ===")
                part4 = dict(cells_beyond_floor=[])
                for hlabel, blk in part2["strata"].items():
                    for arm in ("matched_present", "matched_absent"):
                        g = blk.get(arm, {})
                        for cell in g.get("curve", []):
                            ci = cell.get("deviation_ci")
                            if not ci or ci[0] is None:
                                continue
                            lo, hi = ci
                            # category-specific floor: use per-market category from mdf for this cell's markets
                            # (cells here are pooled across category within the matched arm; report against
                            # BOTH floors explicitly since the matched arms are not category-pure)
                            for cat, fl in COST_FLOORS.items():
                                beyond_lo = bool(lo > fl["lo"] or hi < -fl["lo"])
                                beyond_hi = bool(lo > fl["hi"] or hi < -fl["hi"])
                                if beyond_lo:
                                    part4["cells_beyond_floor"].append(dict(
                                        horizon=hlabel, arm=arm, bucket=cell["bucket"],
                                        price_lo=cell["price_lo"], n=cell["n"],
                                        deviation=cell["deviation_edge"], deviation_ci=ci,
                                        vs_category=cat, floor_lo=fl["lo"], floor_hi=fl["hi"],
                                        beyond_floor_hi=beyond_hi))
                print(f"  cells clearing >=1 category floor_lo: {len(part4['cells_beyond_floor'])}")
                for c in part4["cells_beyond_floor"][:40]:
                    print(f"    {c['horizon']:>6} {c['arm']:<16} bucket{c['bucket']} vs {c['vs_category']}: "
                          f"dev={c['deviation']:+.4f} CI={c['deviation_ci']} n={c['n']} beyond_hi={c['beyond_floor_hi']}")

    sha_after = oos_result_sha(args.db)
    print(f"\n[stop-cond] metric_v2f_oos_result sha256 AFTER:  {sha_after}")
    conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_out = args.json_out or f"data/characterizations/skilled_presence_causal_test_{ts}.json"
    artifact = dict(
        spec="skilled_presence_causal_test",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        params=dict(t_split=T_SPLIT, seed=args.seed, reps=args.reps, caliper=CALIPER,
                    base_rate_stop_pp=BASE_RATE_STOP_PP, m_chosen=M_CHOSEN,
                    horizon_labels=HORIZON_LABELS, price_buckets=PRICE_BUCKETS,
                    cost_floors=COST_FLOORS, match_features=["n_trades", "n_distinct_traders",
                                                              "volume", "lifetime_hours"]),
        oos_result_sha_before=sha_before, oos_result_sha_after=sha_after,
        oos_result_unchanged=bool(sha_before == sha_after == OOS_RESULT_SHA_EXPECTED),
        population_meta=popmeta, cluster_meta=clmeta,
        n_markets_present=int(mdf["present"].sum()), n_markets_absent=int((~mdf["present"]).sum()),
        part1=part1,
        stop_after_part1=stop_after_part1,
        part2_match=(match_result if part2 is not None else None),
        part2=part2,
        part2_gate=part2_gate,
        part3=part3,
        part3_gate=part3_gate,
        part4=part4,
    )
    os.makedirs(os.path.dirname(json_out), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(artifact, f, indent=2, default=str)
    print(f"[artifact] {json_out}")
    if sha_before != sha_after:
        print("[STOP] metric_v2f_oos_result CHANGED during the run.", file=sys.stderr)
        sys.exit(3)
    print(f"\n[done] stop_after_part1={stop_after_part1}  "
          f"part2_survives={(part2_gate or {}).get('survives')}  "
          f"part3_placebo_replicates={(part3_gate or {}).get('placebo_shows_same_elevation')}  "
          f"oos_result_unchanged=True")


if __name__ == "__main__":
    main()
