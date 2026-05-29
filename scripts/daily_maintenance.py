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
SCRIPTS_DIR = Path(__file__).parent
TRADING_SWARM_SCRIPTS = Path("/home/parison/trading-swarm/scripts")
# Each entry: (label, script_path [, extra_args] [, non_blocking])
# non_blocking=True  → log WARNING on failure but continue; don't abort.
STEPS = [
    ("Update research exclusions",        SCRIPTS_DIR / "update_research_exclusions.py"),
    ("Promote high-P&L traders",          SCRIPTS_DIR / "promote_high_pnl_traders.py",    None, True),
    ("Resolution sweep",                  SCRIPTS_DIR / "resolution_sweep.py",            None, True),
    ("Update geo ELO scores",             SCRIPTS_DIR / "update_geo_elo.py",               None, True),
    ("Score insider signals",             SCRIPTS_DIR / "score_insider_signals.py",        None, True),
    ("Score STR-003 signals",             SCRIPTS_DIR / "score_str003_signals.py",         None, True),
    ("Verify market titles",              SCRIPTS_DIR / "verify_market_titles.py",        None, True),
    ("Fetch new market resolutions",      SCRIPTS_DIR / "fast_resolution_check.py"),
    ("Evaluate new trader results",        SCRIPTS_DIR / "evaluate_new_trader_results.py", None, True),
    ("Requeue resolved market traders",   SCRIPTS_DIR / "requeue_resolved_market_traders.py"),
    ("Apply full ELO modifiers",          SCRIPTS_DIR / "apply_full_elo_modifiers.py"),
    ("Resync position counts",            SCRIPTS_DIR / "resync_position_counts.py"),
    ("Write integration health",          TRADING_SWARM_SCRIPTS / "write_integration_health.py"),
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
        # Replace incremental geo ELO step with full recalc on Sundays.
        steps = [
            ("Update geo ELO scores (full recalc)", s[1], ["--full-recalc"], True)
            if s[0] == "Update geo ELO scores" else s
            for s in steps
        ]
        steps.append(("Weekly full ELO recalculation",
                       SCRIPTS_DIR / "recalculate_comprehensive_elo.py",
                       ["--skip-correlation", "--skip-contrarian", "--skip-advanced-metrics"]))
        # Weekly trader discovery — scans top geopolitics markets for new participants not yet in DB.
        # API-rate-limited so runs weekly only.
        steps.append(("Discover leaderboard traders", SCRIPTS_DIR / "discover_leaderboard_traders.py", ["--limit", "100"], True))
        print("\n[WEEKLY] Sunday — full ELO recalculation added to run (--skip-correlation --skip-contrarian --skip-advanced-metrics)")
        print("[WEEKLY] Sunday — geo ELO full recalculation enabled (--full-recalc)")

    for i, step in enumerate(steps, 1):
        label        = step[0]
        script       = step[1]
        extra_args   = step[2] if len(step) > 2 else None
        non_blocking = step[3] if len(step) > 3 else False
        print(f"\n[{i}/{len(steps)}] {label}")
        ok = run_step(label, script, extra_args)
        if not ok:
            if non_blocking:
                print(f"    WARNING — step {i} ({label}) failed; continuing anyway (non-blocking).")
            else:
                elapsed = time.time() - start
                print(f"\n=== MAINTENANCE FAILED at step {i} ({elapsed:.1f}s total) ===")
                print(f"    Step {i} ({label}) failed — remaining steps skipped.")
                sys.exit(1)

    elapsed = time.time() - start
    print(f"\n=== MAINTENANCE COMPLETE === {elapsed:.1f}s total — all steps succeeded ===")


if __name__ == "__main__":
    main()
