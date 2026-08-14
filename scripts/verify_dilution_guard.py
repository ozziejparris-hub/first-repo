#!/usr/bin/env python3
"""
Verify §4.2's LP-dilution guard (|net|/gross >= 0.7) under multiple readings
of "capital split," and persist the resulting signal set as a reproducible,
machine-readable artifact.

Background: an earlier full-population pass (2026-08-14, not persisted)
found the guard removes ~96% of raw consensus formations on its own
(268 -> 10), and that count alone determines the multi-year duration
estimate to reach the design's n=60/40-cluster target. This script
independently re-derives that number under three explicit readings of
"capital split," so the guard's bite is no longer resting on one
unreproducible interpretation.

§4.2 literal text (FABLE design doc, 2026-07-17, quoted verbatim):

    "Cohort positions at T: for each cohort member (§4.1), net open
    exposure in M = Yes-capital - No-capital across positions entered
    <= T (per knowability rules) and not exited by T. Members whose
    per-market capital split is near-balanced (|net|/(gross) < 0.7)
    are excluded from this market -- LP/market-making behavior,
    STR-002's dilution source."

The phrase "not exited by T" scopes the underlying position set for
"net open exposure" to positions still open at T. This script treats
that as the textually literal reading (READING_OPEN) and additionally
computes two alternate readings the text does not literally support,
so the sensitivity can be reported honestly:

  READING_OPEN      net/gross computed over capital in positions still
                     open (status in open/partially_closed) at T. The
                     literal spec reading.
  READING_TOTAL      net/gross computed over ALL capital ever entered
                     by T (entry_shares * entry_avg_price), regardless
                     of whether later exited. NOT what the text says --
                     included only as the alternate reading under test.
  READING_DIRECTION  floor case: any nonzero net open exposure counts
                     as a directional vote, no magnitude threshold at
                     all (guard effectively off, still requires a real
                     side).

Position reconstruction reuses analysis/pit_positions.reconstruct_one_at
(validated at 1.2M-row scale against the live positions table) and tier
reconstruction reuses analysis/pit_geo_elo.reconstruct_one_at (validated
against the 30 recorded elo_snapshots dates) -- this script does not
reimplement FIFO matching or the geo_elo fold, only the candidate-market
discovery, change-point walk, guard-reading comparison, and the funnel
filters (price band, liquidity floor, one-bet-per-cluster).

Price proxy: outcome-normalized trade-tape last-trade-at-or-before-T
(NOT CLOB price_at() -- time-boxed out of this pass, same gap the prior
run also carried; see the persisted artifact's `price_source` field).

Read-only against the database. Writes only to the artifact table named
by --artifact-table (default: dilution_guard_signals) and, if asked,
stdout/JSON report. No production table is ever modified.
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.pit_geo_elo import (
    reconstruct_one_at as geo_elo_at,
    _ensure_tape_end_temp_table,
    _last_any_trade_at,
    _compute_geo_elo_active_at,
    _pool_c_gate,
)
from analysis.pit_positions import (
    reconstruct_one_at as positions_at,
    _TRACKER,
    _apply_synthetic_closes_at,
)
from scripts.update_geo_elo import _compute_geo_elo, _compute_geo_directionality, MIN_TRADES_FOR_ELO

SPEC_VERSION = "FABLE-2026-07-17-sec4.2"
GEO_ELO_LEGENDARY = 2175.0
CONTESTED_BAND = (0.10, 0.90)
LIQUIDITY_FLOOR_TRADES_7D = 20
GUARD_THRESHOLD = 0.7

READINGS = ("open", "total", "direction")


def db_connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def candidate_cohort(conn, tier_threshold=GEO_ELO_LEGENDARY):
    """Screen: traders whose undecayed geo_elo ever reached tier_threshold,
    current table or any historical snapshot. Over-inclusive by design --
    exact PIT gating happens per (trader, T) via pit_geo_elo."""
    rows = conn.execute(f"""
        SELECT DISTINCT address FROM (
            SELECT address FROM traders WHERE geo_elo >= {tier_threshold}
            UNION
            SELECT address FROM elo_snapshots WHERE geo_elo >= {tier_threshold}
        )
    """).fetchall()
    return {r[0] for r in rows}


def candidate_markets(conn, cohort):
    placeholders = ",".join("?" for _ in cohort)
    rows = conn.execute(f"""
        SELECT t.market_id, COUNT(DISTINCT t.trader_address) AS n
        FROM trades t
        JOIN markets m ON m.market_id = t.market_id
        WHERE t.trader_address IN ({placeholders})
          AND m.category IN ('Geopolitics', 'Elections')
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
        GROUP BY t.market_id
        HAVING n >= 2
    """, tuple(cohort)).fetchall()
    return [r[0] for r in rows]


def market_change_points(conn, market_id, cohort):
    placeholders = ",".join("?" for _ in cohort)
    rows = conn.execute(f"""
        SELECT DISTINCT trader_address, timestamp
        FROM trades
        WHERE market_id = ? AND trader_address IN ({placeholders})
        ORDER BY timestamp ASC
    """, (market_id, *cohort)).fetchall()
    return rows  # list of (trader, ts) in chronological order


class TierTimeline:
    """
    Per-trader precomputed step function of (undecayed geo_elo, resolved_count,
    directionality) over the thresholds at which the qualifying-trade set
    changes (i.e. each distinct market tape_end among that trader's qualifying
    trades). Built ONCE per trader instead of re-fetching + re-folding the
    full qualifying-trade list at every change point that trader is a voter
    candidate for -- pit_geo_elo.reconstruct_one_at's own per-call cost is
    dominated by re-querying trades on every call, which becomes O(markets *
    change_points * traders) if used naively across a 1000+-market sweep.

    Decay (T-dependent, continuous) is deliberately NOT baked into the
    timeline -- it's applied at query time via the same
    _compute_geo_elo_active_at + _last_any_trade_at pair pit_geo_elo.py uses,
    both of which are already cheap indexed lookups, not re-folds.

    Cross-checked against analysis.pit_geo_elo.reconstruct_one_at directly
    (see --selfcheck) rather than trusted blind.
    """

    def __init__(self, conn, trader):
        self.conn = conn
        self.trader = trader
        _ensure_tape_end_temp_table(conn)
        rows = conn.execute("""
            SELECT tr.outcome_bet, tr.price, tr.trade_result, tr.market_id,
                   tr.shares, tr.timestamp, tape.tape_end
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            JOIN tape_end tape ON tape.market_id = tr.market_id
            WHERE tr.trader_address = ?
              AND m.category IN ('Geopolitics', 'Elections')
              AND tr.trade_result IN ('won', 'lost')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
              AND tr.price BETWEEN 0.10 AND 0.80
            ORDER BY tr.timestamp ASC
        """, (trader,)).fetchall()

        # canonical_count mirrors _canonical_count_at exactly: distinct
        # resolved geo/elec market_id count, deliberately WITHOUT the
        # price-band restriction the ELO-fold input uses (that's a real
        # divergence in the production query pit_geo_elo.py replicates
        # faithfully, not a bug to "fix" here).
        count_rows = conn.execute("""
            SELECT DISTINCT tr.market_id, tape.tape_end
            FROM trades tr
            JOIN markets m ON m.market_id = tr.market_id
            JOIN tape_end tape ON tape.market_id = tr.market_id
            WHERE tr.trader_address = ?
              AND tr.trade_result IN ('won', 'lost')
              AND m.category IN ('Geopolitics', 'Elections')
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
        """, (trader,)).fetchall()

        thresholds = sorted({r[6] for r in rows} | {r[1] for r in count_rows})
        self.thresholds = thresholds
        self.geo_elo_by_threshold = []      # parallel arrays, index-aligned to thresholds
        self.resolved_count_by_threshold = []
        self.directionality_by_threshold = []
        for th in thresholds:
            included = [r for r in rows if r[6] <= th]  # already timestamp-sorted
            fold_rows = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in included]
            n = len(fold_rows)
            if n < MIN_TRADES_FOR_ELO:
                self.geo_elo_by_threshold.append(None)
                self.directionality_by_threshold.append(None)
            else:
                self.geo_elo_by_threshold.append(_compute_geo_elo(fold_rows))
                self.directionality_by_threshold.append(_compute_geo_directionality(fold_rows))
            self.resolved_count_by_threshold.append(
                len({mid for mid, te in count_rows if te <= th})
            )

        bot_row = conn.execute(
            "SELECT bot_type, wash_trade_suspect, bot_suspect FROM traders WHERE address = ?",
            (trader,)
        ).fetchone()
        self.bot_type, self.wash_trade_suspect, self.bot_suspect = bot_row if bot_row else (None, None, None)

    def state_at(self, t_dt):
        t_sql = t_dt.strftime('%Y-%m-%d %H:%M:%S')
        idx = None
        for i, th in enumerate(self.thresholds):
            if th <= t_sql:
                idx = i
            else:
                break
        if idx is None:
            geo_elo = None
            resolved_count = 0
            directionality = None
        else:
            geo_elo = self.geo_elo_by_threshold[idx]
            resolved_count = self.resolved_count_by_threshold[idx]
            directionality = self.directionality_by_threshold[idx]

        last_any_trade = _last_any_trade_at(self.conn, self.trader, t_sql)
        geo_elo_active = _compute_geo_elo_active_at(geo_elo, last_any_trade, t_dt)
        pool_c = _pool_c_gate(
            geo_elo, geo_elo_active, resolved_count, directionality,
            self.bot_type, self.wash_trade_suspect, self.bot_suspect
        )
        return {
            'geo_elo': geo_elo,
            'geo_elo_active': geo_elo_active,
            'geo_accuracy_pool': 1 if pool_c else 0,
            'geo_resolved_trades_count': resolved_count,
        }


def is_legendary_at(timeline, t_dt, traders_today, trader, tier_threshold=GEO_ELO_LEGENDARY):
    state = timeline.state_at(t_dt)
    today = traders_today.get(trader, {})
    if state['geo_elo_active'] is None:
        return False
    if state['geo_elo_active'] < tier_threshold:
        return False
    if state['geo_accuracy_pool'] != 1:
        return False
    if today.get('research_excluded'):
        return False
    if today.get('bot_type') is not None:
        return False
    return True


def _fetch_trader_market_trades(conn, trader, market_id, first_seen_dt):
    """
    Fetch ALL of one trader's trades in one market, bounded only by the
    §4.1 knowability lower bound (timestamp >= trader.first_seen) -- NOT by
    T. Called once per (trader, market) pair and cached by the caller, since
    the trade list itself is T-invariant; only how much of its PREFIX is
    visible at a given T changes. Re-querying this per change point (the
    naive approach) re-scans the market's full trade history on every call
    via the market_id index -- expensive for heavily-traded markets when
    called at every change point for every candidate voter.
    """
    lower = first_seen_dt.strftime('%Y-%m-%d %H:%M:%S') if first_seen_dt else '0001-01-01'
    rows = conn.execute("""
        SELECT trade_id, outcome, shares, price, side, timestamp
        FROM trades
        WHERE trader_address = ? AND market_id = ? AND timestamp >= ?
        ORDER BY timestamp ASC
    """, (trader, market_id, lower)).fetchall()
    out = []
    for trade_id, outcome, shares, price, side, timestamp in rows:
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)  # naive, matches pit_positions.py's own convention
        out.append({
            'trade_id': trade_id, 'market_title': None, 'outcome': outcome,
            'shares': shares, 'price': price, 'side': side, 'timestamp': timestamp,
        })
    return out


def knowable_positions_at(conn, trader, market_id, t_dt, full_trades):
    """
    Position reconstruction restricted to the §4.1 knowability rule: the
    SIGNAL side may only use trades we would have observed by T, i.e.
    timestamp >= trader.first_seen (discovery, already applied in
    full_trades) AND timestamp <= T. Backfilled pre-discovery trades are
    legitimate for ELO/tier *qualification* (see TierTimeline, which
    deliberately does NOT apply this bound) but must never inform what
    position the cohort appeared to hold at T -- using them would be a
    look-ahead the live system could not have had.

    pit_positions.reconstruct_one_at has no first_seen bound (out of its
    scope by design -- see its own docstring on division of labor), so this
    reuses its validated matching primitives (_TRACKER._match_group,
    _apply_synthetic_closes_at) directly against a knowability-bounded,
    T-sliced trade list instead of calling it and trusting an unbounded
    result.
    """
    t_sql = t_dt.strftime('%Y-%m-%d %H:%M:%S')
    t_naive = t_dt.replace(tzinfo=None)
    grouped = defaultdict(list)
    for tr in full_trades:
        if tr['timestamp'] > t_naive:
            break  # full_trades is timestamp-sorted; nothing further qualifies
        grouped[tr['outcome']].append(tr)

    positions = []
    for outcome, trades in grouped.items():
        positions.extend(_TRACKER._match_group(trader, market_id, outcome, trades))

    _apply_synthetic_closes_at(positions, conn, t_sql)
    return positions


def exposure_readings(conn, trader, market_id, t_dt, full_trades):
    """Returns (yes_open, no_open, yes_total, no_total) capital sums for one
    trader in one market as of T, knowability-bounded (see
    knowable_positions_at). full_trades: this (trader, market) pair's trades,
    already first_seen-bounded and timestamp-sorted (see
    _fetch_trader_market_trades) -- fetched once and reused across every T
    this pair is evaluated at."""
    positions = knowable_positions_at(conn, trader, market_id, t_dt, full_trades)
    yes_open = no_open = yes_total = no_total = 0.0
    for p in positions:
        outcome = (p.outcome or '').strip().lower()
        entry_total = (p.entry_shares or 0.0) * (p.entry_avg_price or 0.0)
        open_capital = (p.remaining_shares or 0.0) * (p.entry_avg_price or 0.0)
        if outcome == 'yes':
            yes_total += entry_total
            yes_open += open_capital
        elif outcome == 'no':
            no_total += entry_total
            no_open += open_capital
    return yes_open, no_open, yes_total, no_total


def side_under_reading(yes_open, no_open, yes_total, no_total, reading):
    if reading == "open":
        net, gross = yes_open - no_open, yes_open + no_open
        if gross <= 0:
            return None
        if abs(net) / gross < GUARD_THRESHOLD:
            return None
        return 'Yes' if net > 0 else 'No'
    if reading == "total":
        net, gross = yes_total - no_total, yes_total + no_total
        if gross <= 0:
            return None
        if abs(net) / gross < GUARD_THRESHOLD:
            return None
        return 'Yes' if net > 0 else 'No'
    if reading == "direction":
        net = yes_open - no_open
        if net == 0:
            return None
        return 'Yes' if net > 0 else 'No'
    raise ValueError(reading)


def consensus(sides, min_voters=2):
    """sides: dict trader -> 'Yes'/'No'/None (voters only, None already filtered)."""
    if not sides:
        return None
    counts = defaultdict(int)
    for s in sides.values():
        counts[s] += 1
    total = sum(counts.values())
    if total < min_voters:
        return None
    for side, n in counts.items():
        if n / total >= (2.0 / 3.0):
            return side, total, n
    return None


def price_at_trade_tape(conn, market_id, t_dt):
    """Outcome-normalized last-trade-at-or-before-T price proxy. Not CLOB --
    flagged in the persisted artifact's price_source field."""
    t_sql = t_dt.strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute("""
        SELECT outcome_bet, price FROM trades
        WHERE market_id = ? AND timestamp <= ? AND price IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, (market_id, t_sql)).fetchone()
    if not row:
        return None
    outcome_bet, price = row
    if outcome_bet == 'Yes':
        return price
    if outcome_bet == 'No':
        return 1.0 - price
    return None


def liquidity_7d(conn, market_id, t_dt):
    t_sql = t_dt.strftime('%Y-%m-%d %H:%M:%S')
    from datetime import timedelta
    start = (t_dt - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    row = conn.execute("""
        SELECT COUNT(*) FROM trades
        WHERE market_id = ? AND timestamp <= ? AND timestamp >= ?
    """, (market_id, t_sql, start)).fetchone()
    return row[0] if row else 0


def parse_ts(ts):
    if isinstance(ts, datetime):
        return ts
    s = str(ts).replace('Z', '+00:00').replace(' ', 'T')
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def run(conn, verbose=False, collect_diffs=False, tier_threshold=GEO_ELO_LEGENDARY,
        min_voters=2, liquidity_floor=LIQUIDITY_FLOOR_TRADES_7D):
    cohort = candidate_cohort(conn, tier_threshold)
    markets = candidate_markets(conn, cohort)
    traders_today = {
        r[0]: {'research_excluded': r[1], 'bot_type': r[2]}
        for r in conn.execute(
            "SELECT address, research_excluded, bot_type FROM traders"
        ).fetchall()
    }
    first_seen_by_trader = {}
    for addr, fs in conn.execute("SELECT address, first_seen FROM traders").fetchall():
        first_seen_by_trader[addr] = parse_ts(fs) if fs else None

    # cluster_id per market_id, from the committed B5 labels (most recent snapshot)
    cluster_rows = conn.execute("""
        SELECT market_id, cluster_id FROM event_cluster_labels
        WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM event_cluster_labels)
    """).fetchall()
    cluster_of = {mid: cid for mid, cid in cluster_rows}

    raw_formations = {r: [] for r in READINGS}       # reading -> list of dicts (pre-filter)
    fired = {r: set() for r in READINGS}              # reading -> set of market_id already fired
    guard_diffs = []  # (trader, market_id, T) where open-reading excludes but total/direction admits

    if verbose:
        print(f"[cohort] {len(cohort)} candidate traders", file=sys.stderr)
        print(f"[markets] {len(markets)} candidate markets", file=sys.stderr)

    t0 = datetime.now()
    timelines = {tr: TierTimeline(conn, tr) for tr in cohort}
    if verbose:
        print(f"[timelines] built {len(timelines)} in {(datetime.now()-t0).total_seconds():.1f}s", file=sys.stderr)

    for i, market_id in enumerate(markets):
        if verbose and i % 100 == 0:
            print(f"[progress] {i}/{len(markets)} markets", file=sys.stderr)

        cps = market_change_points(conn, market_id, cohort)
        if not cps:
            continue
        traders_seen = set()
        trade_cache = {}  # trader -> full_trades list for this market, fetched once
        # walk change points chronologically; stop tracking a reading once fired
        for trader, ts in cps:
            traders_seen.add(trader)
            if all(market_id in fired[r] for r in READINGS):
                break
            t_dt = parse_ts(ts)

            sides = {r: {} for r in READINGS}
            for tr in traders_seen:
                if not is_legendary_at(timelines[tr], t_dt, traders_today, tr, tier_threshold):
                    continue
                if tr not in trade_cache:
                    trade_cache[tr] = _fetch_trader_market_trades(
                        conn, tr, market_id, first_seen_by_trader.get(tr))
                yo, no_, yt, nt = exposure_readings(conn, tr, market_id, t_dt, trade_cache[tr])
                for r in READINGS:
                    s = side_under_reading(yo, no_, yt, nt, r)
                    if s is not None:
                        sides[r][tr] = s
                if collect_diffs:
                    open_side = side_under_reading(yo, no_, yt, nt, 'open')
                    total_side = side_under_reading(yo, no_, yt, nt, 'total')
                    if open_side is None and total_side is not None:
                        guard_diffs.append({
                            'trader': tr, 'market_id': market_id,
                            'formation_ts': t_dt.isoformat(),
                            'yes_open': yo, 'no_open': no_, 'yes_total': yt, 'no_total': nt,
                            'total_side': total_side,
                        })

            for r in READINGS:
                if market_id in fired[r]:
                    continue
                result = consensus(sides[r], min_voters)
                if result is None:
                    continue
                side, total_voters, majority_voters = result
                fired[r].add(market_id)
                raw_formations[r].append({
                    'market_id': market_id,
                    'formation_ts': t_dt.isoformat(),
                    'side': side,
                    'total_voters': total_voters,
                    'majority_voters': majority_voters,
                    'voters': sorted(sides[r].keys()),
                })

    # apply funnel filters: price band, liquidity floor, one-bet-per-cluster
    final = {}
    diagnostics = {}
    for r in READINGS:
        survivors = []
        band_dropped = 0
        liq_dropped = 0
        for f in raw_formations[r]:
            t_dt = parse_ts(f['formation_ts'])
            price = price_at_trade_tape(conn, f['market_id'], t_dt)
            f['price_at_formation'] = price
            f['price_source'] = 'trade_tape_outcome_normalized'
            f['cluster_id'] = cluster_of.get(f['market_id'], f['market_id'])
            # epsilon guard: outcome-normalized price (1 - raw_price for No-side
            # trades) hits float artifacts like 0.09999999999999998 for an exact
            # 0.10 boundary -- a strict comparison would wrongly drop a
            # genuinely-at-the-boundary formation over a rounding hair.
            band_eps = 1e-9
            if price is None or not (CONTESTED_BAND[0] - band_eps <= price <= CONTESTED_BAND[1] + band_eps):
                band_dropped += 1
                f['status'] = 'band_dropped'
                continue
            liq = liquidity_7d(conn, f['market_id'], t_dt)
            f['liquidity_7d'] = liq
            if liq < liquidity_floor:
                liq_dropped += 1
                f['status'] = 'liquidity_dropped'
                continue
            f['status'] = 'survived_pre_dedup'
            survivors.append(f)

        # one bet per cluster: keep strongest signal (most voters, then largest majority)
        by_cluster = defaultdict(list)
        for f in survivors:
            by_cluster[f['cluster_id']].append(f)
        deduped = []
        for cid, fs in by_cluster.items():
            fs.sort(key=lambda x: (x['total_voters'], x['majority_voters']), reverse=True)
            fs[0]['status'] = 'survived_final'
            for dupe in fs[1:]:
                dupe['status'] = 'cluster_dedup_dropped'
            deduped.append(fs[0])

        final[r] = deduped
        diagnostics[r] = {
            'raw_formations': len(raw_formations[r]),
            'band_dropped': band_dropped,
            'liquidity_dropped': liq_dropped,
            'survivors_pre_dedup': len(survivors),
            'distinct_clusters': len(deduped),
        }

    result = {
        'cohort_size': len(cohort),
        'candidate_markets': len(markets),
        'readings': final,
        'raw_formations': raw_formations,  # includes dropped ones, each tagged with 'status'
        'diagnostics': diagnostics,
    }
    if collect_diffs:
        result['guard_diffs'] = guard_diffs
    return result


def persist(conn, result, artifact_table, generator_commit, guard_diffs_table=None):
    """Persists EVERY raw formation (survived or dropped, tagged by `status`),
    not just final survivors -- Task 4's reproducibility requirement means the
    funnel itself (what got dropped and why) must be inspectable later, not
    just the headline count."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {artifact_table} (
            reading TEXT NOT NULL,
            market_id TEXT NOT NULL,
            cluster_id TEXT,
            formation_ts TEXT NOT NULL,
            side TEXT,
            total_voters INTEGER,
            majority_voters INTEGER,
            voters_json TEXT,
            price_at_formation REAL,
            price_source TEXT,
            liquidity_7d INTEGER,
            status TEXT NOT NULL,
            spec_version TEXT NOT NULL,
            guard_threshold REAL NOT NULL,
            generated_at TEXT NOT NULL,
            generator_commit TEXT,
            PRIMARY KEY (reading, market_id)
        )
    """)
    conn.execute(f"DELETE FROM {artifact_table}")
    generated_at = datetime.now(timezone.utc).isoformat()
    for reading, formations in result['raw_formations'].items():
        for f in formations:
            conn.execute(f"""
                INSERT INTO {artifact_table}
                (reading, market_id, cluster_id, formation_ts, side, total_voters,
                 majority_voters, voters_json, price_at_formation, price_source,
                 liquidity_7d, status, spec_version, guard_threshold, generated_at, generator_commit)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                reading, f['market_id'], f.get('cluster_id'), f['formation_ts'], f['side'],
                f['total_voters'], f['majority_voters'], json.dumps(f['voters']),
                f.get('price_at_formation'), f.get('price_source'), f.get('liquidity_7d'),
                f.get('status'), SPEC_VERSION, GUARD_THRESHOLD, generated_at, generator_commit
            ))

    if guard_diffs_table and 'guard_diffs' in result:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {guard_diffs_table} (
                trader TEXT NOT NULL,
                market_id TEXT NOT NULL,
                formation_ts TEXT NOT NULL,
                yes_open REAL, no_open REAL, yes_total REAL, no_total REAL,
                total_side TEXT,
                spec_version TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                PRIMARY KEY (trader, market_id, formation_ts)
            )
        """)
        conn.execute(f"DELETE FROM {guard_diffs_table}")
        for d in result['guard_diffs']:
            conn.execute(f"""
                INSERT INTO {guard_diffs_table}
                (trader, market_id, formation_ts, yes_open, no_open, yes_total, no_total,
                 total_side, spec_version, generated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (d['trader'], d['market_id'], d['formation_ts'], d['yes_open'], d['no_open'],
                  d['yes_total'], d['no_total'], d['total_side'], SPEC_VERSION, generated_at))

    conn.commit()
    return generated_at


