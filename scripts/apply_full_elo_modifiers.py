#!/usr/bin/env python3
"""
Apply Full ELO Modifiers to Backfilled Base Ratings

Takes the base ELO written by backfill_elo_ratings.py and applies the P&L
multiplier from the Unified ELO System on top of it.

Why a separate script (not using get_trader_global_elo directly):
  - UnifiedELOSystem.get_trader_global_elo reads base ELO from its own
    in-memory category_elos dict, which is empty unless calculate_elo_ratings()
    is called first. That would overwrite the backfill with another in-memory
    calculation from the same 114 markets.
  - Instead, we read the backfilled comprehensive_elo from the DB as our base,
    then multiply only the P&L modifier on top of it.

Which modifiers are applied:
  - P&L multiplier (0.40x-2.50x): YES — sourced from positions table via
    PositionTracker. Currently meaningful for ~35 traders with closed positions.
    Guard: only applies open_cost_basis drag when closed_positions >= 1.
  - Behavioral bonus (±100 pts): SKIPPED — kelly_alignment_score and
    patience_score columns are all NULL (not yet calculated).
  - Advanced metrics: SKIPPED — same reason.
  - Network/contrarian: SKIPPED — not relevant to consensus detection goal.

When to re-run:
  - After P&L worker coverage increases significantly (currently ~40%)
  - After behavioral scores are populated
  - Safe to re-run anytime — reads fresh base ELO from DB each time

Usage:
    python scripts/apply_full_elo_modifiers.py
    python scripts/apply_full_elo_modifiers.py --dry-run
    python scripts/apply_full_elo_modifiers.py --min-closed 5  # only apply to traders with 5+ closed positions
"""

import sys
import sqlite3
import argparse
import os
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)


