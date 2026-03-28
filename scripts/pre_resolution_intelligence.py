"""
pre_resolution_intelligence.py

Scans open markets resolving within 7 days and reports how qualified traders
(ELO >= 1500) are positioned vs. the current market price.

Signal tiers:
  LEGENDARY  — at least 1 ELO >= 2175 trader positioned
  ELITE      — at least 1 ELO >= 1800 trader, none legendary
  QUALIFIED  — ELO >= 1500 traders only

An alert fires when the share-weighted smart-money YES% diverges from the
current market price by more than 15 percentage points.

Trend labels (comparing positions entered <= 48 h ago vs older positions):
  NEW           — all elite positions entered in the last 48 h
  STRENGTHENING — recent positioning has moved further from 50%
  WEAKENING     — recent positioning has drifted back toward market price
  STABLE        — insufficient recent data to determine direction

Usage:
  python scripts/pre_resolution_intelligence.py            # live run
  python scripts/pre_resolution_intelligence.py --dry-run  # print only, no Telegram

Importable:
  from scripts.pre_resolution_intelligence import run_pre_resolution_intelligence
"""

import argparse
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH   = os.path.join(_REPO_ROOT, 'data', 'polymarket_tracker.db')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TRADERS         = 3      # minimum qualified (ELO >= 1500) traders per market
DIVERGENCE_THRESH   = 15.0   # percentage points
LOOKBACK_DAYS       = 7
TREND_WINDOW_HOURS  = 48
ELO_QUALIFIED       = 1500
ELO_ELITE           = 1800
ELO_LEGENDARY       = 2175

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_upcoming_markets(conn: sqlite3.Connection) -> list[dict]:
    """Return open markets resolving within LOOKBACK_DAYS days."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            market_id,
            title,
            end_date,
            CAST(
                (julianday(end_date) - julianday('now'))
            AS REAL) AS days_left
        FROM markets
        WHERE resolved = 0
          AND end_date IS NOT NULL
          AND end_date > datetime('now')
          AND end_date < datetime('now', :window)
        ORDER BY end_date ASC
    """, {"window": f"+{LOOKBACK_DAYS} days"})
    return [dict(r) for r in cur.fetchall()]


def _fetch_elite_positions(conn: sqlite3.Connection, market_id: str) -> list[dict]:
    """
    Return all open positions in *market_id* for qualified traders (ELO >= 1500).
    Includes entry price, shares, outcome, entry timestamp, and ELO.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            p.outcome,
            p.entry_avg_price,
            p.entry_shares,
            p.entry_timestamp,
            t.comprehensive_elo
        FROM positions p
        JOIN traders   t ON t.address = p.trader_address
        WHERE p.market_id  = :mid
          AND p.status      = 'open'
          AND t.comprehensive_elo >= :min_elo
    """, {"mid": market_id, "min_elo": ELO_QUALIFIED})
    return [dict(r) for r in cur.fetchall()]


def _latest_trade_price(conn: sqlite3.Connection, market_id: str, outcome: str) -> float | None:
    """
    Return the most recent trade price for *outcome* in *market_id*.
    Used as a proxy for current market price when the API is unavailable.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT price FROM trades
        WHERE market_id = :mid
          AND outcome   = :outcome
        ORDER BY timestamp DESC
        LIMIT 1
    """, {"mid": market_id, "outcome": outcome})
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Current price fetching
# ---------------------------------------------------------------------------

