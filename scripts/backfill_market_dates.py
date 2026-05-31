#!/usr/bin/env python3
"""
Backfill end_date and resolution_date for markets that have NULL values.

Fetches endDate from the Gamma API using api_id (numeric) or title search,
then updates both end_date and resolution_date (using end_date as proxy where
resolution_date is NULL).

Strategy (tried in order per market):
  1. api_id is set → GET /markets/{api_id} (direct, exact match guaranteed)
  2. condition_id or market_id starts with 0x → skip Gamma API conditionId query
     (Gamma API conditionId param does NOT filter; always returns unrelated markets)
     → fall through to title search
  3. Title search: GET /markets?search={title}&limit=5, validate by title similarity ≥ 0.8

Usage:
    python3 backfill_market_dates.py [--limit N] [--dry-run] [--geo-only]

Flags:
    --limit N     Max markets to process per run (default 1000)
    --dry-run     Fetch and print results without writing to DB
    --geo-only    Only process markets that have trades with
                  market_category IN ('Geopolitics','Elections')
"""

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
GAMMA_API = "https://gamma-api.polymarket.com"


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _parse_end_date(raw) -> str | None:
    """Parse endDate from Gamma API response to ISO string."""
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = raw / 1000 if raw > 1e10 else raw
            return datetime.fromtimestamp(ts).isoformat()
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def _fetch_by_api_id(session: requests.Session, api_id: str) -> dict | None:
    """
    Direct Gamma API lookup by numeric market ID (e.g. '21742').
    Guaranteed to return exactly the right market.
    """
    try:
        resp = session.get(f"{GAMMA_API}/markets/{api_id}", timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _fetch_by_title(session: requests.Session, title: str) -> dict | None:
    """
    Search Gamma API by title text. Validates match by title similarity ≥ 0.8.

    Note: The Gamma API conditionId query param does NOT filter by conditionId —
    it always returns the same default set. Title search is the only reliable
    fallback for markets whose numeric api_id is unknown.
    """
    if not title or title == "Unknown Market":
        return None
    try:
        resp = session.get(
            f"{GAMMA_API}/markets",
            params={"search": title[:100], "limit": 20, "closed": "true"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("data", [])
        if not markets:
            return None
        title_lower = title.lower().strip()
        # Exact match first
        for m in markets:
            q = (m.get("question") or m.get("title") or "").lower().strip()
            if q == title_lower:
                return m
        # Highest similarity ≥ 0.8
        best, best_score = None, 0.0
        for m in markets:
            q = (m.get("question") or m.get("title") or "").lower().strip()
            score = SequenceMatcher(None, title_lower, q).ratio()
            if score > best_score:
                best, best_score = m, score
        return best if best_score >= 0.8 else None
    except Exception:
        return None


def get_markets_to_backfill(conn, limit: int, geo_only: bool) -> list:
    """Return list of market dicts needing backfill."""
    if geo_only:
        query = """
            SELECT DISTINCT m.market_id, m.title, m.condition_id, m.api_id
            FROM markets m
            INNER JOIN trades t ON (t.market_id = m.market_id OR t.market_id = m.condition_id)
            WHERE (m.end_date IS NULL OR m.resolution_date IS NULL)
              AND t.market_category IN ('Geopolitics', 'Elections')
            LIMIT ?
        """
    else:
        query = """
            SELECT market_id, title, condition_id, api_id
            FROM markets
            WHERE end_date IS NULL OR resolution_date IS NULL
            LIMIT ?
        """
    rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def backfill(limit: int, dry_run: bool, geo_only: bool):
    conn = _get_connection()
    markets = get_markets_to_backfill(conn, limit, geo_only)

    total = len(markets)
    print(f"[BACKFILL] Markets to process: {total} (limit={limit}, geo_only={geo_only}, dry_run={dry_run})")

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketBackfill/1.0"})

    updated = 0
    not_found = 0
    errors = 0
    skipped_no_api_id = 0

    for i, row in enumerate(markets, 1):
        market_id = row["market_id"]
        title = row["title"] or ""
        condition_id = row["condition_id"]
        api_id = row["api_id"]

        if i % 100 == 0:
            print(
                f"[BACKFILL] Progress: {i}/{total} — "
                f"updated={updated}, not_found={not_found}, "
                f"skipped={skipped_no_api_id}, errors={errors}"
            )

        market_data = None

        # Strategy 1: direct lookup via numeric api_id (guaranteed exact match)
        if api_id:
            market_data = _fetch_by_api_id(session, api_id)

        # Strategy 2: title search (only if we have a usable title)
        # NOTE: we deliberately skip conditionId queries because the Gamma API
        # conditionId param does not filter — it always returns unrelated markets.
        if not market_data and title and title != "Unknown Market":
            market_data = _fetch_by_title(session, title)

        # If neither strategy worked, skip
        if not market_data:
            if not api_id and (not title or title == "Unknown Market"):
                skipped_no_api_id += 1
            else:
                not_found += 1
            time.sleep(0.1)
            continue

        end_date_raw = market_data.get("endDate") or market_data.get("endDateIso") or market_data.get("end_date_iso")
        end_date_str = _parse_end_date(end_date_raw)

        if not end_date_str:
            not_found += 1
            time.sleep(0.1)
            continue

        if dry_run:
            matched_q = (market_data.get("question") or market_data.get("title") or "")[:40]
            print(f"[DRY-RUN] {market_id[:20]}... '{title[:40]}' → end_date={end_date_str} (Gamma: '{matched_q}')")
            updated += 1
        else:
            try:
                conn.execute("""
                    UPDATE markets
                    SET end_date = ?,
                        resolution_date = COALESCE(resolution_date, ?)
                    WHERE market_id = ?
                """, (end_date_str, end_date_str, market_id))
                conn.commit()
                updated += 1
            except Exception as e:
                print(f"[BACKFILL] ERROR updating {market_id}: {e}")
                errors += 1

        time.sleep(0.1)

    conn.close()

    print(
        f"\n[BACKFILL] Done — updated={updated}, not_found={not_found}, "
        f"skipped_no_api_id={skipped_no_api_id}, errors={errors}, total={total}"
    )
    return updated, not_found, errors


def main():
    parser = argparse.ArgumentParser(description="Backfill market end_date and resolution_date")
    parser.add_argument("--limit", type=int, default=1000, help="Max markets to process (default 1000)")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument("--geo-only", action="store_true",
                        help="Only backfill markets with Geopolitics/Elections trades")
    args = parser.parse_args()

    backfill(limit=args.limit, dry_run=args.dry_run, geo_only=args.geo_only)


if __name__ == "__main__":
    main()
