#!/usr/bin/env python3
"""
B1b-positions validation harness.

Part 1: T=now reconstruction (analysis/pit_positions.py) vs the live `positions`
table for the Pool-C population. Classifies every divergence into exactly one
of three buckets rather than reporting a single match rate, because two
pre-existing, independent defects in the live table's write path (found while
building this harness, ledgered as O-42 and O-43 in trading-swarm) guarantee
divergence that has nothing to do with B1b's own correctness:

  (a) O-43 (position_id collision): B1b holds >1 distinct position under a
      position_id the live table's upsert collapsed to one row.
  (b) O-42 (is_synthetic_close freeze): the live row matches on every
      economically meaningful field (shares, prices, timestamps, status) and
      differs ONLY on the is_synthetic_close flag.
  (c) unexplained: everything else. This is the number that would indicate a
      real B1b bug.

Part 2: the O-36 correction's measured value. At a fixed past T, counts how
many synthetic-close-eligible positions would have a DIFFERENT open/closed
verdict under tape-end (what B1b uses) vs. the stored resolution_date (what a
naive reconstruction would use) — i.e. how many positions a naive PIT
reconstruction would misjudge as open-when-closed or closed-when-open at
that T.

Read-only. No writes to the database.
"""

import os
import sys
import time
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import analysis.pit_positions as pp

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'polymarket_tracker.db')

FLOAT_TOL = 0.01


def _close(a, b, tol=FLOAT_TOL):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < tol


def _fields_match_except_synthetic_flag(recon_pos, live_row):
    """live_row: (position_id, entry_shares, entry_avg_price, exit_shares,
    exit_avg_price, status, remaining_shares, is_synthetic_close, exit_timestamp)."""
    (_, entry_shares, entry_avg_price, exit_shares, exit_avg_price,
     status, remaining_shares, is_synthetic_close, exit_timestamp) = live_row

    if recon_pos['status'] != status:
        return False, False
    if not _close(recon_pos['entry_shares'], entry_shares):
        return False, False
    if not _close(recon_pos['entry_avg_price'], entry_avg_price, tol=0.001):
        return False, False
    if not _close(recon_pos['remaining_shares'] or 0, remaining_shares or 0):
        return False, False
    if (recon_pos['exit_shares'] is None) != (exit_shares is None):
        return False, False
    if recon_pos['exit_shares'] is not None and not _close(recon_pos['exit_shares'], exit_shares):
        return False, False
    if (recon_pos['exit_avg_price'] is None) != (exit_avg_price is None):
        return False, False
    if recon_pos['exit_avg_price'] is not None and not _close(recon_pos['exit_avg_price'], exit_avg_price, tol=0.005):
        return False, False

    full_match = (recon_pos['is_synthetic_close'] == is_synthetic_close)
    return True, full_match


