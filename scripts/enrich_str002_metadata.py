#!/usr/bin/env python3
"""
enrich_str002_metadata.py — add classification metadata to STR-002 signals.

Adds three derived fields used by both the research track and the STR-003
confirmation check:
  - has_proven_trader: 1 if any ELITE or LEGENDARY trader on the signal side
                       (elite_traders > 0 OR legendary_traders > 0)
  - regime: market-price band at registration —
            CONTESTED (0.20-0.80), NEAR_RESOLVED (>=0.90 or <=0.10), MID (else)
  - event_cluster: groups correlated markets (Iran peace deal variants, Fed
                   variants, Peru candidates) so correlated signals count as
                   ~1 observation, not N

These tags let us:
  1. Filter the research analysis by tier x regime x proven-trader
  2. Drive the STR-002 -> STR-003 confirmation flag (proven-trader contested signals)
  3. Deflate n for correlated signals in accuracy metrics

Idempotent. Run after register_str002_signals.py.

Usage:
  python3 enrich_str002_metadata.py
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")


def ensure_columns(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(str002_signals)")
    cols = {r[1] for r in cur.fetchall()}
    for col, decl in [
        ('has_proven_trader', 'INTEGER'),
        ('regime', 'TEXT'),
        ('event_cluster', 'TEXT'),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE str002_signals ADD COLUMN {col} {decl}")
            print(f"Added column: {col}")
    conn.commit()


def compute_regime(price):
    if price is None:
        return None
    if price >= 0.90 or price <= 0.10:
        return 'NEAR_RESOLVED'
    if 0.20 <= price <= 0.80:
        return 'CONTESTED'
    return 'MID'


def compute_event_cluster(title):
    """Derive an event cluster key from the market title.
    Groups correlated markets so they count as ~1 observation."""
    t = (title or '').lower()
    # Iran peace deal / agreement variants
    if 'iran' in t and ('peace deal' in t or 'agreement' in t or 'ceasefire' in t):
        return 'iran_us_peace_2026'
    # Iran airspace variants
    if 'iran' in t and 'airspace' in t:
        return 'iran_airspace_2026'
    # Israel airspace variants
    if 'israel' in t and 'airspace' in t:
        return 'israel_airspace_2026'
    # Strait of Hormuz
    if 'hormuz' in t:
        return 'hormuz_2026'
    # Fed June 2026 decision variants
    if 'fed' in t and ('interest rate' in t or 'pause' in t or 'bps' in t):
        return 'fed_june_2026'
    # Peru 2026 presidential candidates
    if 'peruvian' in t or ('peru' in t and 'win' in t):
        return 'peru_president_2026'
    # Maine 2026 governor primary candidates
    if 'maine governor' in t:
        return 'maine_governor_2026'
    # South Carolina 2026 governor primary
    if 'south carolina governor' in t:
        return 'sc_governor_2026'
    # Colombia 2026 candidates
    if 'colombia' in t or 'colom' in t:
        return 'colombia_2026'
    # Lebanon ceasefire
    if 'lebanon' in t:
        return 'lebanon_ceasefire_2026'
    # Default: no cluster (standalone)
    return None


def enrich(conn):
    ensure_columns(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT signal_id, market_title, market_price_at_registration,
               elite_traders, legendary_traders
        FROM str002_signals
    """)
    rows = cur.fetchall()

    updated = 0
    for signal_id, title, price, elite, legendary in rows:
        has_proven = 1 if ((elite or 0) > 0 or (legendary or 0) > 0) else 0
        regime = compute_regime(price)
        cluster = compute_event_cluster(title)

        cur.execute("""
            UPDATE str002_signals
            SET has_proven_trader = ?, regime = ?, event_cluster = ?
            WHERE signal_id = ?
        """, (has_proven, regime, cluster, signal_id))
        updated += 1

    conn.commit()
    print(f"Enriched {updated} signals\n")

    # Report the resulting distribution
    print("=== TIER x REGIME x PROVEN-TRADER DISTRIBUTION ===")
    cur.execute("""
        SELECT tier, regime, has_proven_trader, COUNT(*)
        FROM str002_signals
        GROUP BY tier, regime, has_proven_trader
        ORDER BY tier, regime
    """)
    for tier, regime, proven, count in cur.fetchall():
        proven_str = 'PROVEN' if proven else 'unproven'
        print(f"  {tier:10} / {regime or 'NULL':13} / {proven_str:8}: {count}")

    print("\n=== EVENT CLUSTERS (correlated signal groups) ===")
    cur.execute("""
        SELECT event_cluster, COUNT(*)
        FROM str002_signals
        WHERE event_cluster IS NOT NULL
        GROUP BY event_cluster ORDER BY COUNT(*) DESC
    """)
    for cluster, count in cur.fetchall():
        print(f"  {cluster}: {count} signals")
    cur.execute("SELECT COUNT(*) FROM str002_signals WHERE event_cluster IS NULL")
    standalone = cur.fetchone()[0]
    print(f"  (standalone, no cluster): {standalone}")

    # The key cell for the thesis
    print("\n=== THE THESIS CELL: proven trader + contested market ===")
    cur.execute("""
        SELECT signal_id, tier, direction, market_price_at_registration, market_title
        FROM str002_signals
        WHERE has_proven_trader = 1 AND regime = 'CONTESTED'
    """)
    thesis = cur.fetchall()
    if thesis:
        for r in thesis:
            print(f"  {r[0]} [{r[1]}] {r[2]} @ {r[3]:.3f} | {r[4][:40]}")
    else:
        print("  (none yet — this is the gap the redesign targets)")
    print(f"  Total in thesis cell: {len(thesis)}")


def main():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    enrich(conn)
    conn.close()


if __name__ == '__main__':
    main()
