#!/usr/bin/env python3
"""
Daily maintenance wrapper.
Runs fast_resolution_check.py, requeue_resolved_market_traders.py, then
apply_full_elo_modifiers.py in order.
Stops after any failed step — does not continue on bad data.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
STEPS = [
    ("Update research exclusions",        SCRIPTS_DIR / "update_research_exclusions.py"),
    ("Fetch new market resolutions",      SCRIPTS_DIR / "fast_resolution_check.py"),
    ("Requeue resolved market traders",   SCRIPTS_DIR / "requeue_resolved_market_traders.py"),
    ("Apply full ELO modifiers",          SCRIPTS_DIR / "apply_full_elo_modifiers.py"),
    ("Resync position counts",            SCRIPTS_DIR / "resync_position_counts.py"),
]

def run_step(label, script_path, extra_args=None):
    print(f"\n--- Step: {label} ---")
    print(f"    {script_path.name}")
    step_start = time.time()

    import os
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    # fast_resolution_check.py does `from database import Database` so needs
    # the monitoring/ directory on PYTHONPATH
    monitoring_dir = str(SCRIPTS_DIR.parent / 'monitoring')
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{monitoring_dir}{os.pathsep}{existing}" if existing else monitoring_dir

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        cwd=str(SCRIPTS_DIR.parent),
        env=env,
    )

    elapsed = time.time() - step_start
    if result.returncode == 0:
        print(f"    OK ({elapsed:.1f}s)")
        return True
    else:
        print(f"    FAILED — exit code {result.returncode} ({elapsed:.1f}s)")
        return False


def main():
    start = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== DAILY MAINTENANCE === {timestamp}")

    steps = list(STEPS)
    if datetime.now().weekday() == 6:  # Sunday
        steps.append(("Weekly full ELO recalculation",
                       SCRIPTS_DIR / "recalculate_comprehensive_elo.py",
                       ["--skip-correlation", "--skip-contrarian", "--skip-advanced-metrics"]))
        print("\n[WEEKLY] Sunday — full ELO recalculation added to run (--skip-correlation --skip-contrarian --skip-advanced-metrics)")

    for i, step in enumerate(steps, 1):
        label, script = step[0], step[1]
        extra_args = step[2] if len(step) > 2 else None
        print(f"\n[{i}/{len(steps)}] {label}")
        ok = run_step(label, script, extra_args)
        if not ok:
            elapsed = time.time() - start
            print(f"\n=== MAINTENANCE FAILED at step {i} ({elapsed:.1f}s total) ===")
            print(f"    Step {i} ({label}) failed — remaining steps skipped.")
            sys.exit(1)

    elapsed = time.time() - start
    print(f"\n=== MAINTENANCE COMPLETE === {elapsed:.1f}s total — all steps succeeded ===")


if __name__ == "__main__":
    main()
