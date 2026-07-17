#!/usr/bin/env python3
"""
b2_price_history_probe.py

B2 feasibility probe (see ~/trading-swarm/brain/decisions/2026-07-17-edge-proof-experiment-design-FABLE.md,
item B2): for a stratified sample of 50 resolved Geopolitics/Elections markets,
measure whether Polymarket's CLOB `prices-history` endpoint is a usable source of
historical entry prices, and how well the local trade tape covers the gap when it
isn't.

Read-only: only external GET requests (Gamma, CLOB) + a read-only SELECT against
the local DB (opened in `mode=ro`). No writes to data/polymarket_tracker.db.

Resumable / idempotent-ish: the sample and all per-market results are checkpointed
to logs/b2_price_history_probe_state.json after every market. Re-running loads the
checkpoint, keeps the same sample, and only re-fetches markets not yet marked done.
Worst case on interruption is a few repeated API calls for the in-flight market.

Usage:
  python3 scripts/b2_price_history_probe.py
"""

import sqlite3, requests, json, os, time, random, statistics
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data', 'polymarket_tracker.db')
STATE_PATH = os.path.join(ROOT, 'logs', 'b2_price_history_probe_state.json')

TRADING_SWARM_DECISIONS = os.path.expanduser('~/trading-swarm/brain/decisions')
RESULT_PATH = os.path.join(TRADING_SWARM_DECISIONS, '2026-07-17-b2-price-history-probe-result.md')
# Fallback if the trading-swarm checkout isn't present on this machine.
RESULT_PATH_FALLBACK = os.path.join(ROOT, 'logs', '2026-07-17-b2-price-history-probe-result.md')

CLOB_BASE = 'https://clob.polymarket.com'
GAMMA_BASE = 'https://gamma-api.polymarket.com'

SAMPLE_SIZE = 50
SEED = 20260717
RATE_LIMIT_SLEEP = 0.25
REQUEST_TIMEOUT = 20
TARGET_FIDELITY_MIN = 30  # the granularity §4.3 entry-timing needs

NOW = datetime.now(timezone.utc)
OLD_WINDOW_START = datetime(2025, 11, 1, tzinfo=timezone.utc)
OLD_WINDOW_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
RECENT_WINDOW_START = NOW - timedelta(days=60)


def log(msg):
    print(f'[{datetime.now(timezone.utc).isoformat(timespec="seconds")}] {msg}', flush=True)


# ---------------------------------------------------------------------------
# State (checkpoint) helpers
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {'sample': None, 'results': {}}


def save_state(state):
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_PATH)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def parse_ts(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None


def fetch_candidates():
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=30)
    cur = conn.cursor()
    cur.execute('''
        SELECT m.market_id, m.title, m.category, m.resolution_date, m.condition_id,
               m.clob_token_id_yes, m.clob_token_id_no,
               COALESCE(t.notional, 0) AS notional, COALESCE(t.trade_count, 0) AS trade_count,
               COALESCE(t.avg_shares, 0) AS avg_shares
        FROM markets m
        LEFT JOIN (
            SELECT market_id, SUM(shares * price) AS notional, COUNT(*) AS trade_count,
                   AVG(shares) AS avg_shares
            FROM trades GROUP BY market_id
        ) t ON t.market_id = m.market_id
        WHERE m.category IN ('Geopolitics', 'Elections')
          AND m.resolved = 1
          AND m.resolution_date IS NOT NULL
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    ''')
    rows = cur.fetchall()
    conn.close()

    # Sanity filter: a handful of market_ids carry implausible trade stats
    # (600k+ trades on one market, avg 200k+ shares/trade, several distinct
    # market_ids sharing byte-identical trade_count/avg_shares) that look like
    # synthetic/duplicated data rather than organic volume. Left in, these
    # would dominate the high-volume stratum and skew the sample. Excluded
    # from candidates; count is logged so it's visible, not silently dropped.
    candidates = []
    excluded_implausible = 0
    for market_id, title, category, resolution_date, condition_id, clob_yes, clob_no, notional, trade_count, avg_shares in rows:
        if avg_shares > 5000 or trade_count > 50000:
            excluded_implausible += 1
            continue
        rd = parse_ts(resolution_date)
        if rd is None:
            continue
        if OLD_WINDOW_START <= rd < OLD_WINDOW_END:
            age = 'old'
        elif rd >= RECENT_WINDOW_START:
            age = 'recent'
        else:
            continue
        candidates.append({
            'market_id': market_id, 'title': title, 'category': category,
            'resolution_date': resolution_date, 'condition_id': condition_id,
            'clob_token_id_yes': clob_yes, 'clob_token_id_no': clob_no,
            'notional': notional, 'trade_count': trade_count, 'age': age,
        })
    if excluded_implausible:
        log(f'Excluded {excluded_implausible} markets with implausible trade stats '
            f'(avg_shares>5000 or trade_count>50000) — likely synthetic/duplicated data.')
    return candidates


