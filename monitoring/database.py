import sqlite3
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
import json
from functools import wraps


def retry_on_locked(max_retries=3, delay=1):
    """Retry database operations on lock errors."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if 'locked' in str(e).lower() and attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 1))  # Exponential backoff
                        print(f"[DATABASE] Database locked, retrying... (attempt {attempt + 1}/{max_retries})")
                        continue
                    raise
            return None
        return wrapper
    return decorator


class Database:
    """Handle SQLite database operations for tracking traders and trades."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default to data directory in parent folder
            db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'polymarket_tracker.db')
        self.db_path = db_path
        self.init_database()

    def get_connection(self):
        """
        Get database connection with WAL mode enabled for better concurrency.

        WAL (Write-Ahead Logging) allows multiple readers and one writer simultaneously,
        reducing "database is locked" errors.
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # Enable WAL mode for better concurrency (allows multiple readers + 1 writer)
        conn.execute('PRAGMA journal_mode=WAL')
        # Set busy timeout to 30 seconds
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

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

        # Migration: Add P&L tracking columns for background worker
        try:
            cursor.execute("""
                ALTER TABLE traders
                ADD COLUMN pnl_last_updated TIMESTAMP
            """)
            print("[DATABASE] Added 'pnl_last_updated' column to traders table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        try:
            cursor.execute("""
                ALTER TABLE traders
                ADD COLUMN pnl_update_priority INTEGER DEFAULT 0
            """)
            print("[DATABASE] Added 'pnl_update_priority' column to traders table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: Add is_synthetic_close flag to positions table
        try:
            cursor.execute("""
                ALTER TABLE positions ADD COLUMN is_synthetic_close BOOLEAN DEFAULT 0
            """)
            print("[DATABASE] Added 'is_synthetic_close' column to positions table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Create index for efficient P&L worker queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_traders_pnl_priority
            ON traders(pnl_update_priority DESC, pnl_last_updated ASC)
        """)

        # monitor_state table — persists key/value pairs across restarts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitor_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        try:
            conn.commit()
        finally:
            conn.close()

    def get_monitor_state(self, key: str) -> Optional[str]:
        """Return the stored value for key, or None if not set."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM monitor_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def set_monitor_state(self, key: str, value: str) -> None:
        """Persist key/value pair, overwriting any previous value."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO monitor_state (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                           updated_at = excluded.updated_at
        """, (key, value))
        conn.commit()
        conn.close()

    @retry_on_locked(max_retries=3, delay=1)
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

        try:
            conn.commit()
        finally:
            conn.close()

    def get_flagged_traders(self) -> List[str]:
        """Get list of all flagged trader addresses."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT address FROM traders WHERE is_flagged = 1 AND (research_excluded = 0 OR research_excluded IS NULL)")
        traders = [row[0] for row in cursor.fetchall()]

        conn.close()
        return traders

    @retry_on_locked(max_retries=3, delay=1)
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
            # Soft dedup: skip if same economic trade already exists (API can return
            # the same trade with a different trade_id across polling cycles)
            cursor.execute("""
                SELECT 1 FROM trades
                WHERE trader_address = ? AND market_id = ? AND timestamp = ?
                  AND outcome = ? AND shares = ? AND price = ?
                LIMIT 1
            """, (trader_address, market_id, timestamp, outcome, shares, price))
            if cursor.fetchone():
                return False

            cursor.execute("""
                INSERT INTO trades (trade_id, trader_address, market_id, market_title,
                                  market_category, outcome, shares, price, side, timestamp, outcome_bet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trade_id, trader_address, market_id, market_title, market_category,
                  outcome, shares, price, side, timestamp, outcome_bet))

            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Trade already exists (same trade_id)
            return False
        finally:
            conn.close()

    def insert_position(self, position):
        """
        Insert or update a position in the positions table.

        Args:
            position: Position object with to_dict() method or dict
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Convert Position object to dict if needed
        if hasattr(position, 'to_dict'):
            pos_dict = position.to_dict()
        else:
            pos_dict = position

        try:
            # Dedup guard: if a row already exists for the same logical position
            # (same trader/market/outcome/entry_timestamp) but with a different
            # position_id (timezone artifact from the April 2026 server migration),
            # reuse the existing position_id so we update rather than duplicate.
            existing = cursor.execute("""
                SELECT position_id FROM positions
                WHERE trader_address = ? AND market_id = ? AND outcome = ? AND entry_timestamp = ?
                LIMIT 1
            """, (pos_dict['trader_address'], pos_dict['market_id'],
                  pos_dict['outcome'], pos_dict['entry_timestamp'])).fetchone()
            if existing and existing[0] != pos_dict['position_id']:
                pos_dict['position_id'] = existing[0]

            cursor.execute("""
                INSERT OR REPLACE INTO positions (
                    position_id,
                    trader_address,
                    market_id,
                    market_title,
                    outcome,
                    entry_shares,
                    entry_avg_price,
                    entry_total_cost,
                    entry_timestamp,
                    entry_trade_ids,
                    exit_shares,
                    exit_avg_price,
                    exit_total_received,
                    exit_timestamp,
                    exit_trade_ids,
                    realized_pnl,
                    roi_percent,
                    holding_period_hours,
                    status,
                    remaining_shares,
                    last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                pos_dict['position_id'],
                pos_dict['trader_address'],
                pos_dict['market_id'],
                pos_dict['market_title'],
                pos_dict['outcome'],
                pos_dict['entry_shares'],
                pos_dict['entry_avg_price'],
                pos_dict['entry_total_cost'],
                pos_dict['entry_timestamp'],
                pos_dict['entry_trade_ids'],
                pos_dict['exit_shares'],
                pos_dict['exit_avg_price'],
                pos_dict['exit_total_received'],
                pos_dict['exit_timestamp'],
                pos_dict['exit_trade_ids'],
                pos_dict['realized_pnl'],
                pos_dict['roi_percent'],
                pos_dict['holding_period_hours'],
                pos_dict['status'],
                pos_dict['remaining_shares']
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"[DATABASE] Error inserting position: {e}")
            return False
        finally:
            conn.close()

    def mark_trade_notified(self, trade_id: str):
        """Mark a trade as notified."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE trades SET notified = 1 WHERE trade_id = ?", (trade_id,))

        try:
            conn.commit()
        finally:
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

        try:
            conn.commit()
        finally:
            conn.close()

    @retry_on_locked(max_retries=3, delay=1)
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

        try:
            conn.commit()
        finally:
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
            AND (tr.research_excluded = 0 OR tr.research_excluded IS NULL)
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

    @retry_on_locked(max_retries=3, delay=1)
    def update_trade_result(self, trade_id: str, result: str):
        """Update the trade_result field for a trade."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE trades
            SET trade_result = ?
            WHERE trade_id = ?
        """, (result, trade_id))

        try:
            conn.commit()
        finally:
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
              AND (tr.research_excluded = 0 OR tr.research_excluded IS NULL)
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

    def store_market_from_trade(self, trade: Dict, event_category: Optional[str] = None):
        """
        Store market information extracted from a trade.

        Handles different market_id field names: 'market_id', 'id', 'conditionId', 'asset_id'.
        event_category: real category from Gamma /events (preferred over trade-embedded category).
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
        # Prefer the event_category from Gamma /events; fall back to trade-embedded value
        category = event_category or trade.get('category') or trade.get('market_category') or 'Unknown'

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

    def get_top_traders_by_elo(self, limit: int = 10, min_elo: float = 0) -> List[Dict]:
        """
        Get top traders ranked by comprehensive ELO.

        Args:
            limit: Number of traders to return
            min_elo: Minimum ELO threshold

        Returns:
            List of dicts with trader data and rank
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                win_rate,
                realized_pnl,
                avg_roi,
                total_trades,
                closed_positions,
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
                elo_last_updated
            FROM traders
            WHERE is_flagged = 1
            AND (research_excluded = 0 OR research_excluded IS NULL)
            AND comprehensive_elo IS NOT NULL
            AND comprehensive_elo >= ?
            ORDER BY comprehensive_elo DESC
            LIMIT ?
        """, (min_elo, limit))

        traders = []
        for i, row in enumerate(cursor.fetchall(), 1):
            traders.append({
                'rank': i,
                'address': row[0],
                'comprehensive_elo': row[1],
                'base_category_elo': row[2],
                'win_rate': row[3] or 0,
                'realized_pnl': row[4] or 0,
                'avg_roi': row[5] or 0,
                'total_trades': row[6] or 0,
                'closed_positions': row[7] or 0,
                'behavioral_modifier': row[8] or 1.0,
                'advanced_modifier': row[9] or 1.0,
                'pnl_modifier': row[10] or 1.0,
                'elo_last_updated': row[11]
            })

        conn.close()
        return traders

    def get_trader_rank(self, trader_address: str) -> Optional[Dict]:
        """
        Get specific trader's rank and details.

        Returns:
            Dict with rank, elo, and other stats, or None if not found
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Get trader's ELO
        cursor.execute("""
            SELECT comprehensive_elo
            FROM traders
            WHERE address = ?
        """, (trader_address,))

        result = cursor.fetchone()
        if not result or result[0] is None:
            conn.close()
            return None

        trader_elo = result[0]

        # Count how many traders have higher ELO
        cursor.execute("""
            SELECT COUNT(*) + 1
            FROM traders
            WHERE is_flagged = 1
            AND (research_excluded = 0 OR research_excluded IS NULL)
            AND comprehensive_elo > ?
        """, (trader_elo,))

        rank = cursor.fetchone()[0]

        # Get trader details
        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                win_rate,
                realized_pnl,
                avg_roi,
                total_trades
            FROM traders
            WHERE address = ?
        """, (trader_address,))

        row = cursor.fetchone()
        conn.close()

        return {
            'rank': rank,
            'address': row[0],
            'comprehensive_elo': row[1],
            'base_category_elo': row[2],
            'win_rate': row[3] or 0,
            'realized_pnl': row[4] or 0,
            'avg_roi': row[5] or 0,
            'total_trades': row[6] or 0
        }

    def get_elite_traders(self, min_elo: float = 1800) -> List[Dict]:
        """Get all traders above ELO threshold."""
        return self.get_top_traders_by_elo(limit=1000, min_elo=min_elo)

    def is_elite_trader(self, trader_address: str, min_elo: float = 1800) -> bool:
        """Check if trader is in elite tier."""
        rank_data = self.get_trader_rank(trader_address)
        if not rank_data:
            return False
        return rank_data['comprehensive_elo'] >= min_elo

    def get_trader_win_streak(self, trader_address: str, min_streak: int = 3) -> Optional[Dict]:
        """
        Get trader's current win streak.

        Args:
            trader_address: Trader address
            min_streak: Minimum streak to return

        Returns:
            Dict with streak info or None
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Get recent trades in reverse chronological order
        cursor.execute("""
            SELECT trade_result
            FROM trades
            WHERE trader_address = ?
            AND trade_result IS NOT NULL
            ORDER BY last_updated DESC
            LIMIT 20
        """, (trader_address,))

        results = [row[0] for row in cursor.fetchall()]
        conn.close()

        if not results:
            return None

        # Count consecutive wins from most recent
        streak = 0
        for result in results:
            if result == 'won':
                streak += 1
            else:
                break

        if streak >= min_streak:
            return {
                'streak': streak,
                'recent_results': results[:10]
            }

        return None

    def get_traders_needing_pnl_update(self, limit: int = 10) -> list:
        """
        Get traders that need P&L updates, prioritized by:
        1. Traders with trades in last hour (highest priority)
        2. Traders with stale P&L (>24h since last update)
        3. Traders never updated
        4. Traders with oldest updates

        Args:
            limit: Maximum number of traders to return

        Returns:
            List of (trader_address, last_trade_time, last_pnl_update) tuples
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT trader_address, last_trade, pnl_last_updated
            FROM (
                -- Branch 1: traders with trades in last 30 days
                SELECT
                    t.trader_address,
                    MAX(t.timestamp) as last_trade,
                    tr.pnl_last_updated
                FROM trades t
                LEFT JOIN traders tr ON t.trader_address = tr.address
                WHERE t.timestamp > datetime('now', '-30 days')
                GROUP BY t.trader_address

                UNION

                -- Branch 2: traders never processed, regardless of trade age
                SELECT
                    tr.address as trader_address,
                    NULL as last_trade,
                    tr.pnl_last_updated
                FROM traders tr
                WHERE tr.pnl_last_updated IS NULL
            )
            ORDER BY
                CASE
                    -- Priority 1: Recent trades (last hour)
                    WHEN last_trade > datetime('now', '-1 hour') THEN 1
                    -- Priority 2: Never updated
                    WHEN pnl_last_updated IS NULL THEN 2
                    -- Priority 3: Stale P&L (>24h old)
                    WHEN pnl_last_updated < datetime('now', '-24 hours') THEN 3
                    -- Priority 4: Everything else
                    ELSE 4
                END,
                pnl_last_updated ASC NULLS FIRST,
                last_trade DESC
            LIMIT ?
        """, (limit,))

        results = cursor.fetchall()
        conn.close()
        return results

    def get_priority1_traders(self, limit: int) -> list:
        """Traders with a trade in the last hour — highest priority."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.trader_address, MAX(t.timestamp) as last_trade, tr.pnl_last_updated,
                   COALESCE(tr.closed_positions, 0) AS closed_positions
            FROM trades t
            LEFT JOIN traders tr ON t.trader_address = tr.address
            WHERE t.timestamp > datetime('now', '-1 hour')
            GROUP BY t.trader_address
            ORDER BY last_trade DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        conn.close()
        return results

    def get_backlog_traders(self, limit: int, exclude: list = None) -> list:
        """Traders never updated or stale >24 h, excluding any addresses already in the batch."""
        conn = self.get_connection()
        cursor = conn.cursor()
        exclude = exclude or []
        # Build exclusion clause only when there are addresses to exclude.
        # NOT IN (NULL) evaluates to UNKNOWN in SQLite and would filter everything.
        if exclude:
            ph = ','.join('?' * len(exclude))
            excl_clause = f"AND tr.address NOT IN ({ph})"
            excl_clause2 = f"AND t.trader_address NOT IN ({ph})"
            params = (*exclude, *exclude, limit)
        else:
            excl_clause = ""
            excl_clause2 = ""
            params = (limit,)
        cursor.execute(f"""
            SELECT trader_address, last_trade, pnl_last_updated, closed_positions
            FROM (
                -- never-updated traders from the traders table
                SELECT tr.address AS trader_address,
                       NULL      AS last_trade,
                       tr.pnl_last_updated,
                       COALESCE(tr.closed_positions, 0) AS closed_positions
                FROM traders tr
                WHERE tr.pnl_last_updated IS NULL
                  {excl_clause}

                UNION

                -- stale traders (>24 h since last update) with any-age trades
                SELECT t.trader_address,
                       MAX(t.timestamp) AS last_trade,
                       tr.pnl_last_updated,
                       COALESCE(tr.closed_positions, 0) AS closed_positions
                FROM trades t
                INNER JOIN traders tr ON t.trader_address = tr.address
                WHERE tr.pnl_last_updated < datetime('now', '-24 hours')
                  {excl_clause2}
                GROUP BY t.trader_address
            )
            ORDER BY pnl_last_updated ASC NULLS FIRST
            LIMIT ?
        """, params)
        results = cursor.fetchall()
        conn.close()
        return results

    def mark_trader_pnl_updated(self, trader_address: str):
        """
        Mark trader's P&L as recently updated.

        Args:
            trader_address: Trader address
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE traders
            SET pnl_last_updated = datetime('now')
            WHERE address = ?
        """, (trader_address,))

        try:
            conn.commit()
        finally:
            conn.close()

    def get_pnl_worker_stats(self) -> dict:
        """
        Get statistics about P&L update status.

        Returns:
            Dict with stats about P&L updates
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Total traders with trades in last 30 days
        cursor.execute("""
            SELECT COUNT(DISTINCT trader_address)
            FROM trades
            WHERE timestamp > datetime('now', '-30 days')
        """)
        total_active = cursor.fetchone()[0]

        # Traders never updated
        cursor.execute("""
            SELECT COUNT(DISTINCT t.trader_address)
            FROM trades t
            LEFT JOIN traders tr ON t.trader_address = tr.address
            WHERE t.timestamp > datetime('now', '-30 days')
              AND tr.pnl_last_updated IS NULL
        """)
        never_updated = cursor.fetchone()[0]

        # Traders with stale P&L (>24h)
        cursor.execute("""
            SELECT COUNT(DISTINCT t.trader_address)
            FROM trades t
            INNER JOIN traders tr ON t.trader_address = tr.address
            WHERE t.timestamp > datetime('now', '-30 days')
              AND tr.pnl_last_updated < datetime('now', '-24 hours')
        """)
        stale = cursor.fetchone()[0]

        # Traders updated in last hour
        cursor.execute("""
            SELECT COUNT(DISTINCT t.trader_address)
            FROM trades t
            INNER JOIN traders tr ON t.trader_address = tr.address
            WHERE t.timestamp > datetime('now', '-30 days')
              AND tr.pnl_last_updated > datetime('now', '-1 hour')
        """)
        recently_updated = cursor.fetchone()[0]

        conn.close()

        return {
            'total_active_traders': total_active,
            'never_updated': never_updated,
            'stale_pnl': stale,
            'recently_updated': recently_updated,
            'up_to_date': total_active - never_updated - stale
        }

    def get_resolved_markets_for_trader(self, trader_address: str) -> List[Dict]:
        """
        Get resolved markets where a trader has open BUY positions.

        Returns markets whose condition_id appears in the trader's trades table
        and where the market is resolved with a known winning_outcome.

        NOTE: trades.market_id stores the market's conditionId —
        joined on markets.condition_id.

        Returns:
            List of dicts with keys: market_id (conditionId), winning_outcome, resolution_date
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT
                m.condition_id AS market_id,
                m.winning_outcome,
                m.resolution_date
            FROM markets m
            INNER JOIN trades t ON m.condition_id = t.market_id
            WHERE t.trader_address = ?
              AND m.resolved = 1
              AND m.winning_outcome IS NOT NULL
              AND m.winning_outcome != ''
              AND m.condition_id IS NOT NULL
        """, (trader_address,))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'market_id': row[0],
                'winning_outcome': row[1],
                'resolution_date': row[2],
            }
            for row in rows
        ]
