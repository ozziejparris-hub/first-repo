#!/usr/bin/env python3
"""
ELO Bridge for Monitoring System

This module bridges the monitoring system (monitoring/*.py) with the
unified ELO system (analysis/unified_elo_system.py) to enable automatic,
continuous ELO updates when markets resolve.

TWO-TIERED APPROACH:
1. Quick Updates (monitoring cycles): Base ELO + P&L + cached modifiers (4/6 dimensions)
2. Full Recalculation (daily): All 6 dimensions including Network + Contrarian

INTEGRATION POINT:
Called from trader_analyzer.py after trade evaluation to update ELO ratings
for traders whose trades were just evaluated.

Author: Monitoring → ELO Integration (Phase 2)
"""

import sys
import os
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import time

# Add analysis directory to path for unified_elo_system import
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(project_root, 'analysis'))

from unified_elo_system import UnifiedELOSystem
from monitoring.position_tracker import PositionTracker


class UnifiedELOMonitoringBridge:
    """
    Bridge class connecting monitoring system to unified ELO system.

    Responsibilities:
    - Update positions for traders after trade evaluation
    - Quick ELO updates during monitoring cycles (4/6 dimensions)
    - Full ELO recalculation for periodic deep analysis (6/6 dimensions)
    - Store updated ELO ratings in database

    Performance Targets:
    - Quick update: <10 seconds for 50-100 traders
    - Full recalculation: <5 minutes for all traders
    """

    def __init__(self, db=None, db_path: str = None):
        """
        Initialize ELO bridge.

        Args:
            db: Existing Database instance (optional)
            db_path: Path to database (optional, uses default if not provided)
        """
        # Import Database here to avoid circular imports
        from .database import Database

        self.db = db or Database(db_path)

        # Cache for UnifiedELOSystem (expensive to initialize)
        self._elo_system = None
        self._elo_system_last_init = None
        self._elo_cache_ttl = timedelta(hours=24)  # Reinitialize daily

        # Cache for base ELO calculations (expensive market resolution checks)
        self._base_elo_last_calculated = None
        self._base_elo_cache_ttl = timedelta(hours=1)  # Recalculate hourly

        # Cache for PositionTracker
        self._position_tracker = None

        # Performance tracking
        self._last_quick_update_duration = None
        self._last_full_update_duration = None

    def _get_elo_system(self, force_refresh: bool = False) -> UnifiedELOSystem:
        """
        Get or create UnifiedELOSystem instance with caching.

        Args:
            force_refresh: Force re-initialization even if cache valid

        Returns:
            UnifiedELOSystem instance
        """
        now = datetime.now()

        # Check if we need to refresh
        needs_refresh = (
            force_refresh or
            self._elo_system is None or
            self._elo_system_last_init is None or
            (now - self._elo_system_last_init) > self._elo_cache_ttl
        )

        if needs_refresh:
            print(f"[ELO_BRIDGE] Initializing UnifiedELOSystem...")
            start = time.time()

            self._elo_system = UnifiedELOSystem()
            self._elo_system_last_init = now

            elapsed = time.time() - start
            print(f"[ELO_BRIDGE] UnifiedELOSystem initialized in {elapsed:.2f}s")

        return self._elo_system

    def _get_position_tracker(self) -> PositionTracker:
        """Get or create PositionTracker instance."""
        if self._position_tracker is None:
            self._position_tracker = PositionTracker(database=self.db)
        return self._position_tracker

    def update_positions_for_traders(self, trader_addresses: List[str],
                                     verbose: bool = False) -> Dict:
        """
        Update positions for specific traders.

        This should be called BEFORE ELO update to ensure P&L data is current.

        Args:
            trader_addresses: List of trader addresses to update
            verbose: Print detailed progress

        Returns:
            Dictionary with update results:
            {
                'traders_processed': int,
                'total_positions_created': int,
                'total_positions_closed': int,
                'errors': List[str],
                'duration_seconds': float
            }
        """
        start_time = time.time()

        if verbose:
            print(f"\n[ELO_BRIDGE] Updating positions for {len(trader_addresses)} traders...")

        tracker = self._get_position_tracker()

        total_positions_created = 0
        total_positions_closed = 0
        errors = []

        for i, trader_address in enumerate(trader_addresses):
            try:
                # Match trades to positions
                positions = tracker.match_trades_for_trader(trader_address)

                if positions:
                    # Store positions in database
                    tracker.store_positions(positions, trader_address)

                    # Count new vs closed
                    closed = sum(1 for p in positions if p.get('status') == 'closed')
                    opened = len(positions) - closed

                    total_positions_created += opened
                    total_positions_closed += closed

                    if verbose and (opened > 0 or closed > 0):
                        print(f"  [{i+1}/{len(trader_addresses)}] {trader_address[:10]}... "
                              f"→ {opened} open, {closed} closed")

            except Exception as e:
                error_msg = f"Position update failed for {trader_address}: {str(e)}"
                errors.append(error_msg)
                if verbose:
                    print(f"  [ERROR] {error_msg}")

        duration = time.time() - start_time

        result = {
            'traders_processed': len(trader_addresses),
            'total_positions_created': total_positions_created,
            'total_positions_closed': total_positions_closed,
            'errors': errors,
            'duration_seconds': duration
        }

        if verbose:
            print(f"[ELO_BRIDGE] Position update complete: "
                  f"{total_positions_created} opened, {total_positions_closed} closed "
                  f"in {duration:.2f}s")

        return result

    # ============================================================
    # BATCH PROCESSING OPTIMIZATION METHODS
    # ============================================================

    def _chunk_list(self, lst: List, chunk_size: int = 50) -> List[List]:
        """
        Split list into chunks of specified size.

        Args:
            lst: List to split
            chunk_size: Maximum size of each chunk

        Returns:
            List of lists (chunks)
        """
        return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

    def _batch_store_elo_results(self, elo_results: Dict[str, Dict]) -> int:
        """
        Store ELO results for multiple traders in a single transaction.

        This is a major performance optimization - instead of committing after
        each trader update, we batch all updates into a single transaction.

        Args:
            elo_results: Dict mapping trader_address -> ELO data

        Returns:
            Number of traders successfully updated
        """
        if not elo_results:
            return 0

        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Prepare batch update data
        updates = []
        for trader_address, elo_data in elo_results.items():
            updates.append((
                elo_data['comprehensive_elo'],
                elo_data['base_category_elo'],
                elo_data['behavioral_modifier'],
                elo_data['advanced_modifier'],
                elo_data['pnl_modifier'],
                datetime.now().isoformat(),
                trader_address
            ))

        # Batch update (SINGLE TRANSACTION - major speedup)
        cursor.executemany("""
            UPDATE traders
            SET
                comprehensive_elo = ?,
                base_category_elo = ?,
                behavioral_modifier = ?,
                advanced_modifier = ?,
                pnl_modifier = ?,
                elo_last_updated = ?
            WHERE address = ?
        """, updates)

        conn.commit()
        updated_count = len(updates)
        conn.close()

        return updated_count

    def _process_trader_chunk(self, elo_system, trader_addresses: List[str],
                              verbose: bool = False) -> Dict:
        """
        Process a chunk of traders with optimized batch operations.

        Args:
            elo_system: UnifiedELOSystem instance
            trader_addresses: List of trader addresses (typically 50 or less)
            verbose: Print progress

        Returns:
            Dict with updated/failed counts and results
        """
        elo_results = {}
        errors = []
        elo_values = []

        for i, trader_address in enumerate(trader_addresses):
            try:
                # Get comprehensive ELO with quick modifiers
                comprehensive_elo = elo_system.get_trader_global_elo(
                    trader_address,
                    apply_behavioral=True,  # Cached
                    apply_advanced=True,     # Cached
                    apply_network=False,     # Skip (expensive)
                    apply_contrarian=False,  # Skip (expensive)
                    apply_pnl=True          # Fresh calculation
                )

                # Get base category ELO (without any modifiers)
                base_category_elo = elo_system.get_trader_global_elo(trader_address)

                # Get component modifiers for storage
                behavioral_data = elo_system.calculate_behavioral_multiplier(trader_address)
                advanced_data = elo_system.calculate_advanced_metrics_multiplier(trader_address)
                pnl_data = elo_system.calculate_pnl_multiplier(trader_address)

                behavioral_modifier = behavioral_data['combined_multiplier']
                advanced_modifier = advanced_data['combined_multiplier']
                pnl_modifier = pnl_data['combined_multiplier']

                # Store in results dict (will be batch-written later)
                elo_results[trader_address] = {
                    'comprehensive_elo': comprehensive_elo,
                    'base_category_elo': base_category_elo,
                    'behavioral_modifier': behavioral_modifier,
                    'advanced_modifier': advanced_modifier,
                    'pnl_modifier': pnl_modifier
                }

                elo_values.append(comprehensive_elo)

                if verbose and (i + 1) % 10 == 0:
                    print(f"  [{i+1}/{len(trader_addresses)}] Processed")

            except Exception as e:
                error_msg = f"ELO calculation failed for {trader_address}: {str(e)}"
                errors.append(error_msg)
                if verbose:
                    print(f"  [ERROR] {error_msg}")

        # Batch store all results (SINGLE DATABASE TRANSACTION)
        updated_count = self._batch_store_elo_results(elo_results)

        return {
            'updated': updated_count,
            'failed': len(trader_addresses) - updated_count,
            'errors': errors,
            'elo_values': elo_values
        }

    def quick_elo_update_for_traders(self, trader_addresses: List[str],
                                     verbose: bool = False,
                                     force_refresh: bool = False,
                                     chunk_size: int = 50) -> Dict:
        """
        Quick ELO update for specific traders (4/6 dimensions).

        Used during monitoring cycles. Updates:
        1. Base category ELO (resolution-based) ✓
        2. Behavioral modifiers (cached, 24h TTL) ✓
        3. Advanced metrics (cached, 24h TTL) ✓
        4. P&L modifiers (fresh calculation) ✓

        Skips:
        5. Network analysis (expensive) ✗
        6. Contrarian analysis (expensive) ✗

        Args:
            trader_addresses: List of trader addresses to update
            verbose: Print detailed progress
            force_refresh: Force ELO system re-initialization
            chunk_size: Number of traders to process per batch (default: 50)

        Returns:
            Dictionary with update results:
            {
                'traders_updated': int,
                'traders_failed': int,
                'avg_elo': float,
                'top_traders': List[Dict],
                'errors': List[str],
                'duration_seconds': float,
                'chunks_processed': int
            }
        """
        start_time = time.time()

        if not trader_addresses:
            return {
                'traders_updated': 0,
                'traders_failed': 0,
                'avg_elo': 0,
                'top_traders': [],
                'errors': [],
                'duration_seconds': 0,
                'chunks_processed': 0
            }

        if verbose:
            print(f"\n[ELO_BRIDGE] Quick ELO update for {len(trader_addresses)} traders...")
            print(f"[ELO_BRIDGE] Using batch processing (chunk size: {chunk_size})")

        # Get ELO system
        elo_system = self._get_elo_system(force_refresh=force_refresh)

        # Check if we need to recalculate base ELO ratings
        now = datetime.now()
        needs_base_elo_recalc = (
            force_refresh or
            self._base_elo_last_calculated is None or
            (now - self._base_elo_last_calculated) > self._base_elo_cache_ttl
        )

        if needs_base_elo_recalc:
            # Calculate base ELO for all traders (expensive: ~200s for 1,946 markets)
            if verbose:
                print("[ELO_BRIDGE] Recalculating base ELO ratings (this may take a few minutes)...")

            try:
                elo_system.calculate_elo_ratings(verbose=verbose)
                self._base_elo_last_calculated = now
            except Exception as e:
                return {
                    'traders_updated': 0,
                    'traders_failed': len(trader_addresses),
                    'errors': [f"Base ELO calculation failed: {str(e)}"],
                    'duration_seconds': time.time() - start_time,
                    'chunks_processed': 0
                }
        else:
            # Use cached base ELO ratings (significant speedup!)
            if verbose:
                age_minutes = int((now - self._base_elo_last_calculated).total_seconds() / 60)
                print(f"[ELO_BRIDGE] Using cached base ELO ratings (age: {age_minutes}m, refreshes every {int(self._base_elo_cache_ttl.total_seconds() / 60)}m)")

        # BATCH PROCESSING: Split into chunks for optimal performance
        chunks = self._chunk_list(trader_addresses, chunk_size)

        traders_updated = 0
        traders_failed = 0
        all_errors = []
        elo_values = []

        for i, chunk in enumerate(chunks, 1):
            if verbose:
                print(f"[ELO_BRIDGE] Processing chunk {i}/{len(chunks)} ({len(chunk)} traders)...")

            try:
                # Process this chunk with batch operations
                chunk_results = self._process_trader_chunk(elo_system, chunk, verbose)

                traders_updated += chunk_results['updated']
                traders_failed += chunk_results['failed']
                all_errors.extend(chunk_results['errors'])
                elo_values.extend(chunk_results['elo_values'])

            except Exception as e:
                print(f"[ELO_BRIDGE] Error processing chunk {i}: {e}")
                traders_failed += len(chunk)
                all_errors.append(f"Chunk {i} failed: {str(e)}")

        duration = time.time() - start_time
        self._last_quick_update_duration = duration

        # Get top traders
        top_traders = self._get_top_traders_from_db(limit=10)

        result = {
            'traders_updated': traders_updated,
            'traders_failed': traders_failed,
            'avg_elo': sum(elo_values) / len(elo_values) if elo_values else 0,
            'top_traders': top_traders,
            'errors': all_errors,
            'duration_seconds': duration,
            'chunks_processed': len(chunks)
        }

        if verbose:
            print(f"[ELO_BRIDGE] Quick ELO update complete: "
                  f"{traders_updated} updated, {traders_failed} failed "
                  f"in {duration:.2f}s ({len(chunks)} chunks)")
            if elo_values:
                per_trader = duration / len(trader_addresses)
                throughput = len(trader_addresses) / duration
                print(f"[ELO_BRIDGE] Performance: {per_trader:.3f}s per trader, "
                      f"{throughput:.1f} traders/second")

        return result

    def full_elo_recalculation(self, verbose: bool = False,
                              force_refresh: bool = True,
                              skip_correlation: bool = False,
                              skip_contrarian: bool = False,
                              skip_advanced_metrics: bool = False) -> Dict:
        """
        Full ELO recalculation for ALL traders (6/6 dimensions).

        Used for periodic deep analysis (daily). Updates:
        1. Base category ELO (resolution-based) ✓
        2. Behavioral modifiers (fresh calculation) ✓
        3. Advanced metrics (fresh calculation) ✓  [skipped if skip_advanced_metrics=True]
        4. Network analysis (fresh calculation) ✓  [skipped if skip_correlation=True]
        5. Contrarian analysis (fresh calculation) ✓  [skipped if skip_contrarian=True]
        6. P&L modifiers (fresh calculation) ✓

        Args:
            verbose: Print detailed progress
            force_refresh: Force ELO system re-initialization (default: True)
            skip_correlation: Skip correlation matrix (8.26M pairs, ~5h). Uses
                cached/neutral scores instead. Reduces runtime to ~15 minutes.
            skip_contrarian: Skip contrarian analysis (internal ELO recalc + market
                resolution pass). Uses neutral modifiers instead.
            skip_advanced_metrics: Skip calibration/risk/regret analysis. Uses
                neutral modifiers (1.0x) instead. Safety valve for analysis errors.

        Returns:
            Dictionary with update results:
            {
                'traders_updated': int,
                'traders_failed': int,
                'avg_elo': float,
                'top_traders': List[Dict],
                'errors': List[str],
                'duration_seconds': float
            }
        """
        start_time = time.time()

        if verbose:
            skipped = [name for flag, name in [
                (skip_correlation, "correlation"),
                (skip_contrarian, "contrarian"),
                (skip_advanced_metrics, "advanced_metrics"),
            ] if flag]
            if skipped:
                label = ", ".join(skipped) + " skipped"
                dims = 6 - len(skipped)
                print(f"\n[ELO_BRIDGE] Starting FULL ELO recalculation ({dims}/6 dimensions, {label})...")
            else:
                print(f"\n[ELO_BRIDGE] Starting FULL ELO recalculation (6/6 dimensions)...")

        # Get ELO system (force refresh to clear caches)
        elo_system = self._get_elo_system(force_refresh=force_refresh)

        # Calculate base ELO for all traders
        if verbose:
            print("[ELO_BRIDGE] Recalculating base ELO ratings...")

        try:
            elo_system.calculate_elo_ratings()
        except Exception as e:
            return {
                'traders_updated': 0,
                'traders_failed': 0,
                'errors': [f"Base ELO calculation failed: {str(e)}"],
                'duration_seconds': time.time() - start_time
            }

        # Get all flagged traders
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT address FROM traders WHERE is_flagged = 1")
        trader_addresses = [row[0] for row in cursor.fetchall()]

        if verbose:
            print(f"[ELO_BRIDGE] Updating {len(trader_addresses)} traders...")

        # Update ELO for each trader
        traders_updated = 0
        traders_failed = 0
        errors = []
        elo_values = []

        for i, trader_address in enumerate(trader_addresses):
            try:
                # Get comprehensive ELO with ALL modifiers
                comprehensive_elo = elo_system.get_trader_global_elo(
                    trader_address,
                    apply_behavioral=True,
                    apply_advanced=not skip_advanced_metrics,
                    apply_network=not skip_correlation,
                    apply_contrarian=not skip_contrarian,
                    apply_pnl=True
                )

                # Get base category ELO (without any modifiers)
                base_category_elo = elo_system.get_trader_global_elo(trader_address)

                # Get component modifiers for storage
                behavioral_data = elo_system.calculate_behavioral_multiplier(trader_address)
                advanced_data = elo_system.calculate_advanced_metrics_multiplier(trader_address)
                pnl_data = elo_system.calculate_pnl_multiplier(trader_address)

                behavioral_modifier = behavioral_data['combined_multiplier']
                advanced_modifier = advanced_data['combined_multiplier']
                pnl_modifier = pnl_data['combined_multiplier']

                # Store in database
                cursor.execute("""
                    UPDATE traders
                    SET comprehensive_elo = ?,
                        base_category_elo = ?,
                        behavioral_modifier = ?,
                        advanced_modifier = ?,
                        pnl_modifier = ?,
                        elo_last_updated = ?
                    WHERE address = ?
                """, (
                    comprehensive_elo,
                    base_category_elo,
                    behavioral_modifier,
                    advanced_modifier,
                    pnl_modifier,
                    datetime.now(),
                    trader_address
                ))

                traders_updated += 1
                elo_values.append(comprehensive_elo)

                if (i + 1) % 500 == 0:
                    conn.commit()
                    if verbose:
                        print(f"  [{i+1}/{len(trader_addresses)}] Updated (batch commit)")

            except Exception as e:
                traders_failed += 1
                error_msg = f"ELO update failed for {trader_address}: {str(e)}"
                errors.append(error_msg)
                if verbose:
                    print(f"  [ERROR] {error_msg}")

        conn.commit()  # final flush for remaining traders
        conn.close()

        duration = time.time() - start_time
        self._last_full_update_duration = duration

        # Get top traders
        top_traders = self._get_top_traders_from_db(limit=10)

        result = {
            'traders_updated': traders_updated,
            'traders_failed': traders_failed,
            'avg_elo': sum(elo_values) / len(elo_values) if elo_values else 0,
            'top_traders': top_traders,
            'errors': errors,
            'duration_seconds': duration
        }

        if verbose:
            print(f"[ELO_BRIDGE] Full ELO recalculation complete: "
                  f"{traders_updated} updated, {traders_failed} failed "
                  f"in {duration:.2f}s ({duration/60:.1f} min)")

        return result

    def get_trader_ranking(self, limit: int = 100,
                          min_elo: float = 0.0) -> List[Dict]:
        """
        Get trader ranking by comprehensive ELO.

        Args:
            limit: Maximum number of traders to return
            min_elo: Minimum ELO threshold

        Returns:
            List of trader dictionaries sorted by comprehensive ELO (descending)
        """
        return self._get_top_traders_from_db(limit=limit, min_elo=min_elo)

    def _get_top_traders_from_db(self, limit: int = 10,
                                  min_elo: float = 0.0) -> List[Dict]:
        """
        Get top traders from database by comprehensive ELO.

        Args:
            limit: Maximum number of traders to return
            min_elo: Minimum ELO threshold

        Returns:
            List of trader dictionaries with ELO data
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                address,
                comprehensive_elo,
                base_category_elo,
                behavioral_modifier,
                advanced_modifier,
                pnl_modifier,
                elo_last_updated,
                total_trades,
                win_rate
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            AND comprehensive_elo >= ?
            ORDER BY comprehensive_elo DESC
            LIMIT ?
        """, (min_elo, limit))

        traders = []
        for row in cursor.fetchall():
            traders.append({
                'address': row[0],
                'comprehensive_elo': row[1],
                'base_category_elo': row[2],
                'behavioral_modifier': row[3],
                'advanced_modifier': row[4],
                'pnl_modifier': row[5],
                'elo_last_updated': row[6],
                'total_trades': row[7],
                'win_rate': row[8]
            })

        conn.close()
        return traders

    def get_performance_stats(self) -> Dict:
        """
        Get performance statistics for the bridge.

        Returns:
            Dictionary with performance metrics
        """
        return {
            'last_quick_update_duration': self._last_quick_update_duration,
            'last_full_update_duration': self._last_full_update_duration,
            'elo_system_cached': self._elo_system is not None,
            'elo_system_age_hours': (
                (datetime.now() - self._elo_system_last_init).total_seconds() / 3600
                if self._elo_system_last_init else None
            )
        }