def build_sample(candidates):
    rnd = random.Random(SEED)
    strata = {}
    for age in ('old', 'recent'):
        bucket = [c for c in candidates if c['age'] == age]
        bucket.sort(key=lambda c: c['notional'])
        mid = len(bucket) // 2
        strata[(age, 'low_vol')] = bucket[:mid]
        strata[(age, 'high_vol')] = bucket[mid:]

    targets = {k: SAMPLE_SIZE // 4 for k in strata}
    # distribute the remainder deterministically
    for i, k in enumerate(strata):
        if i < SAMPLE_SIZE % 4:
            targets[k] += 1

    sample = []
    shortfall = 0
    picked_ids = set()
    for k, pool in strata.items():
        rnd.shuffle(pool)
        take = pool[:targets[k]]
        sample.extend(take)
        picked_ids.update(c['market_id'] for c in take)
        if len(take) < targets[k]:
            shortfall += targets[k] - len(take)

    # backfill shortfall from any remaining candidates not already picked
    if shortfall > 0:
        remaining = [c for c in candidates if c['market_id'] not in picked_ids]
        rnd.shuffle(remaining)
        sample.extend(remaining[:shortfall])

    return sample[:SAMPLE_SIZE]


# ---------------------------------------------------------------------------
# External API calls
# ---------------------------------------------------------------------------

def http_get(url, params):
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429 and attempt == 0:
                time.sleep(5)
                continue
            return r
        except requests.RequestException as e:
            if attempt == 0:
                time.sleep(2)
                continue
            return None
    return None


def resolve_token_id(market):
    """Returns (yes_token_id, source, note)."""
    if market['clob_token_id_yes']:
        return market['clob_token_id_yes'], 'db', None

    lookup_id = market['condition_id'] if market['condition_id'] else market['market_id']
    if not lookup_id:
        return None, None, 'no condition_id or market_id to look up'
    if not market['condition_id'] and not str(market['market_id']).startswith('0x'):
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


# CLOB caps prices-history responses at roughly 700-750 points per call
# (discovered empirically: 15 days @ fidelity=30 works, 16 days 400s with
# "interval is too long"). `interval=max`/`1m`/etc. are relative-to-NOW
# windows and return empty for anything already resolved/delisted — the
# endpoint requires explicit startTs/endTs for historical, resolved markets.
POINT_BUDGET = 700
MAX_CHUNKS_PER_MARKET = 8


def chunk_days_for_fidelity(fidelity):
    return max(1, int(POINT_BUDGET * fidelity / 1440))


def fetch_price_history_window(token_id, start_dt, end_dt, fidelity):
    """Single CLOB call for one window. Returns (points, err)."""
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
    return points, None


def probe_fidelity(token_id, anchor_start, anchor_end):
    """Try the most-recent chunk_days-sized window at successively coarser
    fidelities until one returns data. Returns (fidelity_or_None, tried)."""
    tried = []
    for fid in (TARGET_FIDELITY_MIN, 60, 1440):
        chunk_days = chunk_days_for_fidelity(fid)
        win_start = max(anchor_start, anchor_end - timedelta(days=chunk_days))
        points, err = fetch_price_history_window(token_id, win_start, anchor_end, fid)
        time.sleep(RATE_LIMIT_SLEEP)
        tried.append({'fidelity': fid, 'point_count': len(points) if points else 0, 'error': err})
        if points:
            return fid, tried
    return None, tried


def fetch_full_history(token_id, anchor_start, anchor_end, fidelity):
    """Walk backward from anchor_end to anchor_start in chunk_days-sized
    windows, up to MAX_CHUNKS_PER_MARKET calls, concatenating points."""
    chunk_days = chunk_days_for_fidelity(fidelity)
    all_points = []
    cur_end = anchor_end
    chunks_used = 0
    capped = False
    while cur_end > anchor_start and chunks_used < MAX_CHUNKS_PER_MARKET:
        cur_start = max(anchor_start, cur_end - timedelta(days=chunk_days))
        points, err = fetch_price_history_window(token_id, cur_start, cur_end, fidelity)
        time.sleep(RATE_LIMIT_SLEEP)
        chunks_used += 1
        if points:
            all_points.extend(points)
        cur_end = cur_start
        if cur_end > anchor_start and chunks_used >= MAX_CHUNKS_PER_MARKET:
            capped = True
    dedup = sorted(set(all_points))
    return dedup, chunks_used, capped


def analyze_history(points, anchor_start, anchor_end, capped):
    if not points:
        return {'retained': False, 'point_count': 0}
    ts = [p[0] for p in points]
    gaps_min = [(ts[i + 1] - ts[i]) / 60.0 for i in range(len(ts) - 1)]
    median_gap = statistics.median(gaps_min) if gaps_min else None
    span_days = (ts[-1] - ts[0]) / 86400.0
    first_point_dt = datetime.fromtimestamp(ts[0], tz=timezone.utc)
    last_point_dt = datetime.fromtimestamp(ts[-1], tz=timezone.utc)
    # "full coverage" = data reaches back near the anchor window's start and
    # forward near its end (anchor window = our own locally-observed active
    # trading span for this market, not the DB's resolution_date — see
    # anchor_source in the caller; resolution_date proved unreliable for at
    # least one spot-checked market).
    coverage_full = (not capped
                      and abs((first_point_dt - anchor_start).total_seconds()) <= 2 * 86400
                      and abs((anchor_end - last_point_dt).total_seconds()) <= 2 * 86400)
    return {
        'retained': True,
        'point_count': len(points),
        'median_gap_minutes': round(median_gap, 1) if median_gap is not None else None,
        'span_days': round(span_days, 2),
        'first_point': ts[0], 'last_point': ts[-1],
        'coverage_full_to_anchor_window': coverage_full,
        'chunks_capped': capped,
    }


def local_trades(market_id):
    """Read-only local trade tape for a market: list of (datetime, price), sorted."""
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=30)
    cur = conn.cursor()
    cur.execute('SELECT timestamp, price FROM trades WHERE market_id = ? ORDER BY timestamp', (market_id,))
    rows = cur.fetchall()
    conn.close()
    trades = []
    for ts_str, price in rows:
        dt = parse_ts(ts_str)
        if dt is not None and price is not None:
            trades.append((dt, price))
    trades.sort()
    return trades


