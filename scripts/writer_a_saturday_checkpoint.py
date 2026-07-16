#!/usr/bin/env python3
"""
scripts/writer_a_saturday_checkpoint.py

One-command pre-Sunday validation of Writer A (ELO arc Stage 3) with a
MINIMAL shadow-forecast-to-run gap. The 2026-07-15 dry-run's forecast was
up to ~46h stale (elo_shadow computed 07-13/14, scratch copy taken 07-15
evening), which is what caused most of its 279 mismatches -- all traced to
benign recompute drift, not a formula bug (see
~/trading-swarm/brain/decisions/2026-06-29-overhang-ledger.md, O-7,
"STAGE 3 DRY-RUN VALIDATED"). This wrapper closes that gap by refreshing
the forecast and taking the scratch copy back-to-back, immediately before
the dry-run starts, so the only remaining drift window is the dry-run's own
runtime (~107 min), not days.

Steps:
  1. Refresh elo_shadow (scripts/compute_elo_shadow.py) against production.
     Fast (~minutes) -- reads live pnl_cache and STORED base/behavioral
     components, does not re-run the full base-ELO pass.
  2. Immediately take a WAL-safe scratch copy of production (SQLite Online
     Backup API, same approach as scripts/backup_database.py -- safe against
     a live WAL-mode writer, unlike a raw file copy). The scratch copy
     carries the just-refreshed elo_shadow table alongside current `traders`.
  3. Run scripts/writer_a_dry_run.py against the scratch copy -- the real
     ~107-minute Writer-A pass, writes redirected to the scratch copy only,
     reads still hit live production (read-only) throughout.
  4. Print the match-rate summary (already computed by writer_a_dry_run.py)
     prominently at the end, plus the full log path.

Usage (foreground, ~2h):
    python3 scripts/writer_a_saturday_checkpoint.py

Usage (backgrounded, recommended for Saturday evening):
    nohup python3 scripts/writer_a_saturday_checkpoint.py \\
        > logs/writer_a_checkpoint_$(date -u +%Y%m%d_%H%M%S).log 2>&1 &
    disown

Does NOT delete old scratch copies -- see the O-3/Stage-5 cleanup note in
the ledger for the 07-15 file; disk has ample headroom (1.4T free as of
2026-07-16) for another ~14GB copy, but old ones should be removed once
superseded (they're multi-GB and serve no purpose after their dry-run's
findings are documented).
"""
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"
SCRATCH_DIR = REPO_ROOT / "data" / "scratch"
LOG_DIR = REPO_ROOT / "logs"


def run_step(label, cmd, log_f):
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    log_f.write(f"\n{'='*70}\n  {label}\n{'='*70}\n")
    log_f.flush()
    start = time.time()
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    out_lines = []
    for line in proc.stdout:
        print(line, end="")
        log_f.write(line)
        out_lines.append(line)
    proc.wait()
    elapsed = time.time() - start
    log_f.flush()
    if proc.returncode != 0:
        print(f"\n[ERROR] {label} failed (exit {proc.returncode}) after {elapsed:.0f}s")
        log_f.write(f"\n[ERROR] {label} failed (exit {proc.returncode}) after {elapsed:.0f}s\n")
        sys.exit(proc.returncode)
    print(f"\n[OK] {label} done in {elapsed:.0f}s")
    log_f.write(f"\n[OK] {label} done in {elapsed:.0f}s\n")
    return out_lines


def take_scratch_copy(scratch_path, log_f):
    print(f"\n{'='*70}\n  SCRATCH COPY (WAL-safe online backup) -> {scratch_path}\n{'='*70}")
    log_f.write(f"\n{'='*70}\n  SCRATCH COPY (WAL-safe online backup) -> {scratch_path}\n{'='*70}\n")
    start = time.time()

    source_conn = sqlite3.connect(str(DB_PATH))
    dest_conn = sqlite3.connect(str(scratch_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    check_conn = sqlite3.connect(str(scratch_path))
    try:
        result = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
    except sqlite3.DatabaseError as e:
        result = str(e)
    finally:
        check_conn.close()

    elapsed = time.time() - start
    if result != "ok":
        msg = f"[ERROR] scratch copy failed integrity check: {result}"
        print(msg)
        log_f.write(msg + "\n")
        scratch_path.unlink(missing_ok=True)
        sys.exit(1)

    size_gb = scratch_path.stat().st_size / (1024 ** 3)
    msg = f"[OK] scratch copy verified ({size_gb:.1f} GB) in {elapsed:.0f}s"
    print(msg)
    log_f.write(msg + "\n")


def main():
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scratch_path = SCRATCH_DIR / f"writer_a_dryrun_{timestamp}.db"
    log_path = LOG_DIR / f"writer_a_checkpoint_{timestamp}.log"

    with open(log_path, "w") as log_f:
        banner = (
            f"Writer-A Saturday checkpoint\n"
            f"Started (UTC): {datetime.now(timezone.utc).isoformat()}\n"
            f"Scratch target: {scratch_path}\n"
        )
        print(banner)
        log_f.write(banner)

        run_step(
            "STEP 1/3 — Refresh elo_shadow forecast (compute_elo_shadow.py)",
            [sys.executable, "scripts/compute_elo_shadow.py"],
            log_f,
        )

        take_scratch_copy(scratch_path, log_f)

        dry_run_output = run_step(
            "STEP 3/3 — Writer-A dry-run vs scratch copy (writer_a_dry_run.py)",
            [sys.executable, "scripts/writer_a_dry_run.py", str(scratch_path)],
            log_f,
        )

    # Pull the match-rate line(s) out for a prominent summary.
    summary_lines = [
        l for l in dry_run_output
        if re.search(r"Compared|Matched|Mismatched|Traders updated|Traders failed", l)
    ]
    print(f"\n{'='*70}\n  SATURDAY CHECKPOINT SUMMARY\n{'='*70}")
    for l in summary_lines:
        print("  " + l.rstrip())
    print(f"\n  Scratch DB : {scratch_path}")
    print(f"  Full log   : {log_path}")
    print(
        "\n  Expectation: with a fresh shadow, match rate should be well above "
        "07-15's 98.95% (the gap that drove most of that run's drift was ~a "
        "day of shadow staleness; this run's gap is only its own ~107min "
        "runtime). If it is NOT clearly higher, treat that as unexpected and "
        "investigate before Sunday's 03:00 UTC real run."
    )


if __name__ == "__main__":
    main()
