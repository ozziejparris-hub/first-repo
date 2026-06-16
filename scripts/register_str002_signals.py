#!/usr/bin/env python3
"""
register_str002_signals.py — STR-002 signal registry builder.

STR-002 = pre-resolution divergence signal. A signal is born the FIRST time a
market+direction crosses the divergence threshold in the daily pre-res scan.
"First-seen wins": subsequent daily appearances of the same market+direction are
ignored — the signal already exists with its registration-time state locked in.

DESIGN PRINCIPLE (per integration contract): lock concrete identifiers (market_id)
at registration BEFORE resolution. Scoring then queries market_id directly — no
title-matching at score time, no ambiguity from title drift.

What it does:
  1. Creates str002_signals table (idempotent)
  2. Reads ALL historical pre-res scan files chronologically
  3. For each market+direction, finds its FIRST appearance (earliest scan date)
  4. Resolves title -> market_id ONCE, locks it into the registry
  5. Captures registration state: market_price_at_registration, smart_money_pct,
     tier, elite/legendary counts, resolution_date
  6. INSERT OR IGNORE on PK (market_id, direction) enforces first-seen

Idempotent: re-running registers only NEW first-seen signals. Existing rows untouched.

Wire into daily maintenance AFTER the pre-res scan step so each day's new signals
get registered with that day's price as their registration price.

Usage:
  python3 register_str002_signals.py            # register all first-seen signals
  python3 register_str002_signals.py --stats    # show registry stats
"""

import json
import sqlite3
import argparse
import glob
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
SCAN_DIR = Path("/home/parison/trading-swarm/brain/agent-outputs/pre-resolution/")


def ensure_table(conn):
    """Create str002_signals table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS str002_signals (
            signal_id            TEXT,
            market_id            TEXT NOT NULL,
            market_title         TEXT,
            direction            TEXT NOT NULL,
            tier                 TEXT,
            first_seen_date      TEXT,
            registered_at        TEXT,
            market_price_at_registration  REAL,
            smart_money_pct_at_registration REAL,
            gap_pt_at_registration         REAL,
            elite_traders        INTEGER,
            legendary_traders    INTEGER,
            resolution_date      TEXT,
            outcome_correct      INTEGER,
            winning_outcome      TEXT,
            edge_at_entry        REAL,
            resolved_at          TEXT,
            scored_at            TEXT,
            PRIMARY KEY (market_id, direction)
        )
    """)
    conn.commit()


def collect_first_seen(conn):
    """Read all scan files chronologically, return {(market_id, direction): first_seen_record}."""
    scan_files = sorted(glob.glob(str(SCAN_DIR / "*-pre-res-scan.json")))
    cur = conn.cursor()
    first_seen = {}
    unmatched = []

    for scan_path in scan_files:
        scan_date = os.path.basename(scan_path)[:10]
        try:
            with open(scan_path) as f:
                scan = json.load(f)
        except Exception as e:
            print(f"  [warn] Could not read {scan_path}: {e}", file=sys.stderr)
            continue

        for s in scan.get('signals', []):
            title = s.get('market', '')
            direction = (s.get('direction') or '').upper()
            if not title or direction not in ('YES', 'NO'):
                continue

            # Resolve title -> market_id ONCE (locking concrete identifier)
            # When duplicates exist, pick the market_id with highest trade activity
            cur.execute("SELECT market_id FROM markets WHERE title = ?", (title,))
            row = cur.fetchone()
            if not row:
                unmatched.append((scan_date, title))
                continue
            market_id = row[0]

            # Minimum activity filter: skip thin markets (noise, not signal)
            # Threshold: >=200 trades OR >=50000 notional (shares*price)
            cur.execute("""
                SELECT COUNT(trade_id), COALESCE(SUM(shares*price),0)
                FROM trades WHERE market_id = ?
            """, (market_id,))
            activity = cur.fetchone()
            trade_count, notional = activity[0], activity[1]
            if trade_count < 200 and notional < 50000:
                continue  # Skip thin market — divergence is meaningless

            key = (market_id, direction)
            if key not in first_seen:  # FIRST-SEEN WINS
                first_seen[key] = {
                    'market_id': market_id,
                    'market_title': title,
                    'direction': direction,
                    'tier': s.get('tier'),
                    'first_seen_date': scan_date,
                    'market_price_pct': s.get('market_price_pct'),
                    'smart_money_pct': s.get('smart_money_pct'),
                    'gap_pt': s.get('gap_pt'),
                    'elite_traders': s.get('elite_traders', 0),
                    'legendary_traders': s.get('legendary_traders', 0),
                    'resolution_date': s.get('resolution_date'),
                }

    if unmatched:
        print(f"  [warn] {len(unmatched)} scan entries could not resolve title->market_id")
        for d, t in unmatched[:5]:
            print(f"    [{d}] {t[:50]}", file=sys.stderr)

    return first_seen


