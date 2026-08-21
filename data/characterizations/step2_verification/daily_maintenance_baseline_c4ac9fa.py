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

# O-27: default subprocess budget for any step that doesn't specify its own.
# Sized above the highest historical max among steps WITHOUT an explicit override —
# "Verify market titles" hit 7204.7s once (2026-06-09, RPC incident) and "Evaluate new
# trader results" hit 5017.4s once; every other unbudgeted step has never exceeded ~500s
# across 35 days of logged runs. 3h clears both with 50%+ headroom.
DEFAULT_STEP_TIMEOUT = 10800  # 3h

# Each entry: (label, script_path [, extra_args] [, non_blocking] [, timeout])
# non_blocking=True  → log WARNING on failure but continue; don't abort.
# timeout            → per-step subprocess.run() budget in seconds; defaults to
#                       DEFAULT_STEP_TIMEOUT when omitted. On expiry the step is killed
#                       and treated as FAILED (same as a non-zero exit code) — subject
#                       to the same non_blocking handling as any other failure.
STEPS = [
    ("Update research exclusions",        SCRIPTS_DIR / "update_research_exclusions.py"),
    ("Sync trade categories",             SCRIPTS_DIR / "sync_trade_categories.py",        ["--incremental"], True),
    ("Detect ARB_BOT patterns",           SCRIPTS_DIR / "detect_arb_bots.py",             None, True),
    ("Promote high-P&L traders",          SCRIPTS_DIR / "promote_high_pnl_traders.py",    None, True),
    ("Resolution sweep",                  SCRIPTS_DIR / "resolution_sweep.py",            None, True),
    # Recomputes all geo_resolved_trades_count values canonically and re-gates Pool C
    # immediately before the audit gate. Catches sync_trade_categories drift (and any
    # other pre-audit category changes). Blocking: exits 0 normally; non-zero only on
    # hard DB error.
    ("Reconcile geo resolved counts [pre-audit]",  SCRIPTS_DIR / "reconcile_geo_resolved_counts.py"),
    # EXIT CONTRACT: audit_invariants exits 2 on any Tier-1 CRITICAL (impossible state →
    # hard abort before ELO writes); exits 0 on PASS or REGRESSION-only (Telegram alert
    # already sent, run continues). Never exits 1. Non-blocking=False (default) so the
    # existing blocking-step abort path catches exit 2.
    ("Integrity audit (pre-ELO gate)",   SCRIPTS_DIR / "audit_invariants.py",            ["--alert"]),
    # Code-drift check: alerts if any .py file hardcodes ELO thresholds instead of using
    # canonical column_definitions constants. NON-BLOCKING — a code smell, not a data gate.
    ("Canonical definitions drift",      SCRIPTS_DIR / "check_canonical_definitions.py", ["--alert"], True),
    ("Update geo ELO scores",             SCRIPTS_DIR / "update_geo_elo.py",               None, True),
    ("Score insider signals",             SCRIPTS_DIR / "score_insider_signals.py",        None, True),
    ("Score STR-003 signals",             SCRIPTS_DIR / "score_str003_signals.py",         None, True),
    # Recent normal (last 10 runs): 6883-10714s (~2-3h). Historical worst case during the
    # 2026-06-09/06-12 RPC incident: 22996.8s (6.39h), completed successfully (not a true
    # hang). Budget set above that so no normal-if-slow run is ever killed.
    ("Backfill transaction hashes",       SCRIPTS_DIR / "backfill_transaction_hashes.py", ["--tier", "pool_c"], True, 28800),  # 8h
    # Stable: max ever observed 239.6s across 35 runs. Generous 7.5x headroom for a bad
    # API day without being reckless — this is the step named in the O-27 incident report.
    ("Label maker/taker roles",           SCRIPTS_DIR / "polygon_maker_taker.py",         ["--backfill", "--limit", "500"], True, 1800),  # 30min
    ("Verify market titles",              SCRIPTS_DIR / "verify_market_titles.py",        None, True),
    ("Backfill market categories",        SCRIPTS_DIR / "backfill_market_categories.py",  ["--limit", "50"], True),
    ("Fetch new market resolutions",      SCRIPTS_DIR / "fast_resolution_check.py",       ["--stale-limit", "500"], True),
    ("Register STR-002 signals",           SCRIPTS_DIR / "register_str002_signals.py",     None, True),
    ("Enrich STR-002 metadata",            SCRIPTS_DIR / "enrich_str002_metadata.py",      None, True),
    ("Score STR-002 signals",              SCRIPTS_DIR / "score_str002_signals.py",        None, True),
    ("Resolve LEGENDARY trader markets",   SCRIPTS_DIR / "resolve_legendary_markets.py", ["--limit", "50"], True),
    ("Evaluate new trader results",        SCRIPTS_DIR / "evaluate_new_trader_results.py", None, True),
    # Settles geo counts after post-audit evaluation. evaluate_new_trader_results flips
    # pending→won/lost on geo trades, changing geo_resolved_trades_count. Running here
    # ensures the next morning's audit opens on a clean reconciled state.
    # Non-blocking: settlement pass, not a gate; morning's reconcile #1 is the real gate.
    ("Reconcile geo resolved counts [post-eval]",  SCRIPTS_DIR / "reconcile_geo_resolved_counts.py", None, True),
    ("Requeue resolved market traders",   SCRIPTS_DIR / "requeue_resolved_market_traders.py"),
    ("Apply full ELO modifiers",          SCRIPTS_DIR / "apply_full_elo_modifiers.py"),
    ("Resync position counts",            SCRIPTS_DIR / "resync_position_counts.py"),
    ("Detect counter-signals",            SCRIPTS_DIR / "detect_counter_signals.py",           None, True),
    ("Snapshot ELO scores",               SCRIPTS_DIR / "snapshot_elo_scores.py",              None, True),
    ("Snapshot order books",              SCRIPTS_DIR / "snapshot_order_books.py",             None, True),
    ("Write integration health",          TRADING_SWARM_SCRIPTS / "write_integration_health.py"),
]

