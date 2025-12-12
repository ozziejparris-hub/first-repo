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
                  shares: float, price: float, side: str, timestamp: datetime,
                  outcome_bet: str = None):
        """Add a new trade to the database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Use outcome if outcome_bet not provided
        if outcome_bet is None:
            outcome_bet = outcome

        try:
            cursor.execute("""
                INSERT INTO trades (trade_id, trader_address, market_id, market_title,
                                  market_category, outcome, shares, price, side, timestamp, outcome_bet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trade_id, trader_address, market_id, market_title, market_category,
                  outcome, shares, price, side, timestamp, outcome_bet))

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
                     resolution_date: Optional[datetime] = None,
                     condition_id: Optional[str] = None):
        """Add or update market information."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO markets (market_id, title, category, end_date, resolved,
                               winning_outcome, resolution_date, last_checked, condition_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                title = excluded.title,
                category = excluded.category,
                end_date = excluded.end_date,
                resolved = excluded.resolved,
                winning_outcome = excluded.winning_outcome,
                resolution_date = excluded.resolution_date,
                last_checked = excluded.last_checked,
                condition_id = COALESCE(excluded.condition_id, condition_id)
        """, (market_id, title, category, end_date, resolved, winning_outcome,
              resolution_date, datetime.now(), condition_id))

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
        """
        Get unresolved markets that have trades from flagged traders.

        This ensures we only check resolutions for markets we actually care about.

        NOTE: Joins on condition_id because trades table uses conditionId in market_id field,
        while markets table now uses API-compatible ID in market_id field.
        """
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT
                m.market_id,
                m.api_id,
                m.title,
                m.category,
                m.end_date,
                m.last_checked
            FROM markets m
            INNER JOIN trades t ON m.condition_id = t.market_id
            INNER JOIN traders tr ON t.trader_address = tr.address
            WHERE tr.is_flagged = 1
            AND (m.resolved = 0 OR m.resolved IS NULL)
            ORDER BY m.last_checked ASC
        """)

        markets = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return markets

    def get_trades_for_market(self, market_id: str) -> List[Dict]:
        """Get all trades for a specific market."""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM trades
            WHERE market_id = ?
        """, (market_id,))

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return trades

    def get_resolved_trades_for_trader(self, trader_address: str) -> List[Dict]:
        """Get only trades that have been evaluated (won/lost)."""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM trades
            WHERE trader_address = ?
            AND trade_result IN ('won', 'lost')
        """, (trader_address,))

        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return trades

    def update_trade_result(self, trade_id: str, result: str):
        """Update the trade_result field for a trade."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE trades
            SET trade_result = ?
            WHERE trade_id = ?
        """, (result, trade_id))

        conn.commit()
        conn.close()

    def get_markets_with_trades(self) -> List[str]:
        """Get list of market_ids that have trades from flagged traders."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT t.market_id
            FROM trades t
            INNER JOIN traders tr ON t.trader_address = tr.address
            WHERE tr.is_flagged = 1
        """)

        market_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        return market_ids

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
        """Check if a market already exists in the database by market_id."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM markets WHERE market_id = ? LIMIT 1", (market_id,))
        exists = cursor.fetchone() is not None

        conn.close()
        return exists

    def market_exists_by_condition_id(self, condition_id: str) -> bool:
        """Check if a market already exists in the database by condition_id."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM markets WHERE condition_id = ? LIMIT 1", (condition_id,))
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

        IMPORTANT: Polymarket uses TWO ID types:
        - 'id' field: Used for /markets/{id} API endpoint (e.g., "21742")
        - 'conditionId': Used for matching trades (e.g., "0x1b6f76e5b858...")
        """
        # Extract the API-compatible ID (for /markets/{id} endpoint)
        # Priority: 'id' field first, then fall back to conditionId
        api_id = market.get('id')  # This is what /markets/{id} expects

        # Extract the conditionId (for matching with trades)
        condition_id = market.get('conditionId')

        # We need at least one ID
        if not api_id and not condition_id:
            return  # Can't store without any ID

        # Use api_id as primary market_id (for API calls)
        # Fall back to condition_id if api_id not available
        market_id = api_id or condition_id

        # Check if market already exists (check by either ID)
        if self.market_exists(market_id) or (condition_id and self.market_exists_by_condition_id(condition_id)):
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

        # Store the market with BOTH IDs
        self.update_market(
            market_id=market_id,  # API-compatible ID for resolution checking
            title=title,
            category=category,
            end_date=end_date,
            resolved=resolved,
            winning_outcome=None,
            condition_id=condition_id  # For matching with trades
        )

        print(f"[DATABASE] Stored new market: {market_id[:10]}... - {title[:50]}")

    def migrate_add_api_id_column(self):
        """
        Add api_id column to store numeric market IDs for Gamma API.

        This enables resolution checking for markets stored with conditionId.
        Migration is idempotent (safe to run multiple times).
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # Check if column already exists
            cursor.execute("PRAGMA table_info(markets)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'api_id' not in columns:
                print("Adding api_id column to markets table...")
                cursor.execute("ALTER TABLE markets ADD COLUMN api_id TEXT")

                # Create index for faster lookups
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_markets_api_id
                    ON markets(api_id)
                """)

                conn.commit()
                print("[OK] Added api_id column and index")
            else:
                print("[OK] api_id column already exists")

        except Exception as e:
            print(f"[ERROR] Migration failed: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_market_api_id(self, market_id: str, api_id: str):
        """
        Update the api_id for a market.

        Args:
            market_id: Current market_id (likely conditionId)
            api_id: Numeric API ID to store
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE markets
                SET api_id = ?
                WHERE market_id = ?
            """, (api_id, market_id))

            conn.commit()

        except Exception as e:
            print(f"Error updating api_id for {market_id}: {e}")
            conn.rollback()
        finally:
            conn.close()

    def get_markets_needing_api_id(self, limit: int = None):
        """
        Get markets that don't have an api_id yet.

        Returns:
            List of (market_id, title, condition_id) tuples
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        query = """
            SELECT market_id, title, condition_id
            FROM markets
            WHERE api_id IS NULL OR api_id = ''
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()

        return results

    def get_traders_with_recent_evaluated_trades(self, hours: int = 24) -> List[str]:
        """
        Get list of trader addresses who have had trades evaluated recently.

        This is used to determine which traders need ELO updates after market resolutions.

        Args:
            hours: Look back window in hours (default: 24)

        Returns:
            List of trader addresses with recently evaluated trades
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT t.trader_address
            FROM trades t
            INNER JOIN markets m ON t.market_id = m.condition_id
            WHERE m.resolved = 1
            AND m.resolution_date IS NOT NULL
            AND datetime(m.resolution_date) >= datetime('now', '-' || ? || ' hours')
            AND t.trade_result IN ('won', 'lost')
        """, (hours,))

        traders = [row[0] for row in cursor.fetchall()]
        conn.close()

        return traders