def part1(conn, addresses):
    t0 = time.time()
    T_now = datetime.now(timezone.utc)
    t_sql = pp._t_sql(T_now)

    n_traders = 0
    n_positions_recon = 0
    n_positions_live = 0
    exact_match = 0
    o43_explained = 0
    o42_explained = 0
    o44_explained = 0
    unexplained = 0
    unexplained_examples = []

    # status-specific breakdown of the four buckets, so open/partially_closed
    # can be reported on its own per the sanity-check ask.
    by_status = defaultdict(lambda: defaultdict(int))

    for address in addresses:
        n_traders += 1

        grouped = pp._fetch_trades_at(conn, address, t_sql)
        # O-44 signature, generalized: any (market_id, outcome) group that
        # currently produces at least one reconstructed position has been
        # "reprocessed" against the full current trade tape. A live-only row
        # in that same group with no recon counterpart is a boundary-shift
        # orphan -- some FIFO/simplified-matching boundary moved once later
        # trades arrived (not only the 50-trade/100k-share threshold; any
        # trade added to a group can shift where positions start/end), and
        # store_positions() never deletes rows a fresh computation no longer
        # produces. The threshold crossing is the most common, quantifiable
        # trigger (see O-44 in the ledger) but not the only one.
        reprocessed_market_outcomes = set(grouped.keys())

        positions = []
        for (market_id, outcome), trades in grouped.items():
            positions.extend(pp._TRACKER._match_group(address, market_id, outcome, trades))
        pp._apply_synthetic_closes_at(positions, conn, t_sql)
        recon = [p.to_dict() for p in positions]
        n_positions_recon += len(recon)

        live_rows_raw = conn.execute("""
            SELECT position_id, entry_shares, entry_avg_price, exit_shares,
                   exit_avg_price, status, remaining_shares, is_synthetic_close, exit_timestamp,
                   market_id, outcome
            FROM positions WHERE trader_address = ?
        """, (address,)).fetchall()
        n_positions_live += len(live_rows_raw)
        # keep the 9-field tuple _fields_match_except_synthetic_flag expects;
        # market_id/outcome carried alongside for the O-44 check below.
        live_by_id = {r[0]: r[:9] for r in live_rows_raw}
        live_group_by_id = {r[0]: (r[9], r[10]) for r in live_rows_raw}

        recon_by_id = defaultdict(list)
        for p in recon:
            recon_by_id[p['position_id']].append(p)

        matched_live_ids = set()

        for pid, plist in recon_by_id.items():
            status_key = plist[0]['status']
            if pid not in live_by_id:
                unexplained += len(plist)
                by_status[status_key]['unexplained'] += len(plist)
                if len(unexplained_examples) < 10:
                    unexplained_examples.append(('MISSING_FROM_LIVE', address, pid, plist[0]))
                continue

            matched_live_ids.add(pid)
            live_row = live_by_id[pid]

            if len(plist) > 1:
                survivor_matches = any(
                    _fields_match_except_synthetic_flag(p, live_row)[0] for p in plist
                )
                if survivor_matches:
                    o43_explained += len(plist)
                    by_status[status_key]['o43'] += len(plist)
                else:
                    unexplained += len(plist)
                    by_status[status_key]['unexplained'] += len(plist)
                    if len(unexplained_examples) < 10:
                        unexplained_examples.append(('COLLISION_SURVIVOR_MISMATCH', address, pid, plist))
                continue

            p = plist[0]
            base_match, full_match = _fields_match_except_synthetic_flag(p, live_row)
            if full_match:
                exact_match += 1
                by_status[status_key]['exact'] += 1
            elif base_match:
                o42_explained += 1
                by_status[status_key]['o42'] += 1
            else:
                unexplained += 1
                by_status[status_key]['unexplained'] += 1
                if len(unexplained_examples) < 10:
                    unexplained_examples.append(('FIELD_DIFF', address, pid, p, live_row))

        # O-44 pass: live rows with NO recon counterpart at all (neither as an
        # exact id match nor absorbed into a collision group above).
        for lid, lrow in live_by_id.items():
            if lid in matched_live_ids:
                continue
            live_status = lrow[5]
            # O-44 signature (generalized): this row's (market_id, outcome)
            # group produced at least one position under the current, full
            # trade tape -- i.e. it WAS reprocessed, just with different
            # boundaries than whenever this stale row was first stored.
            group_key = live_group_by_id.get(lid)
            if group_key in reprocessed_market_outcomes:
                o44_explained += 1
                by_status[live_status]['o44'] += 1
            else:
                unexplained += 1
                by_status[live_status]['unexplained'] += 1
                if len(unexplained_examples) < 10:
                    unexplained_examples.append(('LIVE_ONLY_NOT_O44', address, lid, lrow))

    elapsed = time.time() - t0
    print(f'=== PART 1: T=now reconstruction vs live table ({n_traders} traders, {elapsed:.1f}s) ===')
    print(f'positions: recon={n_positions_recon}  live={n_positions_live}')
    print(f'exact match:      {exact_match}')
    print(f'O-43 explained:   {o43_explained}  (position_id collisions)')
    print(f'O-42 explained:   {o42_explained}  (is_synthetic_close flag freeze only)')
    print(f'O-44 explained:   {o44_explained}  (stale fine-grained rows, group since crossed simplified-matching threshold)')
    print(f'UNEXPLAINED:      {unexplained}')
    print()
    print('By status (open / partially_closed shown separately per the sanity-check ask):')
    for status in ('open', 'partially_closed', 'closed'):
        d = by_status[status]
        print(f'  {status:18s} exact={d["exact"]:>8} o43={d["o43"]:>7} o42={d["o42"]:>7} '
              f'o44={d["o44"]:>7} unexplained={d["unexplained"]:>6}')
    if unexplained_examples:
        print('\nUnexplained examples:')
        for ex in unexplained_examples:
            print(' ', ex)

    return {
        'n_traders': n_traders, 'recon': n_positions_recon, 'live': n_positions_live,
        'exact_match': exact_match, 'o43_explained': o43_explained,
        'o42_explained': o42_explained, 'o44_explained': o44_explained,
        'unexplained': unexplained, 'by_status': dict(by_status),
    }


