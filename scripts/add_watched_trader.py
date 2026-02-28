#!/usr/bin/env python3
"""
Add Watched Trader — manually add a high-interest trader to the watchlist.

Watched traders receive Telegram alerts for every new trade regardless of ELO,
labelled with a 👁 WATCHED TRADER badge.

Usage:
    python scripts/add_watched_trader.py --address 0x4dfd481c...
    python scripts/add_watched_trader.py --username Magamyman --address 0x4dfd481c...
    python scripts/add_watched_trader.py --list                   # show all watched traders
    python scripts/add_watched_trader.py --remove --address 0x... # unwatch
"""

import sys
import json
import sqlite3
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Project root ─────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ── Constants ─────────────────────────────────────────────────────────────────
ACTIVITY_API  = "https://data-api.polymarket.com/activity?user={address}&limit=1"
REQUEST_TIMEOUT = 10


def _ensure_columns(conn: sqlite3.Connection):
    """Add discovery_source and watched columns if they don't exist."""
    for ddl in [
        "ALTER TABLE traders ADD COLUMN discovery_source TEXT DEFAULT 'live_feed'",
        "ALTER TABLE traders ADD COLUMN watched INTEGER DEFAULT 0",
        "ALTER TABLE traders ADD COLUMN username TEXT",
    ]:
        try:
            conn.execute(ddl)
            col = ddl.split("ADD COLUMN")[1].strip().split()[0]
            print(f"[DB] Added '{col}' column to traders table.")
        except sqlite3.OperationalError:
            pass  # already exists
    conn.commit()


def _fetch_profile(address: str) -> dict:
    """Fetch Polymarket profile for address. Returns dict with name/pseudonym."""
    url = ACTIVITY_API.format(address=address)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
            if data:
                row = data[0]
                return {
                    "name":      (row.get("name") or "").strip(),
                    "pseudonym": (row.get("pseudonym") or "").strip(),
                }
    except Exception:
        pass
    return {}


def _resolve_username(profile: dict, provided_username: str | None) -> str | None:
    """Return best username: provided arg > API name > pseudonym."""
    if provided_username:
        return provided_username
    if profile.get("name"):
        return profile["name"]
    if profile.get("pseudonym"):
        return profile["pseudonym"]
    return None


