#!/usr/bin/env python3
"""
Daily maintenance wrapper.
Runs requeue_resolved_market_traders.py then apply_full_elo_modifiers.py in order.
Stops after step 1 if it fails — does not apply modifiers on bad data.
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
STEPS = [
    ("Requeue resolved market traders", SCRIPTS_DIR / "requeue_resolved_market_traders.py"),
    ("Apply full ELO modifiers",        SCRIPTS_DIR / "apply_full_elo_modifiers.py"),
]

def run_step(label, script_path):
    print(f"\n--- Step: {label} ---")
    print(f"    {script_path.name}")
    step_start = time.time()

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(SCRIPTS_DIR.parent),
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

    for i, (label, script) in enumerate(STEPS, 1):
        print(f"\n[{i}/{len(STEPS)}] {label}")
        ok = run_step(label, script)
        if not ok:
            elapsed = time.time() - start
            print(f"\n=== MAINTENANCE FAILED at step {i} ({elapsed:.1f}s total) ===")
            print(f"    Step {i} ({label}) failed — remaining steps skipped.")
            sys.exit(1)

    elapsed = time.time() - start
    print(f"\n=== MAINTENANCE COMPLETE === {elapsed:.1f}s total — all steps succeeded ===")


if __name__ == "__main__":
    main()
