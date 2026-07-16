#!/usr/bin/env python3
"""
scripts/writer_a_dry_run.py

Writer-A full end-to-end dry-run driver — validates the ELO arc Stage 3
canonical write path (monitoring.elo_bridge.UnifiedELOMonitoringBridge
.full_elo_recalculation) without touching production.

Runs the REAL bridge method (the ~2h cold pass: fresh calculate_elo_ratings()
+ fresh behavioral/advanced/pnl per trader) but redirects the ONLY write call
(write_elo_result) to a scratch copy of the DB instead of production.

Verified safe because:
  - UnifiedELOSystem() (the compute engine, instantiated internally by the
    bridge) is hardcoded to read data/polymarket_tracker.db regardless of any
    path passed elsewhere -- all reads during the run hit production,
    read-only.
  - The bridge's only write, write_elo_result(conn, ...), uses
    self.db.get_connection() -- self.db is the Database object passed in here,
    pointed at the scratch copy. Production `traders` is never opened for
    writing.

First run 2026-07-15 (26,841 traders, 0 failed, 107 min): confirmed Writer
A's canonical wiring matches analysis.comprehensive_elo_formula
.compute_comprehensive_elo exactly (same-inputs-same-output holds for every
mismatch against the elo_shadow forecast) -- mismatches were 100% benign
recompute drift from a stale forecast, 0% formula/logic divergence. Full
writeup: ~/trading-swarm/brain/decisions/2026-06-29-overhang-ledger.md, O-7,
"STAGE 3 DRY-RUN VALIDATED". Moved into the repo 2026-07-16 (was in session
scratch space) so it survives as a reusable pre-Sunday validation tool --
see scripts/writer_a_saturday_checkpoint.py for the one-command wrapper that
refreshes elo_shadow, takes a fresh scratch copy, and runs this in sequence.

Usage:
    python3 scripts/writer_a_dry_run.py /path/to/scratch_copy.db
"""
import sys
import os
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)  # elo_bridge does `from comprehensive_elo_formula import ...` (relative to analysis/ on sys.path via monitoring's own setup)

from monitoring.database import Database
from monitoring.elo_bridge import UnifiedELOMonitoringBridge


def main():
    if len(sys.argv) != 2:
        print("usage: writer_a_dry_run.py /path/to/scratch_copy.db")
        return 1
    scratch_path = sys.argv[1]
    if not os.path.exists(scratch_path):
        print(f"[ERROR] scratch copy does not exist: {scratch_path}")
        return 1
    if os.path.realpath(scratch_path) == os.path.realpath(
        os.path.join(REPO_ROOT, "data", "polymarket_tracker.db")
    ):
        print("[ABORT] scratch_path resolves to the production DB. Refusing to run.")
        return 1

    print(f"[DRY-RUN] scratch DB: {scratch_path}")
    print("[DRY-RUN] production data/polymarket_tracker.db will be READ ONLY "
          "(UnifiedELOSystem's internal path is hardcoded to it); "
          "all WRITES go to the scratch copy only.")

    db = Database(db_path=scratch_path)
    bridge = UnifiedELOMonitoringBridge(db=db)

    start = time.time()
    results = bridge.full_elo_recalculation(
        verbose=True,
        force_refresh=True,
        skip_correlation=True,
        skip_contrarian=True,
    )
    elapsed = time.time() - start

    print("\n" + "=" * 70)
    print("  WRITER-A DRY-RUN COMPLETE")
    print("=" * 70)
    print(f"  Traders updated : {results['traders_updated']}")
    print(f"  Traders failed  : {results['traders_failed']}")
    print(f"  Avg comp ELO    : {results.get('avg_elo', float('nan')):.1f}")
    print(f"  Elapsed         : {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # ---- Compare against the existing forecast (elo_shadow.stage3_bounded),
    # which lives in the SAME scratch file since it was cloned from production
    # after compute_elo_shadow.py last ran there. ----
    import sqlite3
    conn = sqlite3.connect(scratch_path)
    conn.execute("PRAGMA query_only = ON")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='elo_shadow'")
    if not cur.fetchone():
        print("\n[WARN] no elo_shadow table in this scratch copy -- "
              "run scripts/compute_elo_shadow.py against production BEFORE "
              "taking the scratch backup if you want a forecast comparison.")
        conn.close()
        return 0

    cur.execute("""
        SELECT s.address, s.comp_v2 AS forecast, t.comprehensive_elo AS actual,
               s.closed_positions
        FROM elo_shadow s
        JOIN traders t ON t.address = s.address
        WHERE s.config = 'stage3_bounded'
    """)
    rows = cur.fetchall()
    conn.close()

    n = len(rows)
    matched = sum(1 for _, f, a, _ in rows if a is not None and abs(f - a) < 0.5)
    mismatched = [(addr, f, a, cp) for addr, f, a, cp in rows
                  if a is None or abs(f - a) >= 0.5]
    print(f"\n  -- Forecast comparison (elo_shadow.stage3_bounded vs real run) --")
    print(f"     Compared            : {n:,}")
    print(f"     Matched (<0.5 diff) : {matched:,} ({100*matched/n:.2f}%)" if n else "     (no rows)")
    print(f"     Mismatched          : {len(mismatched):,}")
    if mismatched:
        print("     First 20 mismatches (addr, forecast, actual, closed_positions):")
        for row in mismatched[:20]:
            print(f"       {row}")
        print("\n     NOTE: mismatches are EXPECTED if trade history / behavioral "
              "data changed between when compute_elo_shadow.py ran and when this "
              "scratch backup was taken -- the forecast used STORED components, "
              "this run recomputes base_category_elo and behavioral_modifier "
              "fresh from current trades. See scripts/writer_a_saturday_checkpoint.py "
              "to minimize this gap.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
