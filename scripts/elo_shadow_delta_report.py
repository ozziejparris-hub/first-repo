#!/usr/bin/env python3
"""
scripts/elo_shadow_delta_report.py

The Stage 1 deliverable (design doc §5): the delta report, for human review
before Stage 2. Reads `elo_shadow` (populated by compute_elo_shadow.py) and
`traders`, both read-only. Reports, for EACH config (stage2_neutral,
stage3_bounded):

  - per-trader comp_v2 - comp_v1 distribution (mean, percentiles)
  - tier-count changes at the gates (1500 / 1800 / 2175)
  - top-100 leaderboard diff (by comp_v1 today vs comp_v2)

Segments stage2_neutral's population by which writer last touched each
trader (elo_last_updated format: T-separated = Writer B / daily,
space-separated = Writer A / Sunday-retained, NULL = never written) --
Stage 2's "should be ~zero delta" claim only applies to the Writer-B-
maintained subset; Writer-A-retained traders are EXPECTED to show a real
delta (that's a preview of what Stage 3 does to them, not a bug in Stage 2).

IMPORTANT — tier-count and leaderboard sections use an "effective post-
deploy value", not a blanket comp_v2, because Stage 2 and Stage 3 touch
different populations per the design (§4.2/§5): Stage 2 only replaces
apply_full_elo_modifiers.py (the daily/Writer-B pass) -- it does not touch
full_elo_recalculation (Writer A/Sunday) at all, so Writer-A-retained
traders' values would NOT change under a real Stage 2 deploy. Stage 3 is
the stage that moves Writer A onto canonical too, so by then the whole
population genuinely becomes comp_v2. Blending comp_v2 across the whole
population for BOTH configs would overstate Stage 2's real effect: the
~1,026-trader Writer-A population sampled here sits disproportionately at
high ELO (average 1,686 among those >=1500) and drops hard once behavioral
zeroes out -- real, but not something Stage 2 alone causes.
  effective(stage2_neutral) = comp_v2 for writer_b bucket, comp_v1 (unchanged) otherwise
  effective(stage3_bounded) = comp_v2 for everyone (Stage 3 migrates both writers)

Usage:
    python3 scripts/elo_shadow_delta_report.py
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"
TIERS = [1500, 1800, 2175]  # QUALIFIED / ELITE / LEGENDARY-adjacent gates
TOP_N = 100


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def writer_bucket(elo_last_updated):
    if not elo_last_updated:
        return "unknown"
    return "writer_b" if "T" in elo_last_updated else "writer_a"


def report_for_config(cur, config):
    cur.execute("""
        SELECT s.address, s.comp_v1, s.comp_v2, t.elo_last_updated
        FROM elo_shadow s
        JOIN traders t ON t.address = s.address
        WHERE s.config = ?
    """, (config,))
    rows = cur.fetchall()

    print(f"\n{'='*70}")
    print(f"  CONFIG: {config}")
    print(f"{'='*70}")
    print(f"  Population: {len(rows):,} traders")

    deltas_by_bucket = {"writer_b": [], "writer_a": [], "unknown": []}
    for address, comp_v1, comp_v2, elo_last_updated in rows:
        bucket = writer_bucket(elo_last_updated)
        deltas_by_bucket[bucket].append(comp_v2 - comp_v1)

    for bucket, label in [("writer_b", "Writer-B population (daily, T-separated)"),
                           ("writer_a", "Writer-A population (Sunday-retained, space-separated)"),
                           ("unknown", "Unknown / never written")]:
        deltas = sorted(deltas_by_bucket[bucket])
        if not deltas:
            print(f"\n  -- {label}: 0 traders --")
            continue
        n = len(deltas)
        mean = sum(deltas) / n
        n_zero = sum(1 for d in deltas if abs(d) < 0.01)
        print(f"\n  -- {label}: {n:,} traders --")
        print(f"     mean delta      : {mean:+.4f}")
        print(f"     ~zero (|d|<0.01): {n_zero:,} ({100*n_zero/n:.2f}%)")
        print(f"     p1 / p5 / p25   : {percentile(deltas,.01):+.2f} / {percentile(deltas,.05):+.2f} / {percentile(deltas,.25):+.2f}")
        print(f"     p50 (median)    : {percentile(deltas,.50):+.2f}")
        print(f"     p75 / p95 / p99 : {percentile(deltas,.75):+.2f} / {percentile(deltas,.95):+.2f} / {percentile(deltas,.99):+.2f}")
        print(f"     min / max       : {deltas[0]:+.2f} / {deltas[-1]:+.2f}")

    # ---- Effective post-deploy value: Stage 2 only rewrites the Writer-B
    # write path; Stage 3 rewrites both. See module docstring. ----
    if config == "stage2_neutral":
        effective = [
            (address, comp_v1, comp_v2 if writer_bucket(elo_last_updated) == "writer_b" else comp_v1)
            for address, comp_v1, comp_v2, elo_last_updated in rows
        ]
        note = "(Stage 2 only touches the Writer-B/daily write path — Writer-A/unknown traders keep comp_v1)"
    else:
        effective = [(address, comp_v1, comp_v2) for address, comp_v1, comp_v2, _ in rows]
        note = "(Stage 3 migrates both writers onto canonical — whole population becomes comp_v2)"

    # ---- Tier-count changes, using the effective post-deploy value ----
    print(f"\n  -- Tier-count changes {note} --")
    comp1 = [e[1] for e in effective]
    comp2 = [e[2] for e in effective]
    for tier in TIERS:
        n1 = sum(1 for c in comp1 if c >= tier)
        n2 = sum(1 for c in comp2 if c >= tier)
        print(f"     >= {tier}: {n1:,} -> {n2:,}  (delta {n2-n1:+,}, {100*(n2-n1)/n1 if n1 else 0:+.2f}%)")

    # ---- Top-100 leaderboard diff, using the effective post-deploy value ----
    top100_v1 = set(a for a, _, _ in sorted(effective, key=lambda e: -e[1])[:TOP_N])
    top100_v2 = set(a for a, _, _ in sorted(effective, key=lambda e: -e[2])[:TOP_N])
    retained = top100_v1 & top100_v2
    dropped = top100_v1 - top100_v2
    entered = top100_v2 - top100_v1
    print(f"\n  -- Top-{TOP_N} leaderboard diff {note} --")
    print(f"     retained in top-{TOP_N}: {len(retained)}/{TOP_N}")
    print(f"     dropped out           : {len(dropped)}")
    print(f"     newly entered         : {len(entered)}")


def report_bounds_only_effect(cur):
    """Isolates JUST what turning on apply_soft_cap/apply_floor does, by
    diffing stage3_bounded.comp_v2 against stage2_neutral.comp_v2 directly
    (both at w_beh=0 -- the only difference between the two configs is the
    bounds switches). This is distinct from either config's report above,
    which diffs against comp_v1 (today's actual stored value) and therefore
    also captures the Writer-A-vs-canonical formula change. Answers
    specifically: what does Stage 3's cap/floor cutover do, on its own?"""
    cur.execute("""
        SELECT s2.address, s2.comp_v2 AS stage2_comp, s3.comp_v2 AS stage3_comp,
               s3.cap_applied, s3.resolved_trades_count
        FROM elo_shadow s2
        JOIN elo_shadow s3 ON s3.address = s2.address AND s3.config = 'stage3_bounded'
        WHERE s2.config = 'stage2_neutral'
    """)
    rows = cur.fetchall()
    n_soft = sum(1 for _, _, _, cap, _ in rows if "soft" in cap)
    n_floor = sum(1 for _, _, _, cap, _ in rows if "floor" in cap)
    n_hard_only = sum(1 for _, _, _, cap, _ in rows if cap == "hard")

    print(f"\n{'='*70}")
    print(f"  BOUNDS-ONLY EFFECT (stage3_bounded.comp_v2 - stage2_neutral.comp_v2, both w_beh=0)")
    print(f"{'='*70}")
    print(f"  Traders where the soft cap binds  : {n_soft:,}")
    print(f"  Traders where the floor binds     : {n_floor:,}  (expected: 0 -- empirical min is well above 400)")
    print(f"  Traders where only the (always-on) hard cap applies: {n_hard_only:,}")

    soft_hits = sorted(
        [(a, s2c, s3c, s3c - s2c, resolved) for a, s2c, s3c, cap, resolved in rows if "soft" in cap],
        key=lambda x: x[3],
    )
    if soft_hits:
        print(f"\n  Soft-cap examples (address, stage2_comp, stage3_comp, delta, resolved):")
        for row in soft_hits[:10]:
            print(f"    {row}")


def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA query_only = ON")
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT config FROM elo_shadow")
    configs = [r[0] for r in cur.fetchall()]
    if not configs:
        print("No elo_shadow data. Run scripts/compute_elo_shadow.py first.")
        return

    print("=" * 70)
    print("  ELO ARC STAGE 1 — DELTA REPORT (read-only)")
    print("=" * 70)

    for config in sorted(configs):
        report_for_config(cur, config)

    if "stage2_neutral" in configs and "stage3_bounded" in configs:
        report_bounds_only_effect(cur)

    conn.close()
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
