#!/usr/bin/env python3
"""
register_signal.py — THE canonical signal registration utility.

This is the SINGLE chokepoint through which every STR-003 signal is born.
Both signal-agent (automated) and manual registration MUST go through this function.
Direct writes to signals.json are prohibited — they cause schema drift (see the
001-006 vs 007-009 bifurcation that motivated this utility).

What it does atomically at the moment of registration:
  1. Validates inputs (market exists, direction valid, traders non-empty)
  2. Fetches market_price_at_registration from CLOB (authoritative YES price NOW)
  3. Captures a registration order-book snapshot
  4. Looks up each trader's geo_elo_active at registration (point-in-time, from live DB)
  5. Reads each trader's archetype from the profile index
  6. Computes signal_credibility_score via signal_credibility.py
  7. Assigns event_cluster, generates next signal_id, stamps registered_at
  8. Builds the canonical schema record
  9. Validates all required fields present
  10. Writes to signals.json atomically (read-append-write under lock)

Why registration price matters: edge_at_entry = outcome - market_price_at_registration.
Capturing it at any time other than registration introduces hindsight contamination.
A signal without a true registration price cannot be cleanly validated.

Usage (CLI):
  python3 register_signal.py \
    --market-id 0x... \
    --direction NO \
    --traders 0xabc,0xdef \
    --event-cluster iran_june2026 \
    --notes "Two LEGENDARY traders converging NO"

Usage (import):
  from register_signal import register_signal
  result = register_signal(market_id='0x...', direction='NO',
                           key_traders=['0x...'], notes='...')
"""

import json
import sqlite3
import argparse
import sys
import re
import os
import fcntl
from datetime import datetime, timezone
from pathlib import Path

# Import CLOB price + book snapshot functions from the order book module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitoring.column_definitions as cd
from snapshot_order_books import fetch_clob_market_price, snapshot_market

DB_PATH = Path("/home/parison/projects/first-repo/data/polymarket_tracker.db")
SIGNALS_PATH = Path("/home/parison/trading-swarm/brain/signals.json")
PROFILE_INDEX = Path("/home/parison/trading-swarm/brain/trader-profiles/_index.json")

# Canonical schema — every signal MUST have all these fields
CANONICAL_FIELDS = [
    'signal_id', 'strategy', 'status', 'market_id', 'market_title', 'direction',
    'registered_at', 'key_traders', 'trader_elos_at_registration',
    'market_price_at_registration', 'event_cluster', 'correlated_with',
    'legendary_count', 'str002_confirmed', 'signal_credibility_score', 'signal_credibility_tier',
    'outcome_correct', 'edge_at_entry', 'resolved_at', 'scored_at', 'notes'
]


def _get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _load_archetypes():
    """Load archetype lookup from the profile index."""
    if not PROFILE_INDEX.exists():
        return {}
    try:
        with open(PROFILE_INDEX) as f:
            idx = json.load(f)
        return {addr: data.get('archetype') for addr, data in idx.items()}
    except Exception:
        return {}


def _next_signal_id(data):
    """Return the next STR003-NNN id (max existing + 1)."""
    ids = []
    for s in data.get('str003_signals', []):
        if isinstance(s, dict):
            m = re.match(r'STR003-(\d+)', s.get('signal_id', ''))
            if m:
                ids.append(int(m.group(1)))
    next_num = (max(ids) + 1) if ids else 1
    return f"STR003-{next_num:03d}"


def _validate_inputs(conn, market_id, direction, key_traders):
    """Validate registration inputs. Returns (ok, error_msg, market_row)."""
    if direction not in ('YES', 'NO'):
        return False, f"direction must be YES or NO, got {direction!r}", None
    if not key_traders or not isinstance(key_traders, list):
        return False, "key_traders must be a non-empty list", None

    row = conn.execute(
        "SELECT market_id, title, condition_id, resolved FROM markets WHERE market_id = ?",
        (market_id,)
    ).fetchone()
    if not row:
        return False, f"market_id {market_id} not found in DB", None
    if row['resolved']:
        return False, f"market {market_id} is already resolved — cannot register signal", None
    return True, None, row


