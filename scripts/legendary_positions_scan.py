"""
legendary_positions_scan.py

Intelligence report of ALL open markets where LEGENDARY traders
(geo_elo_active >= 2175, geo_accuracy_pool = 1) have positions.

Extends pre_resolution_intelligence.py to long-horizon markets —
covers the full open book, not just markets resolving within 7 days.

For each qualifying market:
  - legendary_count       : number of LEGENDARY traders with open positions
  - smart_money_direction : YES or NO (whichever side has more LEGENDARY capital)
  - smart_money_pct       : fraction of total LEGENDARY capital on that side (%)
  - yes_capital / no_capital : raw LEGENDARY capital by side ($)
  - days_to_resolution    : days until resolution_date (None if unknown)
  - current_price         : live YES probability from Gamma API (0–1)
  - gap_pt                : smart_money_pct minus market-price-for-that-side (pp)

Usage:
  python scripts/legendary_positions_scan.py
  python scripts/legendary_positions_scan.py --min-traders 3 --min-gap 10
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH   = os.path.join(_REPO_ROOT, 'data', 'polymarket_tracker.db')

OUTPUT_DIR = Path("/home/parison/trading-swarm/brain/agent-outputs/positions-scan")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEO_CATEGORIES = ('Geopolitics', 'Elections', 'Global Politics')
ELO_LEGENDARY  = 2175
GAMMA_API_BASE = "https://gamma-api.polymarket.com/markets"
API_DELAY      = 0.1   # seconds between Gamma requests

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fetch_legendary_markets(conn: sqlite3.Connection, min_traders: int) -> list[dict]:
    """
    Return open geo/elections markets with >= min_traders LEGENDARY traders
    holding open positions on binary YES/NO outcomes.
    """
    placeholders = ",".join(f"'{c}'" for c in GEO_CATEGORIES)
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            m.market_id,
            m.title,
            m.category,
            m.end_date,
            m.resolution_date,
            m.api_id,
            COUNT(DISTINCT t.address) AS legendary_count,
            SUM(CASE WHEN LOWER(p.outcome) = 'yes' THEN p.entry_total_cost ELSE 0 END) AS yes_capital,
            SUM(CASE WHEN LOWER(p.outcome) = 'no'  THEN p.entry_total_cost ELSE 0 END) AS no_capital
        FROM markets m
        JOIN positions p ON p.market_id = m.market_id
        JOIN traders   t ON t.address   = p.trader_address
        WHERE m.resolved = 0
          AND m.category IN ({placeholders})
          AND t.geo_elo_active >= :elo
          AND t.geo_accuracy_pool = 1
          AND p.status = 'open'
          AND LOWER(p.outcome) IN ('yes', 'no')
        GROUP BY m.market_id
        HAVING legendary_count >= :min_traders
        ORDER BY legendary_count DESC, (yes_capital + no_capital) DESC
    """, {"elo": ELO_LEGENDARY, "min_traders": min_traders})
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Gamma API helpers
# ---------------------------------------------------------------------------

