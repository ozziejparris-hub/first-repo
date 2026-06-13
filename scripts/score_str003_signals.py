#!/usr/bin/env python3
"""
Score active STR-003 signals in signals.json against resolved market outcomes.

For each signal with type containing 'str003':
  1. Find the market in the markets table (JOIN on market_id)
  2. If resolved=1 and winning_outcome known:
     - outcome_correct = 1 if signal direction matches winning_outcome
     - Record result with timestamp
  3. Update signals.json with outcome_correct, resolved_at, scored_at
  4. Write accuracy finding to findings.json if 3+ signals resolved
  5. Report accuracy: correct/total, by trader geo_elo tier

Expected signal payload fields:
  market_id       — matches markets.market_id
  direction       — 'YES' or 'NO'
  geo_elo_tier    — optional; computed from trader_geo_elo if absent
  trader_geo_elo  — optional; used for tier breakdown
  market_title    — optional; used for human-readable output
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
SIGNALS_PATH = Path("/home/parison/trading-swarm/brain/signals.json")
FINDINGS_PATH = Path("/home/parison/trading-swarm/brain/findings.json")

GEO_ELO_LEGENDARY = 2175.0
GEO_ELO_ELITE = 1800.0
GEO_ELO_QUALIFIED = 1500.0


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _geo_elo_tier(geo_elo) -> str:
    if geo_elo is None:
        return "UNKNOWN"
    geo_elo = float(geo_elo)
    if geo_elo >= GEO_ELO_LEGENDARY:
        return "LEGENDARY"
    if geo_elo >= GEO_ELO_ELITE:
        return "ELITE"
    if geo_elo >= GEO_ELO_QUALIFIED:
        return "QUALIFIED"
    return "BELOW_QUALIFIED"


def _collect_str003_signals(data: dict) -> list:
    """
    Walk all list-valued keys in signals.json; return (list_key, index, signal_dict)
    for every entry whose 'type' field contains 'str003'.
    """
    found = []
    for key, val in data.items():
        if isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, dict) and 'str003' in str(item.get('type', '')).lower():
                    found.append((key, i, item))
    return found


def _score_signal(signal: dict, conn) -> dict:
    """
    Attempt to score a signal. Returns updated dict with outcome fields, or
    the original dict unchanged if the market is not yet resolved.
    """
    payload = signal.get('payload', {})
    market_id = payload.get('market_id') or signal.get('market_id')
    direction = str(payload.get('direction') or signal.get('direction', '')).upper()

    if not market_id or direction not in ('YES', 'NO'):
        return signal

    row = conn.execute("""
        SELECT resolved, winning_outcome, resolution_date
        FROM markets
        WHERE market_id = ?
    """, (market_id,)).fetchone()

    if not row:
        return signal

    if not row['resolved']:
        return signal

    wo = row['winning_outcome']
    if not wo or wo.lower() in ('', 'unknown'):
        return signal

    winning_outcome = wo.upper()
    outcome_correct = 1 if direction == winning_outcome else 0

    updated = dict(signal)
    updated['outcome_correct'] = outcome_correct
    updated['resolved_at'] = row['resolution_date']
    updated['scored_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Market-relative edge: how much the signal beat market consensus at entry.
    # Positive = correctly identified underpriced side; near-zero = market already knew.
    # Only computable when a registration price was captured at or near signal creation.
    reg_price = (signal.get('market_price_at_registration') or
                 signal.get('market_price_at_first_capture'))
    if reg_price is not None:
        try:
            reg_price = float(reg_price)
            market_implied_signal_side = reg_price if direction == 'YES' else (1.0 - reg_price)
            edge_at_entry = float(outcome_correct) - market_implied_signal_side
            updated['edge_at_entry'] = round(edge_at_entry, 4)
            updated['market_price_at_registration_used'] = reg_price
        except (TypeError, ValueError):
            updated['edge_at_entry'] = None
    else:
        updated['edge_at_entry'] = None

    return updated


def _write_finding(resolved_signals: list):
    """Append a STR-003 accuracy finding to findings.json (requires 3+ resolved signals)."""
    if len(resolved_signals) < 3:
        return

    if not FINDINGS_PATH.exists():
        print(f"[str003] WARNING — findings.json not found at {FINDINGS_PATH}", file=sys.stderr)
        return

    correct = sum(1 for s in resolved_signals if s.get('outcome_correct') == 1)
    total = len(resolved_signals)
    accuracy = correct / total

    # Per-tier breakdown
    tier_stats = {}
    for sig in resolved_signals:
        payload = sig.get('payload', {})
        tier = (payload.get('geo_elo_tier') or sig.get('geo_elo_tier') or
                _geo_elo_tier(payload.get('trader_geo_elo') or sig.get('trader_geo_elo')))
        if tier not in tier_stats:
            tier_stats[tier] = {'correct': 0, 'total': 0}
        tier_stats[tier]['total'] += 1
        if sig.get('outcome_correct') == 1:
            tier_stats[tier]['correct'] += 1

    now = datetime.now(timezone.utc)
    finding_id = now.strftime('%Y-%m-%d') + f"-STR003-ACC-{total:03d}"
    confidence = "HIGH" if total >= 20 else ("MEDIUM" if total >= 10 else "LOW")

    finding = {
        "id": finding_id,
        "generated_by": "score_str003_signals",
        "generated_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "finding_type": "strategy_performance",
        "confidence": confidence,
        "sample_size": total,
        "summary": (
            f"STR-003 out-of-sample accuracy: {accuracy:.1%} "
            f"({correct}/{total} resolved signals correct)"
        ),
        "detail": {
            "metric": "str003_outcome_accuracy",
            "value": round(accuracy, 4),
            "baseline": 0.5,
            "direction": "above_baseline" if accuracy > 0.5 else "below_baseline",
            "pass_threshold": 0.60,
            "passed": accuracy >= 0.60,
            "by_tier": {
                tier: {
                    "n": s['total'],
                    "accuracy": round(s['correct'] / s['total'], 4) if s['total'] > 0 else None,
                }
                for tier, s in sorted(tier_stats.items())
            },
        },
        "actionable": accuracy >= 0.60 and total >= 10,
        "action_recommendation": (
            "STR-003 exceeds 60% accuracy threshold — consider advancing strategy to PENDING_VALIDATION."
            if accuracy >= 0.60 and total >= 10
            else "Accumulate more resolved signals before drawing conclusions (minimum 10 for MEDIUM confidence)."
        ),
        "expires_at": now.replace(year=now.year + 1).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }

    data = json.loads(FINDINGS_PATH.read_text())
    findings = data.get('findings', [])
    # Remove any earlier STR003-ACC finding from today (keep only latest)
    findings = [
        f for f in findings
        if not f.get('id', '').startswith(now.strftime('%Y-%m-%d') + '-STR003-ACC')
    ]
    findings.append(finding)
    data['findings'] = findings
    FINDINGS_PATH.write_text(json.dumps(data, indent=2))
    print(f"[str003] Finding written: {finding_id} "
          f"({confidence}, {accuracy:.1%} accuracy, n={total})")


def main():
    if not SIGNALS_PATH.exists():
        print(f"[str003] signals.json not found at {SIGNALS_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = _get_connection()
    data = json.loads(SIGNALS_PATH.read_text())
    str003_refs = _collect_str003_signals(data)

    if not str003_refs:
        print("[str003] No STR-003 signals found in signals.json.")
        conn.close()
        return

    print(f"[str003] Found {len(str003_refs)} STR-003 signal(s).")

    changed = False
    pending = 0
    newly_scored = 0

    for key, idx, signal in str003_refs:
        if signal.get('outcome_correct') is not None:
            continue  # already scored

        updated = _score_signal(signal, conn)
        if updated is signal:
            pending += 1
            continue

        data[key][idx] = updated
        changed = True
        newly_scored += 1

        p = updated.get('payload', {})
        direction = p.get('direction') or updated.get('direction', '?')
        title = (p.get('market_title') or updated.get('market_title') or
                 p.get('market_id') or updated.get('market_id', 'unknown'))
        result_str = "CORRECT" if updated['outcome_correct'] == 1 else "WRONG"
        print(f"  Scored: {title} | {direction} → {result_str}")

    conn.close()

    if changed:
        SIGNALS_PATH.write_text(json.dumps(data, indent=2))
        print(f"[str003] signals.json updated — {newly_scored} newly scored")

    # Accuracy report across all resolved STR-003 signals
    all_str003 = [data[k][i] for k, i, _ in _collect_str003_signals(data)]
    already_scored = [s for s in all_str003 if s.get('outcome_correct') is not None]
    total_signals = len(all_str003)

    print(f"[str003] Status: {len(already_scored)}/{total_signals} resolved, {pending} pending resolution")

    if already_scored:
        correct = sum(1 for s in already_scored if s.get('outcome_correct') == 1)
        accuracy = correct / len(already_scored)
        print(f"[str003] Accuracy: {accuracy:.1%} ({correct}/{len(already_scored)})")

        with_edge = [s for s in already_scored if s.get('edge_at_entry') is not None]
        if with_edge:
            avg_edge = sum(s['edge_at_entry'] for s in with_edge) / len(with_edge)
            print(f"[str003] Market-relative edge: {avg_edge:+.4f} avg "
                  f"({len(with_edge)}/{len(already_scored)} signals have registration price)")
            for s in with_edge:
                print(f"  {s.get('signal_id','?')}: edge={s['edge_at_entry']:+.4f} "
                      f"(registered at YES={s.get('market_price_at_registration_used','?')})")
        else:
            print("[str003] Market-relative edge: N/A — no signals have market_price_at_registration")
            print("  (forward-only metric — new signals will capture this at registration)")

        tier_counts = {}
        for sig in already_scored:
            payload = sig.get('payload', {})
            tier = (payload.get('geo_elo_tier') or sig.get('geo_elo_tier') or
                _geo_elo_tier(payload.get('trader_geo_elo') or sig.get('trader_geo_elo')))
            if tier not in tier_counts:
                tier_counts[tier] = {'correct': 0, 'total': 0}
            tier_counts[tier]['total'] += 1
            if sig.get('outcome_correct') == 1:
                tier_counts[tier]['correct'] += 1

        for tier, s in sorted(tier_counts.items()):
            acc = s['correct'] / s['total'] if s['total'] > 0 else 0.0
            print(f"  {tier}: {acc:.1%} ({s['correct']}/{s['total']})")

        _write_finding(already_scored)
    else:
        print("[str003] No resolved signals yet — accuracy not yet measurable.")


if __name__ == "__main__":
    main()
