#!/usr/bin/env python3
"""
monitoring/price_history.py — CLOB token resolution + point-in-time price lookup.

Extracted from scripts/b2_price_history_probe.py (the diagnostic feasibility
probe for B1b-prices, 2026-07-17) — resolve_token_id() and
fetch_price_history_window() are unmodified from the probe. The probe itself
is left in place as the diagnostic tool; this module is the production path.

price_at() is new: a single point-in-time price lookup, built for B1b-prices
PIT reconstruction. It intentionally does NOT retain or cache full market
curves (that's what the probe's fetch_full_history()/analyze_history() are
for, and B1b never needs a whole curve — only the point before a given T).

Settled semantics (B1b-prices scoping, 2026-07-23):
  - Last-point-at-or-before T, never interpolated.
  - No point before T at all -> None (legitimate "not yet trading", not an
    error). Caller falls through to the trade-tape fallback per FABLE §4.3.
  - A stale last point (>staleness threshold before T) is returned WITH its
    staleness surfaced (staleness_hours), not silently dropped or silently
    used. The drop decision belongs to the caller, symmetric with the
    no-point case and consistent with FABLE §4.3's existing 6h staleness cap
    + dropped-bet accounting for the trade-tape fallback. A pricing utility
    should not make drop/keep decisions that belong in one place
    (centralized experiment-logic accounting) -- it surfaces the fact.
  - Token resolution failure -> None, same as no-point: distinguishable only
    in that no CLOB call was attempted. Never raises for an unresolvable
    token or a network error; those are caller-routable "no price" outcomes,
    not exceptions.

Interval cap: CLOB /prices-history enforces a flat ~15 calendar-day cap on
(endTs - startTs), independent of fidelity ("invalid filters: 'startTs' and
'endTs' interval is too long" beyond it) -- confirmed live 2026-07-23 across
fidelity=1..30. This is NOT the probe's chunk_days_for_fidelity() model
(points-budget that shrinks the window as fidelity gets finer) -- that model
was measured wrong; the real cap is flat. price_at() only ever requests a
single short window (lookback_hours, default well under 15 days) so it never
needs to chunk, but MAX_INTERVAL_DAYS is exposed so a lookback misconfigured
above the cap fails loudly (ValueError) rather than silently 400ing.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import requests

CLOB_BASE = 'https://clob.polymarket.com'
GAMMA_BASE = 'https://gamma-api.polymarket.com'

REQUEST_TIMEOUT = 20
RATE_LIMIT_SLEEP = 0.25

# Flat interval cap confirmed live 2026-07-23 (15 days OK, 16 days 400s),
# independent of fidelity. Not the probe's fidelity-scaled chunk_days model.
MAX_INTERVAL_DAYS = 15

# FABLE §4.3's existing staleness cap for the trade-tape fallback, applied
# here too for consistency (see module docstring). Advisory only -- price_at()
# surfaces staleness_hours, it does not enforce this threshold itself.
DEFAULT_STALENESS_CAP_HOURS = 6.0


def http_get(url, params):
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 and attempt == 0:
                time.sleep(5)
                continue
            return r
        except requests.RequestException:
            if attempt == 0:
                time.sleep(2)
                continue
            return None
    return None


def resolve_token_id(market):
    """Returns (yes_token_id, source, note). Unmodified from
    scripts/b2_price_history_probe.py. `market` is a dict-like with keys
    clob_token_id_yes, condition_id, market_id."""
    if market.get('clob_token_id_yes'):
        return market['clob_token_id_yes'], 'db', None

    lookup_id = market.get('condition_id') or market.get('market_id')
    if not lookup_id:
        return None, None, 'no condition_id or market_id to look up'
    if not market.get('condition_id') and not str(market.get('market_id', '')).startswith('0x'):
        return None, None, 'no condition_id and market_id is not a 0x hash'

    # Primary: CLOB exact-match
    r = http_get(f'{CLOB_BASE}/markets/{lookup_id}', None)
    if r is not None and r.status_code == 200:
        try:
            mkt = r.json()
            tokens = mkt.get('tokens', [])
            yes_token = next((t['token_id'] for t in tokens if t.get('outcome') == 'Yes'), None)
            if yes_token:
                return yes_token, 'clob', None
        except (ValueError, KeyError):
            pass

    # Fallback: Gamma, with conditionId match verification (Gamma silently
    # returns a default popular-market list for unrecognised IDs).
    r = http_get(f'{GAMMA_BASE}/markets', {'conditionIds': lookup_id})
    if r is None or r.status_code != 200:
        return None, None, f'gamma http {r.status_code if r is not None else "no-response"}'
    try:
        markets = r.json()
    except ValueError:
        return None, None, 'gamma non-json response'
    match = next((m for m in markets if m.get('conditionId', '').lower() == lookup_id.lower()), None)
    if not match:
        return None, None, 'gamma returned no matching conditionId'
    raw = match.get('clobTokenIds')
    if not raw:
        return None, None, 'gamma match has no clobTokenIds'
    token_ids = json.loads(raw) if isinstance(raw, str) else raw
    if not token_ids:
        return None, None, 'gamma clobTokenIds empty after parse'
    return token_ids[0], 'gamma', None


def fetch_price_history_window(token_id, start_dt, end_dt, fidelity):
    """Single CLOB call for one window. Returns (points, err).
    Unmodified from scripts/b2_price_history_probe.py."""
    r = http_get(f'{CLOB_BASE}/prices-history', {
        'market': token_id,
        'startTs': int(start_dt.timestamp()),
        'endTs': int(end_dt.timestamp()),
        'fidelity': fidelity,
    })
    if r is None:
        return None, 'no-response'
    if r.status_code != 200:
        return None, f'http {r.status_code}: {r.text[:120]}'
    try:
        body = r.json()
    except ValueError:
        return None, 'non-json response'
    history = body.get('history', body) if isinstance(body, dict) else body
    if not isinstance(history, list):
        return None, 'unexpected response shape'
    points = []
    for pt in history:
        t = pt.get('t', pt.get('timestamp'))
        p = pt.get('p', pt.get('price'))
        if t is not None and p is not None:
            points.append((int(t), float(p)))
    points.sort()
    return points, None


class PriceAtError(Exception):
    """Raised only for caller misconfiguration (e.g. lookback > interval
    cap) -- never for network failure or absence of data. Those return None."""


def price_at(token_id, T, lookback_hours=6.0, fidelity=1):
    """Point-in-time price lookup: last point at-or-before T.

    Returns (price, point_ts, staleness_hours) or None.
      - None means: no point exists at or before T within the lookback
        window (market hadn't started trading, or CLOB returned nothing).
      - staleness_hours = (T - point_ts) in hours, always >= 0. NOT enforced
        against DEFAULT_STALENESS_CAP_HOURS here -- surfaced for the caller
        to apply its own drop rule (FABLE §4.3 centralizes drop/keep
        decisions in the experiment logic, not in a pricing utility).

    Raises PriceAtError if lookback_hours would exceed the CLOB flat 15-day
    interval cap -- a caller misconfiguration, not a runtime data condition,
    so it must fail loudly rather than silently 400 against the API.
    """
    if lookback_hours > MAX_INTERVAL_DAYS * 24:
        raise PriceAtError(
            f'lookback_hours={lookback_hours} exceeds the CLOB flat '
            f'{MAX_INTERVAL_DAYS}-day interval cap ({MAX_INTERVAL_DAYS * 24}h). '
            f'Chunk the request yourself if you need a longer lookback.'
        )

    end_dt = T
    start_dt = T - timedelta(hours=lookback_hours)
    points, err = fetch_price_history_window(token_id, start_dt, end_dt, fidelity)
    if not points:
        return None

    T_epoch = int(T.timestamp())
    at_or_before = [p for p in points if p[0] <= T_epoch]
    if not at_or_before:
        return None

    point_ts, price = at_or_before[-1]
    staleness_hours = max(0.0, (T_epoch - point_ts) / 3600.0)
    point_dt = datetime.fromtimestamp(point_ts, tz=timezone.utc)
    return price, point_dt, staleness_hours