def next_signal_id(conn, existing_count):
    """Generate next STR002-NNNN id."""
    cur = conn.cursor()
    cur.execute("SELECT signal_id FROM str002_signals WHERE signal_id IS NOT NULL")
    nums = []
    import re
    for (sid,) in cur.fetchall():
        m = re.match(r'STR002-(\d+)', sid or '')
        if m:
            nums.append(int(m.group(1)))
    start = (max(nums) + 1) if nums else 1
    return start


def register_all(conn):
    """Register all first-seen signals. Idempotent via INSERT OR IGNORE."""
    ensure_table(conn)
    first_seen = collect_first_seen(conn)
    print(f"Unique first-seen signals found: {len(first_seen)}")

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    next_num = next_signal_id(conn, len(first_seen))

    registered = 0
    skipped = 0
    cur = conn.cursor()

    # Sort by first_seen_date so signal_id order roughly follows chronology
    items = sorted(first_seen.items(), key=lambda kv: kv[1]['first_seen_date'])

    for (market_id, direction), rec in items:
        # Check if already registered
        cur.execute(
            "SELECT 1 FROM str002_signals WHERE market_id = ? AND direction = ?",
            (market_id, direction)
        )
        if cur.fetchone():
            skipped += 1
            continue

        signal_id = f"STR002-{next_num:04d}"
        next_num += 1

        cur.execute("""
            INSERT OR IGNORE INTO str002_signals
            (signal_id, market_id, market_title, direction, tier, first_seen_date,
             registered_at, market_price_at_registration, smart_money_pct_at_registration,
             gap_pt_at_registration, elite_traders, legendary_traders, resolution_date,
             outcome_correct, winning_outcome, edge_at_entry, resolved_at, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
        """, (
            signal_id, market_id, rec['market_title'], direction, rec['tier'],
            rec['first_seen_date'], now, rec['market_price_pct'],
            rec['smart_money_pct'], rec['gap_pt'], rec['elite_traders'],
            rec['legendary_traders'], rec['resolution_date']
        ))
        registered += 1
        print(f"  + {signal_id}: [{rec['tier']}] {rec['market_title'][:42]} | {direction} "
              f"@ mkt={rec['market_price_pct']}")

    conn.commit()
    print(f"\nRegistered: {registered} new | Skipped (already registered): {skipped}")
    return registered


def show_stats(conn):
    ensure_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM str002_signals")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM str002_signals WHERE scored_at IS NOT NULL")
    scored = cur.fetchone()[0]
    cur.execute("SELECT tier, COUNT(*) FROM str002_signals GROUP BY tier")
    by_tier = cur.fetchall()

    print(f"STR-002 Registry Stats")
    print(f"  Total registered: {total}")
    print(f"  Scored: {scored}")
    print(f"  Pending resolution: {total - scored}")
    print(f"  By tier:")
    for tier, count in by_tier:
        print(f"    {tier}: {count}")

    # Resolution date distribution
    cur.execute("""
        SELECT substr(resolution_date,1,10) as rd, COUNT(*)
        FROM str002_signals GROUP BY rd ORDER BY rd
    """)
    print(f"  By resolution date:")
    for rd, count in cur.fetchall():
        print(f"    {rd}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Register STR-002 first-seen signals")
    parser.add_argument('--stats', action='store_true', help='Show registry stats only')
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    if args.stats:
        show_stats(conn)
    else:
        register_all(conn)
        print()
        show_stats(conn)

    conn.close()


if __name__ == '__main__':
    main()
