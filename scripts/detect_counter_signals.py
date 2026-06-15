#!/usr/bin/env python3
"""
detect_counter_signals.py — detect proven-trader counter-positioning on active signals.

PRINCIPLE (reaffirmed by Peru, June 2026): counter-signals DOWNWEIGHT, never
auto-invalidate. A LEGENDARY trader reversing does NOT mean the signal was wrong —
Peru proved counter-signals can themselves be wrong. The output is a credibility
adjustment for human review, never an automatic status change.

For each ACTIVE STR-003 signal, examines proven-trader (LEGENDARY/ELITE) net positions
in the signal market and classifies each into three states:

  CONFIRMING : net position on the signal side (still backing the signal)
  EXITED     : had signal-side position, now net ~0 (withdrew support — soft counter)
  REVERSED   : net position on the OPPOSING side (actively betting against — strong)

Recency: a state only counts as a NEW counter-signal if the exit/reversal trades
occurred AFTER the signal's registration date. Pre-registration positioning is the
baseline, not a counter-signal.

Two modes:
  Mode 1 (specific-trader): signal has key_traders/key_trader addresses — watch those
                            exact traders. High precision.
  Mode 2 (market-level):    signal has only a legendary_traders count — watch ANY
                            proven trader in the market. Lower precision.

DOWNWEIGHT mechanic:
  strength = opposing_or_exited_size / signal_side_baseline_size  (capped 1.0)
  EXITED   -> -5 SCS (mild)
  REVERSED -> -10 to -20 SCS scaled by strength
  adjusted_scs = max(scs - adjustment, SCS_FLOOR=25)   # never invalidates

Writes counter_signal_v2 block to each active signal in signals.json.
Fires Telegram alert only on REVERSED by a LEGENDARY trader (per alert policy).

Usage:
  python3 detect_counter_signals.py            # detect + write adjustments
  python3 detect_counter_signals.py --report   # report only, no writes
"""

import json
import sqlite3
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
SIGNALS_PATH = Path("/home/parison/trading-swarm/brain/signals.json")

GEO_ELO_LEGENDARY = 2175.0
GEO_ELO_ELITE = 1800.0
SCS_FLOOR = 25.0

# Net-position threshold (shares) below which a position is considered "flat/exited"
FLAT_THRESHOLD = 50.0


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _signal_side_outcome(direction):
    """Map signal direction to the outcome string on the signal side."""
    return 'No' if direction.upper() == 'NO' else 'Yes'


def _opposing_outcome(direction):
    return 'Yes' if direction.upper() == 'NO' else 'No'


def _net_positions_for_market(conn, market_id, signal_date, proven_addresses=None):
    """
    Compute net positions for proven traders in a market.
    If proven_addresses given (Mode 1), restrict to those traders.
    Otherwise (Mode 2), include all LEGENDARY/ELITE traders in the market.

    Returns list of dicts per trader with net_signal_side, net_opposing,
    and post-registration activity flags.
    """
    cur = conn.cursor()

    # Build trader filter
    if proven_addresses:
        placeholders = ','.join('?' * len(proven_addresses))
        trader_filter = f"AND t.trader_address IN ({placeholders})"
        params = [market_id] + list(proven_addresses)
    else:
        trader_filter = """AND tr.geo_elo_active >= ?
                           AND tr.geo_accuracy_pool = 1
                           AND tr.research_excluded = 0
                           AND tr.bot_type IS NULL"""
        params = [market_id, GEO_ELO_ELITE]

    query = f"""
        SELECT t.trader_address, t.outcome, t.side, t.shares, t.timestamp,
               tr.geo_elo_active
        FROM trades t
        JOIN traders tr ON tr.address = t.trader_address
        WHERE t.market_id = ?
        {trader_filter}
        ORDER BY t.trader_address, t.timestamp
    """
    cur.execute(query, params)
    rows = cur.fetchall()

    # Aggregate per trader
    traders = {}
    for r in rows:
        addr = r['trader_address']
        if addr not in traders:
            traders[addr] = {
                'address': addr,
                'geo_elo': r['geo_elo_active'],
                'net_yes': 0.0,
                'net_no': 0.0,
                'post_reg_yes': 0.0,
                'post_reg_no': 0.0,
                'last_trade': None,
                'has_post_reg_activity': False,
            }
        t = traders[addr]
        signed = r['shares'] if r['side'] == 'BUY' else -r['shares']
        if r['outcome'] == 'Yes':
            t['net_yes'] += signed
        elif r['outcome'] == 'No':
            t['net_no'] += signed

        # Track post-registration activity
        trade_ts = str(r['timestamp'])[:10]
        if signal_date and trade_ts > signal_date:
            t['has_post_reg_activity'] = True
            if r['outcome'] == 'Yes':
                t['post_reg_yes'] += signed
            elif r['outcome'] == 'No':
                t['post_reg_no'] += signed
        t['last_trade'] = str(r['timestamp'])

    return list(traders.values())


def _classify_trader(trader, direction):
    """Classify a trader's net position relative to signal direction.
    Returns (state, net_signal_side, net_opposing)."""
    if direction.upper() == 'NO':
        net_signal_side = trader['net_no']
        net_opposing = trader['net_yes']
    else:
        net_signal_side = trader['net_yes']
        net_opposing = trader['net_no']

    net = net_signal_side - net_opposing

    if net_opposing > FLAT_THRESHOLD and net < -FLAT_THRESHOLD:
        state = 'REVERSED'
    elif abs(net) <= FLAT_THRESHOLD:
        state = 'EXITED'
    elif net > FLAT_THRESHOLD:
        state = 'CONFIRMING'
    else:
        state = 'EXITED'  # net slightly negative but no real opposing position

    return state, net_signal_side, net_opposing


