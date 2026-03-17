#!/usr/bin/env python3
"""
Analysis Scheduler - Unified Analysis Orchestrator

Orchestrates all analysis tools in coordinated phases with data sufficiency checks.
Provides graceful degradation when data is insufficient.

Phases:
0. Data sufficiency check
1. Independent analysis (trading behavior, correlation matrix)
2. Performance-based analysis (needs resolved markets)
3. Integration analysis (needs Phase 1 & 2)
4. Unified reporting and alerts
"""

import os
import sys
import argparse
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from monitoring.database import Database


class AnalysisScheduler:
    """
    Orchestrates all analysis tools in coordinated phases.

    Checks data sufficiency, runs tools in optimal order, generates unified reports.
    """

    def __init__(self, db_path: str = None, send_alerts: bool = True):
        """
        Initialize scheduler.

        Args:
            db_path: Path to database
            send_alerts: Whether to send Telegram alerts
        """
        if db_path:
            self.db = Database(db_path)
        else:
            self.db = Database()

        self.send_alerts = send_alerts
        self.telegram = None  # Initialize if needed

        # Track execution
        self.execution_log = []
        self.start_time = None
        self.results = {}
        self.errors = []

    def check_data_sufficiency(self) -> Dict:
        """
        Check if enough data exists to run analysis.

        Returns:
            {
                'sufficient': bool,
                'resolved_markets': int,
                'active_traders': int,
                'total_trades': int,
                'avg_trades_per_trader': float,
                'missing_requirements': List[str],
                'recommendations': List[str]
            }
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Count resolved markets
        cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
        resolved_markets = cursor.fetchone()[0]

        # Count total markets
        cursor.execute("SELECT COUNT(*) FROM markets")
        total_markets = cursor.fetchone()[0]

        # Count active traders (traders with trades)
        cursor.execute("SELECT COUNT(DISTINCT trader_address) FROM trades")
        active_traders = cursor.fetchone()[0]

        # Count total trades
        cursor.execute("SELECT COUNT(*) FROM trades")
        total_trades = cursor.fetchone()[0]

        # Calculate trades per trader
        avg_trades_per_trader = total_trades / active_traders if active_traders > 0 else 0

        # Check shared markets for correlation analysis
        cursor.execute("""
            SELECT COUNT(DISTINCT market_id) as shared_count
            FROM (
                SELECT market_id, COUNT(DISTINCT trader_address) as trader_count
                FROM trades
                GROUP BY market_id
                HAVING trader_count >= 2
            )
        """)
        shared_markets = cursor.fetchone()[0]

        conn.close()

        # Determine sufficiency
        missing_requirements = []
        recommendations = []

        # Check thresholds
        if resolved_markets < 10:
            missing_requirements.append(
                f"Need 10+ resolved markets (currently: {resolved_markets})"
            )
            recommendations.append(
                "Wait for more markets to resolve (typically 1-2 weeks)"
            )

        if active_traders < 20:
            missing_requirements.append(
                f"Need 20+ active traders (currently: {active_traders})"
            )
            recommendations.append(
                f"Continue monitoring to track {20 - active_traders} more traders"
            )

        if total_trades < 100:
            missing_requirements.append(
                f"Need 100+ total trades (currently: {total_trades})"
            )
            recommendations.append(
                f"Continue monitoring to collect {100 - total_trades} more trades"
            )

        if shared_markets < 5:
            missing_requirements.append(
                f"Need 5+ markets with multiple traders (currently: {shared_markets})"
            )
            recommendations.append(
                "Wait for traders to participate in more markets"
            )

        # General recommendations
        if missing_requirements:
            recommendations.append("Run 'python analysis/analysis_scheduler.py --mode check' weekly to monitor progress")
            recommendations.append("Limited analysis will still be performed with available data")

        sufficient = len(missing_requirements) == 0

        return {
            'sufficient': sufficient,
            'resolved_markets': resolved_markets,
            'total_markets': total_markets,
            'active_traders': active_traders,
            'total_trades': total_trades,
            'shared_markets': shared_markets,
            'avg_trades_per_trader': round(avg_trades_per_trader, 1),
            'missing_requirements': missing_requirements,
            'recommendations': recommendations
        }

    def run_phase_0_checks(self) -> bool:
        """
        Phase 0: Data sufficiency checks.

        Returns True if can proceed with full analysis, False if limited.
        """
        print("\n" + "="*70)
        print("  PHASE 0: DATA SUFFICIENCY CHECK")
        print("="*70 + "\n")

        sufficiency = self.check_data_sufficiency()

        # Display results
        print("📊 CURRENT DATA STATUS:")
        print(f"   Resolved Markets: {sufficiency['resolved_markets']} / {sufficiency['total_markets']} total")
        print(f"   Active Traders: {sufficiency['active_traders']}")
        print(f"   Total Trades: {sufficiency['total_trades']}")
        print(f"   Shared Markets: {sufficiency['shared_markets']}")
        print(f"   Avg Trades/Trader: {sufficiency['avg_trades_per_trader']}")

        if not sufficiency['sufficient']:
            print("\n⚠️  INSUFFICIENT DATA FOR FULL ANALYSIS")

            if sufficiency['missing_requirements']:
                print("\n❌ Missing Requirements:")
                for req in sufficiency['missing_requirements']:
                    print(f"   • {req}")

            if sufficiency['recommendations']:
                print("\n💡 Recommendations:")
                for rec in sufficiency['recommendations']:
                    print(f"   ✓ {rec}")

            print("\n📌 Limited analysis will be performed with available data.\n")
            return False

        print("\n✅ SUFFICIENT DATA - Full analysis will proceed\n")
        return True

    def run_phase_1_independent(self):
        """
        Phase 1: Run independent analysis tools (don't need resolutions).

        Tools:
        - trading_behavior_analysis.py
        - correlation_matrix.py
        """
        print("\n" + "="*70)
        print("  PHASE 1: INDEPENDENT ANALYSIS")
        print("="*70 + "\n")

        phase_start = datetime.now()
        tools_run = 0

        # 1. Trading Behavior Analysis
        try:
            print("[1/2] Running Trading Behavior Analysis...")

            # Import dynamically to avoid circular imports
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from trading_behavior_analysis import TradingBehaviorAnalyzer

            behavior = TradingBehaviorAnalyzer(self.db.db_path)
            behavior_results = behavior.analyze_all_traders()

            self.results['behavior'] = {
                'total_analyzed': len(behavior_results),
                'data': behavior_results
            }

            print(f"   ✅ Analyzed {len(behavior_results)} traders")
            tools_run += 1

        except Exception as e:
            error_msg = f"Trading Behavior Analysis failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['behavior'] = None

        # 2. Correlation Matrix (7-day TTL cache + trader cap)
        try:
            print("\n[2/2] Running Correlation Matrix Analysis...")

            from analysis.correlation_matrix import TraderCorrelationMatrix
            import json as _json
            import os as _os

            correlation = TraderCorrelationMatrix(self.db.db_path)

            # --- 7-day TTL cache check ---
            cache_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(__file__)), 'reports', 'correlation_cache.json'
            )
            cache_valid = False
            corr_results = None
            if _os.path.exists(cache_path):
                age_days = (datetime.now() - datetime.fromtimestamp(
                    _os.path.getmtime(cache_path)
                )).total_seconds() / 86400
                if age_days < 7:
                    try:
                        with open(cache_path) as _f:
                            cached_data = _json.load(_f)
                        cached_count = cached_data.get('total_traders', 0)
                        # Use filtered count for drift check (same population as cap)
                        conn = self.db.get_connection()
                        cur = conn.cursor()
                        cur.execute("""
                            SELECT COUNT(*) FROM traders t
                            WHERE is_flagged = 1
                            AND (comprehensive_elo >= 1500 OR total_trades >= 30)
                            AND EXISTS (
                                SELECT 1 FROM trades tr
                                WHERE tr.trader_address = t.address LIMIT 1
                            )
                        """)
                        current_count = cur.fetchone()[0]
                        conn.close()
                        drift = abs(current_count - cached_count) / max(1, cached_count)
                        if drift <= 0.05:
                            cache_valid = True
                            corr_results = cached_data
                            print(f"   Using cached matrix ({cached_count} traders, "
                                  f"built {cached_data.get('timestamp','')[:10]}, "
                                  f"age {age_days:.1f}d, drift {drift*100:.1f}%)")
                    except Exception:
                        pass

            if not cache_valid:
                # --- Trader cap: flagged + meaningful activity + local trade data ---
                print("   Cache stale or missing - recalculating with trader cap...")
                conn = self.db.get_connection()
                cur = conn.cursor()
                cur.execute("""
                    SELECT t.address FROM traders t
                    WHERE t.is_flagged = 1
                    AND (t.comprehensive_elo >= 1500 OR t.total_trades >= 30)
                    AND EXISTS (
                        SELECT 1 FROM trades tr
                        WHERE tr.trader_address = t.address LIMIT 1
                    )
                """)
                capped_traders = [row[0] for row in cur.fetchall()]
                conn.close()

                pairs = (len(capped_traders) * (len(capped_traders) - 1)) // 2
                print(f"   Trader cap applied: {len(capped_traders):,} traders, "
                      f"{pairs:,} pairs (was {len(self.db.get_flagged_traders()):,} flagged total)")

                # Patch the trader list used by build_correlation_matrix
                original_get_flagged = correlation.db.get_flagged_traders
                correlation.db.get_flagged_traders = lambda: capped_traders

                matrix = correlation.build_correlation_matrix()
                corr_results = correlation.export_for_integration()

                correlation.db.get_flagged_traders = original_get_flagged

                print(f"   Built matrix for {matrix.get('total_traders', len(capped_traders))} traders")
                print(f"   Found {len(corr_results['high_correlation_pairs'])} high-correlation pairs")

            self.results['correlation'] = corr_results
            tools_run += 1

        except Exception as e:
            error_msg = f"Correlation Matrix failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['correlation'] = None

        duration = (datetime.now() - phase_start).total_seconds()
        print(f"\n✅ Phase 1 Complete: {tools_run}/2 tools run ({duration:.1f}s)")

    def run_phase_2_performance(self):
        """
        Phase 2: Run performance-based analysis (needs resolved markets).

        Tools:
        - trader_performance_analysis.py
        - weighted_consensus_system.py
        - trader_specialization_analysis.py
        """
        print("\n" + "="*70)
        print("  PHASE 2: PERFORMANCE-BASED ANALYSIS")
        print("="*70 + "\n")

        # Check if enough resolved markets
        sufficiency = self.check_data_sufficiency()
        if sufficiency['resolved_markets'] < 10:
            print(f"⚠️  Skipping Phase 2 - need 10+ resolved markets")
            print(f"   Currently have: {sufficiency['resolved_markets']}")
            print(f"   Wait for more markets to resolve, then re-run\n")
            return

        phase_start = datetime.now()
        tools_run = 0

        # 1. Trader Performance Analysis
        try:
            print("[1/3] Running Trader Performance Analysis...")

            from trader_performance_analysis import TraderPerformanceAnalyzer

            performance = TraderPerformanceAnalyzer(self.db.db_path)
            performance_results = performance.analyze_all_traders()

            self.results['performance'] = {
                'total_analyzed': len(performance_results),
                'data': performance_results
            }

            print(f"   ✅ Analyzed {len(performance_results)} traders")
            tools_run += 1

        except Exception as e:
            error_msg = f"Performance Analysis failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['performance'] = None

        # 2. Weighted Consensus System
        try:
            print("\n[2/3] Running Weighted Consensus System...")

            from weighted_consensus_system import WeightedConsensusSystem

            consensus = WeightedConsensusSystem(self.db.db_path)
            # Get unresolved markets and calculate consensus
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT market_id FROM markets WHERE resolved = 0")
            unresolved = [row[0] for row in cursor.fetchall()]
            conn.close()

            consensus_results = []
            for market_id in unresolved[:10]:  # Limit to avoid long runtime
                result = consensus.calculate_weighted_consensus(market_id)
                if result:
                    consensus_results.append(result)

            self.results['consensus'] = {
                'total_markets': len(consensus_results),
                'data': consensus_results
            }

            print(f"   ✅ Calculated consensus for {len(consensus_results)} markets")
            tools_run += 1

        except Exception as e:
            error_msg = f"Consensus System failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['consensus'] = None

        # 3. Trader Specialization Analysis
        try:
            print("\n[3/3] Running Trader Specialization Analysis...")

            from trader_specialization_analysis import TraderSpecializationAnalyzer

            specialization = TraderSpecializationAnalyzer(self.db.db_path)
            spec_results = specialization.analyze_all_traders()

            self.results['specialization'] = {
                'total_analyzed': len(spec_results),
                'data': spec_results
            }

            print(f"   ✅ Analyzed specialization for {len(spec_results)} traders")
            tools_run += 1

        except Exception as e:
            error_msg = f"Specialization Analysis failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['specialization'] = None

        duration = (datetime.now() - phase_start).total_seconds()
        print(f"\n✅ Phase 2 Complete: {tools_run}/3 tools run ({duration:.1f}s)")

    def run_phase_3_integration(self):
        """
        Phase 3: Run integration tools (need Phase 1 & 2 results).

        Tools:
        - copy_trade_detector.py
        - market_confidence_meter.py
        - consensus_divergence_detector.py
        """
        print("\n" + "="*70)
        print("  PHASE 3: INTEGRATION ANALYSIS")
        print("="*70 + "\n")

        # Check prerequisites
        if not self.results.get('correlation'):
            print("⚠️  Skipping Phase 3 - need correlation matrix from Phase 1\n")
            return

        phase_start = datetime.now()
        tools_run = 0

        # 1. Copy Trade Detector
        try:
            print("[1/3] Running Copy Trade Detector...")

            from analysis.copy_trade_detector import CopyTradeDetector

            detector = CopyTradeDetector(self.db.db_path, max_cache_age_hours=168)
            relationships = detector.detect_copy_relationships()
            network = detector.build_copy_network()

            self.results['copy_trading'] = {
                'relationships': len(relationships),
                'leaders': len(network['leaders']),
                'followers': len(network['followers']),
                'data': detector.export_for_integration()
            }

            print(f"   ✅ Found {len(relationships)} copy relationships")
            print(f"   ✅ Identified {len(network['leaders'])} leaders, {len(network['followers'])} followers")
            tools_run += 1

        except Exception as e:
            error_msg = f"Copy Trade Detector failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['copy_trading'] = None

        # 2. Market Confidence Meter (needs performance data)
        try:
            if not self.results.get('performance'):
                print("\n[2/3] Skipping Confidence Meter - needs performance data")
            else:
                print("\n[2/3] Running Market Confidence Meter...")

                from market_confidence_meter import MarketConfidenceMeter

                confidence = MarketConfidenceMeter(self.db.db_path)

                # Get unresolved markets
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT market_id FROM markets WHERE resolved = 0 LIMIT 10")
                markets = [row[0] for row in cursor.fetchall()]
                conn.close()

                confidence_results = []
                for market_id in markets:
                    result = confidence.calculate_confidence(market_id)
                    if result:
                        confidence_results.append(result)

                self.results['confidence'] = {
                    'total_markets': len(confidence_results),
                    'high_confidence': len([r for r in confidence_results if r.get('confidence_score', 0) >= 85]),
                    'data': confidence_results
                }

                print(f"   ✅ Analyzed {len(confidence_results)} markets")
                print(f"   ✅ Found {self.results['confidence']['high_confidence']} high-confidence signals")
                tools_run += 1

        except Exception as e:
            error_msg = f"Confidence Meter failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['confidence'] = None

        # 3. Consensus Divergence Detector
        try:
            if not self.results.get('consensus'):
                print("\n[3/3] Skipping Divergence Detector - needs consensus data")
            else:
                print("\n[3/3] Running Consensus Divergence Detector...")

                from consensus_divergence_detector import ConsensusDivergenceDetector

                divergence = ConsensusDivergenceDetector(self.db.db_path)

                # Get markets with divergence
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT market_id FROM markets WHERE resolved = 0 LIMIT 10")
                markets = [row[0] for row in cursor.fetchall()]
                conn.close()

                divergence_results = []
                for market_id in markets:
                    result = divergence.detect_divergence(market_id)
                    if result and result.get('has_divergence'):
                        divergence_results.append(result)

                self.results['divergence'] = {
                    'total_divergences': len(divergence_results),
                    'data': divergence_results
                }

                print(f"   ✅ Found {len(divergence_results)} divergence signals")
                tools_run += 1

        except Exception as e:
            error_msg = f"Divergence Detector failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            self.errors.append(error_msg)
            self.results['divergence'] = None

        duration = (datetime.now() - phase_start).total_seconds()
        print(f"\n✅ Phase 3 Complete: {tools_run}/3 tools run ({duration:.1f}s)")

    def generate_unified_report(self) -> Dict:
        """
        Combine all analysis results into unified report.

        Returns comprehensive report with top opportunities and insights.
        """
        report = {
            'timestamp': datetime.now(),
            'data_status': self.check_data_sufficiency(),
            'tools_run': len([r for r in self.results.values() if r is not None]),
            'errors': self.errors,
            'top_opportunities': [],
            'contrarian_signals': [],
            'trader_rankings': [],
            'copy_networks': [],
            'summary': {}
        }

        # Extract top opportunities from confidence meter
        if self.results.get('confidence'):
            confidence_data = self.results['confidence'].get('data', [])
            high_conf = [m for m in confidence_data if m.get('confidence_score', 0) >= 85]
            report['top_opportunities'] = sorted(high_conf,
                                                key=lambda x: x.get('confidence_score', 0),
                                                reverse=True)[:5]

        # Extract contrarian signals
        if self.results.get('divergence'):
            report['contrarian_signals'] = self.results['divergence'].get('data', [])[:5]

        # Extract trader rankings
        if self.results.get('performance'):
            perf_data = self.results['performance'].get('data', [])
            report['trader_rankings'] = sorted(perf_data,
                                              key=lambda x: x.get('elo_rating', 1000),
                                              reverse=True)[:10]

        # Extract copy networks
        if self.results.get('copy_trading'):
            copy_data = self.results['copy_trading'].get('data', {})
            leaders = copy_data.get('leaders', {})
            # Get top leaders by follower count
            leader_list = [(k, len(v)) for k, v in leaders.items()]
            leader_list.sort(key=lambda x: x[1], reverse=True)
            report['copy_networks'] = leader_list[:5]

        # Summary statistics
        report['summary'] = {
            'phase_1_tools': 2 if self.results.get('behavior') or self.results.get('correlation') else 0,
            'phase_2_tools': sum([1 for k in ['performance', 'consensus', 'specialization'] if self.results.get(k)]),
            'phase_3_tools': sum([1 for k in ['copy_trading', 'confidence', 'divergence'] if self.results.get(k)]),
            'total_errors': len(self.errors)
        }

        return report

    def save_reports(self, unified_report: Dict):
        """
        Save all reports to /reports directory.

        Generates:
        - unified_analysis_YYYYMMDD.txt (master report)
        - top_opportunities_YYYYMMDD.txt (actionable signals)
        - trader_rankings_YYYYMMDD.txt (best traders)
        """
        # Create reports directory
        reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
        os.makedirs(reports_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 1. Unified Analysis Report
        unified_file = os.path.join(reports_dir, f'unified_analysis_{timestamp}.txt')
        with open(unified_file, 'w') as f:
            f.write("="*70 + "\n")
            f.write("  UNIFIED ANALYSIS REPORT\n")
            f.write("="*70 + "\n\n")
            f.write(f"Generated: {unified_report['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            # Data status
            f.write("DATA STATUS:\n")
            status = unified_report['data_status']
            f.write(f"  Resolved Markets: {status['resolved_markets']}\n")
            f.write(f"  Active Traders: {status['active_traders']}\n")
            f.write(f"  Total Trades: {status['total_trades']}\n")
            f.write(f"  Data Sufficient: {'✅ Yes' if status['sufficient'] else '⚠️  No'}\n\n")

            # Tools run
            f.write("ANALYSIS TOOLS:\n")
            f.write(f"  Tools Run: {unified_report['tools_run']}/8\n")
            f.write(f"  Phase 1: {unified_report['summary']['phase_1_tools']}/2\n")
            f.write(f"  Phase 2: {unified_report['summary']['phase_2_tools']}/3\n")
            f.write(f"  Phase 3: {unified_report['summary']['phase_3_tools']}/3\n")
            f.write(f"  Errors: {unified_report['summary']['total_errors']}\n\n")

            # Top opportunities
            if unified_report['top_opportunities']:
                f.write("TOP OPPORTUNITIES (High Confidence):\n")
                for i, opp in enumerate(unified_report['top_opportunities'], 1):
                    f.write(f"{i}. Market: {opp.get('market_title', 'Unknown')[:50]}\n")
                    f.write(f"   Confidence: {opp.get('confidence_score', 0)}/100\n")
                    f.write(f"   Consensus: {opp.get('consensus_outcome', 'N/A')}\n\n")

            # Contrarian signals
            if unified_report['contrarian_signals']:
                f.write("CONTRARIAN SIGNALS:\n")
                for i, signal in enumerate(unified_report['contrarian_signals'], 1):
                    f.write(f"{i}. Market: {signal.get('market_title', 'Unknown')[:50]}\n")
                    f.write(f"   Divergence Score: {signal.get('divergence_score', 0)}/100\n\n")

            # Trader rankings
            if unified_report['trader_rankings']:
                f.write("TOP TRADERS (by ELO):\n")
                for i, trader in enumerate(unified_report['trader_rankings'], 1):
                    f.write(f"{i}. {trader.get('trader_address', 'Unknown')[:12]}...\n")
                    f.write(f"   ELO: {trader.get('elo_rating', 1000)}\n")
                    f.write(f"   Win Rate: {trader.get('win_rate', 0)*100:.1f}%\n\n")

            # Copy networks
            if unified_report['copy_networks']:
                f.write("TOP LEADERS (Copy Trading Networks):\n")
                for i, (leader, follower_count) in enumerate(unified_report['copy_networks'], 1):
                    f.write(f"{i}. {leader[:12]}... - {follower_count} followers\n")

            f.write("\n" + "="*70 + "\n")

        print(f"   ✅ Saved {unified_file}")

        # 2. Top Opportunities (quick reference)
        if unified_report['top_opportunities']:
            opp_file = os.path.join(reports_dir, f'top_opportunities_{timestamp}.txt')
            with open(opp_file, 'w') as f:
                f.write("TOP OPPORTUNITIES - QUICK REFERENCE\n")
                f.write("="*70 + "\n\n")

                for i, opp in enumerate(unified_report['top_opportunities'], 1):
                    f.write(f"{i}. {opp.get('market_title', 'Unknown')}\n")
                    f.write(f"   Confidence: {opp.get('confidence_score', 0)}/100\n")
                    f.write(f"   Consensus: {opp.get('consensus_outcome', 'N/A')}\n")
                    f.write(f"   Prediction: {opp.get('prediction', 'N/A')}\n\n")

            print(f"   ✅ Saved {opp_file}")

        return unified_file

    def run_phase_3b_composite_scores(self):
        """
        Phase 3b: Calculate composite skill scores for all flagged traders.
        Synthesises ELO, behavioural, network, and advanced metrics into
        a single 0-100 score with tier classification (ELITE/STRONG/etc).
        Runs after Phase 3. Gracefully degrades when upstream data is missing.
        """
        print("\n" + "="*70)
        print("  PHASE 3b: COMPOSITE SKILL SCORES")
        print("="*70 + "\n")

        try:
            from collections import Counter
            import csv as _csv
            import json as _json

            # --- Bulk-load all inputs from DB and cache files in one pass ---

            conn = self.db.get_connection()
            cur = conn.cursor()

            # 1. ELO scores
            cur.execute("""
                SELECT address, comprehensive_elo
                FROM traders
                WHERE comprehensive_elo IS NOT NULL AND is_flagged = 1
                ORDER BY comprehensive_elo DESC
            """)
            elo_map = {row[0]: row[1] for row in cur.fetchall()}

            # 2. Behavioral scores from DB
            cur.execute("""
                SELECT address, kelly_alignment_score, patience_score, timing_score
                FROM traders
                WHERE is_flagged = 1
            """)
            behavior_map = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

            conn.close()

            # 3. Network independence from correlation cache
            independence_map = {}
            copy_followers = set()
            corr_data = self.results.get('correlation') or {}
            if not corr_data:
                cache_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), 'reports', 'correlation_cache.json'
                )
                if os.path.exists(cache_path):
                    with open(cache_path) as _f:
                        corr_data = _json.load(_f)
            if corr_data:
                independence_map = corr_data.get('independence_scores', {})
                for pair in corr_data.get('high_correlation_pairs', []):
                    if pair.get('correlation_score', 0) >= 0.7:
                        copy_followers.add(pair['trader_b'])

            print(f"   ELO data: {len(elo_map)} traders")
            print(f"   Behavioral data: {sum(1 for v in behavior_map.values() if any(x is not None for x in v))} traders with scores")
            print(f"   Network data: {len(independence_map)} independence scores, {len(copy_followers)} copy followers")

            # --- Score each trader using lightweight inline logic ---
            def _elo_points(elo):
                if elo >= 2400: return 25.0
                if elo >= 2200: return 23.0
                if elo >= 2000: return 21.0
                if elo >= 1800: return 19.0
                if elo >= 1700: return 17.0
                if elo >= 1600: return 15.0
                if elo >= 1500: return 13.0
                if elo >= 1400: return 11.0
                if elo >= 1300: return 9.0
                if elo >= 1200: return 7.0
                return 5.0

            def _behavioral_points(kelly, patience, timing):
                # Kelly (0-5 pts): higher is better, 0.5+ is good
                kelly_pts = 2.5  # neutral default
                if kelly is not None:
                    if kelly >= 0.8: kelly_pts = 5.0
                    elif kelly >= 0.6: kelly_pts = 4.0
                    elif kelly >= 0.4: kelly_pts = 3.0
                    elif kelly >= 0.2: kelly_pts = 2.0
                    else: kelly_pts = 1.0
                # Patience (0-5 pts): 0-1 scale, higher is more patient
                patience_pts = 2.5
                if patience is not None:
                    if patience >= 0.7: patience_pts = 5.0
                    elif patience >= 0.5: patience_pts = 4.0
                    elif patience >= 0.3: patience_pts = 3.0
                    elif patience >= 0.1: patience_pts = 2.0
                    else: patience_pts = 1.0
                # Timing (0-5 pts): 0-1 scale
                timing_pts = 2.5
                if timing is not None:
                    if timing >= 0.7: timing_pts = 5.0
                    elif timing >= 0.5: timing_pts = 4.0
                    elif timing >= 0.3: timing_pts = 3.0
                    elif timing >= 0.1: timing_pts = 2.0
                    else: timing_pts = 1.0
                return kelly_pts + patience_pts + timing_pts

            def _network_points(addr):
                ind = independence_map.get(addr)
                if ind is None:
                    return 6.0  # neutral default (50/100 independence assumed)
                ind = int(ind) if not isinstance(ind, int) else ind
                if ind >= 90: return 10.0
                if ind >= 80: return 9.0
                if ind >= 70: return 8.0
                if ind >= 60: return 7.0
                if ind >= 50: return 6.0
                if ind >= 40: return 5.0
                if ind >= 30: return 4.0
                if ind >= 20: return 3.0
                if ind >= 10: return 2.0
                return 1.0

            def _copy_penalty(addr):
                if addr in copy_followers:
                    return -10.0  # moderate penalty (score is 0.7-0.8 range)
                return 0.0

            def _classify_tier(score):
                if score >= 85: return 'ELITE'
                if score >= 70: return 'STRONG'
                if score >= 55: return 'ABOVE AVERAGE'
                if score >= 40: return 'AVERAGE'
                if score >= 25: return 'BELOW AVERAGE'
                return 'WEAK/NOISE'

            # Load Sharpe map from Phase 2b results
            sharpe_map = (self.results.get('risk_metrics') or {}).get('sharpe_map', {})
            if sharpe_map:
                print(f"   Loaded Sharpe ratios for {len(sharpe_map)} traders from Phase 2b")

            # Load Brier map from Phase 2c results
            brier_map = (self.results.get('calibration') or {}).get('brier_map', {})
            if brier_map:
                print(f"   Loaded Brier scores for {len(brier_map)} traders from Phase 2c")

            trader_addresses = list(elo_map.keys())
            print(f"   Scoring {len(trader_addresses)} flagged traders...")

            ranked = []
            for addr in trader_addresses:
                elo = elo_map[addr]
                kelly, patience, timing = behavior_map.get(addr, (None, None, None))

                elo_pts = _elo_points(elo)
                behav_pts = _behavioral_points(kelly, patience, timing)
                network_pts = _network_points(addr)
                copy_pen = _copy_penalty(addr)
                # Forecasting: use Brier score from Phase 2c if available
                brier = brier_map.get(addr)
                if brier is None:      forecast_pts = 13.0
                elif brier < 0.10:     forecast_pts = 25.0
                elif brier < 0.15:     forecast_pts = 20.0
                elif brier < 0.20:     forecast_pts = 15.0
                elif brier < 0.25:     forecast_pts = 10.0
                else:                  forecast_pts = 5.0
                exec_pts = 7.0        # execution: neutral (no regret analysis yet)
                contrarian_pts = 0.0  # contrarian: no bonus by default

                # Consistency: use Sharpe ratio from Phase 2b if available
                sharpe = sharpe_map.get(addr)
                if sharpe is None:
                    consist_pts = 7.0
                elif sharpe > 3.0:   consist_pts = 15.0
                elif sharpe >= 2.5:  consist_pts = 14.0
                elif sharpe >= 2.0:  consist_pts = 13.0
                elif sharpe >= 1.5:  consist_pts = 11.0
                elif sharpe >= 1.0:  consist_pts = 9.0
                elif sharpe >= 0.5:  consist_pts = 7.0
                elif sharpe >= 0.0:  consist_pts = 5.0
                else:                consist_pts = 3.0

                total = elo_pts + forecast_pts + exec_pts + consist_pts + behav_pts + network_pts + contrarian_pts + copy_pen
                score = max(0, min(100, int(round(total))))
                tier = _classify_tier(score)

                ranked.append({
                    'trader_address': addr,
                    'composite_score': score,
                    'tier': tier,
                    'elo_points': elo_pts,
                    'forecasting_points': forecast_pts,
                    'execution_points': exec_pts,
                    'consistency_points': consist_pts,
                    'behavioral_points': round(behav_pts, 1),
                    'network_points': network_pts,
                    'contrarian_points': contrarian_pts,
                    'copy_penalty': copy_pen,
                    'breakdown': (f"ELO:{elo_pts:.0f}/25 Forecast:{forecast_pts:.0f}/25 "
                                  f"Exec:{exec_pts:.0f}/15 Consist:{consist_pts:.0f}/15 "
                                  f"Behav:{behav_pts:.0f}/15 Net:{network_pts:.0f}/10 "
                                  f"Copy:{copy_pen:.0f} = {score}/100 ({tier})"),
                })

            ranked.sort(key=lambda x: x['composite_score'], reverse=True)
            for rank, t in enumerate(ranked, 1):
                t['rank'] = rank

            self.results['composite_scores'] = ranked

            # Save CSV
            reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'reports')
            os.makedirs(reports_dir, exist_ok=True)
            csv_path = os.path.join(reports_dir, f"composite_scores_{datetime.now().strftime('%Y%m%d')}.csv")
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = _csv.writer(f)
                writer.writerow(['Rank', 'Address', 'Score', 'Tier', 'ELO', 'Forecast',
                                  'Exec', 'Consist', 'Behav', 'Network', 'Contrarian',
                                  'CopyPenalty', 'Breakdown'])
                for t in ranked:
                    writer.writerow([
                        t['rank'], t['trader_address'], t['composite_score'], t['tier'],
                        f"{t['elo_points']:.1f}", f"{t['forecasting_points']:.1f}",
                        f"{t['execution_points']:.1f}", f"{t['consistency_points']:.1f}",
                        f"{t['behavioral_points']:.1f}", f"{t['network_points']:.1f}",
                        f"{t['contrarian_points']:.1f}", f"{t['copy_penalty']:.1f}",
                        t['breakdown'],
                    ])

            tier_counts = Counter(t['tier'] for t in ranked)
            print(f"\n   Scored {len(ranked)} traders")
            print(f"   ELITE (85-100):        {tier_counts.get('ELITE', 0)}")
            print(f"   STRONG (70-84):        {tier_counts.get('STRONG', 0)}")
            print(f"   ABOVE AVERAGE (55-69): {tier_counts.get('ABOVE AVERAGE', 0)}")
            print(f"   AVERAGE (40-54):       {tier_counts.get('AVERAGE', 0)}")
            print(f"   BELOW AVERAGE (25-39): {tier_counts.get('BELOW AVERAGE', 0)}")
            print(f"   WEAK/NOISE (0-24):     {tier_counts.get('WEAK/NOISE', 0)}")
            print(f"   Report: {csv_path}")

        except Exception as e:
            import traceback
            print(f"   Composite score calculation failed: {e}")
            traceback.print_exc()
            self.results['composite_scores'] = None

    def run_phase_2b_risk_metrics(self):
        """
        Phase 2b: Compute risk-adjusted returns (Sharpe, Sortino, drawdown)
        for all traders with sufficient resolved-market trade history.
        Results feed into Phase 3b's consistency component.
        """
        print("\n" + "="*70)
        print("  PHASE 2b: RISK-ADJUSTED RETURNS")
        print("="*70 + "\n")

        try:
            from analysis.risk_adjusted_returns import RiskAdjustedAnalyzer
            import logging as _logging
            # Suppress per-trader WARNING spam — we only want summary output
            _logging.getLogger().setLevel(_logging.ERROR)

            with RiskAdjustedAnalyzer(self.db.db_path) as analyzer:
                df = analyzer.compare_all_traders()

            _logging.getLogger().setLevel(_logging.WARNING)

            sharpe_map = {}
            if df is not None and len(df) > 0:
                sharpe_map = {
                    row['trader_address']: row['sharpe_ratio']
                    for _, row in df.iterrows()
                    if row['sharpe_ratio'] is not None and str(row['sharpe_ratio']) != 'nan'
                }

            self.results['risk_metrics'] = {
                'sharpe_map': sharpe_map,
                'trader_count': len(sharpe_map),
            }

            print(f"   Traders with Sharpe data: {len(sharpe_map)}")
            if sharpe_map:
                vals = [v for v in sharpe_map.values()]
                print(f"   Sharpe range: {min(vals):.2f} to {max(vals):.2f}")
                above_1 = sum(1 for v in vals if v >= 1.0)
                above_2 = sum(1 for v in vals if v >= 2.0)
                print(f"   Sharpe >= 1.0: {above_1}  |  Sharpe >= 2.0: {above_2}")

        except Exception as e:
            import traceback
            print(f"   Risk-adjusted analysis failed: {e}")
            traceback.print_exc()
            self.results['risk_metrics'] = None

    def run_phase_2c_calibration(self):
        """
        Phase 2c: Compute Brier scores and calibration metrics for all traders
        with sufficient resolved-market predictions.
        Results feed into Phase 3b's forecasting component.
        """
        print("\n" + "="*70)
        print("  PHASE 2c: CALIBRATION ANALYSIS")
        print("="*70 + "\n")

        try:
            import matplotlib
            matplotlib.use('Agg')
            import logging as _logging
            from analysis.calibration_analysis import CalibrationAnalyzer

            # Suppress per-trader WARNING spam
            _logging.getLogger().setLevel(_logging.ERROR)
            analyzer = CalibrationAnalyzer(self.db.db_path)
            results = analyzer.analyze_all_traders()
            _logging.getLogger().setLevel(_logging.WARNING)

            brier_map = {}
            if results:
                brier_map = {
                    addr: r['brier_score']
                    for addr, r in results.items()
                    if r.get('brier_score') is not None
                }

            self.results['calibration'] = {
                'brier_map': brier_map,
                'trader_count': len(brier_map),
            }

            print(f"   Traders with Brier data: {len(brier_map)}")
            if brier_map:
                vals = list(brier_map.values())
                print(f"   Brier range: {min(vals):.4f} to {max(vals):.4f}")
                excellent = sum(1 for v in vals if v < 0.10)
                good = sum(1 for v in vals if 0.10 <= v < 0.20)
                print(f"   Brier < 0.10 (excellent): {excellent}  |  0.10-0.20 (good): {good}")

        except Exception as e:
            import traceback
            print(f"   Calibration analysis failed: {e}")
            traceback.print_exc()
            self.results['calibration'] = None

    def run_phase_4_reporting(self):
        """
        Phase 4: Generate unified reports and send alerts.
        """
        print("\n" + "="*70)
        print("  PHASE 4: UNIFIED REPORTING")
        print("="*70 + "\n")

        # Generate unified report
        print("[1/2] Generating unified report...")
        unified_report = self.generate_unified_report()

        # Save reports
        print("[2/2] Saving reports...")
        report_file = self.save_reports(unified_report)

        print(f"\n✅ Phase 4 Complete")
        print(f"   Reports saved to: reports/")

    def run_full_analysis(self):
        """
        Run complete analysis workflow.

        Executes all phases in order with graceful degradation.
        """
        self.start_time = datetime.now()

        print("\n" + "="*70)
        print("  ANALYSIS SCHEDULER - FULL ANALYSIS WORKFLOW")
        print("="*70)
        print(f"\nStarted: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Phase 0: Check data
        sufficient = self.run_phase_0_checks()

        # Phase 1: Always run (doesn't need resolutions)
        self.run_phase_1_independent()

        # Phase 2: Only if sufficient data
        if sufficient:
            self.run_phase_2_performance()
        else:
            print("\n" + "="*70)
            print("  PHASE 2: SKIPPED (Insufficient resolved markets)")
            print("="*70 + "\n")

        # Phase 2b: Risk-adjusted returns (always run — only needs resolved trades)
        self.run_phase_2b_risk_metrics()

        # Phase 2c: Calibration analysis (always run — only needs resolved trades)
        self.run_phase_2c_calibration()

        # Phase 3: Only if prerequisites met
        if sufficient and self.results.get('correlation'):
            self.run_phase_3_integration()
        else:
            print("\n" + "="*70)
            print("  PHASE 3: SKIPPED (Missing prerequisites)")
            print("="*70 + "\n")

        # Phase 3b: Composite scores (always run — graceful degradation)
        self.run_phase_3b_composite_scores()

        # Phase 4: Always run (generates reports from available data)
        self.run_phase_4_reporting()

        # Summary
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds() / 60

        print("\n" + "="*70)
        print("  ANALYSIS COMPLETE")
        print("="*70)
        print(f"\nDuration: {duration:.1f} minutes")
        print(f"Tools Run: {len([r for r in self.results.values() if r is not None])}/8")
        print(f"Errors: {len(self.errors)}")
        if self.errors:
            print("\n⚠️  Errors encountered:")
            for error in self.errors:
                print(f"   • {error}")

        print(f"\n📊 Reports Generated: Check reports/ directory")

        # Next steps
        if not sufficient:
            print("\n💡 NEXT STEPS:")
            print("   1. Continue monitoring for 1-2 weeks")
            print("   2. Wait for markets to resolve")
            print("   3. Re-run: python analysis/analysis_scheduler.py --mode check")
            print("   4. When sufficient data available, run full analysis again\n")

    def run_quick_update(self):
        """
        Run quick update (no full recalculation).

        Just checks for new data and significant changes.
        """
        print("\n" + "="*70)
        print("  QUICK UPDATE")
        print("="*70 + "\n")

        sufficiency = self.check_data_sufficiency()

        print("📊 CURRENT STATUS:")
        print(f"   Resolved Markets: {sufficiency['resolved_markets']}")
        print(f"   Active Traders: {sufficiency['active_traders']}")
        print(f"   Total Trades: {sufficiency['total_trades']}")
        print(f"   Data Sufficient: {'✅ Yes' if sufficiency['sufficient'] else '⚠️  No'}")

        if not sufficiency['sufficient']:
            print("\n💡 Not yet ready for full analysis")
            print("   Missing requirements:")
            for req in sufficiency['missing_requirements']:
                print(f"   • {req}")
        else:
            print("\n✅ Ready for full analysis!")
            print("   Run: python analysis/analysis_scheduler.py --mode full")

        print()


def main():
    """Main entry point for analysis scheduler."""
    parser = argparse.ArgumentParser(
        description='Analysis Scheduler - Orchestrate all analysis tools',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--mode', type=str, default='full',
                       choices=['full', 'quick', 'check'],
                       help='Analysis mode: full/quick/check')
    parser.add_argument('--no-alerts', action='store_true',
                       help='Disable Telegram alerts')
    parser.add_argument('--force', action='store_true',
                       help='Force run even if insufficient data')
    parser.add_argument('--db-path', type=str, default=None,
                       help='Path to database file')

    args = parser.parse_args()

    scheduler = AnalysisScheduler(
        db_path=args.db_path,
        send_alerts=not args.no_alerts
    )

    if args.mode == 'check':
        # Just check data sufficiency
        print("\n" + "="*70)
        print("  DATA SUFFICIENCY CHECK")
        print("="*70 + "\n")

        sufficiency = scheduler.check_data_sufficiency()

        print("📊 CURRENT DATA STATUS:")
        print(f"   Resolved Markets: {sufficiency['resolved_markets']} / {sufficiency['total_markets']} total")
        print(f"   Active Traders: {sufficiency['active_traders']}")
        print(f"   Total Trades: {sufficiency['total_trades']}")
        print(f"   Shared Markets: {sufficiency['shared_markets']}")
        print(f"   Avg Trades/Trader: {sufficiency['avg_trades_per_trader']}")

        print("\n" + "="*70)
        if sufficiency['sufficient']:
            print("✅ SUFFICIENT DATA - Ready for full analysis!")
            print("="*70)
            print("\n💡 Run: python analysis/analysis_scheduler.py --mode full\n")
        else:
            print("⚠️  INSUFFICIENT DATA - Need more data")
            print("="*70)

            if sufficiency['missing_requirements']:
                print("\n❌ Missing Requirements:")
                for req in sufficiency['missing_requirements']:
                    print(f"   • {req}")

            if sufficiency['recommendations']:
                print("\n💡 Recommendations:")
                for rec in sufficiency['recommendations']:
                    print(f"   ✓ {rec}")

            print("\n📌 You can still run limited analysis with --force flag\n")

    elif args.mode == 'quick':
        # Quick update only
        scheduler.run_quick_update()

    elif args.mode == 'full':
        # Full analysis workflow
        if not args.force:
            # Check sufficiency first
            sufficiency = scheduler.check_data_sufficiency()
            if not sufficiency['sufficient']:
                print("\n" + "="*70)
                print("❌ INSUFFICIENT DATA FOR FULL ANALYSIS")
                print("="*70 + "\n")

                print("Missing requirements:")
                for req in sufficiency['missing_requirements']:
                    print(f"  • {req}")

                print("\n💡 Options:")
                print("   1. Wait for more data, then re-run")
                print("   2. Use --force to run with limited data")
                print("   3. Run --mode check to see current status\n")
                return

        scheduler.run_full_analysis()


if __name__ == "__main__":
    main()
