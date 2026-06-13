#!/usr/bin/env python3
"""
snapshot_order_books.py

Captures CLOB order book depth for all active signal markets.
Writes to order_book_snapshots table (immutable, append-only).
Purpose: Phase 6 paper trading fill simulator needs real historical book data.
Book history CANNOT be backfilled — every missed day is permanently lost.

Run daily in maintenance (Step 20, non-blocking).
Also callable at signal registration time with --signal-id and --snapshot-type registration.

Usage:
  python3 snapshot_order_books.py                    # daily snapshot all active signals
  python3 snapshot_order_books.py --stats            # show capture history
  python3 snapshot_order_books.py --signal-id STR003-007 --snapshot-type registration
"""

import sqlite3, requests, json, argparse, os, time
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')
SIGNALS_PATH = '/home/parison/trading-swarm/brain/signals.json'
CLOB_BASE = 'https://clob.polymarket.com'

def fetch_clob_market_price(condition_id):
    """Fetch authoritative YES price from CLOB /markets/{condition_id}.
    Returns float YES price (0-1) or None if unavailable."""
    try:
        r = requests.get(f'{CLOB_BASE}/markets/{condition_id}', timeout=10)
        if r.status_code == 200:
            market = r.json()
            tokens = market.get('tokens', [])
            yes_token = next((t for t in tokens if t.get('outcome') == 'Yes'), None)
            if yes_token:
                price = yes_token.get('price')
                return float(price) if price is not None else None
    except Exception:
        pass
    return None


def get_active_signal_markets():
    """Read active signals from signals.json, return list of (signal_id, market_id, direction)."""
    try:
        with open(SIGNALS_PATH) as f:
            sigs = json.load(f)
    except Exception as e:
        print(f'Could not read signals.json: {e}')
        return []

    active = []
    for s in sigs.get('str003_signals', []):
        if not isinstance(s, dict):
            continue
        status = s.get('status', '')
        if status not in ('ACTIVE', 'ACTIVE_BELOW_THRESHOLD'):
            continue
        mid = s.get('market_id') or s.get('market')
        sid = s.get('signal_id')
        direction = s.get('direction', 'YES')
        if mid and sid:
            active.append((sid, mid, direction))
    return active

def fetch_book(token_id, top_n=10):
    """Fetch order book from CLOB, return (bids, asks, mid, spread, bid_depth, ask_depth)."""
    try:
        r = requests.get(f'{CLOB_BASE}/book', params={'token_id': token_id}, timeout=15)
        if r.status_code != 200:
            return None
        book = r.json()
        bids = book.get('bids', [])[:top_n]
        asks = book.get('asks', [])[:top_n]

        mid_price, spread, bid_depth, ask_depth = None, None, None, None
        if bids and asks:
            best_bid = float(bids[0].get('price', 0))
            best_ask = float(asks[0].get('price', 0))
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
        if bids:
            bid_depth = sum(float(b.get('size', 0)) for b in bids)
        if asks:
            ask_depth = sum(float(a.get('size', 0)) for a in asks)

        return bids, asks, mid_price, spread, bid_depth, ask_depth
    except Exception as e:
        print(f'  Book fetch error: {e}')
        return None

def snapshot_market(conn, signal_id, market_id, direction, snapshot_type='daily'):
    cur = conn.cursor()

    # Get token IDs for this market
    cur.execute('''SELECT clob_token_id_yes, clob_token_id_no
                   FROM markets WHERE market_id = ?''', (market_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        print(f'  No token IDs for {market_id[:20]} — run backfill_clob_token_ids.py first')
        return False

    yes_token, no_token = row
    # Use the token matching the signal direction
    token_id = yes_token if direction == 'YES' else (no_token or yes_token)

    result = fetch_book(token_id)
    if not result:
        print(f'  Book fetch failed for {signal_id}')
        return False

    bids, asks, mid_price, spread, bid_depth, ask_depth = result
    snapshot_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    clob_yes_price = fetch_clob_market_price(market_id)

    try:
        conn.execute('''
            INSERT OR IGNORE INTO order_book_snapshots
            (market_id, snapshot_ts, signal_id, snapshot_type, direction, token_id,
             bids_json, asks_json, mid_price, spread, bid_depth_10, ask_depth_10,
             clob_market_price_yes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (market_id, snapshot_ts, signal_id, snapshot_type, direction,
              token_id, json.dumps(bids), json.dumps(asks),
              mid_price, spread, bid_depth, ask_depth, clob_yes_price))
        conn.commit()
        yes_str = f'{clob_yes_price:.4f}' if clob_yes_price is not None else 'N/A'
        print(f'  ✓ {signal_id} {direction}: YES={yes_str} mid={mid_price:.3f} '
              f'bid_depth={bid_depth:.0f} ask_depth={ask_depth:.0f}')
        return True
    except Exception as e:
        print(f'  DB write error: {e}')
        return False

def show_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''SELECT signal_id, COUNT(*) as snapshots,
                   MIN(snapshot_ts) as first, MAX(snapshot_ts) as last
                   FROM order_book_snapshots GROUP BY signal_id ORDER BY signal_id''')
    print('Order book snapshot history:')
    for r in cur.fetchall():
        print(f'  {r[0]}: {r[1]} snapshots ({r[2][:10]} → {r[3][:10]})')
    cur.execute('SELECT COUNT(*) FROM order_book_snapshots')
    print(f'Total snapshots: {cur.fetchone()[0]}')
    conn.close()

def run(signal_id_filter=None, snapshot_type='daily'):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')

    active = get_active_signal_markets()
    if signal_id_filter:
        active = [(s, m, d) for s, m, d in active if s == signal_id_filter]

    print(f'Active signal markets to snapshot: {len(active)}')
    captured = 0
    for sid, mid, direction in active:
        print(f'Snapshotting {sid} ({direction})...')
        if snapshot_market(conn, sid, mid, direction, snapshot_type):
            captured += 1
        time.sleep(0.5)

    conn.close()
    print(f'Captured {captured}/{len(active)} book snapshots')
    return captured

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--signal-id', help='Snapshot specific signal only')
    parser.add_argument('--snapshot-type', default='daily',
                        choices=['daily', 'registration'],
                        help='Snapshot type label')
    parser.add_argument('--stats', action='store_true')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        run(signal_id_filter=args.signal_id, snapshot_type=args.snapshot_type)
