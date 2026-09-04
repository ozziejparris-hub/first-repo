#!/usr/bin/env python3
"""
scripts/run_relevance_gate.py

The formal validation gate for the geo/elections relevance classifier
(design: brain/decisions/2026-08-31-relevance-classifier-design.md, e601648,
§3.8-3.11). Runs classify_batch() over the recall corpus (markets already
category IN ('Geopolitics','Elections')) and/or the precision set
(gate-sets-2026-09-01/labels.csv, 500 hand-labelled rows), WITHOUT writing
markets.category / category_source / category_classification_log.

This script does NOT modify monitoring/relevance_classifier.py,
monitoring/relevance_classifier_prompt.py, or monitoring/relevance_prefilter.py
-- it only imports and calls classify_batch(). It also does not write to
relevance_slug_staging (that table is scoped to the classifier-build's
residual population, a different population than either gate corpus here);
slugs fetched by this script go to this run's own output files only.

Neither corpus (the recall corpus, nor labels.csv) fully overlaps with
relevance_slug_staging, since that table was populated only for the
Unknown-category pre-filter RESIDUAL population -- a different population
from "already classified Geopolitics/Elections" (recall) or the hand-drawn
gate sets (precision, mostly EXCLUDE-bucket). So this script does its own
live Gamma fetch (two-pass closed=false/closed=true merge, same method
established in 2026-09-01-slug-fetch-unswept.md, since both corpora here
have mixed resolved status) for whichever market_ids arrive without a
market_slug already on file.

Output: JSONL files under data/characterizations/relevance_gate_2026-09-03/,
one line per market, resumable (skips market_ids already written) so a
crash mid-run does not require re-classifying completed markets -- this is
NOT "re-running after seeing results" (§ task constraints), it is crash
recovery within one continuous, not-yet-observed run.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monitoring.relevance_classifier import classify_batch  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "polymarket_tracker.db"
GATE_SETS_DIR = Path.home() / "trading-swarm" / "brain" / "decisions" / "gate-sets-2026-09-01"
OUT_DIR = REPO_ROOT / "data" / "characterizations" / "relevance_gate_2026-09-03"
GAMMA_URL = "https://gamma-api.polymarket.com/markets"
GAMMA_BATCH_SIZE = 100
GAMMA_SLEEP = 1.5
HTTP_TIMEOUT = 45
CLASSIFY_BATCH_SIZE = 20  # matches monitoring/relevance_classifier.DEFAULT_BATCH_SIZE

# design §3.8: gamma_backfill_* variants folded together; background_backfill
# and gap_recovery ("too small... folded into nearest", design's own words,
# which stratum is "nearest" left unspecified there) folded into
# historical_backfill here -- both are backfill-shaped origins, not live
# ingest. This choice is this script's own judgment call, stated here so it
# is not read as verified design text.
STRATUM_MAP = {
    "live_monitoring": "live_monitoring",
    "historical_backfill": "historical_backfill",
    "background_backfill": "historical_backfill",
}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def stratum_for(data_source: str) -> str:
    if data_source in STRATUM_MAP:
        return STRATUM_MAP[data_source]
    if data_source and data_source.startswith("gamma_backfill"):
        return "gamma_backfill"
    if data_source and data_source.startswith("gap_recovery"):
        return "historical_backfill"
    return f"other:{data_source}"


def gamma_batch(cond_ids: list[str], closed: str) -> tuple[int, dict]:
    """Same shape/semantics as scripts/fetch_relevance_slugs.py::gamma_batch
    (not imported, to keep this script's dependency footprint self-contained;
    logic is intentionally identical, established there and in
    2026-09-01-slug-fetch-unswept.md: closed is a strict binary filter, no
    'both' value)."""
    q = [("closed", closed), ("limit", "500")] + [("condition_ids", c) for c in cond_ids]
    url = GAMMA_URL + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "relevance-gate/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            status = r.getcode()
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:  # noqa: BLE001
        log(f"  gamma batch request failed (non-HTTP): {type(e).__name__}: {e}")
        return 0, {}
    return status, {m.get("conditionId"): m for m in data if isinstance(m, dict)}


def fetch_slugs_for(market_ids: list[str]) -> dict[str, dict]:
    """Two-pass (closed=false, closed=true) merge over market_ids, batched at
    GAMMA_BATCH_SIZE. Returns {market_id: {market_slug, event_slug,
    event_title, found: bool}}. Ids that are not real conditionIds (no
    Gamma match either pass) come back found=False with all fields None --
    the classifier then runs title-only for them, same as any genuine
    not_found case."""
    result: dict[str, dict] = {mid: {"market_slug": None, "event_slug": None,
                                      "event_title": None, "found": False}
                                for mid in market_ids}
    if not market_ids:
        return result

    n_batches = -(-len(market_ids) // GAMMA_BATCH_SIZE)
    log(f"gamma slug fetch: {len(market_ids):,} ids -> {n_batches} batches x2 passes")
    for bi in range(0, len(market_ids), GAMMA_BATCH_SIZE):
        chunk = market_ids[bi:bi + GAMMA_BATCH_SIZE]
        merged: dict[str, dict] = {}
        for closed_val in ("false", "true"):
            status, by_cid = gamma_batch(chunk, closed=closed_val)
            if status != 200:
                log(f"  batch {bi // GAMMA_BATCH_SIZE + 1}/{n_batches} closed={closed_val} "
                    f"HTTP {status} -- treated as no matches this pass")
            merged.update(by_cid)  # closed=true pass wins on overlap (shouldn't overlap)
            time.sleep(GAMMA_SLEEP)
        for mid in chunk:
            m = merged.get(mid)
            if m is None:
                continue
            evs = m.get("events") or []
            e = evs[0] if evs else {}
            result[mid] = {
                "market_slug": m.get("slug") or None,
                "event_slug": e.get("slug") or None,
                "event_title": e.get("title") or None,
                "found": True,
            }
        if (bi // GAMMA_BATCH_SIZE + 1) % 10 == 0 or bi + GAMMA_BATCH_SIZE >= len(market_ids):
            log(f"  gamma progress: {min(bi + GAMMA_BATCH_SIZE, len(market_ids)):,}/{len(market_ids):,}")
    return result


def load_recall_corpus() -> list[dict]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT market_id, title, category, data_source FROM markets "
            "WHERE category IN ('Geopolitics','Elections') "
            "AND title IS NOT NULL ORDER BY market_id"
        ).fetchall()
    finally:
        conn.close()
    corpus = []
    for market_id, title, category, data_source in rows:
        corpus.append({
            "market_id": market_id,
            "title": title,
            "stored_category": category,
            "data_source": data_source,
            "stratum": stratum_for(data_source),
            "market_slug": None,
            "event_slug": None,
            "event_title": None,
        })
    return corpus


def load_precision_set() -> list[dict]:
    rows = []
    with open(GATE_SETS_DIR / "labels.csv") as f:
        for r in csv.DictReader(f):
            rows.append({
                "market_id": r["market_id"],
                "title": r["title"],
                "set": r["set"],
                "hand_label": r["label"],
                "borderline": r.get("borderline", "0"),
                "prefilter": r.get("prefilter"),
                "market_slug": r.get("market_slug") or None,
                "event_slug": r.get("event_slug") or None,
                "event_title": r.get("event_title") or None,
            })
    return rows


def fill_missing_slugs(rows: list[dict]) -> None:
    missing_ids = [r["market_id"] for r in rows if not r.get("market_slug")]
    if not missing_ids:
        log("no rows missing slugs -- skipping gamma fetch")
        return
    log(f"{len(missing_ids):,}/{len(rows):,} rows missing staged slugs -- fetching live")
    fetched = fetch_slugs_for(missing_ids)
    n_found = sum(1 for v in fetched.values() if v["found"])
    log(f"gamma fetch done: {n_found:,}/{len(missing_ids):,} found "
        f"({len(missing_ids) - n_found:,} not_found -- title-only for those)")
    for r in rows:
        if not r.get("market_slug") and r["market_id"] in fetched:
            f = fetched[r["market_id"]]
            r["market_slug"] = f["market_slug"]
            r["event_slug"] = f["event_slug"]
            r["event_title"] = f["event_title"]


def already_done(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    done = set()
    with open(out_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            done.add(json.loads(line)["market_id"])
    return done


def run_classification(rows: list[dict], out_path: Path, dry_run: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = already_done(out_path)
    if done:
        log(f"resuming: {len(done):,}/{len(rows):,} already classified in {out_path.name}")
    todo = [r for r in rows if r["market_id"] not in done]
    log(f"to classify this run: {len(todo):,}")

    n_batches = -(-len(todo) // CLASSIFY_BATCH_SIZE)
    t_start = time.monotonic()
    with open(out_path, "a") as out_f:
        for bi in range(0, len(todo), CLASSIFY_BATCH_SIZE):
            chunk = todo[bi:bi + CLASSIFY_BATCH_SIZE]
            batch_num = bi // CLASSIFY_BATCH_SIZE + 1
            t0 = time.monotonic()

            if dry_run:
                cls_results = [
                    type("R", (), {"market_id": r["market_id"], "category": "DRY_RUN",
                                   "confidence": None, "raw_response": "DRY_RUN"})()
                    for r in chunk
                ]
            else:
                cls_results = classify_batch(
                    [{"market_id": r["market_id"], "title": r["title"],
                      "market_slug": r["market_slug"], "event_slug": r["event_slug"],
                      "event_title": r["event_title"]} for r in chunk]
                )

            by_id = {r.market_id: r for r in cls_results}
            for r in chunk:
                cr = by_id.get(r["market_id"])
                record = dict(r)
                record["classifier_category"] = cr.category if cr else None
                record["classifier_confidence"] = cr.confidence if cr else None
                record["classifier_raw"] = cr.raw_response if cr else "ERROR: no result returned"
                out_f.write(json.dumps(record) + "\n")
            out_f.flush()

            elapsed = time.monotonic() - t0
            total_elapsed = time.monotonic() - t_start
            done_count = bi + len(chunk)
            rate = done_count / total_elapsed if total_elapsed > 0 else 0
            eta_s = (len(todo) - done_count) / rate if rate > 0 else float("nan")
            log(f"batch {batch_num}/{n_batches} ({len(chunk)} markets) in {elapsed:.1f}s -- "
                f"{done_count:,}/{len(todo):,} done, ETA {eta_s/60:.1f} min")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["recall", "precision"], required=True)
    ap.add_argument("--dry-run", action="store_true",
                     help="fetch slugs and build the pipeline but skip the actual "
                          "Ollama call -- for validating mechanics only, never "
                          "counts toward the gate")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.stage == "recall":
        log("=== RECALL RUN: loading corpus (category IN Geopolitics/Elections) ===")
        rows = load_recall_corpus()
        log(f"corpus size: {len(rows):,}")
        fill_missing_slugs(rows)
        out_path = OUT_DIR / ("recall_results.dryrun.jsonl" if args.dry_run else "recall_results.jsonl")
        run_classification(rows, out_path, args.dry_run)
    else:
        log("=== PRECISION RUN: loading gate-sets-2026-09-01/labels.csv ===")
        rows = load_precision_set()
        log(f"precision set size: {len(rows):,}")
        fill_missing_slugs(rows)
        out_path = OUT_DIR / ("precision_results.dryrun.jsonl" if args.dry_run else "precision_results.jsonl")
        run_classification(rows, out_path, args.dry_run)

    log("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
