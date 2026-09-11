#!/usr/bin/env python3
"""
ELO-tier-conditioned calibration: does the skilled-presence causal-vs-
compositional test replicate when the conditioning variable is a current
ELO tier instead of the PIT-legal directional-skill classification?

FRAMING -- READ BEFORE INTERPRETING ANY NUMBER BELOW. geo_elo is condemned
for SKILL-RANKING (MASTER_HANDOVER_2026-08-15 Section 1: sign error,
improper scoring rule, 35.7% sell contamination, 52.3% double-counting,
uncalibrated parameters). NOTHING HERE REOPENS THAT. This script uses ELO
tier ONLY as a CONDITIONING VARIABLE on market mispricing -- the same use
as skilled-trader presence in 2026-09-11-skilled-presence-causal-vs-
compositional.md -- never as a skill measure, never as a selector, never
to claim a trader is good. A market being "LEGENDARY-present" here means
only "a trader currently carrying that tier label holds a position in it";
it is not a claim that tier label is a valid measure of anything.

Reuses own_market_calibration.py's population/tape/snapshot/bootstrap/
slope machinery, and scripts/skilled_presence_causal_test.py's Part 1
(part1_characterise), Part 2 (match_markets, part2_matched, part2_survives)
and Part 3 (part3_placebo, part3_survives) pipeline DIRECTLY -- none of it
is re-derived here, per instructions. The only new code is: (a) defining
each ELO-tier "present" trader set from the CURRENT traders table (not a
frozen PIT-legal artifact -- tier is a live, continuously-recomputed
state field, unlike the frozen directional-skill classification), and
(b) orchestrating the same pipeline across three conditioning variables
with explicit UNCOMPUTABLE handling for thin arms.

Conditioning variables (current traders-table state, all-time positions
for "present"):
  (a) LEGENDARY  -- monitoring.column_definitions.LEGENDARY_GATE_WHERE
                    (geo_elo_active>=2175, geo_accuracy_pool=1,
                    research_excluded=0, bot_type IS NULL). Extreme tier,
                    small n -- see POWER WARNING below.
  (b) Pool C     -- geo_accuracy_pool=1 (the broad tier, ~4,483 traders).
  (c) NEAR_LEGENDARY -- the one other clean, well-defined tier in
                    column_definitions.py's derive_tier() (1800 <=
                    geo_elo_active < 2175, clean pool member). A real
                    tier boundary, not an invented one; reported alongside
                    the full tier list (ELITE, QUALIFIED, DEVELOPING,
                    UNRANKED also exist but ELITE/QUALIFIED explicitly do
                    NOT require pool cleanliness per derive_tier's own
                    design note, and DEVELOPING/UNRANKED are catch-alls,
                    not selective conditioning variables in the same
                    spirit as (a)/(b)/(c)).

POWER WARNING: at n=9 LEGENDARY traders the present arm may be thin at
some or all horizons. Per-cell n reported at every stage; a horizon is
marked UNCOMPUTABLE (not silently fit) if n_present < MIN_N_FOR_FIT (30,
matching _fit_logistic_slope's own internal len(y)<20 guard with a
margin) or if the point-estimate fit degenerates.

Read-only throughout. --persist not implemented. No canonical definition,
harness, threshold, or ELO script modified. Does not touch or re-run the
copy-trade decay ladder. Does not restart any service.

Seed 42, reps 1500. T_SPLIT = 2026-04-01 00:00:00.
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
    snapshot_rows,
    HORIZONS_HOURS, HORIZON_LABELS, COST_FLOORS,
    oos_result_sha, OOS_RESULT_SHA_EXPECTED, git_commit,
)
from scripts.skilled_presence_causal_test import (
    base_market_features, describe, part1_characterise, match_markets,
    part2_matched, part2_survives, part3_placebo, part3_survives,
    CALIPER, BASE_RATE_STOP_PP,
)
from scripts.trader_skill_metric_v2f import T_SPLIT, SEED, GATE_REPS_LOCAL
import monitoring.column_definitions as cd

REPS = GATE_REPS_LOCAL  # 1500
MIN_N_FOR_FIT = 30  # markets; below this, mark UNCOMPUTABLE rather than fit

TIER_DEFINITIONS_REPORTED = dict(
    LEGENDARY=f"geo_elo_active >= {cd.GEO_ELO_LEGENDARY}, clean pool member (LEGENDARY_GATE_WHERE)",
    NEAR_LEGENDARY=f"{cd.GEO_ELO_NEAR_LEGENDARY} <= geo_elo_active < {cd.GEO_ELO_LEGENDARY}, clean pool member",
    ELITE=f"geo_elo_active >= {cd.GEO_ELO_ELITE} (no pool-cleanliness requirement, per derive_tier design note)",
    QUALIFIED=f"geo_elo_active >= {cd.GEO_ELO_QUALIFIED} (no pool-cleanliness requirement)",
    DEVELOPING="geo_elo_active set but < QUALIFIED threshold",
    UNRANKED="geo_elo_active IS NULL",
    POOL_C="geo_accuracy_pool = 1 (POOL_C_GATE_WHERE-populated; broad tier, not a derive_tier() rung)",
)


def tier_trader_sets(conn):
    out = {}
    rows = conn.execute(f"SELECT address FROM traders WHERE {cd.LEGENDARY_GATE_WHERE}").fetchall()
    out["LEGENDARY"] = set(r[0] for r in rows)
    rows = conn.execute("SELECT address FROM traders WHERE geo_accuracy_pool = 1").fetchall()
    out["POOL_C"] = set(r[0] for r in rows)
    rows = conn.execute(
        f"SELECT address FROM traders WHERE geo_elo_active >= {cd.GEO_ELO_NEAR_LEGENDARY} "
        f"AND geo_elo_active < {cd.GEO_ELO_LEGENDARY} AND geo_accuracy_pool = 1 "
        f"AND research_excluded = 0 AND bot_type IS NULL").fetchall()
    out["NEAR_LEGENDARY"] = set(r[0] for r in rows)
    return out


def markets_with_any_position_from(conn, pop, trader_set):
    if not trader_set:
        return set()
    mids = sorted(pop)
    present = set()
    CH = 900
    for i in range(0, len(mids), CH):
        chunk = mids[i:i + CH]
        ph = ",".join("?" for _ in chunk)
        for mid, addr in conn.execute(
            f"SELECT DISTINCT market_id, trader_address FROM positions WHERE market_id IN ({ph})", chunk):
            if addr in trader_set:
                present.add(mid)
    return present & set(pop)


def build_mdf(pop, present_mids, basefeats, clusters):
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
    return pd.DataFrame(rows)


def annotate_uncomputable(strata_dict, arm_names):
    """Post-process a {horizon: {arm: {...}}} strata dict from part2_matched
    or part3_placebo: mark an arm UNCOMPUTABLE if n < MIN_N_FOR_FIT or the
    slope point estimate is None (degenerate fit), rather than reporting a
    bootstrap CI that doesn't mean anything at that n."""
    summary = {}
    for hlabel, blk in strata_dict.items():
        summary[hlabel] = {}
        for arm in arm_names:
            g = blk.get(arm, {})
            n = g.get("n", 0)
            slope = g.get("logit_slope", {}).get("slope") if g else None
            uncomputable = bool(n < MIN_N_FOR_FIT or slope is None)
            summary[hlabel][arm] = dict(n=n, slope=slope,
                                        ci=g.get("logit_slope", {}).get("ci") if g else None,
                                        uncomputable=uncomputable,
                                        reason=("n<%d" % MIN_N_FOR_FIT if n < MIN_N_FOR_FIT
                                               else ("degenerate_fit" if slope is None else None)))
    return summary


