"""
Trade Evaluator - Determines trade success based on market resolutions.
"""

from typing import Dict, List
import json


class TradeEvaluator:
    """Evaluates trade success based on market resolutions."""

    def __init__(self, database, polymarket_client):
        self.db = database
        self.client = polymarket_client

    def evaluate_trade(self, trade: Dict, winning_outcome: str) -> str:
        """
        Determine if a trade won or lost.

        Args:
            trade: Trade dict with 'outcome_bet' or 'outcome' field
            winning_outcome: The outcome that won (from market resolution)

        Returns:
            "won" | "lost" | "invalid"
        """
        # Extract what outcome they bet on (prefer outcome_bet if available)
        trade_outcome = trade.get('outcome_bet') or trade.get('outcome', '')
        trade_outcome = str(trade_outcome).strip().lower()
        winning_outcome = str(winning_outcome).strip().lower()

        if not trade_outcome or not winning_outcome:
            return "invalid"

        # Handle side (BUY = betting on outcome, SELL = betting against)
        side = trade.get('side', 'buy').lower()

        if side == 'buy':
            # They bought the outcome - they win if it matches
            result = "won" if trade_outcome == winning_outcome else "lost"
        else:  # sell
            # They sold (bet against) - they win if it doesn't match
            result = "won" if trade_outcome != winning_outcome else "lost"

        return result

    def evaluate_market_trades(self, market_id: str, winning_outcome: str,
                               verbose: bool = True) -> Dict:
        """
        Evaluate all trades for a resolved market.

        Args:
            market_id: Market identifier
            winning_outcome: The outcome that won
            verbose: Print detailed logs

        Returns:
            {
                'market_id': str,
                'winning_outcome': str,
                'evaluated': int,
                'won': int,
                'lost': int,
                'invalid': int,
                'errors': int
            }
        """
        trades = self.db.get_trades_for_market(market_id)

        stats = {
            'market_id': market_id,
            'winning_outcome': winning_outcome,
            'evaluated': 0,
            'won': 0,
            'lost': 0,
            'invalid': 0,
            'errors': 0
        }

        if verbose and trades:
            print(f"\n[EVALUATOR] Market {market_id[:16]}... - Winner: '{winning_outcome}'")
            print(f"[EVALUATOR] Evaluating {len(trades)} trades...")

        for trade in trades:
            try:
                result = self.evaluate_trade(trade, winning_outcome)

                # Update trade in database
                trade_id = trade['trade_id']
                self.db.update_trade_result(trade_id, result)

                stats['evaluated'] += 1

                if result == 'won':
                    stats['won'] += 1
                elif result == 'lost':
                    stats['lost'] += 1
                elif result == 'invalid':
                    stats['invalid'] += 1

                if verbose:
                    outcome_bet = trade.get('outcome_bet') or trade.get('outcome', 'N/A')
                    side = trade.get('side', 'N/A')
                    print(f"  Trade {trade_id[:16]}... | Bet: '{outcome_bet}' ({side}) -> {result.upper()}")

            except Exception as e:
                stats['errors'] += 1
                print(f"[ERROR] Evaluating trade {trade.get('trade_id', 'unknown')}: {e}")

        return stats

    def batch_evaluate_resolved_markets(self, limit: int = None,
                                       verbose: bool = True) -> Dict:
        """
        Evaluate all resolved markets that haven't been processed yet.

        Args:
            limit: Maximum number of markets to process (None = all)
            verbose: Print progress

        Returns:
            {
                'markets_processed': int,
                'total_trades': int,
                'won': int,
                'lost': int,
                'invalid': int,
                'errors': int
            }
        """
        # Get resolved markets
        resolved_markets = self.db.get_resolved_markets()

        if limit:
            resolved_markets = resolved_markets[:limit]

        if verbose:
            print(f"\n{'='*70}")
            print(f"BATCH TRADE EVALUATION")
            print(f"{'='*70}")
            print(f"Processing {len(resolved_markets)} resolved markets...\n")

        summary = {
            'markets_processed': 0,
            'total_trades': 0,
            'won': 0,
            'lost': 0,
            'invalid': 0,
            'errors': 0
        }

        for i, market in enumerate(resolved_markets, 1):
            market_id = market['market_id']
            winning_outcome = market.get('winning_outcome')

            if not winning_outcome:
                continue

            # Evaluate this market's trades
            result = self.evaluate_market_trades(
                market_id,
                winning_outcome,
                verbose=False  # Quiet for batch processing
            )

            summary['markets_processed'] += 1
            summary['total_trades'] += result['evaluated']
            summary['won'] += result['won']
            summary['lost'] += result['lost']
            summary['invalid'] += result['invalid']
            summary['errors'] += result['errors']

            if verbose and i % 10 == 0:
                print(f"[PROGRESS] Processed {i}/{len(resolved_markets)} markets...")

        if verbose:
            print(f"\n{'='*70}")
            print("BATCH EVALUATION COMPLETE")
            print(f"{'='*70}")
            print(f"Markets processed: {summary['markets_processed']}")
            print(f"Total trades evaluated: {summary['total_trades']}")
            print(f"  Won: {summary['won']}")
            print(f"  Lost: {summary['lost']}")
            print(f"  Invalid: {summary['invalid']}")
            print(f"  Errors: {summary['errors']}")
            print(f"{'='*70}\n")

        return summary