# CLI for testing and standalone usage
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ELO Bridge - Monitoring → Unified ELO Integration")
    parser.add_argument('--quick-update', action='store_true',
                       help='Run quick ELO update for recently evaluated traders')
    parser.add_argument('--full-recalc', action='store_true',
                       help='Run full ELO recalculation for all traders (6/6 dimensions)')
    parser.add_argument('--update-positions', action='store_true',
                       help='Update positions for recently evaluated traders')
    parser.add_argument('--top', type=int, default=20,
                       help='Show top N traders (default: 20)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')

    args = parser.parse_args()

    bridge = UnifiedELOMonitoringBridge()

    if args.update_positions:
        print("=" * 70)
        print("  POSITION UPDATE")
        print("=" * 70)

        # Get traders with recent evaluated trades
        traders = bridge.db.get_traders_with_recent_evaluated_trades(hours=24)
        print(f"\nFound {len(traders)} traders with recently evaluated trades")

        if traders:
            result = bridge.update_positions_for_traders(traders, verbose=args.verbose)
            print(f"\nResults:")
            print(f"  Traders processed: {result['traders_processed']}")
            print(f"  Positions created: {result['total_positions_created']}")
            print(f"  Positions closed: {result['total_positions_closed']}")
            print(f"  Duration: {result['duration_seconds']:.2f}s")

    elif args.quick_update:
        print("=" * 70)
        print("  QUICK ELO UPDATE (4/6 dimensions)")
        print("=" * 70)

        # Get traders with recent evaluated trades
        traders = bridge.db.get_traders_with_recent_evaluated_trades(hours=24)
        print(f"\nFound {len(traders)} traders with recently evaluated trades")

        if traders:
            result = bridge.quick_elo_update_for_traders(traders, verbose=args.verbose)
            print(f"\nResults:")
            print(f"  Traders updated: {result['traders_updated']}")
            print(f"  Traders failed: {result['traders_failed']}")
            print(f"  Average ELO: {result['avg_elo']:.1f}")
            print(f"  Duration: {result['duration_seconds']:.2f}s")

            if result['top_traders']:
                print(f"\nTop {len(result['top_traders'])} Traders:")
                for i, trader in enumerate(result['top_traders'][:10], 1):
                    print(f"  {i}. {trader['address'][:10]}... "
                          f"ELO: {trader['comprehensive_elo']:.1f} "
                          f"(base: {trader['base_category_elo']:.1f})")

    elif args.full_recalc:
        print("=" * 70)
        print("  FULL ELO RECALCULATION (6/6 dimensions)")
        print("=" * 70)

        result = bridge.full_elo_recalculation(verbose=args.verbose)
        print(f"\nResults:")
        print(f"  Traders updated: {result['traders_updated']}")
        print(f"  Traders failed: {result['traders_failed']}")
        print(f"  Average ELO: {result['avg_elo']:.1f}")
        print(f"  Duration: {result['duration_seconds']:.2f}s ({result['duration_seconds']/60:.1f} min)")

        if result['top_traders']:
            print(f"\nTop {len(result['top_traders'])} Traders:")
            for i, trader in enumerate(result['top_traders'][:20], 1):
                print(f"  {i:2d}. {trader['address'][:10]}... "
                      f"ELO: {trader['comprehensive_elo']:7.1f} "
                      f"(base: {trader['base_category_elo']:6.1f}, "
                      f"WR: {trader['win_rate']*100:5.1f}%)")

    else:
        # Default: Show top traders
        print("=" * 70)
        print(f"  TOP {args.top} TRADERS BY COMPREHENSIVE ELO")
        print("=" * 70)

        top_traders = bridge.get_trader_ranking(limit=args.top)

        if top_traders:
            print(f"\nRank | Address    | Comp ELO | Base ELO | Modifiers (B/A/P) | Trades | Win Rate")
            print("-" * 90)
            for i, trader in enumerate(top_traders, 1):
                print(f"{i:4d} | {trader['address'][:10]} | "
                      f"{trader['comprehensive_elo']:8.1f} | "
                      f"{trader['base_category_elo']:8.1f} | "
                      f"{trader['behavioral_modifier']:.2f}/{trader['advanced_modifier']:.2f}/{trader['pnl_modifier']:.2f} | "
                      f"{trader['total_trades']:6d} | "
                      f"{trader['win_rate']*100:5.1f}%")
        else:
            print("\nNo traders with ELO ratings found.")
            print("Run --full-recalc to calculate ELO ratings.")
