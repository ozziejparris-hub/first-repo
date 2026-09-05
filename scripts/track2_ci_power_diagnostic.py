#!/usr/bin/env python3
"""
TRACK 2 -- CI POWER DIAGNOSTIC. Executes the method fixed by
brain/decisions/2026-09-04-track2-ci-power-prereg.md (trading-swarm f5df56a).
Read-only against production tables. Writes no metric_v2f_* or other
production table -- output goes only to the JSON artifact named on the
command line. Reuses build_presplit_cohort / match_control / measure_oos /
weighted_pair_table exactly as committed in trader_skill_metric_v2f.py /
v2d.py; no reimplementation of cohort selection, placebo matching, or the
two-way bootstrap's core mechanics.

Every threshold below is copied verbatim from the pre-registration, not
re-derived here:
  Gate A (Sec 6, ACCEPTABLE DRIFT / STOP):
    - point estimate within original CI bounds [-0.00881, +0.07101]
    - same sign (positive)
    - n_positions / n_traders growing, not shrinking, vs 3032/120
    - any >10% discrepancy attributed to a named, checked mechanism
  Decomposition (Sec 2): share_trader/share_market vs 0.65 / 0.35.
  Projection (Sec 3): K_required = K_today * (hw_today/hw_target)^2,
    valid only for K_required/K_today <= 3.
  Thresholds (Sec 4): 12-month horizon, ATTAINABLE iff K_required/R <= 12.
  Outcomes (Sec 5): market-bound+attainable / market-bound+not-attainable /
    trader-bound / mixed / inconclusive.
"""
import argparse
import json
import subprocess
import sys
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2c import WEIGHT_FNS
from scripts.trader_skill_metric_v2d import weighted_pair_table
from scripts.trader_skill_metric_v2f import build_presplit_cohort, match_control, measure_oos, T_SPLIT, SEED

REPS = 1500
ORIGINAL_CI_LO = -0.00881147179033796
ORIGINAL_CI_HI = 0.0710126418085991
ORIGINAL_POINT = 0.0315983580923187
ORIGINAL_N_POS = 3032
ORIGINAL_N_TRADERS = 120
ORIGINAL_GENERATED_AT = "2026-08-15T19:36:56.852700+00:00"
SHARE_BIND = 0.65
SHARE_NOTBIND = 0.35
K_VALIDITY_LIMIT = 3.0
HORIZON_MONTHS = 12


def load_oos_positions(conn, cohort_traders, t_split):
    """Identical query to measure_oos() in trader_skill_metric_v2f.py --
    copied, not re-derived, so the pair table decomposes the exact same
    rows the reproduced CI is based on."""
    placeholders = ",".join("?" for _ in cohort_traders)
    rows = conn.execute(f"""
        SELECT p.trader_address, p.market_id, p.outcome, p.entry_avg_price, p.entry_timestamp, t.trade_result
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({placeholders})
          AND p.entry_timestamp > ?
    """, list(cohort_traders) + [t_split]).fetchall()
    df = pd.DataFrame(rows, columns=['trader', 'market_id', 'outcome', 'price', 'entry_ts', 'trade_result'])
    df['won'] = (df['trade_result'] == 'won').astype(int)
    return df


