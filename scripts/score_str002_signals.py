#!/usr/bin/env python3
"""
score_str002_signals.py — STR-002 signal scorer.

Reads the str002_signals registry. For each unscored signal whose market has been
FINALIZED by the UMA oracle (closed=true AND a token has winner=true — NOT merely
ended or trading at 0.99), computes:
  - outcome_correct: 1 if signal direction matches winning outcome, else 0
  - edge_at_entry: market-relative edge vs registration price (forward-honest)

DESIGN: Scoring is deterministic. Each signal has a locked market_id from registration.
We query THAT market_id's resolution directly — no title matching, no ambiguity.

RESOLUTION SEMANTICS (integration contract 14b): A market at 0.99 is NOT resolved.
We score ONLY when the DB shows resolved=1 with a winning_outcome (which the resolution
pipeline sets only after verifying closed=true AND winner token via CLOB). We trust the
DB's resolved flag because fast_resolution_check.py enforces the UMA finalization check.

edge_at_entry:
  market_implied_signal_side = market_price_at_registration if direction==YES
                               else (1 - market_price_at_registration)
  edge_at_entry = outcome_correct - market_implied_signal_side
  Positive = signal beat the market (identified underpriced side)
  Near-zero = market already knew

Scores BOTH metrics (raw accuracy AND market-relative edge) per the Fable metric-trap
finding: raw accuracy without edge is uninformative.

Writes a findings file for feedback-loop-agent. Wire into daily maintenance.

Usage:
  python3 score_str002_signals.py            # score all newly-resolved signals
  python3 score_str002_signals.py --report   # show current accuracy + edge report
"""

import json
import sqlite3
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
FINDINGS_DIR = Path("/home/parison/trading-swarm/brain/agent-outputs/str002-scoring/")


def score_signals(conn):
    """Score all unscored STR-002 signals whose markets have UMA-finalized."""
    cur = conn.cursor()

    # Get unscored signals
    cur.execute("""
        SELECT signal_id, market_id, market_title, direction,
               market_price_at_registration, tier
        FROM str002_signals
        WHERE scored_at IS NULL
    """)
    unscored = cur.fetchall()
    print(f"Unscored signals: {len(unscored)}")

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    newly_scored = 0

    for signal_id, market_id, title, direction, reg_price, tier in unscored:
        # Check if THIS market_id is resolved (UMA-finalized — DB flag is trustworthy
        # because fast_resolution_check verifies closed+winner before setting it)
        cur.execute("""
            SELECT resolved, winning_outcome, resolution_date
            FROM markets WHERE market_id = ?
        """, (market_id,))
        m = cur.fetchone()
        if not m or m[0] != 1 or not m[1]:
            continue  # Not finalized yet — leave pending, will score automatically later

        winning_outcome = str(m[1]).upper()
        resolution_date = m[2]

        # outcome_correct: does signal direction match the winning outcome?
        outcome_correct = 1 if direction.upper() == winning_outcome else 0

        # edge_at_entry — only if we have registration price
        edge_at_entry = None
        if reg_price is not None:
            try:
                rp = float(reg_price)
                if direction.upper() == 'YES':
                    market_implied = rp
                else:
                    market_implied = 1.0 - rp
                edge_at_entry = round(float(outcome_correct) - market_implied, 4)
            except (TypeError, ValueError):
                edge_at_entry = None

        cur.execute("""
            UPDATE str002_signals
            SET outcome_correct = ?, winning_outcome = ?, edge_at_entry = ?,
                resolved_at = ?, scored_at = ?
            WHERE market_id = ? AND direction = ?
        """, (outcome_correct, winning_outcome, edge_at_entry, resolution_date, now,
              market_id, direction))

        result = 'CORRECT' if outcome_correct else 'WRONG'
        edge_str = f"{edge_at_entry:+.4f}" if edge_at_entry is not None else "n/a"
        print(f"  SCORED {signal_id}: [{tier}] {title[:38]} | {direction} "
              f"-> {winning_outcome} | {result} | edge={edge_str}")
        newly_scored += 1

    conn.commit()
    print(f"\nNewly scored: {newly_scored}")
    return newly_scored


