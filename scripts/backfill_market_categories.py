#!/usr/bin/env python3
"""
Backfill market categories for Unknown-category markets using Ollama classification.

Classifies political/geopolitical markets via Qwen3-Coder 30B and updates
both markets.category and trades.market_category. Resumable via state file.
"""

import argparse
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"
STATE_FILE = "/home/parison/projects/first-repo/data/category_backfill_state.json"
LOG_FILE = "/home/parison/projects/first-repo/logs/category_backfill.log"

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3-coder:30b-a3b-q4_K_M"
OLLAMA_TIMEOUT = 120

DEFAULT_BATCH_SIZE = 20
COMMIT_EVERY_N = 100
SLEEP_BETWEEN_BATCHES = 0.5

KEYWORD_FILTER = [
    "election", "president", "congress", "senate", "war", "russia", "ukraine",
    "china", "iran", "nato", "trump", "biden", "government", "shutdown",
    "sanction", "ceasefire", "nuclear", "military", "parliament", "minister",
    "treaty", "referendum", "diplomatic", "invasion", "conflict", "zelensky",
    "putin", "xi jinping", "macron", "scholz", "mayor", "governor", "ballot",
    "tariff", "foreign policy", "regime", "coup", "protest", "revolution",
]

CLASSIFY_PROMPT = """\
Classify each market title as Geopolitics, Elections, or Unknown.

Geopolitics = war, foreign policy, international relations, sanctions, treaties, military conflict, diplomatic relations, nuclear, terrorism, international organisations, government policy
Elections = voting, candidates, electoral outcomes, primaries, referendums, polling, ballot, political campaigns, party leadership
Unknown = financial markets, sports, entertainment, crypto, personal celebrity, business earnings, weather, technology products, science

IMPORTANT: Be conservative. If unsure, classify as Unknown.

Classify these titles:
{numbered_list}

Reply with ONLY a JSON array, no other text, no markdown:
[{{"id": 1, "category": "Geopolitics/Elections/Unknown", "confidence": "HIGH/LOW"}}]
"""


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("category_backfill")
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    fh = logging.FileHandler(LOG_FILE, mode="a")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


