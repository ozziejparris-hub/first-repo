#!/usr/bin/env python3
"""
Polymarket Full Validation Pipeline

Runs complete ELO system validation workflow in one command.

Pipeline Stages:
1. Data Generation - Seed test data
2. ELO Calculation - Calculate ratings
3. Validation - Automated tests
4. Optimization - Find best K-factor
5. Backtesting - Test strategies
6. Error Analysis - Identify failures
7. System Comparison - A/B testing
8. Final Report - Summary

Usage:
    py scripts/simulation/run_full_pipeline.py                    # Full pipeline
    py scripts/simulation/run_full_pipeline.py --quick            # Fast mode
    py scripts/simulation/run_full_pipeline.py --stages 1-4       # Partial run
    py scripts/simulation/run_full_pipeline.py --export results/  # Save all reports
"""

import sys
import os
import subprocess
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _sim_db_guard import add_sim_db_args, resolve_sim_db, SIM_DB_DEFAULT


class PipelineOrchestrator:
    """Orchestrate full validation pipeline."""

    def __init__(self, export_dir: str = None, verbose: bool = True, db_path: str = SIM_DB_DEFAULT):
        """Initialize orchestrator."""
        self.export_dir = export_dir or 'results/pipeline'
        self.verbose = verbose
        self.db_path = db_path
        self.results = {}
        self.start_time = None
        self.stage_times = {}

    def run_command(self, cmd: List[str], stage_name: str) -> tuple:
        """
        Run a command and capture output.

        Args:
            cmd: Command to run as list of strings
            stage_name: Name for logging

        Returns:
            (return_code, stdout, stderr)
        """
        if self.verbose:
            print(f"  Running: {' '.join(cmd)}")

        start = time.time()

        try:
            # Set PYTHONPATH to project root so child processes can import modules
            project_root = Path(__file__).parent.parent.parent
            env = os.environ.copy()
            env['PYTHONPATH'] = str(project_root)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=project_root,
                env=env  # Pass environment with PYTHONPATH
            )

            elapsed = time.time() - start
            self.stage_times[stage_name] = elapsed

            if self.verbose:
                print(f"  Completed in {elapsed:.1f}s")

            return result.returncode, result.stdout, result.stderr

        except Exception as e:
            if self.verbose:
                print(f"  ERROR: {e}")
            return 1, "", str(e)

    def stage_1_data_generation(self) -> bool:
        """Stage 1: Generate simulation data."""
        print()
        print("=" * 70)
        print("  STAGE 1: DATA GENERATION")
        print("=" * 70)
        print()

        # Seed new data
        cmd_seed = [
            'py', 'scripts/simulation/seed_test_data.py',
            '--config', 'experiments/configs/config_simulation.json',
            '--clear-simulation',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd_seed, 'seed_data')

        if returncode != 0:
            print(f"[ERROR] Failed to seed simulation data")
            print(stderr)
            return False

        self.results['data_generation'] = {
            'success': True,
            'output': stdout[-500:] if len(stdout) > 500 else stdout  # Last 500 chars
        }

        print("[OK] Stage 1 complete: Data generated")
        return True

    def stage_2_elo_calculation(self) -> bool:
        """Stage 2: Calculate ELO ratings."""
        print()
        print("=" * 70)
        print("  STAGE 2: ELO CALCULATION")
        print("=" * 70)
        print()

        cmd = [
            'py', 'scripts/simulation/calculate_elo_simple.py',
            '--k-factor', '32',
            '--write-to-db',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'calculate_elo')

        if returncode != 0:
            print(f"[ERROR] Failed to calculate ELO")
            print(stderr)
            return False

        self.results['elo_calculation'] = {
            'success': True,
            'k_factor': 32,
            'output': stdout[-500:] if len(stdout) > 500 else stdout
        }

        print("[OK] Stage 2 complete: ELO calculated")
        return True

    def stage_3_validation(self) -> bool:
        """Stage 3: Validate ELO accuracy."""
        print()
        print("=" * 70)
        print("  STAGE 3: VALIDATION")
        print("=" * 70)
        print()

        export_path = os.path.join(self.export_dir, 'validation_report.json')
        os.makedirs(self.export_dir, exist_ok=True)

        cmd = [
            'py', 'scripts/simulation/verify_elo_rankings.py',
            '--simulation-age-days', '7',
            '--threshold', '0.5',
            '--export', export_path,
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'validation')

        if returncode != 0:
            print(f"[WARNING] Validation tests failed (expected for some systems)")

        # Load results
        try:
            with open(export_path, 'r') as f:
                validation_data = json.load(f)

            self.results['validation'] = validation_data

            num_passed = sum(1 for r in validation_data.get('test_results', []) if r.get('passed'))
            num_total = len(validation_data.get('test_results', []))

            print(f"[OK] Stage 3 complete: {num_passed}/{num_total} tests passed")
            return True

        except Exception as e:
            print(f"[WARNING] Could not load validation results: {e}")
            return True  # Non-fatal

    def stage_4_optimization(self) -> bool:
        """Stage 4: Optimize parameters."""
        print()
        print("=" * 70)
        print("  STAGE 4: OPTIMIZATION")
        print("=" * 70)
        print()

        export_path = os.path.join(self.export_dir, 'optimization_report.json')

        cmd = [
            'py', 'scripts/simulation/optimize_parameters.py',
            '--k-range', '24', '40',
            '--optimize-for', 'combined',
            '--export', export_path,
            '--quiet',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'optimization')

        if returncode != 0:
            print(f"[ERROR] Optimization failed")
            print(stderr)
            return False

        # Load results
        try:
            with open(export_path, 'r') as f:
                opt_data = json.load(f)

            self.results['optimization'] = opt_data

            best_k = opt_data.get('optimal_k_factor', 'Unknown')
            print(f"[OK] Stage 4 complete: Best K-factor = {best_k}")
            return True

        except Exception as e:
            print(f"[WARNING] Could not load optimization results: {e}")
            return True  # Non-fatal

    def stage_5_backtesting(self) -> bool:
        """Stage 5: Backtest strategies."""
        print()
        print("=" * 70)
        print("  STAGE 5: BACKTESTING")
        print("=" * 70)
        print()

        export_path = os.path.join(self.export_dir, 'backtest_report.json')

        cmd = [
            'py', 'scripts/simulation/backtest_strategy.py',
            '--all-strategies',
            '--export', export_path,
            '--quiet',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'backtesting')

        if returncode != 0:
            print(f"[ERROR] Backtesting failed")
            print(stderr)
            return False

        # Load results
        try:
            with open(export_path, 'r') as f:
                backtest_data = json.load(f)

            self.results['backtesting'] = backtest_data

            strategies = backtest_data.get('strategies', [])
            if strategies:
                best = max(strategies, key=lambda s: s.get('roi', 0))
                roi = best.get('roi', 0) * 100
                print(f"[OK] Stage 5 complete: Best ROI = {roi:.1f}%")
            else:
                print(f"[OK] Stage 5 complete")

            return True

        except Exception as e:
            print(f"[WARNING] Could not load backtesting results: {e}")
            return True  # Non-fatal

    def stage_6_error_analysis(self) -> bool:
        """Stage 6: Analyze prediction errors."""
        print()
        print("=" * 70)
        print("  STAGE 6: ERROR ANALYSIS")
        print("=" * 70)
        print()

        export_path = os.path.join(self.export_dir, 'analysis_report.json')

        cmd = [
            'py', 'scripts/simulation/analyze_predictions.py',
            '--export', export_path,
            '--quiet',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'error_analysis')

        if returncode != 0:
            print(f"[ERROR] Error analysis failed")
            print(stderr)
            return False

        # Load results
        try:
            with open(export_path, 'r') as f:
                analysis_data = json.load(f)

            self.results['error_analysis'] = analysis_data

            num_fp = len(analysis_data.get('analysis', {}).get('false_positives', []))
            num_fn = len(analysis_data.get('analysis', {}).get('false_negatives', []))
            print(f"[OK] Stage 6 complete: {num_fp} false positives, {num_fn} false negatives")
            return True

        except Exception as e:
            print(f"[WARNING] Could not load analysis results: {e}")
            return True  # Non-fatal

    def stage_7_system_comparison(self) -> bool:
        """Stage 7: Compare systems."""
        print()
        print("=" * 70)
        print("  STAGE 7: SYSTEM COMPARISON")
        print("=" * 70)
        print()

        export_path = os.path.join(self.export_dir, 'comparison_report.json')

        cmd = [
            'py', 'scripts/simulation/compare_systems.py',
            '--all',
            '--export', export_path,
            '--quiet',
            '--db-path', self.db_path
        ]

        returncode, stdout, stderr = self.run_command(cmd, 'comparison')

        if returncode != 0:
            print(f"[ERROR] System comparison failed")
            print(stderr)
            return False

        # Load results
        try:
            with open(export_path, 'r') as f:
                comparison_data = json.load(f)

            self.results['comparison'] = comparison_data

            num_configs = len(comparison_data.get('comparisons', []))
            print(f"[OK] Stage 7 complete: {num_configs} configurations compared")
            return True

        except Exception as e:
            print(f"[WARNING] Could not load comparison results: {e}")
            return True  # Non-fatal

    def stage_8_final_report(self):
        """Stage 8: Generate final summary report."""
        print()
        print("=" * 70)
        print("  STAGE 8: FINAL REPORT")
        print("=" * 70)
        print()

        # Generate summary
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_time': sum(self.stage_times.values()),
            'stage_times': self.stage_times,
            'results': self.results
        }

        # Export summary
        summary_path = os.path.join(self.export_dir, 'pipeline_summary.json')
        os.makedirs(self.export_dir, exist_ok=True)

        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)

        # Print executive summary
        print()
        print("=" * 70)
        print("  EXECUTIVE SUMMARY")
        print("=" * 70)
        print()

        # Validation results
        if 'validation' in self.results:
            val_results = self.results['validation'].get('test_results', [])
            num_passed = sum(1 for r in val_results if r.get('passed'))
            num_total = len(val_results)
            print(f"Validation: {num_passed}/{num_total} tests passed")

        # Optimization results
        if 'optimization' in self.results:
            best_k = self.results['optimization'].get('optimal_k_factor', 'N/A')
            best_metrics = self.results['optimization'].get('best_metrics', {})
            corr = best_metrics.get('correlation', 0)
            print(f"Optimal K-factor: {best_k} (correlation: {corr:.3f})")

        # Backtesting results
        if 'backtesting' in self.results:
            strategies = self.results['backtesting'].get('strategies', [])
            if strategies:
                best = max(strategies, key=lambda s: s.get('roi', 0))
                roi = best.get('roi', 0) * 100
                params = best.get('params', {})
                print(f"Best Strategy: ROI = {roi:.1f}% ({params})")

        # Error analysis results
        if 'error_analysis' in self.results:
            analysis = self.results['error_analysis'].get('analysis', {})
            cm_acc = analysis.get('confusion_matrix_accuracy', {})
            if cm_acc:
                acc = cm_acc.get('accuracy', 0) * 100
                print(f"Prediction Accuracy: {acc:.1f}%")

        print()
        print(f"Total Runtime: {sum(self.stage_times.values()):.1f}s")
        print(f"Reports saved to: {self.export_dir}")
        print()
        print(f"[OK] Pipeline complete!")
        print()

    def run_pipeline(self, stages: List[int] = None):
        """Run full pipeline or specified stages."""
        if stages is None:
            stages = list(range(1, 9))  # All 8 stages

        self.start_time = time.time()

        print()
        print("=" * 70)
        print("  POLYMARKET ELO VALIDATION PIPELINE")
        print("=" * 70)
        print(f"  Stages: {stages}")
        print(f"  Export directory: {self.export_dir}")
        print("=" * 70)

        # Create export directory
        os.makedirs(self.export_dir, exist_ok=True)

        # Run stages
        stage_functions = {
            1: self.stage_1_data_generation,
            2: self.stage_2_elo_calculation,
            3: self.stage_3_validation,
            4: self.stage_4_optimization,
            5: self.stage_5_backtesting,
            6: self.stage_6_error_analysis,
            7: self.stage_7_system_comparison,
            8: self.stage_8_final_report
        }

        for stage_num in stages:
            if stage_num in stage_functions:
                try:
                    if stage_num == 8:
                        # Final report doesn't return bool
                        stage_functions[stage_num]()
                    else:
                        success = stage_functions[stage_num]()
                        if not success:
                            print(f"\n[ERROR] Stage {stage_num} failed. Stopping pipeline.")
                            return False
                except Exception as e:
                    print(f"\n[ERROR] Stage {stage_num} crashed: {e}")
                    import traceback
                    traceback.print_exc()
                    return False

        return True


