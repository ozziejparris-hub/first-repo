from typing import List, Dict
import time
from .database import Database
from .polymarket_client import PolymarketClient
from .trader_statistics import TraderStatisticsCalculator
from .trade_evaluator import TradeEvaluator


class TraderAnalyzer:
    """Analyze traders to identify successful ones worth tracking."""

    def __init__(self, db: Database, polymarket: PolymarketClient,
                 min_trades: int = 50, min_volume: float = 10000.0):
        self.db = db
        self.polymarket = polymarket
        self.min_trades = min_trades
        self.min_volume = min_volume  # Minimum $10k traded

    def analyze_and_flag_traders(self, trader_addresses: List[str]) -> int:
        """
        Analyze a list of traders and flag those meeting success criteria.
        Returns the number of newly flagged traders.
        """
        newly_flagged = 0

        for address in trader_addresses:
            # Check if already flagged
            existing = self.db.get_trader_stats(address)
            if existing and existing['is_flagged']:
                continue

            # Analyze trader performance
            print(f"Analyzing trader: {address[:10]}...")
            stats = self.polymarket.analyze_trader_performance(address)

            total_trades = stats['total_trades']
            total_volume = stats['total_volume']
            win_rate = stats['win_rate']  # Keep as 0 for now (placeholder)

            # Flag based on volume AND trade count (not win rate)
            should_flag = (total_trades >= self.min_trades and
                          total_volume >= self.min_volume)

            self.db.add_or_update_trader(
                address=address,
                total_trades=total_trades,
                successful_trades=stats['successful_trades'],
                win_rate=win_rate,  # Store as 0 (placeholder for future)
                total_volume=total_volume,
                is_flagged=should_flag
            )

            if should_flag:
                newly_flagged += 1
                print(f"[FLAG] Flagged trader {address[:10]}... "
                      f"(Volume: ${total_volume:.2f}, Trades: {total_trades})")

        return newly_flagged

    def scan_for_successful_traders(self) -> int:
        """
        Scan geopolitics markets for active traders and identify successful ones.
        Returns the number of newly flagged traders.
        """
        print("Fetching geopolitics markets...")
        markets = self.polymarket.get_markets(category="Geopolitics")
        print(f"Found {len(markets)} geopolitics markets")

        # Store market information from the markets we discovered
        print("Storing market information...")
        for market in markets:
            self.db.store_market_dict(market)

        print("Extracting active traders from markets...")
        traders = self.polymarket.get_active_traders_from_markets(markets)
        print(f"Found {len(traders)} unique traders")

        print("Analyzing traders for success criteria...")
        newly_flagged = self.analyze_and_flag_traders(list(traders))

        return newly_flagged

    def get_flagged_traders_summary(self) -> str:
        """Get a formatted summary of all flagged traders."""
        traders = self.db.get_all_flagged_traders_stats()

        if not traders:
            return "No flagged traders yet."

        summary = f"📊 Currently tracking {len(traders)} successful traders:\n\n"

        for i, trader in enumerate(traders, 1):
            summary += (
                f"{i}. Address: {trader['address'][:10]}...\n"
                f"   Win Rate: {trader['win_rate']:.1f}% | "
                f"Trades: {trader['total_trades']} | "
                f"Volume: ${trader['total_volume']:.2f}\n\n"
            )

        return summary

    def check_market_resolutions(self) -> int:
        """
        Check if any tracked markets have been resolved and update database.
        Should be called periodically (e.g., once per day or every 10 monitoring cycles).

        Returns the number of newly resolved markets.
        """
        print("\n" + "="*70)
        print("[RESOLUTION CHECK] Starting resolution check...")
        print("="*70)

        unresolved_markets = self.db.get_unresolved_markets()
        print(f"[RESOLUTION CHECK] Found {len(unresolved_markets)} unresolved markets to check")

        # Track detailed statistics
        newly_resolved = 0
        markets_checked = 0
        markets_closed = 0
        markets_with_outcomes = 0
        api_failures = 0
        no_data_returned = 0

        for idx, market in enumerate(unresolved_markets, 1):
            market_id = market['market_id']
            market_title = market.get('title', 'Unknown')

            # Show progress every 10 markets or for first 3
            if idx <= 3 or idx % 10 == 0 or idx == len(unresolved_markets):
                print(f"\n[RESOLUTION] Checking market {idx}/{len(unresolved_markets)}: {market_title[:50]}...")
                print(f"[RESOLUTION] Market ID: {market_id}")

            try:
                # Get market details from Polymarket API
                market_data = self.polymarket.get_market(market_id)
                markets_checked += 1

                if not market_data:
                    no_data_returned += 1
                    if idx <= 3:
                        print(f"[RESOLUTION DEBUG] ❌ No data returned from API for market {market_id}")
                    continue

                # DEBUG: Show what API returned (for first 3 markets)
                if idx <= 3:
                    print(f"[RESOLUTION DEBUG] API returned data with keys: {list(market_data.keys())}")
                    print(f"[RESOLUTION DEBUG] Market data sample: {{")
                    for key in ['closed', 'archived', 'active', 'status', 'resolved']:
                        if key in market_data:
                            print(f"[RESOLUTION DEBUG]   '{key}': {market_data[key]}")
                    print(f"[RESOLUTION DEBUG] }}")

                # Check if market is closed/resolved
                closed = market_data.get('closed', False)
                archived = market_data.get('archived', False)

                if idx <= 3:
                    print(f"[RESOLUTION DEBUG] Closed: {closed}, Archived: {archived}")

                if closed or archived:
                    markets_closed += 1
                    print(f"[RESOLUTION] ✓ Market is closed/archived: {market_title[:50]}...")

                    # Try to determine winning outcome
                    outcomes = market_data.get('outcomes', [])
                    winning_outcome = None

                    print(f"[RESOLUTION DEBUG] Found {len(outcomes)} outcomes")

                    # Show outcome details for closed markets
                    for i, outcome in enumerate(outcomes):
                        payout = outcome.get('payoutNumerator', 0)
                        name = outcome.get('name', 'Unknown')
                        print(f"[RESOLUTION DEBUG]   Outcome {i+1}: '{name}' - payoutNumerator: {payout}")

                        # Check if this outcome paid out (payoutNumerator = 1000 means it won)
                        if payout == 1000:
                            winning_outcome = name.lower()
                            print(f"[RESOLUTION DEBUG]   ✓ WINNING OUTCOME: '{winning_outcome}'")
                            break

                    if outcomes:
                        markets_with_outcomes += 1

                    if winning_outcome:
                        # Store resolution in database
                        self.db.update_market_resolution(market_id, winning_outcome)
                        newly_resolved += 1
                        print(f"[RESOLUTION] ✅ Market resolved: {market_title[:50]}... → {winning_outcome}")
                    else:
                        print(f"[RESOLUTION] ⚠️  Market closed but no winning outcome found")
                        print(f"[RESOLUTION DEBUG] Outcomes data: {outcomes}")
                else:
                    # Market still active - only log for first few
                    if idx <= 3:
                        print(f"[RESOLUTION DEBUG] Market still active (not closed/archived)")

                # Rate limiting to avoid overwhelming API
                time.sleep(0.1)

            except Exception as e:
                api_failures += 1
                print(f"[RESOLUTION ERROR] Failed to check market {market_id}: {e}")
                import traceback
                if idx <= 3:
                    print(f"[RESOLUTION DEBUG] Full error traceback:")
                    traceback.print_exc()
                continue

        # Print comprehensive summary
        print("\n" + "="*70)
        print("[RESOLUTION CHECK] Summary:")
        print("="*70)
        print(f"  Total unresolved markets in DB: {len(unresolved_markets)}")
        print(f"  Markets checked via API: {markets_checked}")
        print(f"  API failures: {api_failures}")
        print(f"  No data returned: {no_data_returned}")
        print(f"  Markets marked as closed/archived: {markets_closed}")
        print(f"  Markets with outcomes data: {markets_with_outcomes}")
        print(f"  Markets with winning outcome: {newly_resolved}")
        print(f"  Markets updated in database: {newly_resolved}")
        print("="*70)

        if newly_resolved > 0:
            print(f"[RESOLUTION] ✅ SUCCESS: {newly_resolved} market(s) resolved and stored!")
        elif markets_closed > 0:
            print(f"[RESOLUTION] ⚠️  WARNING: {markets_closed} markets are closed but no winners found")
        else:
            print(f"[RESOLUTION] ℹ️  No resolved markets found this check (normal if markets are long-dated)")

        print("="*70 + "\n")

        # After finding resolved markets, evaluate trades and update trader statistics
        if newly_resolved > 0:
            print("\n" + "="*70)
            print("[POST-RESOLUTION] Evaluating trades and updating trader statistics...")
            print("="*70 + "\n")

            # Step 1: Evaluate trades for newly resolved markets
            evaluator = TradeEvaluator(self.db, self.polymarket)
            eval_results = evaluator.batch_evaluate_resolved_markets(verbose=True)

            print(f"\n[POST-RESOLUTION] Trade evaluation complete:")
            print(f"  Trades evaluated: {eval_results['total_trades']}")
            print(f"  Won: {eval_results['won']}")
            print(f"  Lost: {eval_results['lost']}")

            # Step 2: Recalculate trader statistics based on new results
            if eval_results['total_trades'] > 0:
                print(f"\n[POST-RESOLUTION] Recalculating trader statistics...")
                stats_calculator = TraderStatisticsCalculator(self.db)
                stats_summary = stats_calculator.recalculate_all_flagged_traders(verbose=True)

                print(f"[POST-RESOLUTION] Statistics update complete:")
                print(f"  Traders updated: {stats_summary['traders_updated']}")
                if stats_summary['traders_with_minimum'] > 0:
                    print(f"  Average win rate: {stats_summary['average_win_rate']:.2f}%")

                # Step 3: Update positions and ELO ratings for affected traders
                try:
                    from .elo_bridge import UnifiedELOMonitoringBridge

                    print(f"\n[POST-RESOLUTION] Updating positions and ELO ratings...")

                    # Get traders with recently evaluated trades
                    affected_traders = self.db.get_traders_with_recent_evaluated_trades(hours=24)

                    if affected_traders:
                        print(f"  Found {len(affected_traders)} traders with recently evaluated trades")

                        # Initialize ELO bridge
                        elo_bridge = UnifiedELOMonitoringBridge(self.db)

                        # Update positions first (ensures P&L is current)
                        position_results = elo_bridge.update_positions_for_traders(
                            affected_traders,
                            verbose=False
                        )

                        print(f"  Position update: {position_results['total_positions_closed']} closed, "
                              f"{position_results['total_positions_created']} created")

                        # Quick ELO update (4/6 dimensions for speed)
                        elo_results = elo_bridge.quick_elo_update_for_traders(
                            affected_traders,
                            verbose=False
                        )

                        print(f"  ELO update: {elo_results['traders_updated']} traders updated "
                              f"(avg: {elo_results['avg_elo']:.1f})")

                        if elo_results['top_traders']:
                            top = elo_results['top_traders'][0]
                            print(f"  Top trader: {top['address'][:10]}... "
                                  f"(ELO: {top['comprehensive_elo']:.1f})")

                except Exception as e:
                    # ELO integration failure should not stop monitoring
                    print(f"  [WARN] ELO update failed (continuing): {str(e)}")

            print("="*70 + "\n")

        return newly_resolved