def trade_tape_fallback(trades):
    """§4.3's fallback rule: nearest trade within 6h of a target timestamp."""
    if not trades:
        return {'has_trades': False, 'trade_count': 0}
    span_days = (trades[-1][0] - trades[0][0]).total_seconds() / 86400.0

    # Sample up to 5 evenly-spaced target timestamps across the market's local
    # trade span and check the §4.3 "trade within 6h" rule at each.
    n_checks = min(5, len(trades))
    hits = 0
    for i in range(n_checks):
        frac = i / max(1, n_checks - 1) if n_checks > 1 else 0
        idx = int(frac * (len(trades) - 1))
        target = trades[idx][0]
        within_6h = any(abs((t[0] - target).total_seconds()) <= 6 * 3600 for t in trades)
        if within_6h:
            hits += 1

    return {
        'has_trades': True,
        'trade_count': len(trades),
        'span_days': round(span_days, 2),
        'checks_within_6h': f'{hits}/{n_checks}',
    }


# ---------------------------------------------------------------------------
# Per-market processing
# ---------------------------------------------------------------------------

def determine_anchor_window(trades, resolution_dt):
    """Prefer the market's own locally-observed trade span as the window to
    query CLOB over — resolution_date in the DB was spot-checked against a
    real market (NYC mayoral, 2025) and found stale by ~7 months, so it's not
    trustworthy as a query anchor on its own."""
    if trades:
        start = trades[0][0] - timedelta(hours=6)
        end = trades[-1][0] + timedelta(hours=6)
        return start, end, 'local_trades'
    if resolution_dt:
        return resolution_dt - timedelta(days=30), resolution_dt, 'resolution_date_fallback'
    return None, None, 'no_anchor'