def main():
    """Entry point with CLI arguments."""
    parser = argparse.ArgumentParser(
        description='Run full ELO validation pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline
  py scripts/simulation/run_full_pipeline.py

  # Quick mode (stages 1-4 only)
  py scripts/simulation/run_full_pipeline.py --quick

  # Run specific stages
  py scripts/simulation/run_full_pipeline.py --stages 1 2 3

  # Custom export directory
  py scripts/simulation/run_full_pipeline.py --export-dir results/my_validation
        """
    )

    parser.add_argument('--quick', action='store_true',
                       help='Quick mode (stages 1-4 only)')

    parser.add_argument('--stages', type=int, nargs='+',
                       help='Specific stages to run (1-8)')

    parser.add_argument('--export-dir', type=str,
                       default='results/pipeline',
                       help='Directory for all exports (default: results/pipeline)')

    parser.add_argument('--quiet', action='store_true',
                       help='Suppress verbose output')
    add_sim_db_args(parser)

    args = parser.parse_args()

    # Determine stages
    if args.quick:
        stages = [1, 2, 3, 4]
    elif args.stages:
        stages = args.stages
    else:
        stages = list(range(1, 9))  # All stages

    # Create orchestrator
    orchestrator = PipelineOrchestrator(
        export_dir=args.export_dir,
        verbose=not args.quiet,
        db_path=resolve_sim_db(args)
    )

    # Run pipeline
    try:
        success = orchestrator.run_pipeline(stages=stages)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Pipeline cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
