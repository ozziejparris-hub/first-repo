#!/usr/bin/env python3
"""
Automated ARB_BOT detection — patterns A, B, C.

Pattern A: Coordinated wallet factory clusters. Groups of 2+ traders with
           identical (ROUND(elo,2), resolved_trades_count, ROUND(pnl,2)),
           all first_seen within 60 minutes of each other, ≤3 distinct markets.

Pattern B: Symmetric YES/NO arb. ELO ≥1800, >50 YES-market buys, >50 NO-market
           buys, abs(yes-no)/(yes+no) < 0.03, >100 distinct markets, pnl < 1000.

Pattern C: Single-market concentration. >500 trades, exactly 1 distinct market.

On detection (unless --dry-run): sets bot_type='ARB_BOT', research_excluded=1,
bot_suspect=1. Appends to logs/arb_bot_exclusions.log.

Exit 0 always — non-blocking for daily_maintenance.
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
LOGS_DIR = Path(__file__).parent.parent / "logs"
ARB_LOG = LOGS_DIR / "arb_bot_exclusions.log"

# ── Pattern A ──────────────────────────────────────────────────────────────────
# Wallet factory clusters: identical metric fingerprint + tight first_seen window
# + ≤3 distinct markets traded.
PATTERN_A_DETECT_SQL = """
WITH candidate_markets AS (
    SELECT trader_address, COUNT(DISTINCT market_id) AS distinct_markets
    FROM trades
    GROUP BY trader_address
),
candidates AS (
    SELECT
        t.address,
        ROUND(t.comprehensive_elo, 2)  AS elo_r,
        t.resolved_trades_count        AS trade_count,
        ROUND(t.realized_pnl, 2)       AS pnl_r,
        t.first_seen
    FROM traders t
    JOIN candidate_markets cm ON cm.trader_address = t.address
    WHERE t.research_excluded = 0
      AND t.bot_type IS NULL
      AND t.comprehensive_elo IS NOT NULL
      AND t.first_seen IS NOT NULL
      AND cm.distinct_markets <= 3
),
fingerprints AS (
    SELECT
        elo_r, trade_count, pnl_r,
        COUNT(*)                                                           AS cluster_size,
        (JULIANDAY(MAX(first_seen)) - JULIANDAY(MIN(first_seen))) * 1440  AS span_minutes,
        MIN(first_seen)                                                    AS earliest,
        MAX(first_seen)                                                    AS latest
    FROM candidates
    GROUP BY elo_r, trade_count, pnl_r
    HAVING COUNT(*) >= 2
       AND (JULIANDAY(MAX(first_seen)) - JULIANDAY(MIN(first_seen))) * 1440 <= 60
)
SELECT
    c.address,
    f.elo_r,
    f.trade_count,
    f.pnl_r,
    f.cluster_size,
    f.span_minutes,
    f.earliest,
    f.latest
FROM candidates c
JOIN fingerprints f
  ON f.elo_r      = c.elo_r
 AND f.trade_count = c.trade_count
 AND f.pnl_r      = c.pnl_r
ORDER BY f.elo_r, c.address
"""

# ── Pattern B ──────────────────────────────────────────────────────────────────
# Symmetric arb: automated traders that buy both YES and NO across many markets
# with near-equal counts. High ELO but near-zero real P&L confirms arb artefact.
PATTERN_B_DETECT_SQL = """
WITH trader_sides AS (
    SELECT
        trader_address,
        COUNT(DISTINCT CASE WHEN outcome = 'Yes' AND side = 'BUY' THEN market_id END) AS long_yes,
        COUNT(DISTINCT CASE WHEN outcome = 'No'  AND side = 'BUY' THEN market_id END) AS long_no,
        COUNT(DISTINCT market_id) AS market_count
    FROM trades
    GROUP BY trader_address
)
SELECT
    t.address,
    t.comprehensive_elo,
    ts.long_yes,
    ts.long_no,
    ts.market_count,
    t.realized_pnl
