#!/usr/bin/env python3
"""
B1a validation harness — PIT geo_elo reconstruction (analysis/pit_geo_elo.py).

Read-only. Three checks:

  Part 1 (primary): reconstruct_geo_elo_at(now) vs a direct, independent,
    right-now production computation (production's own _fetch_qualifying_trades /
    _compute_geo_elo / compute_geo_elo_active — NOT the stored traders.geo_elo
    column, which was proven stale/frozen-since-06-18 for most traders in the
    Stage 2 investigation). Also a whole-table gate-logic fidelity check
    (_pool_c_gate vs stored geo_accuracy_pool, zero confound from staleness).

  Part 2 (secondary): past-T validation restricted to the "provably fresh"
    subset of the 07-20/07-21 elo_snapshots — traders whose stored geo_elo was
    actually last-changed on that exact snapshot date, i.e. the only rows
    where the snapshot is a legitimate as-of-T oracle.

No writes.
"""

import os
import sys
import sqlite3
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.pit_geo_elo import (
    reconstruct_one_at, _fetch_qualifying_trades_at, _canonical_count_at,
    _last_any_trade_at, _compute_geo_elo_active_at, _pool_c_gate, _to_utc, _t_sql,
    _ensure_tape_end_temp_table,
)
from scripts.update_geo_elo import _fetch_qualifying_trades, _compute_geo_elo, _compute_geo_directionality
import monitoring.column_definitions as cd

DB_PATH = 'data/polymarket_tracker.db'
EPS = 1e-6


def classify(a, b):
    if a is None and b is None:
        return 'exact'
    if a is None or b is None:
        return 'diverge'
    d = abs(a - b)
    if d == 0:
        return 'exact'
    if d < EPS:
        return 'epsilon'
    return 'diverge'


def production_now(conn, address):
    """Direct, independent, unwrapped production computation — right now."""
    trades = _fetch_qualifying_trades(conn, address)
    n = len(trades)
    if n < 5:
        geo_elo = None
        directionality = None
    else:
        geo_elo = _compute_geo_elo(trades)
        directionality = _compute_geo_directionality(trades)

    last_any_trade = conn.execute("""
        SELECT MAX(tr.timestamp)
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trader_address = ?
        AND tr.market_category IN ('Geopolitics', 'Elections')
        AND tr.timestamp <= datetime('now')
    """, (address,)).fetchone()[0]
    geo_elo_active = cd.compute_geo_elo_active(geo_elo, last_any_trade)

    canonical_count = conn.execute("""
        SELECT COUNT(DISTINCT tr.market_id)
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trader_address = ?
          AND tr.trade_result IN ('won', 'lost')
          AND m.category IN ('Geopolitics', 'Elections')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """, (address,)).fetchone()[0]

    row = conn.execute(
        "SELECT bot_type, wash_trade_suspect, bot_suspect FROM traders WHERE address = ?",
        (address,)
    ).fetchone()
    bot_type, wash_trade_suspect, bot_suspect = row if row else (None, None, None)
    pool = _pool_c_gate(geo_elo, geo_elo_active, canonical_count, directionality,
                         bot_type, wash_trade_suspect, bot_suspect)

    return {
        'geo_elo': geo_elo,
        'geo_elo_active': geo_elo_active,
        'geo_directionality_score': directionality,
        'geo_resolved_trades_count': canonical_count,
        'geo_accuracy_pool': 1 if pool else 0,
    }


def part1(conn):
    print("=" * 78)
    print("PART 1 (PRIMARY): reconstruct_geo_elo_at(now) vs direct production-now")
    print("=" * 78)

    # --- 1a. whole-table gate-logic fidelity (zero confound) ---
    rows = conn.execute("""
        SELECT geo_elo, geo_elo_active, geo_resolved_trades_count,
               geo_directionality_score, bot_type, wash_trade_suspect,
               bot_suspect, geo_accuracy_pool
        FROM traders
    """).fetchall()
    gate_total = len(rows)
    gate_mismatch = 0
    for r in rows:
        (geo_elo, geo_elo_active, count, direc, bot_type, wash, bot_susp, stored_pool) = r
        computed = 1 if _pool_c_gate(geo_elo, geo_elo_active, count, direc, bot_type, wash, bot_susp) else 0
        if computed != (stored_pool or 0):
            gate_mismatch += 1
    print(f"\n[1a] Pool-gate logic fidelity, whole traders table ({gate_total} rows):")
    print(f"     mismatches vs stored geo_accuracy_pool: {gate_mismatch}")

    # --- 1b. end-to-end reconstruct_geo_elo_at(now) vs production-now ---
    addrs = [r[0] for r in conn.execute(
        "SELECT address FROM elo_snapshots WHERE snapshot_date='2026-07-21'"
    ).fetchall()]

    T_now = datetime.now(timezone.utc)
    print(f"\n[1b] End-to-end reconstruction, {len(addrs)} clean-subset (07-21) traders, T_now={T_now.isoformat()}")

    _ensure_tape_end_temp_table(conn)  # warm once

    fields = ['geo_elo', 'geo_elo_active', 'geo_directionality_score', 'geo_resolved_trades_count', 'geo_accuracy_pool']
    counts = {f: {'exact': 0, 'epsilon': 0, 'diverge': 0} for f in fields}
    divergences = []

    t0 = time.time()
    for addr in addrs:
        mine = reconstruct_one_at(conn, addr, T_now)
        prod = production_now(conn, addr)

        for f in fields:
            if f == 'geo_resolved_trades_count' or f == 'geo_accuracy_pool':
                cls = 'exact' if mine[f] == prod[f] else 'diverge'
            else:
                cls = classify(mine[f], prod[f])
            counts[f][cls] += 1
            if cls == 'diverge':
                divergences.append((addr, f, mine[f], prod[f]))
    dt = time.time() - t0
    print(f"     done in {dt:.1f}s")

    for f in fields:
        c = counts[f]
        print(f"     {f:28s} exact={c['exact']:4d}  epsilon={c['epsilon']:4d}  diverge={c['diverge']:4d}")

    if divergences:
        print(f"\n     First {min(20,len(divergences))} of {len(divergences)} divergence rows:")
        for addr, f, mv, pv in divergences[:20]:
            print(f"       {addr}  {f}: mine={mv!r} prod={pv!r}")

    return divergences, addrs, T_now