def run_one_conditioning_variable(name, conn, pop, clusters, tape, snapshots, basefeats,
                                  trader_set, reps, seed):
    print(f"\n{'='*78}\n=== CONDITIONING VARIABLE: {name}  (n_traders={len(trader_set)}) ===\n{'='*78}")
    present_mids = markets_with_any_position_from(conn, pop, trader_set)
    print(f"  markets present: {len(present_mids)}/{len(pop)}")
    mdf = build_mdf(pop, present_mids, basefeats, clusters)
    result = dict(n_traders=len(trader_set), n_markets_present=int(mdf["present"].sum()),
                  n_markets_absent=int((~mdf["present"]).sum()))

    # ---- Part 1 ----
    part1 = part1_characterise(mdf, snapshots)
    result["part1"] = part1
    br = part1["base_rate"]
    print(f"  [Part1] base rate present={br['present_yes_rate']:.3f} absent={br['absent_yes_rate']:.3f} "
          f"gap={br['gap_pp']:+.2f}pp STOP={br['stop_condition_tripped']}")
    result["stop_after_part1"] = bool(br["stop_condition_tripped"])
    if result["stop_after_part1"]:
        print(f"  [STOP] {name}: Part 1 base-rate gap trips the stop condition -- halting before Part 2.")
        return result

    # per-horizon market-level UNCOMPUTABLE check BEFORE even matching --
    # if the present arm itself is too thin at a horizon, matching won't
    # fix that; report and continue with whichever horizons are usable.
    per_horizon_presence = {}
    for hlabel, snap in snapshots.items():
        n_h_present = int(snap["mkt"].isin(present_mids).sum())
        n_h_absent = int((~snap["mkt"].isin(present_mids)).sum())
        per_horizon_presence[hlabel] = dict(n_present=n_h_present, n_absent=n_h_absent,
                                            present_uncomputable=bool(n_h_present < MIN_N_FOR_FIT),
                                            absent_uncomputable=bool(n_h_absent < MIN_N_FOR_FIT))
    result["per_horizon_raw_presence"] = per_horizon_presence
    print("  [Part1] per-horizon raw presence n (before matching):")
    for hlabel, d in per_horizon_presence.items():
        print(f"    {hlabel:>6}: present={d['n_present']:>5} (uncomputable={d['present_uncomputable']})  "
              f"absent={d['n_absent']:>5} (uncomputable={d['absent_uncomputable']})")

    # ---- Part 2 ----
    match_result = match_markets(mdf, seed=seed)
    print(f"  [Part2] match per_category={match_result['per_category']}")
    part2 = part2_matched(mdf, snapshots, match_result, reps, seed)
    part2["uncomputable"] = annotate_uncomputable(part2["strata"], ("matched_present", "matched_absent"))
    result["part2_match"] = match_result
    result["part2"] = part2
    for hlabel, u in part2["uncomputable"].items():
        mp, ma = u["matched_present"], u["matched_absent"]
        print(f"    {hlabel:>6}: matched_present n={mp['n']:>5} slope={mp['slope']} "
              f"UNCOMPUTABLE={mp['uncomputable']}  |  matched_absent n={ma['n']:>5} slope={ma['slope']} "
              f"UNCOMPUTABLE={ma['uncomputable']}")

    part2_gate = part2_survives(part2, None, None)
    result["part2_gate"] = part2_gate
    n_usable_computable = sum(
        1 for hlabel, u in part2["uncomputable"].items()
        if not u["matched_present"]["uncomputable"] and not u["matched_absent"]["uncomputable"]
    )
    print(f"  [gate] Part2 direction preserved {part2_gate['n_horizons_direction_preserved']}/"
          f"{part2_gate['n_horizons_usable']} usable  ({n_usable_computable} horizons fully computable, "
          f"not thin-flagged) -> survives={part2_gate['survives']}")

    if n_usable_computable == 0:
        print(f"  [STOP] {name}: every horizon UNCOMPUTABLE at Part 2 -- too thin to test. "
              f"Complete finding for this arm.")
        result["all_horizons_uncomputable_at_part2"] = True
        return result
    result["all_horizons_uncomputable_at_part2"] = False

    if not part2_gate["survives"]:
        print(f"  [STOP] {name}: effect disappears/reverses under matching -- complete finding, "
              f"halting before Part 3.")
        return result

    # ---- Part 3 (gated) ----
    print(f"  [Part3] placebo, cohort={name}, n_traders={len(trader_set)}")
    part3 = part3_placebo(conn, pop, clusters, snapshots, trader_set, reps, seed)
    part3["uncomputable"] = annotate_uncomputable(part3["strata"], ("placebo_present", "placebo_absent"))
    result["part3"] = part3
    print(f"    n_classifiable_pool={part3['n_classifiable_pool']}  "
          f"n_cohort_not_in_pool={part3['n_skilled_not_in_elig_pool']}  "
          f"n_placebo_traders={part3['n_placebo_traders']}  "
          f"n_markets_placebo_present={part3['n_markets_placebo_present']}")
    same_size_achieved = bool(part3["n_placebo_traders"] == len(trader_set))
    result["placebo_same_size_achieved"] = same_size_achieved
    if not same_size_achieved:
        print(f"    [NOTE] placebo could not draw a full same-size set: got "
              f"{part3['n_placebo_traders']}/{len(trader_set)} -- classifiable pool minus cohort "
              f"({part3['n_classifiable_pool'] - len(trader_set)} candidates) is smaller than the "
              f"cohort itself. Reported as-is, not padded or re-drawn.")
    for hlabel, u in part3["uncomputable"].items():
        pp, pa = u["placebo_present"], u["placebo_absent"]
        print(f"    {hlabel:>6}: placebo_present n={pp['n']:>5} slope={pp['slope']} "
              f"UNCOMPUTABLE={pp['uncomputable']}  |  placebo_absent n={pa['n']:>5} slope={pa['slope']} "
              f"UNCOMPUTABLE={pa['uncomputable']}")

    part3_gate = part3_survives(part3)
    result["part3_gate"] = part3_gate
    print(f"  [gate] placebo shows same elevation {part3_gate['n_horizons_direction_preserved']}/"
          f"{part3_gate['n_horizons_usable']} -> placebo_replicates={part3_gate['placebo_shows_same_elevation']}")

    if part3_gate["placebo_shows_same_elevation"]:
        print(f"  [STOP] {name}: placebo shows the same elevation -- complete finding, halting before Part 4.")
        return result

    # ---- Part 4 (gated) ----
    print(f"  [Part4] edge-units deviation vs cost floors (matched arms), {name}")
    part4 = dict(cells_beyond_floor=[])
    for hlabel, blk in part2["strata"].items():
        for arm in ("matched_present", "matched_absent"):
            g = blk.get(arm, {})
            for cell in g.get("curve", []):
                ci = cell.get("deviation_ci")
                if not ci or ci[0] is None:
                    continue
                lo, hi = ci
                for cat, fl in COST_FLOORS.items():
                    beyond_lo = bool(lo > fl["lo"] or hi < -fl["lo"])
                    beyond_hi = bool(lo > fl["hi"] or hi < -fl["hi"])
                    if beyond_lo:
                        part4["cells_beyond_floor"].append(dict(
                            horizon=hlabel, arm=arm, bucket=cell["bucket"], price_lo=cell["price_lo"],
                            n=cell["n"], deviation=cell["deviation_edge"], deviation_ci=ci,
                            vs_category=cat, floor_lo=fl["lo"], floor_hi=fl["hi"], beyond_floor_hi=beyond_hi))
    result["part4"] = part4
    print(f"    cells clearing >=1 category floor_lo: {len(part4['cells_beyond_floor'])}")
    for c in part4["cells_beyond_floor"][:40]:
        print(f"      {c['horizon']:>6} {c['arm']:<16} bucket{c['bucket']} vs {c['vs_category']}: "
              f"dev={c['deviation']:+.4f} CI={c['deviation_ci']} n={c['n']} beyond_hi={c['beyond_floor_hi']}")
    return result