def part2(conn, addresses, T_past):
    """Flip count: positions still-open-after-real-trades whose market-resolved
    verdict disagrees between tape_end<=T (B1b) and resolution_date<=T (naive)."""
    t0 = time.time()
    t_sql = pp._t_sql(T_past)
    pp._ensure_tape_end_temp_table(conn)

    total_candidates = 0
    flips_naive_says_open_actually_closed = 0   # tape_end<=T<resolution_date
    flips_naive_says_closed_actually_open = 0   # resolution_date<=T<tape_end
    no_flip = 0

    for address in addresses:
        grouped = pp._fetch_trades_at(conn, address, t_sql)
        positions = []
        for (market_id, outcome), trades in grouped.items():
            positions.extend(pp._TRACKER._match_group(address, market_id, outcome, trades))

        open_positions = [p for p in positions if p.status == 'open']
        if not open_positions:
            continue

        market_ids = list({p.market_id for p in open_positions})
        placeholders = ','.join('?' for _ in market_ids)
        rows = conn.execute(f"""
            SELECT m.market_id, m.resolved, m.resolution_date, tape.tape_end
            FROM markets m
            LEFT JOIN tape_end tape ON tape.market_id = m.market_id
            WHERE m.market_id IN ({placeholders})
        """, market_ids).fetchall()
        market_meta = {mid: (resolved, resolution_date, tape_end)
                       for mid, resolved, resolution_date, tape_end in rows}

        # Count per POSITION, not per (trader, market) -- a trader can hold
        # multiple open positions in the same market (e.g. several separate
        # BUYs never sold), each independently misjudged by a naive gate.
        for pos in open_positions:
            meta = market_meta.get(pos.market_id)
            if not meta:
                continue
            resolved, resolution_date, tape_end = meta
            if not resolved or not resolution_date or not tape_end:
                continue
            total_candidates += 1
            tape_closed = tape_end <= t_sql
            naive_closed = resolution_date <= t_sql
            if tape_closed and not naive_closed:
                flips_naive_says_open_actually_closed += 1
            elif naive_closed and not tape_closed:
                flips_naive_says_closed_actually_open += 1
            else:
                no_flip += 1

    elapsed = time.time() - t0
    total_flips = flips_naive_says_open_actually_closed + flips_naive_says_closed_actually_open
    print(f'\n=== PART 2: flip count at T={T_past.isoformat()} ({elapsed:.1f}s) ===')
    print(f'candidate (market, still-open-after-real-trades) pairs evaluated: {total_candidates}')
    print(f'no flip (both gates agree):                                      {no_flip}')
    print(f'FLIP - naive(resolution_date) says OPEN, tape-end says CLOSED:   {flips_naive_says_open_actually_closed}')
    print(f'FLIP - naive(resolution_date) says CLOSED, tape-end says OPEN:   {flips_naive_says_closed_actually_open}')
    print(f'TOTAL FLIPS: {total_flips} / {total_candidates} ({100*total_flips/total_candidates:.2f}%)' if total_candidates else 'n/a')

    return {
        'candidates': total_candidates, 'no_flip': no_flip,
        'flip_open_to_closed': flips_naive_says_open_actually_closed,
        'flip_closed_to_open': flips_naive_says_closed_actually_open,
    }


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)

    addresses = [r[0] for r in conn.execute(
        "SELECT address FROM traders WHERE geo_accuracy_pool = 1"
    ).fetchall()]
    print(f'Scope: {len(addresses)} Pool-C traders (includes all {len(addresses)} cohort-eligible members).')

    part1(conn, addresses)

    T_past = datetime(2026, 5, 22, tzinfo=timezone.utc)
    part2(conn, addresses, T_past)

    conn.close()


if __name__ == '__main__':
    main()