def main():
    parser = argparse.ArgumentParser(
        description='Apply P&L multiplier to backfilled base ELO ratings'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing to DB')
    parser.add_argument('--min-closed', type=int, default=1,
                        help='Minimum closed positions to apply P&L modifier (default: 1)')
    parser.add_argument('--db', default='data/polymarket_tracker.db',
                        help='Path to SQLite database')
    args = parser.parse_args()

    print("=" * 70)
    print("  APPLY FULL ELO MODIFIERS")
    print("=" * 70)
    print(f"  Database    : {args.db}")
    print(f"  Min closed  : {args.min_closed}")
    if args.dry_run:
        print("  *** DRY RUN — no changes will be written ***")
    print()

    # Import UnifiedELOSystem for the P&L calculator only
    try:
        from analysis.unified_elo_system import UnifiedELOSystem
    except Exception as e:
        print(f"ERROR: Could not import UnifiedELOSystem: {e}")
        sys.exit(1)

    system = UnifiedELOSystem(db_path=args.db)

    # Load P&L data once (it caches internally)
    print("[1/3] Loading P&L data...")
    try:
        has_pnl = system._load_pnl_data(force_refresh=True)
        pnl_traders = len(system.pnl_cache) if has_pnl else 0
        print(f"  Traders with P&L history : {pnl_traders:,}")
    except Exception as e:
        print(f"  WARNING: P&L data load failed ({e}) — running with neutral multipliers")
        pnl_traders = 0

    # Filter to traders who have enough closed positions to trust the data
    eligible = {
        addr: data
        for addr, data in (system.pnl_cache if has_pnl else {}).items()
        if data.get('closed_positions', 0) >= args.min_closed
    }
    print(f"  Eligible (>={args.min_closed} closed pos) : {len(eligible):,}")

    # Load base ELOs from DB
    print("\n[2/3] Loading base ELO from database...")
    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    placeholders = ','.join('?' * len(eligible))
    cur.execute("""
        SELECT address, base_category_elo, comprehensive_elo, pnl_modifier
        FROM traders
        WHERE address IN ({})
    """.format(placeholders), list(eligible.keys()))

    rows = cur.fetchall()

    base_elos = {}       # addr -> base ELO to use
    skipped_stale = 0    # had a modifier but no safe base — skip to avoid stacking

    for addr, base_cat, comp_elo, pnl_mod in rows:
        # Prefer base_category_elo when it has been explicitly set (backfilled OR
        # recorded at first-modifier-write time by this script).  NULL means never
        # set; any stored value — including 1500.0 — is a valid clean base.
        if base_cat is not None:
            base_elos[addr] = base_cat
        # Fallback: comprehensive_elo is safe to use only if no modifier has been
        # applied yet (pnl_modifier == 1.0 or NULL), otherwise we'd stack
        elif comp_elo is not None and (pnl_mod is None or abs(pnl_mod - 1.0) < 0.0001):
            base_elos[addr] = comp_elo
        else:
            # Modifier already applied and no clean base available — skip
            skipped_stale += 1

    from_backfill = sum(1 for a, b, c, p in rows
                        if b is not None and a in base_elos)
    from_comp = len(base_elos) - from_backfill

    print(f"  Matched {len(base_elos):,} eligible traders in DB")
    print(f"    From base_category_elo (backfilled) : {from_backfill:,}")
    print(f"    From comprehensive_elo  (unmodified): {from_comp:,}")
    if skipped_stale:
        print(f"    Skipped (modified, no clean base)  : {skipped_stale:,}")

    if not base_elos:
        print("\n  No eligible traders found. Nothing to do.")
        print("  Wait for P&L worker to process more traders, then re-run.")
        conn.close()
        return

    # Apply P&L multiplier to each eligible trader
    print("\n[3/3] Applying P&L multiplier...")

    updates = []
    now = datetime.now().isoformat()
    skipped_excluded = 0

    # Change 1: raised hard cap
    MAX_FINAL_ELO = 3500.0

    # Change 2: confidence gate — max multiplier by closed position count
    def _confidence_cap(closed: int) -> float:
        if closed >= 20: return 2.20
        if closed >= 10: return 2.00
        if closed >= 5:  return 1.80
        if closed >= 3:  return 1.60
        if closed >= 2:  return 1.45
        return 1.30  # 1 closed position

    for addr, base_elo in base_elos.items():
        try:
            pnl_data = system.calculate_pnl_multiplier(addr)
            mult = pnl_data['combined_multiplier']

            # Skip if the system excluded this trader (copy-trader detection)
            if mult == 0.0:
                skipped_excluded += 1
                continue

            pnl_entry = eligible.get(addr, {})
            closed_pos = pnl_entry.get('closed_positions', 0)

            # Change 2: gate the multiplier by confidence (closed positions)
            cap = _confidence_cap(closed_pos)
            mult = min(mult, cap) if mult > 1.0 else mult

            # Change 4: asymmetric loss penalty at high ELO
            if mult < 1.0 and base_elo >= 2000:
                loss_amplifier = 1.30
                mult = 1.0 - ((1.0 - mult) * loss_amplifier)

            # Change 3: ELO-level K-factor dampening on the gain
            if base_elo >= 2500:
                dampening = 0.60
            elif base_elo >= 2000:
                dampening = 0.80
            else:
                dampening = 1.00
            new_elo = base_elo + (base_elo * (mult - 1.0) * dampening)

            # Change 1: hard cap at 3500
            new_elo = min(new_elo, MAX_FINAL_ELO)
            updates.append((addr, base_elo, mult, new_elo, pnl_data['breakdown']))
        except Exception as e:
            print(f"  WARNING: could not compute P&L for {addr[:10]}...: {e}")
            continue

    # Sort by new ELO descending for display
    updates.sort(key=lambda x: x[3], reverse=True)

    # Show preview
    print(f"\n  Traders to update: {len(updates):,}")
    print(f"  Excluded (copy-traders): {skipped_excluded}")
    if updates:
        new_elos = [u[3] for u in updates]
        print(f"  New ELO range for updated traders: {min(new_elos):.0f} – {max(new_elos):.0f}")

        print("\n  Top 10 after modifiers:")
        for addr, base, mult, new, breakdown in updates[:10]:
            pnl_entry = eligible.get(addr, {})
            closed = pnl_entry.get('closed_positions', 0)
            damp = 0.60 if base >= 2500 else (0.80 if base >= 2000 else 1.00)
            conf_cap = _confidence_cap(closed)
            print(f"    {addr[:6]}...{addr[-4:]}  base={base:.0f}  closed={closed}  "
                  f"conf_cap={conf_cap:.2f}x  damp={damp:.2f}  ×{mult:.3f}  ->  {new:.0f}")
            print(f"      {breakdown}")

    if args.dry_run:
        print("\n  DRY RUN — no changes written.")
        conn.close()
        return

    # Write updates — retry on lock
    import time as _time
    write_rows = [
        (round(new_elo, 4), round(mult, 4), now, round(base_elo, 6), addr)
        for addr, base_elo, mult, new_elo, _ in updates
    ]
    written = 0
    for row in write_rows:
        for _attempt in range(15):
            try:
                cur.execute("""
                    UPDATE traders
                    SET comprehensive_elo = ?,
                        pnl_modifier = ?,
                        elo_last_updated = ?,
                        base_category_elo = CASE
                            WHEN base_category_elo IS NULL
                              OR ABS(base_category_elo - 1500.0) <= 0.0001
                            THEN ?
                            ELSE base_category_elo
                        END
                    WHERE address = ?
                """, row)
                written += cur.rowcount
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    _time.sleep(2)
                else:
                    raise
    for _attempt in range(15):
        try:
            conn.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                _time.sleep(2)
            else:
                raise

    # Final stats
    print(f"\n  Written {written} updates to database")

    cur.execute("""
        SELECT
            COUNT(*) as n,
            AVG(comprehensive_elo),
            MIN(comprehensive_elo),
            MAX(comprehensive_elo),
            SUM(CASE WHEN comprehensive_elo >= 1550 THEN 1 ELSE 0 END)
        FROM traders WHERE comprehensive_elo IS NOT NULL
    """)
    n, avg, lo, hi, elite = cur.fetchone()
    print()
    print("  Overall DB state after update:")
    print(f"    Total traders : {n:,}")
    print(f"    ELO range     : {lo:.0f} – {hi:.0f}")
    print(f"    Average ELO   : {avg:.0f}")
    print(f"    Elite (>=1550): {elite:,}")

    conn.close()
    print()
    print("=" * 70)
    print("  ✅ COMPLETE")
    print("=" * 70)
    print()
    print("  NOTE: Only traders with closed positions were updated.")
    print("  Re-run after P&L worker processes more traders:")
    print("    python scripts/apply_full_elo_modifiers.py")


if __name__ == "__main__":
    main()
