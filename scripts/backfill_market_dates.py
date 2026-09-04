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
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitoring.resolution_writer import mark_market_resolved

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


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


def _fetch_by_clob(session: requests.Session, condition_id: str) -> dict | None:
    """
    Strategy 0: CLOB API direct lookup by conditionId.
    GET https://clob.polymarket.com/markets/{condition_id}

    Returns the parsed response dict whenever the HTTP call itself
    succeeds (status 200, valid JSON) -- None only on a genuine fetch
    failure (bad status, malformed JSON, network error, no condition_id
    to query). Does NOT gate on `end_date_iso` presence -- that test moved
    to each caller (2026-08-21-discovery-gap-closure-prereg.md SS B
    amendment). The old combined gate answered two different questions
    ("did we get a usable date?" / "did we get a usable response?") with
    one test -- correct for the only caller that existed when it was
    written, and silently wrong the moment a second caller (the
    resolution-assertion branch) needed `closed`/`tokens[].winner` from a
    response whose `end_date_iso` happens to be null, which step 1's first
    attempt found is common for already-resolved markets
    (2026-08-21-step1-implementation.md, d41d02b: 3/3 sampled resolved
    markets had `closed: true`, a real winner, and `end_date_iso: None`).
    """
    if not condition_id:
        return None
    try:
        resp = session.get(f"{CLOB_API}/markets/{condition_id}", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _extract_clob_resolution(market_data: dict) -> tuple[str, str | None]:
    """
    Classify a CLOB /markets/{condition_id} response for resolution status.

    Discovery-gap closure, step 1 (2026-08-21-discovery-gap-closure-prereg.md
    SS A step 1, SS B). Mirrors discovery_gap_sizing.py's query_clob()
    classification exactly (resolved / open / indeterminate) -- not
    reinvented -- since that is the already-validated method (the sizing
    run's 527 CLOB calls, ~5% indeterminate rate).

    Returns (classification, winning_outcome_or_None). classification is
    one of {"resolved", "open", "indeterminate"}. "resolved" is returned
    only when `closed is True` AND some token has `winner: true` -- a
    closed market with no winning token is "indeterminate", per the
    sizing pre-registration's own classification (a market cannot be
    asserted resolved with a null winner via this path; allow_no_winner
    is never set True by this script's caller).
    """
    closed = market_data.get("closed")
    if closed is None:
        return "indeterminate", None
    if closed is False:
        return "open", None

    winning_outcome = None
    for token in market_data.get("tokens", []) or []:
        if token.get("winner"):
            winning_outcome = token.get("outcome")
            break

    if winning_outcome is None:
        return "indeterminate", None
    return "resolved", winning_outcome


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


_GEO_ELEC_CANDIDATES_QUERY = """
    SELECT DISTINCT m.market_id, m.title, m.condition_id, m.api_id
    FROM markets m
    INNER JOIN trades t ON (t.market_id = m.market_id OR t.market_id = m.condition_id)
    WHERE (m.end_date IS NULL OR m.resolution_date IS NULL)
      AND t.market_category IN ('Geopolitics', 'Elections')
    LIMIT ?
"""


def get_markets_to_backfill(conn, limit: int, geo_only: bool) -> list:
    """Return list of market dicts needing backfill.

    Non-geo_only runs prioritize the Geo/Elec-tagged sub-population first,
    then fill remaining budget from the full pool. `--geo-only` was dropped
    from the daily invocation 2026-08-21 because a category-scoped *filter*
    made newly-classified markets invisible -- but a plain, unordered
    `LIMIT` scan over the unscoped pool has no way to prioritise the small,
    already-correctly-tagged, highest-priority subset, and silently starved
    it (2026-09-04-limit-restore-and-sweep-closure.md). Ordering restores
    that subset's exhaustive daily coverage without reintroducing the
    filter's blind spot: unclassified/newly-classified markets still fall
    through to the general pool below, unlike under `--geo-only`.
    """
    if geo_only:
        rows = conn.execute(_GEO_ELEC_CANDIDATES_QUERY, (limit,)).fetchall()
        return [dict(r) for r in rows]

    geo_rows = conn.execute(_GEO_ELEC_CANDIDATES_QUERY, (limit,)).fetchall()
    geo_ids = [r["market_id"] for r in geo_rows]
    remaining = limit - len(geo_rows)

    rest_rows = []
    if remaining > 0:
        exclude_clause = ""
        params: tuple = (remaining,)
        if geo_ids:
            exclude_clause = f"AND market_id NOT IN ({','.join('?' * len(geo_ids))})"
            params = (*geo_ids, remaining)
        rest_query = f"""
            SELECT market_id, title, condition_id, api_id
            FROM markets
            WHERE (end_date IS NULL OR resolution_date IS NULL)
              {exclude_clause}
            LIMIT ?
        """
        rest_rows = conn.execute(rest_query, params).fetchall()

    return [dict(r) for r in geo_rows] + [dict(r) for r in rest_rows]


def backfill(limit: int, dry_run: bool, geo_only: bool, sleep: float = 0.1):
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
    resolved_accepted = 0
    resolved_rejected = 0

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
        clob_response = None

        # Strategy 0: CLOB API lookup — market_id IS the conditionId for most markets.
        # `_fetch_by_clob` no longer gates on end_date_iso (SS B amendment,
        # 2026-08-21-discovery-gap-closure-prereg.md) -- it returns whatever
        # the HTTP call got. `clob_response` keeps the first such raw
        # response, regardless of whether it carries a usable date, so the
        # assertion-branch check below can inspect `closed`/`tokens[].winner`
        # even when no date is present. `market_data`/the break/continue
        # below reproduce the ORIGINAL end_date_iso-gated behaviour exactly,
        # unchanged -- this is what the proxy branch (further below) still
        # relies on.
        for cid in filter(None, dict.fromkeys([condition_id, market_id])):
            resp_data = _fetch_by_clob(session, cid)
            if resp_data is not None and clob_response is None:
                clob_response = resp_data
            if resp_data and (resp_data.get("end_date_iso") or resp_data.get("endDateIso")):
                market_data = resp_data
                break

        # ASSERTION BRANCH (new). Checked here, ahead of the Gamma fallback
        # and the not_found skip below, because it must fire independent of
        # whether a usable end_date was found -- resolved markets on CLOB
        # frequently carry `end_date_iso: null` (root cause of step 1's
        # first stop, 2026-08-21-step1-implementation.md, d41d02b).
        # allow_no_winner is never passed: a closed market with no winning
        # token classifies "indeterminate", not "resolved", and falls
        # through to the untouched proxy branch below, unasserted.
        clob_classification = None
        clob_winner = None
        if clob_response is not None:
            clob_classification, clob_winner = _extract_clob_resolution(clob_response)

        if clob_classification == "resolved":
            result = mark_market_resolved(
                conn,
                market_id,
                winning_outcome=clob_winner,
                resolution_event_time=None,
                evidence_source="clob",
                evidence_detail="token.winner",
                dry_run=dry_run,
            )
            if result.accepted:
                resolved_accepted += 1
            else:
                resolved_rejected += 1

            # end_date is not a canonical-path column (design SS A/D) and
            # keeps a direct write here too -- but it is best-effort, not
            # required: the CLOB response for a resolved market often has
            # no date field at all, in which case there is nothing to
            # backfill and none is written.
            assert_end_date_raw = clob_response.get("end_date_iso") or clob_response.get("endDateIso")
            assert_end_date_str = _parse_end_date(assert_end_date_raw)

            if dry_run:
                print(
                    f"[DRY-RUN][CLOB-ASSERT] {market_id[:20]}... '{title[:40]}' → "
                    f"end_date={assert_end_date_str}, winning_outcome={clob_winner!r}, "
                    f"accepted={result.accepted}, reason={result.reason!r}"
                )
                updated += 1
            else:
                try:
                    if assert_end_date_str:
                        conn.execute(
                            "UPDATE markets SET end_date = ? WHERE market_id = ?",
                            (assert_end_date_str, market_id),
                        )
                        conn.commit()
                    updated += 1
                except Exception as e:
                    print(f"[BACKFILL] ERROR updating end_date for {market_id}: {e}")
                    errors += 1

            time.sleep(sleep)
            continue

        # PROXY BRANCH (existing) — untouched, byte-for-byte, below this line.

        # Strategy 1: direct lookup via numeric api_id (guaranteed exact match)
        if not market_data and api_id:
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
            time.sleep(sleep)
            continue

        end_date_raw = market_data.get("endDate") or market_data.get("endDateIso") or market_data.get("end_date_iso")
        end_date_str = _parse_end_date(end_date_raw)

        if not end_date_str:
            not_found += 1
            time.sleep(sleep)
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

        time.sleep(sleep)

    conn.close()

    print(
        f"\n[BACKFILL] Done — updated={updated}, not_found={not_found}, "
        f"skipped_no_api_id={skipped_no_api_id}, errors={errors}, "
        f"resolved_accepted={resolved_accepted}, resolved_rejected={resolved_rejected}, total={total}"
    )
    return updated, not_found, errors, resolved_accepted, resolved_rejected


def main():
    parser = argparse.ArgumentParser(description="Backfill market end_date and resolution_date")
    parser.add_argument("--limit", type=int, default=1000, help="Max markets to process (default 1000)")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument("--geo-only", action="store_true",
                        help="Only backfill markets with Geopolitics/Elections trades")
    parser.add_argument("--sleep", type=float, default=0.1,
                        help="Seconds to sleep between API calls (default 0.1, unchanged from "
                             "today's scheduled invocation; the discovery-gap sweep driver "
                             "passes 0.25 explicitly per 2026-08-21-discovery-gap-closure-prereg.md)")
    args = parser.parse_args()

    backfill(limit=args.limit, dry_run=args.dry_run, geo_only=args.geo_only, sleep=args.sleep)


if __name__ == "__main__":
    main()