# --------------------------------------------------------------------------
# PART 2 -- elo_snapshots inventory (independent of Part 1)
# --------------------------------------------------------------------------

def elo_snapshots_inventory(conn, repo_dir):
    out = {}
    cols = [r[1] for r in conn.execute("PRAGMA table_info(elo_snapshots)").fetchall()]
    out["schema_columns"] = cols
    out["row_count"] = conn.execute("SELECT COUNT(*) FROM elo_snapshots").fetchone()[0]
    dr = conn.execute("SELECT MIN(snapshot_date), MAX(snapshot_date) FROM elo_snapshots").fetchone()
    out["date_range"] = dict(min=dr[0], max=dr[1])

    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT snapshot_date FROM elo_snapshots ORDER BY snapshot_date").fetchall()]
    out["n_distinct_dates"] = len(dates)
    gaps = []
    for i in range(1, len(dates)):
        d0 = datetime.strptime(dates[i - 1][:10], "%Y-%m-%d")
        d1 = datetime.strptime(dates[i][:10], "%Y-%m-%d")
        gap_days = (d1 - d0).days
        if gap_days > 1:
            gaps.append(dict(after=dates[i - 1], before=dates[i], gap_days=gap_days))
    out["date_gaps"] = gaps
    out["coverage_continuous"] = bool(len(gaps) == 0)

    out["n_distinct_traders"] = conn.execute("SELECT COUNT(DISTINCT address) FROM elo_snapshots").fetchone()[0]
    per_trader_days = conn.execute(
        "SELECT address, COUNT(DISTINCT snapshot_date) as ndays FROM elo_snapshots GROUP BY address").fetchall()
    ndays_arr = np.array([r[1] for r in per_trader_days])
    out["per_trader_snapshot_count"] = dict(
        n_traders=len(ndays_arr), mean=float(ndays_arr.mean()) if len(ndays_arr) else None,
        median=float(np.median(ndays_arr)) if len(ndays_arr) else None,
        p25=float(np.percentile(ndays_arr, 25)) if len(ndays_arr) else None,
        p75=float(np.percentile(ndays_arr, 75)) if len(ndays_arr) else None,
        max=int(ndays_arr.max()) if len(ndays_arr) else None,
    )
    for thresh in (7, 14, 30, 60):
        out[f"n_traders_with_ge_{thresh}_snapshots"] = int((ndays_arr >= thresh).sum())

    # column population: NULL vs non-NULL, and comprehensive_elo default-1500 detection
    col_stats = {}
    for col in cols:
        if col in ("snapshot_date", "address"):
            continue
        n_null = conn.execute(f"SELECT COUNT(*) FROM elo_snapshots WHERE {col} IS NULL").fetchone()[0]
        n_nonnull = out["row_count"] - n_null
        col_stats[col] = dict(n_null=n_null, n_nonnull=n_nonnull,
                              pct_null=100.0 * n_null / out["row_count"] if out["row_count"] else None)
    if "comprehensive_elo" in cols:
        n_default_1500 = conn.execute(
            "SELECT COUNT(*) FROM elo_snapshots WHERE comprehensive_elo = 1500.0").fetchone()[0]
        col_stats["comprehensive_elo"]["n_exactly_1500_default_suspect"] = n_default_1500
        col_stats["comprehensive_elo"]["pct_exactly_1500"] = (
            100.0 * n_default_1500 / out["row_count"] if out["row_count"] else None)
    out["column_stats"] = col_stats

    if "tier" in cols:
        tier_vals = conn.execute(
            "SELECT tier, COUNT(*) FROM elo_snapshots GROUP BY tier ORDER BY COUNT(*) DESC").fetchall()
        out["tier_value_counts"] = {(t if t is not None else "NULL"): c for t, c in tier_vals}
        canonical_tiers = set(["LEGENDARY", "NEAR_LEGENDARY", "ELITE", "QUALIFIED", "DEVELOPING", "UNRANKED"])
        observed_tiers = set(t for t in out["tier_value_counts"] if t != "NULL")
        out["tier_values_matching_current_derive_tier"] = sorted(observed_tiers & canonical_tiers)
        out["tier_values_NOT_matching_current_derive_tier"] = sorted(observed_tiers - canonical_tiers)

    # who reads elo_snapshots? search both repos
    def grep_readers(root, exclude_self):
        hits = []
        for dirpath, dirnames, filenames in os.walk(root):
            if "/.git" in dirpath or "__pycache__" in dirpath:
                continue
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(dirpath, fn)
                if os.path.abspath(fp) == os.path.abspath(exclude_self):
                    continue
                try:
                    with open(fp, "r", errors="ignore") as f:
                        content = f.read()
                except Exception:
                    continue
                if "elo_snapshots" in content:
                    is_writer = ("INSERT INTO elo_snapshots" in content or "CREATE TABLE elo_snapshots" in content
                                or "INTO elo_snapshots" in content)
                    hits.append(dict(file=os.path.relpath(fp, root), looks_like_writer=is_writer))
        return hits

    self_path = os.path.join(repo_dir, "scripts", "elo_tier_causal_test.py")
    fr_hits = grep_readers(repo_dir, self_path)
    ts_root = os.path.expanduser("~/trading-swarm")
    ts_hits = grep_readers(ts_root, self_path) if os.path.isdir(ts_root) else []
    out["references_first_repo"] = fr_hits
    out["references_trading_swarm"] = ts_hits
    out["any_reader_found"] = bool(any(not h["looks_like_writer"] for h in fr_hits + ts_hits))

    return out