def find_fresh_subset(conn, snapshot_date):
    """
    Traders whose stored geo_elo on `snapshot_date` was actually LAST CHANGED
    on that exact date (not carried forward stale from an earlier date) —
    the only rows where the snapshot is a legitimate as-of-T oracle.
    """
    rows = conn.execute("""
        WITH ordered AS (
          SELECT address, snapshot_date, geo_elo,
                 LAG(geo_elo) OVER (PARTITION BY address ORDER BY snapshot_date) AS prev_geo_elo,
                 LAG(snapshot_date) OVER (PARTITION BY address ORDER BY snapshot_date) AS prev_date
          FROM elo_snapshots
        )
        SELECT address FROM ordered
        WHERE snapshot_date = ?
          AND (prev_geo_elo IS NULL OR geo_elo != prev_geo_elo)
    """, (snapshot_date,)).fetchall()
    return [r[0] for r in rows]


def part2(conn):
    print("\n" + "=" * 78)
    print("PART 2 (SECONDARY): past-T validation on the provably-fresh subset")
    print("=" * 78)

    write_times = {
        '2026-07-21': '2026-07-21T06:01:54Z',
        '2026-07-20': '2026-07-20T06:01:53Z',
    }

    for date, T_str in write_times.items():
        fresh = find_fresh_subset(conn, date)
        total = conn.execute("SELECT COUNT(*) FROM elo_snapshots WHERE snapshot_date=?", (date,)).fetchone()[0]
        print(f"\n[{date}] fresh (last-changed-on-this-date) subset: {len(fresh)} / {total} total")

        if not fresh:
            print("     (empty — nothing to validate for this date)")
            continue

        counts = {'exact': 0, 'epsilon': 0, 'diverge': 0}
        divergences = []
        for addr in fresh:
            recon = reconstruct_one_at(conn, addr, T_str)
            stored = conn.execute("""
                SELECT geo_elo, geo_elo_active, geo_resolved_trades_count, geo_accuracy_pool
                FROM elo_snapshots WHERE address=? AND snapshot_date=?
            """, (addr, date)).fetchone()
            s_geo_elo, s_active, s_count, s_pool = stored

            cls_elo = classify(recon['geo_elo'], s_geo_elo)
            cls_active = classify(recon['geo_elo_active'], s_active)
            count_match = recon['geo_resolved_trades_count'] == s_count
            pool_match = recon['geo_accuracy_pool'] == s_pool

            overall = 'exact' if (cls_elo == 'exact' and cls_active == 'exact' and count_match and pool_match) else \
                      ('epsilon' if cls_elo in ('exact', 'epsilon') and cls_active in ('exact', 'epsilon')
                       and count_match and pool_match else 'diverge')
            counts[overall] += 1
            if overall == 'diverge':
                divergences.append((addr, recon, stored))

        print(f"     match: exact={counts['exact']}  epsilon={counts['epsilon']}  diverge={counts['diverge']}")
        if divergences:
            print(f"     divergences ({len(divergences)}):")
            for addr, recon, stored in divergences[:10]:
                print(f"       {addr}")
                print(f"         stored     : geo_elo={stored[0]!r} active={stored[1]!r} count={stored[2]} pool={stored[3]}")
                print(f"         reconstruct: geo_elo={recon['geo_elo']!r} active={recon['geo_elo_active']!r} count={recon['geo_resolved_trades_count']} pool={recon['geo_accuracy_pool']}")


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')

    part1(conn)
    part2(conn)

    conn.close()