FROM traders t
JOIN trader_sides ts ON ts.trader_address = t.address
WHERE t.research_excluded = 0
  AND t.bot_type IS NULL
  AND t.comprehensive_elo >= 1800
  AND ts.long_yes > 50
  AND ts.long_no > 50
  AND CAST(ABS(ts.long_yes - ts.long_no) AS REAL) / (ts.long_yes + ts.long_no) < 0.03
  AND ts.market_count > 100
  AND t.realized_pnl < 1000
ORDER BY t.comprehensive_elo DESC
"""

# ── Pattern C ──────────────────────────────────────────────────────────────────
# Single-market bots: very high trade volume concentrated in one market only.
PATTERN_C_DETECT_SQL = """
WITH trade_stats AS (
    SELECT
        trader_address,
        COUNT(*)               AS trade_count,
        COUNT(DISTINCT market_id) AS market_count
    FROM trades
    GROUP BY trader_address
    HAVING COUNT(*) > 500 AND COUNT(DISTINCT market_id) = 1
)
SELECT
    t.address,
    ts.trade_count,
    t.comprehensive_elo,
    t.realized_pnl
FROM traders t
JOIN trade_stats ts ON ts.trader_address = t.address
WHERE t.research_excluded = 0
  AND t.bot_type IS NULL
