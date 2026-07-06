#!/usr/bin/env python3
"""
O-16 Tier-2 backfill.

Resolves markets stuck resolved=0 / resolution_date NULL from the
2025-12-11 historical_backfill import event -- the remainder of the
O-16 population NOT covered by Tier-1's flagged-trader filter (former
design doc's Tier 2 + Tier 3 combined: markets touched by non-flagged
traders, and markets with no known local trades at all).

Design: ~/trading-swarm/brain/decisions/2026-07-01-o16-resolution-collection-gap-quantified.md §7
Tier-1 precedent: scripts/backfill_o16_tier1.py (ran clean 2026-07-02:
62,350 total, 62,188 resolved, 162 skipped_open, 0 errors).

Identical crash-safety properties to Tier-1 (see that script's docstring
for the full rationale) -- self-shrinking idempotent query, small-batch
commits, hard-timeout Gamma calls, plain UPDATE only, direct-by-api_id
lookup only (no broken list-pagination fallback).

Only difference from Tier-1: the query drops Tier-1's
`EXISTS (... tr.is_flagged = 1 ...)` clause, since this tier targets
everything else. Uses a tier/date-specific data_source tag
(gamma_backfill_tier2_2026-07-06) rather than reusing Tier-1's tag, so
provenance stays distinguishable between the two runs.

Usage:
    python3 scripts/backfill_o16_tier2.py --dry-run --limit 50
    python3 scripts/backfill_o16_tier2.py --limit 5000
    python3 scripts/backfill_o16_tier2.py                     # full Tier-2 run
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_SOURCE_TAG = "gamma_backfill_tier2_2026-07-06"
REQUEST_TIMEOUT = (5, 10)  # (connect, read) seconds -- hard cap, no indefinite hang
BATCH_COMMIT_SIZE = 25
LOG_EVERY = 100
REQUEST_DELAY = 0.1  # seconds between Gamma requests

TIER2_QUERY = """
    SELECT DISTINCT m.market_id, m.title, m.condition_id, m.api_id, m.end_date
    FROM markets m
    WHERE m.data_source = 'historical_backfill'
      AND (m.resolved = 0 OR m.resolved IS NULL)
      AND m.resolution_date IS NULL
      AND m.end_date IS NOT NULL AND m.end_date < datetime('now', '-7 days')
      AND m.api_id IS NOT NULL AND m.api_id != ''
    ORDER BY m.market_id
    LIMIT ?
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def get_tier2_targets(conn: sqlite3.Connection, limit: int) -> list[dict]:
    rows = conn.execute(TIER2_QUERY, (limit,)).fetchall()
    return [dict(r) for r in rows]


