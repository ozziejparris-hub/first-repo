#!/usr/bin/env python3
"""
Hydrate stub market records for external_seed traders.

Markets inserted as stubs during trade import have market_id but no metadata
(resolution_date, resolved, winning_outcome, category, title). This script
fetches that metadata from the Gamma API and fills in the gaps.

Targets: markets where resolution_date IS NULL AND market_id appears in trades
by external_seed traders.

Usage:
    python scripts/hydrate_stub_markets.py [--limit N] [--dry-run]

Flags:
    --limit N    Max markets to process per run (default 500)
    --dry-run    Fetch and print results without writing to DB
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
GAMMA_API = "https://gamma-api.polymarket.com"


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _parse_date(raw) -> str | None:
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = raw / 1000 if raw > 1e10 else raw
            return datetime.fromtimestamp(ts).isoformat()
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).isoformat()
    except Exception:
        return None


def _extract_winner(market_data: dict) -> str | None:
    try:
        outcomes_raw = market_data.get("outcomes", "[]")
        prices_raw = market_data.get("outcomePrices", "[]")
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        for idx, price in enumerate(prices):
            if float(price) >= 0.99:
                return outcomes[idx]
    except Exception:
        pass
    return None


def _fetch_market(session: requests.Session, market_id: str, api_id: str | None) -> dict | None:
    """Try Gamma API: direct api_id lookup first, then ?id= query param."""
    if api_id:
        try:
            resp = session.get(f"{GAMMA_API}/markets/{api_id}", timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass

    try:
        resp = session.get(f"{GAMMA_API}/markets", params={"id": market_id}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            markets = data if isinstance(data, list) else data.get("data", [])
            if markets:
                return markets[0]
    except Exception:
        pass

    return None


def get_stub_markets(conn, limit: int) -> list:
    query = """
        SELECT DISTINCT m.market_id, m.title, m.api_id, m.category
        FROM markets m
        WHERE m.resolution_date IS NULL
          AND m.market_id IN (
              SELECT DISTINCT t.market_id
              FROM trades t
              JOIN traders tr ON tr.address = t.trader_address
              WHERE tr.discovery_source = 'external_seed'
          )
        LIMIT ?
    """
    rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def hydrate(limit: int, dry_run: bool):
    conn = _get_connection()
    markets = get_stub_markets(conn, limit)

    total = len(markets)
    print(f"[HYDRATE] Stub markets to process: {total} (limit={limit}, dry_run={dry_run})")

    if not total:
        print("[HYDRATE] Nothing to do.")
        conn.close()
        return 0, 0, 0

    session = requests.Session()
    session.headers.update({"User-Agent": "PolymarketHydrate/1.0"})

    updated = 0
    not_found = 0
    errors = 0
    batch_size = 50

    for i, row in enumerate(markets, 1):
        market_id = row["market_id"]
        title = row["title"] or ""
        api_id = row["api_id"]

        # 1-second pause between batches of 50 to respect rate limits
        if i > 1 and (i - 1) % batch_size == 0:
            print(f"[HYDRATE] Batch complete ({i - 1}/{total}) — sleeping 1s...")
            time.sleep(1)

        if i % 50 == 0 or i == total:
            print(
                f"[HYDRATE] Progress: {i}/{total} — "
                f"updated={updated}, not_found={not_found}, errors={errors}"
            )

        market_data = _fetch_market(session, market_id, api_id)

        if not market_data:
            not_found += 1
            time.sleep(0.1)
            continue

        end_date_raw = (
            market_data.get("endDate")
            or market_data.get("endDateIso")
            or market_data.get("end_date_iso")
            or market_data.get("resolutionTime")
        )
        resolution_date = _parse_date(end_date_raw)

        if not resolution_date:
            not_found += 1
            time.sleep(0.1)
            continue

        prices_raw = market_data.get("outcomePrices", "[]")
        try:
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            is_resolved = int(any(float(p) >= 0.99 for p in prices if p))
        except Exception:
            is_resolved = 0

        winning_outcome = _extract_winner(market_data) if is_resolved else None

        api_title = market_data.get("question") or market_data.get("title") or ""
        api_category = market_data.get("category") or ""

        new_title = api_title if api_title and title in ("", "Unknown Market") else None
        new_category = (
            api_category
            if api_category and api_category.lower() not in ("", "unknown")
            else None
        )

        if dry_run:
            print(
                f"[DRY-RUN] {market_id[:26]}... "
                f"resolution_date={resolution_date}, resolved={is_resolved}, "
                f"winner={winning_outcome}, category={new_category}, "
                f"title_update={bool(new_title)}"
            )
            updated += 1
        else:
            try:
                conn.execute(
                    """
                    UPDATE markets
                    SET resolution_date = COALESCE(resolution_date, ?),
                        end_date        = COALESCE(end_date, ?),
                        resolved        = CASE WHEN (resolved IS NULL OR resolved = 0)
                                               THEN ? ELSE resolved END,
                        winning_outcome = CASE WHEN winning_outcome IS NULL AND ? IS NOT NULL
                                               THEN ? ELSE winning_outcome END,
                        category        = CASE WHEN (category IS NULL OR category IN ('', 'Unknown'))
                                                    AND ? IS NOT NULL
                                               THEN ? ELSE category END,
                        title           = CASE WHEN (title IS NULL OR title IN ('', 'Unknown Market'))
                                                    AND ? IS NOT NULL
                                               THEN ? ELSE title END
                    WHERE market_id = ?
                    """,
                    (
                        resolution_date, resolution_date,
                        is_resolved,
                        winning_outcome, winning_outcome,
                        new_category, new_category,
                        new_title, new_title,
                        market_id,
                    ),
                )
                conn.commit()
                updated += 1
            except Exception as e:
                print(f"[HYDRATE] ERROR updating {market_id}: {e}")
                errors += 1

        time.sleep(0.1)

    conn.close()
    print(
        f"\n[HYDRATE] Done — updated={updated}, not_found={not_found}, "
        f"errors={errors}, total={total}"
    )
    return updated, not_found, errors


def main():
    parser = argparse.ArgumentParser(
        description="Hydrate stub market records for external_seed traders"
    )
    parser.add_argument("--limit", type=int, default=500,
                        help="Max markets to process per run (default 500)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing to DB")
    args = parser.parse_args()
    hydrate(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
