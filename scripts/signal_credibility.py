"""
signal_credibility.py

Signal Credibility Score (SCS, 0-100) for markets in the legendary
positions scan. Answers: "how much should we trust this signal?"

Methodology adapted from arXiv 2604.24147 (Signal Credibility Index):
directionality of flow, two-sidedness penalty, and trader-concentration
adjustment — mapped onto our LEGENDARY net-position data.

CANONICAL DEFINITIONS: See brain/integration-contract.md Section 10.
LEGENDARY: geo_elo_active >= 2175 AND geo_accuracy_pool = 1 (NOT comprehensive_elo).
Pool filter: research_excluded = 0 AND bot_type IS NULL.
JOIN key: trades.market_id = markets.market_id (NEVER condition_id — SCL-004).
Trade filter: timestamp <= datetime('now') (37 future-dated trades — Section 2).

Components:
  1. Net Position Conviction (0..40)
     Per-trader net_position = signed YES shares minus signed NO shares
     (BUY adds, SELL subtracts, NO legs negated). Traders with
     abs(net_position) > 1.0 are "net-committed". Consensus = fraction
     of net-committed traders agreeing on direction. Score = 40 * consensus^2.
  2. Two-Sidedness Penalty (-20..0)
     both_sides_ratio = min(yes_cap, no_cap) / max(yes_cap, no_cap)
     over net capital by direction. Penalty = -20 * ratio.
  3. Entry Timing Alpha (0..20)
     Per net-committed trader: current price of their side minus their
     capital-weighted avg entry price on that side.
     > 0.20 → 20 pts; 0.10-0.20 → 10; 0-0.10 → 5; < 0 → 0. Market score
     is the mean across net-committed traders.
  4. Conviction Depth (0..20)
     relative_size = trader's BUY notional on this market (net side)
     / trader's avg per-market BUY notional across all markets.
     Per-trader score = 20 * min(max(rel, 0), 2) / 2; market score is
     the mean across net-committed traders.

Final SCS = clamp(C1 + C2 + C3 + C4, 0, 100).
Tiers: >= 70 HIGH CREDIBILITY, 40-69 MEDIUM, < 40 LOW.

Pre-registered as RQ-SCI-001 (brain/strategy-notes/research-directions.md).

Usage:
  python scripts/signal_credibility.py                     # enrich latest scan JSON
  python scripts/signal_credibility.py --scan-json PATH    # enrich a specific scan JSON
  python scripts/signal_credibility.py --market-id 0x... --price-yes 0.29
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"
SCAN_DIR = Path("/home/parison/trading-swarm/brain/agent-outputs/positions-scan")

ELO_LEGENDARY = 2175           # integration-contract Section 10.1 (geo_elo_active)
NET_COMMIT_THRESHOLD = 1.0     # abs(net shares) above this = genuine commitment

TIER_HIGH = 70
TIER_MEDIUM = 40


def get_conn() -> sqlite3.Connection:
    # Connection pattern from integration-contract.md Section 1
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# ---------------------------------------------------------------------------
# Core data structure: per-trader net positions on a market
# ---------------------------------------------------------------------------

def compute_net_positions(conn: sqlite3.Connection, market_id: str) -> dict:
    """
    Net position per LEGENDARY trader on one market. The reusable core
    of the SCS — also what the POSITIONS-ANALYSIS-001 finding asked for.

    Returns {address: {
        net_position      : signed shares (+YES / -NO),
        net_direction     : 'YES' | 'NO' | 'FLAT',
        net_committed     : abs(net_position) > NET_COMMIT_THRESHOLD,
        avg_entry_price   : capital-weighted avg BUY price on net side (None if FLAT),
        net_capital       : abs(net_position) * avg_entry_price (0.0 if FLAT),
        side_buy_notional : total BUY notional on net side,
    }}

    Traders with no SELL trades net to their full BUY position; traders
    with a single trade produce a one-row aggregate — both fall out of
    the same signed-sum arithmetic.
    """
    cur = conn.execute("""
        SELECT
            t.trader_address              AS address,
            LOWER(t.outcome)              AS outcome,
            UPPER(t.side)                 AS side,
            SUM(t.shares)                 AS shares,
            SUM(t.shares * t.price)       AS notional
        FROM trades t
        JOIN traders tr ON tr.address = t.trader_address
        WHERE t.market_id = :market_id
          AND t.timestamp <= datetime('now')
          AND LOWER(t.outcome) IN ('yes', 'no')
          AND tr.geo_elo_active >= :elo
          AND tr.geo_accuracy_pool = 1
          AND tr.research_excluded = 0
          AND tr.bot_type IS NULL
        GROUP BY t.trader_address, LOWER(t.outcome), UPPER(t.side)
    """, {"market_id": market_id, "elo": ELO_LEGENDARY})

    raw: dict[str, dict] = {}
    for r in cur.fetchall():
        agg = raw.setdefault(r["address"], {
            "yes_buy_sh": 0.0, "yes_sell_sh": 0.0,
            "no_buy_sh": 0.0,  "no_sell_sh": 0.0,
            "yes_buy_notional": 0.0, "no_buy_notional": 0.0,
        })
        key = f"{r['outcome']}_{'buy' if r['side'] == 'BUY' else 'sell'}_sh"
        agg[key] += r["shares"] or 0.0
        if r["side"] == "BUY":
            agg[f"{r['outcome']}_buy_notional"] += r["notional"] or 0.0

    positions = {}
    for addr, a in raw.items():
        yes_net = a["yes_buy_sh"] - a["yes_sell_sh"]
        no_net = a["no_buy_sh"] - a["no_sell_sh"]
        # Signed exposure: YES shares positive, NO shares negative
        net_position = yes_net - no_net

        if net_position > 0:
            direction = "YES"
            buy_sh, buy_notional = a["yes_buy_sh"], a["yes_buy_notional"]
        elif net_position < 0:
            direction = "NO"
            buy_sh, buy_notional = a["no_buy_sh"], a["no_buy_notional"]
        else:
            direction = "FLAT"
            buy_sh, buy_notional = 0.0, 0.0

        avg_entry = (buy_notional / buy_sh) if buy_sh > 0 else None
        net_capital = abs(net_position) * avg_entry if avg_entry is not None else 0.0

        positions[addr] = {
            "net_position": round(net_position, 4),
            "net_direction": direction,
            "net_committed": abs(net_position) > NET_COMMIT_THRESHOLD,
            "avg_entry_price": round(avg_entry, 4) if avg_entry is not None else None,
            "net_capital": round(net_capital, 2),
            "side_buy_notional": round(buy_notional, 2),
        }
    return positions


def _trader_avg_notional(conn: sqlite3.Connection, address: str) -> float | None:
    """Trader's average per-market BUY notional across all markets."""
    cur = conn.execute("""
        SELECT AVG(mkt_notional) AS avg_notional
        FROM (
            SELECT SUM(shares * price) AS mkt_notional
            FROM trades
            WHERE trader_address = ?
              AND UPPER(side) = 'BUY'
              AND timestamp <= datetime('now')
            GROUP BY market_id
        )
    """, (address,))
    row = cur.fetchone()
    return row["avg_notional"] if row and row["avg_notional"] else None


