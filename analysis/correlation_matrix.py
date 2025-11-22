#!/usr/bin/env python3
"""
Trader Correlation Matrix Analysis Tool

Analyzes trading pattern correlations between traders to:
1. Detect copy trading networks
2. Validate signal independence
3. Find coordinated trading groups
4. Identify truly independent alpha traders
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
import csv

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitoring.database import Database


class TraderCorrelationMatrix:
    """
    Analyzes trading pattern correlations between traders.

    Correlation methodology uses three weighted dimensions:
    - Market Overlap (30%): How many same markets do they trade?
    - Outcome Agreement (50%): Do they bet on same outcomes?
    - Timing Similarity (20%): Do they trade at similar times?
    """

    def __init__(self, db_path: str = None):
        """Initialize with database connection."""
        if db_path:
            self.db = Database(db_path)
        else:
            self.db = Database()

        self.correlation_cache = {}  # Cache results to avoid recomputation
        self.trader_trades_cache = {}  # Cache trader trades

    def _get_trader_trades(self, trader_address: str) -> List[Dict]:
        """
        Get all trades for a trader (with caching).

        Returns:
            List of trades with market_id, outcome, timestamp, side
        """
        if trader_address in self.trader_trades_cache:
            return self.trader_trades_cache[trader_address]

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT market_id, outcome, timestamp, side, shares, price
            FROM trades
            WHERE trader_address = ?
            ORDER BY timestamp
        """, (trader_address,))

        trades = []
        for row in cursor.fetchall():
            trades.append({
                'market_id': row[0],
                'outcome': row[1],
                'timestamp': row[2],
                'side': row[3],
                'shares': row[4],
                'price': row[5]
            })

        conn.close()

        self.trader_trades_cache[trader_address] = trades
        return trades

    def _calculate_market_overlap(self, trader_a_markets: set, trader_b_markets: set) -> float:
        """
        Calculate market overlap score (0-1).

        Formula: shared_markets / total_markets_either_traded
        """
        if not trader_a_markets or not trader_b_markets:
            return 0.0

        shared = trader_a_markets & trader_b_markets
        total = trader_a_markets | trader_b_markets

        return len(shared) / len(total) if total else 0.0

    def _calculate_outcome_agreement(self, trades_a: List[Dict], trades_b: List[Dict]) -> Tuple[float, int]:
        """
        Calculate outcome agreement score (0-1) for shared markets.

        Returns:
            (agreement_score, shared_markets_count)
        """
        # Group trades by market
        markets_a = defaultdict(list)
        markets_b = defaultdict(list)

        for trade in trades_a:
            markets_a[trade['market_id']].append(trade)

        for trade in trades_b:
            markets_b[trade['market_id']].append(trade)

        # Find shared markets
        shared_markets = set(markets_a.keys()) & set(markets_b.keys())

        if not shared_markets:
            return 0.0, 0

        agreements = 0
        total = 0

        for market_id in shared_markets:
            # Get most common outcome for each trader in this market
            outcomes_a = [t['outcome'] for t in markets_a[market_id]]
            outcomes_b = [t['outcome'] for t in markets_b[market_id]]

            # Use most frequent outcome
            most_common_a = max(set(outcomes_a), key=outcomes_a.count)
            most_common_b = max(set(outcomes_b), key=outcomes_b.count)

            if most_common_a.lower() == most_common_b.lower():
                agreements += 1

            total += 1

        return agreements / total if total > 0 else 0.0, len(shared_markets)

    def _calculate_timing_similarity(self, trades_a: List[Dict], trades_b: List[Dict]) -> float:
        """
        Calculate timing similarity score (0-1) for shared markets.

        Formula: 1 - min(avg_time_diff_hours / 24, 1.0)
        """
        # Group trades by market
        markets_a = defaultdict(list)
        markets_b = defaultdict(list)

        for trade in trades_a:
            markets_a[trade['market_id']].append(trade)

        for trade in trades_b:
            markets_b[trade['market_id']].append(trade)

        # Find shared markets
        shared_markets = set(markets_a.keys()) & set(markets_b.keys())

        if not shared_markets:
            return 0.0

        time_diffs = []

        for market_id in shared_markets:
            # Get earliest trade timestamp for each trader
            times_a = [datetime.fromisoformat(str(t['timestamp']).replace('Z', '+00:00')) if 'Z' in str(t['timestamp']) else datetime.fromisoformat(str(t['timestamp'])) for t in markets_a[market_id]]
            times_b = [datetime.fromisoformat(str(t['timestamp']).replace('Z', '+00:00')) if 'Z' in str(t['timestamp']) else datetime.fromisoformat(str(t['timestamp'])) for t in markets_b[market_id]]

            earliest_a = min(times_a)
            earliest_b = min(times_b)

            # Calculate time difference in hours
            diff_seconds = abs((earliest_a - earliest_b).total_seconds())
            diff_hours = diff_seconds / 3600

            time_diffs.append(diff_hours)

        if not time_diffs:
            return 0.0

        avg_diff_hours = sum(time_diffs) / len(time_diffs)

        # Convert to similarity score (1.0 = same time, 0.0 = 24+ hours apart)
        similarity = 1.0 - min(avg_diff_hours / 24.0, 1.0)

        return similarity

    def calculate_pairwise_correlation(self, trader_a: str, trader_b: str) -> Dict:
        """
        Calculate correlation between two traders.

        Returns:
            {
                'market_overlap': float (0-1),
                'outcome_agreement': float (0-1),
                'timing_similarity': float (0-1),
                'correlation_score': float (0-1),
                'shared_markets': int,
                'total_interactions': int
            }
        """
        # Check cache
        cache_key = tuple(sorted([trader_a, trader_b]))
        if cache_key in self.correlation_cache:
            return self.correlation_cache[cache_key]

        # Get trades for both traders
        trades_a = self._get_trader_trades(trader_a)
        trades_b = self._get_trader_trades(trader_b)

        if not trades_a or not trades_b:
            return {
                'market_overlap': 0.0,
                'outcome_agreement': 0.0,
                'timing_similarity': 0.0,
                'correlation_score': 0.0,
                'shared_markets': 0,
                'total_interactions': 0
            }

        # Get unique markets
        markets_a = set(t['market_id'] for t in trades_a)
        markets_b = set(t['market_id'] for t in trades_b)

        # Calculate three dimensions
        market_overlap = self._calculate_market_overlap(markets_a, markets_b)
        outcome_agreement, shared_markets = self._calculate_outcome_agreement(trades_a, trades_b)
        timing_similarity = self._calculate_timing_similarity(trades_a, trades_b)

        # Calculate weighted correlation score
        # Weights: Market Overlap (30%), Outcome Agreement (50%), Timing (20%)
        correlation_score = (
            (market_overlap * 0.3) +
            (outcome_agreement * 0.5) +
            (timing_similarity * 0.2)
        )

        result = {
            'market_overlap': round(market_overlap, 3),
            'outcome_agreement': round(outcome_agreement, 3),
            'timing_similarity': round(timing_similarity, 3),
            'correlation_score': round(correlation_score, 3),
            'shared_markets': shared_markets,
            'total_interactions': len(markets_a | markets_b)
        }

        # Cache result
        self.correlation_cache[cache_key] = result

        return result

    def build_correlation_matrix(self, min_shared_markets: int = 3) -> Dict:
        """
        Build full NxN correlation matrix for all traders.

        Args:
            min_shared_markets: Minimum shared markets to calculate correlation

        Returns:
            {
                'matrix': Dict[trader_pair, correlation_score],
                'trader_list': List[trader_addresses],
                'avg_correlations': Dict[trader, avg_correlation]
            }
        """
        print("[CORRELATION MATRIX] Building correlation matrix...")

        # Get all flagged traders
        traders = self.db.get_flagged_traders()
        print(f"[CORRELATION MATRIX] Analyzing {len(traders)} traders...")

        matrix = {}
        trader_correlations = defaultdict(list)

        total_pairs = (len(traders) * (len(traders) - 1)) // 2
        calculated = 0

        # Calculate correlation for each pair
        for i, trader_a in enumerate(traders):
            for trader_b in traders[i+1:]:
                calculated += 1
                if calculated % 50 == 0:
                    print(f"[CORRELATION MATRIX] Progress: {calculated}/{total_pairs} pairs...")

                corr = self.calculate_pairwise_correlation(trader_a, trader_b)

                # Only include if meets minimum shared markets
                if corr['shared_markets'] >= min_shared_markets:
                    pair_key = (trader_a, trader_b)
                    matrix[pair_key] = corr['correlation_score']

                    # Track for average calculation
                    trader_correlations[trader_a].append(corr['correlation_score'])
                    trader_correlations[trader_b].append(corr['correlation_score'])

        # Calculate average correlation per trader
        avg_correlations = {}
        for trader, correlations in trader_correlations.items():
            if correlations:
                avg_correlations[trader] = round(sum(correlations) / len(correlations), 3)
            else:
                avg_correlations[trader] = 0.0

        print(f"[CORRELATION MATRIX] Calculated {len(matrix)} trader pairs")

        return {
            'matrix': matrix,
            'trader_list': traders,
            'avg_correlations': avg_correlations
        }

    def identify_correlation_clusters(self, threshold: float = 0.6) -> List[Dict]:
        """
        Find groups of highly correlated traders.

        Args:
            threshold: Minimum correlation to be in cluster (default 0.6)

        Returns:
            List of clusters
        """
        print(f"[CLUSTERS] Identifying clusters (threshold={threshold})...")

        matrix_data = self.build_correlation_matrix()
        matrix = matrix_data['matrix']

        # Build adjacency list for traders with high correlation
        adjacency = defaultdict(set)
        for (trader_a, trader_b), score in matrix.items():
            if score >= threshold:
                adjacency[trader_a].add(trader_b)
                adjacency[trader_b].add(trader_a)

        # Find clusters using simple connected components
        visited = set()
        clusters = []
        cluster_id = 0

        for trader in adjacency.keys():
            if trader in visited:
                continue

            # BFS to find all connected traders
            cluster = set()
            queue = [trader]

            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue

                visited.add(current)
                cluster.add(current)

                for neighbor in adjacency[current]:
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(cluster) > 1:  # Only clusters with 2+ traders
                # Calculate avg correlation within cluster
                correlations = []
                cluster_list = list(cluster)
                for i, t1 in enumerate(cluster_list):
                    for t2 in cluster_list[i+1:]:
                        pair = tuple(sorted([t1, t2]))
                        if pair in matrix:
                            correlations.append(matrix[pair])

                avg_corr = sum(correlations) / len(correlations) if correlations else 0.0

                # Classify cluster type
                if avg_corr >= 0.8:
                    cluster_type = "SUSPICIOUS (Very High)"
                elif avg_corr >= 0.7:
                    cluster_type = "TIGHT"
                else:
                    cluster_type = "LOOSE"

                clusters.append({
                    'cluster_id': cluster_id,
                    'traders': sorted(list(cluster)),
                    'size': len(cluster),
                    'avg_correlation': round(avg_corr, 3),
                    'cluster_type': cluster_type
                })

                cluster_id += 1

        # Sort by avg correlation (highest first)
        clusters.sort(key=lambda x: x['avg_correlation'], reverse=True)

        print(f"[CLUSTERS] Found {len(clusters)} correlation clusters")

        return clusters

    def find_independent_traders(self, threshold: float = 0.25) -> List[Dict]:
        """
        Identify traders with low correlation to others.

        Args:
            threshold: Max avg correlation to be considered independent

        Returns:
            List of independent traders
        """
        print(f"[INDEPENDENT] Finding independent traders (threshold={threshold})...")

        matrix_data = self.build_correlation_matrix()
        avg_correlations = matrix_data['avg_correlations']
        matrix = matrix_data['matrix']

        independent = []

        for trader, avg_corr in avg_correlations.items():
            if avg_corr <= threshold:
                # Find max correlation with any other trader
                max_corr = 0.0
                for (t1, t2), score in matrix.items():
                    if trader in (t1, t2):
                        max_corr = max(max_corr, score)

                # Calculate independence score (0-100)
                independence_score = int((1.0 - avg_corr) * 100)

                # Get trader stats
                trades = self._get_trader_trades(trader)
                markets = len(set(t['market_id'] for t in trades))

                independent.append({
                    'trader_address': trader,
                    'avg_correlation': round(avg_corr, 3),
                    'max_correlation': round(max_corr, 3),
                    'independence_score': independence_score,
                    'total_markets': markets
                })

        # Sort by independence score (highest first)
        independent.sort(key=lambda x: x['independence_score'], reverse=True)

        print(f"[INDEPENDENT] Found {len(independent)} independent traders")

        return independent

    def analyze_trader_relationships(self, trader_address: str) -> Dict:
        """
        Analyze a specific trader's correlations.

        Returns comprehensive correlation analysis for one trader
        """
        matrix_data = self.build_correlation_matrix()
        matrix = matrix_data['matrix']
        avg_correlations = matrix_data['avg_correlations']

        # Get all correlations involving this trader
        trader_correlations = []
        for (t1, t2), score in matrix.items():
            if trader_address == t1:
                trader_correlations.append((t2, score))
            elif trader_address == t2:
                trader_correlations.append((t1, score))

        # Sort by correlation score
        trader_correlations.sort(key=lambda x: x[1], reverse=True)

        # Get most and least similar
        most_similar = trader_correlations[:5] if len(trader_correlations) >= 5 else trader_correlations
        least_similar = trader_correlations[-5:] if len(trader_correlations) >= 5 else trader_correlations

        # Check cluster membership
        clusters = self.identify_correlation_clusters()
        cluster_membership = None
        for cluster in clusters:
            if trader_address in cluster['traders']:
                cluster_membership = f"Cluster {cluster['cluster_id']} ({cluster['cluster_type']})"
                break

        # Calculate independence rank
        independent_traders = self.find_independent_traders(threshold=1.0)  # Get all
        rank = None
        for i, trader in enumerate(independent_traders, 1):
            if trader['trader_address'] == trader_address:
                rank = i
                break

        return {
            'trader_address': trader_address,
            'avg_correlation': avg_correlations.get(trader_address, 0.0),
            'most_similar': most_similar,
            'least_similar': least_similar,
            'independence_rank': rank,
            'cluster_membership': cluster_membership,
            'total_correlations': len(trader_correlations)
        }

    def generate_reports(self, output_dir: str):
        """
        Generate correlation analysis reports.

        Creates:
        1. correlation_matrix_YYYYMMDD.csv - Full matrix
        2. correlation_clusters_YYYYMMDD.csv - Identified clusters
        3. independent_traders_YYYYMMDD.csv - Low correlation traders
        4. correlation_summary_YYYYMMDD.txt - Analysis summary
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d')

        print(f"\n[REPORTS] Generating correlation reports in {output_dir}...")

        # Build data
        matrix_data = self.build_correlation_matrix()
        clusters = self.identify_correlation_clusters()
        independent = self.find_independent_traders()

        # 1. Correlation Matrix CSV
        matrix_file = os.path.join(output_dir, f'correlation_matrix_{timestamp}.csv')
        with open(matrix_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Trader_A', 'Trader_B', 'Market_Overlap', 'Outcome_Agreement',
                           'Timing_Similarity', 'Correlation_Score', 'Shared_Markets'])

            for (trader_a, trader_b), score in sorted(matrix_data['matrix'].items(),
                                                      key=lambda x: x[1], reverse=True):
                corr = self.calculate_pairwise_correlation(trader_a, trader_b)
                writer.writerow([
                    trader_a[:10] + '...',
                    trader_b[:10] + '...',
                    corr['market_overlap'],
                    corr['outcome_agreement'],
                    corr['timing_similarity'],
                    corr['correlation_score'],
                    corr['shared_markets']
                ])

        print(f"[REPORTS] ✅ Created {matrix_file}")

        # 2. Correlation Clusters CSV
        clusters_file = os.path.join(output_dir, f'correlation_clusters_{timestamp}.csv')
        with open(clusters_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Cluster_ID', 'Traders_In_Cluster', 'Cluster_Size',
                           'Avg_Correlation', 'Cluster_Type'])

            for cluster in clusters:
                traders_str = ', '.join([t[:10] + '...' for t in cluster['traders']])
                writer.writerow([
                    cluster['cluster_id'],
                    traders_str,
                    cluster['size'],
                    cluster['avg_correlation'],
                    cluster['cluster_type']
                ])

        print(f"[REPORTS] ✅ Created {clusters_file}")

        # 3. Independent Traders CSV
        independent_file = os.path.join(output_dir, f'independent_traders_{timestamp}.csv')
        with open(independent_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Rank', 'Trader_Address', 'Avg_Correlation', 'Max_Correlation',
                           'Independence_Score', 'Total_Markets'])

            for i, trader in enumerate(independent, 1):
                writer.writerow([
                    i,
                    trader['trader_address'][:10] + '...',
                    trader['avg_correlation'],
                    trader['max_correlation'],
                    trader['independence_score'],
                    trader['total_markets']
                ])

        print(f"[REPORTS] ✅ Created {independent_file}")

        # 4. Correlation Summary TXT
        summary_file = os.path.join(output_dir, f'correlation_summary_{timestamp}.txt')
        with open(summary_file, 'w') as f:
            f.write("="*70 + "\n")
            f.write("  TRADER CORRELATION MATRIX ANALYSIS SUMMARY\n")
            f.write("="*70 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Overall statistics
            f.write("OVERALL STATISTICS:\n")
            f.write(f"  Traders Analyzed: {len(matrix_data['trader_list'])}\n")
            f.write(f"  Trader Pairs Calculated: {len(matrix_data['matrix'])}\n")

            if matrix_data['avg_correlations']:
                avg_corr = sum(matrix_data['avg_correlations'].values()) / len(matrix_data['avg_correlations'])
                f.write(f"  Average Correlation: {avg_corr:.3f}\n")

            high_corr = sum(1 for score in matrix_data['matrix'].values() if score > 0.6)
            f.write(f"  High Correlation Pairs (>0.6): {high_corr}\n")
            f.write(f"  Independent Traders (<0.25): {len(independent)}\n\n")

            # Top clusters
            f.write("TOP CORRELATION CLUSTERS:\n")
            for cluster in clusters[:5]:
                f.write(f"\nCluster {cluster['cluster_id']}: {cluster['cluster_type']}\n")
                f.write(f"  Size: {cluster['size']} traders\n")
                f.write(f"  Avg Correlation: {cluster['avg_correlation']}\n")
                f.write(f"  Traders: {', '.join([t[:10] + '...' for t in cluster['traders'][:3]])}\n")

            # Top independent traders
            f.write("\n\nTOP 10 INDEPENDENT TRADERS:\n")
            for i, trader in enumerate(independent[:10], 1):
                f.write(f"{i}. {trader['trader_address'][:10]}... "
                       f"(Avg: {trader['avg_correlation']}, "
                       f"Score: {trader['independence_score']}/100)\n")

            # Suspicious patterns
            f.write("\n\nSUSPICIOUS PATTERNS:\n")
            suspicious_clusters = [c for c in clusters if c['avg_correlation'] >= 0.8]
            if suspicious_clusters:
                for cluster in suspicious_clusters:
                    f.write(f"⚠️  High correlation cluster: {cluster['size']} traders "
                          f"with {cluster['avg_correlation']:.2f} correlation\n")
            else:
                f.write("No highly suspicious patterns detected.\n")

            f.write("\n" + "="*70 + "\n")

        print(f"[REPORTS] ✅ Created {summary_file}")
        print(f"\n[REPORTS] All reports generated successfully!\n")

    def display_correlation_dashboard(self):
        """Display correlation analysis in terminal."""
        print("\n" + "="*70)
        print("  TRADER CORRELATION MATRIX ANALYSIS")
        print("="*70 + "\n")

        matrix_data = self.build_correlation_matrix()
        clusters = self.identify_correlation_clusters()
        independent = self.find_independent_traders()

        # Overall statistics
        print("📊 OVERALL STATISTICS:")
        print(f"Traders Analyzed: {len(matrix_data['trader_list'])}")
        print(f"Trader Pairs Calculated: {len(matrix_data['matrix']):,}")

        if matrix_data['avg_correlations']:
            avg_corr = sum(matrix_data['avg_correlations'].values()) / len(matrix_data['avg_correlations'])
            print(f"Average Correlation: {avg_corr:.2f}")

        high_corr = sum(1 for score in matrix_data['matrix'].values() if score > 0.6)
        print(f"High Correlation Pairs (>0.6): {high_corr}")
        print(f"Independent Traders (<0.25): {len(independent)}\n")

        # Correlation clusters
        print(f"🔍 CORRELATION CLUSTERS DETECTED ({len(clusters)}):\n")
        for cluster in clusters[:3]:
            print(f"Cluster {cluster['cluster_id']}: {cluster['cluster_type']}")
            print(f"  - Traders: {cluster['size']} ({', '.join([t[:10] + '...' for t in cluster['traders'][:5]])})")
            print(f"  - Avg Correlation: {cluster['avg_correlation']}")

            if cluster['avg_correlation'] >= 0.8:
                print(f"  - Flag: ⚠️  Possible copy trading network")
            print()

        # Top independent traders
        print("🏆 TOP 10 INDEPENDENT TRADERS:")
        print(f"{'Rank':<6} {'Trader':<15} {'Avg Corr':<10} {'Max Corr':<10} {'Independence':<12} {'Markets':<8}")
        print("-" * 70)
        for i, trader in enumerate(independent[:10], 1):
            print(f"{i:<6} {trader['trader_address'][:10] + '...':<15} "
                  f"{trader['avg_correlation']:<10.2f} {trader['max_correlation']:<10.2f} "
                  f"{trader['independence_score']}/100{'':<6} {trader['total_markets']:<8}")

        # Suspicious patterns
        print("\n⚠️  SUSPICIOUS PATTERNS:\n")
        suspicious_clusters = [c for c in clusters if c['avg_correlation'] >= 0.8]
        if suspicious_clusters:
            for cluster in suspicious_clusters:
                print(f"1. High correlation group: {cluster['size']} traders with {cluster['avg_correlation']:.2f}+ correlation")
                print(f"   - Recommendation: Flag for copy trading investigation\n")

        # Perfect correlation pairs
        perfect_pairs = [(pair, score) for pair, score in matrix_data['matrix'].items() if score >= 0.98]
        if perfect_pairs:
            for (t1, t2), score in perfect_pairs[:3]:
                print(f"2. Perfect correlation pair: {t1[:10]}... ↔ {t2[:10]}... ({score:.2f})")
                print(f"   - Likely same person or coordinated trading\n")

        if not suspicious_clusters and not perfect_pairs:
            print("No highly suspicious patterns detected.\n")

        print("="*70 + "\n")

    def export_for_integration(self) -> Dict:
        """
        Export correlation data for other analysis tools.

        Returns data structure that copy_trade_detector and
        confidence_meter can consume.
        """
        matrix_data = self.build_correlation_matrix()
        clusters = self.identify_correlation_clusters()
        independent = self.find_independent_traders()

        # High correlation pairs for copy_trade_detector
        high_corr_pairs = []
        for (trader_a, trader_b), score in matrix_data['matrix'].items():
            if score >= 0.6:
                corr_detail = self.calculate_pairwise_correlation(trader_a, trader_b)
                high_corr_pairs.append({
                    'trader_a': trader_a,
                    'trader_b': trader_b,
                    'correlation_score': score,
                    'outcome_agreement': corr_detail['outcome_agreement'],
                    'timing_similarity': corr_detail['timing_similarity'],
                    'shared_markets': corr_detail['shared_markets']
                })

        # Independence scores for confidence_meter
        independence_scores = {
            trader['trader_address']: trader['independence_score']
            for trader in independent
        }

        return {
            'high_correlation_pairs': high_corr_pairs,
            'correlation_clusters': clusters,
            'independence_scores': independence_scores,
            'avg_correlations': matrix_data['avg_correlations'],
            'matrix': matrix_data['matrix']
        }


def main():
    """Main entry point for correlation matrix analysis."""
    parser = argparse.ArgumentParser(
        description='Trader Correlation Matrix Analysis',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--min-markets', type=int, default=3,
                       help='Minimum shared markets to calculate correlation')
    parser.add_argument('--threshold', type=float, default=0.6,
                       help='Correlation threshold for clustering')
    parser.add_argument('--independence', type=float, default=0.25,
                       help='Max correlation to be considered independent')
    parser.add_argument('--db-path', type=str, default=None,
                       help='Path to database file')

    args = parser.parse_args()

    print("\n" + "="*70)
    print("  TRADER CORRELATION MATRIX ANALYSIS")
    print("="*70 + "\n")

    # Initialize
    analyzer = TraderCorrelationMatrix(db_path=args.db_path)

    # Build correlation matrix
    print("Building correlation matrix...")
    matrix = analyzer.build_correlation_matrix(
        min_shared_markets=args.min_markets
    )

    # Identify clusters
    print(f"Identifying clusters (threshold={args.threshold})...")
    clusters = analyzer.identify_correlation_clusters(
        threshold=args.threshold
    )

    # Find independent traders
    print(f"Finding independent traders (threshold={args.independence})...")
    independent = analyzer.find_independent_traders(
        threshold=args.independence
    )

    # Generate reports
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
    analyzer.generate_reports(reports_dir)

    # Display dashboard
    analyzer.display_correlation_dashboard()

    # Export for integration
    print("[EXPORT] Exporting data for integration with other tools...")
    integration_data = analyzer.export_for_integration()
    print(f"[EXPORT] ✅ Exported {len(integration_data['high_correlation_pairs'])} high correlation pairs")
    print(f"[EXPORT] ✅ Exported {len(integration_data['independence_scores'])} independence scores")

    print("\n✅ Correlation matrix analysis complete!\n")


if __name__ == "__main__":
    main()
