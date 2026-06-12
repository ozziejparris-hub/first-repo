#!/usr/bin/env python3
"""
backfill_clob_token_ids.py

Fetches clobTokenIds for markets missing them in the DB.
Primary: CLOB API /markets/{condition_id} (exact match, reliable).
Fallback: Gamma conditionIds param — BUT Gamma silently ignores unrecognised
  conditionIds and returns a default popular-market list, so we MUST verify
  that the returned market's conditionId matches what we queried.

Run after any new signal markets are added.

Usage:
  python3 backfill_clob_token_ids.py              # backfill all missing
  python3 backfill_clob_token_ids.py --market-id X # backfill specific market
"""

import sqlite3, requests, json, argparse, os, time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')
CLOB_BASE = 'https://clob.polymarket.com'
GAMMA_BASE = 'https://gamma-api.polymarket.com'

def fetch_token_ids(condition_id):
    """Fetch YES/NO token IDs for a market.

    Tries CLOB first (exact match). Falls back to Gamma with conditionId
    verification — Gamma returns a default list when the ID is unrecognised,
    so we reject results where the returned conditionId doesn't match.
    """
    # --- Primary: CLOB API ---
    try:
        r = requests.get(f'{CLOB_BASE}/markets/{condition_id}', timeout=15)
        if r.status_code == 200:
            market = r.json()
            tokens = market.get('tokens', [])
            yes_token = next((t['token_id'] for t in tokens if t.get('outcome') == 'Yes'), None)
            no_token = next((t['token_id'] for t in tokens if t.get('outcome') == 'No'), None)
            if yes_token:
                return yes_token, no_token
        elif r.status_code != 404:
            print(f'  CLOB error {r.status_code} for {condition_id[:20]}')
    except Exception as e:
        print(f'  CLOB fetch error: {e}')

    # --- Fallback: Gamma API (with match verification) ---
    try:
        r = requests.get(f'{GAMMA_BASE}/markets',
                        params={'conditionIds': condition_id},
                        timeout=15)
        if r.status_code != 200:
            print(f'  Gamma error {r.status_code} for {condition_id[:20]}')
            return None, None
        markets = r.json()
        if not markets:
            print(f'  No market found for conditionId {condition_id[:20]}')
            return None, None
        # Gamma silently ignores unrecognised IDs and returns a default list —
        # verify the returned market actually matches the queried conditionId.
        market = next((m for m in markets if m.get('conditionId', '').lower() == condition_id.lower()), None)
        if not market:
            print(f'  Gamma returned no matching conditionId for {condition_id[:20]} (got unrelated markets)')
            return None, None
        token_ids_raw = market.get('clobTokenIds')
        if not token_ids_raw:
            print(f'  No clobTokenIds in Gamma response')
            return None, None
        if isinstance(token_ids_raw, str):
            token_ids = json.loads(token_ids_raw)
        else:
            token_ids = token_ids_raw
        # token_ids[0] = YES token, token_ids[1] = NO token (Polymarket convention)
        yes_token = token_ids[0] if len(token_ids) > 0 else None
        no_token = token_ids[1] if len(token_ids) > 1 else None
        return yes_token, no_token
    except Exception as e:
        print(f'  Gamma fetch error: {e}')
        return None, None

def run(market_id=None):
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=60000')
    cur = conn.cursor()

    if market_id:
        cur.execute('SELECT market_id, condition_id FROM markets WHERE market_id = ?', (market_id,))
    else:
        # Include markets where condition_id is NULL but market_id is a 0x hash
        # (market_id IS the conditionId for many Polymarket markets)
        cur.execute('''SELECT market_id, condition_id FROM markets
                      WHERE clob_token_id_yes IS NULL
                      AND (
                        (condition_id IS NOT NULL AND condition_id != "")
                        OR (condition_id IS NULL AND market_id LIKE "0x%")
                      )
                      LIMIT 500''')
    rows = cur.fetchall()
    print(f'Markets to process: {len(rows)}')

    updated = 0
    for market_id, condition_id in rows:
        # Fall back to market_id when condition_id is NULL (they're the same for many markets)
        lookup_id = condition_id if condition_id else market_id
        yes_token, no_token = fetch_token_ids(lookup_id)
        if yes_token:
            conn.execute('''UPDATE markets SET clob_token_id_yes = ?, clob_token_id_no = ?
                           WHERE market_id = ?''', (yes_token, no_token, market_id))
            updated += 1
            print(f'  ✓ {market_id[:20]}... YES={yes_token[:20]}...')
        time.sleep(0.2)  # rate limit

    conn.commit()
    print(f'Updated {updated} markets')
    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-id', help='Specific market to backfill')
    args = parser.parse_args()
    run(market_id=args.market_id)