DB_PATH = Path(__file__).parent.parent / "data" / "polymarket_tracker.db"


def run_test_suite() -> bool:
    """Run the test suite and write results to tests/LATEST_TEST_RESULTS.md. Always
    non-blocking (never aborts the run) but now RETURNS pass/fail (O-26) so main()
    can include it in the honest completion banner instead of discarding it."""
    repo_root = SCRIPTS_DIR.parent
    runner    = repo_root / "run_tests.py"
    out_path  = repo_root / "tests" / "LATEST_TEST_RESULTS.md"

    print("\n--- Step: Run test suite ---")
    step_start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(runner), "--verbose"],
            capture_output=True, text=True,
            cwd=str(repo_root), timeout=300,
        )
        output  = result.stdout + (result.stderr or "")
        passed  = result.returncode == 0
        elapsed = time.time() - step_start
        status  = "ALL TESTS PASSED" if passed else "FAILURES DETECTED"

        header = (
            f"# Test Suite Results\n\n"
            f"**Run:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
            f"**Duration:** {elapsed:.1f}s  \n"
            f"**Result:** {status}\n\n---\n\n"
        )
        out_path.write_text(header + output, encoding="utf-8")

        level = "PASS" if passed else "WARNING"
        print(f"    {level} — {status} ({elapsed:.1f}s) → tests/LATEST_TEST_RESULTS.md")
        return passed
    except Exception as exc:
        elapsed = time.time() - step_start
        print(f"    WARNING — test suite runner error: {exc} ({elapsed:.1f}s)")
        try:
            out_path.write_text(
                f"# Test Suite Results\n\n"
                f"**Run:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
                f"**Result:** ERROR — runner crashed\n\n```\n{exc}\n```\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        return False


def run_trade_dedup() -> bool:
    """O-26: now returns pass/fail so main() can include it in the honest banner
    instead of discarding it (previously a bare call, failure was WARNING-only)."""
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
        return False
    deleted = result.stdout.strip() or "0"
    print(f"    Deleted {deleted} duplicate trade row(s) ({elapsed:.1f}s)")
    return True


def run_step(label, script_path, extra_args=None, timeout=DEFAULT_STEP_TIMEOUT):
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

    try:
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPTS_DIR.parent),
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run() already killed the child before raising this.
        elapsed = time.time() - step_start
        print(f"    WARNING — step exceeded {timeout}s budget, killed ({elapsed:.1f}s)")
        return False

    elapsed = time.time() - step_start
    if result.returncode == 0:
        print(f"    OK ({elapsed:.1f}s)")
        return True
    else:
        print(f"    FAILED — exit code {result.returncode} ({elapsed:.1f}s)")
        return False


def build_steps(weekday):
    """Return the ordered step list for a given weekday (0=Monday ... 6=Sunday).

    Pure function (no datetime.now() call) so the Sunday-only gating can be
    unit-tested directly against every weekday value without mocking time.
    """
    steps = list(STEPS)
    if weekday == 6:  # Sunday
        # Full ELO recalculation runs at 03:00 UTC via polymarket-sunday-elo.timer
        # daily_maintenance does NOT run --full-recalc — the timer owns it exclusively.
        # Weekly trader discovery — scans top geopolitics markets for new participants not yet in DB.
        # API-rate-limited so runs weekly only.
        # Proven offender (O-27): all 3 successful runs took 5.45-7.19h, and the first-ever
        # run (05-31) was manually SIGKILLed (exit -9) after 4.43h — someone already hit
        # this exact hang before there was a budget to catch it.
        steps.append(("Discover leaderboard traders", SCRIPTS_DIR / "discover_leaderboard_traders.py", ["--limit", "100"], True, 36000))  # 10h
        # O-2 backstop: the daily "Sync trade categories" step above only runs --incremental
        # (7-day timestamp window), which structurally can never catch a market whose
        # category is set after its trades already exist with an old timestamp (confirmed
        # root cause: background_backfill_worker.py inserts trades with a hardcoded
        # 'Unknown' category regardless of the parent market's real category — source fix
        # deferred, see O-30). Weekly --full-sync bounds that drift to at most 7 days'
        # accumulation instead of growing unbounded. Idempotent (WHERE clause only ever
        # touches genuinely-mismatched rows) — measured 2026-07-10: ~31s for a 277K-row
        # backlog (14s count + 17s batched update), so 30min is generous headroom even if
        # the backlog balloons well beyond anything seen so far.
        steps.append(("Sync trade categories [full, weekly]", SCRIPTS_DIR / "sync_trade_categories.py", ["--full-sync"], True, 1800))  # 30min
    return steps