def process_market(market):
    result = {
        'market_id': market['market_id'], 'title': market['title'],
        'category': market['category'], 'age': market['age'],
        'notional': market['notional'], 'resolution_date': market['resolution_date'],
    }

    trades = local_trades(market['market_id'])
    resolution_dt = parse_ts(market['resolution_date'])
    anchor_start, anchor_end, anchor_source = determine_anchor_window(trades, resolution_dt)
    result['anchor_source'] = anchor_source

    token_id, source, note = resolve_token_id(market)
    time.sleep(RATE_LIMIT_SLEEP)
    result['token_resolved'] = token_id is not None
    result['token_source'] = source
    if not token_id or anchor_start is None:
        if not token_id:
            result['token_resolve_note'] = note
        else:
            result['token_resolve_note'] = 'no anchor window (no local trades, no resolution_date)'
        result['clob'] = {'retained': False, 'point_count': 0}
        result['trade_tape'] = trade_tape_fallback(trades)
        result['status'] = 'done'
        return result

    fid, probe_tried = probe_fidelity(token_id, anchor_start, anchor_end)
    result['fidelity_probe'] = probe_tried

    if fid is None:
        result['clob'] = {'retained': False, 'point_count': 0}
        result['trade_tape'] = trade_tape_fallback(trades)
        result['status'] = 'done'
        return result

    points, chunks_used, capped = fetch_full_history(token_id, anchor_start, anchor_end, fid)
    analysis = analyze_history(points, anchor_start, anchor_end, capped)
    analysis['fidelity_used_minutes'] = fid
    analysis['chunks_used'] = chunks_used
    result['clob'] = analysis

    if not analysis['retained']:
        result['trade_tape'] = trade_tape_fallback(trades)
    else:
        result['trade_tape'] = None  # not needed, CLOB served this market

    result['status'] = 'done'
    return result


# ---------------------------------------------------------------------------
# Result report
# ---------------------------------------------------------------------------

def result_path():
    if os.path.isdir(TRADING_SWARM_DECISIONS):
        return RESULT_PATH
    return RESULT_PATH_FALLBACK


