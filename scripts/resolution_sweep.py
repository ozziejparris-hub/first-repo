#!/usr/bin/env python3
"""
Resolution Sweep — Channel 2 discovery.

When political/geopolitics markets resolve, sweep ALL significant traders from
those markets into the monitored pool. Catches event-specific insiders
(Magamyman archetype) who trade single markets in large size and would never
appear in leaderboard discovery (which requires 3+ markets).

Categories swept: 'Elections', 'Geopolitics', 'Global Politics', 'Politics', 'Ukraine & Russia'

Entry criteria (intentionally permissive — catch small insiders):
  - total position volume >= $500 in the market
  - No minimum trade count (one large bet qualifies)
  - No minimum geo market count (single-event traders are the TARGET)
  - Skip bot_type IN ('LP_ARTIFACT', 'ARB_BOT') only

Usage:
    python scripts/resolution_sweep.py
    python scripts/resolution_sweep.py --dry-run
    python scripts/resolution_sweep.py --days 30 --dry-run
    python scripts/resolution_sweep.py --db data/polymarket_tracker.db
"""

import sys
import time
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

DB_DEFAULT  = "data/polymarket_tracker.db"
MIN_VOLUME  = 500.0
BOT_EXCLUDE = ("LP_ARTIFACT", "ARB_BOT")

# SQLite limit for IN (?) placeholders — stay under 999
_IN_BATCH = 900


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_existing_traders(cur: sqlite3.Cursor, addresses: list[str]) -> dict:
    """Return {lower_address: Row} for all addresses already in traders table."""
    result = {}
    for i in range(0, len(addresses), _IN_BATCH):
        batch = addresses[i:i + _IN_BATCH]
        placeholders = ",".join("?" * len(batch))
        cur.execute(
            f"SELECT LOWER(address) AS address, is_flagged, research_excluded, bot_type "
            f"FROM traders WHERE LOWER(address) IN ({placeholders})",
            batch,
        )
        for row in cur.fetchall():
            result[row["address"]] = row
    return result