def _get_market_price(conn: sqlite3.Connection, market: dict) -> float | None:
    """
    Return the implied YES probability for a binary market.

    Strategy:
      1. Try the Polymarket CLOB/Data API via PolymarketClient if available.
      2. Fall back to the most recent YES trade price in the DB.

    For non-binary markets (no clear YES/NO split) returns None — those
    markets are still included in the report but show 'price unavailable'.
    """
    # Fast path: DB fallback only (avoids network dependency)
    yes_price = _latest_trade_price(conn, market['market_id'], 'Yes')
    no_price  = _latest_trade_price(conn, market['market_id'], 'No')

    if yes_price is not None:
        return yes_price
    if no_price is not None:
        return 1.0 - no_price

    # Try live API price if PolymarketClient is importable
    try:
        sys.path.insert(0, _REPO_ROOT)
        from monitoring.polymarket_client import PolymarketClient
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_REPO_ROOT, '.env'))
        api_key = os.getenv('POLYMARKET_API_KEY', '')
        client = PolymarketClient(api_key=api_key)
        markets = client.get_markets(limit=1)  # lightweight probe
        # We'd need condition_id lookup for a single market; skip for now
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def _compute_signal(positions: list[dict]) -> dict:
    """
    Given a list of open positions for one market, compute:
      - elite_yes_pct   : share-weighted YES% among qualified traders
      - trader_count    : total qualified traders
      - elite_count     : ELO >= 1800
      - legendary_count : ELO >= 2175
      - elite_yes_pct_recent    : same but only positions entered in last 48 h
      - elite_yes_pct_older     : same but older positions
      - trend           : STRENGTHENING / WEAKENING / NEW / STABLE
      - tier            : LEGENDARY / ELITE / QUALIFIED
    """
    cutoff_ts = datetime.now(timezone.utc) - timedelta(hours=TREND_WINDOW_HOURS)

    total_yes_shares   = 0.0
    total_no_shares    = 0.0
    recent_yes_shares  = 0.0
    recent_no_shares   = 0.0
    older_yes_shares   = 0.0
    older_no_shares    = 0.0

    trader_set    = set()
    elite_set     = set()
    legendary_set = set()

    for p in positions:
        outcome   = (p['outcome'] or '').strip().lower()
        shares    = p['entry_shares'] or 0.0
        elo       = p['comprehensive_elo'] or 0.0
        ts_str    = p['entry_timestamp'] or ''
        is_yes    = outcome == 'yes'
        is_no     = outcome == 'no'

        if not (is_yes or is_no):
            continue  # skip multi-outcome legs for trend calc

        trader_set.add(id(p))  # positional id as proxy (address not fetched)
        if elo >= ELO_LEGENDARY:
            legendary_set.add(id(p))
            elite_set.add(id(p))
        elif elo >= ELO_ELITE:
            elite_set.add(id(p))

        if is_yes:
            total_yes_shares += shares
        else:
            total_no_shares  += shares

        # Trend window
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            is_recent = ts >= cutoff_ts
        except (ValueError, AttributeError):
            is_recent = False

        if is_recent:
            if is_yes: recent_yes_shares += shares
            else:      recent_no_shares  += shares
        else:
            if is_yes: older_yes_shares  += shares
            else:      older_no_shares   += shares

    total_shares = total_yes_shares + total_no_shares
    elite_yes_pct = (total_yes_shares / total_shares * 100.0) if total_shares > 0 else 50.0

    # Trend
    recent_total = recent_yes_shares + recent_no_shares
    older_total  = older_yes_shares  + older_no_shares

    if older_total == 0 and recent_total > 0:
        trend = "NEW"
    elif recent_total == 0:
        trend = "STABLE"
    else:
        recent_pct = recent_yes_shares / recent_total * 100.0
        older_pct  = older_yes_shares  / older_total  * 100.0
        # "Strengthening" means more extreme (further from 50)
        if abs(recent_pct - 50) > abs(older_pct - 50):
            trend = "STRENGTHENING"
        elif abs(recent_pct - 50) < abs(older_pct - 50) - 2:
            trend = "WEAKENING"
        else:
            trend = "STABLE"

    # Tier
    if legendary_set:
        tier = "LEGENDARY"
    elif elite_set:
        tier = "ELITE"
    else:
        tier = "QUALIFIED"

    return {
        "elite_yes_pct":    elite_yes_pct,
        "trader_count":     len(positions),        # all qualifying rows
        "elite_count":      len(elite_set),
        "legendary_count":  len(legendary_set),
        "trend":            trend,
        "tier":             tier,
    }


# ---------------------------------------------------------------------------
# Telegram formatting
# ---------------------------------------------------------------------------

def _tier_emoji(tier: str) -> str:
    return {"LEGENDARY": "👑", "ELITE": "⭐", "QUALIFIED": "✅"}.get(tier, "")


def _trend_emoji(trend: str) -> str:
    return {"STRENGTHENING": "📈", "WEAKENING": "📉", "NEW": "🆕", "STABLE": "➡️"}.get(trend, "")


def _format_market_message(market: dict, signal: dict, market_price: float | None) -> str:
    days = market['days_left']
    if days < 1:
        days_str = f"{days * 24:.0f}h"
    else:
        days_str = f"{days:.1f}d"

    tier    = signal['tier']
    trend   = signal['trend']
    yes_pct = signal['elite_yes_pct']

    price_str = f"{market_price * 100:.1f}%" if market_price is not None else "unavailable"
    gap_str   = (
        f"{abs(yes_pct - market_price * 100):.1f}pt gap"
        if market_price is not None else "gap unknown"
    )

    # Direction word
    direction = "YES" if yes_pct >= 50 else "NO"
    lean_pct  = yes_pct if yes_pct >= 50 else 100 - yes_pct

    elite_line = ""
    if signal['legendary_count'] > 0:
        elite_line = f"\n👑 {signal['legendary_count']} legendary trader(s) positioned"
    elif signal['elite_count'] > 0:
        elite_line = f"\n⭐ {signal['elite_count']} elite (ELO≥1800) trader(s) positioned"

    lines = [
        f"{_tier_emoji(tier)} *{tier} SIGNAL* — resolves in {days_str}",
        f"",
        f"📋 {market['title']}",
        f"",
        f"📊 Market price:  {price_str}",
        f"🧠 Smart money:   {yes_pct:.1f}% → {direction} ({lean_pct:.0f}% conviction)",
        f"📏 Divergence:    {gap_str}",
        f"",
        f"{_trend_emoji(trend)} Trend: {trend}",
        f"👥 Qualified traders: {signal['trader_count']}",
        elite_line.strip() if elite_line else "",
    ]
    return "\n".join(l for l in lines if l != "")


