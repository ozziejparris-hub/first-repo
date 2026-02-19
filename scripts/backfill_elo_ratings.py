#!/usr/bin/env python3
"""
Historical ELO Rating Backfill

Calculates accurate ELO ratings for all traders by replaying resolved markets
chronologically using actual win/loss outcomes.

Algorithm:
  For each resolved market (ordered by resolution_date):
    1. Get all traders who had open BUY positions in this market
    2. Determine which outcome won (from markets.winning_outcome)
    3. Match traders' outcome against winning_outcome
       - Binary markets (YES/NO): direct comparison
       - Multi-outcome markets: direct name match
    4. Update ELO: winners gain from losers, using weighted K-factor
       - K-factor scaled by bet size (larger bet = more ELO movement)
       - Market difficulty: fewer traders = harder market
    5. Process in resolution_date order so ELO evolves realistically

Prerequisites:
  - Run fetch_market_resolutions.py first (populates markets.winning_outcome)
  - Markets with resolved=1 and winning_outcome IS NOT NULL are used

Expected output after full backfill:
  - ELO range: 1200 - 1800+
  - Elite traders (>=1550): 50-200+
  - Average ELO: ~1500

Usage:
    # First: python scripts/fetch_market_resolutions.py
    python scripts/backfill_elo_ratings.py

    # Dry-run (calculate but don't write to DB):
    python scripts/backfill_elo_ratings.py --dry-run

    # Reset all ELO to 1500 before backfill:
    python scripts/backfill_elo_ratings.py --reset
"""

import sys
import sqlite3
import argparse
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

# ── ELO constants ────────────────────────────────────────────────────────────

STARTING_ELO = 1500.0
K_FACTOR = 32.0           # Base K-factor (same as unified_elo_system.py)
MIN_ELO = 800.0           # Floor — prevents ELO going to zero
MAX_ELO = 2500.0          # Ceiling for backfill (live system can exceed this)

# Outcome normalisation helpers
_YES_SYNONYMS = {'yes', 'y', '1', 'true', 'long'}
_NO_SYNONYMS  = {'no',  'n', '0', 'false', 'short'}


def normalise_outcome(raw: str | None) -> str:
    """
    Normalise an outcome string to a consistent lowercase form.

    Binary markets store 'Yes'/'No' in both trades.outcome and
    markets.winning_outcome.  Multi-outcome markets use arbitrary
    names (e.g. 'Chiefs', 'Republicans').  We lower-case everything
    so that comparison is case-insensitive.
    """
    if not raw:
        return ''
    s = raw.strip().lower()
    # Map common YES synonyms to canonical 'yes'
    if s in _YES_SYNONYMS:
        return 'yes'
    if s in _NO_SYNONYMS:
        return 'no'
    return s