class ResolutionSweep:
    def __init__(self, db_path: str, days: int = 7, dry_run: bool = False):
        self.db_path = db_path
        self.days    = days
        self.dry_run = dry_run

    def run(self):
        print("=" * 70)
        print("  Resolution Sweep — Channel 2 Discovery")
        print(f"  Lookback window:     {self.days} days")
        print(f"  Min position volume: ${MIN_VOLUME:,.0f}")
        print(f"  Dry run:             {self.dry_run}")
        print("=" * 70)

        conn = _connect(self.db_path)
        try:
            self._run(conn)
        finally:
            conn.close()

    def _run(self, conn: sqlite3.Connection):
        cur  = conn.cursor()
        now  = datetime.now()

        # ── [1/4] Find recently resolved political/geopolitics markets ──────────
        print(f"\n[1/4] Finding political/geopolitics markets resolved in last {self.days} days...")
        cur.execute("""
            SELECT market_id, title, resolution_date, winning_outcome
            FROM markets
            WHERE resolved = 1
              AND resolution_date >= datetime('now', ?)
              AND resolution_date <= datetime('now')
              AND market_id IN (
                SELECT DISTINCT market_id FROM trades
                WHERE market_category IN ('Geopolitics', 'Elections')
              )
            ORDER BY resolution_date DESC
        """, (f"-{self.days} days",))
        markets = cur.fetchall()
        print(f"      Found {len(markets)} markets.")

        if not markets:
            print(f"\n      No political/geopolitics markets resolved in the last {self.days} days.")
            print("      Try --days 30 or --days 60 for a wider window.")
            _print_summary(
                days=self.days, markets_swept=0, qualifying=0,
                new=0, promoted=0, already_ok=0, dry_run=self.dry_run,
                market_breakdown=[],
            )
            return

        for m in markets:
            title_short = (m["title"] or m["market_id"])[:60].encode("ascii", "replace").decode("ascii")
            outcome     = (m["winning_outcome"] or "?")[:8]
            rdate       = (m["resolution_date"] or "")[:10]
            print(f"      {rdate}  [{outcome:>8}]  {title_short}")

        # ── [2/4] Fetch qualifying traders per market ─────────────────────────
        print(f"\n[2/4] Fetching traders per market (min volume ${MIN_VOLUME:,.0f})...")

        # market_id → list of rows; deduped across markets by best volume
        market_trader_counts: dict[str, int] = {}
        all_candidates: dict[str, float] = {}  # lower_address → best total_volume seen

        for idx, m in enumerate(markets, 1):
            market_id   = m["market_id"]
            title_short = (m["title"] or market_id)[:50].encode("ascii", "replace").decode("ascii")

            cur.execute("""
                SELECT LOWER(trader_address) AS trader_address,
                       SUM(entry_total_cost)  AS total_volume,
                       MAX(entry_total_cost)  AS max_single_position
                FROM positions
                WHERE market_id = ?
                GROUP BY LOWER(trader_address)
                HAVING SUM(entry_total_cost) >= ?
            """, (market_id, MIN_VOLUME))
            rows = cur.fetchall()

            market_trader_counts[market_id] = len(rows)
            print(f"  [{idx:>2}/{len(markets)}] {title_short}")
            print(f"         Qualifying traders (≥${MIN_VOLUME:,.0f}): {len(rows)}")

            for row in rows:
                addr = row["trader_address"]
                vol  = float(row["total_volume"])
                if addr not in all_candidates or all_candidates[addr] < vol:
                    all_candidates[addr] = vol

        total_qualifying = len(all_candidates)
        print(f"\n      Total unique qualifying traders across all markets: {total_qualifying}")

        if not total_qualifying:
            print("\n      No qualifying traders found. Exiting.")
            _print_summary(
                days=self.days, markets_swept=len(markets), qualifying=0,
                new=0, promoted=0, already_ok=0, dry_run=self.dry_run,
                market_breakdown=[(m, market_trader_counts[m["market_id"]]) for m in markets],
            )
            return

        # ── [3/4] Classify candidates against existing traders ─────────────────
        print(f"\n[3/4] Classifying {total_qualifying} candidates against DB...")

        existing = _fetch_existing_traders(cur, list(all_candidates.keys()))

        new_traders:      list[tuple[str, float]] = []
        promoted_traders: list[tuple[str, float]] = []
        already_ok:       list[tuple[str, float]] = []

        for addr, vol in all_candidates.items():
            if addr not in existing:
                new_traders.append((addr, vol))
                continue

            row       = existing[addr]
            bot_type  = row["bot_type"]
            if bot_type in BOT_EXCLUDE:
                continue  # skip — bot measurement artefact

            is_flagged        = bool(row["is_flagged"])
            research_excluded = bool(row["research_excluded"])

            if not is_flagged or research_excluded:
                promoted_traders.append((addr, vol))
            else:
                already_ok.append((addr, vol))

        print(f"      New traders to add:             {len(new_traders)}")
        print(f"      Existing traders to promote:    {len(promoted_traders)}")
        print(f"      Already flagged (no change):    {len(already_ok)}")

        # ── [4/4] Apply writes ────────────────────────────────────────────────
        print(f"\n[4/4] {'DRY RUN — showing planned changes' if self.dry_run else 'Writing to database'}...")

        added    = 0
        promoted = 0

        for addr, vol in new_traders:
            print(f"  [NEW]     {addr[:16]}  vol=${vol:>9,.0f}")
            if not self.dry_run:
                for _attempt in range(5):
                    try:
                        cur.execute("""
                            INSERT INTO traders (
                                address, total_trades, successful_trades, win_rate,
                                total_volume, is_flagged, research_excluded,
                                discovery_source, backfill_attempted, last_updated
                            ) VALUES (?, 0, 0, 0.0, ?, 1, 0, 'resolution_sweep', NULL, ?)
                            ON CONFLICT(address) DO NOTHING
                        """, (addr, vol, now))
                        if cur.rowcount > 0:
                            added += 1
                        if added % 50 == 0:
                            conn.commit()
                        break
                    except sqlite3.OperationalError as e:
                        if "locked" in str(e):
                            time.sleep(3)
                        else:
                            raise

        for addr, vol in promoted_traders:
            print(f"  [PROMOTE] {addr[:16]}  vol=${vol:>9,.0f}")
            if not self.dry_run:
                for _attempt in range(5):
                    try:
                        cur.execute("""
                            UPDATE traders
                            SET is_flagged = 1, research_excluded = 0, last_updated = ?
                            WHERE LOWER(address) = ?
                        """, (now, addr))
                        if cur.rowcount > 0:
                            promoted += 1
                        if promoted % 50 == 0:
                            conn.commit()
                        break
                    except sqlite3.OperationalError as e:
                        if "locked" in str(e):
                            time.sleep(3)
                        else:
                            raise

        if not self.dry_run:
            conn.commit()

        _print_summary(
            days=self.days,
            markets_swept=len(markets),
            qualifying=total_qualifying,
            new=added    if not self.dry_run else len(new_traders),
            promoted=promoted if not self.dry_run else len(promoted_traders),
            already_ok=len(already_ok),
            dry_run=self.dry_run,
            market_breakdown=[(m, market_trader_counts[m["market_id"]]) for m in markets],
        )


def _print_summary(
    days: int,
    markets_swept: int,
    qualifying: int,
    new: int,
    promoted: int,
    already_ok: int,
    dry_run: bool,
    market_breakdown: list,
):
    dry_tag = " (DRY RUN)" if dry_run else ""
    print()
    print("=" * 70)
    print("  RESULTS — Resolution Sweep")
    print("=" * 70)
    print(f"  Markets resolved (last {days}d):{'':<4}{markets_swept}")
    print(f"  Total qualifying traders:     {qualifying}")
    print(f"  New traders added:{dry_tag:<12}{new}")
    print(f"  Existing traders promoted:{dry_tag:<5}{promoted}")
    print(f"  Already flagged (no change):  {already_ok}")
    if dry_run:
        print("  (DRY RUN — no writes)")
    if market_breakdown:
        print()
        print("  Per-market breakdown:")
        for m, count in market_breakdown:
            title_short = (m["title"] or m["market_id"])[:50].encode("ascii", "replace").decode("ascii")
            outcome     = (m["winning_outcome"] or "?")[:8]
            print(f"    [{outcome:>8}]  {count:>4} traders  {title_short}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Sweep recently resolved political/geopolitics markets for significant traders."
    )
    parser.add_argument("--db", default=DB_DEFAULT,
                        help="Path to SQLite database")
    parser.add_argument("--days", type=int, default=7,
                        help="Lookback window in days (default: 7)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report changes without writing to database")
    args = parser.parse_args()

    ResolutionSweep(
        db_path=args.db,
        days=args.days,
        dry_run=args.dry_run,
    ).run()


if __name__ == "__main__":
    main()