ORDER BY ts.trade_count DESC
"""

FLAG_SQL = """
UPDATE traders
SET bot_type = 'ARB_BOT', research_excluded = 1, bot_suspect = 1
WHERE address = ?
"""


def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def flag_wallets(conn, addresses):
    with conn:
        for addr in addresses:
            conn.execute(FLAG_SQL, (addr,))


def append_log(pattern_label, wallet_count, cluster_count, detail_lines):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with ARB_LOG.open("a") as f:
        f.write(
            f"\n{ts}: Pattern {pattern_label} — {wallet_count} ARB_BOT wallet(s) flagged"
            f" ({cluster_count} cluster{'s' if cluster_count != 1 else ''})\n"
        )
        for line in detail_lines:
            f.write(f"  {line}\n")


# ── Pattern A runner ───────────────────────────────────────────────────────────

def run_pattern_a(conn, dry_run):
    rows = conn.execute(PATTERN_A_DETECT_SQL).fetchall()
    if not rows:
        print("  Pattern A: 0 wallets detected")
        return 0, 0

    # Re-assemble into clusters keyed by (elo_r, trade_count, pnl_r).
    clusters = {}
    wallets = []
    for address, elo_r, trade_count, pnl_r, cluster_size, span_minutes, earliest, latest in rows:
        key = (elo_r, trade_count, pnl_r)
        if key not in clusters:
            clusters[key] = {
                "elo": elo_r, "trades": trade_count, "pnl": pnl_r,
                "size": cluster_size, "span_min": span_minutes,
                "earliest": earliest, "latest": latest,
                "addresses": [],
            }
        clusters[key]["addresses"].append(address)
        wallets.append(address)

    cluster_list = list(clusters.values())
    print(f"  Pattern A: {len(wallets)} wallet(s) in {len(cluster_list)} cluster(s)")
    for cl in cluster_list:
        print(
            f"    Cluster ELO={cl['elo']} trades={cl['trades']} pnl={cl['pnl']} "
            f"size={cl['size']} span={cl['span_min']:.1f}min "
            f"window={cl['earliest']}–{cl['latest']}"
        )
        for addr in cl["addresses"]:
            print(f"      {addr}")

    if dry_run:
        print("  [dry-run] No DB changes written.")
        return len(wallets), len(cluster_list)

    flag_wallets(conn, wallets)
    detail_lines = []
    for cl in cluster_list:
        detail_lines.append(
            f"Wallet factory cluster: ELO={cl['elo']} trades={cl['trades']} pnl={cl['pnl']} "
            f"({cl['size']} wallets, {cl['span_min']:.1f}min window, "
            f"{cl['earliest']}–{cl['latest']})"
        )
    detail_lines.append("Addresses: " + ", ".join(wallets))
    append_log("A", len(wallets), len(cluster_list), detail_lines)
    return len(wallets), len(cluster_list)


# ── Pattern B runner ───────────────────────────────────────────────────────────

def run_pattern_b(conn, dry_run):
    rows = conn.execute(PATTERN_B_DETECT_SQL).fetchall()
    if not rows:
        print("  Pattern B: 0 wallets detected")
        return 0, 0

    wallets = [r[0] for r in rows]
    print(f"  Pattern B: {len(wallets)} symmetric arb wallet(s)")
    for address, elo, long_yes, long_no, market_count, pnl in rows:
        symmetry_pct = (1 - abs(long_yes - long_no) / (long_yes + long_no)) * 100
        print(
            f"    {address}  ELO={elo:.0f} YES={long_yes} NO={long_no} "
            f"symmetry={symmetry_pct:.1f}% markets={market_count} pnl={pnl:.2f}"
        )

    if dry_run:
        print("  [dry-run] No DB changes written.")
        return len(wallets), len(wallets)

    flag_wallets(conn, wallets)
    detail_lines = [
        f"{address}: {long_yes}/{long_no} YES/NO symmetry, {market_count} markets, "
        f"ELO {elo:.0f}, pnl {pnl:.2f}"
        for address, elo, long_yes, long_no, market_count, pnl in rows
    ]
    append_log("B", len(wallets), len(wallets), detail_lines)
    return len(wallets), len(wallets)


# ── Pattern C runner ───────────────────────────────────────────────────────────

def run_pattern_c(conn, dry_run):
    rows = conn.execute(PATTERN_C_DETECT_SQL).fetchall()
    if not rows:
        print("  Pattern C: 0 wallets detected")
        return 0, 0

    wallets = [r[0] for r in rows]
    print(f"  Pattern C: {len(wallets)} single-market concentration wallet(s)")
    for address, trade_count, elo, pnl in rows:
        print(f"    {address}  trades={trade_count} ELO={elo:.0f} pnl={pnl:.2f}")

    if dry_run:
        print("  [dry-run] No DB changes written.")
        return len(wallets), len(wallets)

    flag_wallets(conn, wallets)
    detail_lines = [
        f"{address}: {trade_count} trades, 1 market, ELO {elo:.0f}, pnl {pnl:.2f}"
        for address, trade_count, elo, pnl in rows
    ]
    append_log("C", len(wallets), len(wallets), detail_lines)
    return len(wallets), len(wallets)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Detect and flag ARB_BOT traders.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect but do not write to DB or log",
    )
    parser.add_argument(
        "--pattern", choices=["A", "B", "C"],
        help="Run a single pattern only (default: all three)",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(0)

    try:
        conn = connect()
    except Exception as e:
        print(f"[ERROR] DB connection failed: {e}", file=sys.stderr)
        sys.exit(0)

    dry_label = " [DRY RUN]" if args.dry_run else ""
    print(f"=== ARB_BOT Detection{dry_label} ===")

    total_wallets = 0
    total_clusters = 0

    try:
        patterns_to_run = [args.pattern] if args.pattern else ["A", "B", "C"]
        for pattern in patterns_to_run:
            if pattern == "A":
                w, c = run_pattern_a(conn, args.dry_run)
            elif pattern == "B":
                w, c = run_pattern_b(conn, args.dry_run)
            else:
                w, c = run_pattern_c(conn, args.dry_run)
            total_wallets += w
            total_clusters += c
    except Exception as e:
        print(f"[ERROR] Detection failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(0)
    finally:
        conn.close()

    print(f"\n{total_wallets} wallet(s) flagged across {total_clusters} cluster(s)")
    sys.exit(0)


if __name__ == "__main__":
    main()
