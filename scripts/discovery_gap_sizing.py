#!/usr/bin/env python3
"""
Sizes the Gamma resolution-discovery blind spot (2026-08-20).

READ-ONLY: queries the DB and the CLOB API, writes no data anywhere except
its own output files under data/characterizations/. Does not modify
markets, trades, or any other table. Implements exactly the method fixed
in brain/decisions/2026-08-20-discovery-gap-sizing-prereg.md (trading-swarm
repo) -- nothing here may diverge from that document. See that document
for the full rationale; this file is the mechanical implementation.

Usage:
    python3 scripts/discovery_gap_sizing.py
"""

import json
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
CLOB_API = "https://clob.polymarket.com/markets"
OUT_DIR = Path(__file__).parent.parent / "data" / "characterizations"
OUT_DIR.mkdir(exist_ok=True)
TODAY = datetime(2026, 8, 20)

RNG_SEED = 20260820
RATE_LIMIT_SLEEP = 0.25


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Population + stratification (§1, §3, §4 of the pre-registration)
# ---------------------------------------------------------------------------

def get_stratum_g(conn):
    """Geo/Elections, has trades, gap-flag clean. Full census population."""
    rows = conn.execute("""
        SELECT DISTINCT m.market_id, m.condition_id, m.category, m.data_source
        FROM markets m
        JOIN trades t ON t.market_id = m.market_id
        WHERE (m.resolved = 0 OR m.resolved IS NULL)
          AND m.resolution_date IS NULL AND m.end_date IS NULL
          AND m.category IN ('Elections', 'Geopolitics')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
        ORDER BY m.market_id ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_stratum_z(conn):
    """Zero trades, any category."""
    rows = conn.execute("""
        SELECT m.market_id, m.condition_id, m.category, m.data_source
        FROM markets m
        LEFT JOIN (SELECT DISTINCT market_id FROM trades) t ON t.market_id = m.market_id
        WHERE (m.resolved = 0 OR m.resolved IS NULL)
          AND m.resolution_date IS NULL AND m.end_date IS NULL
          AND t.market_id IS NULL
        ORDER BY m.market_id ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_stratum_o_with_tape_start(conn):
    """Everything else: has trades, not in G. Returns rows with tape_start."""
    rows = conn.execute("""
        SELECT m.market_id, m.condition_id, m.category, m.data_source,
               MIN(t.timestamp) AS tape_start
        FROM markets m
        JOIN trades t ON t.market_id = m.market_id
        WHERE (m.resolved = 0 OR m.resolved IS NULL)
          AND m.resolution_date IS NULL AND m.end_date IS NULL
          AND NOT (
              m.category IN ('Elections', 'Geopolitics')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          )
        GROUP BY m.market_id
        ORDER BY m.market_id ASC
    """).fetchall()
    return [dict(r) for r in rows]


def split_o_terciles(o_rows):
    """Split O by tape_start into thirds, using literal positional terciles
    of the tape_start-sorted list (matches pre-registration §4)."""
    sorted_rows = sorted(o_rows, key=lambda r: r["tape_start"])
    n = len(sorted_rows)
    t1_end = n // 3
    t2_end = 2 * n // 3
    return {
        "O-oldest": sorted_rows[:t1_end],
        "O-middle": sorted_rows[t1_end:t2_end],
        "O-newest": sorted_rows[t2_end:],
    }


# ---------------------------------------------------------------------------
# CLOB query + classification (§2 of the pre-registration)
# ---------------------------------------------------------------------------

def build_clob_id(row):
    condition_id = row.get("condition_id")
    market_id = row.get("market_id") or ""
    if condition_id:
        return condition_id
    if len(market_id) == 64 and not market_id.startswith("0x"):
        return "0x" + market_id
    if market_id:
        return market_id
    return None


def query_clob(session, clob_id):
    """Returns (classification, detail_dict). classification in
    {"resolved", "open", "indeterminate"}."""
    if clob_id is None:
        return "indeterminate", {"reason": "no_queryable_identifier"}

    url = f"{CLOB_API}/{clob_id}"
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = session.get(url, timeout=15)
            break
        except (requests.exceptions.RequestException,) as e:
            if attempt >= 2:
                return "indeterminate", {"reason": "request_error", "detail": str(e)}
            time.sleep(2)

    if resp.status_code != 200:
        return "indeterminate", {"reason": f"http_{resp.status_code}"}

    try:
        data = resp.json()
    except Exception:
        return "indeterminate", {"reason": "unparseable_json"}

    closed = data.get("closed")
    if closed is None:
        return "indeterminate", {"reason": "closed_field_missing"}

    if closed is False:
        return "open", {}

    # closed == True
    winner_outcome = None
    for token in data.get("tokens", []) or []:
        if token.get("winner"):
            winner_outcome = token.get("outcome")
            break

    if winner_outcome is None:
        return "indeterminate", {"reason": "closed_no_winner_token"}

    return "resolved", {"winner": winner_outcome}


def run_stratum(session, name, rows):
    results = []
    for i, row in enumerate(rows, 1):
        clob_id = build_clob_id(row)
        classification, detail = query_clob(session, clob_id)
        results.append({
            "market_id": row["market_id"],
            "category": row.get("category"),
            "data_source": row.get("data_source"),
            "clob_id": clob_id,
            "classification": classification,
            "detail": detail,
        })
        if i % 25 == 0 or i == len(rows):
            print(f"  [{name}] {i}/{len(rows)} — "
                  f"resolved={sum(1 for r in results if r['classification']=='resolved')} "
                  f"open={sum(1 for r in results if r['classification']=='open')} "
                  f"indeterminate={sum(1 for r in results if r['classification']=='indeterminate')}")
        time.sleep(RATE_LIMIT_SLEEP)
    return results


# ---------------------------------------------------------------------------
# Estimation (§6 of the pre-registration)
# ---------------------------------------------------------------------------

def wilson_ci(resolved, determinate, z=1.96):
    if determinate == 0:
        return None
    p = resolved / determinate
    n = determinate
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    halfwidth = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return {"point": p, "lo": max(0.0, center - halfwidth), "hi": min(1.0, center + halfwidth)}


def stratum_summary(results):
    n = len(results)
    resolved = sum(1 for r in results if r["classification"] == "resolved")
    open_ = sum(1 for r in results if r["classification"] == "open")
    indet = sum(1 for r in results if r["classification"] == "indeterminate")
    determinate = resolved + open_
    ci = wilson_ci(resolved, determinate)
    return {
        "n": n, "resolved": resolved, "open": open_, "indeterminate": indet,
        "determinate": determinate,
        "indeterminate_rate": indet / n if n else None,
        "resolved_fraction_of_determinate": (resolved / determinate) if determinate else None,
        "wilson_95ci": ci,
    }


def stratified_q1_estimate(strata_summaries_with_N):
    """strata_summaries_with_N: list of (N_h, summary_dict)."""
    N_total = sum(N for N, _ in strata_summaries_with_N)
    p_hat_overall = sum(
        N * (s["resolved_fraction_of_determinate"] or 0.0)
        for N, s in strata_summaries_with_N
    ) / N_total

    var = 0.0
    for N, s in strata_summaries_with_N:
        n_h = s["determinate"]
        p_h = s["resolved_fraction_of_determinate"]
        if n_h is None or n_h < 2 or p_h is None:
            continue
        fpc = max(0.0, 1 - n_h / N) if N else 0.0
        var += ((N / N_total) ** 2) * fpc * (p_h * (1 - p_h)) / (n_h - 1)

    halfwidth = 1.96 * (var ** 0.5)
    return {
        "N_total": N_total,
        "p_hat": p_hat_overall,
        "ci_lo": max(0.0, p_hat_overall - halfwidth),
        "ci_hi": min(1.0, p_hat_overall + halfwidth),
    }


# ---------------------------------------------------------------------------
# Cross-check (§8 of the pre-registration)
# ---------------------------------------------------------------------------

def cross_check_resolved(conn, resolved_rows, limit=15):
    checked = []
    for row in resolved_rows[:limit]:
        r = conn.execute(
            "SELECT MAX(timestamp) FROM trades WHERE market_id = ?",
            (row["market_id"],),
        ).fetchone()
        tape_end = r[0] if r else None
        if tape_end:
            tape_end_dt = datetime.fromisoformat(tape_end.replace("Z", "").split(".")[0])
            days_before_today = (TODAY - tape_end_dt).days
            corroborating = days_before_today > 30
        else:
            days_before_today = None
            corroborating = None
        checked.append({
            "market_id": row["market_id"],
            "tape_end": tape_end,
            "days_before_today": days_before_today,
            "corroborating": corroborating,
        })
    return checked


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    random.seed(RNG_SEED)
    conn = _conn()
    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketDiscoveryGapSizing/1.0"})

    print("=" * 70)
    print("Loading populations (no CLOB calls yet)")
    print("=" * 70)
    g_all = get_stratum_g(conn)
    z_all = get_stratum_z(conn)
    o_all = get_stratum_o_with_tape_start(conn)
    print(f"G (Geo/Elections, has trades): N={len(g_all)}")
    print(f"Z (zero trades): N={len(z_all)}")
    print(f"O (residual): N={len(o_all)}")

    o_terciles = split_o_terciles(o_all)
    for name, rows in o_terciles.items():
        ts_min = min(r["tape_start"] for r in rows) if rows else None
        ts_max = max(r["tape_start"] for r in rows) if rows else None
        print(f"  {name}: N={len(rows)}  tape_start range [{ts_min}, {ts_max}]")

    print("\nSampling (seed={})".format(RNG_SEED))
    z_sample = random.sample(z_all, min(60, len(z_all)))
    o_samples = {
        name: random.sample(rows, min(50, len(rows)))
        for name, rows in o_terciles.items()
    }
    print(f"Z sample: n={len(z_sample)}")
    for name, s in o_samples.items():
        print(f"{name} sample: n={len(s)}")

    total_calls = len(g_all) + len(z_sample) + sum(len(s) for s in o_samples.values())
    print(f"\nTotal CLOB calls planned: {total_calls}")

    print("\n" + "=" * 70)
    print("Querying CLOB — G (full census, this IS Q2)")
    print("=" * 70)
    g_results = run_stratum(session, "G", g_all)

    print("\n" + "=" * 70)
    print("Querying CLOB — Z (sample)")
    print("=" * 70)
    z_results = run_stratum(session, "Z", z_sample)

    o_results = {}
    for name, sample in o_samples.items():
        print("\n" + "=" * 70)
        print(f"Querying CLOB — {name} (sample)")
        print("=" * 70)
        o_results[name] = run_stratum(session, name, sample)

    # ---- Summaries ----
    print("\n" + "=" * 70)
    print("SUMMARIES")
    print("=" * 70)

    g_summary = stratum_summary(g_results)
    z_summary = stratum_summary(z_results)
    o_summaries = {name: stratum_summary(res) for name, res in o_results.items()}

    print(f"G (=Q2 census): {json.dumps(g_summary, indent=2, default=str)}")
    print(f"Z: {json.dumps(z_summary, indent=2, default=str)}")
    for name, s in o_summaries.items():
        print(f"{name}: {json.dumps(s, indent=2, default=str)}")

    # Q1 overall: stratified combination of G, Z, O (O's 3 terciles pooled
    # into one O-level summary weighted by tercile population, then G/Z/O
    # combined weighted by full population).
    o_N_total = sum(len(rows) for rows in o_terciles.values())
    o_pooled_resolved = sum(s["resolved"] for s in o_summaries.values())
    o_pooled_determinate = sum(s["determinate"] for s in o_summaries.values())
    o_pooled_n = sum(s["n"] for s in o_summaries.values())
    o_pooled_indet = sum(s["indeterminate"] for s in o_summaries.values())
    o_pooled_summary = {
        "n": o_pooled_n, "resolved": o_pooled_resolved,
        "determinate": o_pooled_determinate, "indeterminate": o_pooled_indet,
        "indeterminate_rate": o_pooled_indet / o_pooled_n if o_pooled_n else None,
        "resolved_fraction_of_determinate": (o_pooled_resolved / o_pooled_determinate) if o_pooled_determinate else None,
        "wilson_95ci": wilson_ci(o_pooled_resolved, o_pooled_determinate),
    }

    q1_overall = stratified_q1_estimate([
        (len(g_all), g_summary),
        (len(z_all), z_summary),
        (o_N_total, o_pooled_summary),
    ])

    print("\nO (pooled across 3 terciles):", json.dumps(o_pooled_summary, indent=2, default=str))
    print("\nQ1 OVERALL (stratified):", json.dumps(q1_overall, indent=2, default=str))

    # Q2 census bounds
    g_resolved_rows = [r for r in g_results if r["classification"] == "resolved"]
    q2_best_case = g_summary["resolved"]  # indeterminate presumed open
    q2_worst_case = g_summary["resolved"] + g_summary["indeterminate"]  # indeterminate presumed resolved
    print(f"\nQ2 census bounds: best_case(indet=open)={q2_best_case}  "
          f"worst_case(indet=resolved)={q2_worst_case}  "
          f"determinate_point_estimate_count={g_summary['resolved']} of {g_summary['determinate']} determinate "
          f"(N={len(g_all)} total census)")

    # ---- Cross-check ----
    print("\n" + "=" * 70)
    print("CROSS-CHECK (tape_end for Q2 resolved rows)")
    print("=" * 70)
    cross_checked = cross_check_resolved(conn, g_resolved_rows, limit=15)
    for c in cross_checked:
        print(f"  {c['market_id'][:30]}...  tape_end={c['tape_end']}  "
              f"days_before_today={c['days_before_today']}  corroborating={c['corroborating']}")

    # ---- Data-source / boundary-check breakdowns ----
    def data_source_breakdown(results):
        counts = {}
        for r in results:
            ds = r.get("data_source") or "NULL"
            counts[ds] = counts.get(ds, 0) + 1
        return counts

    g_ds_all = data_source_breakdown([{"data_source": r["data_source"]} for r in g_all])
    g_ds_resolved = data_source_breakdown(g_resolved_rows)

    # ---- Write full output ----
    out = {
        "rng_seed": RNG_SEED,
        "generated_at": datetime.now().isoformat(),
        "populations": {
            "base_dateless_unresolved": len(g_all) + len(z_all) + len(o_all),
            "G_N": len(g_all), "Z_N": len(z_all), "O_N": len(o_all),
            "O_tercile_N": {name: len(rows) for name, rows in o_terciles.items()},
        },
        "G_full_census_results": g_results,
        "Z_sample_results": z_results,
        "O_sample_results": o_results,
        "summaries": {
            "G": g_summary, "Z": z_summary, "O_pooled": o_pooled_summary,
            "O_by_tercile": o_summaries,
        },
        "Q1_overall_stratified": q1_overall,
        "Q2_census": {
            "N": len(g_all),
            "resolved": g_summary["resolved"],
            "open": g_summary["open"],
            "indeterminate": g_summary["indeterminate"],
            "determinate": g_summary["determinate"],
            "point_estimate_fraction": g_summary["resolved_fraction_of_determinate"],
            "best_case_resolved_count": q2_best_case,
            "worst_case_resolved_count": q2_worst_case,
            "data_source_breakdown_all": g_ds_all,
            "data_source_breakdown_resolved": g_ds_resolved,
        },
        "cross_check": cross_checked,
        "total_clob_calls": total_calls,
    }

    out_path = OUT_DIR / f"discovery_gap_sizing_20260820T{datetime.now().strftime('%H%M%S')}Z.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nFull output written to {out_path}")

    conn.close()


if __name__ == "__main__":
    main()