def _lookup_trader_elos(conn, key_traders):
    """Return dict of {address: geo_elo_active} and count of LEGENDARY-tier traders."""
    elos = {}
    legendary_count = 0
    for addr in key_traders:
        r = conn.execute(
            "SELECT geo_elo_active, geo_accuracy_pool, research_excluded, bot_type "
            "FROM traders WHERE address = ?", (addr,)
        ).fetchone()
        if r and r['geo_elo_active'] is not None:
            elos[addr] = round(float(r['geo_elo_active']), 1)
            is_clean = (r['geo_accuracy_pool'] == 1 and r['research_excluded'] == 0
                        and r['bot_type'] is None)
            if elos[addr] >= cd.GEO_ELO_LEGENDARY and is_clean:
                legendary_count += 1
        else:
            elos[addr] = None
    return elos, legendary_count


def _compute_scs(conn, market_id, current_price_yes=None):
    """Compute signal credibility score via signal_credibility.py. Returns (score, tier)."""
    try:
        from signal_credibility import score_market
        result = score_market(conn, market_id, current_price_yes)
        if result:
            score = result.get('signal_credibility_score') or result.get('score')
            tier = result.get('signal_credibility_tier') or result.get('tier')
            return score, tier
    except Exception as e:
        print(f"  [scs] Could not compute SCS: {e}", file=sys.stderr)
    return None, None


def _scs_tier_from_score(score):
    """Fallback tier assignment if SCS module doesn't provide one."""
    if score is None:
        return None
    if score >= 70:
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    return "LOW"



def _check_str002_confirmation(conn, market_id, direction):
    """Check if this market+direction has a confirming STR-002 signal with a
    proven trader (ELITE/LEGENDARY). This is the STR-002 -> STR-003 stepping-stone:
    a STR-003 signal that was ALSO flagged by pre-resolution divergence from a
    proven trader is higher-conviction (two independent detection methods agree).

    Returns dict: {confirmed: bool, str002_signal_id, str002_tier, str002_regime,
                   str002_first_seen} or {confirmed: False}.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT signal_id, tier, regime, first_seen_date, has_proven_trader
            FROM str002_signals
            WHERE market_id = ? AND direction = ?
              AND has_proven_trader = 1
            ORDER BY first_seen_date ASC
            LIMIT 1
        """, (market_id, direction.upper()))
        row = cur.fetchone()
        if row:
            return {
                'confirmed': True,
                'str002_signal_id': row[0],
                'str002_tier': row[1],
                'str002_regime': row[2],
                'str002_first_seen': row[3],
            }
    except Exception as e:
        # str002_signals table may not exist in some contexts — fail safe
        pass
    return {'confirmed': False}