def load_state() -> dict:
    """
    Load pagination/progress state.

    last_seen_market_id (str | None) replaces the old last_processed_offset
    (int). OFFSET-based pagination drifted permanently on any batch with a
    mix of classified/skipped rows, because the underlying WHERE
    category='Unknown' result set shrinks as rows get classified within a
    run -- a fixed position number stops meaning the same row. market_id is
    a stable, never-reused, never-renumbered primary key, so a keyset
    cursor (WHERE market_id > last_seen_market_id) cannot drift the same
    way: it advances only past rows that were actually fetched, regardless
    of how many other rows enter or leave the matching set around them.

    A pre-existing state file from before this fix will have
    last_processed_offset but no last_seen_market_id -- that old field is
    intentionally dropped (not migrated: it no longer corresponds to
    anything meaningful under keyset pagination) and last_seen_market_id
    defaults to None, restarting the scan from the true beginning of the
    current category='Unknown' set. This is deliberate, not a fallback of
    convenience: it is the only way to reach the rows the old bug had
    already made permanently unreachable.
    """
    path = Path(STATE_FILE)
    if path.exists():
        try:
            with open(path) as f:
                raw = json.load(f)
            return {
                "last_seen_market_id": raw.get("last_seen_market_id"),
                "total_classified": raw.get("total_classified", 0),
                "total_skipped": raw.get("total_skipped", 0),
                "errors": raw.get("errors", 0),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_seen_market_id": None, "total_classified": 0, "total_skipped": 0, "errors": 0}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def build_keyword_where() -> str:
    conditions = " OR ".join(f"LOWER(title) LIKE '%{kw}%'" for kw in KEYWORD_FILTER)
    return f"({conditions})"


def fetch_batch(conn: sqlite3.Connection, after_market_id: str | None, batch_size: int) -> list[dict]:
    """
    Keyset pagination: fetch the next batch of Unknown markets with
    market_id strictly greater than after_market_id (None means start from
    the beginning). market_id is the table's primary key -- a stable
    anchor that isn't affected by rows entering or leaving the
    category='Unknown' result set, unlike an OFFSET position.
    """
    keyword_clause = build_keyword_where()
    if after_market_id is None:
        sql = f"""
            SELECT market_id, title
            FROM markets
            WHERE category = 'Unknown'
              AND title IS NOT NULL
              AND {keyword_clause}
            ORDER BY market_id
            LIMIT ?
        """
        rows = conn.execute(sql, (batch_size,)).fetchall()
    else:
        sql = f"""
            SELECT market_id, title
            FROM markets
            WHERE category = 'Unknown'
              AND title IS NOT NULL
              AND market_id > ?
              AND {keyword_clause}
            ORDER BY market_id
            LIMIT ?
        """
        rows = conn.execute(sql, (after_market_id, batch_size)).fetchall()
    return [{"market_id": row["market_id"], "title": row["title"]} for row in rows]


def call_ollama(titles: list[str], logger: logging.Logger) -> list[dict] | None:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = CLASSIFY_PROMPT.format(numbered_list=numbered)

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()

    req = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
            raw_text = result.get("response", "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        logger.error(f"Ollama request failed: {e}")
        return None

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        lines = raw_text.splitlines()
        raw_text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        classifications = json.loads(raw_text)
        if not isinstance(classifications, list):
            raise ValueError("Expected JSON array")
        return classifications
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse Ollama response as JSON: {e} | raw={raw_text[:200]}")
        return None


def apply_classifications(
    conn: sqlite3.Connection,
    markets: list[dict],
    classifications: list[dict],
    dry_run: bool,
    logger: logging.Logger,
) -> tuple[int, int]:
    """Returns (classified_count, skipped_count)."""
    classified = 0
    skipped = 0

    id_to_market = {i + 1: m for i, m in enumerate(markets)}

    for item in classifications:
        idx = item.get("id")
        category = item.get("category", "Unknown")
        confidence = item.get("confidence", "LOW")

        market = id_to_market.get(idx)
        if market is None:
            logger.warning(f"Ollama returned unknown id={idx}, skipping")
            skipped += 1
            continue

        if confidence != "HIGH" or category not in ("Geopolitics", "Elections"):
            logger.debug(
                f"SKIP market_id={market['market_id']} title={market['title'][:60]!r} "
                f"category={category} confidence={confidence}"
            )
            skipped += 1
            continue

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}CLASSIFY market_id={market['market_id']} "
            f"-> {category} (HIGH) title={market['title'][:60]!r}"
        )

        if not dry_run:
            try:
                conn.execute(
                    "UPDATE markets SET category = ? WHERE market_id = ?",
                    (category, market["market_id"]),
                )
                conn.execute(
                    "UPDATE trades SET market_category = ? WHERE market_id = ?",
                    (category, market["market_id"]),
                )
            except sqlite3.Error as e:
                logger.error(f"DB write failed for market_id={market['market_id']}: {e}")
                conn.rollback()
                skipped += 1
                continue

        classified += 1

    return classified, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Unknown market categories via Ollama")
    parser.add_argument("--dry-run", action="store_true", help="Classify without writing to DB")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N markets")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, dest="batch_size")
    args = parser.parse_args()

    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging()
    logger.info(f"=== category_backfill starting {'(DRY-RUN) ' if args.dry_run else ''}===")

    state = load_state()
    logger.info(
        f"Resuming from last_seen_market_id={state['last_seen_market_id']!r} "
        f"total_classified={state['total_classified']} "
        f"total_skipped={state['total_skipped']} "
        f"errors={state['errors']}"
    )

    conn = get_db_connection()
    batch_num = 0
    markets_since_commit = 0
    run_classified = 0
    run_skipped = 0

    try:
        while True:
            cursor = state["last_seen_market_id"]

            if args.limit is not None and run_classified + run_skipped >= args.limit:
                logger.info(f"Reached --limit {args.limit} for this run, stopping.")
                break

            markets = fetch_batch(conn, cursor, args.batch_size)
            if not markets:
                # Reached the current end of the matching set. Wrap the
                # cursor back to the beginning rather than leaving it
                # pinned here forever: new markets keep entering
                # category='Unknown' daily, and since market_id is a
                # content hash (not chronological), a newly-added market
                # can sort anywhere -- including "behind" this cursor.
                # Without a wrap, such a market would never be reachable
                # again under keyset pagination once the cursor passes it.
                if state["last_seen_market_id"] is not None:
                    logger.info(
                        "No more Unknown markets matching keyword filter past the "
                        "current cursor -- wrapping to the beginning for next run."
                    )
                    state["last_seen_market_id"] = None
                    save_state(state)
                else:
                    logger.info("No Unknown markets matching keyword filter. Done.")
                break

            # Advance the cursor to the last (highest market_id, since the
            # query is ORDER BY market_id ASC) row in THIS batch, regardless
            # of what happens to it below (classified, skipped, or an
            # error) -- this is what makes the cursor immune to the
            # shrinking-set drift: it tracks a value that was actually
            # fetched, never a position that other rows can shift under it.
            new_cursor = markets[-1]["market_id"]

            batch_num += 1
            titles = [m["title"] for m in markets]

            classifications = call_ollama(titles, logger)
            if classifications is None:
                state["errors"] += 1
                state["last_seen_market_id"] = new_cursor
                save_state(state)
                logger.warning(f"[BATCH {batch_num}] Ollama call failed, skipping batch of {len(markets)}")
                time.sleep(SLEEP_BETWEEN_BATCHES)
                continue

            if not args.dry_run:
                # Begin transaction for this batch
                conn.execute("BEGIN")

            classified, skipped = apply_classifications(conn, markets, classifications, args.dry_run, logger)

            if not args.dry_run:
                try:
                    conn.execute("COMMIT")
                except sqlite3.Error as e:
                    logger.error(f"Commit failed for batch {batch_num}: {e}")
                    conn.execute("ROLLBACK")
                    state["errors"] += 1
                    state["last_seen_market_id"] = new_cursor
                    save_state(state)
                    time.sleep(SLEEP_BETWEEN_BATCHES)
                    continue

            state["total_classified"] += classified
            state["total_skipped"] += skipped
            state["last_seen_market_id"] = new_cursor
            run_classified += classified
            run_skipped += skipped
            markets_since_commit += len(markets)

            save_state(state)

            print(
                f"[BATCH {batch_num}] last_seen_market_id={state['last_seen_market_id']} "
                f"classified={state['total_classified']} "
                f"skipped={state['total_skipped']} "
                f"errors={state['errors']}"
            )

            # Periodic explicit DB checkpoint every COMMIT_EVERY_N markets
            if markets_since_commit >= COMMIT_EVERY_N and not args.dry_run:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                markets_since_commit = 0

            time.sleep(SLEEP_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        logger.info("Interrupted by user. State saved; safe to resume.")
    finally:
        conn.close()

    logger.info(
        f"=== category_backfill finished === "
        f"classified={state['total_classified']} "
        f"skipped={state['total_skipped']} "
        f"errors={state['errors']}"
    )


if __name__ == "__main__":
    main()