def _gamma_request(url: str) -> dict | list | None:
    try:
        req = Request(url, headers={"User-Agent": "polymarket-research/1.0"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (URLError, ValueError, OSError):
        return None


def _fetch_gamma_price(market_row: dict) -> float | None:
    """
    Fetch the YES price (0–1) from the Gamma API.

    Tries api_id (numeric) first; falls back to conditionIds query.
    Returns None on failure.
    """
    api_id = market_row.get("api_id")
    market_id = market_row["market_id"]

    data = None
    if api_id:
        data = _gamma_request(f"{GAMMA_API_BASE}/{api_id}")
        if isinstance(data, dict) and "error" in data:
            data = None

    if data is None:
        result = _gamma_request(f"{GAMMA_API_BASE}?conditionIds={market_id}")
        if isinstance(result, list) and result:
            data = result[0]

    if not isinstance(data, dict):
        return None

    outcome_prices = data.get("outcomePrices")
    if not outcome_prices:
        return None
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except (ValueError, TypeError):
            return None
    if isinstance(outcome_prices, list) and outcome_prices:
        try:
            return float(outcome_prices[0])
        except (ValueError, TypeError):
            return None
    return None


def _fetch_gamma_full(market_row: dict) -> dict | None:
    """Return full Gamma market dict for resolution checks."""
    api_id = market_row.get("api_id")
    market_id = market_row["market_id"]

    if api_id:
        data = _gamma_request(f"{GAMMA_API_BASE}/{api_id}")
        if isinstance(data, dict) and "error" not in data:
            return data

    result = _gamma_request(f"{GAMMA_API_BASE}?conditionIds={market_id}")
    if isinstance(result, list) and result:
        return result[0]
    return None


# ---------------------------------------------------------------------------
# Compute per-market signal
# ---------------------------------------------------------------------------

def _days_to_resolution(end_date: str | None, resolution_date: str | None) -> float | None:
    date_str = resolution_date or end_date
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((dt - datetime.now(timezone.utc)).total_seconds() / 86400, 1)
    except ValueError:
        return None


def _compute_market_signal(row: dict, current_price: float | None) -> dict:
    yes_capital = row["yes_capital"] or 0.0
    no_capital  = row["no_capital"]  or 0.0
    total       = yes_capital + no_capital

    if total == 0:
        smart_money_pct   = 50.0
        direction         = "NEUTRAL"
        gap_pt            = None
    else:
        yes_pct = yes_capital / total * 100.0
        no_pct  = no_capital  / total * 100.0
        if yes_capital >= no_capital:
            direction       = "YES"
            smart_money_pct = yes_pct
            market_side_pct = (current_price * 100.0) if current_price is not None else None
        else:
            direction       = "NO"
            smart_money_pct = no_pct
            market_side_pct = ((1.0 - current_price) * 100.0) if current_price is not None else None

        gap_pt = round(smart_money_pct - market_side_pct, 1) if market_side_pct is not None else None

    return {
        "smart_money_direction": direction,
        "smart_money_pct":       round(smart_money_pct, 1),
        "yes_capital":           round(yes_capital, 2),
        "no_capital":            round(no_capital, 2),
        "total_capital":         round(total, 2),
        "current_price":         round(current_price, 4) if current_price is not None else None,
        "gap_pt":                gap_pt,
        "days_to_resolution":    _days_to_resolution(row["end_date"], row["resolution_date"]),
        "legendary_count":       row["legendary_count"],
    }


# ---------------------------------------------------------------------------
# Ukraine war market resolution update
# ---------------------------------------------------------------------------

def _resolve_one_market(conn: sqlite3.Connection, row: dict) -> bool:
    """
    Check Gamma for a single market and update DB if resolved.
    Returns True if the market was updated.
    """
    cur = conn.cursor()
    data = _fetch_gamma_full(row)
    time.sleep(API_DELAY)
    if data is None:
        print(f"    → Gamma fetch failed, skipping")
        return False

    closed     = data.get("closed", False)
    uma_status = data.get("umaResolutionStatus", "")

    if not (closed or uma_status == "resolved"):
        print(f"    → Not yet resolved on Gamma")
        return False

    outcome_prices = data.get("outcomePrices")
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except (ValueError, TypeError):
            outcome_prices = None

    winning = None
    if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
        try:
            yes_p = float(outcome_prices[0])
            no_p  = float(outcome_prices[1])
            if yes_p >= 0.99:
                winning = "Yes"
            elif no_p >= 0.99:
                winning = "No"
        except (ValueError, TypeError):
            pass

    if winning is None:
        winner_idx   = data.get("winnerIndex")
        outcomes_raw = data.get("outcomes")
        if isinstance(outcomes_raw, str):
            try:
                outcomes_raw = json.loads(outcomes_raw)
            except (ValueError, TypeError):
                outcomes_raw = None
        if winner_idx is not None and isinstance(outcomes_raw, list):
            try:
                winning = outcomes_raw[int(winner_idx)]
            except (IndexError, ValueError, TypeError):
                pass

    if winning:
        cur.execute(
            "UPDATE markets SET resolved = 1, winning_outcome = ? WHERE market_id = ?",
            (winning, row["market_id"])
        )
        conn.commit()
        print(f"    → UPDATED: resolved=1, winning_outcome={winning}")
        return True
    else:
        total_price = sum(float(p) for p in (outcome_prices or []) if p)
        if total_price == 0.0 and closed:
            cur.execute(
                "UPDATE markets SET resolved = 1 WHERE market_id = ?",
                (row["market_id"],)
            )
            conn.commit()
            print(f"    → UPDATED: resolved=1, winning_outcome=NULL (v1/multi-outcome market)")
            return True
        else:
            print(f"    → Resolved on Gamma but outcome unclear (outcomePrices={outcome_prices})")
            return False


def _check_and_update_stale_markets(conn: sqlite3.Connection) -> None:
    """
    Find open geo/elections markets whose end_date has passed and check Gamma
    for resolution.

    Two passes:
      1. Targeted: any market matching the Ukraine-war 90-day title pattern
         (user-reported stale; end_date 2025-04-20 is deep in a recency-sorted list).
      2. General: 30 most recently-overdue geo/elections markets, DESC.
    """
    cur = conn.cursor()

    # Pass 1 — targeted Ukraine war market check
    cur.execute("""
        SELECT market_id, title, end_date, api_id
        FROM markets
        WHERE resolved = 0
          AND title LIKE '%Ukraine%war%90%'
    """)
    ukraine_rows = [dict(r) for r in cur.fetchall()]
    for row in ukraine_rows:
        print(f"  [TARGETED] Checking: {row['title'][:70]}")
        _resolve_one_market(conn, row)

    # Pass 2 — general sweep of recent overdue geo/elections markets
    placeholders = ",".join(f"'{c}'" for c in GEO_CATEGORIES)
    cur.execute(f"""
        SELECT market_id, title, end_date, api_id
        FROM markets
        WHERE resolved = 0
          AND end_date < datetime('now', '-1 day')
          AND category IN ({placeholders})
        ORDER BY end_date DESC
        LIMIT 30
    """)
    stale = [dict(r) for r in cur.fetchall()]

    if not stale:
        print("[STALE] No overdue open markets found.")
        return

    print(f"[STALE] {len(stale)} overdue open market(s) — checking Gamma API...")
    for row in stale:
        print(f"  Checking: {row['title'][:70]} (end {row['end_date'][:10]})")
        _resolve_one_market(conn, row)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_row(rank: int, row: dict, sig: dict) -> str:
    title = row["title"][:68]
    days  = sig["days_to_resolution"]
    days_str = f"{days:.0f}d" if days is not None else "?"

    price_str = f"{sig['current_price'] * 100:.1f}%" if sig["current_price"] is not None else "n/a"
    gap_str   = f"{sig['gap_pt']:+.1f}pt" if sig["gap_pt"] is not None else "n/a"
    dir_arrow = "YES ▲" if sig["smart_money_direction"] == "YES" else "NO  ▼"

    cap_total = sig["total_capital"]
    if cap_total >= 1_000_000:
        cap_str = f"${cap_total/1_000_000:.2f}M"
    elif cap_total >= 1_000:
        cap_str = f"${cap_total/1_000:.1f}K"
    else:
        cap_str = f"${cap_total:.0f}"

    return (
        f"  {rank:>3}. [{row['legendary_count']:>2} LEG] {dir_arrow}  "
        f"{sig['smart_money_pct']:.0f}% vs mkt {price_str}  gap={gap_str}  "
        f"cap={cap_str}  res={days_str}\n"
        f"       {title}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_legendary_scan(min_traders: int = 2, min_gap: float = 0.0) -> dict:
    print("[LEGEND] Starting legendary positions scan...")
    conn = _get_conn()

    # Step 0: fix any stale overdue markets (including Ukraine war)
    _check_and_update_stale_markets(conn)

    markets = _fetch_legendary_markets(conn, min_traders)
    print(f"[LEGEND] {len(markets)} market(s) with >= {min_traders} LEGENDARY traders")

    results = []
    for i, row in enumerate(markets, 1):
        price = _fetch_gamma_price(row)
        time.sleep(API_DELAY)
        sig = _compute_market_signal(row, price)

        # Apply min_gap filter (skip if gap unknown or below threshold)
        if min_gap > 0:
            if sig["gap_pt"] is None or sig["gap_pt"] < min_gap:
                continue

        results.append({"market": row, "signal": sig})

        if i % 50 == 0:
            print(f"[LEGEND]   ... {i}/{len(markets)} processed")

    conn.close()

    # Sort: legendary_count DESC, then gap_pt DESC (None last)
    results.sort(
        key=lambda x: (
            -x["signal"]["legendary_count"],
            -(x["signal"]["gap_pt"] if x["signal"]["gap_pt"] is not None else -999),
        )
    )

    scan_ts = datetime.now(timezone.utc)

    # Print summary
    print(f"\n{'='*70}")
    print(f"  LEGENDARY POSITIONS SCAN — {scan_ts.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Filters: min_traders={min_traders}, min_gap={min_gap}pt")
    print(f"  Markets shown: {len(results)}")
    print(f"{'='*70}")
    for rank, r in enumerate(results, 1):
        print(_format_row(rank, r["market"], r["signal"]))
        print()
    if not results:
        print("  No markets meet the filter criteria.")
    print(f"{'='*70}\n")

    # Build JSON output
    output_rows = []
    for r in results:
        row = r["market"]
        sig = r["signal"]
        output_rows.append({
            "rank":                   len(output_rows) + 1,
            "market_id":              row["market_id"],
            "title":                  row["title"],
            "category":               row["category"],
            "legendary_count":        sig["legendary_count"],
            "smart_money_direction":  sig["smart_money_direction"],
            "smart_money_pct":        sig["smart_money_pct"],
            "yes_capital":            sig["yes_capital"],
            "no_capital":             sig["no_capital"],
            "total_capital":          sig["total_capital"],
            "current_price_yes":      sig["current_price"],
            "gap_pt":                 sig["gap_pt"],
            "days_to_resolution":     sig["days_to_resolution"],
            "resolution_date":        (row["resolution_date"] or row["end_date"] or "")[:10],
        })

    output_data = {
        "scan_date":       scan_ts.strftime("%Y-%m-%d"),
        "scan_timestamp":  scan_ts.isoformat(),
        "filters": {
            "min_traders": min_traders,
            "min_gap_pt":  min_gap,
        },
        "markets_scanned": len(markets),
        "markets_in_report": len(results),
        "markets": output_rows,
    }

    out_file = OUTPUT_DIR / f"{scan_ts.strftime('%Y-%m-%d')}-positions-scan.json"
    with open(out_file, "w") as fh:
        json.dump(output_data, fh, indent=2)
    print(f"[LEGEND] Output → {out_file}")

    return {
        "markets_scanned":    len(markets),
        "markets_in_report":  len(results),
        "output_file":        str(out_file),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Legendary positions scan — all open geo/elections markets "
            "where LEGENDARY traders (geo_elo_active >= 2175) hold positions."
        )
    )
    parser.add_argument(
        "--min-traders", type=int, default=2, metavar="N",
        help="Minimum number of LEGENDARY traders required (default: 2)"
    )
    parser.add_argument(
        "--min-gap", type=float, default=0.0, metavar="PP",
        help="Minimum gap in percentage points between smart money and market price (default: 0)"
    )
    args = parser.parse_args()

    result = run_legendary_scan(min_traders=args.min_traders, min_gap=args.min_gap)
    print(
        f"[LEGEND] Done — {result['markets_scanned']} scanned, "
        f"{result['markets_in_report']} in report → {result['output_file']}"
    )


if __name__ == "__main__":
    main()
