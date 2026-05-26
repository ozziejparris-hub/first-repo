#!/usr/bin/env python3
"""
Composite Score Threshold Calibration

Reconstructs composite scores for all resolved geopolitics/elections trades
and finds the data-driven threshold that achieves >60% win rate with >=30 samples.

Usage:
    python scripts/calibrate_composite_threshold.py
    python scripts/calibrate_composite_threshold.py --dry-run   # print only, no file/DB changes
"""

import sys
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = str(project_root / "data" / "polymarket_tracker.db")
OUTPUT_PATH = Path.home() / "trading-swarm/brain/agent-outputs/composite-score-calibration-2026-05-26.md"

# Current thresholds in detect_insider_activity.py
CURRENT_MIN_COMPOSITE    = 0.30
CURRENT_HIGH_CONVICTION  = 0.60


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ── Score signals inline (same logic as calculate_composite_score) ─────────────

def _score_entry_price(price: float) -> float:
    if price <= 0.10:
        return 1.0
    elif price <= 0.20:
        return 0.8
    elif price <= 0.35:
        return 0.6
    elif price <= 0.50:
        return 0.2
    else:
        return 0.0


def _score_timing(days_before) -> float:
    if days_before is None:
        return 0.0
    if days_before <= 1:
        return 1.0
    elif days_before <= 3:
        return 0.8
    elif days_before <= 7:
        return 0.6
    elif days_before <= 14:
        return 0.4
    elif days_before <= 30:
        return 0.2
    else:
        return 0.0


def _score_concentration(markets_count: int) -> float:
    if markets_count <= 1:
        return 1.0
    elif markets_count <= 2:
        return 0.8
    elif markets_count <= 5:
        return 0.6
    elif markets_count <= 10:
        return 0.2
    else:
        return 0.0


def _calc_composite(position_size, entry_price, markets_count,
                     total_market_volume, trader_avg_position, days_before):
    # S1 — cross-sectional bet size
    if total_market_volume and total_market_volume > 0:
        cs_ratio = position_size / total_market_volume
        s1 = min(1.0, max(0.0, (cs_ratio - 0.01) / (0.10 - 0.01)))
    else:
        s1 = 0.0

    # S2 — within-trader anomaly
    if trader_avg_position and trader_avg_position > 0:
        wt_ratio = position_size / trader_avg_position
        s2 = min(1.0, max(0.0, (wt_ratio - 2.0) / (10.0 - 2.0)))
    else:
        s2 = 0.5  # no history → neutral

    s3 = _score_entry_price(entry_price)
    s4 = _score_timing(days_before)
    s5 = _score_concentration(markets_count)

    return round((s1 + s2 + s3 + s4 + s5) / 5.0, 4)


# ── Data loading ────────────────────────────────────────────────────────────────

def load_data(conn: sqlite3.Connection):
    print("[1/4] Loading trades (geo/elections, resolved, won/lost, price <= 0.80) ...")
    cur = conn.cursor()

    cur.execute("""
        SELECT
            tr.trade_id,
            tr.trader_address,
            tr.market_id,
            tr.price         AS entry_price,
            tr.shares,
            tr.timestamp     AS trade_timestamp,
            tr.trade_result
        FROM trades tr
        JOIN markets m ON tr.market_id = m.market_id
        WHERE tr.trade_result IN ('won', 'lost')
          AND tr.market_category IN ('Geopolitics', 'Elections')
          AND tr.price <= 0.80
          AND tr.price > 0
          AND tr.shares > 0
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """)
    trades = cur.fetchall()
    print(f"    {len(trades):,} eligible trades loaded")

    print("[2/4] Loading lookup tables (markets_count, market_volume, trader_avg) ...")

    # markets_count per trader (total distinct markets ever traded)
    cur.execute("""
        SELECT trader_address, COUNT(DISTINCT market_id) AS cnt
        FROM trades
        GROUP BY trader_address
    """)
    markets_count_map = {r[0]: r[1] for r in cur.fetchall()}

    # total market volume per market_id (from positions table)
    cur.execute("""
        SELECT market_id, SUM(entry_total_cost) AS vol
        FROM positions
        GROUP BY market_id
    """)
    market_volume_map = {r[0]: r[1] for r in cur.fetchall()}

    # trader avg position size per trader (from positions table)
    cur.execute("""
        SELECT trader_address, AVG(entry_total_cost) AS avg_pos
        FROM positions
        GROUP BY trader_address
    """)
    trader_avg_map = {r[0]: r[1] for r in cur.fetchall()}

    # resolution_date per market_id
    cur.execute("""
        SELECT market_id, resolution_date
        FROM markets
        WHERE resolution_date IS NOT NULL
    """)
    resolution_date_map = {r[0]: r[1] for r in cur.fetchall()}

    print("    Lookup tables ready")
    return trades, markets_count_map, market_volume_map, trader_avg_map, resolution_date_map