def build_banner(passed_count: int, total_count: int, failed_labels: list, elapsed: float) -> str:
    """Pure function: the honest maintenance-completion banner (O-26, Fable finding
    4.1). Kept separate from step execution so it's directly unit-testable without
    running any subprocess — see tests/test_maintenance_banner_honesty.py.

    Both strings start with "=== MAINTENANCE COMPLETE" so any existing health-check
    grep for that literal phrase still matches on EITHER outcome (backward compatible
    with whatever's been grepping this all month) — but "ALL OK" vs "FAILURES:" are
    trivially distinct substrings for a grep that wants to tell them apart, which is
    the actual point of this fix.
    """
    if failed_labels:
        names = ", ".join(failed_labels)
        return (f"=== MAINTENANCE COMPLETE — FAILURES: {passed_count}/{total_count} OK "
                f"— FAILED: {names} === {elapsed:.1f}s total ===")
    return f"=== MAINTENANCE COMPLETE — ALL OK: {passed_count}/{total_count} steps === {elapsed:.1f}s total ==="


def main():
    start = time.time()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== DAILY MAINTENANCE === {timestamp}")

    weekday = datetime.now().weekday()
    steps = build_steps(weekday)
    if weekday == 6:  # Sunday
        print("\n[WEEKLY] Sunday — full ELO recalculation handled by polymarket-sunday-elo.timer (03:00 UTC)")

    # O-26: every step's real pass/fail is accumulated here instead of being
    # discarded, so the final banner can tell the truth about what happened.
    failed_steps = []
    total_tracked = len(steps)

    for i, step in enumerate(steps, 1):
        label        = step[0]
        script       = step[1]
        extra_args   = step[2] if len(step) > 2 else None
        non_blocking = step[3] if len(step) > 3 else False
        timeout      = step[4] if len(step) > 4 else DEFAULT_STEP_TIMEOUT
        print(f"\n[{i}/{len(steps)}] {label}")
        ok = run_step(label, script, extra_args, timeout=timeout)
        if not ok:
            failed_steps.append(label)
            if non_blocking:
                print(f"    WARNING — step {i} ({label}) failed; continuing anyway (non-blocking).")
            else:
                elapsed = time.time() - start
                print(f"\n=== MAINTENANCE FAILED at step {i} ({elapsed:.1f}s total) ===")
                print(f"    Step {i} ({label}) failed — remaining steps skipped.")
                sys.exit(1)

    if datetime.now().weekday() == 6:  # Sunday
        total_tracked += 1
        if not run_trade_dedup():
            failed_steps.append("Deduplicate trades table")

    total_tracked += 1
    if not run_test_suite():
        failed_steps.append("Run test suite")

    # WAL checkpoint — clears accumulated WAL pages without blocking readers or writers.
    print("\n--- Step: WAL checkpoint ---")
    wal_result = subprocess.run(
        ["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(PASSIVE);"],
        capture_output=True,
        text=True,
    )
    total_tracked += 1
    if wal_result.returncode == 0:
        print(f"    OK — {wal_result.stdout.strip()}")
    else:
        print(f"    WARNING — WAL checkpoint failed: {wal_result.stderr.strip()}")
        failed_steps.append("WAL checkpoint")

    # Backfill market dates — gradually fills end_date/resolution_date for geo markets.
    # Non-blocking: a Gamma API failure here should never abort maintenance.
    total_tracked += 1
    if not run_step(
        "Backfill market dates",
        SCRIPTS_DIR / "backfill_market_dates.py",
        extra_args=["--geo-only", "--limit", "500"],
    ):
        failed_steps.append("Backfill market dates")

    # Hydrate stub markets for external_seed traders — ~5,929 markets inserted as stubs
    # during trade import have no metadata. Runs 200/day until the backlog is cleared.
    # Non-blocking: a Gamma API failure here should never abort maintenance.
    total_tracked += 1
    if not run_step(
        "Hydrate stub markets (external_seed)",
        SCRIPTS_DIR / "hydrate_stub_markets.py",
        extra_args=["--limit", "200"],
    ):
        failed_steps.append("Hydrate stub markets (external_seed)")

    elapsed = time.time() - start
    passed_count = total_tracked - len(failed_steps)
    print(f"\n{build_banner(passed_count, total_tracked, failed_steps, elapsed)}")


if __name__ == "__main__":
    main()
