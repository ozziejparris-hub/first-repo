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
    ("Sync trade categories",             SCRIPTS_DIR / "sync_trade_categories.py",        ["--incremental"], True),
    ("Detect ARB_BOT patterns",           SCRIPTS_DIR / "detect_arb_bots.py",             None, True),
    ("Promote high-P&L traders",          SCRIPTS_DIR / "promote_high_pnl_traders.py",    None, True),
    ("Resolution sweep",                  SCRIPTS_DIR / "resolution_sweep.py",            None, True),
    ("Update geo ELO scores",             SCRIPTS_DIR / "update_geo_elo.py",               None, True),
    ("Score insider signals",             SCRIPTS_DIR / "score_insider_signals.py",        None, True),
    ("Score STR-003 signals",             SCRIPTS_DIR / "score_str003_signals.py",         None, True),
    ("Backfill transaction hashes",       SCRIPTS_DIR / "backfill_transaction_hashes.py", ["--tier", "pool_c"], True),
    ("Label maker/taker roles",           SCRIPTS_DIR / "polygon_maker_taker.py",         ["--backfill", "--limit", "500"], True),
    ("Verify market titles",              SCRIPTS_DIR / "verify_market_titles.py",        None, True),
    ("Backfill market categories",        SCRIPTS_DIR / "backfill_market_categories.py",  ["--limit", "50"], True),
    ("Fetch new market resolutions",      SCRIPTS_DIR / "fast_resolution_check.py"),
    ("Resolve LEGENDARY trader markets",   SCRIPTS_DIR / "resolve_legendary_markets.py", ["--limit", "50"], True),
    ("Evaluate new trader results",        SCRIPTS_DIR / "evaluate_new_trader_results.py", None, True),
    ("Requeue resolved market traders",   SCRIPTS_DIR / "requeue_resolved_market_traders.py"),
    ("Apply full ELO modifiers",          SCRIPTS_DIR / "apply_full_elo_modifiers.py"),
    ("Resync position counts",            SCRIPTS_DIR / "resync_position_counts.py"),
    ("Snapshot ELO scores",               SCRIPTS_DIR / "snapshot_elo_scores.py",              None, True),
    ("Write integration health",          TRADING_SWARM_SCRIPTS / "write_integration_health.py"),
]

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"


def run_trade_dedup():
    print("\n--- Step: Deduplicate trades table ---")
    step_start = time.time()
    sql = (
        "DELETE FROM trades WHERE rowid NOT IN ("
        "SELECT MIN(rowid) FROM trades "
        "GROUP BY trader_address, market_id, outcome, timestamp, shares, price"
        "); SELECT changes();"
    )
    result = subprocess.run(
        ["sqlite3", str(DB_PATH), sql],
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - step_start
    if result.returncode != 0:
        print(f"    WARNING — dedup failed: {result.stderr.strip()} ({elapsed:.1f}s)")
        return
    deleted = result.stdout.strip() or "0"
    print(f"    Deleted {deleted} duplicate trade row(s) ({elapsed:.1f}s)")


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
        # Full ELO recalculation runs at 03:00 UTC via polymarket-sunday-elo.timer
        # daily_maintenance does NOT run --full-recalc — the timer owns it exclusively.
        # Weekly trader discovery — scans top geopolitics markets for new participants not yet in DB.
        # API-rate-limited so runs weekly only.
        steps.append(("Discover leaderboard traders", SCRIPTS_DIR / "discover_leaderboard_traders.py", ["--limit", "100"], True))
        print("\n[WEEKLY] Sunday — full ELO recalculation handled by polymarket-sunday-elo.timer (03:00 UTC)")

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

    if datetime.now().weekday() == 6:  # Sunday
        run_trade_dedup()

    # WAL checkpoint — clears accumulated WAL pages without blocking readers or writers.
    print("\n--- Step: WAL checkpoint ---")
    wal_result = subprocess.run(
        ["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(PASSIVE);"],
        capture_output=True,
        text=True,
    )
    if wal_result.returncode == 0:
        print(f"    OK — {wal_result.stdout.strip()}")
    else:
        print(f"    WARNING — WAL checkpoint failed: {wal_result.stderr.strip()}")

    # Backfill market dates — gradually fills end_date/resolution_date for geo markets.
    # Non-blocking: a Gamma API failure here should never abort maintenance.
    run_step(
        "Backfill market dates",
        SCRIPTS_DIR / "backfill_market_dates.py",
        extra_args=["--geo-only", "--limit", "500"],
    )

    # Hydrate stub markets for external_seed traders — ~5,929 markets inserted as stubs
    # during trade import have no metadata. Runs 200/day until the backlog is cleared.
    # Non-blocking: a Gamma API failure here should never abort maintenance.
    run_step(
        "Hydrate stub markets (external_seed)",
        SCRIPTS_DIR / "hydrate_stub_markets.py",
        extra_args=["--limit", "200"],
    )

    elapsed = time.time() - start
    print(f"\n=== MAINTENANCE COMPLETE === {elapsed:.1f}s total — all steps succeeded ===")


if __name__ == "__main__":
    main()