# ── Composite scoring pass ──────────────────────────────────────────────────────

def score_all_trades(trades, markets_count_map, market_volume_map,
                     trader_avg_map, resolution_date_map):
    print("[3/4] Calculating composite scores ...")
    results = []
    skipped = 0

    for row in trades:
        addr        = row["trader_address"]
        market_id   = row["market_id"]
        price       = row["entry_price"]
        shares      = row["shares"]
        ts_str      = row["trade_timestamp"]
        result      = row["trade_result"]   # 'won' or 'lost'

        position_size = shares * price

        # Hard disqualification (matches calculate_composite_score)
        if price > 0.80:
            skipped += 1
            continue

        mkts_count         = markets_count_map.get(addr, 0)
        total_mkt_vol      = market_volume_map.get(market_id)
        trader_avg         = trader_avg_map.get(addr)
        resolution_date_s  = resolution_date_map.get(market_id)

        # Compute days_before
        days_before = None
        if resolution_date_s and ts_str:
            try:
                res_dt   = datetime.fromisoformat(
                    str(resolution_date_s).replace("Z", "").split("+")[0]
                )
                trade_dt = datetime.fromisoformat(str(ts_str))
                days_before = (res_dt - trade_dt).total_seconds() / 86400.0
            except Exception:
                pass

        composite = _calc_composite(
            position_size, price, mkts_count,
            total_mkt_vol, trader_avg, days_before,
        )

        results.append({
            "composite": composite,
            "won":       1 if result == "won" else 0,
        })

    print(f"    Scored {len(results):,} trades ({skipped} skipped by price gate)")
    return results


# ── Calibration table ───────────────────────────────────────────────────────────

def build_calibration_table(results):
    print("[4/4] Building calibration table ...")
    rows = []
    thresholds = [round(t / 100, 2) for t in range(10, 95, 5)]

    for thresh in thresholds:
        subset = [r for r in results if r["composite"] >= thresh]
        n      = len(subset)
        wins   = sum(r["won"] for r in subset)
        win_rate = (wins / n * 100) if n > 0 else 0.0
        rows.append({
            "threshold": thresh,
            "n":         n,
            "wins":      wins,
            "win_rate":  win_rate,
        })

    return rows


def find_optimal(cal_rows, min_win_rate=60.0, min_sample=30):
    for row in cal_rows:
        if row["n"] >= min_sample and row["win_rate"] >= min_win_rate:
            return row
    return None


# ── Mitts/Ofir benchmark positioning ───────────────────────────────────────────

def mitts_ofir_context(cal_rows):
    """Return calibration row closest to the 69.9% benchmark level."""
    target = 69.9
    closest = min(cal_rows, key=lambda r: abs(r["win_rate"] - target) if r["n"] > 0 else float("inf"))
    return closest


# ── Report generation ───────────────────────────────────────────────────────────

def print_report(cal_rows, optimal, results, dry_run):
    total = len(results)
    print()
    print("=" * 68)
    print("  COMPOSITE SCORE THRESHOLD CALIBRATION")
    print(f"  Total scored trades: {total:,}")
    print("=" * 68)
    print()
    print(f"  {'Threshold':>10}  {'Sample N':>9}  {'Wins':>7}  {'Win Rate':>9}  {'Flag'}")
    print(f"  {'-'*10}  {'-'*9}  {'-'*7}  {'-'*9}  {'-'*20}")

    for row in cal_rows:
        flag = ""
        if optimal and row["threshold"] == optimal["threshold"]:
            flag = "<-- OPTIMAL"
        if row["threshold"] == CURRENT_MIN_COMPOSITE:
            flag += "  [current MIN]" if flag else "[current MIN_COMPOSITE_SCORE]"
        if row["threshold"] == CURRENT_HIGH_CONVICTION:
            flag += "  [current HIGH_CONV]" if flag else "[current HIGH_CONVICTION_THRESHOLD]"
        stats = f"{row['win_rate']:6.1f}%" if row["n"] > 0 else "   n/a"
        print(f"  {row['threshold']:>10.2f}  {row['n']:>9,}  {row['wins']:>7,}  {stats:>9}  {flag}")

    print()
    if optimal:
        print(f"  OPTIMAL THRESHOLD: {optimal['threshold']:.2f}  "
              f"(win rate {optimal['win_rate']:.1f}%, n={optimal['n']:,})")
    else:
        print("  No threshold achieved >= 60% win rate with >= 30 samples.")

    print()
    print(f"  Current MIN_COMPOSITE_SCORE    = {CURRENT_MIN_COMPOSITE}")
    print(f"  Current HIGH_CONVICTION_THRESHOLD = {CURRENT_HIGH_CONVICTION}")
    print()


