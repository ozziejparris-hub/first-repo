#!/usr/bin/env python3
"""
scripts/fetch_relevance_slugs.py

Fetch market.slug / event.slug / event.title from Gamma for the pre-filter
RESIDUAL markets, into a dedicated staging table.  Stage 1b of the geo/elections
relevance classifier cascade.

Design : brain/decisions/2026-08-31-relevance-classifier-design.md (e601648)
         §1.1 (inputs / coverage), §1.3 (LLM stage inputs), §2.5 (keyset cursor)
Pre-filter : monitoring/relevance_prefilter.py (first-repo cb9ee93)
Record : brain/decisions/2026-08-31-slug-fetch.md

WRITES ONLY to the new table `relevance_slug_staging`.  Touches NOTHING existing:
no markets, no trades, no category, no category_source, no
category_classification_log.

Population:
  --population swept   : category='Unknown' AND resolution_evidence_source='clob'
                         (the 26,506 swept residual — this run)
  --population unswept : category='Unknown' AND (resolved=0 OR resolved IS NULL)
                         (the 43,837 unswept residual — a SEPARATE run)

Iteration: a stable **keyset cursor on market_id** (immutable unique PK), never
LIMIT/OFFSET — the confirmed step-over pathology
(2026-08-30-category-classifier-investigation.md).  The residual (market_id, title)
list is materialised once at start from a read-only connection; the cursor is the
largest market_id staged so far, persisted in an atomic (temp+os.replace)
checkpoint after every batch.  Resume also skips any market_id already in the
staging table, so a re-run is idempotent regardless of checkpoint freshness.

Terminal marker + Telegram on COMPLETE / ABORTED / MAINTENANCE-STOPPED /
EXCEPTION via data/characterizations/sweep_common/sweep_terminal_signal.py
(first-repo 72e7337).  Run with `python3 -u` and source ~/.env_trading with
`set -a` so the Telegram credentials reach the process (gap fixed 2026-08-25).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "data" / "characterizations" / "sweep_common"))

from monitoring.relevance_prefilter import prefilter          # noqa: E402
import sweep_terminal_signal as sts                            # noqa: E402

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"
GAMMA_URL = "https://gamma-api.polymarket.com/markets"

POPULATIONS = {
    "swept":
        "category = 'Unknown' AND resolution_evidence_source = 'clob' "
        "AND title IS NOT NULL",
    "unswept":
        "category = 'Unknown' AND (resolved = 0 OR resolved IS NULL) "
        "AND title IS NOT NULL",
}

# Empirically confirmed this session: Gamma /markets accepts <= 100 condition_ids
# (n=120 -> HTTP 422 "expected array length <= 100"); n=100 -> HTTP 200 in
# ~3.1 s.  The design's "~12" was conservative.
BATCH_SIZE = 100
SLEEP_BETWEEN = 1.5          # s; batch wall-time target ~5 s (3 s req + sleep + write)
BASELINE_REQ_S = 3.1        # measured this session at n=100, ONE Gamma call
# unswept issues two sequential calls per batch (closed=false, closed=true;
# 2026-09-01-slug-fetch-unswept.md "Part 2/3" -- no single `closed` value
# returns both an open and a closed market, confirmed empirically) so its
# pacing baseline is the paired duration, not the single-call one.
PAIR_BASELINE_REQ_S = 2 * BASELINE_REQ_S   # 6.2s
PACING_ABORT_MULT = 3.0     # abort if req time > 3x baseline, sustained 2 batches
                             # swept threshold: 3.0 x 3.1s = 9.3s (unchanged)
                             # unswept threshold: 3.0 x 6.2s = 18.6s (paired)
NOT_FOUND_ABORT_RATE = 0.10 # abort if not_found rate > 10% once n >= 100
MAINT_STOP_MARGIN_MIN = 30  # stop cleanly if within 30 min of 03:00 UTC
HTTP_TIMEOUT = 45

STAGING_DDL = """
CREATE TABLE IF NOT EXISTS relevance_slug_staging (
    market_id     TEXT PRIMARY KEY,   -- Gamma conditionId; PK -> idempotent re-run
    outcome       TEXT NOT NULL,      -- 'found' | 'not_found' | 'no_slug' | 'error'
    market_slug   TEXT,               -- Gamma market.slug
    event_slug    TEXT,               -- Gamma events[0].slug  (the design's signal)
    event_title   TEXT,               -- Gamma events[0].title
    n_events      INTEGER,            -- len(events[]); 0 = no parent event
    gamma_closed  INTEGER,            -- Gamma market.closed flag (0/1/NULL)
    http_status   INTEGER,            -- HTTP status of the batch request
    run_id        TEXT NOT NULL,      -- this fetch run
    fetched_at    TEXT NOT NULL       -- ISO8601 UTC
);
"""


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def next_0300_utc(now: datetime) -> datetime:
    t = now.replace(hour=3, minute=0, second=0, microsecond=0)
    return t + timedelta(days=1) if t <= now else t


def load_residual(where: str) -> list[tuple[str, str]]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f"SELECT market_id, title FROM markets WHERE {where}"
        ).fetchall()
    finally:
        conn.close()
    res = [(mid, t) for mid, t in rows if prefilter(t) == "RESIDUAL"]
    res.sort(key=lambda r: r[0])           # keyset order on the immutable PK
    return res


def already_staged(conn: sqlite3.Connection) -> set[str]:
    """market_ids with a DEFINITIVE outcome already recorded. 'error' rows are
    NOT included, so a transient batch failure is retried on the next run."""
    return {r[0] for r in conn.execute(
        "SELECT market_id FROM relevance_slug_staging WHERE outcome != 'error'")}


def write_checkpoint(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def gamma_batch(cond_ids: list[str], closed: str = "true") -> tuple[int, dict]:
    """Return (http_status, {conditionId: market_dict}).  http_status 0 on a
    non-HTTP failure (URLError/timeout/parse).

    `closed` defaults to "true" so a call site that passes nothing (the only
    call site as of this docstring being written -- the swept path) produces
    the byte-identical query this function always has. Gamma's `closed` param
    is a strict binary filter, established empirically
    (2026-09-01-slug-fetch-unswept.md "Part 2"): closed=true returns only
    closed markets, closed=false returns only open markets, and omitting it
    behaves like closed=false -- there is no "both" value. The unswept path
    calls this twice (closed="false" then closed="true") and merges."""
    q = [("closed", closed), ("limit", "500")] + [("condition_ids", c) for c in cond_ids]
    url = GAMMA_URL + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "relevance-slug-fetch/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            status = r.getcode()
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:                          # noqa: BLE001
        log(f"  batch request failed (non-HTTP): {type(e).__name__}: {e}")
        return 0, {}
    return status, {m.get("conditionId"): m for m in data if isinstance(m, dict)}


def classify_row(mid: str, m: dict | None, status: int, run_id: str) -> tuple:
    now = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
    if m is None:
        # HTTP 200 but no row for this id -> genuinely not_found;
        # any non-200 status (or 0 = non-HTTP failure) -> the batch errored.
        outcome = "not_found" if status == 200 else "error"
        return (mid, outcome, None, None, None, None, None, status, run_id, now)
    evs = m.get("events") or []
    e = evs[0] if evs else {}
    mslug = m.get("slug") or None
    eslug = (e.get("slug") or None)
    etitle = (e.get("title") or None)
    closed = m.get("closed")
    closed_i = 1 if closed is True else (0 if closed is False else None)
    outcome = "found" if eslug else "no_slug"
    return (mid, outcome, mslug, eslug, etitle, len(evs), closed_i, status, run_id, now)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--population", choices=list(POPULATIONS), default="swept")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--marker", default=None)
    args = ap.parse_args()

    pop = args.population
    run_id = args.run_id or f"slugfetch-{pop}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    ckpt_path = Path(args.checkpoint or REPO_ROOT / "data" / "checkpoints"
                     / f"slug_fetch_{pop}_checkpoint.json")
    marker_path = Path(args.marker or REPO_ROOT / "data" / "checkpoints"
                       / f"slug_fetch_{pop}_terminal.json")

    log(f"=== relevance slug fetch START  population={pop}  run_id={run_id} ===")
    log(f"checkpoint={ckpt_path}")
    log(f"marker={marker_path}")

    residual = load_residual(POPULATIONS[pop])
    n_total = len(residual)
    n_batches = -(-n_total // args.batch_size)
    log(f"residual markets: {n_total:,}  ->  {n_batches:,} batches of {args.batch_size}")

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.isolation_level = None            # explicit BEGIN/COMMIT, no implicit txns
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(STAGING_DDL)

    staged = already_staged(conn)
    if staged:
        log(f"resume: {len(staged):,} market_ids already in staging — skipping them")
    work = [(mid, t) for mid, t in residual if mid not in staged]
    log(f"to fetch this run: {len(work):,}")

    now = datetime.now(timezone.utc)
    stop_at = next_0300_utc(now) - timedelta(minutes=MAINT_STOP_MARGIN_MIN)
    log(f"maintenance stop boundary: {stop_at:%Y-%m-%dT%H:%M:%SZ} "
        f"(30 min before {next_0300_utc(now):%H:%M} UTC)")

    tally = Counter()
    batches_done = 0
    processed = 0
    slow_streak = 0
    aborted = False
    abort_reason = None
    maint_stopped = False
    last_mid = max(staged) if staged else ""

    try:
        for i in range(0, len(work), args.batch_size):
            if datetime.now(timezone.utc) >= stop_at:
                maint_stopped = True
                abort_reason = "within 30 min of 03:00 UTC backup window"
                log(f"MAINTENANCE STOP at batch boundary: {abort_reason}")
                break

            chunk = work[i:i + args.batch_size]
            cond_ids = [mid for mid, _ in chunk]

            if pop == "unswept":
                # Two passes, merged: `closed` has no "both" value (established
                # 2026-09-01-slug-fetch-unswept.md "Part 2"), and unswept can
                # legitimately contain markets Gamma has already closed while
                # this DB's `resolved` flag hasn't caught up (O-36 late-bias).
                # A mid missing from BOTH passes is a genuine not_found.
                t0 = time.time()
                status_f, by_cid_f = gamma_batch(cond_ids, closed="false")
                status_t, by_cid_t = gamma_batch(cond_ids, closed="true")
                req_s = time.time() - t0
                if 429 in (status_f, status_t):
                    status, by_cid = 429, {}
                else:
                    by_cid = {**by_cid_f, **by_cid_t}   # disjoint: a market is
                                                         # closed XOR open, never both
                    status = status_f if status_f == 200 else status_t
            else:
                t0 = time.time()
                status, by_cid = gamma_batch(cond_ids)
                req_s = time.time() - t0

            # --- abort: rate limit ---
            if status == 429:
                aborted = True
                abort_reason = f"HTTP 429 (rate limit) on batch {batches_done + 1}"
                log(f"ABORT: {abort_reason} — not retrying")
                break

            rows = [classify_row(mid, by_cid.get(mid), status, run_id) for mid, _ in chunk]
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT OR REPLACE INTO relevance_slug_staging "
                "(market_id,outcome,market_slug,event_slug,event_title,n_events,"
                " gamma_closed,http_status,run_id,fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.execute("COMMIT")

            for r in rows:
                tally[r[1]] += 1
            batches_done += 1
            processed += len(rows)
            last_mid = max(last_mid, max(mid for mid, _ in chunk))

            write_checkpoint(ckpt_path, {
                "run_id": run_id, "population": pop,
                "last_market_id": last_mid,
                "batches_completed": batches_done, "n_batches": n_batches,
                "cumulative_processed": len(staged) + processed,
                "cumulative_tally": dict(tally),
                "updated_at_utc": f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
            })

            # --- abort: not_found rate ---
            seen = tally["found"] + tally["no_slug"] + tally["not_found"]
            if seen >= 100:
                nf_rate = tally["not_found"] / seen
                if nf_rate > NOT_FOUND_ABORT_RATE:
                    aborted = True
                    abort_reason = (f"not_found rate {nf_rate:.1%} > "
                                    f"{NOT_FOUND_ABORT_RATE:.0%} at n={seen} "
                                    "— identifier assumption likely wrong")
                    log(f"ABORT: {abort_reason}")
                    break

            # --- abort: sustained pacing degradation ---
            # unswept measures a PAIR of sequential calls against a paired
            # baseline (2x single-call); swept is unchanged.
            pace_baseline = PAIR_BASELINE_REQ_S if pop == "unswept" else BASELINE_REQ_S
            if req_s > PACING_ABORT_MULT * pace_baseline:
                slow_streak += 1
                log(f"  slow batch: {req_s:.1f}s (> {PACING_ABORT_MULT}x{pace_baseline}s) "
                    f"streak={slow_streak}")
                if slow_streak >= 2:
                    aborted = True
                    abort_reason = (f"pacing degraded > {PACING_ABORT_MULT}x baseline "
                                    f"for {slow_streak} consecutive batches")
                    log(f"ABORT: {abort_reason}")
                    break
            else:
                slow_streak = 0

            if batches_done % 10 == 0 or batches_done == 1:
                log(f"  batch {batches_done}/{n_batches}  req={req_s:.1f}s  "
                    f"tally={dict(tally)}")

            time.sleep(SLEEP_BETWEEN)

    except Exception as exc:                          # noqa: BLE001
        sts.write_terminal_marker(
            marker_path, status="EXCEPTION",
            batches_completed=batches_done, n_batches=n_batches,
            cumulative_processed=len(staged) + processed,
            cumulative_tally=dict(tally),
            reason=f"{type(exc).__name__}: {exc}")
        sts.send_telegram_terminal(
            f"[SLUG-FETCH] {pop} CRASHED after {batches_done}/{n_batches} batches: {exc}")
        conn.close()
        raise

    conn.close()

    if maint_stopped:
        status_str = "MAINTENANCE-STOPPED"
    elif aborted:
        status_str = "ABORTED"
    elif batches_done == len(range(0, len(work), args.batch_size)):
        status_str = "COMPLETE"
    else:
        status_str = "STOPPED (incomplete)"

    total_in_staging = len(staged) + processed
    sts.write_terminal_marker(
        marker_path, status=status_str,
        batches_completed=batches_done, n_batches=n_batches,
        cumulative_processed=total_in_staging,
        cumulative_tally=dict(tally),
        reason=abort_reason)
    sent = sts.send_telegram_terminal(
        f"[SLUG-FETCH] {pop} {status_str}: {batches_done}/{n_batches} batches, "
        f"{total_in_staging:,}/{n_total:,} staged. tally={dict(tally)}"
        + (f" reason={abort_reason}" if abort_reason else ""))

    log(f"=== END  status={status_str}  batches={batches_done}/{n_batches}  "
        f"staged_total={total_in_staging:,}/{n_total:,}  tally={dict(tally)}  "
        f"telegram_sent={sent} ===")
    return 0 if status_str in ("COMPLETE", "MAINTENANCE-STOPPED") else 2


if __name__ == "__main__":
    sys.exit(main())
