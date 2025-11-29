import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional
import json


class Database:
    """Handle SQLite database operations for tracking traders and trades."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default to data directory in parent folder
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def init_database(self):
        """Initialize database schema."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Traders table - stores successful traders we're tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traders (
                address TEXT PRIMARY KEY,
                total_trades INTEGER DEFAULT 0,
                successful_trades INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                total_volume REAL DEFAULT 0.0,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_flagged BOOLEAN DEFAULT 0
            )
        """)

        # Trades table - stores all trades from flagged traders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                trader_address TEXT,
                market_id TEXT,
                market_title TEXT,
                market_category TEXT,
                outcome TEXT,
                shares REAL,
                price REAL,
                side TEXT,
                timestamp TIMESTAMP,
                notified BOOLEAN DEFAULT 0,
                completed BOOLEAN DEFAULT 0,
                was_successful BOOLEAN,
                FOREIGN KEY (trader_address) REFERENCES traders(address)
            )
        """)

        # Markets table - stores market information
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                market_id TEXT PRIMARY KEY,
                title TEXT,
                category TEXT,
                end_date TIMESTAMP,
                resolved BOOLEAN DEFAULT 0,
                winning_outcome TEXT,
                resolution_date TIMESTAMP,
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add resolution_date field if it doesn't exist
        try:
            cursor.execute("ALTER TABLE markets ADD COLUMN resolution_date TIMESTAMP")
            print("[DATABASE] Added 'resolution_date' column to markets table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        conn.commit()
        conn.close()

    def add_or_update_trader(self, address: str, total_trades: int,
                            successful_trades: int, win_rate: float,
                            total_volume: float = 0.0, is_flagged: bool = False):
        """Add or update a trader's information."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO traders (address, total_trades, successful_trades, win_rate,
                               total_volume, is_flagged, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                total_trades = excluded.total_trades,
                successful_trades = excluded.successful_trades,
                win_rate = excluded.win_rate,
                total_volume = excluded.total_volume,
                is_flagged = excluded.is_flagged,
                last_updated = excluded.last_updated
        """, (address, total_trades, successful_trades, win_rate,
              total_volume, is_flagged, datetime.now()))

        conn.commit()
        conn.close()

    def get_flagged_traders(self) -> List[str]:
        """Get list of all flagged trader addresses."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT address FROM traders WHERE is_flagged = 1")
        traders = [row[0] for row in cursor.fetchall()]

        conn.close()
        return traders

    def add_trade(self, trade_id: str, trader_address: str, market_id: str,
                  market_title: str, market_category: str, outcome: str,
                  shares: float, price: float, side: str, timestamp: datetime):
        """Add a new trade to the database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO trades (trade_id, trader_address, market_id, market_title,
                                  market_category, outcome, shares, price, side, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trade_id, trader_address, market_id, market_title, market_category,
                  outcome, shares, price, side, timestamp))

            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Trade already exists
            return False
        finally:
            conn.close()

    def mark_trade_notified(self, trade_id: str):
        """Mark a trade as notified."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE trades SET notified = 1 WHERE trade_id = ?", (trade_id,))

        conn.commit()
        conn.close()

    def get_unnotified_trades(self) -> List[Dict]:
        """Get all trades that haven't been notified yet."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT trade_id, trader_address, market_title, outcome, shares,
                   price, side, timestamp
            FROM trades
            WHERE notified = 0
            ORDER BY timestamp DESC
        """)

        trades = []
        for row in cursor.fetchall():
            trades.append({
                'trade_id': row[0],
                'trader_address': row[1],
                'market_title': row[2],
                'outcome': row[3],
                'shares': row[4],
                'price': row[5],
                'side': row[6],
                'timestamp': row[7]
            })

        conn.close()
        return trades

    def update_market(self, market_id: str, title: str, category: str,
                     end_date: Optional[datetime] = None, resolved: bool = False,
                     winning_outcome: Optional[str] = None,
                     resolution_date: Optional[datetime] = None):
        """Add or update market information."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO markets (market_id, title, category, end_date, resolved,
                               winning_outcome, resolution_date, last_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                title = excluded.title,
                category = excluded.category,
                end_date = excluded.end_date,
                resolved = excluded.resolved,
                winning_outcome = excluded.winning_outcome,
                resolution_date = excluded.resolution_date,
                last_checked = excluded.last_checked
        """, (market_id, title, category, end_date, resolved, winning_outcome,
              resolution_date, datetime.now()))

        conn.commit()
        conn.close()

    def update_market_resolution(self, market_id: str, winning_outcome: str):
        """
        Update market with resolution information.

        Args:
            market_id: Market identifier
            winning_outcome: The outcome that won (e.g., "Yes", "No", specific outcome name)
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE markets
            SET resolved = 1,
                winning_outcome = ?,
                resolution_date = ?,
                last_checked = ?
            WHERE market_id = ?
        """, (winning_outcome, datetime.now(), datetime.now(), market_id))

        conn.commit()
        conn.close()

        print(f"[DATABASE] Marked market {market_id} as resolved: {winning_outcome}")

    def get_resolved_markets(self) -> List[Dict]:
        """Get all resolved markets."""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM markets
            WHERE resolved = 1
            AND winning_outcome IS NOT NULL
            AND winning_outcome != ''
        """)

        markets = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return markets

    def get_unresolved_markets(self) -> List[Dict]:
        """Get all unresolved markets that we're tracking."""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT m.market_id, m.title, m.category, m.end_date, m.last_checked
            FROM markets m
            INNER JOIN trades t ON m.market_id = t.market_id
            WHERE (m.resolved = 0 OR m.resolved IS NULL)
            ORDER BY m.last_checked ASC
        """)

        markets = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return markets

    def get_trader_stats(self, address: str) -> Optional[Dict]:
        """Get statistics for a specific trader."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT address, total_trades, successful_trades, win_rate,
                   total_volume, is_flagged
            FROM traders
            WHERE address = ?
        """, (address,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'address': row[0],
                'total_trades': row[1],
                'successful_trades': row[2],
                'win_rate': row[3],
                'total_volume': row[4],
                'is_flagged': bool(row[5])
            }
        return None

    def get_all_flagged_traders_stats(self) -> List[Dict]:
        """Get statistics for all flagged traders."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT address, total_trades, successful_trades, win_rate, total_volume
            FROM traders
            WHERE is_flagged = 1
            ORDER BY win_rate DESC
        """)

        traders = []
        for row in cursor.fetchall():
            traders.append({
                'address': row[0],
                'total_trades': row[1],
                'successful_trades': row[2],
                'win_rate': row[3],
                'total_volume': row[4]
            })

        conn.close()
        return traders

    def market_exists(self, market_id: str) -> bool:
        """Check if a market already exists in the database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM markets WHERE market_id = ? LIMIT 1", (market_id,))
        exists = cursor.fetchone() is not None

        conn.close()
        return exists

    def store_market_from_trade(self, trade: Dict):
        """
        Store market information extracted from a trade.

        Handles different market_id field names: 'market_id', 'id', 'conditionId', 'asset_id'
        """
        # Extract market_id from various possible field names
        market_id = (trade.get('market_id') or
                    trade.get('conditionId') or
                    trade.get('market') or
                    trade.get('id') or
                    trade.get('asset_id'))

        if not market_id:
            return  # Can't store without market_id

        # Check if market already exists
        if self.market_exists(market_id):
            return  # Already stored

        # Extract market information from trade
        title = trade.get('title') or trade.get('market_title') or 'Unknown Market'
        category = trade.get('category') or trade.get('market_category') or 'Unknown'

        # Store the market
        self.update_market(
            market_id=market_id,
            title=title,
            category=category,
            end_date=None,
            resolved=False,
            winning_outcome=None
        )

        print(f"[DATABASE] Stored new market: {market_id[:10]}... - {title[:50]}")

    def store_market_dict(self, market: Dict):
        """
        Store market information from a market dictionary (from get_markets()).

        Handles different market_id field names and extracts all available metadata.
        """
        # Extract market_id from various possible field names
        market_id = (market.get('conditionId') or
                    market.get('market_id') or
                    market.get('id') or
                    market.get('condition_id'))

        if not market_id:
            return  # Can't store without market_id

        # Check if market already exists
        if self.market_exists(market_id):
            return  # Already stored

        # Extract market information
        title = market.get('question') or market.get('title') or 'Unknown Market'
        category = market.get('category') or 'Unknown'

        # Extract end date if available
        end_date = None
        end_date_raw = market.get('endDate') or market.get('end_date')
        if end_date_raw:
            try:
                if isinstance(end_date_raw, (int, float)):
                    end_date = datetime.fromtimestamp(end_date_raw)
                else:
                    end_date = datetime.fromisoformat(str(end_date_raw).replace('Z', '+00:00'))
            except:
                pass

        # Check if market is already resolved
        resolved = market.get('closed', False) or market.get('archived', False)

        # Store the market
        self.update_market(
            market_id=market_id,
            title=title,
            category=category,
            end_date=end_date,
            resolved=resolved,
            winning_outcome=None
        )

        print(f"[DATABASE] Stored new market: {market_id[:10]}... - {title[:50]}")