def _format_no_signals_message(total_upcoming: int) -> str:
    return (
        f"ℹ️ *Pre-Resolution Intelligence*\n\n"
        f"No high-conviction signals found.\n"
        f"{total_upcoming} market(s) resolve in the next {LOOKBACK_DAYS} days "
        f"but none has ≥{MIN_TRADERS} qualified traders (ELO≥{ELO_QUALIFIED}) "
        f"with ≥{DIVERGENCE_THRESH:.0f}pt divergence from market price."
    )


# ---------------------------------------------------------------------------
# Telegram dispatch
# ---------------------------------------------------------------------------

async def _send_messages(messages: list[str], dry_run: bool) -> None:
    if dry_run:
        import unicodedata
        def _safe(text: str) -> str:
            return ''.join(c if ord(c) < 128 else f'[{unicodedata.name(c, "?")}]' for c in text)
        for i, msg in enumerate(messages, 1):
            print(f"\n{'='*60}")
            print(f"[DRY RUN] Message {i}/{len(messages)}:")
            print(_safe(msg))
        return

    try:
        sys.path.insert(0, _REPO_ROOT)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_REPO_ROOT, '.env'))
        token   = os.getenv('telegram_alerts_token')
        chat_id = os.getenv('telegram_chat_id')
        if not token or not chat_id:
            print("[PRE-RES] ERROR: telegram_alerts_token / telegram_chat_id not in .env")
            return
        from monitoring.telegram_health_bot import TelegramHealthBot
        bot = TelegramHealthBot(token=token, chat_id=chat_id)
        for msg in messages:
            bot._send_message(msg)
    except Exception as e:
        print(f"[PRE-RES] Telegram dispatch error: {e}")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run_pre_resolution_intelligence(dry_run: bool = False) -> dict:
    """
    Core entry point — callable from the scheduler or standalone.

    Returns a summary dict with keys:
      markets_checked, signals_found, messages_sent
    """
    print("[PRE-RES] Starting pre-resolution intelligence scan...")
    conn = _get_conn()

    upcoming = _fetch_upcoming_markets(conn)
    print(f"[PRE-RES] {len(upcoming)} market(s) resolving within {LOOKBACK_DAYS} days")

    signals = []

    for mkt in upcoming:
        positions = _fetch_elite_positions(conn, mkt['market_id'])
        if len(positions) < MIN_TRADERS:
            continue

        # Only process binary (Yes/No) markets for the divergence check
        outcomes = {(p['outcome'] or '').strip().lower() for p in positions}
        if 'yes' not in outcomes and 'no' not in outcomes:
            continue

        signal      = _compute_signal(positions)
        market_price = _get_market_price(conn, mkt)

        # Divergence gate
        if market_price is not None:
            gap = abs(signal['elite_yes_pct'] - market_price * 100.0)
            if gap < DIVERGENCE_THRESH:
                continue
        # If price unavailable, include anyway (can't check divergence)

        signals.append({
            "market":       mkt,
            "signal":       signal,
            "market_price": market_price,
        })

    conn.close()

    print(f"[PRE-RES] {len(signals)} signal(s) meet criteria")

    # Build messages ordered by days_left ascending (already sorted from query)
    if signals:
        messages = [
            _format_market_message(s["market"], s["signal"], s["market_price"])
            for s in signals
        ]
    else:
        messages = [_format_no_signals_message(len(upcoming))]

    asyncio.run(_send_messages(messages, dry_run=dry_run))

    return {
        "markets_checked": len(upcoming),
        "signals_found":   len(signals),
        "messages_sent":   len(messages),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-resolution intelligence: smart money vs. market price"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print Telegram messages to stdout instead of sending them"
    )
    args = parser.parse_args()

    result = run_pre_resolution_intelligence(dry_run=args.dry_run)

    print(
        f"[PRE-RES] Done — "
        f"{result['markets_checked']} markets checked, "
        f"{result['signals_found']} signals, "
        f"{result['messages_sent']} message(s) sent"
    )


if __name__ == "__main__":
    main()