# ---------------------------------------------------------------------------
# SCS components
# ---------------------------------------------------------------------------

def _timing_alpha_points(alpha: float) -> int:
    if alpha > 0.20:
        return 20
    if alpha >= 0.10:
        return 10
    if alpha >= 0.0:
        return 5
    return 0


def score_market(conn: sqlite3.Connection, market_id: str,
                 current_price_yes: float | None) -> dict:
    """Compute the full SCS breakdown for one market."""
    positions = compute_net_positions(conn, market_id)
    committed = {a: p for a, p in positions.items() if p["net_committed"]}

    # Component 1 — Net Position Conviction (0..40)
    n_yes = sum(1 for p in committed.values() if p["net_direction"] == "YES")
    n_no = sum(1 for p in committed.values() if p["net_direction"] == "NO")
    n_committed = n_yes + n_no
    if n_committed > 0:
        net_consensus = max(n_yes, n_no) / n_committed
        c1 = 40.0 * net_consensus ** 2
        net_direction = "YES" if n_yes >= n_no else "NO"
    else:
        net_consensus = 0.0
        c1 = 0.0
        net_direction = "NEUTRAL"

    # Component 2 — Two-Sidedness Penalty (-20..0), on net capital
    yes_cap = sum(p["net_capital"] for p in committed.values() if p["net_direction"] == "YES")
    no_cap = sum(p["net_capital"] for p in committed.values() if p["net_direction"] == "NO")
    if max(yes_cap, no_cap) > 0:
        both_sides_ratio = min(yes_cap, no_cap) / max(yes_cap, no_cap)
    else:
        both_sides_ratio = 0.0
    c2 = -20.0 * both_sides_ratio

    # Components 3 & 4 — per net-committed trader, averaged
    timing_pts: list[int] = []
    depth_pts: list[float] = []
    for addr, p in committed.items():
        if current_price_yes is not None and p["avg_entry_price"] is not None:
            side_price = (current_price_yes if p["net_direction"] == "YES"
                          else 1.0 - current_price_yes)
            timing_pts.append(_timing_alpha_points(side_price - p["avg_entry_price"]))

        avg_notional = _trader_avg_notional(conn, addr)
        if avg_notional:
            rel = p["side_buy_notional"] / avg_notional
            depth_pts.append(20.0 * min(max(rel, 0.0), 2.0) / 2.0)

    c3 = sum(timing_pts) / len(timing_pts) if timing_pts else 0.0
    c4 = sum(depth_pts) / len(depth_pts) if depth_pts else 0.0

    scs = max(0.0, min(100.0, c1 + c2 + c3 + c4))
    if scs >= TIER_HIGH:
        tier = "HIGH"
    elif scs >= TIER_MEDIUM:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {
        "signal_credibility_score": round(scs, 1),
        "signal_credibility_tier": tier,
        "components": {
            "net_position_conviction": round(c1, 1),
            "two_sidedness_penalty": round(c2, 1),
            "entry_timing_alpha": round(c3, 1),
            "conviction_depth": round(c4, 1),
        },
        "net_committed_traders": n_committed,
        "net_committed_yes": n_yes,
        "net_committed_no": n_no,
        "net_consensus": round(net_consensus, 3),
        "net_direction": net_direction,
        "net_yes_capital": round(yes_cap, 2),
        "net_no_capital": round(no_cap, 2),
        "traders_total": len(positions),
        "traders_net_flat": len(positions) - n_committed,
    }