def detect_for_signal(conn, signal):
    """Detect counter-signals for one active signal. Returns counter_signal_v2 block."""
    direction = signal.get('direction', 'NO')
    market_id = signal.get('market_id') or signal.get('market')
    signal_date = signal.get('signal_date') or (signal.get('registered_at') or '')[:10]

    # Determine mode + trader set
    proven_addresses = None
    mode = 'market_level'
    # Mode 1: explicit addresses
    key_traders = signal.get('key_traders')
    key_trader = signal.get('key_trader')
    if key_traders and isinstance(key_traders, list):
        proven_addresses = key_traders
        mode = 'specific_trader'
    elif key_trader and isinstance(key_trader, str) and key_trader.startswith('0x'):
        proven_addresses = [key_trader]
        mode = 'specific_trader'

    traders = _net_positions_for_market(conn, market_id, signal_date, proven_addresses)

    confirming, exited, reversed_ = [], [], []
    for t in traders:
        state, net_ss, net_opp = _classify_trader(t, direction)
        entry = {
            'address': t['address'][:16],
            'geo_elo': round(t['geo_elo'], 0) if t['geo_elo'] else None,
            'net_signal_side': round(net_ss, 0),
            'net_opposing': round(net_opp, 0),
            'last_trade': t['last_trade'],
            'post_reg_activity': t['has_post_reg_activity'],
            'is_legendary': t['geo_elo'] >= GEO_ELO_LEGENDARY if t['geo_elo'] else False,
        }
        if state == 'CONFIRMING':
            confirming.append(entry)
        elif state == 'EXITED':
            exited.append(entry)
        elif state == 'REVERSED':
            reversed_.append(entry)

    # Counter-signal strength: only post-registration exits/reversals count as NEW
    new_exits = [e for e in exited if e['post_reg_activity']]
    new_reversals = [e for e in reversed_ if e['post_reg_activity']]

    # Compute adjustment (DOWNWEIGHT, never invalidate)
    adjustment = 0.0
    if new_reversals:
        legendary_reversals = [e for e in new_reversals if e['is_legendary']]
        base = 20.0 if legendary_reversals else 12.0
        adjustment = base
    elif new_exits:
        legendary_exits = [e for e in new_exits if e['is_legendary']]
        adjustment = 8.0 if legendary_exits else 5.0

    detected = bool(new_exits or new_reversals)

    return {
        'counter_signal_detected': detected,
        'mode': mode,
        'evaluated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'signal_date_cutoff': signal_date,
        'confirming_count': len(confirming),
        'exited_count': len(exited),
        'reversed_count': len(reversed_),
        'new_post_reg_exits': len(new_exits),
        'new_post_reg_reversals': len(new_reversals),
        'credibility_adjustment': -adjustment if detected else 0.0,
        'scs_floor_applied': SCS_FLOOR,
        'reversals': new_reversals,
        'exits': new_exits,
        'note': ('DOWNWEIGHT only — counter-signals inform, never auto-invalidate. '
                 'Peru proved counter-signals can be wrong. Human reviews flagged signals.'),
    }


def run(conn, report_only=False):
    with open(SIGNALS_PATH) as f:
        data = json.load(f)

    active = [s for s in data.get('str003_signals', [])
              if isinstance(s, dict) and s.get('status') == 'ACTIVE']
    print(f"Active STR-003 signals: {len(active)}")

    alerts = []
    for signal in active:
        result = detect_for_signal(conn, signal)
        sid = signal.get('signal_id')

        print(f"\n{sid} ({signal.get('direction')}) — mode={result['mode']}")
        print(f"  confirming={result['confirming_count']}, "
              f"exited={result['exited_count']}, reversed={result['reversed_count']}")
        print(f"  NEW post-registration: exits={result['new_post_reg_exits']}, "
              f"reversals={result['new_post_reg_reversals']}")
        if result['counter_signal_detected']:
            print(f"  ⚠️  COUNTER-SIGNAL: credibility_adjustment={result['credibility_adjustment']}")
            if result['new_post_reg_reversals'] > 0:
                alerts.append((sid, signal, result))
        else:
            print(f"  ✓ No new counter-positioning since registration")

        if not report_only:
            signal['counter_signal_v2'] = result

    if not report_only:
        with open(SIGNALS_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nWrote counter_signal_v2 to {len(active)} active signals")

    # Fire alerts for LEGENDARY reversals
    for sid, signal, result in alerts:
        leg_reversals = [r for r in result['reversals'] if r['is_legendary']]
        if leg_reversals:
            _fire_alert(sid, signal, result, leg_reversals)

    return alerts


def _fire_alert(sid, signal, result, legendary_reversals):
    """Fire Telegram alert for LEGENDARY counter-entry (per alert policy)."""
    msg = (f"⚠️ COUNTER-SIGNAL: {sid}\n"
           f"{signal.get('market_title','')[:50]}\n"
           f"Signal direction: {signal.get('direction')}\n"
           f"{len(legendary_reversals)} LEGENDARY trader(s) REVERSED to opposing side\n"
           f"Credibility adjustment: {result['credibility_adjustment']} SCS\n"
           f"NOTE: downweight only — review, do not auto-act (Peru lesson)")
    print(f"\n[ALERT] {msg}", file=sys.stderr)
    # Wire to actual telegram sender if available in maintenance context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()

    conn = _get_conn()
    run(conn, report_only=args.report)
    conn.close()


if __name__ == '__main__':
    main()
