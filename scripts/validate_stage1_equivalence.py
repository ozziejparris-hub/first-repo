#!/usr/bin/env python3
"""
scripts/validate_stage1_equivalence.py

Stage 1 live-data validation (read-only, no writes): pulls real component
values for the flagged, non-excluded trader population, runs them through
analysis.comprehensive_elo_formula.compute_comprehensive_elo(w_beh=0,
apply_soft_cap=False, apply_floor=False), and compares to each trader's
ACTUAL stored comprehensive_elo.

This is NOT the same as the unit-test equivalence grid (that one diffs two
pure-function implementations against each other on synthetic inputs). This
script diffs the pure function's output against real production output —
it validates that the formula, fed real inputs, reproduces what the live
system actually wrote, not just that two implementations agree in the
abstract.

Segments the population the same way the design doc does (§1b): traders
last written by Writer B (daily, apply_full_elo_modifiers.py — elo_
last_updated is T-separated, .isoformat()) are expected to match near-
exactly TODAY, since Writer B's formula IS this pure function at w_beh=0
(the zero-diff equivalence test proves this structurally). Traders last
written by Writer A (Sunday, elo_bridge.py — elo_last_updated is space-
separated, plain datetime.now()) are NOT expected to match — Writer A
still runs its own formula (behavioral included, soft-capped) pending
Stage 3. Mismatches are also possible for eligible Writer-B traders whose
underlying P&L data has moved since their last write (new trades/closes
between then and now) — this script flags that explicitly, it does not
force a match.

Eligibility mirrors apply_full_elo_modifiers.py's own --min-closed filter
(default 1): traders with 0 closed positions in today's live pnl_cache, or
mult==0.0 (copy-trader exclusion), are never touched by Writer B and are
reported separately, not counted as formula mismatches.

Usage:
    python3 scripts/validate_stage1_equivalence.py
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.comprehensive_elo_formula import compute_comprehensive_elo
from analysis.unified_elo_system import UnifiedELOSystem

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"


def main():
    print("=" * 70)
    print("  STAGE 1 LIVE-DATA VALIDATION (read-only)")
    print("=" * 70)

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA query_only = ON")
    cur = conn.cursor()

    cur.execute("""
        SELECT address, base_category_elo, comprehensive_elo,
               resolved_trades_count, elo_last_updated
        FROM traders
        WHERE is_flagged = 1 AND research_excluded = 0
          AND base_category_elo IS NOT NULL
          AND comprehensive_elo IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()
    print(f"\n  Population (flagged, non-excluded, base+comp both set): {len(rows):,}")

    print("\n  Loading live P&L cache (same call Writer B itself uses)...")
    system = UnifiedELOSystem(db_path=str(DB_PATH))
    system._load_pnl_data(force_refresh=True)

    n_ineligible = 0
    n_writer_b_match = 0
    n_writer_b_mismatch = 0
    n_writer_a_match = 0
    n_writer_a_mismatch = 0
    n_unknown_last_writer_match = 0
    n_unknown_last_writer_mismatch = 0
    mismatch_examples = {"writer_b": [], "writer_a": [], "unknown": []}

    for address, base_elo, comp_elo, resolved, elo_last_updated in rows:
        pnl_data = system.calculate_pnl_multiplier(address)
        mult_raw = pnl_data["combined_multiplier"]
        closed = pnl_data["raw_metrics"]["closed_positions"]

        if closed < 1 or mult_raw == 0.0:
            n_ineligible += 1
            continue

        produced = compute_comprehensive_elo(
            base=base_elo, beh_mult=1.0, bonus=0, pnl_raw=mult_raw,
            closed=closed, resolved=resolved or 0,
            w_beh=0.0, apply_soft_cap=False, apply_floor=False,
        ).comp
        produced_rounded = round(produced, 4)
        stored_rounded = round(comp_elo, 4)
        match = abs(produced_rounded - stored_rounded) < 1e-6

        if elo_last_updated and "T" in elo_last_updated:
            bucket = "writer_b"
        elif elo_last_updated:
            bucket = "writer_a"
        else:
            bucket = "unknown"

        if match:
            if bucket == "writer_b":
                n_writer_b_match += 1
            elif bucket == "writer_a":
                n_writer_a_match += 1
            else:
                n_unknown_last_writer_match += 1
        else:
            if bucket == "writer_b":
                n_writer_b_mismatch += 1
            elif bucket == "writer_a":
                n_writer_a_mismatch += 1
            else:
                n_unknown_last_writer_mismatch += 1
            if len(mismatch_examples[bucket]) < 5:
                mismatch_examples[bucket].append(
                    (address, base_elo, comp_elo, produced_rounded, closed, resolved,
                     elo_last_updated)
                )

    n_eligible = n_writer_b_match + n_writer_b_mismatch + n_writer_a_match + n_writer_a_mismatch \
        + n_unknown_last_writer_match + n_unknown_last_writer_mismatch

    print(f"\n  Eligible (closed>=1, not copy-trader-excluded) : {n_eligible:,}")
    print(f"  Ineligible (skipped, not comparable)           : {n_ineligible:,}")
    print()
    print(f"  Writer-B population (elo_last_updated T-separated):")
    print(f"    Match    : {n_writer_b_match:,}")
    print(f"    Mismatch : {n_writer_b_mismatch:,}")
    if n_writer_b_match + n_writer_b_mismatch:
        pct = 100.0 * n_writer_b_match / (n_writer_b_match + n_writer_b_mismatch)
        print(f"    Match rate: {pct:.2f}%")
    print()
    print(f"  Writer-A population (elo_last_updated space-separated, Sunday-retained):")
    print(f"    Match    : {n_writer_a_match:,}")
    print(f"    Mismatch : {n_writer_a_mismatch:,}  (expected — Writer A runs its own formula pre-Stage-3)")
    print()
    print(f"  Unknown/NULL elo_last_updated:")
    print(f"    Match    : {n_unknown_last_writer_match:,}")
    print(f"    Mismatch : {n_unknown_last_writer_mismatch:,}")

    for bucket, label in [("writer_b", "Writer-B mismatch examples"),
                           ("writer_a", "Writer-A mismatch examples"),
                           ("unknown", "Unknown mismatch examples")]:
        if mismatch_examples[bucket]:
            print(f"\n  {label} (address, base, stored_comp, produced_comp, closed, resolved, elo_last_updated):")
            for ex in mismatch_examples[bucket]:
                print(f"    {ex}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
