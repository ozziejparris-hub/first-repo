#!/usr/bin/env python3
"""
Point-in-time (PIT) reconstruction of trader positions as of a timestamp T.

B1b-positions — stage 1 of B1b (the price-at-T counterpart follows separately
as B1b-prices). Given T, reconstructs what each trader's positions would look
like had position matching run at exactly T instead of "now": which are open,
which are closed, which are partially closed, and at what size.

This module does NOT reimplement position matching. PositionTracker._match_group
/ _match_group_simplified and Position.close_position (monitoring/position_tracker.py)
are imported and called unchanged — matching-algorithm fidelity is guaranteed by
construction. This module's job is bounding the INPUT (which trades are visible
as of T) and correcting the synthetic-close timestamp source, not touching the
matching math. Same division of labor as analysis/pit_geo_elo.py (B1a).

Two correctness properties, carried over from B1a:

  1. Trades are bounded to timestamp <= T before being fed to the matcher.
     Every resulting entry_timestamp, and every exit_timestamp from a real
     SELL trade, is therefore <= T by construction. The open-at-T predicate
     scoping approved —

         entry_timestamp <= T AND (exit_timestamp IS NULL OR exit_timestamp > T)

     — falls out for free rather than being applied as a separate filter over
     a stored table: a position left in status 'open' or 'partially_closed'
     after a T-bounded replay has, by definition, no real exit <= T.

  2. A market counts as resolved-as-of-T only if its trade-tape-end
     (MAX(trades.timestamp) for that market_id, computed unbounded) is <= T.
     This is the same O-36 workaround B1a uses (markets.resolution_date is
     not trusted as a close-time source), imported directly from
     analysis.pit_geo_elo, not rebuilt.

SYNTHETIC-CLOSE TIMESTAMP IS A BOUND, NOT AN INSTANT: when a position is still
open after the real-trade replay and its market has resolved as of T, this
module closes it at tape_end rather than markets.resolution_date (O-36:
resolution_date is unreliable — up to >14 days late on ~5.6% of geo/elec
markets, and occasionally precedes the tape entirely). tape_end only certifies
"this market had stopped trading by here," not "the position closed at this
exact moment." That is sufficient to answer "was this position open at T" —
the question this module exists to answer — but the resulting exit_timestamp
must NOT be treated as a precise close time, and must not be used to compute
holding-period/timing metrics that assume an exact instant.

KNOWN, DELIBERATE DIVERGENCE FROM "FULL CORRECTNESS": production's own
PositionTracker.apply_synthetic_closes only synthetically closes positions
with status == 'open' — it skips 'partially_closed' positions, leaving their
remaining shares stale in resolved markets (trading-swarm ledger O-41). This
module preserves that exact behavior rather than fixing it, so that a T=now
reconstruction stays a clean, comparable twin of the live positions table —
fixing it here would make this module diverge from production even at T=now,
breaking the validation anchor. Not a bug in this file; a deliberate,
recorded scope boundary (see O-41).

Read-only. No writes to the database.
"""

import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.position_tracker import PositionTracker
from analysis.pit_geo_elo import _to_utc, _t_sql, _ensure_tape_end_temp_table

# PositionTracker._match_group / _match_group_simplified never touch self.db —
# they're pure functions of the trade list passed in. One throwaway instance
# is safe to share across every reconstruction in a process.
_TRACKER = PositionTracker(database=None)


def _fetch_trades_at(conn, address: str, t_sql: str) -> Dict[tuple, List[Dict]]:
    """
    Trades for one trader bounded to timestamp <= T, grouped by (market_id,
    outcome) — the same grouping PositionTracker.match_trades_for_trader does
    internally, minus the unbounded query it hardcodes (that query has no T
    param, so match_trades_for_trader can't be called directly for a bounded
    replay — this is the new code the T-bound actually lives in).
    """
    rows = conn.execute("""
        SELECT trade_id, market_id, market_title, outcome, shares, price, side, timestamp
        FROM trades
        WHERE trader_address = ? AND timestamp <= ?
        ORDER BY timestamp ASC
    """, (address, t_sql)).fetchall()

    grouped: Dict[tuple, List[Dict]] = defaultdict(list)
    for trade_id, market_id, market_title, outcome, shares, price, side, timestamp in rows:
        if market_id is None:
            continue
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        grouped[(market_id, outcome)].append({
            'trade_id': trade_id,
            'market_title': market_title,
            'shares': shares,
            'price': price,
            'side': side,
            'timestamp': timestamp,
        })
    return grouped


