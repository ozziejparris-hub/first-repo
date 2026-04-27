#!/usr/bin/env python3
"""
ELO Recalculation Verification Script

Runs after recalculate_comprehensive_elo.py to confirm the recalculation
completed correctly and key invariants are still intact.

Usage:
    python3 scripts/verify_elo_recalculation.py
"""

import sys
import os
import sqlite3
from datetime import datetime, date

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(project_root, "data", "polymarket_tracker.db")

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results = []


def check(label, passed, detail="", warn=False):
    status = WARN if warn else (PASS if passed else FAIL)
    results.append((status, label, detail))
    symbol = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}[status]
    print(f"  [{symbol}] {label}")
    if detail:
        print(f"       {detail}")


def run_checks():
    print("\n" + "=" * 60)
    print("  ELO RECALCULATION VERIFICATION")
    print(f"  Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
    except Exception as e:
        print(f"\n[FATAL] Cannot connect to database: {e}")
        print(f"        DB path: {DB_PATH}")
        sys.exit(1)

    print(f"\n[DB] Connected: {DB_PATH}")

    # ------------------------------------------------------------------
    # Check 1 — Recency: when was elo_last_updated most recently set?
    # ------------------------------------------------------------------
    print("\n--- Check 1: Recalculation recency ---")
    cur.execute("""
        SELECT
            MAX(elo_last_updated)  AS last_updated,
            CAST(julianday('now') - julianday(MAX(elo_last_updated)) AS INTEGER)
                AS days_ago
        FROM traders
        WHERE elo_last_updated IS NOT NULL
    """)
    row = cur.fetchone()
    last_updated = row["last_updated"]
    days_ago = row["days_ago"]

    if last_updated is None:
        check("Most recent elo_last_updated", False, "No elo_last_updated values found")
    elif days_ago == 0:
        check("Most recent elo_last_updated", True, f"{last_updated[:19]} (today)")
    elif days_ago <= 1:
        check("Most recent elo_last_updated", True, f"{last_updated[:19]} ({days_ago} day ago)")
    elif days_ago <= 7:
        check("Most recent elo_last_updated", True,
              f"{last_updated[:19]} ({days_ago} days ago)", warn=True)
    else:
        check("Most recent elo_last_updated", False,
              f"{last_updated[:19]} — {days_ago} days ago (stale!)")

    # ------------------------------------------------------------------
    # Check 2 — Volume: how many traders updated today?
    # ------------------------------------------------------------------
    print("\n--- Check 2: Traders updated today ---")
    today_str = date.today().isoformat()
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM traders
        WHERE date(elo_last_updated) = date('now')
    """)
    updated_today = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM traders")
    total_traders = cur.fetchone()["cnt"]

    if updated_today == 0:
        check("Traders updated today", False,
              f"0 of {total_traders:,} — recalculation may not have run today")
    elif updated_today < 1000:
        check("Traders updated today", False,
              f"{updated_today:,} of {total_traders:,} — suspiciously low (partial run?)")
    else:
        check("Traders updated today", True,
              f"{updated_today:,} of {total_traders:,} traders")

    # ------------------------------------------------------------------
    # Check 3 — ELO distribution
    # ------------------------------------------------------------------
    print("\n--- Check 3: ELO distribution ---")
    cur.execute("""
        SELECT
            MIN(comprehensive_elo)   AS elo_min,
            MAX(comprehensive_elo)   AS elo_max,
            AVG(comprehensive_elo)   AS elo_avg,
            COUNT(*)                 AS total_with_elo,
            SUM(CASE WHEN comprehensive_elo >= 2500 THEN 1 ELSE 0 END) AS legendary,
            SUM(CASE WHEN comprehensive_elo >= 2000
                      AND comprehensive_elo < 2500  THEN 1 ELSE 0 END) AS elite,
            SUM(CASE WHEN comprehensive_elo >= 1550
                      AND comprehensive_elo < 2000  THEN 1 ELSE 0 END) AS strong,
            SUM(CASE WHEN comprehensive_elo < 1550  THEN 1 ELSE 0 END) AS baseline
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
    """)
    d = cur.fetchone()
    elo_min = d["elo_min"]
    elo_max = d["elo_max"]
    elo_avg = d["elo_avg"]
    total_elo = d["total_with_elo"]

    dist_detail = (
        f"min={elo_min:.0f}  max={elo_max:.0f}  avg={elo_avg:.0f}  n={total_elo:,} | "
        f"Legendary={d['legendary']}  Elite={d['elite']}  "
        f"Strong={d['strong']}  Baseline={d['baseline']}"
    )

    if elo_min is None or total_elo == 0:
        check("ELO distribution", False, "No ELO scores found")
    elif elo_min < 0 or elo_max > 10000:
        check("ELO distribution", False,
              f"Outliers detected — {dist_detail}")
    elif elo_avg < 1000 or elo_avg > 3000:
        check("ELO distribution sanity (avg 1000-3000)", False,
              f"Avg {elo_avg:.0f} looks wrong — {dist_detail}")
    else:
        check("ELO distribution", True, dist_detail)

    # ------------------------------------------------------------------
    # Check 4 — Top 20 traders
    # ------------------------------------------------------------------
    print("\n--- Check 4: Top 20 traders ---")
    cur.execute("""
        SELECT address, comprehensive_elo, research_excluded
        FROM traders
        WHERE comprehensive_elo IS NOT NULL
        ORDER BY comprehensive_elo DESC
        LIMIT 20
    """)
    top20 = cur.fetchall()

    if len(top20) < 20:
        check("Top 20 traders retrievable", False,
              f"Only {len(top20)} traders with ELO scores found")
    else:
        excluded_in_top20 = sum(1 for r in top20 if r["research_excluded"])
        min_top20 = min(r["comprehensive_elo"] for r in top20)
        max_top20 = top20[0]["comprehensive_elo"]

        print(f"       Rank  ELO      Excl  Address")
        for i, r in enumerate(top20, 1):
            excl_flag = "EXCL" if r["research_excluded"] else "    "
            addr_short = r["address"][:10] + "…" if r["address"] else "N/A"
            print(f"       {i:3}.  {r['comprehensive_elo']:7.0f}  {excl_flag}  {addr_short}")

        if min_top20 < 1000:
            check("Top 20 ELO values reasonable (>=1000)", False,
                  f"Lowest top-20 ELO: {min_top20:.0f}")
        else:
            check("Top 20 ELO values reasonable (>=1000)", True,
                  f"Range {min_top20:.0f}–{max_top20:.0f}, {excluded_in_top20} excluded traders in top 20")

    # ------------------------------------------------------------------
    # Check 5 — LP artifact traders still correctly flagged
    # ------------------------------------------------------------------
    print("\n--- Check 5: LP artifact traders ---")
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM traders
        WHERE bot_type = 'LP_ARTIFACT'
          AND research_excluded = 1
    """)
    lp_flagged = cur.fetchone()["cnt"]
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM traders WHERE bot_type = 'LP_ARTIFACT'
    """)
    lp_total = cur.fetchone()["cnt"]

    if lp_total == 0:
        check("LP artifact traders exist", False, "No LP_ARTIFACT entries found")
    elif lp_flagged != lp_total:
        check("LP artifact traders all have research_excluded=1", False,
              f"{lp_flagged}/{lp_total} flagged — {lp_total - lp_flagged} missing exclusion")
    elif lp_total == 4:
        check("LP artifact traders (expected 4)", True,
              f"{lp_total} found, all research_excluded=1")
    else:
        check("LP artifact traders (expected 4)", False,
              f"Found {lp_total} (expected 4) — count changed", warn=(lp_total > 4))

    # ------------------------------------------------------------------
    # Check 6 — elo_period1_cutoff column: exists and has 821 values
    # ------------------------------------------------------------------
    print("\n--- Check 6: elo_period1_cutoff column ---")
    try:
        cur.execute("SELECT COUNT(*) AS cnt FROM traders WHERE elo_period1_cutoff IS NOT NULL")
        period1_count = cur.fetchone()["cnt"]
        if period1_count == 0:
            check("elo_period1_cutoff has values", False, "Column exists but all NULL")
        elif period1_count == 821:
            check("elo_period1_cutoff has 821 values", True,
                  f"{period1_count} traders with period1 cutoff (expected 821)")
        else:
            check("elo_period1_cutoff count (expected 821)", False,
                  f"Found {period1_count} (expected 821) — investigate",
                  warn=(period1_count > 821))
    except sqlite3.OperationalError as e:
        check("elo_period1_cutoff column exists", False, str(e))

    # ------------------------------------------------------------------
    # Check 7 — Thin-sample artifact traders still flagged
    # ------------------------------------------------------------------
    print("\n--- Check 7: Thin-sample artifact traders ---")
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM traders
        WHERE bot_type = 'THIN_SAMPLE_ARTIFACT'
          AND research_excluded = 1
    """)
    thin_flagged = cur.fetchone()["cnt"]
    cur.execute("""
        SELECT COUNT(*) AS cnt FROM traders WHERE bot_type = 'THIN_SAMPLE_ARTIFACT'
    """)
    thin_total = cur.fetchone()["cnt"]

    if thin_total == 0:
        check("Thin-sample artifact traders exist", False,
              "No THIN_SAMPLE_ARTIFACT entries found")
    elif thin_flagged != thin_total:
        check("Thin-sample traders all have research_excluded=1", False,
              f"{thin_flagged}/{thin_total} flagged")
    elif thin_total == 17:
        check("Thin-sample artifact traders (expected 17)", True,
              f"{thin_total} found, all research_excluded=1")
    else:
        check("Thin-sample artifact traders (expected 17)", False,
              f"Found {thin_total} (expected 17) — count changed",
              warn=(thin_total > 17))

    conn.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    passed = sum(1 for s, _, _ in results if s == PASS)
    warned = sum(1 for s, _, _ in results if s == WARN)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    total = len(results)

    print(f"  RESULT: {passed}/{total} passed  |  {warned} warnings  |  {failed} failed")

    if failed > 0:
        print("\n  FAILED CHECKS:")
        for status, label, detail in results:
            if status == FAIL:
                print(f"    ✗ {label}: {detail}")
        print("\n  ⚠️  Recalculation has issues — investigate before research reruns.")
        sys.exit(1)
    elif warned > 0:
        print("\n  ✓ All checks passed with warnings — review WARN items above.")
    else:
        print("\n  ✓ All checks passed — ELO recalculation looks healthy.")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_checks()
