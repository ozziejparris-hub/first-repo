#!/usr/bin/env python3
"""
snapshot_elo_scores.py

Writes an immutable daily snapshot of all Pool C trader state to the elo_snapshots table.
This is the temporal memory layer for the system — it preserves the state of every trader
on every day so that historical questions can be answered:
  - What was a trader's geo_elo_active on date X?
  - Who was LEGENDARY on the day a signal fired?
  - How has a trader's archetype migrated over time?

DESIGN PRINCIPLES:
- APPEND-ONLY. Snapshots are never modified once written. The composite PK (snapshot_date,
  address) enforces one row per trader per day.
- IDEMPOTENT. Running twice on the same day is a no-op (INSERT OR IGNORE).
- FULL POOL C. Captures every geo_accuracy_pool=1 trader, not just LEGENDARY — we do not
  know in advance which traders will matter.

Runs daily in maintenance between step 18 (resync_position_counts) and step 19
(write_integration_health). Non-blocking.

Usage:
  python3 snapshot_elo_scores.py              # snapshot today
  python3 snapshot_elo_scores.py --date YYYY-MM-DD   # snapshot specific date (testing)
  python3 snapshot_elo_scores.py --stats      # show snapshot history stats
"""

import sqlite3
import json
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')
PROFILE_INDEX = '/home/parison/trading-swarm/brain/trader-profiles/_index.json'


def ensure_table(conn):
    """Create the elo_snapshots table if it doesn't exist."""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS elo_snapshots (
        snapshot_date              TEXT NOT NULL,
        address                    TEXT NOT NULL,
        geo_elo                    REAL,
        geo_elo_active             REAL,
        comprehensive_elo          REAL,
        geo_accuracy_pool          INTEGER,
        research_excluded          INTEGER,
        bot_type                   TEXT,
        geo_resolved_trades_count  INTEGER,
        geo_directionality_score   REAL,
        tier                       TEXT,
        archetype                  TEXT,
        PRIMARY KEY (snapshot_date, address)
    )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_date ON elo_snapshots(snapshot_date)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_addr ON elo_snapshots(address)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_tier ON elo_snapshots(snapshot_date, tier)')
    conn.commit()


def derive_tier(geo_elo_active, geo_accuracy_pool, research_excluded, bot_type):
    """Derive tier from current state. Matches canonical definitions."""
    if geo_elo_active is None:
        return 'UNRANKED'
    clean = (geo_accuracy_pool == 1 and research_excluded == 0 and bot_type is None)
    if geo_elo_active >= 2175 and clean:
        return 'LEGENDARY'
    if geo_elo_active >= 1800 and clean:
        return 'NEAR_LEGENDARY'
    if geo_elo_active >= 1400:
        return 'ELITE'
    if geo_elo_active >= 1000:
        return 'QUALIFIED'
    return 'DEVELOPING'


def load_archetypes():
    """Load archetype lookup from profile index."""
    if not os.path.exists(PROFILE_INDEX):
        return {}
    try:
        with open(PROFILE_INDEX) as f:
            idx = json.load(f)
        return {addr: data.get('archetype') for addr, data in idx.items()}
    except Exception:
        return {}


def run_snapshot(snapshot_date=None, verbose=True):
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    ensure_table(conn)
    cur = conn.cursor()

    # Idempotency check
    cur.execute('SELECT COUNT(*) FROM elo_snapshots WHERE snapshot_date = ?', (snapshot_date,))
    existing = cur.fetchone()[0]
    if existing > 0:
        if verbose:
            print(f"Snapshot for {snapshot_date} already exists ({existing} rows). Skipping (idempotent).")
        conn.close()
        return existing

    archetypes = load_archetypes()

    # Pull all Pool C traders
    cur.execute('''
        SELECT address, geo_elo, geo_elo_active, comprehensive_elo,
               geo_accuracy_pool, research_excluded, bot_type,
               geo_resolved_trades_count, geo_directionality_score
        FROM traders
        WHERE geo_accuracy_pool = 1
    ''')
    rows = cur.fetchall()

    if verbose:
        print(f"Snapshotting {len(rows)} Pool C traders for {snapshot_date}...")

    snapshot_rows = []
    for r in rows:
        (address, geo_elo, geo_elo_active, comprehensive_elo,
         geo_accuracy_pool, research_excluded, bot_type,
         geo_resolved_trades_count, geo_directionality_score) = r
        tier = derive_tier(geo_elo_active, geo_accuracy_pool, research_excluded, bot_type)
        archetype = archetypes.get(address)
        snapshot_rows.append((
            snapshot_date, address, geo_elo, geo_elo_active, comprehensive_elo,
            geo_accuracy_pool, research_excluded, bot_type,
            geo_resolved_trades_count, geo_directionality_score, tier, archetype
        ))

    conn.executemany('''
        INSERT OR IGNORE INTO elo_snapshots
        (snapshot_date, address, geo_elo, geo_elo_active, comprehensive_elo,
         geo_accuracy_pool, research_excluded, bot_type,
         geo_resolved_trades_count, geo_directionality_score, tier, archetype)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', snapshot_rows)
    conn.commit()

    # Report tier distribution
    cur.execute('''
        SELECT tier, COUNT(*) FROM elo_snapshots
        WHERE snapshot_date = ? GROUP BY tier ORDER BY COUNT(*) DESC
    ''', (snapshot_date,))
    if verbose:
        print(f"Snapshot written. Tier distribution:")
        for tier, cnt in cur.fetchall():
            print(f"  {tier}: {cnt}")

    conn.close()
    return len(snapshot_rows)


def show_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='elo_snapshots'")
    if not cur.fetchone():
        print("No elo_snapshots table exists yet.")
        conn.close()
        return
    cur.execute('''
        SELECT snapshot_date, COUNT(*) as traders,
               SUM(CASE WHEN tier='LEGENDARY' THEN 1 ELSE 0 END) as legendary,
               SUM(CASE WHEN tier='NEAR_LEGENDARY' THEN 1 ELSE 0 END) as near_leg
        FROM elo_snapshots
        GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 30
    ''')
    print("Snapshot history (most recent 30 days):")
    print(f"{'Date':<12} {'Pool C':>8} {'LEGENDARY':>10} {'NEAR_LEG':>9}")
    for r in cur.fetchall():
        print(f"{r[0]:<12} {r[1]:>8} {r[2]:>10} {r[3]:>9}")
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='Snapshot date YYYY-MM-DD (default: today)')
    parser.add_argument('--stats', action='store_true', help='Show snapshot history stats')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        count = run_snapshot(snapshot_date=args.date)
        print(f"snapshot_elo_scores: {count} rows for {args.date or datetime.now().strftime('%Y-%m-%d')}")