def register_signal(market_id, direction, key_traders, strategy='STR-003',
                    event_cluster=None, correlated_with=None, notes='',
                    signal_credibility_score=None, fire_alert=False, dry_run=False):
    """
    Register a new STR-003 signal. THE canonical signal writer.

    Returns dict: {success: bool, signal_id: str, signal: dict, error: str|None}
    """
    direction = direction.upper()
    correlated_with = correlated_with or []
    conn = _get_connection()

    # 1. Validate
    ok, err, market_row = _validate_inputs(conn, market_id, direction, key_traders)
    if not ok:
        conn.close()
        return {"success": False, "signal_id": None, "signal": None, "error": err}

    market_title = market_row['title']
    condition_id = market_row['condition_id'] or market_id  # market_id IS condition_id for most

    # 2. Fetch registration price (authoritative YES price NOW)
    reg_price = fetch_clob_market_price(condition_id)
    if reg_price is None:
        # Try market_id directly as condition_id
        reg_price = fetch_clob_market_price(market_id)
    if reg_price is None:
        print(f"  [warn] Could not fetch registration price for {market_id} — "
              f"signal will have null market_price_at_registration", file=sys.stderr)

    # 3 & 4. Trader ELOs at registration (point-in-time)
    trader_elos, legendary_count = _lookup_trader_elos(conn, key_traders)

    # 5. Archetypes
    archetypes = _load_archetypes()
    trader_archetypes = {addr: archetypes.get(addr) for addr in key_traders}

    # 5b. STR-002 confirmation check (stepping-stone link)
    str002 = _check_str002_confirmation(conn, market_id, direction)

    # 6. SCS
    if signal_credibility_score is None:
        scs_score, scs_tier = _compute_scs(conn, market_id, reg_price)
    else:
        scs_score = signal_credibility_score
        scs_tier = None
    if scs_tier is None:
        scs_tier = _scs_tier_from_score(scs_score)

    # 7. Read signals.json, generate ID, build record
    with open(SIGNALS_PATH) as f:
        data = json.load(f)

    signal_id = _next_signal_id(data)
    registered_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    signal = {
        "signal_id": signal_id,
        "strategy": strategy,
        "status": "ACTIVE",
        "market_id": market_id,
        "market_title": market_title,
        "direction": direction,
        "registered_at": registered_at,
        "key_traders": key_traders,
        "trader_elos_at_registration": trader_elos,
        "trader_archetypes_at_registration": trader_archetypes,
        "market_price_at_registration": reg_price,
        "event_cluster": event_cluster,
        "correlated_with": correlated_with,
        "legendary_count": legendary_count,
        "str002_confirmed": str002['confirmed'],
        "str002_confirmation": str002 if str002['confirmed'] else None,
        "signal_credibility_score": scs_score,
        "signal_credibility_tier": scs_tier,
        "outcome_correct": None,
        "edge_at_entry": None,
        "resolved_at": None,
        "scored_at": None,
        "notes": notes,
    }

    # 8. Validate canonical schema
    missing = [f for f in CANONICAL_FIELDS if f not in signal]
    if missing:
        conn.close()
        return {"success": False, "signal_id": signal_id, "signal": signal,
                "error": f"Schema validation failed — missing fields: {missing}"}

    if dry_run:
        conn.close()
        print(json.dumps(signal, indent=2))
        return {"success": True, "signal_id": signal_id, "signal": signal,
                "error": None, "dry_run": True}

    # 9. Capture registration order-book snapshot
    try:
        snapshot_market(conn, signal_id, market_id, direction, snapshot_type='registration')
    except Exception as e:
        print(f"  [warn] Registration book snapshot failed: {e}", file=sys.stderr)

    # 10. Atomic write to signals.json (read-modify-write under lock)
    with open(SIGNALS_PATH, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            data = json.load(f)
            data.setdefault('str003_signals', []).append(signal)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    conn.close()

    print(f"✓ Registered {signal_id}: {direction} on {market_title[:50]}")
    print(f"  Registration price (YES): {reg_price}")
    print(f"  Traders: {len(key_traders)} ({legendary_count} LEGENDARY)")
    print(f"  Trader ELOs: {trader_elos}")
    print(f"  SCS: {scs_score} ({scs_tier})")
    print(f"  Event cluster: {event_cluster}")

    # 11. Optional Telegram alert
    if fire_alert:
        _fire_telegram_alert(signal)

    return {"success": True, "signal_id": signal_id, "signal": signal, "error": None}


def _fire_telegram_alert(signal):
    """Fire a Telegram alert for the new signal. Best-effort, non-blocking."""
    try:
        msg = (f"🎯 STR-003 SIGNAL REGISTERED\n"
               f"{signal['signal_id']}: {signal['direction']} on {signal['market_title'][:60]}\n"
               f"Registration YES price: {signal['market_price_at_registration']}\n"
               f"LEGENDARY traders: {signal['legendary_count']}\n"
               f"SCS: {signal['signal_credibility_score']} ({signal['signal_credibility_tier']})")
        print(f"  [telegram] Would send:\n{msg}", file=sys.stderr)
    except Exception as e:
        print(f"  [telegram] Alert failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Register a canonical STR-003 signal")
    parser.add_argument('--market-id', required=True, help='Market condition ID (0x...)')
    parser.add_argument('--direction', required=True, choices=['YES', 'NO'])
    parser.add_argument('--traders', required=True,
                       help='Comma-separated trader addresses')
    parser.add_argument('--strategy', default='STR-003')
    parser.add_argument('--event-cluster', default=None)
    parser.add_argument('--correlated-with', default=None,
                       help='Comma-separated signal IDs')
    parser.add_argument('--notes', default='')
    parser.add_argument('--scs', type=float, default=None,
                       help='Override signal credibility score')
    parser.add_argument('--fire-alert', action='store_true')
    parser.add_argument('--dry-run', action='store_true',
                       help='Build and validate but do not write')
    args = parser.parse_args()

    key_traders = [t.strip() for t in args.traders.split(',') if t.strip()]
    correlated = ([c.strip() for c in args.correlated_with.split(',')]
                  if args.correlated_with else [])

    result = register_signal(
        market_id=args.market_id,
        direction=args.direction,
        key_traders=key_traders,
        strategy=args.strategy,
        event_cluster=args.event_cluster,
        correlated_with=correlated,
        notes=args.notes,
        signal_credibility_score=args.scs,
        fire_alert=args.fire_alert,
        dry_run=args.dry_run,
    )

    if not result['success']:
        print(f"✗ Registration failed: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
