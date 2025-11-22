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
from database import Database


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

        # 2. Correlation Matrix
        try:
            print("\n[2/2] Running Correlation Matrix Analysis...")

            from analysis.correlation_matrix import TraderCorrelationMatrix

            correlation = TraderCorrelationMatrix(self.db.db_path)
            matrix = correlation.build_correlation_matrix()
            corr_results = correlation.export_for_integration()

            self.results['correlation'] = corr_results

            print(f"   ✅ Built matrix for {len(matrix)} traders")
            print(f"   ✅ Found {len(corr_results['high_correlation_pairs'])} high-correlation pairs")
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

            detector = CopyTradeDetector(self.db.db_path)
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

        # Phase 3: Only if prerequisites met
        if sufficient and self.results.get('correlation'):
            self.run_phase_3_integration()
        else:
            print("\n" + "="*70)
            print("  PHASE 3: SKIPPED (Missing prerequisites)")
            print("="*70 + "\n")

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