# ── Markdown report ─────────────────────────────────────────────────────────────

def write_markdown(cal_rows, optimal, results, dry_run):
    total = len(results)

    # What did the data say about overall win rate
    all_wins = sum(r["won"] for r in results)
    baseline = all_wins / total * 100 if total > 0 else 0

    lines = []
    lines.append("# Composite Score Threshold Calibration — 2026-05-26")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append("Reconstructed composite scores for **all resolved geopolitics/elections**")
    lines.append("trades in the DB using the five-signal Mitts/Ofir formula from")
    lines.append("`detect_insider_activity.py`. Lookup data (market volumes, trader avg")
    lines.append("position, markets_count, resolution dates) was pre-fetched in bulk to")
    lines.append("avoid per-row DB queries.")
    lines.append("")
    lines.append("**Filters applied:**")
    lines.append("- `trade_result IN ('won', 'lost')` — resolved only")
    lines.append("- `market_category IN ('Geopolitics', 'Elections')`")
    lines.append("- `entry_price <= 0.80` — exclude near-certainty arb")
    lines.append("- `trade_gap_flag = 0` — exclude Apr 7–18 gap window")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- **Total eligible trades:** {total:,}")
    lines.append(f"- **Baseline win rate (all trades, no threshold):** {baseline:.1f}%")
    lines.append("")
    lines.append("## Calibration Table")
    lines.append("")
    lines.append("| Threshold | Sample N | Wins | Win Rate | Notes |")
    lines.append("|----------:|---------:|-----:|---------:|-------|")

    for row in cal_rows:
        notes = []
        if optimal and row["threshold"] == optimal["threshold"]:
            notes.append("**← OPTIMAL**")
        if row["threshold"] == CURRENT_MIN_COMPOSITE:
            notes.append(f"current `MIN_COMPOSITE_SCORE`")
        if row["threshold"] == CURRENT_HIGH_CONVICTION:
            notes.append(f"current `HIGH_CONVICTION_THRESHOLD`")
        note_str = ", ".join(notes) if notes else ""
        wr = f"{row['win_rate']:.1f}%" if row["n"] > 0 else "n/a"
        lines.append(
            f"| {row['threshold']:.2f} | {row['n']:,} | {row['wins']:,} | {wr} | {note_str} |"
        )

    lines.append("")
    lines.append("## Findings")
    lines.append("")

    if optimal:
        lines.append(f"**Optimal threshold: `{optimal['threshold']:.2f}`**")
        lines.append(f"- Win rate: {optimal['win_rate']:.1f}% (requirement: ≥60%)")
        lines.append(f"- Sample size: {optimal['n']:,} (requirement: ≥30)")
        delta = optimal["threshold"] - CURRENT_MIN_COMPOSITE
        direction = "higher" if delta > 0 else "lower"
        lines.append(f"- Delta from current `MIN_COMPOSITE_SCORE` ({CURRENT_MIN_COMPOSITE}): "
                     f"{abs(delta):.2f} {direction}")
    else:
        lines.append("No threshold achieved ≥60% win rate with ≥30 samples.")
        lines.append(f"- Baseline win rate across all geo/elections trades: {baseline:.1f}%")
        lines.append("- The composite score does not reliably stratify outcomes at this scale,")
        lines.append("  or signal coverage is too sparse at high thresholds.")

    lines.append("")
    lines.append("### Mitts/Ofir 69.9% Benchmark Context")
    lines.append("")
    bench = mitts_ofir_context(cal_rows)
    if bench and bench["n"] > 0:
        lines.append(f"The Mitts/Ofir paper reports 69.9% accuracy on insider-flagged trades.")
        lines.append(f"In our data, the threshold closest to matching that win rate is "
                     f"`{bench['threshold']:.2f}` ({bench['win_rate']:.1f}%, n={bench['n']:,}).")
        if bench["n"] < 30:
            lines.append(f"  - ⚠️ Sample too small (n={bench['n']}) for statistical confidence.")
    else:
        lines.append("No threshold in our distribution matches the Mitts/Ofir 69.9% benchmark.")

    lines.append("")
    lines.append("## Threshold Update Decision")
    lines.append("")

    if optimal:
        delta = abs(optimal["threshold"] - CURRENT_MIN_COMPOSITE)
        if delta > 0.05:
            lines.append(f"**Action: Update `MIN_COMPOSITE_SCORE` → `{optimal['threshold']:.2f}`**")
            lines.append(f"(delta = {delta:.2f}, exceeds 0.05 update threshold)")
        else:
            lines.append(f"**No update needed.** Optimal threshold `{optimal['threshold']:.2f}` is "
                         f"within 0.05 of current `{CURRENT_MIN_COMPOSITE}` "
                         f"(delta = {delta:.2f}).")

        hc_candidates = [r for r in cal_rows if r["n"] >= 30 and r["win_rate"] >= 65.0]
        if hc_candidates:
            hc_optimal = hc_candidates[-1]  # highest threshold still meeting criteria
            hc_delta = abs(hc_optimal["threshold"] - CURRENT_HIGH_CONVICTION)
            if hc_delta > 0.05:
                lines.append(f"**Action: Update `HIGH_CONVICTION_THRESHOLD` → "
                             f"`{hc_optimal['threshold']:.2f}`**")
                lines.append(f"(achieves {hc_optimal['win_rate']:.1f}% with n={hc_optimal['n']:,})")
            else:
                lines.append(f"**`HIGH_CONVICTION_THRESHOLD` unchanged** (current {CURRENT_HIGH_CONVICTION} "
                             f"within 0.05 of data-optimal).")
        else:
            lines.append(f"**`HIGH_CONVICTION_THRESHOLD` unchanged** — no threshold achieves "
                         f"≥65% with ≥30 samples.")
    else:
        lines.append("**No update.** Insufficient statistical evidence to change thresholds.")

    lines.append("")
    lines.append("---")
    lines.append(f"*Generated: 2026-05-26 | DB: polymarket_tracker.db*")

    report = "\n".join(lines)

    if not dry_run:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(report)
        print(f"  Report written to: {OUTPUT_PATH}")
    else:
        print("  [DRY RUN] Report not written.")
        print()
        print(report)

    return report


