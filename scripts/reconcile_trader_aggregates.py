#!/usr/bin/env python3
"""
reconcile_trader_aggregates.py — Layer 1 single-writer aggregate reconciler.

Run with --dry-run first to validate; run without flags to apply.

INTEGRATION CONTRACT — canonical column definitions
=====================================================
All columns listed here are OWNED by this script (single-writer pattern).
No other script may write these columns without coordinating through this
reconciler. Values are recomputed from local tables on every run; never
accumulated from previous values.

Column                 Source table      Formula
──────────────────────────────────────────────────────────────────────────────
total_trades           trades            COUNT(*) per trader_address
successful_trades      trades            COUNT(*) WHERE trade_result = 'won'
resolved_trades_count  trades            COUNT(DISTINCT market_id) WHERE
                                           trade_result IN ('won', 'lost')
total_volume           trades            SUM(shares * price) per trader_address

total_invested         positions         SUM(entry_total_cost) WHERE status='closed'
                                         [pnl_skip=1 → preserve existing value]
avg_roi                positions         AVG(roi_percent) WHERE status='closed'
                                         [pnl_skip=1 → preserve existing value]
realized_pnl           positions         SUM(realized_pnl) WHERE status='closed'
                                         [pnl_skip=1 → preserve existing value]
closed_positions       positions         COUNT(*) WHERE status='closed'
open_positions         positions         COUNT(*) WHERE status='open'

win_rate               derived           MIN(1.0, successful_trades /
                                           resolved_trades_count) as FRACTION
                                           [0.0, 1.0]; 0.0 if div-by-zero.
                                         NOTE: successful_trades is a trade count;
                                         resolved_trades_count is a distinct-market
                                         count. In theory these are equal (one trade
                                         per market), but the MIN(1.0) cap enforces
                                         the [0,1] contract if they diverge.

specialisation_ratio   trader_categories MAX(trade_count) / SUM(trade_count)
                                         across all categories where trade_count>0.
                                         Naturally bounded [0.0, 1.0] since MAX≤SUM.
                                         NULL preserved for traders with no
                                         trader_categories rows.

NOT OWNED BY THIS SCRIPT — do not touch:
  roi_percentage, total_pnl, unrealized_pnl   DEAD/DUPLICATE — drop next session
  comprehensive_elo, base_category_elo,        Layer 2 (ELO chain — see
    behavioral_modifier, advanced_modifier,    recalculate_comprehensive_elo.py)
    pnl_modifier, kelly_alignment_score,
    patience_score, timing_score,
    weighted_win_rate, geo_elo, geo_elo_active
  geo_resolved_trades_count, geo_accuracy_pool Already reconciled by
                                               reconcile_geo_resolved_counts.py

KNOWN SECONDARY WRITER VIOLATION (not fixed here — flag for next session):
  monitoring/trader_statistics.py writes win_rate as a PERCENTAGE (×100)
  via add_or_update_trader(). This will re-introduce win_rate > 1.0 violations
  after the next resolution check cycle. That writer must also be neutralized.
"""

import argparse
import sqlite3
import sys
from datetime import datetime

DB_PATH = "data/polymarket_tracker.db"
BATCH_SIZE = 5000


