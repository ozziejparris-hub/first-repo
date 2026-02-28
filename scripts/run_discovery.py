#!/usr/bin/env python3
"""
Run Discovery — orchestrate all trader discovery channels.

Runs Channel 1 (leaderboard sweep) and Channel 2 (market participants) in
sequence. Respects a 7-day cadence by default to avoid hammering the API.
The manual watchlist (Channel 3) runs on demand only via add_watched_trader.py.

Usage:
    python scripts/run_discovery.py           # respects 7-day cadence
    python scripts/run_discovery.py --force   # always runs regardless of cadence
    python scripts/run_discovery.py --channel 1   # run Channel 1 only
    python scripts/run_discovery.py --channel 2   # run Channel 2 only
    python scripts/run_discovery.py --dry-run --force
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# ── Project root ─────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

CADENCE_DAYS = 7
TIMESTAMP_FILE = project_root / "data" / "last_discovery_run.txt"


def _read_last_run() -> datetime | None:
    """Read the timestamp of the last successful discovery run."""
    if not TIMESTAMP_FILE.exists():
        return None
    try:
        ts_str = TIMESTAMP_FILE.read_text().strip()
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _write_last_run():
    """Record the current time as the last successful discovery run."""
    TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    TIMESTAMP_FILE.write_text(datetime.now().isoformat())


def _cadence_check(force: bool) -> bool:
    """Return True if discovery should run. Prints reason if skipping."""
    if force:
        return True

    last_run = _read_last_run()
    if last_run is None:
        print(f"[CADENCE] No previous run found — running for the first time.")
        return True

    age = datetime.now() - last_run
    if age >= timedelta(days=CADENCE_DAYS):
        print(f"[CADENCE] Last run: {last_run.strftime('%Y-%m-%d %H:%M')} ({age.days} days ago) — running.")
        return True

    next_run = last_run + timedelta(days=CADENCE_DAYS)
    remaining = next_run - datetime.now()
    hours = int(remaining.total_seconds() // 3600)
    print(f"[CADENCE] Last run: {last_run.strftime('%Y-%m-%d %H:%M')} ({age.days}d {age.seconds//3600}h ago)")
    print(f"[CADENCE] Next scheduled run in ~{hours}h. Use --force to override.")
    return False


def run_channel_1(db_path: str, dry_run: bool):
    """Run leaderboard discovery (Channel 1)."""
    from discover_leaderboard_traders import LeaderboardDiscovery
    print("\n" + "=" * 70)
    print("  CHANNEL 1 — Leaderboard / Market Sweep Discovery")
    print("=" * 70)
    discovery = LeaderboardDiscovery(db_path=db_path, market_limit=50, dry_run=dry_run)
    discovery.run()


def run_channel_2(db_path: str, dry_run: bool):
    """Run market participant discovery (Channel 2)."""
    from discover_market_participants import MarketParticipantDiscovery
    print("\n" + "=" * 70)
    print("  CHANNEL 2 — High-Signal Market Participant Discovery")
    print("=" * 70)
    discovery = MarketParticipantDiscovery(db_path=db_path, min_elite_traders=3, dry_run=dry_run)
    discovery.run()


def main():
    parser = argparse.ArgumentParser(
        description="Run all trader discovery channels (weekly cadence)."
    )
    parser.add_argument("--db", default="data/polymarket_tracker.db",
                        help="Path to SQLite database")
    parser.add_argument("--force", action="store_true",
                        help="Ignore cadence and run regardless of last run time")
    parser.add_argument("--channel", type=int, choices=[1, 2],
                        help="Run only the specified channel (1=leaderboard, 2=market participants)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch but don't write to database")
    args = parser.parse_args()

    print("=" * 70)
    print("  Polymarket Trader Discovery Runner")
    print(f"  DB:      {args.db}")
    print(f"  Force:   {args.force}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Channel: {args.channel or 'all'}")
    print("=" * 70)
    print()

    if not _cadence_check(args.force):
        sys.exit(0)

    # Add the scripts directory to path so channel imports work
    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))

    start = datetime.now()
    ran_ok = True

    try:
        if args.channel is None or args.channel == 1:
            run_channel_1(args.db, args.dry_run)

        if args.channel is None or args.channel == 2:
            run_channel_2(args.db, args.dry_run)

    except Exception as e:
        print(f"\n[ERROR] Discovery failed: {e}")
        import traceback
        traceback.print_exc()
        ran_ok = False

    elapsed = datetime.now() - start
    print(f"\n{'='*70}")
    print(f"  Discovery complete. Elapsed: {elapsed.seconds // 60}m {elapsed.seconds % 60}s")

    if ran_ok and not args.dry_run:
        _write_last_run()
        print(f"  Next scheduled run: {(datetime.now() + timedelta(days=CADENCE_DAYS)).strftime('%Y-%m-%d')}")
    elif args.dry_run:
        print(f"  (DRY RUN — cadence timestamp not updated)")

    print(f"{'='*70}")


if __name__ == "__main__":
    main()
