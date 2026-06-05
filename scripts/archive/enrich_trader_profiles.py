#!/usr/bin/env python3
"""
Enrich Trader Profiles — fetch Polymarket usernames for top traders.

Queries the top N traders by comprehensive_elo, fetches each trader's
Polymarket profile via the activity API, and stores the display name
(username) in the traders.username column.

API used:
    https://data-api.polymarket.com/activity?user={address}&limit=1
    Returns: name (user-chosen), pseudonym (auto-generated fallback),
             bio, profileImage, profileImageOptimized

Column written:
    traders.username  TEXT  — user-chosen name if set, else pseudonym,
                              else NULL

Usage:
    python scripts/enrich_trader_profiles.py
    python scripts/enrich_trader_profiles.py --limit 100
    python scripts/enrich_trader_profiles.py --db data/polymarket_tracker.db --limit 200
    python scripts/enrich_trader_profiles.py --dry-run        # fetch but don't write
"""

import sys
import time
import json
import sqlite3
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Project root ────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ── Constants ────────────────────────────────────────────────────────────────
PROFILE_API = "https://data-api.polymarket.com/activity?user={address}&limit=1"
REQUEST_DELAY = 1.0          # seconds between API calls
REQUEST_TIMEOUT = 10         # seconds per request
MAX_RETRIES = 2


def _add_username_column(conn: sqlite3.Connection) -> bool:
    """Add username column to traders table if it doesn't exist. Returns True if added."""
    try:
        conn.execute("ALTER TABLE traders ADD COLUMN username TEXT")
        conn.commit()
        print("[DB] Added 'username' column to traders table.")
        return True
    except sqlite3.OperationalError:
        return False  # Already exists


def _fetch_profile(address: str) -> dict | None:
    """
    Fetch Polymarket profile for one address.

    Returns dict with keys 'name', 'pseudonym', 'bio' on success,
    None on any network/parse failure.
    """
    url = PROFILE_API.format(address=address)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read())
                if not data:
                    return {}
                row = data[0]
                return {
                    "name":       (row.get("name") or "").strip(),
                    "pseudonym":  (row.get("pseudonym") or "").strip(),
                    "bio":        (row.get("bio") or "").strip(),
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}          # No activity on record — not an error
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
            else:
                return None        # Give up, log as failed
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
            else:
                return None
    return None


def _resolve_username(profile: dict) -> str | None:
    """
    Pick the best display name from a profile dict.
    Prefers user-chosen 'name'; falls back to 'pseudonym'.
    Returns None if neither is set.
    """
    if not profile:
        return None
    if profile.get("name"):
        return profile["name"]
    if profile.get("pseudonym"):
        return profile["pseudonym"]
    return None


class ProfileEnricher:
    def __init__(self, db_path: str, limit: int = 50, dry_run: bool = False):
        self.db_path = db_path
        self.limit = limit
        self.dry_run = dry_run

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def run(self):
        print("=" * 70)
        print(f"  Polymarket Profile Enrichment")
        print(f"  Limit: top {self.limit} by ELO  |  Dry run: {self.dry_run}")
        print("=" * 70)

        conn = self._connect()

        # ── [1/4] Ensure username column exists ─────────────────────────────
        print("\n[1/4] Checking database schema...")
        _add_username_column(conn)

        # ── [2/4] Load top traders ───────────────────────────────────────────
        print(f"\n[2/4] Loading top {self.limit} traders by ELO...")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT address, comprehensive_elo, realized_pnl, username
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT ?
            """,
            (self.limit,),
        )
        traders = cur.fetchall()
        print(f"      Found {len(traders)} traders.")

        # ── [3/4] Fetch profiles ─────────────────────────────────────────────
        print(f"\n[3/4] Fetching profiles (1 req/s)...\n")

        results = []
        fetched = 0
        failed = 0
        already_named = 0

        for i, (address, elo, pnl, existing_username) in enumerate(traders, 1):
            profile = _fetch_profile(address)

            if profile is None:
                username = existing_username  # Keep whatever we had
                status = "ERR"
                failed += 1
            else:
                username = _resolve_username(profile)
                if username:
                    fetched += 1
                    status = "OK "
                else:
                    status = "---"  # No profile set on Polymarket

            results.append((address, elo, pnl, username, status))

            # Progress line
            name_display = username or "(no name)"
            print(
                f"  {i:>3}/{len(traders)}  {address[:10]}  "
                f"ELO {elo:>6.0f}  [{status}]  {name_display}"
            )

            # Rate limit — skip delay after the last request
            if i < len(traders):
                time.sleep(REQUEST_DELAY)

        # ── [4/4] Write to database ──────────────────────────────────────────
        print(f"\n[4/4] Writing to database...")
        if self.dry_run:
            print("      DRY RUN — no writes performed.")
        else:
            updated = 0
            for address, elo, pnl, username, status in results:
                if status != "ERR" and username is not None:
                    cur.execute(
                        "UPDATE traders SET username = ? WHERE address = ?",
                        (username, address),
                    )
                    updated += 1
            conn.commit()
            print(f"      Updated {updated} rows.")

        conn.close()

        # ── Summary table ────────────────────────────────────────────────────
        print()
        print("=" * 70)
        print(f"  RESULTS — Top {len(results)} Traders")
        print("=" * 70)
        print(f"  {'#':<4} {'Address':<14} {'ELO':>6}  {'P&L':>10}  Username")
        print(f"  {'-'*4} {'-'*14} {'-'*6}  {'-'*10}  {'-'*25}")
        for rank, (address, elo, pnl, username, _) in enumerate(results, 1):
            pnl_str = f"${pnl:,.0f}" if pnl else "N/A"
            name_str = username or "(anonymous)"
            print(f"  {rank:<4} {address[:12]}  {elo:>6.0f}  {pnl_str:>10}  {name_str}")

        print()
        print(f"  Profiles with name : {fetched}")
        print(f"  Anonymous          : {len(results) - fetched - failed}")
        print(f"  API errors         : {failed}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Enrich top traders with Polymarket display names."
    )
    parser.add_argument(
        "--db",
        default="data/polymarket_tracker.db",
        help="Path to SQLite database (default: data/polymarket_tracker.db)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of top traders to enrich (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch profiles but do not write to database",
    )
    args = parser.parse_args()

    enricher = ProfileEnricher(
        db_path=args.db,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    enricher.run()


if __name__ == "__main__":
    main()