def get_violation_counts(conn):
    """Count the three CRITICAL data-integrity violations."""
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN successful_trades > total_trades THEN 1 ELSE 0 END),
            SUM(CASE WHEN win_rate > 1.0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN specialisation_ratio > 1.0 THEN 1 ELSE 0 END)
        FROM traders
    """).fetchone()
    return {
        "succ_gt_total": row[0] or 0,
        "win_rate_gt_1": row[1] or 0,
        "spec_gt_1":     row[2] or 0,
    }


def fetch_new_values(conn):
    """
    Compute all new aggregate values in one pass using SQL CTEs.

    Returns sqlite3.Row objects with old_* and new_* fields for every trader.
    The large JOIN is intentional — we want one consistent snapshot per trader,
    not interleaved reads across multiple passes.

    For position-derived columns, NULL from pos_agg means the trader has no
    position rows; the caller handles the pnl_skip guard before writing.
    """
    return conn.execute("""
        WITH trade_agg AS (
            SELECT
                trader_address,
                COUNT(*)                                                       AS total_trades,
                SUM(CASE WHEN trade_result = 'won'  THEN 1 ELSE 0 END)        AS successful_trades,
                COUNT(DISTINCT
                    CASE WHEN trade_result IN ('won', 'lost')
                         THEN market_id END)                                   AS resolved_trades_count,
                SUM(shares * price)                                            AS total_volume
            FROM trades
            GROUP BY trader_address
        ),
        pos_agg AS (
            SELECT
                trader_address,
                SUM(CASE WHEN status = 'closed' THEN entry_total_cost END)    AS total_invested,
                AVG(CASE WHEN status = 'closed' THEN roi_percent END)          AS avg_roi,
                SUM(CASE WHEN status = 'closed' THEN realized_pnl END)         AS realized_pnl,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END)             AS closed_positions,
                SUM(CASE WHEN status = 'open'   THEN 1 ELSE 0 END)             AS open_positions
            FROM positions
            GROUP BY trader_address
        ),
        spec_agg AS (
            -- Correct specialisation_ratio: fraction of categorised trades in
            -- the trader's top category.  Naturally in [0, 1] since MAX <= SUM.
            SELECT
                trader_address,
                MIN(1.0,
                    CAST(MAX(trade_count) AS REAL) /
                    NULLIF(SUM(trade_count), 0)
                ) AS specialisation_ratio
            FROM trader_categories
            WHERE trade_count > 0
            GROUP BY trader_address
        )
        SELECT
            t.address,
            t.pnl_skip,

            -- current values (used to count diffs in dry-run)
            t.total_trades              AS old_total_trades,
            t.successful_trades         AS old_successful_trades,
            t.resolved_trades_count     AS old_resolved_trades_count,
            t.total_volume              AS old_total_volume,
            t.total_invested            AS old_total_invested,
            t.avg_roi                   AS old_avg_roi,
            t.realized_pnl              AS old_realized_pnl,
            t.closed_positions          AS old_closed_positions,
            t.open_positions            AS old_open_positions,
            t.win_rate                  AS old_win_rate,
            t.specialisation_ratio      AS old_specialisation_ratio,

            -- new trade-derived values (0 if trader has no trades)
            COALESCE(ta.total_trades,          0)    AS new_total_trades,
            COALESCE(ta.successful_trades,     0)    AS new_successful_trades,
            COALESCE(ta.resolved_trades_count, 0)    AS new_resolved_trades_count,
            COALESCE(ta.total_volume,          0.0)  AS new_total_volume,

            -- new position-derived values (NULL = no positions; pnl_skip guard in Python)
            pa.total_invested                         AS new_total_invested,
            pa.avg_roi                                AS new_avg_roi,
            pa.realized_pnl                           AS new_realized_pnl,
            COALESCE(pa.closed_positions, 0)          AS new_closed_positions,
            COALESCE(pa.open_positions,   0)          AS new_open_positions,

            -- new specialisation_ratio (NULL = no trader_categories rows)
            sa.specialisation_ratio                   AS new_specialisation_ratio

        FROM traders t
        LEFT JOIN trade_agg ta ON t.address = ta.trader_address
        LEFT JOIN pos_agg   pa ON t.address = pa.trader_address
        LEFT JOIN spec_agg  sa ON t.address = sa.trader_address
    """).fetchall()


def compute_win_rate(new_st, new_rtc):
    """
    win_rate = MIN(1.0, successful_trades / resolved_trades_count).
    The MIN(1.0) cap enforces the [0,1] contract: if a trader placed multiple
    trades in a single market, successful_trades can exceed resolved_trades_count
    (distinct-market count).  Returns 0.0 on divide-by-zero.
    """
    if new_rtc and new_rtc > 0:
        return min(1.0, new_st / new_rtc)
    return 0.0


def val_changed(old, new):
    """Return True if old and new are meaningfully different."""
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return abs(float(old) - float(new)) > 1e-9


def main():
    parser = argparse.ArgumentParser(
        description="Layer 1 aggregate reconciler — recomputes simple aggregates from local data."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report projected changes without writing anything to the database."
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")
    conn.row_factory = sqlite3.Row

    print("\n=== reconcile_trader_aggregates.py ===")
    print(f"Mode   : {'DRY RUN (no writes)' if args.dry_run else 'LIVE WRITE'}")
    print(f"Started: {datetime.now().isoformat()}")

    before = get_violation_counts(conn)
    print("\nBEFORE — CRITICAL violation counts:")
    print(f"  successful_trades > total_trades : {before['succ_gt_total']}")
    print(f"  win_rate > 1.0                   : {before['win_rate_gt_1']}")
    print(f"  specialisation_ratio > 1.0       : {before['spec_gt_1']}")

    print("\nComputing new aggregate values (single-pass CTE JOIN) ...")
    rows = fetch_new_values(conn)
    total = len(rows)
    print(f"  → {total} traders loaded\n")

    # ── Accumulate diffs ─────────────────────────────────────────────────────
    col_changed = {c: 0 for c in [
        "total_trades", "successful_trades", "resolved_trades_count", "total_volume",
        "total_invested", "avg_roi", "realized_pnl",
        "closed_positions", "open_positions", "win_rate", "specialisation_ratio",
    ]}
    crit_would_fix = {"succ_gt_total": 0, "win_rate_gt_1": 0, "spec_gt_1": 0}
    pnl_skip_count = 0
    spec_recomputed = 0
    spec_preserved  = 0
    win_rate_capped  = 0  # traders where MIN(1.0,...) cap actually kicks in

    update_params = []  # (new values..., address)

    for row in rows:
        address  = row["address"]
        pnl_skip = bool(row["pnl_skip"])
        if pnl_skip:
            pnl_skip_count += 1

        # -- trade-derived (always recompute) --
        new_tt  = row["new_total_trades"]
        new_st  = row["new_successful_trades"]
        new_rtc = row["new_resolved_trades_count"]
        new_tv  = row["new_total_volume"]

        # -- derived win_rate --
        raw_wr  = (new_st / new_rtc) if new_rtc else 0.0
        new_wr  = min(1.0, raw_wr)
        if raw_wr > 1.0:
            win_rate_capped += 1

        # -- position-derived (preserve if pnl_skip) --
        if pnl_skip:
            new_ti = row["old_total_invested"]
            new_ar = row["old_avg_roi"]
            new_rp = row["old_realized_pnl"]
        else:
            new_ti = row["new_total_invested"]
            new_ar = row["new_avg_roi"]
            new_rp = row["new_realized_pnl"]

        new_cp = row["new_closed_positions"]
        new_op = row["new_open_positions"]

        # -- specialisation_ratio (recompute where available, preserve otherwise) --
        if row["new_specialisation_ratio"] is not None:
            new_sr = row["new_specialisation_ratio"]
            spec_recomputed += 1
        else:
            new_sr = row["old_specialisation_ratio"]
            spec_preserved += 1

        # -- count column diffs --
        if val_changed(row["old_total_trades"],          new_tt):  col_changed["total_trades"] += 1
        if val_changed(row["old_successful_trades"],     new_st):  col_changed["successful_trades"] += 1
        if val_changed(row["old_resolved_trades_count"], new_rtc): col_changed["resolved_trades_count"] += 1
        if val_changed(row["old_total_volume"],          new_tv):  col_changed["total_volume"] += 1
        if not pnl_skip:
            if val_changed(row["old_total_invested"],    new_ti):  col_changed["total_invested"] += 1
            if val_changed(row["old_avg_roi"],           new_ar):  col_changed["avg_roi"] += 1
            if val_changed(row["old_realized_pnl"],      new_rp):  col_changed["realized_pnl"] += 1
        if val_changed(row["old_closed_positions"],      new_cp):  col_changed["closed_positions"] += 1
        if val_changed(row["old_open_positions"],        new_op):  col_changed["open_positions"] += 1
        if val_changed(row["old_win_rate"],              new_wr):  col_changed["win_rate"] += 1
        if val_changed(row["old_specialisation_ratio"],  new_sr):  col_changed["specialisation_ratio"] += 1

        # -- count CRITICAL violations that would be fixed --
        old_succ  = row["old_successful_trades"] or 0
        old_tot   = row["old_total_trades"]       or 0
        old_wr    = row["old_win_rate"]            or 0.0
        old_sr    = row["old_specialisation_ratio"] or 0.0

        if old_succ > old_tot and new_st <= new_tt:
            crit_would_fix["succ_gt_total"] += 1
        if old_wr > 1.0 and new_wr <= 1.0:
            crit_would_fix["win_rate_gt_1"] += 1
        if old_sr > 1.0 and (new_sr is None or new_sr <= 1.0):
            crit_would_fix["spec_gt_1"] += 1

        update_params.append((
            new_tt, new_st, new_rtc, new_tv,
            new_ti, new_ar, new_rp,
            new_cp, new_op,
            new_wr, new_sr,
            address,
        ))

    # ── Report ────────────────────────────────────────────────────────────────
    print("─" * 60)
    print(f"{'DRY-RUN PROJECTION' if args.dry_run else 'CHANGE SUMMARY'}")
    print("─" * 60)
    print(f"  Traders with pnl_skip=1 (PnL columns preserved)  : {pnl_skip_count}")
    print(f"  specialisation_ratio recomputed from trader_cats   : {spec_recomputed}")
    print(f"  specialisation_ratio preserved (no cat rows)       : {spec_preserved}")
    print(f"  win_rate capped at 1.0 (multi-trade-per-market)   : {win_rate_capped}")
    print()
    print("  Column-level changes (traders where value would differ):")
    for col, n in col_changed.items():
        print(f"    {col:<30} : {n:>6}")
    print()
    print("  CRITICAL violations → projected outcome:")
    print(f"    successful_trades > total_trades :"
          f" {before['succ_gt_total']} before → "
          f"{before['succ_gt_total'] - crit_would_fix['succ_gt_total']} after"
          f"  ({crit_would_fix['succ_gt_total']} fixed)")
    print(f"    win_rate > 1.0                   :"
          f" {before['win_rate_gt_1']} before → "
          f"{before['win_rate_gt_1'] - crit_would_fix['win_rate_gt_1']} after"
          f"  ({crit_would_fix['win_rate_gt_1']} fixed)")
    print(f"    specialisation_ratio > 1.0       :"
          f" {before['spec_gt_1']} before → "
          f"{before['spec_gt_1'] - crit_would_fix['spec_gt_1']} after"
          f"  ({crit_would_fix['spec_gt_1']} fixed)")

    remaining_wr = before["win_rate_gt_1"] - crit_would_fix["win_rate_gt_1"]
    if remaining_wr > 0:
        print(f"\n  ⚠  WARNING: {remaining_wr} win_rate > 1.0 violations persist after reconcile.")
        print("     Cause: successful_trades (trade count) > resolved_trades_count")
        print("     (distinct-market count) — same market, multiple trades.")
        print("     These are capped to 1.0 by the MIN(1.0,...) guard in this script.")
        print("     If still nonzero after run, the cap is working — count will be 0.")

    if args.dry_run:
        print("\n── DRY RUN complete — no changes written. ──")
        conn.close()
        return

    # ── Live write ────────────────────────────────────────────────────────────
    print(f"\nWriting in batches of {BATCH_SIZE} ...")
    total_written = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = update_params[batch_start : batch_start + BATCH_SIZE]
        batch_end = min(batch_start + BATCH_SIZE, total)
        print(f"  Batch {batch_start + 1}–{batch_end} / {total} ...")
        conn.execute("BEGIN")
        conn.executemany("""
            UPDATE traders SET
                total_trades           = ?,
                successful_trades      = ?,
                resolved_trades_count  = ?,
                total_volume           = ?,
                total_invested         = ?,
                avg_roi                = ?,
                realized_pnl           = ?,
                closed_positions       = ?,
                open_positions         = ?,
                win_rate               = ?,
                specialisation_ratio   = ?,
                last_updated           = CURRENT_TIMESTAMP
            WHERE address = ?
        """, batch)
        conn.commit()
        total_written += len(batch)

    after = get_violation_counts(conn)
    print()
    print("─" * 60)
    print("AFTER — CRITICAL violation counts:")
    print(f"  successful_trades > total_trades : {after['succ_gt_total']}")
    print(f"  win_rate > 1.0                   : {after['win_rate_gt_1']}")
    print(f"  specialisation_ratio > 1.0       : {after['spec_gt_1']}")
    print("─" * 60)
    print(f"\n✅  Reconcile complete — {total_written} traders updated.")
    print(f"    Finished: {datetime.now().isoformat()}")

    conn.close()


if __name__ == "__main__":
    main()
