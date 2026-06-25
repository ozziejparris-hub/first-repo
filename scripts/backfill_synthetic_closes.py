#!/usr/bin/env python
"""
One-off backfill: Apply synthetic resolution closes to all traders who have open
positions in markets that have since resolved.

Safe to run multiple times — ON CONFLICT DO UPDATE handles duplicates.
Run from project root:
    python scripts/backfill_synthetic_closes.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.database import Database
from monitoring.position_tracker import PositionTracker

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')

def main():
    db = Database(DB_PATH)
    tracker = PositionTracker(db)

    # Schema migration runs automatically inside Database.__init__
    print("[BACKFILL] Schema migration complete (is_synthetic_close column ensured)")

    # Find all traders who have any trades in resolved markets
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT t.trader_address
        FROM trades t
        INNER JOIN markets m ON m.market_id = t.market_id
        WHERE m.resolved = 1
          AND m.winning_outcome IS NOT NULL
          AND m.winning_outcome != ''
        ORDER BY t.trader_address
    """)
    traders = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"[BACKFILL] Found {len(traders)} traders with trades in resolved markets")

    total_synthetic = 0
    total_closed_before = 0
    processed = 0
    errors = 0

    for i, addr in enumerate(traders):
        try:
            # Match FIFO positions
            positions = tracker.match_trades_for_trader(addr, verbose=False)
            if not positions:
                continue

            # Get resolved markets for this trader
            resolved_markets = db.get_resolved_markets_for_trader(addr)
            if not resolved_markets:
                continue

            # Count open positions before synthetic closes
            open_before = sum(1 for p in positions if p.status == 'open')
            closed_before = sum(1 for p in positions if p.status == 'closed')
            total_closed_before += closed_before

            # Apply synthetic closes
            n_synthetic = tracker.apply_synthetic_closes(positions, resolved_markets)
            if n_synthetic == 0:
                continue

            total_synthetic += n_synthetic

            # Persist all positions to DB
            conn2 = db.get_connection()
            c2 = conn2.cursor()
            try:
                for pos in positions:
                    pd = pos.to_dict()
                    data_src = 'synthetic_resolution' if pd.get('is_synthetic_close') else 'position_tracker'
                    c2.execute("""
                        INSERT INTO positions (
                            position_id, trader_address, market_id, market_title,
                            outcome, entry_shares, entry_avg_price, entry_total_cost,
                            entry_timestamp, entry_trade_ids,
                            exit_shares, exit_avg_price, exit_total_received,
                            exit_timestamp, exit_trade_ids,
                            realized_pnl, roi_percent, holding_period_hours,
                            status, remaining_shares, is_synthetic_close, last_updated, data_source
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?)
                        ON CONFLICT(position_id) DO UPDATE SET
                            market_title         = excluded.market_title,
                            entry_shares         = excluded.entry_shares,
                            entry_avg_price      = excluded.entry_avg_price,
                            entry_total_cost     = excluded.entry_total_cost,
                            entry_trade_ids      = excluded.entry_trade_ids,
                            exit_shares          = excluded.exit_shares,
                            exit_avg_price       = excluded.exit_avg_price,
                            exit_total_received  = excluded.exit_total_received,
                            exit_timestamp       = excluded.exit_timestamp,
                            exit_trade_ids       = excluded.exit_trade_ids,
                            realized_pnl         = excluded.realized_pnl,
                            roi_percent          = excluded.roi_percent,
                            holding_period_hours = excluded.holding_period_hours,
                            status               = excluded.status,
                            remaining_shares     = excluded.remaining_shares,
                            is_synthetic_close   = excluded.is_synthetic_close,
                            last_updated         = CURRENT_TIMESTAMP,
                            data_source          = CASE WHEN data_source = 'synthetic_resolution'
                                                        THEN 'synthetic_resolution'
                                                        ELSE excluded.data_source END
                    """, (
                        pd['position_id'], pd['trader_address'], pd['market_id'],
                        pd['market_title'], pd['outcome'],
                        pd['entry_shares'], pd['entry_avg_price'], pd['entry_total_cost'],
                        pd['entry_timestamp'], pd['entry_trade_ids'],
                        pd['exit_shares'], pd['exit_avg_price'], pd['exit_total_received'],
                        pd['exit_timestamp'], pd['exit_trade_ids'],
                        pd['realized_pnl'], pd['roi_percent'], pd['holding_period_hours'],
                        pd['status'], pd['remaining_shares'],
                        pd.get('is_synthetic_close', 0),
                        data_src,
                    ))
                conn2.commit()
            except Exception as e:
                print(f"  [ERROR] DB write failed for {addr[:10]}...: {e}")
                conn2.rollback()
                errors += 1
            finally:
                conn2.close()

            # Update traders row with aggregated P&L
            closed_positions = [p for p in positions if p.status == 'closed']
            if closed_positions:
                n_closed = len(closed_positions)
                realized_pnl = sum(p.realized_pnl for p in closed_positions if p.realized_pnl)
                avg_roi = sum(p.roi_percent for p in closed_positions if p.roi_percent) / n_closed

                conn3 = db.get_connection()
                c3 = conn3.cursor()
                try:
                    c3.execute("""
                        UPDATE traders
                        SET realized_pnl = ?,
                            avg_roi = ?,
                            roi_percentage = ?,
                            closed_positions = ?,
                            open_positions = ?
                        WHERE address = ?
                    """, (
                        realized_pnl, avg_roi, avg_roi, n_closed,
                        len([p for p in positions if p.status == 'open']),
                        addr,
                    ))
                    conn3.commit()
                except Exception as e:
                    print(f"  [ERROR] Trader update failed for {addr[:10]}...: {e}")
                    conn3.rollback()
                finally:
                    conn3.close()

            db.mark_trader_pnl_updated(addr)
            processed += 1

            if processed % 50 == 0:
                print(f"  [BACKFILL] Progress: {processed}/{len(traders)} processed, "
                      f"{total_synthetic} synthetic closes so far...")

        except Exception as e:
            print(f"  [ERROR] Failed for {addr[:10]}...: {e}")
            errors += 1
            continue

    # Final report
    print(f"\n[BACKFILL] === COMPLETE ===")
    print(f"  Traders processed:       {processed}")
    print(f"  Synthetic closes added:  {total_synthetic}")
    print(f"  Real closes (pre-run):   {total_closed_before}")
    print(f"  Errors:                  {errors}")

    # Query final counts
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM positions WHERE status='closed'")
    total_closed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM positions WHERE status='closed' AND COALESCE(is_synthetic_close,0)=1")
    total_synthetic_db = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT trader_address) FROM positions WHERE status='closed'")
    traders_with_pnl = cursor.fetchone()[0]
    conn.close()

    print(f"\n[BACKFILL] DB state after backfill:")
    print(f"  Total closed positions:  {total_closed}")
    print(f"  Synthetic closes:        {total_synthetic_db}")
    print(f"  Real SELL closes:        {total_closed - total_synthetic_db}")
    print(f"  Traders with closed P&L: {traders_with_pnl}")


if __name__ == '__main__':
    main()
