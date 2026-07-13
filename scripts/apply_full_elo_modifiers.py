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
  - Behavioral bonus (±100 pts): SKIPPED — w_beh=0 (Stage 0b decision; see
    analysis/comprehensive_elo_formula.W_BEH). Real behavioral_modifier /
    kelly / patience / timing values ARE read and re-written atomically
    alongside comprehensive_elo (see below), they just don't affect the
    computed value at w_beh=0.
  - Advanced metrics: SKIPPED — same reason (w_beh gates the whole
    behavioral dimension; advanced_modifier is excluded from the formula
    entirely per design §2.5, re-written unchanged for now).
  - Network/contrarian: SKIPPED — not relevant to consensus detection goal.

ELO ARC STAGE 2 (2026-07): this script's formula internals were replaced
with analysis.comprehensive_elo_formula.compute_comprehensive_elo(w_beh=0,
apply_soft_cap=False, apply_floor=False) — proven term-for-term identical
to this script's PREVIOUS inline formula (zero-diff equivalence test,
61,248-point grid; live-data validation, 99.87% match). The write now goes
through monitoring.database.write_elo_result(), which writes the full
component-column set atomically every time (this is the O-3 elo_last_updated
canonical-format fix, and closes the "columns from different writers at
different times" artifact class — see the ELO arc design doc §4.1).

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

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from analysis.comprehensive_elo_formula import compute_comprehensive_elo
from monitoring.database import write_elo_result


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
        SELECT address, base_category_elo, comprehensive_elo, pnl_modifier,
               resolved_trades_count, behavioral_modifier, advanced_modifier,
               kelly_alignment_score, patience_score, timing_score
        FROM traders
        WHERE address IN ({})
    """.format(placeholders), list(eligible.keys()))

    rows = cur.fetchall()

    base_elos = {}          # addr -> base ELO to use
    base_cat_raw = {}       # addr -> the RAW stored base_category_elo (None if never set)
    resolved_counts = {}    # addr -> resolved_trades_count
    behavioral_snapshot = {}  # addr -> (behavioral_modifier, advanced_modifier, kelly, patience, timing)
    skipped_stale = 0       # had a modifier but no safe base — skip to avoid stacking

    for addr, base_cat, comp_elo, pnl_mod, res_count, beh_mod, adv_mod, kelly, patience, timing in rows:
        base_cat_raw[addr] = base_cat
        behavioral_snapshot[addr] = (beh_mod, adv_mod, kelly, patience, timing)
        # Prefer base_category_elo when it has been explicitly set (backfilled OR
        # recorded at first-modifier-write time by this script).  NULL means never
        # set; any stored value — including 1500.0 — is a valid clean base.
        if base_cat is not None:
            base_elos[addr] = base_cat
            resolved_counts[addr] = res_count or 0
        # Fallback: comprehensive_elo is safe to use only if no modifier has been
        # applied yet (pnl_modifier == 1.0 or NULL), otherwise we'd stack
        elif comp_elo is not None and (pnl_mod is None or abs(pnl_mod - 1.0) < 0.0001):
            base_elos[addr] = comp_elo
            resolved_counts[addr] = res_count or 0
        else:
            # Modifier already applied and no clean base available — skip
            skipped_stale += 1

    from_backfill = sum(1 for a, b, c, p, r, *_ in rows
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
    skipped_excluded = 0

    # Cosmetic only (preview display below) — the actual computation goes
    # through analysis.comprehensive_elo_formula.compute_comprehensive_elo,
    # which has its own internal confidence-cap table (identical values).
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

            # Skip if the system excluded this trader (copy-trader detection).
            # pnl_raw=0.0 is out-of-domain for compute_comprehensive_elo (see
            # its docstring) — this mirrors the pre-Stage-2 behavior exactly.
            if mult == 0.0:
                skipped_excluded += 1
                continue

            pnl_entry = eligible.get(addr, {})
            closed_pos = pnl_entry.get('closed_positions', 0)

            # ELO ARC STAGE 2: canonical formula at output-neutral settings.
            # w_beh=0 (Stage 0b), apply_soft_cap=False, apply_floor=False —
            # at these settings this IS Writer B's formula, term for term
            # (proven: zero-diff equivalence test + live-data validation).
            # beh_mult/bonus are mathematically inert at w_beh=0 (also
            # proven), so plain placeholders are used here rather than
            # reconstructing the real bonus step-function.
            result = compute_comprehensive_elo(
                base=base_elo, beh_mult=1.0, bonus=0.0,
                pnl_raw=mult, closed=closed_pos,
                resolved=resolved_counts.get(addr, 0),
                w_beh=0.0, apply_soft_cap=False, apply_floor=False,
            )
            updates.append((addr, base_elo, mult, result, pnl_data['breakdown']))
        except Exception as e:
            print(f"  WARNING: could not compute P&L for {addr[:10]}...: {e}")
            continue

    # Sort by new ELO descending for display
    updates.sort(key=lambda x: x[3].comp, reverse=True)

    # Show preview
    print(f"\n  Traders to update: {len(updates):,}")
    print(f"  Excluded (copy-traders): {skipped_excluded}")
    if updates:
        new_elos = [u[3].comp for u in updates]
        print(f"  New ELO range for updated traders: {min(new_elos):.0f} – {max(new_elos):.0f}")

        print("\n  Top 10 after modifiers:")
        for addr, base, mult, result, breakdown in updates[:10]:
            pnl_entry = eligible.get(addr, {})
            closed = pnl_entry.get('closed_positions', 0)
            conf_cap = _confidence_cap(closed)
            print(f"    {addr[:6]}...{addr[-4:]}  base={base:.0f}  closed={closed}  "
                  f"conf_cap={conf_cap:.2f}x  damp={result.damp:.2f}  ×{mult:.3f}  ->  {result.comp:.0f}")
            print(f"      {breakdown}")

    if args.dry_run:
        print("\n  DRY RUN — no changes written.")
        conn.close()
        return

    # Write updates — one atomic full-column-set write per trader (design
    # §4.1). write_elo_result() has its own retry-on-lock (monitoring.database
    # .retry_on_locked); we still retry the final commit the same way as before.
    import time as _time
    for addr, base_elo, mult, result, _breakdown in updates:
        # Replicate the exact pre-Stage-2 base_category_elo policy: backfill
        # it only if it was never set (NULL) or still sitting at the 1500.0
        # default; otherwise preserve whatever Writer A/a prior backfill set.
        # (This is Writer B's policy specifically — write_elo_result itself
        # takes whatever value the caller resolves, it has no opinion here.)
        existing_base_cat = base_cat_raw.get(addr)
        if existing_base_cat is None or abs(existing_base_cat - 1500.0) <= 0.0001:
            # Backfill branch — matches the old SQL's bound `round(base_elo, 6)`.
            final_base_cat = round(base_elo, 6)
        else:
            # Preserve branch — matches the old SQL's ELSE (column reassigned
            # to its own current value, unrounded). write_elo_result() does
            # not round base_category_elo itself; pass it through as-is.
            final_base_cat = existing_base_cat

        beh_mod, adv_mod, kelly, patience, timing = behavioral_snapshot.get(
            addr, (None, None, None, None, None)
        )
        write_elo_result(
            conn, addr, result,
            base_category_elo=final_base_cat,
            behavioral_modifier=beh_mod,
            advanced_modifier=adv_mod,
            kelly_alignment_score=kelly,
            patience_score=patience,
            timing_score=timing,
        )
    for _attempt in range(15):
        try:
            conn.commit()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                _time.sleep(2)
            else:
                raise
    written = len(updates)

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
