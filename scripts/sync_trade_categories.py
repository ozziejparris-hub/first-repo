#!/usr/bin/env python3
"""
sync_trade_categories.py

Syncs trades.market_category from the authoritative markets.category column.
Fixes the historical gap where trades were ingested before markets were
recategorised by Polymarket.

Run modes:
  --full-sync   : update all mismatched trades (one-time backfill)
  --incremental : update only trades from last N days (daily maintenance)
  --dry-run     : report counts without making changes

Daily maintenance: add to daily_maintenance.py as Step 0b (after update_research_exclusions,
before update_geo_elo) so ELO always has current category data.
"""

import sqlite3
import argparse
import logging
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')

def run_sync(full_sync=False, incremental_days=7, dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    cur = conn.cursor()

    # Build the WHERE clause
    if full_sync:
        where_clause = '''
            t.market_category != m.category
            AND m.category IS NOT NULL
            AND t.market_category IS NOT NULL
        '''
        params = []
        logger.info("Mode: FULL SYNC - updating all mismatched trades")
    else:
        cutoff = (datetime.now() - timedelta(days=incremental_days)).isoformat()
        where_clause = '''
            t.market_category != m.category
            AND m.category IS NOT NULL
            AND t.market_category IS NOT NULL
            AND t.timestamp >= ?
        '''
        params = [cutoff]
        logger.info(f"Mode: INCREMENTAL - updating trades from last {incremental_days} days")

    # Count first
    cur.execute(f'''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN m.category IN ("Geopolitics","Elections")
                     AND t.market_category NOT IN ("Geopolitics","Elections")
                     THEN 1 ELSE 0 END) as gaining_geo,
            SUM(CASE WHEN t.market_category IN ("Geopolitics","Elections")
                     AND m.category NOT IN ("Geopolitics","Elections")
                     THEN 1 ELSE 0 END) as losing_geo
        FROM trades t
        JOIN markets m ON m.market_id = t.market_id
        WHERE {where_clause}
    ''', params)
    total, gaining_geo, losing_geo = cur.fetchone()

    logger.info(f"Trades to update: {total:,}")
    logger.info(f"  Gaining geo status: +{gaining_geo or 0:,}")
    logger.info(f"  Losing geo status:  -{losing_geo or 0:,}")

    if dry_run:
        logger.info("DRY RUN - no changes made")
        conn.close()
        return total, gaining_geo, losing_geo

    if total == 0:
        logger.info("Nothing to update")
        conn.close()
        return 0, 0, 0

    # Execute the update in batches to avoid lock contention
    BATCH_SIZE = 10000
    updated = 0

    # Get all trade_ids and new categories to update
    cur.execute(f'''
        SELECT t.trade_id, m.category
        FROM trades t
        JOIN markets m ON m.market_id = t.market_id
        WHERE {where_clause}
    ''', params)
    rows = cur.fetchall()

    logger.info(f"Updating {len(rows):,} trades in batches of {BATCH_SIZE}...")

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i+BATCH_SIZE]
        conn.executemany(
            'UPDATE trades SET market_category = ? WHERE trade_id = ?',
            [(cat, tid) for tid, cat in batch]
        )
        conn.commit()
        updated += len(batch)
        if updated % 50000 == 0:
            logger.info(f"  Progress: {updated:,}/{len(rows):,}")

    logger.info(f"Complete. Updated {updated:,} trades.")
    conn.close()
    return updated, gaining_geo, losing_geo

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync trades.market_category from markets.category')
    parser.add_argument('--full-sync', action='store_true', help='Update all mismatched trades')
    parser.add_argument('--incremental', type=int, default=7, nargs='?', const=7,
                        metavar='DAYS', help='Update trades from last N days (default: 7)')
    parser.add_argument('--dry-run', action='store_true', help='Report only, no changes')
    args = parser.parse_args()

    updated, gained, lost = run_sync(
        full_sync=args.full_sync,
        incremental_days=args.incremental,
        dry_run=args.dry_run
    )

    print(f"sync_trade_categories: updated={updated}, gained_geo={gained}, lost_geo={lost}")