def cmd_list(db_path: str):
    """Print all currently watched traders."""
    conn = sqlite3.connect(db_path)
    _ensure_columns(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT address, username, comprehensive_elo, realized_pnl,
               discovery_source, first_seen
        FROM traders
        WHERE watched = 1
        ORDER BY COALESCE(comprehensive_elo, 0) DESC
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No watched traders yet.")
        return

    print(f"\n{'='*70}")
    print(f"  Watched Traders ({len(rows)} total)")
    print(f"{'='*70}")
    print(f"  {'Address':<14}  {'Username':<20}  {'ELO':>6}  {'P&L':>12}  Source")
    print(f"  {'-'*14}  {'-'*20}  {'-'*6}  {'-'*12}  {'-'*15}")
    for address, username, elo, pnl, source, first_seen in rows:
        elo_str  = f"{elo:.0f}" if elo else "N/A"
        pnl_str  = f"${pnl:,.0f}" if pnl else "N/A"
        name_str = username or "(anonymous)"
        print(f"  {address[:12]}..  {name_str:<20}  {elo_str:>6}  {pnl_str:>12}  {source or 'live_feed'}")
    print()


def cmd_add(db_path: str, address: str, username: str | None, dry_run: bool):
    """Add or update a trader on the watchlist."""
    address = address.lower()

    print(f"\n{'='*60}")
    print(f"  Adding Watched Trader")
    print(f"  Address: {address}")
    print(f"{'='*60}\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_columns(conn)
    cur = conn.cursor()

    # Check if already in DB
    cur.execute("SELECT address, username, comprehensive_elo, is_flagged FROM traders WHERE address = ?",
                (address,))
    existing = cur.fetchone()
    if existing:
        print(f"[DB] Trader already in database:")
        print(f"     Username: {existing[1] or '(none)'}")
        print(f"     ELO:      {existing[2] or 'N/A'}")
        print(f"     Flagged:  {existing[3]}")
    else:
        print(f"[DB] New trader — not currently in database.")

    # Fetch Polymarket profile
    print(f"\n[API] Fetching Polymarket profile...")
    profile = _fetch_profile(address)
    resolved_username = _resolve_username(profile, username)

    if resolved_username:
        print(f"[API] Username resolved: {resolved_username}")
    else:
        print(f"[API] No username found (anonymous trader).")

    if dry_run:
        print("\n[DRY RUN] Would upsert into traders table:")
        print(f"  address:          {address}")
        print(f"  username:         {resolved_username or '(none)'}")
        print(f"  watched:          1")
        print(f"  discovery_source: manual_watchlist")
        print(f"  is_flagged:       1")
        conn.close()
        return

    # UPSERT — insert or update with watched=1
    cur.execute("""
        INSERT INTO traders (
            address, total_trades, successful_trades, win_rate,
            total_volume, is_flagged, watched, discovery_source,
            username, last_updated
        ) VALUES (?, 0, 0, 0.0, 0.0, 1, 1, 'manual_watchlist', ?, ?)
        ON CONFLICT(address) DO UPDATE SET
            watched          = 1,
            discovery_source = CASE
                WHEN discovery_source IS NULL OR discovery_source = 'live_feed'
                THEN 'manual_watchlist'
                ELSE discovery_source
            END,
            is_flagged       = 1,
            username         = CASE
                WHEN ? IS NOT NULL THEN ?
                ELSE username
            END,
            last_updated     = ?
    """, (address, resolved_username, datetime.now(),
          resolved_username, resolved_username, datetime.now()))
    conn.commit()
    conn.close()

    print(f"\n[OK] Trader added to watchlist:")
    print(f"     Address:  {address[:10]}...{address[-4:]}")
    print(f"     Username: {resolved_username or '(anonymous)'}")
    print(f"     Watched:  YES — will receive priority alerts regardless of ELO")
    print()


def cmd_remove(db_path: str, address: str, dry_run: bool):
    """Remove a trader from the watchlist (sets watched=0, keeps other data)."""
    address = address.lower()
    conn = sqlite3.connect(db_path)
    _ensure_columns(conn)
    cur = conn.cursor()

    cur.execute("SELECT address, username FROM traders WHERE address = ?", (address,))
    row = cur.fetchone()
    if not row:
        print(f"[ERR] Address {address[:12]}... not found in database.")
        conn.close()
        return

    print(f"[DB] Unwatching: {address[:10]}...{address[-4:]} ({row[1] or 'anonymous'})")

    if not dry_run:
        cur.execute("UPDATE traders SET watched = 0 WHERE address = ?", (address,))
        conn.commit()
        print("[OK] Trader removed from watchlist (data preserved).")
    else:
        print("[DRY RUN] Would set watched=0.")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Add or manage manually watched traders."
    )
    parser.add_argument("--db", default="data/polymarket_tracker.db",
                        help="Path to SQLite database")
    parser.add_argument("--address", help="Wallet address to watch")
    parser.add_argument("--username", help="Optional display name override")
    parser.add_argument("--remove", action="store_true",
                        help="Remove from watchlist instead of adding")
    parser.add_argument("--list", action="store_true",
                        help="List all currently watched traders")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without writing")
    args = parser.parse_args()

    if args.list:
        cmd_list(args.db)
        return

    if not args.address:
        parser.error("--address is required (use --list to see existing watched traders)")

    if args.remove:
        cmd_remove(args.db, args.address, args.dry_run)
    else:
        cmd_add(args.db, args.address, args.username, args.dry_run)


if __name__ == "__main__":
    main()
