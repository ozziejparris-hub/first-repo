"""
resolve_legendary_markets.py

CANONICAL DEFINITIONS: See brain/integration-contract.md Section 10.
LEGENDARY: geo_elo_active >= 2175 AND geo_accuracy_pool = 1 (NOT comprehensive_elo).
Pool filter: research_excluded = 0 AND bot_type IS NULL.

Targeted resolution pass for markets where LEGENDARY traders
(geo_elo_active >= 2175, geo_accuracy_pool = 1) have positions
that are overdue but not yet resolved in our DB.

Queries the Gamma API individually for each market — more targeted
than fast_resolution_check.py's bulk scan which caps at 50K recent
markets and may miss older or lower-volume LEGENDARY markets.

Usage:
    python scripts/resolve_legendary_markets.py
    python scripts/resolve_legendary_markets.py --limit 50
    python scripts/resolve_legendary_markets.py --dry-run
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH   = os.path.join(_REPO_ROOT, 'data', 'polymarket_tracker.db')

sys.path.insert(0, _REPO_ROOT)
from monitoring import column_definitions as cd

GAMMA_API_BASE = "https://gamma-api.polymarket.com/markets"
API_DELAY      = 0.2   # seconds between Gamma requests


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _fetch_overdue_legendary_markets(conn: sqlite3.Connection, limit: int) -> list[dict]:
    """Return markets overdue by >3 days where LEGENDARY traders have trades."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT m.market_id, m.title, m.api_id, m.condition_id, m.resolution_date
        FROM markets m
        WHERE m.resolved = 0
          AND m.resolution_date IS NOT NULL
          AND m.resolution_date < datetime('now', '-3 days')
          AND m.market_id IN (
              SELECT DISTINCT t.market_id
              FROM trades t
              WHERE t.trader_address IN (
                  SELECT address
                  FROM traders
                  WHERE {cd.LEGENDARY_GATE_WHERE}
              )
          )
        ORDER BY m.resolution_date DESC
        LIMIT ?
    """, (limit,))
    return [dict(r) for r in cur.fetchall()]


def _gamma_request(url: str) -> dict | list | None:
    try:
        req = Request(url, headers={"User-Agent": "polymarket-research/1.0"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (URLError, ValueError, OSError):
        return None


def _fetch_gamma_market(row: dict) -> dict | None:
    """Fetch Gamma market data, trying api_id then conditionIds fallback."""
    api_id       = row.get("api_id")
    market_id    = row["market_id"]
    condition_id = row.get("condition_id")

    if api_id:
        data = _gamma_request(f"{GAMMA_API_BASE}/{api_id}")
        if isinstance(data, dict) and "error" not in data:
            return data

    lookup_id = condition_id or market_id
    result = _gamma_request(f"{GAMMA_API_BASE}?conditionIds={lookup_id}")
    if isinstance(result, list) and result:
        return result[0]
    return None


def _extract_winning_outcome(data: dict) -> str | None:
    """
    Extract winning outcome from Gamma market data.

    Returns:
      - outcome name string if resolved with a clear winner
      - "__RESOLVED_NO_WINNER__" for v1/multi-outcome markets (closed, all prices zero)
      - None if the market is not yet resolved or outcome is unclear
    """
    closed     = data.get("closed", False)
    uma_status = data.get("umaResolutionStatus", "")

    if not (closed or uma_status == "resolved"):
        return None

    outcome_prices = data.get("outcomePrices")
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except (ValueError, TypeError):
            outcome_prices = None

    outcomes_raw = data.get("outcomes")
    if isinstance(outcomes_raw, str):
        try:
            outcomes_raw = json.loads(outcomes_raw)
        except (ValueError, TypeError):
            outcomes_raw = None

    # Primary: find outcome with price >= 0.99
    if isinstance(outcome_prices, list) and isinstance(outcomes_raw, list):
        for idx, price in enumerate(outcome_prices):
            try:
                if float(price) >= 0.99 and idx < len(outcomes_raw):
                    return outcomes_raw[idx]
            except (ValueError, TypeError):
                continue

    # Fallback: winnerIndex field
    winner_idx = data.get("winnerIndex")
    if winner_idx is not None and isinstance(outcomes_raw, list):
        try:
            return outcomes_raw[int(winner_idx)]
        except (IndexError, ValueError, TypeError):
            pass

    # V1 / multi-outcome: closed but all prices are zero → mark resolved, no winner stored
    if closed:
        total_price = sum(float(p) for p in (outcome_prices or []) if p)
        if total_price == 0.0:
            return "__RESOLVED_NO_WINNER__"

    return None


def resolve_legendary_markets(limit: int = 100, dry_run: bool = False) -> dict:
    """
    Targeted resolution pass for overdue LEGENDARY trader markets.

    Returns summary dict: markets_checked, markets_resolved, markets_updated.
    """
    conn = _get_conn()
    markets = _fetch_overdue_legendary_markets(conn, limit)
    total   = len(markets)

    print(f"\n{'='*70}")
    print("LEGENDARY MARKET RESOLUTION PASS")
    print(f"{'='*70}")
    if dry_run:
        print("[DRY-RUN] No database changes will be made.")
    print(f"Overdue LEGENDARY markets to check: {total}\n")

    if not total:
        print("No overdue LEGENDARY markets found.")
        conn.close()
        return {"markets_checked": 0, "markets_resolved": 0, "markets_updated": 0}

    resolved_count = 0
    updated_count  = 0
    not_ready      = 0
    api_errors     = 0

    cur = conn.cursor()

    for idx, row in enumerate(markets, 1):
        time.sleep(API_DELAY)

        title_short = (row.get("title") or row["market_id"])[:60]
        res_date    = (row.get("resolution_date") or "")[:10]

        data = _fetch_gamma_market(row)

        if data is None:
            api_errors += 1
            if api_errors <= 5:
                print(f"  [{idx}/{total}] API error — {title_short}")
            continue

        winning = _extract_winning_outcome(data)

        if winning is None:
            not_ready += 1
            continue

        resolved_count += 1

        if not dry_run:
            if winning == "__RESOLVED_NO_WINNER__":
                cur.execute(
                    "UPDATE markets SET resolved = 1, last_checked = ? WHERE market_id = ?",
                    (datetime.now(), row["market_id"])
                )
            else:
                cur.execute(
                    "UPDATE markets SET resolved = 1, winning_outcome = ?, last_checked = ? WHERE market_id = ?",
                    (winning, datetime.now(), row["market_id"])
                )
            conn.commit()
            updated_count += 1

        outcome_label = "resolved (no winner)" if winning == "__RESOLVED_NO_WINNER__" else winning
        if resolved_count <= 10 or idx == total:
            print(f"  [{idx}/{total}] RESOLVED → {outcome_label[:30]}  ({res_date})  {title_short}")

        if idx % 25 == 0 and idx < total:
            print(f"  ... {idx}/{total} checked, {resolved_count} resolved so far")

    conn.close()

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"  Markets checked:  {total}")
    print(f"  Resolved on API:  {resolved_count}")
    if dry_run:
        print(f"  Would update DB:  {resolved_count}  [DRY-RUN — no changes made]")
    else:
        print(f"  DB updated:       {updated_count}")
    print(f"  Not yet resolved: {not_ready}")
    print(f"  API errors:       {api_errors}")

    if not dry_run and updated_count > 0:
        print(f"\n  Next step: python scripts/evaluate_new_trader_results.py")
        print(f"  (scores trades against newly resolved markets)")
    print(f"{'='*70}\n")

    return {
        "markets_checked": total,
        "markets_resolved": resolved_count,
        "markets_updated": updated_count,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Targeted resolution pass for overdue LEGENDARY trader markets"
    )
    parser.add_argument(
        "--limit", type=int, default=100, metavar="N",
        help="Maximum markets to check (default: 100)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Check Gamma API but do not update the database"
    )
    args = parser.parse_args()

    resolve_legendary_markets(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