def expected_score(rating_a: float, rating_b: float) -> float:
    """Standard ELO expected score for player A vs player B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(
    current_elo: float,
    opponent_elo: float,
    won: bool,
    k_factor: float = K_FACTOR,
) -> float:
    """
    Standard ELO update formula.

    actual_score: 1.0 for win, 0.0 for loss (no draws in prediction markets)
    """
    exp = expected_score(current_elo, opponent_elo)
    actual = 1.0 if won else 0.0
    new_elo = current_elo + k_factor * (actual - exp)
    return max(MIN_ELO, min(MAX_ELO, new_elo))


# ── Database helpers ──────────────────────────────────────────────────────────

def load_resolved_markets(cur: sqlite3.Cursor) -> list[dict]:
    """
    Return all resolved markets that have traders' trades, ordered chronologically.

    Uses resolution_date when available; falls back to end_date.
    """
    cur.execute("""
        SELECT
            m.market_id,
            m.winning_outcome,
            COALESCE(m.resolution_date, m.end_date) AS resolve_ts
        FROM markets m
        WHERE m.resolved = 1
          AND m.winning_outcome IS NOT NULL
          AND m.winning_outcome != ''
          AND EXISTS (
              SELECT 1 FROM trades t WHERE t.market_id = m.market_id
          )
        ORDER BY resolve_ts ASC NULLS LAST
    """)
    rows = cur.fetchall()
    return [
        {'market_id': r[0], 'winning_outcome': r[1], 'resolve_ts': r[2]}
        for r in rows
    ]


def load_market_traders(cur: sqlite3.Cursor, market_id: str) -> list[dict]:
    """
    Return all traders who placed BUY trades in a market, with their outcome
    and a weight proportional to the total shares bought.

    We group by (trader_address, outcome) so each trader has one position
    per outcome bet.  Traders who bet both YES and NO are treated separately
    per outcome (rare, but possible via partial exits and re-entries).
    """
    cur.execute("""
        SELECT
            trader_address,
            outcome,
            SUM(CASE WHEN shares > 0 THEN shares ELSE 0 END) AS total_shares,
            AVG(price) AS avg_price
        FROM trades
        WHERE market_id = ?
          AND shares > 0          -- only BUY positions
          AND outcome IS NOT NULL
          AND outcome != ''
        GROUP BY trader_address, outcome
        HAVING total_shares > 0
    """, (market_id,))
    rows = cur.fetchall()
    return [
        {
            'trader_address': r[0],
            'outcome': r[1],
            'total_shares': float(r[2]),
            'avg_price': float(r[3]) if r[3] else 0.5,
        }
        for r in rows
    ]


# ── Core backfill logic ───────────────────────────────────────────────────────

class ELOBackfill:

    def __init__(self, db_path: str, dry_run: bool = False, reset: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        self.reset = reset
        self.elo: dict[str, float] = defaultdict(lambda: STARTING_ELO)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Step 1: Load seed ELO ────────────────────────────────────────────

    def load_seed_elos(self, cur: sqlite3.Cursor):
        """
        Seed in-memory ELO from DB.

        If --reset: everyone starts at 1500.
        Otherwise: use existing comprehensive_elo if present (allows incremental
        re-runs without wiping prior ratings).
        """
        if self.reset:
            print("  --reset flag: all traders start at 1500")
            return

        cur.execute("""
            SELECT address, comprehensive_elo
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
        """)
        loaded = 0
        for address, elo in cur.fetchall():
            if elo:
                self.elo[address] = float(elo)
                loaded += 1
        print(f"  Seeded {loaded:,} existing ELO ratings from DB")

    # ── Step 2: Process each resolved market ─────────────────────────────

    def process_market(self, market: dict, traders: list[dict]) -> int:
        """
        Update ELO for all traders in one resolved market.

        Returns number of ELO updates applied.
        """
        winning_outcome_norm = normalise_outcome(market['winning_outcome'])
        if not winning_outcome_norm:
            return 0

        # Partition into winners and losers
        winners = [t for t in traders if normalise_outcome(t['outcome']) == winning_outcome_norm]
        losers  = [t for t in traders if normalise_outcome(t['outcome']) != winning_outcome_norm]

        if not winners or not losers:
            # If everyone bet the same side (or no one on one side), no ELO movement
            return 0

        # Market difficulty: fewer total participants → harder market (they had less
        # information / competition to help them decide)
        n_traders = len(traders)
        difficulty = max(0.5, min(1.5, 1.0 + (10 - n_traders) / 20.0))

        # Average ELO of winners and losers (used as "opponent" for each side)
        avg_winner_elo = sum(self.elo[t['trader_address']] for t in winners) / len(winners)
        avg_loser_elo  = sum(self.elo[t['trader_address']] for t in losers)  / len(losers)

        # Max shares in this market (used to normalise bet size)
        max_shares = max(t['total_shares'] for t in traders)

        updates = 0

        for trader in winners:
            addr = trader['trader_address']
            bet_size_norm = min(trader['total_shares'] / max_shares, 2.0) if max_shares > 0 else 1.0
            adjusted_k = K_FACTOR * bet_size_norm * difficulty

            self.elo[addr] = update_elo(
                self.elo[addr], avg_loser_elo, won=True, k_factor=adjusted_k
            )
            updates += 1

        for trader in losers:
            addr = trader['trader_address']
            bet_size_norm = min(trader['total_shares'] / max_shares, 2.0) if max_shares > 0 else 1.0
            adjusted_k = K_FACTOR * bet_size_norm * difficulty

            self.elo[addr] = update_elo(
                self.elo[addr], avg_winner_elo, won=False, k_factor=adjusted_k
            )
            updates += 1

        return updates

    # ── Step 3: Persist results ───────────────────────────────────────────

    def save_elos(self, conn: sqlite3.Connection):
        """Write all computed ELOs back to traders.comprehensive_elo."""
        cur = conn.cursor()
        now = datetime.now().isoformat()

        updated = 0
        for address, elo in self.elo.items():
            cur.execute("""
                UPDATE traders
                SET comprehensive_elo = ?,
                    base_category_elo = ?,
                    elo_last_updated = ?
                WHERE address = ?
            """, (round(elo, 4), round(elo, 4), now, address))
            if cur.rowcount > 0:
                updated += 1

        conn.commit()
        return updated

    # ── Step 4: Statistics ────────────────────────────────────────────────

    def print_stats(self, cur: sqlite3.Cursor):
        cur.execute("""
            SELECT
                COUNT(*) as n,
                AVG(comprehensive_elo),
                MIN(comprehensive_elo),
                MAX(comprehensive_elo)
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
        """)
        n, avg, lo, hi = cur.fetchone()
        print(f"  Total traders with ELO : {n:,}")
        print(f"  ELO range              : {lo:.0f} – {hi:.0f}")
        print(f"  Average ELO            : {avg:.0f}")
        print()

        for label, threshold in [('Elite (≥1550)', 1550), ('Expert (≥1600)', 1600), ('Master (≥1700)', 1700)]:
            cur.execute("SELECT COUNT(*) FROM traders WHERE comprehensive_elo >= ?", (threshold,))
            cnt = cur.fetchone()[0]
            pct = cnt / n * 100 if n else 0
            print(f"  {label:<20} : {cnt:>5,}  ({pct:.1f}%)")

        print()
        print("  Top 15 traders:")
        cur.execute("""
            SELECT address, comprehensive_elo, roi_percentage, closed_positions
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 15
        """)
        for rank, (addr, elo, roi, closed) in enumerate(cur.fetchall(), 1):
            roi_str = f"{roi:+.1f}%" if roi is not None else "n/a"
            print(f"    {rank:>2}. {addr[:6]}...{addr[-4:]}  ELO={elo:>7.1f}  "
                  f"ROI={roi_str:>7}  closed_pos={closed}")

    # ── Main entry ────────────────────────────────────────────────────────

    def run(self):
        print("\n" + "=" * 70)
        print("  HISTORICAL ELO BACKFILL  (accurate — resolution-based)")
        print("=" * 70)
        if self.dry_run:
            print("  *** DRY RUN — no changes will be written to database ***")
            print()

        conn = self._connect()
        cur  = conn.cursor()

        # 1. Seed
        print("\n[1/4] Seeding ELO ratings...")
        self.load_seed_elos(cur)

        # 2. Load resolved markets
        print("\n[2/4] Loading resolved markets...")
        markets = load_resolved_markets(cur)
        print(f"  Found {len(markets):,} resolved markets with trader activity")

        if not markets:
            print("\n  ⚠️  No resolved markets found.")
            print("  Run: python scripts/fetch_market_resolutions.py")
            conn.close()
            return

        # 3. Process chronologically
        print(f"\n[3/4] Replaying {len(markets):,} markets chronologically...")
        total_updates = 0
        skipped = 0

        for i, market in enumerate(markets, 1):
            traders = load_market_traders(cur, market['market_id'])

            if not traders:
                skipped += 1
                continue

            updates = self.process_market(market, traders)
            total_updates += updates

            if i % 20 == 0 or i == len(markets):
                unique_traders = len(self.elo)
                print(
                    f"  [{i:>5}/{len(markets)}]  ELO updates={total_updates:,}  "
                    f"traders tracked={unique_traders:,}",
                    end='\r',
                    flush=True,
                )

        print()  # newline after \r
        print(f"  Markets processed  : {len(markets) - skipped:,}")
        print(f"  Markets skipped    : {skipped:,}  (no BUY trades found)")
        print(f"  Total ELO updates  : {total_updates:,}")
        print(f"  Unique traders     : {len(self.elo):,}")

        # 4. Save
        if self.dry_run:
            print("\n[4/4] Dry run — skipping database write")
            # Still show stats from in-memory data
            elo_vals = list(self.elo.values())
            if elo_vals:
                elite = sum(1 for e in elo_vals if e >= 1550)
                print(f"\n  In-memory ELO range : {min(elo_vals):.0f} – {max(elo_vals):.0f}")
                print(f"  Average ELO         : {sum(elo_vals)/len(elo_vals):.0f}")
                print(f"  Elite traders       : {elite:,}")
        else:
            print("\n[4/4] Writing ELO ratings to database...")
            written = self.save_elos(conn)
            print(f"  Updated {written:,} trader records")

        # 5. Stats from DB
        if not self.dry_run:
            print("\n" + "=" * 70)
            print("  RESULTS")
            print("=" * 70)
            self.print_stats(cur)

        conn.close()

        print("\n" + "=" * 70)
        if self.dry_run:
            print("  DRY RUN complete — re-run without --dry-run to apply changes")
        else:
            print("  ✅  BACKFILL COMPLETE")
            print()
            print("  Next steps:")
            print("    1. Restart System Observer to pick up new ELO ratings")
            print("    2. Check consensus detection — elite traders should now appear")
            print("    3. Review top traders to validate ELO makes intuitive sense")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description='Backfill historical ELO ratings using resolved market outcomes'
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Calculate ELO but do not write to database')
    parser.add_argument('--reset', action='store_true',
                        help='Reset all ELO to 1500 before backfill (full recalculation)')
    parser.add_argument('--db', default='data/polymarket_tracker.db',
                        help='Path to SQLite database')
    args = parser.parse_args()

    backfill = ELOBackfill(
        db_path=args.db,
        dry_run=args.dry_run,
        reset=args.reset,
    )
    backfill.run()


if __name__ == "__main__":
    main()
