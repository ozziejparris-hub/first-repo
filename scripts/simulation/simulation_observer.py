#!/usr/bin/env python3
"""
Polymarket Simulation Observer

Analyzes simulation pipeline results and suggests improvements.

Features:
- Load all pipeline reports
- Analyze metrics against targets
- Identify root causes
- Prioritize improvements by impact
- Generate actionable recommendations
- Compare before/after results

Usage:
    py scripts/simulation/simulation_observer.py                           # Analyze latest
    py scripts/simulation/simulation_observer.py --pipeline results/pipeline
    py scripts/simulation/simulation_observer.py --compare results/baseline results/improved
"""

import sys
import os
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class SimulationObserver:
    """Analyze simulation results and suggest improvements."""

    def __init__(self, pipeline_dir: str):
        """Initialize observer with pipeline directory."""
        self.pipeline_dir = Path(pipeline_dir)
        self.reports = {}
        self.issues = []
        self.recommendations = []
        self.metrics = {}

    def load_reports(self) -> bool:
        """Load all pipeline reports from directory."""
        report_files = {
            'validation': 'validation_report.json',
            'optimization': 'optimization_report.json',
            'backtesting': 'backtest_report.json',
            'analysis': 'analysis_report.json',
            'comparison': 'comparison_report.json',
            'summary': 'pipeline_summary.json'
        }

        loaded_count = 0
        for key, filename in report_files.items():
            filepath = self.pipeline_dir / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r') as f:
                        self.reports[key] = json.load(f)
                    loaded_count += 1
                except Exception as e:
                    print(f"[WARNING] Could not load {filename}: {e}")
            # Silently skip missing files (not all may exist)

        return loaded_count > 0

    def extract_metrics(self):
        """Extract key metrics from all reports."""
        # From analysis report
        analysis = self.reports.get('analysis', {})
        self.metrics['num_traders'] = analysis.get('num_traders', 0)

        analysis_data = analysis.get('analysis', {})

        # Market difficulty
        market_difficulty = analysis_data.get('market_difficulty', [])
        self.metrics['num_resolved_markets'] = len(market_difficulty)
        if market_difficulty:
            avg_difficulty = sum(m['difficulty'] for m in market_difficulty) / len(market_difficulty)
            self.metrics['avg_market_difficulty'] = avg_difficulty
        else:
            self.metrics['avg_market_difficulty'] = 0

        # Error analysis
        false_positives = analysis_data.get('false_positives', [])
        false_negatives = analysis_data.get('false_negatives', [])
        self.metrics['num_false_positives'] = len(false_positives)
        self.metrics['num_false_negatives'] = len(false_negatives)

        if false_positives:
            avg_fp_trades = sum(fp['total_trades'] for fp in false_positives) / len(false_positives)
            self.metrics['avg_fp_trades'] = avg_fp_trades
        else:
            self.metrics['avg_fp_trades'] = 0

        if false_negatives:
            avg_fn_trades = sum(fn['total_trades'] for fn in false_negatives) / len(false_negatives)
            self.metrics['avg_fn_trades'] = avg_fn_trades
        else:
            self.metrics['avg_fn_trades'] = 0

        # Confusion matrix accuracy
        cm_accuracy = analysis_data.get('confusion_matrix_accuracy', {})
        self.metrics['confusion_accuracy'] = cm_accuracy.get('accuracy', 0)

        # From optimization report
        optimization = self.reports.get('optimization', {})
        best_metrics = optimization.get('best_metrics', {})
        self.metrics['optimal_k_factor'] = optimization.get('optimal_k_factor', 0)
        self.metrics['correlation'] = best_metrics.get('correlation', 0)
        self.metrics['r_squared'] = best_metrics.get('r_squared', 0)
        self.metrics['elo_spread'] = best_metrics.get('elo_spread', 0)
        self.metrics['elite_accuracy'] = best_metrics.get('elite_accuracy', 0)
        self.metrics['poor_accuracy'] = best_metrics.get('poor_accuracy', 0)

        # From backtesting report
        backtesting = self.reports.get('backtesting', {})
        strategies = backtesting.get('strategies', [])
        if strategies:
            best_strategy = max(strategies, key=lambda s: s.get('roi', 0))
            self.metrics['best_roi'] = best_strategy.get('roi', 0)
            self.metrics['best_sharpe'] = best_strategy.get('sharpe_ratio', 0)
            self.metrics['best_strategy_params'] = best_strategy.get('params', {})
        else:
            self.metrics['best_roi'] = 0
            self.metrics['best_sharpe'] = 0
            self.metrics['best_strategy_params'] = {}

        # Estimate trades per trader
        if self.metrics['num_traders'] > 0 and self.metrics['num_resolved_markets'] > 0:
            # Rough estimate: assuming ~30-40 trades per market distributed among traders
            estimated_total_trades = self.metrics['num_resolved_markets'] * 35
            self.metrics['trades_per_trader'] = estimated_total_trades / self.metrics['num_traders']
        else:
            self.metrics['trades_per_trader'] = 0

    def analyze_data_quality(self):
        """Analyze data quality and identify issues."""
        num_traders = self.metrics.get('num_traders', 0)
        num_resolved = self.metrics.get('num_resolved_markets', 0)
        trades_per_trader = self.metrics.get('trades_per_trader', 0)

        # Check resolved markets
        if num_resolved < 80:
            severity = 'CRITICAL' if num_resolved < 50 else 'WARNING'
            self.issues.append({
                'severity': severity,
                'category': 'Data Quality',
                'title': 'Insufficient resolved markets',
                'current': num_resolved,
                'target': 80,
                'root_cause': 'Not enough data for law of large numbers',
                'impact': 'Correlation +0.15, Accuracy +12%'
            })

        # Check trades per trader
        if trades_per_trader < 20:
            severity = 'WARNING' if trades_per_trader >= 15 else 'CRITICAL'
            self.issues.append({
                'severity': severity,
                'category': 'Data Quality',
                'title': 'Small sample size per trader',
                'current': trades_per_trader,
                'target': 20,
                'root_cause': 'Not enough resolved markets',
                'impact': 'ELO confidence: LOW'
            })

        # Check trader count
        if num_traders < 50:
            self.issues.append({
                'severity': 'INFO',
                'category': 'Data Quality',
                'title': 'Small trader sample',
                'current': num_traders,
                'target': 100,
                'root_cause': 'Limited test data',
                'impact': 'Statistical power reduced'
            })

    def analyze_elo_performance(self):
        """Analyze ELO system performance."""
        correlation = self.metrics.get('correlation', 0)
        r_squared = self.metrics.get('r_squared', 0)
        elo_spread = self.metrics.get('elo_spread', 0)

        # Check correlation
        if correlation < 0.70:
            severity = 'CRITICAL' if correlation < 0.60 else 'WARNING'
            self.issues.append({
                'severity': severity,
                'category': 'ELO Performance',
                'title': 'Low correlation',
                'current': correlation,
                'target': 0.70,
                'root_cause': 'Insufficient data (need more resolved markets)',
                'impact': 'Poor skill prediction'
            })

        # Check R-squared
        if r_squared < 0.49:
            self.issues.append({
                'severity': 'WARNING',
                'category': 'ELO Performance',
                'title': 'Low R-squared',
                'current': r_squared,
                'target': 0.49,
                'root_cause': 'ELO explains <50% of variance in win rate',
                'impact': 'Prediction confidence low'
            })

        # Check ELO spread
        if elo_spread < 200 or elo_spread > 800:
            severity = 'INFO'
            self.issues.append({
                'severity': severity,
                'category': 'ELO Performance',
                'title': 'ELO spread outside optimal range',
                'current': elo_spread,
                'target': '200-800',
                'root_cause': 'K-factor may need tuning',
                'impact': 'Suboptimal discrimination'
            })

    def analyze_prediction_accuracy(self):
        """Analyze prediction accuracy metrics."""
        confusion_accuracy = self.metrics.get('confusion_accuracy', 0)
        elite_accuracy = self.metrics.get('elite_accuracy', 0)
        poor_accuracy = self.metrics.get('poor_accuracy', 0)

        # Check confusion matrix accuracy
        if confusion_accuracy < 0.50:
            severity = 'CRITICAL' if confusion_accuracy < 0.45 else 'WARNING'
            self.issues.append({
                'severity': severity,
                'category': 'Prediction Accuracy',
                'title': 'Low overall prediction accuracy',
                'current': confusion_accuracy,
                'target': 0.50,
                'root_cause': 'Insufficient resolved markets',
                'impact': 'Unreliable tier predictions'
            })

        # Check elite accuracy
        if elite_accuracy < 0.70:
            self.issues.append({
                'severity': 'WARNING',
                'category': 'Prediction Accuracy',
                'title': 'Elite ranking accuracy below target',
                'current': elite_accuracy,
                'target': 0.70,
                'root_cause': 'Sample size too small',
                'impact': 'Difficulty identifying top traders'
            })

        # Check poor accuracy
        if poor_accuracy < 0.70:
            self.issues.append({
                'severity': 'WARNING',
                'category': 'Prediction Accuracy',
                'title': 'Poor ranking accuracy below target',
                'current': poor_accuracy,
                'target': 0.70,
                'root_cause': 'Sample size too small',
                'impact': 'Difficulty identifying weak traders'
            })

    def analyze_errors(self):
        """Analyze error patterns."""
        num_fp = self.metrics.get('num_false_positives', 0)
        num_fn = self.metrics.get('num_false_negatives', 0)
        avg_fp_trades = self.metrics.get('avg_fp_trades', 0)

        # Check false positives
        if num_fp > 5:
            severity = 'WARNING' if num_fp <= 10 else 'CRITICAL'
            self.issues.append({
                'severity': severity,
                'category': 'Error Patterns',
                'title': 'High false positive count',
                'current': num_fp,
                'target': 5,
                'root_cause': f'Traders with {avg_fp_trades:.1f} avg trades (too few)',
                'impact': 'Overrating lucky traders'
            })

        # Check false negatives
        if num_fn > 5:
            self.issues.append({
                'severity': 'WARNING',
                'category': 'Error Patterns',
                'title': 'High false negative count',
                'current': num_fn,
                'target': 5,
                'root_cause': 'Underrating unlucky traders',
                'impact': 'Missing skilled traders'
            })

    def analyze_strategy_performance(self):
        """Analyze strategy performance."""
        best_roi = self.metrics.get('best_roi', 0)
        best_sharpe = self.metrics.get('best_sharpe', 0)

        # Check ROI
        if best_roi < 0.50:
            severity = 'CRITICAL' if best_roi < 0.30 else 'WARNING'
            self.issues.append({
                'severity': severity,
                'category': 'Strategy Performance',
                'title': 'Low strategy ROI',
                'current': best_roi,
                'target': 0.50,
                'root_cause': 'ELO not predicting skill well',
                'impact': 'Following top traders unprofitable'
            })

        # Check Sharpe
        if best_sharpe < 1.0:
            self.issues.append({
                'severity': 'WARNING',
                'category': 'Strategy Performance',
                'title': 'Low Sharpe ratio',
                'current': best_sharpe,
                'target': 1.0,
                'root_cause': 'High volatility in returns',
                'impact': 'Risk-adjusted returns suboptimal'
            })

    def prioritize_improvements(self):
        """Generate prioritized improvement recommendations."""
        # Group issues by severity
        critical = [i for i in self.issues if i['severity'] == 'CRITICAL']
        warning = [i for i in self.issues if i['severity'] == 'WARNING']
        info = [i for i in self.issues if i['severity'] == 'INFO']

        priority = 1

        # Critical issues
        if critical:
            # Group related data quality issues
            data_issues = [i for i in critical if i['category'] == 'Data Quality']
            if data_issues:
                self.recommendations.append({
                    'priority': priority,
                    'severity': 'CRITICAL',
                    'title': 'Increase sample size',
                    'issues': data_issues,
                    'action': 'Edit experiments/configs/config_simulation.json',
                    'changes': [
                        'markets.total: 50 -> 125',
                        'markets.resolved_ratio: 0.80 (keep)',
                        'trades.total: 2000 -> 5000'
                    ],
                    'expected_improvement': {
                        'resolved_markets': '+150%',
                        'correlation': '+0.15',
                        'accuracy': '+12%',
                        'false_positives': '-71%'
                    },
                    'time_to_fix': '5 minutes',
                    'confidence': 'HIGH'
                })
                priority += 1

            # Other critical issues
            other_critical = [i for i in critical if i['category'] != 'Data Quality']
            for issue in other_critical:
                self.recommendations.append({
                    'priority': priority,
                    'severity': 'CRITICAL',
                    'title': issue['title'],
                    'issues': [issue],
                    'time_to_fix': '30 minutes',
                    'confidence': 'MEDIUM'
                })
                priority += 1

        # Warning issues
        if warning:
            # Add recommendation for minimum trade threshold
            if any('false positive' in i['title'].lower() for i in warning):
                self.recommendations.append({
                    'priority': priority,
                    'severity': 'WARNING',
                    'title': 'Add minimum trade threshold',
                    'action': 'Add confidence filter in production',
                    'changes': [
                        'if trader_resolved_trades < 10: elo_confidence = "LOW"'
                    ],
                    'expected_improvement': {
                        'reliability': '+25%',
                        'false_positives': '-40%'
                    },
                    'time_to_fix': '30 minutes',
                    'confidence': 'MEDIUM'
                })
                priority += 1

        # Recommended improvements
        self.recommendations.append({
            'priority': priority,
            'severity': 'RECOMMENDED',
            'title': 'Implement time decay for ELO',
            'action': 'Add recency weighting to ELO calculation',
            'changes': [
                'weight = 1.0 (0-30d), 0.75 (30-60d), 0.5 (60-90d), 0.25 (90d+)'
            ],
            'expected_improvement': {
                'responsiveness': 'Better',
                'handles_streaks': 'Yes'
            },
            'time_to_fix': '2 hours',
            'confidence': 'MEDIUM'
        })
        priority += 1

        self.recommendations.append({
            'priority': priority,
            'severity': 'RECOMMENDED',
            'title': 'Implement market difficulty weighting',
            'action': 'Weight ELO changes by market difficulty',
            'changes': [
                'elo_change = k_factor * result * (1 + difficulty)'
            ],
            'expected_improvement': {
                'discrimination': '+15%',
                'rewards_hard_markets': 'Yes'
            },
            'time_to_fix': '3 hours',
            'confidence': 'MEDIUM'
        })

    def get_health_status(self, metric_value, target, higher_is_better=True):
        """Determine health status of a metric."""
        if higher_is_better:
            if metric_value >= target:
                return 'PASS'
            elif metric_value >= target * 0.9:
                return 'WARNING'
            else:
                return 'CRITICAL'
        else:
            if metric_value <= target:
                return 'PASS'
            elif metric_value <= target * 1.1:
                return 'WARNING'
            else:
                return 'CRITICAL'

    def generate_report(self, verbose: bool = True):
        """Generate comprehensive observer report."""
        print()
        print("=" * 70)
        print("  SIMULATION OBSERVER REPORT")
        print("=" * 70)
        print(f"  Pipeline: {self.pipeline_dir}")
        print(f"  Analyzed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print()

        # System health overview
        print("SYSTEM HEALTH OVERVIEW")
        print("-" * 30)

        # Data quality
        data_status = self.get_health_status(self.metrics.get('num_resolved_markets', 0), 80)
        icon = '[OK]' if data_status == 'PASS' else '[!!]' if data_status == 'WARNING' else '[XX]'
        print(f"{icon} Data Quality:         {data_status:<8}  "
              f"({self.metrics.get('num_traders', 0)} traders, "
              f"{self.metrics.get('num_resolved_markets', 0)} markets)")

        # ELO correlation
        corr_status = self.get_health_status(self.metrics.get('correlation', 0), 0.70)
        icon = '[OK]' if corr_status == 'PASS' else '[!!]' if corr_status == 'WARNING' else '[XX]'
        print(f"{icon} ELO Correlation:     {corr_status:<8}  "
              f"({self.metrics.get('correlation', 0):.3f})")

        # Prediction accuracy
        acc_status = self.get_health_status(self.metrics.get('confusion_accuracy', 0), 0.50)
        icon = '[OK]' if acc_status == 'PASS' else '[!!]' if acc_status == 'WARNING' else '[XX]'
        print(f"{icon} Prediction Accuracy: {acc_status:<8}  "
              f"({self.metrics.get('confusion_accuracy', 0)*100:.1f}%)")

        # Strategy performance
        roi = self.metrics.get('best_roi', 0)
        if roi > 0.80:
            strat_status = 'EXCELLENT'
            icon = '[OK]'
        elif roi > 0.50:
            strat_status = 'GOOD'
            icon = '[OK]'
        else:
            strat_status = 'POOR'
            icon = '[XX]'
        print(f"{icon} Strategy Performance: {strat_status:<8}  ({roi*100:.1f}% ROI)")

        # Sample size
        trades_pt = self.metrics.get('trades_per_trader', 0)
        sample_status = self.get_health_status(trades_pt, 20)
        icon = '[OK]' if sample_status == 'PASS' else '[!!]' if sample_status == 'WARNING' else '[XX]'
        print(f"{icon} Sample Size:          {sample_status:<8}  "
              f"(avg {trades_pt:.1f} trades/trader)")

        # Overall score
        statuses = [data_status, corr_status, acc_status, strat_status if strat_status != 'GOOD' else 'PASS', sample_status]
        pass_count = sum(1 for s in statuses if s in ['PASS', 'EXCELLENT', 'GOOD'])
        total = len(statuses)

        if pass_count >= 4:
            overall = 'EXCELLENT'
        elif pass_count >= 3:
            overall = 'GOOD'
        elif pass_count >= 2:
            overall = 'NEEDS IMPROVEMENT'
        else:
            overall = 'CRITICAL'

        print()
        print(f"Overall Score: {pass_count}/{total} ({overall})")
        print()

        # Priority improvements
        if self.recommendations:
            print("=" * 70)
            print("  PRIORITY IMPROVEMENTS")
            print("=" * 70)
            print()

            for rec in self.recommendations[:5]:  # Show top 5
                priority = rec['priority']
                severity = rec['severity']
                title = rec['title']

                icon = '[!!]' if severity == 'CRITICAL' else '[!]' if severity == 'WARNING' else '[*]'
                print(f"{icon} {severity} - Priority {priority}")
                print("-" * 30)
                print(f"Issue: {title}")

                if 'issues' in rec:
                    for issue in rec['issues']:
                        print(f"  Current: {issue['current']}")
                        print(f"  Target: {issue['target']}")
                        if 'root_cause' in issue:
                            print(f"  Root Cause: {issue['root_cause']}")

                if 'action' in rec:
                    print(f"\nAction: {rec['action']}")

                if 'changes' in rec:
                    for change in rec['changes']:
                        print(f"  - {change}")

                if 'expected_improvement' in rec:
                    print(f"\nExpected Result:")
                    for key, value in rec['expected_improvement'].items():
                        print(f"  - {key.replace('_', ' ').title()}: {value}")

                print(f"\nConfidence: {rec.get('confidence', 'MEDIUM')}")
                print(f"Time to Fix: {rec.get('time_to_fix', 'Unknown')}")
                print()

        # Detailed metrics
        print("=" * 70)
        print("  DETAILED METRICS")
        print("=" * 70)
        print()

        print("Data Quality:")
        print(f"  - Total traders: {self.metrics.get('num_traders', 0)}")
        print(f"  - Resolved markets: {self.metrics.get('num_resolved_markets', 0)}")
        print(f"  - Trades/trader: {self.metrics.get('trades_per_trader', 0):.1f}")
        print()

        print("ELO Performance:")
        print(f"  - Correlation: {self.metrics.get('correlation', 0):.3f}")
        print(f"  - R-squared: {self.metrics.get('r_squared', 0):.3f}")
        print(f"  - Optimal K-factor: {self.metrics.get('optimal_k_factor', 0)}")
        print(f"  - ELO spread: {self.metrics.get('elo_spread', 0):.1f} points")
        print()

        print("Prediction Accuracy:")
        print(f"  - Confusion accuracy: {self.metrics.get('confusion_accuracy', 0)*100:.1f}%")
        print(f"  - Elite accuracy: {self.metrics.get('elite_accuracy', 0)*100:.1f}%")
        print(f"  - Poor accuracy: {self.metrics.get('poor_accuracy', 0)*100:.1f}%")
        print()

        print("Error Analysis:")
        print(f"  - False positives: {self.metrics.get('num_false_positives', 0)}")
        print(f"  - False negatives: {self.metrics.get('num_false_negatives', 0)}")
        print(f"  - Avg trades (FP): {self.metrics.get('avg_fp_trades', 0):.1f}")
        print()

        print("Strategy Performance:")
        print(f"  - Best ROI: {self.metrics.get('best_roi', 0)*100:.1f}%")
        print(f"  - Best Sharpe: {self.metrics.get('best_sharpe', 0):.2f}")
        params = self.metrics.get('best_strategy_params', {})
        print(f"  - Strategy: {params}")
        print()

    def compare_pipelines(self, baseline_dir: str, improved_dir: str):
        """Compare two pipeline results."""
        print()
        print("=" * 70)
        print("  PIPELINE COMPARISON")
        print("=" * 70)
        print()

        # Load both pipelines
        baseline = SimulationObserver(baseline_dir)
        baseline.load_reports()
        baseline.extract_metrics()

        improved = SimulationObserver(improved_dir)
        improved.load_reports()
        improved.extract_metrics()

        print(f"Comparing: {baseline_dir} vs {improved_dir}")
        print()

        # Compare metrics
        metrics_to_compare = [
            ('Resolved Markets', 'num_resolved_markets', False),
            ('Correlation', 'correlation', True),
            ('Accuracy', 'confusion_accuracy', True),
            ('False Positives', 'num_false_positives', False),
            ('Best ROI', 'best_roi', True)
        ]

        print(f"{'Metric':<25} {'Baseline':<15} {'Improved':<15} {'Change':<15}")
        print("-" * 70)

        for label, key, is_percentage in metrics_to_compare:
            baseline_val = baseline.metrics.get(key, 0)
            improved_val = improved.metrics.get(key, 0)

            if baseline_val > 0:
                change_pct = ((improved_val - baseline_val) / baseline_val) * 100
            else:
                change_pct = 0

            if is_percentage:
                b_str = f"{baseline_val*100:.1f}%"
                i_str = f"{improved_val*100:.1f}%"
            else:
                b_str = f"{baseline_val:.1f}"
                i_str = f"{improved_val:.1f}"

            print(f"{label:<25} {b_str:<15} {i_str:<15} {change_pct:+.1f}%")

        print()

        # Determine winner
        improvements = sum(1 for _, key, _ in metrics_to_compare
                          if improved.metrics.get(key, 0) > baseline.metrics.get(key, 0))

        if improvements >= 3:
            print(f"Winner: IMPROVED (+{improvements}/{len(metrics_to_compare)} metrics improved)")
        else:
            print(f"Winner: BASELINE (only {improvements}/{len(metrics_to_compare)} metrics improved)")
        print()


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Analyze simulation results and suggest improvements',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze latest pipeline
  py scripts/simulation/simulation_observer.py

  # Analyze specific pipeline
  py scripts/simulation/simulation_observer.py --pipeline results/pipeline

  # Compare two pipelines
  py scripts/simulation/simulation_observer.py --compare results/pipeline results/improved

  # Export report
  py scripts/simulation/simulation_observer.py --export results/observer_report.txt
        """
    )

    parser.add_argument('--pipeline', type=str, default='results/pipeline',
                       help='Pipeline directory to analyze (default: results/pipeline)')

    parser.add_argument('--compare', type=str, nargs=2,
                       metavar=('BASELINE', 'IMPROVED'),
                       help='Compare two pipeline results')

    parser.add_argument('--export', type=str,
                       help='Export report to file')

    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')

    args = parser.parse_args()

    try:
        if args.compare:
            # Compare two pipelines
            observer = SimulationObserver(args.compare[0])
            observer.compare_pipelines(args.compare[0], args.compare[1])
        else:
            # Analyze single pipeline
            observer = SimulationObserver(args.pipeline)
            if not observer.load_reports():
                print(f"[ERROR] No reports found in {args.pipeline}")
                return 1

            observer.extract_metrics()
            observer.analyze_data_quality()
            observer.analyze_elo_performance()
            observer.analyze_prediction_accuracy()
            observer.analyze_errors()
            observer.analyze_strategy_performance()
            observer.prioritize_improvements()
            observer.generate_report(verbose=not args.quiet)

        return 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Cancelled by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
