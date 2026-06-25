#!/usr/bin/env python3
"""
Backfill missing market rows.

Finds all market_id values in the trades table that have no corresponding
row in the markets table, fetches each from the Gamma API, and inserts a
new row. Safe to re-run — uses INSERT OR IGNORE.

Usage:
    python scripts/backfill_missing_markets.py [--dry-run] [--limit N]
"""
import sys
import sqlite3
import argparse
import time
import json
import requests
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / 'data' / 'polymarket_tracker.db'
GAMMA_URL = 'https://gamma-api.polymarket.com'

CATEGORY_TAG_MAP = {
    'politics': 'Elections',
    'election': 'Elections',
    'president': 'Elections',
    'congress': 'Elections',
    'senate': 'Elections',
    'geopolitics': 'Geopolitics',
    'war': 'Geopolitics',
    'conflict': 'Geopolitics',
    'ukraine': 'Geopolitics',
    'russia': 'Geopolitics',
    'israel': 'Geopolitics',
    'nato': 'Geopolitics',
    'economics': 'Economics',
    'economy': 'Economics',
    'fed': 'Economics',
    'inflation': 'Economics',
    'gdp': 'Economics',
    'crypto': 'Crypto',
    'bitcoin': 'Crypto',
    'btc': 'Crypto',
    'ethereum': 'Crypto',
    'eth': 'Crypto',
    'sports': 'Sports',
    'nfl': 'Sports',
    'nba': 'Sports',
    'mlb': 'Sports',
    'soccer': 'Sports',
    'tennis': 'Sports',
    'entertainment': 'Entertainment',
    'oscar': 'Entertainment',
    'emmy': 'Entertainment',
    'movie': 'Entertainment',
    'celebrity': 'Entertainment',
}


def map_category(tags) -> str:
    if not tags:
        return 'Unknown'
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [tags]
    for tag in tags:
        slug = str(tag.get('slug', '') if isinstance(tag, dict) else tag).lower()
        label = str(tag.get('label', '') if isinstance(tag, dict) else '').lower()
        for keyword, category in CATEGORY_TAG_MAP.items():
            if keyword in slug or keyword in label:
                return category
    return 'Unknown'


def get_missing_markets(db_path: str):
    """Return list of (market_id, title, category) sourced from trades for missing markets."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('''
        SELECT t.market_id,
               MAX(t.market_title)    AS title,
               MAX(t.market_category) AS category
        FROM trades t
        LEFT JOIN markets m ON m.market_id = t.market_id
        WHERE m.market_id IS NULL
          AND t.market_id IS NOT NULL
        GROUP BY t.market_id
        ORDER BY t.market_id
    ''')
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_market(session, market_id: str):
    try:
        resp = session.get(f'{GAMMA_URL}/markets/{market_id}', timeout=10)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def infer_winner(data) -> str | None:
    prices_raw = data.get('outcomePrices')
    outcomes_raw = data.get('outcomes')
    if not prices_raw or not outcomes_raw:
        return None
    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        for outcome, price in zip(outcomes, prices):
            try:
                if float(price) >= 0.99:
                    return str(outcome)
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return None


def insert_market(conn, row: dict, dry_run: bool) -> bool:
    if dry_run:
        return True
    cur = conn.cursor()
    cur.execute('''
        INSERT OR IGNORE INTO markets
            (market_id, title, category, end_date, resolved, winning_outcome,
             condition_id, resolution_date, last_checked, data_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        row['market_id'],
        row['title'],
        row['category'],
        row['end_date'],
        row['resolved'],
        row['winning_outcome'],
        row['condition_id'],
        row['resolution_date'],
        datetime.now().isoformat(),
        'background_backfill',
    ))
    conn.commit()
    return cur.rowcount > 0


def main():
    parser = argparse.ArgumentParser(description='Backfill missing market rows from Gamma API')
    parser.add_argument('--dry-run', action='store_true', help='Fetch but do not write to DB')
    parser.add_argument('--limit', type=int, default=0, help='Max markets to process (0 = all)')
    parser.add_argument('--db', default=str(DB_PATH), help='Path to SQLite database')
    args = parser.parse_args()

    print('=' * 60)
    print('  BACKFILL MISSING MARKETS')
    print('=' * 60)
    if args.dry_run:
        print('  *** DRY RUN — no DB writes ***')
    print()

    missing = get_missing_markets(args.db)
    print(f'Missing market rows found: {len(missing)}')
    if args.limit:
        missing = missing[:args.limit]
        print(f'Limited to: {args.limit}')
    print()

    session = requests.Session()
    session.headers.update({'Accept': 'application/json', 'User-Agent': 'PolymarketTracker/1.0'})

    conn = sqlite3.connect(args.db)
    conn.execute('PRAGMA journal_mode=WAL')

    stats = {'inserted': 0, 'skipped': 0, 'api_ok': 0, 'api_fail_stub': 0}

    for idx, (market_id, trade_title, trade_category) in enumerate(missing, 1):
        data = fetch_market(session, market_id)

        if data and data.get('question'):
            # API returned full data
            closed = data.get('closed', False)
            winner = infer_winner(data) if closed else None
            row = {
                'market_id':       market_id,
                'title':           data.get('question') or data.get('title') or trade_title or '',
                'category':        map_category(data.get('tags')) or trade_category or 'Unknown',
                'end_date':        data.get('endDate'),
                'resolved':        1 if closed else 0,
                'winning_outcome': winner,
                'condition_id':    data.get('conditionId'),
                'resolution_date': data.get('endDate') if closed else None,
            }
            stats['api_ok'] += 1
            source = 'API'
        else:
            # API unavailable — stub row from trade data so the market_id exists in markets table
            row = {
                'market_id':       market_id,
                'title':           trade_title or '',
                'category':        trade_category or 'Unknown',
                'end_date':        None,
                'resolved':        0,
                'winning_outcome': None,
                'condition_id':    None,
                'resolution_date': None,
            }
            stats['api_fail_stub'] += 1
            source = 'STUB'
            time.sleep(0.2)

        inserted = insert_market(conn, row, args.dry_run)
        if inserted:
            stats['inserted'] += 1
            status = 'DRY' if args.dry_run else 'OK'
        else:
            stats['skipped'] += 1
            status = 'SKIP'

        if idx <= 10 or idx % 20 == 0 or idx == len(missing):
            title_short = (row['title'] or market_id)[:45]
            print(f'  [{idx}/{len(missing)}] [{status}][{source}] {title_short}')

        if data:
            time.sleep(0.2)

    conn.close()

    print()
    print('=' * 60)
    print('  SUMMARY')
    print('=' * 60)
    print(f'  Processed  : {len(missing)}')
    print(f'  Inserted   : {stats["inserted"]}')
    print(f'  Skipped    : {stats["skipped"]} (already existed)')
    print(f'  From API   : {stats["api_ok"]}')
    print(f'  Stub rows  : {stats["api_fail_stub"]} (API unavailable, inserted from trade data)')
    print('=' * 60)


if __name__ == '__main__':
    main()