def _apply_synthetic_closes_at(positions: List, conn, t_sql: str) -> int:
    """
    Synthetically close positions still 'open' after the T-bounded real-trade
    replay, for markets resolved as of T (tape_end <= T). See module docstring
    for why tape_end (not resolution_date) is used, and why it's a bound, not
    an exact close instant. Mirrors PositionTracker.apply_synthetic_closes'
    winning/losing $1.00/$0.00 pricing exactly; only the eligibility gate
    (tape_end <= T instead of "resolved now") and the timestamp source differ.

    Deliberately, like production, only touches status == 'open' positions —
    'partially_closed' positions are left as-is. See O-41 (trading-swarm
    ledger) and the module docstring's "known divergence" section.
    """
    open_positions = [p for p in positions if p.status == 'open']
    if not open_positions:
        return 0

    _ensure_tape_end_temp_table(conn)
    market_ids = list({p.market_id for p in open_positions})
    placeholders = ','.join('?' for _ in market_ids)
    rows = conn.execute(f"""
        SELECT m.market_id, m.winning_outcome, tape.tape_end
        FROM markets m
        JOIN tape_end tape ON tape.market_id = m.market_id
        WHERE m.market_id IN ({placeholders})
          AND m.resolved = 1
          AND m.winning_outcome IS NOT NULL AND m.winning_outcome != ''
          AND tape.tape_end <= ?
    """, (*market_ids, t_sql)).fetchall()
    resolved_by_t = {mid: (winning, tape_end) for mid, winning, tape_end in rows}

    applied = 0
    for pos in open_positions:
        if pos.market_id not in resolved_by_t:
            continue
        winning_outcome, tape_end_raw = resolved_by_t[pos.market_id]
        tape_end_dt = (
            datetime.fromisoformat(tape_end_raw)
            if isinstance(tape_end_raw, str) else tape_end_raw
        )

        pos_outcome = (pos.outcome or '').strip().lower()
        win_outcome = (winning_outcome or '').strip().lower()
        close_price = 1.0 if pos_outcome == win_outcome else 0.0

        pos.close_position(
            exit_shares=pos.remaining_shares,
            exit_avg_price=close_price,
            exit_timestamp=tape_end_dt,
            exit_trade_ids=[],
        )
        pos.is_synthetic_close = True
        applied += 1
    return applied


def reconstruct_one_at(conn, address: str, T) -> List[Dict]:
    """Reconstruct one trader's positions as of T. Read-only."""
    T = _to_utc(T)
    t_sql = _t_sql(T)

    grouped = _fetch_trades_at(conn, address, t_sql)
    positions = []
    for (market_id, outcome), trades in grouped.items():
        positions.extend(_TRACKER._match_group(address, market_id, outcome, trades))

    _apply_synthetic_closes_at(positions, conn, t_sql)

    return [p.to_dict() for p in positions]


def reconstruct_positions_at(conn, T, addresses: Iterable[str]) -> Dict[str, List[Dict]]:
    """
    Reconstruct positions as of T for a given set of trader addresses.

    Returns {address: [position_dict, ...]} — ALL positions resulting from
    the T-bounded replay (open, closed, and partially_closed), same contract
    as PositionTracker.match_trades_for_trader / Position.to_dict(). "Open at
    T" is status in ('open', 'partially_closed'); filtering to that is left
    to the caller rather than baked in here, so one reconstruction serves
    both "what's open" and "what closed and when" without a second pass.

    remaining_shares on 'open'/'partially_closed' positions is the size-at-T
    (not just presence) — it falls out of reusing the matching engine
    unmodified, since _match_group/_match_group_simplified/close_position
    already track it incrementally as SELLs are matched over the T-bounded
    trade list.
    """
    T = _to_utc(T)
    return {addr: reconstruct_one_at(conn, addr, T) for addr in addresses}