# ── Threshold update ────────────────────────────────────────────────────────────

def update_thresholds(cal_rows, optimal, dry_run):
    detect_path = project_root / "scripts" / "detect_insider_activity.py"
    source = detect_path.read_text()

    changes = []

    # MIN_COMPOSITE_SCORE update
    if optimal:
        delta = abs(optimal["threshold"] - CURRENT_MIN_COMPOSITE)
        if delta > 0.05:
            new_val = optimal["threshold"]
            old_line = f"        if composite < {CURRENT_MIN_COMPOSITE}:"
            new_line = f"        if composite < {new_val}:"
            if old_line in source:
                changes.append(("MIN_COMPOSITE_SCORE", CURRENT_MIN_COMPOSITE, new_val))
                source = source.replace(old_line, new_line)
            else:
                print(f"  WARNING: Could not find MIN_COMPOSITE_SCORE line to update")

        # HIGH_CONVICTION_THRESHOLD — find highest threshold >=65% with >=30 samples
        hc_candidates = [r for r in cal_rows if r["n"] >= 30 and r["win_rate"] >= 65.0]
        if hc_candidates:
            hc_optimal = hc_candidates[-1]
            hc_delta = abs(hc_optimal["threshold"] - CURRENT_HIGH_CONVICTION)
            if hc_delta > 0.05:
                new_hc = hc_optimal["threshold"]
                # Update in composite score function: composite >= 0.60
                old_hc_line = f"            elif composite >= {CURRENT_HIGH_CONVICTION}:"
                new_hc_line = f"            elif composite >= {new_hc}:"
                if old_hc_line in source:
                    changes.append(("HIGH_CONVICTION_THRESHOLD", CURRENT_HIGH_CONVICTION, new_hc))
                    source = source.replace(old_hc_line, new_hc_line)
                else:
                    print(f"  WARNING: Could not find HIGH_CONVICTION_THRESHOLD line to update")

    if changes:
        if not dry_run:
            detect_path.write_text(source)
            for name, old, new in changes:
                print(f"  Updated {name}: {old} → {new}")
        else:
            for name, old, new in changes:
                print(f"  [DRY RUN] Would update {name}: {old} → {new}")
    else:
        print("  No threshold updates needed (within 0.05 tolerance or no optimal found).")


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Composite score threshold calibration")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report but do not write files or update thresholds")
    args = parser.parse_args()

    import os
    os.chdir(project_root)

    print()
    print("=" * 68)
    print("  COMPOSITE SCORE CALIBRATION — 2026-05-26")
    print("=" * 68)
    print()

    conn = connect(DB_PATH)
    trades, markets_count_map, market_volume_map, trader_avg_map, resolution_date_map = load_data(conn)
    conn.close()

    results    = score_all_trades(trades, markets_count_map, market_volume_map,
                                   trader_avg_map, resolution_date_map)
    cal_rows   = build_calibration_table(results)
    optimal    = find_optimal(cal_rows)

    print_report(cal_rows, optimal, results, args.dry_run)

    print("Writing markdown report ...")
    write_markdown(cal_rows, optimal, results, args.dry_run)

    print()
    print("Checking threshold updates ...")
    update_thresholds(cal_rows, optimal, args.dry_run)

    print()
    print("Done.")
    print()


if __name__ == "__main__":
    main()