# ---------------------------------------------------------------------------
# Scan JSON enrichment
# ---------------------------------------------------------------------------

def enrich_scan_rows(conn: sqlite3.Connection, market_rows: list[dict]) -> None:
    """
    Add signal_credibility_score / signal_credibility_tier (plus the
    component breakdown) to each market row from a positions-scan output.
    Mutates the rows in place. Rows use the scan-time current_price_yes
    so SCS and gap_pt reference the same price snapshot.
    """
    for row in market_rows:
        result = score_market(conn, row["market_id"], row.get("current_price_yes"))
        row["signal_credibility_score"] = result["signal_credibility_score"]
        row["signal_credibility_tier"] = result["signal_credibility_tier"]
        row["signal_credibility_components"] = result["components"]
        row["net_committed_traders"] = result["net_committed_traders"]


def enrich_scan_file(scan_path: Path, conn: sqlite3.Connection | None = None) -> dict:
    """Load a scan JSON, enrich every market entry, write it back."""
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    try:
        with open(scan_path) as fh:
            data = json.load(fh)
        enrich_scan_rows(conn, data.get("markets", []))
        with open(scan_path, "w") as fh:
            json.dump(data, fh, indent=2)
        return data
    finally:
        if own_conn:
            conn.close()


def _latest_scan_file() -> Path | None:
    files = sorted(SCAN_DIR.glob("*-positions-scan.json"))
    return files[-1] if files else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Signal Credibility Score (0-100) for legendary positions scan markets."
    )
    parser.add_argument("--scan-json", type=Path, default=None,
                        help="Positions-scan JSON to enrich (default: latest in brain/agent-outputs/positions-scan/)")
    parser.add_argument("--market-id", type=str, default=None,
                        help="Score a single market instead of a scan file")
    parser.add_argument("--price-yes", type=float, default=None,
                        help="Current YES price (0-1) for --market-id mode")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.market_id:
            result = score_market(conn, args.market_id, args.price_yes)
            print(json.dumps(result, indent=2))
            return

        scan_path = args.scan_json or _latest_scan_file()
        if scan_path is None or not scan_path.exists():
            print(f"[SCS] No scan JSON found ({scan_path or SCAN_DIR})", file=sys.stderr)
            sys.exit(1)

        data = enrich_scan_file(scan_path, conn)
        print(f"[SCS] Enriched {len(data.get('markets', []))} market(s) → {scan_path}\n")
        for row in data.get("markets", []):
            c = row["signal_credibility_components"]
            print(f"  SCS {row['signal_credibility_score']:>5.1f} [{row['signal_credibility_tier']:<6}] "
                  f"net-committed={row['net_committed_traders']}  "
                  f"(conv={c['net_position_conviction']:+.1f} two-side={c['two_sidedness_penalty']:+.1f} "
                  f"timing={c['entry_timing_alpha']:+.1f} depth={c['conviction_depth']:+.1f})")
            print(f"        {row['title'][:70]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