# --------------------------------------------------------------------------
# selfcheck
# --------------------------------------------------------------------------

def selfcheck():
    ok = True
    d = describe([1, 2, 3, 4, 5])
    ok &= (d["median"] == 3.0)
    # annotate_uncomputable: n below threshold flags correctly
    fake_strata = {"h0.5h": {"arm_a": dict(n=5, logit_slope=dict(slope=1.2, ci=[1.0, 1.4])),
                             "arm_b": dict(n=500, logit_slope=dict(slope=1.1, ci=[1.0, 1.2]))}}
    ann = annotate_uncomputable(fake_strata, ("arm_a", "arm_b"))
    ok &= ann["h0.5h"]["arm_a"]["uncomputable"] is True
    ok &= ann["h0.5h"]["arm_b"]["uncomputable"] is False
    # tier definition self-consistency: LEGENDARY threshold < what a clean
    # NEAR_LEGENDARY trader could reach (sanity on the constants used)
    ok &= cd.GEO_ELO_NEAR_LEGENDARY < cd.GEO_ELO_LEGENDARY
    print(f"[selfcheck] describe={d['median']==3.0}  uncomputable_flagging_ok="
          f"{ann['h0.5h']['arm_a']['uncomputable'] and not ann['h0.5h']['arm_b']['uncomputable']}  "
          f"tier_thresholds_ordered={cd.GEO_ELO_NEAR_LEGENDARY < cd.GEO_ELO_LEGENDARY}")
    return ok


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/polymarket_tracker.db")
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--skip-part1", action="store_true", help="run only the elo_snapshots inventory")
    ap.add_argument("--skip-part2", action="store_true", help="run only the ELO-tier calibration test")
    args = ap.parse_args()

    if args.selfcheck:
        ok = selfcheck()
        print("[selfcheck] " + ("PASSED" if ok else "FAILED"))
        if not ok:
            sys.exit(1)

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    conn = db_connect(args.db)

    sha_before = oos_result_sha(args.db)
    print(f"[stop-cond] metric_v2f_oos_result sha256 BEFORE: {sha_before}")
    if sha_before != OOS_RESULT_SHA_EXPECTED:
        print("[STOP] metric_v2f_oos_result sha256 != expected", file=sys.stderr)
        sys.exit(3)

    inventory = None
    if not args.skip_part2:
        print("\n" + "#" * 78 + "\n# PART 2 (independent) -- elo_snapshots inventory\n" + "#" * 78)
        inventory = elo_snapshots_inventory(conn, repo_dir)
        print(f"  rows={inventory['row_count']}  dates={inventory['n_distinct_dates']}  "
              f"range={inventory['date_range']}  gaps={len(inventory['date_gaps'])}  "
              f"distinct_traders={inventory['n_distinct_traders']}")
        print(f"  any_reader_found={inventory['any_reader_found']}")

    tier_results = None
    if not args.skip_part1:
        print("\n" + "#" * 78 + "\n# PART 1 -- ELO-tier-conditioned calibration\n" + "#" * 78)
        print("[framing] ELO tier used ONLY as a conditioning variable on mispricing, "
              "NEVER as a skill measure or selector. See MASTER_HANDOVER_2026-08-15 Section 1.")

        print("[load] population ...")
        pop, popmeta = load_population(conn)
        clusters, clmeta = load_event_clusters(conn, list(pop))
        print("[load] trade tape ...")
        tape = load_tape(conn, list(pop))
        print("[load] per-market base features ...")
        basefeats = base_market_features(conn, list(pop))
        print("[compute] six-horizon price snapshots ...")
        snapshots = {}
        for h, hlabel in zip(HORIZONS_HOURS, HORIZON_LABELS):
            df, meta = snapshot_rows(pop, clusters, tape, h)
            snapshots[hlabel] = df

        tiers = tier_trader_sets(conn)
        print(f"[tiers] current counts: LEGENDARY={len(tiers['LEGENDARY'])}  "
              f"POOL_C={len(tiers['POOL_C'])}  NEAR_LEGENDARY={len(tiers['NEAR_LEGENDARY'])}")

        tier_results = dict(tier_definitions=TIER_DEFINITIONS_REPORTED,
                            tier_counts={k: len(v) for k, v in tiers.items()}, arms={})
        for name in ("LEGENDARY", "NEAR_LEGENDARY", "POOL_C"):
            tier_results["arms"][name] = run_one_conditioning_variable(
                name, conn, pop, clusters, tape, snapshots, basefeats,
                tiers[name], args.reps, args.seed)

    sha_after = oos_result_sha(args.db)
    print(f"\n[stop-cond] metric_v2f_oos_result sha256 AFTER:  {sha_after}")
    conn.close()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_out = args.json_out or f"data/characterizations/elo_tier_causal_test_{ts}.json"
    artifact = dict(
        spec="elo_tier_causal_test",
        generated_at=datetime.now(timezone.utc).isoformat(),
        script_commit=git_commit(repo_dir),
        params=dict(t_split=T_SPLIT, seed=args.seed, reps=args.reps, caliper=CALIPER,
                    base_rate_stop_pp=BASE_RATE_STOP_PP, min_n_for_fit=MIN_N_FOR_FIT,
                    horizon_labels=HORIZON_LABELS, cost_floors=COST_FLOORS,
                    legendary_gate_where=cd.LEGENDARY_GATE_WHERE,
                    geo_elo_legendary=cd.GEO_ELO_LEGENDARY, geo_elo_near_legendary=cd.GEO_ELO_NEAR_LEGENDARY),
        oos_result_sha_before=sha_before, oos_result_sha_after=sha_after,
        oos_result_unchanged=bool(sha_before == sha_after == OOS_RESULT_SHA_EXPECTED),
        framing=("ELO tier used strictly as a conditioning variable on market mispricing, "
                 "never as a skill measure or selector -- geo_elo is condemned for skill-ranking, "
                 "MASTER_HANDOVER_2026-08-15 Section 1. Nothing here reopens that."),
        elo_tier_test=tier_results,
        elo_snapshots_inventory=inventory,
    )
    os.makedirs(os.path.dirname(json_out), exist_ok=True)
    with open(json_out, "w") as f:
        json.dump(artifact, f, indent=2, default=str)
    print(f"[artifact] {json_out}")
    if sha_before != sha_after:
        print("[STOP] metric_v2f_oos_result CHANGED during the run.", file=sys.stderr)
        sys.exit(3)
    print("\n[done] oos_result_unchanged=True")


if __name__ == "__main__":
    main()