def write_report(state, final=False):
    results = [r for r in state['results'].values() if r.get('status') == 'done']
    total = len(state['sample'])
    done = len(results)

    resolved = [r for r in results if r['token_resolved']]
    clob_ok = [r for r in resolved if r['clob']['retained']]
    clob_fail = [r for r in resolved if not r['clob']['retained']]
    unresolved = [r for r in results if not r['token_resolved']]

    def rate(n, d):
        return f'{n}/{d} ({100 * n / d:.0f}%)' if d else 'n/a'

    lines = []
    lines.append('# B2 Price-History Probe — Result')
    lines.append('')
    lines.append(f'Status: {"FINAL" if final else "IN PROGRESS"} ({done}/{total} markets processed)')
    lines.append(f'Generated: {datetime.now(timezone.utc).isoformat(timespec="seconds")}')
    lines.append('')
    lines.append('Probe of item B2 from `2026-07-17-edge-proof-experiment-design-FABLE.md`: '
                  'does CLOB `prices-history` retain usable ~30min-granularity data for resolved '
                  'geo/elec markets, and how well does the local trade tape cover the gap when it '
                  'doesn\'t. Read-only against production DB; no writes.')
    lines.append('')

    lines.append('## Sample composition')
    lines.append('')
    lines.append(f'- Target: {SAMPLE_SIZE}, sampled: {total}')
    for age in ('old', 'recent'):
        n_age = sum(1 for c in state['sample'] if c['age'] == age)
        lines.append(f'  - {age}: {n_age} markets')
    lines.append(f'- Age windows: old = 2025-11-01..2026-01-01, recent = last 60 days (>= {RECENT_WINDOW_START.date()})')
    lines.append(f'- Volume tiers: notional (sum shares*price from local trades) split at the median within each age bucket')
    lines.append('')

    lines.append('## Funnel')
    lines.append('')
    lines.append(f'- clobTokenId resolved: {rate(len(resolved), done)}')
    lines.append(f'- CLOB prices-history retained data (of resolved): {rate(len(clob_ok), len(resolved))}')
    lines.append(f'- CLOB prices-history empty/failed (of resolved): {rate(len(clob_fail), len(resolved))}')
    lines.append(f'- Token not resolved at all: {rate(len(unresolved), done)}')
    lines.append('')

    if clob_ok:
        gaps = [r['clob']['median_gap_minutes'] for r in clob_ok if r['clob'].get('median_gap_minutes') is not None]
        full_cov = [r for r in clob_ok if r['clob'].get('coverage_full_to_anchor_window')]
        lines.append('## Granularity & coverage (CLOB-retained markets)')
        lines.append('')
        if gaps:
            lines.append(f'- Median observed gap between points: {statistics.median(gaps):.1f} min '
                          f'(target was {TARGET_FIDELITY_MIN} min)')
            n_fine = sum(1 for g in gaps if g <= TARGET_FIDELITY_MIN + 5)
            n_hour = sum(1 for g in gaps if TARGET_FIDELITY_MIN + 5 < g <= 65)
            n_coarse = sum(1 for g in gaps if g > 65)
            lines.append(f'  - <= ~30min: {n_fine}/{len(gaps)}, ~hourly: {n_hour}/{len(gaps)}, coarser: {n_coarse}/{len(gaps)}')
        lines.append(f'- Coverage full to resolution (last point within 24h of resolution_date): {rate(len(full_cov), len(clob_ok))}')
        lines.append('')

    lines.append('## Age degradation (old Nov-Dec 2025 vs recent)')
    lines.append('')
    for age in ('recent', 'old'):
        age_resolved = [r for r in resolved if r['age'] == age]
        age_ok = [r for r in age_resolved if r['clob']['retained']]
        lines.append(f'- {age}: token resolved {len(age_resolved)}, CLOB retained {rate(len(age_ok), len(age_resolved))}')
    lines.append('')

    if clob_fail:
        with_fallback = [r for r in clob_fail if r['trade_tape'] and r['trade_tape'].get('has_trades')]
        lines.append('## Trade-tape fallback (markets where CLOB failed)')
        lines.append('')
        lines.append(f'- Local trades available: {rate(len(with_fallback), len(clob_fail))}')
        if with_fallback:
            checks = []
            for r in with_fallback:
                hit, n = r['trade_tape']['checks_within_6h'].split('/')
                checks.append((int(hit), int(n)))
            total_hit = sum(h for h, _ in checks)
            total_n = sum(n for _, n in checks)
            lines.append(f'- Sampled-timestamp 6h-window hit rate: {rate(total_hit, total_n)}')
        lines.append('')

    if final:
        lines.append('## Verdict')
        lines.append('')
        clob_retention_rate = len(clob_ok) / len(resolved) if resolved else 0
        if clob_retention_rate >= 0.8:
            lines.append('CLOB `prices-history` retains data for the large majority of resolved geo/elec '
                          'markets in this sample. It can serve as the **primary** entry-price source per '
                          '§4.3; the trade-tape path stays a fallback as designed. Check the age-degradation '
                          'and granularity numbers above before finalizing — if either strata or granularity '
                          'skew badly, narrow the design\'s claim accordingly.')
        elif clob_retention_rate >= 0.4:
            lines.append('CLOB `prices-history` retention is partial/mixed. The design should treat CLOB as '
                          'primary-with-fallback rather than assuming near-universal coverage — expect a '
                          'meaningful share of bets to fall back to the trade tape or be dropped for staleness. '
                          'Revisit the dropped-bet accounting in the experiment design before running Phase 1.')
        else:
            lines.append('CLOB `prices-history` retention is low. Per the design doc\'s own framing '
                          '("if retention fails, the trade-tape fallback becomes primary and uncertainty '
                          'widens"), the trade-tape path should be promoted to primary and the experiment\'s '
                          'entry-pricing uncertainty should be widened accordingly before Phase 1 proceeds.')
        lines.append('')

    lines.append('## Raw per-market results')
    lines.append('')
    lines.append('See `logs/b2_price_history_probe_state.json` (first-repo) for full per-market detail.')
    lines.append('')

    path = result_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write('\n'.join(lines))
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state = load_state()

    if state['sample'] is None:
        log('No checkpoint found — building fresh stratified sample.')
        candidates = fetch_candidates()
        log(f'Candidate pool: {len(candidates)} resolved geo/elec markets in old/recent windows.')
        sample = build_sample(candidates)
        state['sample'] = sample
        save_state(state)
        log(f'Sample built: {len(sample)} markets. Checkpointed to {STATE_PATH}.')
    else:
        log(f'Resuming from checkpoint: {len(state["sample"])} sampled, '
            f'{len(state["results"])} already processed.')

    total = len(state['sample'])
    for i, market in enumerate(state['sample'], start=1):
        mid = market['market_id']
        if state['results'].get(mid, {}).get('status') == 'done':
            continue
        log(f'[{i}/{total}] processing {mid} ({market["age"]}, notional={market["notional"]:.0f}) — {market["title"][:60]}')
        try:
            result = process_market(market)
        except Exception as e:
            log(f'  ERROR processing {mid}: {e} — will retry on next run')
            continue
        state['results'][mid] = result
        save_state(state)
        if i % 5 == 0:
            path = write_report(state, final=False)
            log(f'  progress report written to {path}')

    path = write_report(state, final=True)
    log(f'DONE. Final report written to {path}')


if __name__ == '__main__':
    main()