def selfcheck(conn, n_traders=8, n_points_per_trader=5, verbose=True):
    """Cross-check TierTimeline.state_at against pit_geo_elo.reconstruct_one_at
    (the validated ground truth) on a sample of (trader, T) pairs."""
    import random
    cohort = list(candidate_cohort(conn))
    random.seed(42)
    sample_traders = random.sample(cohort, min(n_traders, len(cohort)))
    mismatches = []
    checked = 0
    for tr in sample_traders:
        markets = candidate_markets(conn, {tr, *random.sample(cohort, min(3, len(cohort)))})
        tl = TierTimeline(conn, tr)
        points = []
        for mid in markets[:3]:
            for trd, ts in market_change_points(conn, mid, {tr}):
                points.append(ts)
        if not points:
            continue
        random.shuffle(points)
        for ts in points[:n_points_per_trader]:
            t_dt = parse_ts(ts)
            fast = tl.state_at(t_dt)
            slow = geo_elo_at(conn, tr, t_dt)
            checked += 1
            ge_match = (fast['geo_elo'] is None and slow['geo_elo'] is None) or \
                       (fast['geo_elo'] is not None and slow['geo_elo'] is not None
                        and abs(fast['geo_elo'] - slow['geo_elo']) < 0.01)
            gea_match = (fast['geo_elo_active'] is None and slow['geo_elo_active'] is None) or \
                        (fast['geo_elo_active'] is not None and slow['geo_elo_active'] is not None
                         and abs(fast['geo_elo_active'] - slow['geo_elo_active']) < 0.01)
            pool_match = fast['geo_accuracy_pool'] == slow['geo_accuracy_pool']
            count_match = fast['geo_resolved_trades_count'] == slow['geo_resolved_trades_count']
            if not (ge_match and gea_match and pool_match and count_match):
                mismatches.append((tr, str(ts), fast, slow))
    if verbose:
        print(f"[selfcheck] {checked} (trader,T) points checked, {len(mismatches)} mismatches")
        for m in mismatches[:10]:
            print(f"  MISMATCH trader={m[0]} T={m[1]}\n    fast={m[2]}\n    slow={m[3]}")
    return checked, mismatches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/polymarket_tracker.db')
    ap.add_argument('--artifact-table', default='dilution_guard_signals')
    ap.add_argument('--persist', action='store_true')
    ap.add_argument('--generator-commit', default=None)
    ap.add_argument('--json-out', default=None)
    ap.add_argument('--selfcheck', action='store_true')
    ap.add_argument('--collect-diffs', action='store_true',
                     help='also collect (trader,market,T) pairs where the open-reading '
                          'guard excludes but the total-reading guard admits, for sampling')
    ap.add_argument('-v', '--verbose', action='store_true')
    ap.add_argument('--tier-threshold', type=float, default=GEO_ELO_LEGENDARY,
                     help='geo_elo_active gate, e.g. 2175 (LEGENDARY) or 1800 (NEAR_LEGENDARY)')
    ap.add_argument('--min-voters', type=int, default=2)
    ap.add_argument('--liquidity-floor', type=int, default=LIQUIDITY_FLOOR_TRADES_7D,
                     help='trailing-7d trade count floor; 0 disables it')
    args = ap.parse_args()

    conn = db_connect(args.db)

    if args.selfcheck:
        checked, mismatches = selfcheck(conn)
        if mismatches:
            print(f"[selfcheck] FAILED: {len(mismatches)}/{checked} mismatches", file=sys.stderr)
            sys.exit(1)
        print(f"[selfcheck] PASSED: {checked}/{checked} match")
        return

    result = run(conn, verbose=args.verbose, collect_diffs=args.collect_diffs,
                 tier_threshold=args.tier_threshold, min_voters=args.min_voters,
                 liquidity_floor=args.liquidity_floor)
    if args.collect_diffs:
        print(f"[guard_diffs] {len(result.get('guard_diffs', []))} strict-excludes/loose-admits pairs found")

    for r in READINGS:
        d = result['diagnostics'][r]
        print(f"[{r}] raw={d['raw_formations']} band_dropped={d['band_dropped']} "
              f"liq_dropped={d['liquidity_dropped']} survivors={d['survivors_pre_dedup']} "
              f"clusters={d['distinct_clusters']}")

    if args.json_out:
        with open(args.json_out, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"[json] written to {args.json_out}")

    if args.persist:
        ts = persist(conn, result, args.artifact_table, args.generator_commit,
                     guard_diffs_table=f"{args.artifact_table}_guard_diffs" if args.collect_diffs else None)
        print(f"[persist] table={args.artifact_table} generated_at={ts}")

    conn.close()


if __name__ == '__main__':
    main()