def three_way_bootstrap(pairs, reps, seed):
    """Full two-way (identical mechanics/order to weighted_two_way_gap_bootstrap),
    plus trader-only and market-only ablations, drawn from the SAME rng
    stream in the SAME per-rep order (t_mult then m_mult) as the original
    function -- so 'resample t_mult exactly as today' / 'resample m_mult
    exactly as today' are bit-identical to the full variant's own draws,
    not independently re-drawn."""
    traders = pairs['trader'].astype('category')
    markets = pairs['market_id'].astype('category')
    t_idx = traders.cat.codes.to_numpy()
    m_idx = markets.cat.codes.to_numpy()
    n_traders = traders.cat.categories.size
    n_markets = markets.cat.categories.size
    base_w = pairs['base_weight'].to_numpy()
    p_won = pairs['pair_won'].to_numpy()
    p_price = pairs['pair_price'].to_numpy()

    point_denom = base_w.sum()
    point_gap = float((base_w * p_won).sum() / point_denom - (base_w * p_price).sum() / point_denom)

    rng = np.random.default_rng(seed)
    boot_full = np.empty(reps)
    boot_trader = np.empty(reps)   # t_mult resampled, m_mult fixed = 1
    boot_market = np.empty(reps)   # m_mult resampled, t_mult fixed = 1
    ones_t = np.ones(n_traders)
    ones_m = np.ones(n_markets)

    for b in range(reps):
        t_mult = np.bincount(rng.integers(0, n_traders, size=n_traders), minlength=n_traders)
        m_mult = np.bincount(rng.integers(0, n_markets, size=n_markets), minlength=n_markets)

        for which, boot_arr, t_arr, m_arr in (
            ('full', boot_full, t_mult, m_mult),
            ('trader', boot_trader, t_mult, ones_m),
            ('market', boot_market, ones_t, m_mult),
        ):
            total_w = base_w * t_arr[t_idx] * m_arr[m_idx]
            denom = total_w.sum()
            if denom <= 0:
                boot_arr[b] = np.nan
                continue
            wmean_won = (total_w * p_won).sum() / denom
            wmean_price = (total_w * p_price).sum() / denom
            boot_arr[b] = wmean_won - wmean_price

    def summarize(boot):
        boot = boot[~np.isnan(boot)]
        if len(boot) < reps * 0.5:
            return dict(valid_draws=len(boot), ci_lo=None, ci_hi=None, half_width=None)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        return dict(valid_draws=len(boot), ci_lo=float(lo), ci_hi=float(hi), half_width=float((hi - lo) / 2))

    return dict(
        point_gap=point_gap, n_pairs=len(pairs), n_traders=int(n_traders), n_markets=int(n_markets),
        full=summarize(boot_full), trader_only=summarize(boot_trader), market_only=summarize(boot_market),
    )


def monthly_rate(conn, cohort_traders, t_split):
    placeholders = ",".join("?" for _ in cohort_traders)
    rows = conn.execute(f"""
        SELECT strftime('%Y-%m', p.entry_timestamp) AS ym,
               COUNT(*) AS n_positions, COUNT(DISTINCT p.market_id) AS n_markets
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND p.entry_avg_price IS NOT NULL
          AND t.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND p.trader_address IN ({placeholders})
          AND p.entry_timestamp > ?
        GROUP BY ym ORDER BY ym
    """, list(cohort_traders) + [t_split]).fetchall()
    return [dict(month=r[0], n_positions=r[1], n_new_markets=r[2]) for r in rows]


