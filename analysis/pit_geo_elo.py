#!/usr/bin/env python3
"""
Point-in-time (PIT) reconstruction of geo_elo / geo_elo_active / geo_accuracy_pool.

B1a — the core of the PIT replay engine. Given a timestamp T, reconstructs what
scripts/update_geo_elo.py + monitoring/column_definitions.py would have written
for each trader had they run at exactly T, instead of "now".

This module does NOT reimplement the ELO formula. _compute_geo_elo and
_compute_geo_directionality are imported directly from scripts/update_geo_elo.py
so formula fidelity is guaranteed by construction — B1a's job is bounding the
INPUT to that formula to "as of T", not touching the math.

Three correctness guards (see brain/decisions B1a record for full detail):
  1. T must be the exact write-time of the target snapshot's underlying
     update_geo_elo.py run (sourced from logs/daily_maintenance.log), not the
     snapshot's calendar date.
  2. A market counts as resolved-as-of-T only if its trade-tape-end
     (MAX(trades.timestamp) for that market_id, computed unbounded) is <= T.
     This is the O-36 workaround: markets.resolution_date is not trusted.
  3. trade_gap_flag exclusion (the O-37 quarantine) is applied at its CURRENT
     state regardless of T — replay reflects the corrected baseline at every
     T, not "what was known then".

Read-only. No writes to the database.
"""

import os
import sys
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.update_geo_elo import _compute_geo_elo, _compute_geo_directionality
import monitoring.column_definitions as cd