def build_report(conn):
    """Compute and display accuracy + edge across all scored signals."""
    cur = conn.cursor()
    cur.execute("""
        SELECT signal_id, tier, direction, outcome_correct, edge_at_entry,
               market_price_at_registration, market_title
        FROM str002_signals
        WHERE scored_at IS NOT NULL
    """)
    scored = cur.fetchall()

    if not scored:
        print("[str002] No signals scored yet.")
        cur.execute("SELECT COUNT(*) FROM str002_signals")
        total = cur.fetchone()[0]
        print(f"[str002] {total} signals registered, awaiting market resolution.")
        return None

    total = len(scored)
    correct = sum(1 for s in scored if s[3] == 1)
    accuracy = correct / total if total else 0

    print(f"[str002] OVERALL: {accuracy:.1%} accuracy ({correct}/{total})")

    # By tier
    print(f"[str002] By tier:")
    for tier in ('LEGENDARY', 'ELITE', 'QUALIFIED'):
        tier_sigs = [s for s in scored if s[1] == tier]
        if tier_sigs:
            t_correct = sum(1 for s in tier_sigs if s[3] == 1)
            print(f"  {tier}: {t_correct/len(tier_sigs):.1%} ({t_correct}/{len(tier_sigs)})")

    # Market-relative edge
    with_edge = [s for s in scored if s[4] is not None]
    if with_edge:
        avg_edge = sum(s[4] for s in with_edge) / len(with_edge)
        print(f"[str002] Market-relative edge: {avg_edge:+.4f} avg "
              f"({len(with_edge)}/{total} have registration price)")
        # Edge by tier
        for tier in ('LEGENDARY', 'ELITE', 'QUALIFIED'):
            tier_edge = [s[4] for s in with_edge if s[1] == tier]
            if tier_edge:
                print(f"  {tier} edge: {sum(tier_edge)/len(tier_edge):+.4f}")

    # Gate 3 check
    print(f"[str002] GATE 3: needs >=10 scored at >=60% accuracy")
    if total >= 10:
        status = "PASS" if accuracy >= 0.60 else "FAIL"
        print(f"  Status: {status} ({total} scored, {accuracy:.1%})")
    else:
        print(f"  Status: PENDING ({total}/10 scored)")

    return {
        'total_scored': total,
        'accuracy': round(accuracy, 4),
        'correct': correct,
        'avg_edge': round(sum(s[4] for s in with_edge) / len(with_edge), 4) if with_edge else None,
    }


def write_findings(conn, summary):
    """Write findings file for feedback-loop-agent."""
    if not summary:
        return
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    findings_path = FINDINGS_DIR / f"{date_str}-str002-scoring.json"

    cur = conn.cursor()
    cur.execute("""
        SELECT signal_id, tier, direction, outcome_correct, edge_at_entry,
               market_title, winning_outcome, resolved_at
        FROM str002_signals WHERE scored_at IS NOT NULL
    """)
    signals = [{
        'signal_id': r[0], 'tier': r[1], 'direction': r[2],
        'outcome_correct': r[3], 'edge_at_entry': r[4],
        'market_title': r[5], 'winning_outcome': r[6], 'resolved_at': r[7]
    } for r in cur.fetchall()]

    findings = {
        'strategy': 'STR-002',
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'summary': summary,
        'scored_signals': signals,
    }
    with open(findings_path, 'w') as f:
        json.dump(findings, f, indent=2)
    print(f"[str002] Findings written: {findings_path.name}")


def main():
    parser = argparse.ArgumentParser(description="Score STR-002 signals")
    parser.add_argument('--report', action='store_true', help='Show report only, no scoring')
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    if args.report:
        build_report(conn)
    else:
        score_signals(conn)
        print()
        summary = build_report(conn)
        write_findings(conn, summary)

    conn.close()


if __name__ == '__main__':
    main()
