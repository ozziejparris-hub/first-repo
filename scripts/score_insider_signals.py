#!/usr/bin/env python3
"""
Score insider_signals against resolved market outcomes.

For each signal:
  - Joins to markets on market_id (the correct join key per integration-contract.md)
  - Sets outcome_correct, information_value, resolved_at, scored_at for resolved markets
  - Flags unresolved signals in markets whose title implies a past deadline (manual review)

Information value formula:
  correct:  IV =  1 - entry_price   (rewards low-price correct calls)
  wrong:    IV = -entry_price        (penalises high-price wrong calls)

Weighted accuracy = sum(IV for correct signals) / total signals
"""

import re
import sqlite3
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"


def _get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn):
    for sql in [
        "ALTER TABLE insider_signals ADD COLUMN outcome_correct BOOLEAN DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN resolved_at TEXT DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN information_value REAL DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN scored_at TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()


def _parse_deadline_from_title(title):
    """Best-effort extraction of a deadline date from a market title."""
    if not title:
        return None
    patterns = [
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2},?\s+\d{4}\b',
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            date_str = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', m.group(0))
            for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue
    return None


def main():
    conn = _get_connection()
    _ensure_columns(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    rows = conn.execute("""
        SELECT
            s.id,
            s.outcome,
            s.entry_price,
            s.market_title,
            m.resolved,
            m.winning_outcome,
            m.resolution_date
        FROM insider_signals s
        LEFT JOIN markets m ON m.market_id = s.market_id
    """).fetchall()

    scored = 0
    correct_count = 0
    wrong_count = 0
    pending_count = 0
    iv_sum_correct = 0.0
    best = None
    worst = None

    for row in rows:
        resolved = row["resolved"] == 1
        wo = row["winning_outcome"]
        if not resolved or not wo or wo in ("", "unknown"):
            pending_count += 1
            continue

        outcome_correct = 1 if row["outcome"] == wo else 0
        ep = row["entry_price"] or 0.0
        information_value = (1.0 - ep) if outcome_correct else (-ep)

        conn.execute("""
            UPDATE insider_signals
               SET outcome_correct   = ?,
                   resolved_at       = ?,
                   information_value = ?,
                   scored_at         = ?
             WHERE id = ?
        """, (outcome_correct, row["resolution_date"], information_value, now, row["id"]))

        scored += 1
        if outcome_correct:
            correct_count += 1
            iv_sum_correct += information_value
        else:
            wrong_count += 1

        d = {**dict(row), "information_value": information_value, "outcome_correct": outcome_correct}
        if best is None or information_value > best["information_value"]:
            best = d
        if worst is None or information_value < worst["information_value"]:
            worst = d

    conn.commit()

    # Flag unresolved signals whose market title implies a past deadline
    today = datetime.now()
    unresolved = conn.execute("""
        SELECT s.id, s.market_title
        FROM insider_signals s
        LEFT JOIN markets m ON m.market_id = s.market_id
        WHERE (m.resolved IS NULL OR m.resolved = 0)
          AND s.outcome_correct IS NULL
    """).fetchall()

    flagged = []
    for row in unresolved:
        deadline = _parse_deadline_from_title(row["market_title"])
        if deadline and deadline < today:
            flagged.append((row["id"], row["market_title"], deadline.strftime("%Y-%m-%d")))

    conn.close()

    total = scored + pending_count
    raw_accuracy = (correct_count / scored * 100) if scored > 0 else 0.0
    weighted_accuracy = (iv_sum_correct / total) if total > 0 else 0.0

    print(f"\n=== INSIDER SIGNAL SCORING REPORT ===")
    print(f"Total signals:       {total}")
    print(f"  Scored:            {scored}  (market resolved)")
    print(f"    Correct:         {correct_count}")
    print(f"    Wrong:           {wrong_count}")
    print(f"  Pending:           {pending_count}  (market unresolved)")
    if scored > 0:
        print(f"\nRaw accuracy:        {raw_accuracy:.1f}%  ({correct_count}/{scored})")
        print(f"Weighted accuracy:   {weighted_accuracy:+.4f}  (sum IV correct / total signals)")

    if best:
        print(f"\nBest signal:  '{best['market_title']}'")
        print(f"  outcome={best['outcome']}  entry={best['entry_price']:.3f}"
              f"  correct={best['outcome_correct']}  IV={best['information_value']:+.4f}")
    if worst:
        print(f"Worst signal: '{worst['market_title']}'")
        print(f"  outcome={worst['outcome']}  entry={worst['entry_price']:.3f}"
              f"  correct={worst['outcome_correct']}  IV={worst['information_value']:+.4f}")

    if flagged:
        print(f"\nManual review needed — {len(flagged)} unresolved signal(s) with past deadline:")
        for sig_id, title, dl in flagged:
            print(f"  Signal #{sig_id}: '{title}'  (implied deadline: {dl})")

    print()


if __name__ == "__main__":
    main()