def fetch_gamma_market(session: requests.Session, api_id: str) -> tuple[dict | None, bool]:
    """Direct-by-api_id lookup only (see module docstring for why no fallback).
    Returns (data_or_None, network_error_flag)."""
    try:
        resp = session.get(f"{GAMMA_API}/markets/{api_id}", timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None, True

    if resp.status_code != 200:
        return None, False

    try:
        data = resp.json()
    except ValueError:
        return None, False

    if isinstance(data, dict) and data:
        return data, False
    return None, False


def parse_timestamp(raw) -> str | None:
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = raw / 1000 if raw > 1e10 else raw
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return None


def extract_resolution(data: dict, local_end_date: str) -> tuple[bool, str | None, str | None]:
    """Returns (is_resolved, winning_outcome_or_sentinel, resolution_date).

    Mirrors resolve_legendary_markets.py's proven extraction logic (price>=0.99
    winner, winnerIndex fallback, __RESOLVED_NO_WINNER__ for closed v1/multi
    markets with all-zero prices). Only ever returns is_resolved=True when
    Gamma explicitly confirms closed/resolved -- never guesses.
    """
    closed = data.get("closed", False)
    uma_status = data.get("umaResolutionStatus", "")

    if not (closed or uma_status == "resolved"):
        return False, None, None

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

    winner = None
    if isinstance(outcome_prices, list) and isinstance(outcomes_raw, list):
        for idx, price in enumerate(outcome_prices):
            try:
                if float(price) >= 0.99 and idx < len(outcomes_raw):
                    winner = outcomes_raw[idx]
                    break
            except (ValueError, TypeError):
                continue

    if winner is None:
        winner_idx = data.get("winnerIndex")
        if winner_idx is not None and isinstance(outcomes_raw, list):
            try:
                winner = outcomes_raw[int(winner_idx)]
            except (IndexError, ValueError, TypeError):
                pass

    res_date = (
        parse_timestamp(data.get("closedTime"))
        or parse_timestamp(data.get("umaEndDate"))
        or parse_timestamp(data.get("endDate"))
        or local_end_date
    )

    if winner is not None:
        return True, winner, res_date

    if closed:
        total_price = sum(float(p) for p in (outcome_prices or []) if p not in (None, ""))
        if total_price == 0.0:
            return True, "__RESOLVED_NO_WINNER__", res_date

    return False, None, None


def run(limit: int, dry_run: bool) -> dict:
    conn = get_connection()
    targets = get_tier2_targets(conn, limit)
    total = len(targets)

    print(f"[O16-T2] Tier-2 targets this run: {total} (limit={limit}, dry_run={dry_run})")
    if not total:
        print("[O16-T2] Nothing to do.")
        conn.close()
        return {"total": 0}

    session = requests.Session()
    session.headers.update({"User-Agent": "O16-Tier2-Backfill/1.0"})

    resolved = skipped_open = skipped_no_data = errors = since_commit = 0

    for i, row in enumerate(targets, 1):
        market_id = row["market_id"]
        api_id = row["api_id"]

        data, net_error = fetch_gamma_market(session, api_id)

        if data is None:
            if net_error:
                errors += 1
            else:
                skipped_no_data += 1
        else:
            is_resolved, winner, res_date = extract_resolution(data, row["end_date"])
            if not is_resolved:
                skipped_open += 1
            else:
                resolved += 1
                label = "no-winner" if winner == "__RESOLVED_NO_WINNER__" else winner
                if resolved <= 10 or dry_run:
                    tag = "[DRY-RUN]" if dry_run else "[LIVE]"
                    print(f"  {tag} {market_id[:24]}...  -> resolved, winner={label}, resolution_date={res_date}")

                if not dry_run:
                    if winner == "__RESOLVED_NO_WINNER__":
                        conn.execute(
                            """UPDATE markets
                               SET resolved = 1,
                                   resolution_date = COALESCE(resolution_date, ?),
                                   data_source = ?,
                                   last_checked = ?
                               WHERE market_id = ?""",
                            (res_date, DATA_SOURCE_TAG, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), market_id),
                        )
                    else:
                        conn.execute(
                            """UPDATE markets
                               SET resolved = 1,
                                   winning_outcome = ?,
                                   resolution_date = COALESCE(resolution_date, ?),
                                   data_source = ?,
                                   last_checked = ?
                               WHERE market_id = ?""",
                            (winner, res_date, DATA_SOURCE_TAG, datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'), market_id),
                        )
                    since_commit += 1
                    if since_commit >= BATCH_COMMIT_SIZE:
                        conn.commit()
                        since_commit = 0

        if i % LOG_EVERY == 0 or i == total:
            print(
                f"[O16-T2] Progress: {i}/{total} done | remaining={total - i} | "
                f"resolved={resolved} skipped_open={skipped_open} "
                f"no_data={skipped_no_data} errors={errors}"
            )

        time.sleep(REQUEST_DELAY)

    if not dry_run and since_commit:
        conn.commit()

    conn.close()

    summary = {
        "total": total,
        "resolved": resolved,
        "skipped_open": skipped_open,
        "skipped_no_data": skipped_no_data,
        "errors": errors,
    }

    print(f"\n[O16-T2] DONE — {summary}")
    if dry_run:
        print("[O16-T2] DRY-RUN — no database changes were made.")
    return summary


def main():
    ap = argparse.ArgumentParser(description="O-16 Tier-2 backfill (remaining historical_backfill markets)")
    ap.add_argument("--limit", type=int, default=140000, help="Max markets to process this run (default 140000, covers full Tier-2 population)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + log only, no DB writes")
    args = ap.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