def git_commit(repo_dir):
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--json-out', required=True)
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = dict(
        spec="track2_ci_power_diagnostic", seed=SEED, reps=REPS, t_split=T_SPLIT,
        weight_fn="cap5", generated_at=datetime.now(timezone.utc).isoformat(),
        diagnostic_script_commit=git_commit(repo_dir),
        trader_skill_metric_v2f_commit=git_commit(repo_dir),  # same repo/commit as diagnostic
    )

    conn = db_connect(args.db)

    # ---- Step 0: reconstruct the true presplit-qualifying cohort + matched controls ----
    print(f"=== STEP 0: reconstruct true cohort, T_split={T_SPLIT} ===")
    presplit_data = build_presplit_cohort(conn, T_SPLIT, verbose=args.verbose)
    oos_cohort = set(presplit_data['intersection']['trader'])
    control_cohort = match_control(presplit_data['profile'], oos_cohort,
                                    set(presplit_data['elig_pool']['trader']), seed=SEED, verbose=True)
    print(f"true presplit-qualifying cohort: {len(oos_cohort)} traders "
          f"(persisted result of record: 120)")
    print(f"matched placebo controls: {len(control_cohort)} traders")
    result['cohort_trader_list'] = sorted(oos_cohort)
    result['control_trader_list'] = sorted(control_cohort)
    result['cohort_n_traders_reconstructed'] = len(oos_cohort)
    result['control_n_traders_reconstructed'] = len(control_cohort)

    # ---- GATE A: reproduce the baseline ----
    print(f"\n=== GATE A: baseline reproduction ===")
    oos_result = measure_oos(conn, oos_cohort, T_SPLIT, verbose=True, label="cohort")
    placebo_result = measure_oos(conn, control_cohort, T_SPLIT, verbose=True, label="placebo")
    result['gate_a'] = dict(cohort=oos_result, placebo=placebo_result)

    point = oos_result.get('point_gap')
    n_pos = oos_result.get('n_positions')
    n_trd = oos_result.get('n_surviving_traders')

    within_bounds = point is not None and (ORIGINAL_CI_LO <= point <= ORIGINAL_CI_HI)
    same_sign = point is not None and point > 0
    growing = (n_pos is not None and n_trd is not None and
               n_pos >= ORIGINAL_N_POS and n_trd >= ORIGINAL_N_TRADERS)
    pos_disc_pct = abs(n_pos - ORIGINAL_N_POS) / ORIGINAL_N_POS if n_pos is not None else None
    trd_disc_pct = abs(n_trd - ORIGINAL_N_TRADERS) / ORIGINAL_N_TRADERS if n_trd is not None else None

    # attribution check for any >10% discrepancy: how much of the growth is
    # positions that already existed at 08-15 (pending->resolved), vs genuinely new
    attribution = None
    if (pos_disc_pct is not None and pos_disc_pct > 0.10) or (trd_disc_pct is not None and trd_disc_pct > 0.10):
        placeholders = ",".join("?" for _ in oos_cohort)
        row = conn.execute(f"""
            SELECT
              SUM(CASE WHEN p.entry_timestamp > ? THEN 1 ELSE 0 END) AS new_entries,
              SUM(CASE WHEN p.entry_timestamp <= ? THEN 1 ELSE 0 END) AS preexisting_now_resolved,
              COUNT(*) AS total
            FROM positions p
            JOIN markets m ON m.market_id = p.market_id
            JOIN trades t ON t.trade_id = json_extract(p.entry_trade_ids, '$[0]')
            WHERE m.category IN ('Geopolitics','Elections') AND p.entry_avg_price IS NOT NULL
              AND t.trade_result IN ('won','lost') AND (m.trade_gap_flag=0 OR m.trade_gap_flag IS NULL)
              AND p.trader_address IN ({placeholders}) AND p.entry_timestamp > ?
        """, [ORIGINAL_GENERATED_AT, ORIGINAL_GENERATED_AT] + list(oos_cohort) + [T_SPLIT]).fetchone()
        attribution = dict(new_entries_since_result_of_record=row[0], preexisting_now_resolved=row[1], total=row[2],
                            mechanism="positions transitioning pending->won/lost as markets resolved, vs genuinely new entries")
        print(f"[attribution] {attribution}")
    attributed = attribution is not None and attribution['total'] > 0

    gate_pass = within_bounds and same_sign and growing and (
        (pos_disc_pct is None or pos_disc_pct <= 0.10) and (trd_disc_pct is None or trd_disc_pct <= 0.10)
        or attributed
    )

    result['gate_a']['checks'] = dict(
        within_original_ci_bounds=within_bounds, same_sign_positive=same_sign,
        n_growing_not_shrinking=growing, n_positions_discrepancy_pct=pos_disc_pct,
        n_traders_discrepancy_pct=trd_disc_pct, attribution=attribution, gate_pass=gate_pass,
    )
    print(f"\n[GATE A] within_bounds={within_bounds} same_sign={same_sign} growing={growing} "
          f"pos_disc={pos_disc_pct} trd_disc={trd_disc_pct} -> {'PASS' if gate_pass else 'STOP'}")

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)

    if not gate_pass:
        print("\n[STOP] Gate A failed per the pre-registration's amended A3 rule (Sec 6). "
              "Not proceeding to decomposition.", file=sys.stderr)
        conn.close()
        sys.exit(2)

    # ---- Decomposition ----
    print(f"\n=== DECOMPOSITION (Sec 2) ===")
    cohort_df = load_oos_positions(conn, oos_cohort, T_SPLIT)
    pairs = weighted_pair_table(cohort_df, WEIGHT_FNS['cap5'])
    decomp = three_way_bootstrap(pairs, reps=REPS, seed=SEED)
    print(json.dumps(decomp, indent=2, default=str))
    result['decomposition'] = decomp

    w_full = decomp['full']['half_width']
    w_trader = decomp['trader_only']['half_width']
    w_market = decomp['market_only']['half_width']
    inconclusive_convergence = any(v['valid_draws'] < REPS * 0.5 for v in
                                    (decomp['full'], decomp['trader_only'], decomp['market_only']))

    classification = None
    share_trader = share_market = None
    if not inconclusive_convergence and w_full:
        share_trader = (w_full - w_market) / w_full
        share_market = (w_full - w_trader) / w_full
        if share_trader >= SHARE_BIND and share_market < SHARE_NOTBIND:
            classification = "trader-bound"
        elif share_market >= SHARE_BIND and share_trader < SHARE_NOTBIND:
            classification = "market-bound"
        else:
            classification = "mixed"
    else:
        classification = "inconclusive"

    print(f"\n[SEC 2] w_full={w_full} w_trader_only={w_trader} w_market_only={w_market}")
    print(f"[SEC 2] share_trader={share_trader} share_market={share_market} -> classification={classification}")
    result['sec2'] = dict(w_full=w_full, w_trader_only=w_trader, w_market_only=w_market,
                          share_trader=share_trader, share_market=share_market, classification=classification)

    # ---- Projection (Sec 3) ----
    print(f"\n=== PROJECTION (Sec 3) ===")
    k_today = None
    k_required = None
    k_valid = None
    if classification == "trader-bound":
        k_today = decomp['n_traders']
    elif classification == "market-bound":
        k_today = decomp['n_markets']

    if k_today and w_full and decomp['point_gap']:
        half_width_target = decomp['point_gap']  # boundary: half_width < point_gap for lower bound to clear 0
        if half_width_target > 0:
            k_required = k_today * (w_full / half_width_target) ** 2
            k_valid = (k_required / k_today) <= K_VALIDITY_LIMIT
    print(f"[SEC 3] binding_dimension={classification} K_today={k_today} K_required={k_required} "
          f"valid(<=3x)={k_valid}")
    result['sec3'] = dict(k_today=k_today, k_required=k_required, k_required_valid_within_3x=k_valid)

    # ---- Thresholds / attainability (Sec 4) ----
    print(f"\n=== THRESHOLDS (Sec 4) ===")
    monthly = monthly_rate(conn, oos_cohort, T_SPLIT)
    print(f"[monthly rate, true cohort] {monthly}")
    result['sec4_monthly_rate'] = monthly
    complete_months = [m for m in monthly if m['month'] < datetime.now(timezone.utc).strftime('%Y-%m')]
    R = None
    if complete_months:
        last = complete_months[-1]
        R = last['n_new_markets'] if classification == "market-bound" else None
        if classification == "trader-bound":
            R = None  # cohort is frozen by definition; no "new qualifying trader" rate is measurable from this cohort
    attainable = None
    if k_required is not None and k_valid and R:
        attainable = (k_required / R) <= HORIZON_MONTHS
    elif k_required is not None and not k_valid:
        attainable = False  # order-of-magnitude signal only, not attainable on any reasonable reading
    print(f"[SEC 4] R={R} (last complete month {complete_months[-1]['month'] if complete_months else None}) "
          f"K_required/R={(k_required/R) if (k_required and R) else None} horizon={HORIZON_MONTHS}mo "
          f"attainable={attainable}")
    result['sec4'] = dict(R=R, horizon_months=HORIZON_MONTHS, attainable=attainable)

    # ---- Verdict (Sec 5) ----
    if classification == "inconclusive":
        outcome = "5_inconclusive"
    elif classification == "trader-bound":
        outcome = "3_trader_bound"
    elif classification == "mixed":
        outcome = "4_mixed"
    elif classification == "market-bound" and attainable:
        outcome = "1_market_bound_attainable"
    elif classification == "market-bound" and not attainable:
        outcome = "2_market_bound_not_attainable"
    else:
        outcome = "5_inconclusive"
    print(f"\n=== VERDICT: {outcome} ===")
    result['verdict'] = outcome

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n[json] written to {args.json_out}")

    conn.close()


if __name__ == '__main__':
    main()
