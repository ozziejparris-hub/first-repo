#!/usr/bin/env python3
"""
scripts/dry_run_stage3.py

ELO arc Stage 3 dry-run — supplements elo_shadow_delta_report.py with the
two checks that report needs but doesn't have:

1. A CORRECT Writer-A vs Writer-B population split. elo_shadow_delta_report
   .py's writer_bucket() heuristic (T-separated elo_last_updated = Writer B,
   space-separated = Writer A) went stale the moment Stage 2 shipped: Writer
   B's write_elo_result() now defaults to the same canonical space-separated
   format Writer A always used, so every trader now reads as "writer_a" by
   that heuristic. This script uses the real eligibility definition instead
   (closed_positions >= 1, matching apply_full_elo_modifiers.py's default
   --min-closed=1), read directly from elo_shadow's own stored columns.

2. An explicit "everyone else unchanged" assertion for the Writer-B
   population: for every Writer-B-eligible trader where neither the soft cap
   nor the floor binds, stage3_bounded.comp_v2 must equal stage2_neutral
   .comp_v2 exactly (both go through the identical formula; bounds are the
   only difference). Any non-zero diff there would mean something outside
   the bounds switches changed — flagged as UNEXPECTED, not summarized away.

Read-only. Run scripts/compute_elo_shadow.py first against current live
data (writes only to the elo_shadow side table, never to `traders`).
"""

import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA query_only = ON")
    cur = conn.cursor()

    cur.execute("""
        SELECT address, comp_v1, comp_v2, closed_positions, resolved_trades_count,
               behavioral_modifier, cap_applied
        FROM elo_shadow WHERE config = 'stage3_bounded'
    """)
    rows = cur.fetchall()
    print("=" * 70)
    print("  ELO ARC STAGE 3 — DRY-RUN POPULATION SPLIT (read-only)")
    print("=" * 70)
    print(f"\n  Population (elo_shadow, stage3_bounded): {len(rows):,}")

    writer_b = [r for r in rows if r[3] >= 1]
    writer_a = [r for r in rows if r[3] < 1]
    print(f"  Writer-B-eligible (closed_positions >= 1): {len(writer_b):,}")
    print(f"  Writer-A-only     (closed_positions == 0): {len(writer_a):,}")

    # ---- Writer-B population: "everyone else unchanged" assertion ----
    cur.execute("""
        SELECT s3.address, s3.comp_v2, s2.comp_v2, s3.cap_applied, s3.closed_positions
        FROM elo_shadow s3
        JOIN elo_shadow s2 ON s2.address = s3.address AND s2.config = 'stage2_neutral'
        WHERE s3.config = 'stage3_bounded' AND s3.closed_positions >= 1
    """)
    wb_rows = cur.fetchall()
    n_capped = sum(1 for _, _, _, cap, _ in wb_rows if cap != "none")
    unexpected = [(a, s3, s2, cap) for a, s3, s2, cap, _ in wb_rows
                  if cap == "none" and abs(s3 - s2) > 0.001]
    print(f"\n  -- Writer-B population ({len(wb_rows):,} traders) --")
    print(f"     Capped or floored (soft/floor applied): {n_capped}")
    print(f"     Uncapped, changed anyway (MUST be 0)   : {len(unexpected)}")
    if unexpected:
        print("     !!! UNEXPECTED CHANGES — investigate before proceeding !!!")
        for row in unexpected[:20]:
            print(f"       {row}")
    else:
        print("     OK — every uncapped Writer-B trader is byte-identical to stage2_neutral.")

    # ---- Writer-A-only population: quantify ----
    deltas_full = sorted(
        (c2 - c1, a, c1, c2, closed, resolved, beh)
        for a, c1, c2, closed, resolved, beh, cap in writer_a
    )
    deltas = [d[0] for d in deltas_full]
    n = len(deltas)
    n_zero = sum(1 for d in deltas if abs(d) < 0.01)
    n_down = sum(1 for d in deltas if d < -0.01)
    n_up = sum(1 for d in deltas if d > 0.01)
    print(f"\n  -- Writer-A-only population ({n:,} traders) --")
    print(f"     Unchanged (|delta|<0.01): {n_zero:,} ({100*n_zero/n:.2f}%)")
    print(f"     Dropped                 : {n_down:,} ({100*n_down/n:.2f}%)")
    print(f"     Rose                    : {n_up:,} ({100*n_up/n:.2f}%)")
    print(f"     Mean delta   : {sum(deltas)/n:+.2f}")
    print(f"     Median delta : {percentile(deltas, .50):+.2f}")
    print(f"     p5 / p95     : {percentile(deltas, .05):+.2f} / {percentile(deltas, .95):+.2f}")
    print(f"     min / max    : {deltas[0]:+.2f} / {deltas[-1]:+.2f}")

    big_drops = [d for d in deltas_full if d[0] < -50]
    print(f"\n     Traders with delta < -50: {len(big_drops):,}")
    if big_drops:
        high_beh_thin = sum(
            1 for delta, a, c1, c2, closed, resolved, beh in big_drops
            if (beh or 1.0) > 1.05 and (closed < 20 or (resolved or 0) < 20)
        )
        pct = 100 * high_beh_thin / len(big_drops)
        print(f"       ...of which high-behavioral(>1.05x) + thin-sample(<20 closed or resolved): "
              f"{high_beh_thin} ({pct:.1f}%)")
        print("       10 largest drops (delta, addr, comp_v1, comp_v2, closed, resolved, beh_mod):")
        for row in big_drops[:10]:
            print(f"         {row}")

    big_rises = sorted(deltas_full, key=lambda d: -d[0])[:10]
    print("\n     10 largest rises (delta, addr, comp_v1, comp_v2, closed, resolved, beh_mod):")
    for row in big_rises:
        print(f"       {row}")

    conn.close()
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
