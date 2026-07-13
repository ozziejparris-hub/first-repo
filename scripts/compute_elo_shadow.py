#!/usr/bin/env python3
"""
scripts/compute_elo_shadow.py

ELO arc Stage 1 shadow job (design doc §5, Stage 1): computes what the
canonical comprehensive_elo formula (analysis/comprehensive_elo_formula.py)
would produce for every flagged, non-excluded trader, using their CURRENT
stored components, and writes the result ONLY to a new side table
(`elo_shadow`) — never to `traders`.

ZERO production writes. `elo_shadow` has no schema contact with any column
the live system reads (comprehensive_elo, pnl_modifier, etc. on `traders`
are untouched) and is trivially droppable (`DROP TABLE elo_shadow`).

Computes TWO configs per trader in one pass, so the delta report can show
both migration stages before either happens:
  stage2_neutral : w_beh=0, apply_soft_cap=False, apply_floor=False
                   (Stage 2's settings — should reproduce today's Writer-B
                   output for the population Writer B currently maintains)
  stage3_bounded : w_beh=0, apply_soft_cap=True,  apply_floor=True
                   (Stage 3's settings — behavioral still off, but shows
                   what turning the bounds on does)

Population: is_flagged=1, research_excluded=0, base_category_elo AND
comprehensive_elo both set (matches scripts/validate_stage1_equivalence.py's
population, for direct comparability). Traders whose live pnl_cache reports
combined_multiplier==0.0 (copy-trader exclusion) are skipped — Writer B
never touches them either, so there is no meaningful "shadow" value to
compute; production would leave their existing value untouched in Stage 2/3
too.

Usage:
    python3 scripts/compute_elo_shadow.py
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.comprehensive_elo_formula import compute_comprehensive_elo
from analysis.unified_elo_system import UnifiedELOSystem

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"

CONFIGS = {
    "stage2_neutral": dict(w_beh=0.0, apply_soft_cap=False, apply_floor=False),
    "stage3_bounded": dict(w_beh=0.0, apply_soft_cap=True, apply_floor=True),
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS elo_shadow (
    address                 TEXT NOT NULL,
    config                  TEXT NOT NULL,
    comp_v2                 REAL NOT NULL,
    comp_v1                 REAL,
    base_category_elo       REAL,
    behavioral_modifier     REAL,
    pnl_raw                 REAL,
    pnl_gated               REAL,
    beh_applied             REAL,
    gain_pnl                REAL,
    gain_beh                REAL,
    damp                    REAL,
    cap_applied             TEXT,
    closed_positions        INTEGER,
    resolved_trades_count   INTEGER,
    w_beh                   REAL,
    apply_soft_cap          BOOLEAN,
    apply_floor             BOOLEAN,
    computed_at             TIMESTAMP,
    PRIMARY KEY (address, config)
)
"""


def main():
    print("=" * 70)
    print("  ELO SHADOW COMPUTATION (Stage 1) — writes ONLY to elo_shadow")
    print("=" * 70)

    read_conn = sqlite3.connect(str(DB_PATH), timeout=60)
    read_conn.execute("PRAGMA query_only = ON")
    read_cur = read_conn.cursor()
    read_cur.execute("""
        SELECT address, base_category_elo, comprehensive_elo,
               behavioral_modifier, resolved_trades_count
        FROM traders
        WHERE is_flagged = 1 AND research_excluded = 0
          AND base_category_elo IS NOT NULL
          AND comprehensive_elo IS NOT NULL
    """)
    rows = read_cur.fetchall()
    read_conn.close()
    print(f"\n  Population: {len(rows):,} flagged, non-excluded traders")

    print("  Loading live P&L cache...")
    system = UnifiedELOSystem(db_path=str(DB_PATH))
    system._load_pnl_data(force_refresh=True)

    write_conn = sqlite3.connect(str(DB_PATH), timeout=60)
    write_conn.execute(CREATE_TABLE_SQL)
    write_conn.commit()

    now = datetime.now().isoformat()
    n_written = 0
    n_skipped_copy_trader = 0
    shadow_rows = []

    for address, base_elo, comp_v1, beh_mod, resolved in rows:
        pnl_data = system.calculate_pnl_multiplier(address)
        mult_raw = pnl_data["combined_multiplier"]
        closed = pnl_data["raw_metrics"]["closed_positions"]
        resolved = resolved or 0

        if mult_raw == 0.0:
            n_skipped_copy_trader += 1
            continue

        for config_name, params in CONFIGS.items():
            result = compute_comprehensive_elo(
                base=base_elo, beh_mult=beh_mod if beh_mod is not None else 1.0,
                bonus=0.0, pnl_raw=mult_raw, closed=closed, resolved=resolved,
                **params,
            )
            shadow_rows.append((
                address, config_name, result.comp, comp_v1,
                base_elo, beh_mod, mult_raw, result.pnl_gated, result.beh_applied,
                result.gain_pnl, result.gain_beh, result.damp, result.cap_applied,
                closed, resolved, params["w_beh"], params["apply_soft_cap"],
                params["apply_floor"], now,
            ))
        n_written += 1

    write_conn.executemany("""
        INSERT OR REPLACE INTO elo_shadow (
            address, config, comp_v2, comp_v1,
            base_category_elo, behavioral_modifier, pnl_raw, pnl_gated, beh_applied,
            gain_pnl, gain_beh, damp, cap_applied,
            closed_positions, resolved_trades_count, w_beh, apply_soft_cap,
            apply_floor, computed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, shadow_rows)
    write_conn.commit()
    write_conn.close()

    print(f"\n  Traders shadow-computed : {n_written:,}  ({n_written * len(CONFIGS):,} rows written, {len(CONFIGS)} configs each)")
    print(f"  Skipped (copy-trader, mult=0.0, not comparable): {n_skipped_copy_trader:,}")
    print(f"\n  Wrote to elo_shadow. No writes to `traders`. Drop with: DROP TABLE elo_shadow;")
    print("=" * 70)


if __name__ == "__main__":
    main()