def _to_utc(T) -> datetime:
    """Accept a datetime or ISO string; return a tz-aware UTC datetime."""
    if isinstance(T, datetime):
        dt = T
    else:
        dt = datetime.fromisoformat(str(T).replace('Z', '+00:00').replace(' ', 'T'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _t_sql(T: datetime) -> str:
    """SQLite-comparable string form of T (matches trades.timestamp text format)."""
    return T.strftime('%Y-%m-%d %H:%M:%S')


_TAPE_END_READY = set()


def _ensure_tape_end_temp_table(conn) -> None:
    """
    Materialize per-market trade-tape-end into a TEMP table once per connection,
    so repeated per-trader lookups don't re-aggregate the full trades table
    (9M+ rows) on every call. tape_end itself remains globally computed and
    unbounded by any T — see module docstring / guard #2.
    """
    key = id(conn)
    if key in _TAPE_END_READY:
        return
    conn.execute("DROP TABLE IF EXISTS temp.tape_end")
    conn.execute("""
        CREATE TEMP TABLE tape_end AS
        SELECT market_id, MAX(timestamp) AS tape_end FROM trades GROUP BY market_id
    """)
    conn.execute("CREATE INDEX idx_tmp_tape_end ON tape_end(market_id)")
    _TAPE_END_READY.add(key)


def _fetch_qualifying_trades_at(conn, address: str, t_sql: str) -> list:
    """
    Same qualifying-trade definition as update_geo_elo.py:_fetch_qualifying_trades,
    with resolution-as-of-T (guard #2) replacing the implicit "resolved now" bound.

    tape_end is computed UNBOUNDED (global MAX per market_id) and only the
    COMPARISON (tape_end <= T) is bounded — bounding the MAX itself would
    misclassify a still-open market's most-recent-pre-T trade as a real
    tape-end.
    """
    _ensure_tape_end_temp_table(conn)
    return conn.execute("""
        SELECT tr.outcome_bet, tr.price, tr.trade_result, tr.market_id, tr.shares, tr.timestamp
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        JOIN tape_end tape ON tape.market_id = tr.market_id
        WHERE tr.trader_address = ?
          AND m.category IN ('Geopolitics', 'Elections')
          AND tr.trade_result IN ('won', 'lost')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tr.price BETWEEN 0.10 AND 0.80
          AND tape.tape_end <= ?
        ORDER BY tr.timestamp ASC
    """, (address, t_sql)).fetchall()


def _canonical_count_at(conn, address: str, t_sql: str) -> int:
    """Mirrors update_geo_elo.py's canonical_count query, bounded by tape_end<=T."""
    _ensure_tape_end_temp_table(conn)
    row = conn.execute("""
        SELECT COUNT(DISTINCT tr.market_id)
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        JOIN tape_end tape ON tape.market_id = tr.market_id
        WHERE tr.trader_address = ?
          AND tr.trade_result IN ('won', 'lost')
          AND m.category IN ('Geopolitics', 'Elections')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          AND tape.tape_end <= ?
    """, (address, t_sql)).fetchone()
    return row[0] if row else 0


def _last_any_trade_at(conn, address: str, t_sql: str) -> Optional[str]:
    """
    Mirrors update_geo_elo.py's last_any_trade query for decay-recency.
    Faithfully replicates its quirks: uses tr.market_category (not m.category)
    and does NOT filter trade_gap_flag — reproducing the existing formula's
    input exactly, not correcting it.
    """
    row = conn.execute("""
        SELECT MAX(tr.timestamp)
        FROM trades tr
        JOIN markets m ON m.market_id = tr.market_id
        WHERE tr.trader_address = ?
          AND tr.market_category IN ('Geopolitics', 'Elections')
          AND tr.timestamp <= ?
    """, (address, t_sql)).fetchone()
    return row[0] if row else None


def _compute_geo_elo_active_at(geo_elo: Optional[float], last_trade_ts: Optional[str],
                                T: datetime) -> Optional[float]:
    """
    T-parametrized twin of column_definitions.compute_geo_elo_active.
    Same formula (geo_elo * 0.5**(days_dormant/180)), days_dormant measured
    against T instead of datetime.now(timezone.utc).
    """
    if last_trade_ts is None or geo_elo is None:
        return None
    try:
        ts = last_trade_ts.replace('Z', '+00:00').replace(' ', 'T')
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_dormant = (T - last).days
        decay = 0.5 ** (days_dormant / 180.0)
        return round(geo_elo * decay, 4)
    except Exception:
        return None


def _pool_c_gate(geo_elo, geo_elo_active, geo_resolved_trades_count,
                  geo_directionality_score, bot_type, wash_trade_suspect,
                  bot_suspect) -> bool:
    """
    Pure-Python re-implementation of monitoring.column_definitions.POOL_C_GATE_WHERE.
    Re-implemented (not called) because refresh_pool_c() is DB-mutating and B1a
    is read-only. Must match the SQL predicate exactly:

        geo_elo IS NOT NULL
        AND geo_elo_active >= GEO_ELO_POOL_SANITY_FLOOR
        AND geo_resolved_trades_count >= POOL_C_MIN_RESOLVED_TRADES
        AND geo_directionality_score IS NOT NULL
        AND bot_type IS NULL
        AND (wash_trade_suspect = 0 OR wash_trade_suspect IS NULL)
        AND (bot_suspect = 0 OR bot_suspect IS NULL)
    """
    if geo_elo is None:
        return False
    if geo_elo_active is None or geo_elo_active < cd.GEO_ELO_POOL_SANITY_FLOOR:
        return False
    if geo_resolved_trades_count is None or geo_resolved_trades_count < cd.POOL_C_MIN_RESOLVED_TRADES:
        return False
    if geo_directionality_score is None:
        return False
    if bot_type is not None:
        return False
    if wash_trade_suspect not in (0, None):
        return False
    if bot_suspect not in (0, None):
        return False
    return True


def reconstruct_one_at(conn, address: str, T) -> Dict:
    """Reconstruct one trader's geo_elo state as of T. Read-only."""
    T = _to_utc(T)
    t_sql = _t_sql(T)

    trades = _fetch_qualifying_trades_at(conn, address, t_sql)
    n = len(trades)

    if n < 5:  # MIN_TRADES_FOR_ELO, per update_geo_elo.py
        geo_elo = None
        directionality = None
    else:
        geo_elo = _compute_geo_elo(trades)
        directionality = _compute_geo_directionality(trades)

    last_any_trade = _last_any_trade_at(conn, address, t_sql)
    geo_elo_active = _compute_geo_elo_active_at(geo_elo, last_any_trade, T)
    canonical_count = _canonical_count_at(conn, address, t_sql)

    row = conn.execute(
        "SELECT bot_type, wash_trade_suspect, bot_suspect FROM traders WHERE address = ?",
        (address,)
    ).fetchone()
    bot_type, wash_trade_suspect, bot_suspect = row if row else (None, None, None)

    geo_accuracy_pool = _pool_c_gate(
        geo_elo, geo_elo_active, canonical_count, directionality,
        bot_type, wash_trade_suspect, bot_suspect
    )

    return {
        'geo_elo': geo_elo,
        'geo_elo_active': geo_elo_active,
        'geo_directionality_score': directionality,
        'geo_resolved_trades_count': canonical_count,
        'geo_accuracy_pool': 1 if geo_accuracy_pool else 0,
    }


def reconstruct_geo_elo_at(conn, T, addresses: Iterable[str]) -> Dict[str, Dict]:
    """Reconstruct geo_elo state as of T for a given set of trader addresses."""
    T = _to_utc(T)
    return {addr: reconstruct_one_at(conn, addr, T) for addr in addresses}
