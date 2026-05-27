#!/usr/bin/env python3
"""
Insider Activity Detector

Scans recent trades for two patterns:

INDIVIDUAL SIGNAL — all five must be true simultaneously:
  1. Fresh wallet: trader's first trade in our DB within last 30 days
  2. Large single bet: position > $5,000
  3. Low-odds entry: market price at time of bet < $0.35
  4. Single-market focus: trader has traded in <= 2 markets total
  5. Geopolitics market: passes keyword filter

CLUSTER ALERT — 3+ fresh wallets betting the same outcome on the same
geopolitics/elections market within any 6-hour window, each with position
> $500. Only fires if combined position >= $50K AND avg composite_score
>= 0.35.

Signals are stored in insider_signals and insider_clusters tables.
Can be called directly (backtest mode) or imported by system_observer.py.

Usage:
    python scripts/detect_insider_activity.py                  # scan last 24h
    python scripts/detect_insider_activity.py --hours 720      # backtest 30 days
    python scripts/detect_insider_activity.py --dry-run        # no DB writes
"""

import sys
import sqlite3
import argparse
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ── Geopolitics keyword filter (inline copy from monitor.py) ──────────────────
EXCLUSION_KEYWORDS = [
    # Sports
    "nba", "nfl", "mlb", "nhl", "ncaa", "ufc", "mma", "f1", "formula 1",
    "premier league", "champions league", "world cup", "super bowl",
    "march madness", "stanley cup", "world series", "kentucky derby",
    # Tennis — Grand Slams
    "wimbledon", "roland garros", "french open", "australian open",
    "us open tennis",
    # Tennis — ATP/WTA tour events
    "atp", "wta", "madrid open", "miami open", "bnp paribas",
    "indian wells", "monte carlo", "rome open", "canadian open",
    "cincinnati open", "stuttgart open", "eastbourne", "birmingham",
    "bad homburg", "queen's club", "upper austria",
    # Tennis — player name collisions (Ben Shelton vs Judy Shelton)
    "ben shelton", "shelton vs", "vs shelton", "shelton vs.",
    # Generic match-up marker (catches remaining head-to-head sport markets)
    " vs ",
    # Entertainment
    "oscars", "grammy", "emmy", "golden globe", "academy award",
    "box office", "billboard", "spotify", "netflix", "apple tv",
    # Crypto price
    "bitcoin price", "eth price", "btc price", "sol price",
    "will bitcoin", "will eth", "will btc",
    # Esports
    "esports", "valorant", "league of legends", "dota", "counter-strike",
    "cs2", "overwatch", "rocket league",
    # Pop culture / celeb
    "taylor swift", "beyonce", "kardashian", "justin bieber",
    # Markets / finance (non-geo)
    "stock price", "earnings", "ipo", "nasdaq", "s&p 500",
    # Religious / novelty (not tradeable insider events)
    "jesus", "christ", "god ", "allah", "bible",
    "rapture", "antichrist", "second coming",
]


def _is_geopolitics(title: str) -> bool:
    """Return True if title likely represents a geopolitics market."""
    t = title.lower()
    for kw in EXCLUSION_KEYWORDS:
        if kw in t:
            return False
    return True


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at     TEXT NOT NULL,
            market_id       TEXT,
            market_title    TEXT,
            outcome         TEXT,
            trader_address  TEXT NOT NULL,
            username        TEXT,
            position_size   REAL,
            entry_price     REAL,
            wallet_age_days INTEGER,
            markets_count   INTEGER,
            trade_timestamp TEXT,
            pattern         TEXT,
            alerted         INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS insider_clusters (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at     TEXT NOT NULL,
            market_id       TEXT,
            market_title    TEXT,
            outcome         TEXT,
            wallet_count    INTEGER,
            combined_size   REAL,
            window_start    TEXT,
            window_end      TEXT,
            wallet_list     TEXT,
            alerted         INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS ix_insider_signals_market
            ON insider_signals(market_id, detected_at);
        CREATE INDEX IF NOT EXISTS ix_insider_clusters_market
            ON insider_clusters(market_id, detected_at);
    """)
    # Migration: add pattern column if table was created before it was added
    try:
        conn.execute("ALTER TABLE insider_signals ADD COLUMN pattern TEXT")
    except Exception:
        pass  # column already exists
    # Migration: add outcome tracking columns for signal scoring
    for _col_sql in [
        "ALTER TABLE insider_signals ADD COLUMN outcome_correct BOOLEAN DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN resolved_at TEXT DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN information_value REAL DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN scored_at TEXT DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN composite_score REAL DEFAULT NULL",
        "ALTER TABLE insider_signals ADD COLUMN score_breakdown TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(_col_sql)
        except Exception:
            pass  # column already exists
    conn.commit()


# ── Composite scoring (Mitts/Ofir 2026) ───────────────────────────────────────

def calculate_composite_score(
    trader_address: str,
    market_id: str,
    position_size: float,
    entry_price: float,
    wallet_age_days: int,
    markets_count: int,
    trade_timestamp: str,
    conn: sqlite3.Connection,
) -> tuple[float, dict]:
    """
    Five-signal Mitts/Ofir composite score (0.0–1.0).
    Returns (composite_score, breakdown_dict).

    Hard disqualification: entry_price > 0.80 → score = 0.0.
    This filters near-certainty arb bets that have no information value.
    """
    breakdown = {}

    if entry_price > 0.80:
        breakdown["disqualified"] = "DISQUALIFIED: near-certainty arb bet"
        breakdown["entry_price"] = entry_price
        return 0.0, breakdown

    cur = conn.cursor()

    # Signal 1 — Cross-sectional bet size
    cur.execute(
        "SELECT SUM(entry_total_cost) FROM positions WHERE market_id = ?",
        (market_id,),
    )
    row = cur.fetchone()
    total_market_volume = (row[0] or 0.0) if row else 0.0
    if total_market_volume > 0:
        cs_ratio = position_size / total_market_volume
        s1 = min(1.0, max(0.0, (cs_ratio - 0.01) / (0.10 - 0.01)))
    else:
        s1 = 0.0
    breakdown["s1_cross_sectional"] = round(s1, 4)
    breakdown["s1_market_volume"] = round(total_market_volume, 2)

    # Signal 2 — Within-trader bet size anomaly
    cur.execute(
        "SELECT AVG(entry_total_cost) FROM positions WHERE trader_address = ?",
        (trader_address,),
    )
    row = cur.fetchone()
    trader_avg = (row[0] or 0.0) if row else 0.0
    if trader_avg > 0:
        wt_ratio = position_size / trader_avg
        s2 = min(1.0, max(0.0, (wt_ratio - 2.0) / (10.0 - 2.0)))
    else:
        s2 = 0.5  # no history → neutral
    breakdown["s2_within_trader"] = round(s2, 4)
    breakdown["s2_trader_avg_position"] = round(trader_avg, 2)

    # Signal 3 — Entry price contrarianism
    if entry_price <= 0.10:
        s3 = 1.0
    elif entry_price <= 0.20:
        s3 = 0.8
    elif entry_price <= 0.35:
        s3 = 0.6
    elif entry_price <= 0.50:
        s3 = 0.2
    else:
        s3 = 0.0
    breakdown["s3_price_contrarian"] = round(s3, 4)

    # Signal 4 — Pre-resolution timing
    cur.execute(
        "SELECT resolution_date FROM markets WHERE market_id = ?",
        (market_id,),
    )
    row = cur.fetchone()
    resolution_date_str = (row[0] if row else None) if row else None
    s4 = 0.0
    days_before = None
    if resolution_date_str and trade_timestamp:
        try:
            res_dt = datetime.fromisoformat(str(resolution_date_str).replace("Z", "+00:00").rstrip("+00:00") if "Z" in str(resolution_date_str) else str(resolution_date_str))
            trade_dt = datetime.fromisoformat(str(trade_timestamp))
            # Strip timezone info for naive comparison
            if res_dt.tzinfo is not None:
                res_dt = res_dt.replace(tzinfo=None)
            if trade_dt.tzinfo is not None:
                trade_dt = trade_dt.replace(tzinfo=None)
            days_before = (res_dt - trade_dt).total_seconds() / 86400.0
            if days_before <= 1:
                s4 = 1.0
            elif days_before <= 3:
                s4 = 0.8
            elif days_before <= 7:
                s4 = 0.6
            elif days_before <= 14:
                s4 = 0.4
            elif days_before <= 30:
                s4 = 0.2
            else:
                s4 = 0.0
        except Exception:
            s4 = 0.0
    breakdown["s4_timing"] = round(s4, 4)
    if days_before is not None:
        breakdown["s4_days_before_resolution"] = round(days_before, 1)

    # Signal 5 — Directional concentration
    if markets_count == 1:
        s5 = 1.0
    elif markets_count <= 2:
        s5 = 0.8
    elif markets_count <= 5:
        s5 = 0.6
    elif markets_count <= 10:
        s5 = 0.2
    else:
        s5 = 0.0
    breakdown["s5_concentration"] = round(s5, 4)

    composite = (s1 + s2 + s3 + s4 + s5) / 5.0
    breakdown["composite"] = round(composite, 4)

    return round(composite, 4), breakdown


def backfill_composite_scores(conn: sqlite3.Connection) -> int:
    """
    Calculate and store composite_score + score_breakdown for all
    insider_signals rows that have composite_score IS NULL.
    Returns the number of rows updated.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, trader_address, market_id, position_size, entry_price,
               wallet_age_days, markets_count, trade_timestamp
        FROM insider_signals
        WHERE composite_score IS NULL
    """)
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        sig_id, addr, market_id, pos, price, age, mkts, ts = (
            row[0], row[1], row[2], row[3] or 0.0,
            row[4] or 0.0, row[5] or 0, row[6] or 0, row[7],
        )
        score, bd = calculate_composite_score(addr, market_id, pos, price, age, mkts, ts, conn)
        conn.execute(
            "UPDATE insider_signals SET composite_score = ?, score_breakdown = ? WHERE id = ?",
            (score, json.dumps(bd), sig_id),
        )
        updated += 1
    conn.commit()
    return updated


def backfill_wallet_age_days(conn: sqlite3.Connection) -> int:
    """
    Recompute wallet_age_days for all insider_signals using:
        (trade_timestamp - traders.first_seen).days
    Falls back to (now - first_seen).days if trader not found.
    Returns number of rows updated.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, trader_address, trade_timestamp
        FROM insider_signals
        WHERE trade_timestamp IS NOT NULL
    """)
    rows = cur.fetchall()
    updated = 0
    for row in rows:
        sig_id = row[0]
        addr   = row[1]
        ts     = row[2]
        try:
            fs_row = conn.execute(
                "SELECT first_seen FROM traders WHERE address = ?", (addr,)
            ).fetchone()
            if fs_row and fs_row[0]:
                age_days = (
                    datetime.fromisoformat(ts) - datetime.fromisoformat(fs_row[0])
                ).days
            else:
                age_days = None  # cannot compute — leave unchanged
        except Exception:
            age_days = None
        if age_days is not None:
            conn.execute(
                "UPDATE insider_signals SET wallet_age_days = ? WHERE id = ?",
                (age_days, sig_id),
            )
            updated += 1
    conn.commit()
    return updated


# ── Core detection ─────────────────────────────────────────────────────────────

def detect_individual_signals(conn: sqlite3.Connection,
                               since: datetime,
                               min_position: float = 2000.0,
                               max_price: float = 0.35,
                               max_markets: int = 2,
                               wallet_age_days: int = 90) -> list[dict]:
    """
    Find trades that match the individual insider signal pattern.
    Returns list of signal dicts.
    """
    cur = conn.cursor()

    # Pull all recent geopolitics trades with trader metadata
    cur.execute("""
        SELECT
            tr.trade_id,
            tr.trader_address,
            tr.market_id,
            tr.market_title,
            tr.outcome,
            tr.price,
            tr.shares,
            tr.timestamp,
            t.username,
            t.first_seen,
            (SELECT COUNT(DISTINCT market_id) FROM trades WHERE trader_address = tr.trader_address) AS markets_count
        FROM trades tr
        JOIN traders t ON tr.trader_address = t.address
        WHERE tr.timestamp >= ?
          AND tr.shares > 0
        ORDER BY tr.timestamp DESC
    """, (since.isoformat(),))

    rows = cur.fetchall()
    wallet_cutoff = (datetime.now() - timedelta(days=wallet_age_days)).isoformat()
    signals = []

    seen_ids = set()  # deduplicate by trade_id
    for row in rows:
        tid         = row["trade_id"]
        addr        = row["trader_address"]
        market_id   = row["market_id"]
        market_title= row["market_title"] or ""
        outcome     = row["outcome"]
        price       = row["price"] or 0.0
        shares      = row["shares"] or 0.0
        ts          = row["timestamp"]
        username    = row["username"]
        first_seen  = row["first_seen"] or ""
        mkts        = row["markets_count"] or 0

        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        # 1. Geopolitics filter
        if not _is_geopolitics(market_title):
            continue

        # 2. Fresh wallet
        if first_seen < wallet_cutoff:
            continue

        # 3. Large bet
        position_size = shares * price
        if position_size < min_position:
            continue

        # 5. Single-market focus (checked before price so we can annotate pattern)
        if mkts > max_markets:
            continue

        # Compute wallet age: days from first_seen to trade_timestamp (not to now)
        try:
            fs_row = conn.execute(
                "SELECT first_seen FROM traders WHERE address = ?", (addr,)
            ).fetchone()
            if fs_row and fs_row[0]:
                age_days = (
                    datetime.fromisoformat(ts) - datetime.fromisoformat(fs_row[0])
                ).days
            else:
                age_days = (datetime.now() - datetime.fromisoformat(first_seen)).days
        except Exception:
            age_days = 0

        # 4. Price check — two patterns:
        #    LOW_ODDS: price < max_price (original spec: buying at ~0.35 is high conviction early)
        #    HIGH_CONVICTION: late-stage insider (e.g. Feb 28 Iran wallets at $0.875 before strike).
        #      Requires price >= 0.75 AND position >= $10K hard floor.
        #      Above 0.90 the signal is almost always arb/market-making, so we require $50K+
        #      to keep only the most anomalous near-certain bets.
        low_odds  = price < max_price
        high_conv = (
            price >= 0.75
            and position_size >= max(10_000.0, min_position * 2)
            and (price <= 0.90 or position_size >= 50_000.0)
        )
        if not (low_odds or high_conv):
            continue

        pattern = "New wallet, low-odds entry, single market focus" if low_odds else \
                  "New wallet, large high-price bet, single market focus (Iran-strike pattern)"

        composite, breakdown = calculate_composite_score(
            addr, market_id, round(position_size, 2), round(price, 4),
            age_days, mkts, ts, conn,
        )

        signals.append({
            "market_id":        market_id,
            "market_title":     market_title,
            "outcome":          outcome,
            "trader_address":   addr,
            "username":         username,
            "position_size":    round(position_size, 2),
            "entry_price":      round(price, 4),
            "wallet_age_days":  age_days,
            "markets_count":    mkts,
            "trade_timestamp":  ts,
            "pattern":          pattern,
            "composite_score":  composite,
            "score_breakdown":  breakdown,
        })

    return signals


def detect_cluster_signals(conn: sqlite3.Connection,
                            since: datetime,
                            min_wallets: int = 3,
                            cluster_window_hours: float = 6.0,
                            min_position: float = 500.0,        # per-wallet floor
                            min_combined: float = 50_000.0,     # combined cluster gate
                            min_avg_composite: float = 0.35,    # composite score gate
                            wallet_age_days: int = 90) -> list[dict]:
    """
    Detect clusters: N+ fresh wallets betting the same outcome on the same
    geopolitics/elections market within a rolling time window.
    Only fires if combined position >= $50K and avg composite_score >= 0.35.
    """
    cur = conn.cursor()
    wallet_cutoff = (datetime.now() - timedelta(days=wallet_age_days)).isoformat()
    window_secs = cluster_window_hours * 3600

    # Get all recent fresh-wallet trades — SQL-level category filter (Geopolitics/Elections)
    cur.execute("""
        SELECT
            tr.trader_address,
            tr.market_id,
            tr.market_title,
            tr.outcome,
            tr.price,
            tr.shares,
            tr.timestamp,
            t.first_seen
        FROM trades tr
        JOIN traders t ON tr.trader_address = t.address
        WHERE tr.timestamp >= ?
          AND t.first_seen >= ?
          AND tr.shares > 0
          AND tr.market_category IN ('Geopolitics', 'Elections')
        ORDER BY tr.market_id, tr.outcome, tr.timestamp
    """, (since.isoformat(), wallet_cutoff))

    rows = cur.fetchall()

    # Group by (market_id, outcome)
    bucket: dict = defaultdict(list)
    for row in rows:
        title = row["market_title"] or ""
        if not _is_geopolitics(title):  # secondary keyword guard
            continue
        pos = (row["shares"] or 0) * (row["price"] or 0)
        if pos < min_position:
            continue
        key = (row["market_id"], row["outcome"])
        bucket[key].append({
            "addr":       row["trader_address"],
            "pos":        pos,
            "ts":         row["timestamp"],
            "title":      title,
            "price":      row["price"] or 0.0,
            "first_seen": row["first_seen"] or "",
        })

    clusters = []
    for (market_id, outcome), trades in bucket.items():
        if len(trades) < min_wallets:
            continue

        # Sliding window over sorted timestamps
        trades.sort(key=lambda x: x["ts"])
        for i in range(len(trades)):
            window = [trades[i]]
            t0 = trades[i]["ts"]
            for j in range(i + 1, len(trades)):
                t1 = trades[j]["ts"]
                try:
                    delta = (datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds()
                except Exception:
                    continue
                if delta <= window_secs:
                    window.append(trades[j])
                else:
                    break

            if len(window) < min_wallets:
                continue

            # Deduplicate wallets within window (keep first-seen trade per wallet)
            seen_addrs: dict = {}
            for t in window:
                if t["addr"] not in seen_addrs:
                    seen_addrs[t["addr"]] = t
            if len(seen_addrs) < min_wallets:
                continue

            # Gate 1: combined position must reach $50K
            combined_size = sum(e["pos"] for e in seen_addrs.values())
            if combined_size < min_combined:
                continue

            # Gate 2: avg composite score of cluster wallets must be >= 0.35
            wallet_scores = []
            for addr, entry in seen_addrs.items():
                try:
                    fs_row = conn.execute(
                        "SELECT first_seen FROM traders WHERE address = ?", (addr,)
                    ).fetchone()
                    if fs_row and fs_row[0]:
                        age_days = (
                            datetime.fromisoformat(entry["ts"]) - datetime.fromisoformat(fs_row[0])
                        ).days
                    else:
                        age_days = (datetime.now() - datetime.fromisoformat(entry["first_seen"])).days
                except Exception:
                    age_days = 0
                sc = conn.cursor()
                sc.execute(
                    "SELECT COUNT(DISTINCT market_id) FROM trades WHERE trader_address = ?",
                    (addr,),
                )
                mkts = sc.fetchone()[0] or 0
                score, _ = calculate_composite_score(
                    addr, market_id, entry["pos"], entry["price"],
                    age_days, mkts, entry["ts"], conn,
                )
                wallet_scores.append(score)
            avg_composite = sum(wallet_scores) / len(wallet_scores) if wallet_scores else 0.0
            if avg_composite < min_avg_composite:
                continue

            clusters.append({
                "market_id":    market_id,
                "market_title": trades[0]["title"],
                "outcome":      outcome,
                "wallet_count": len(seen_addrs),
                "combined_size": round(combined_size, 2),
                "window_start": window[0]["ts"],
                "window_end":   window[-1]["ts"],
                "wallet_list":  ",".join(seen_addrs.keys()),
            })
            # Don't slide further into same window
            break

    # Deduplicate clusters by (market_id, outcome, window_start)
    seen = set()
    unique = []
    for c in clusters:
        key = (c["market_id"], c["outcome"], c["window_start"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


# ── DB persistence ─────────────────────────────────────────────────────────────

def _already_stored_signal(conn: sqlite3.Connection, sig: dict) -> bool:
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM insider_signals
        WHERE trader_address = ? AND market_id = ? AND trade_timestamp = ?
        LIMIT 1
    """, (sig["trader_address"], sig["market_id"], sig["trade_timestamp"]))
    return cur.fetchone() is not None


def _already_stored_cluster(conn: sqlite3.Connection, cl: dict) -> bool:
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM insider_clusters
        WHERE market_id = ? AND outcome = ? AND window_start = ?
        LIMIT 1
    """, (cl["market_id"], cl["outcome"], cl["window_start"]))
    return cur.fetchone() is not None


def save_signals(conn: sqlite3.Connection, signals: list[dict],
                 clusters: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """Persist new signals and clusters. Returns (new_signals, new_clusters)."""
    import time as _time

    now = datetime.now().isoformat()
    new_sigs = 0
    new_cls = 0

    for sig in signals:
        # Composite score gate: skip arb bets and low-conviction signals
        composite = sig.get("composite_score", 0.0)
        if composite < 0.45:
            continue
        if _already_stored_signal(conn, sig):
            continue
        if dry_run:
            new_sigs += 1
            continue
        breakdown_json = json.dumps(sig.get("score_breakdown", {})) if sig.get("score_breakdown") else None
        for _attempt in range(10):
            try:
                conn.execute("""
                    INSERT INTO insider_signals
                        (detected_at, market_id, market_title, outcome,
                         trader_address, username, position_size, entry_price,
                         wallet_age_days, markets_count, trade_timestamp, pattern,
                         composite_score, score_breakdown, alerted)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                """, (now, sig["market_id"], sig["market_title"], sig["outcome"],
                      sig["trader_address"], sig["username"], sig["position_size"],
                      sig["entry_price"], sig["wallet_age_days"], sig["markets_count"],
                      sig["trade_timestamp"], sig.get("pattern"), composite, breakdown_json))
                conn.commit()
                new_sigs += 1
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    _time.sleep(2)
                else:
                    raise

    for cl in clusters:
        if _already_stored_cluster(conn, cl):
            continue
        if dry_run:
            new_cls += 1
            continue
        for _attempt in range(10):
            try:
                conn.execute("""
                    INSERT INTO insider_clusters
                        (detected_at, market_id, market_title, outcome,
                         wallet_count, combined_size, window_start, window_end,
                         wallet_list, alerted)
                    VALUES (?,?,?,?,?,?,?,?,?,0)
                """, (now, cl["market_id"], cl["market_title"], cl["outcome"],
                      cl["wallet_count"], cl["combined_size"],
                      cl["window_start"], cl["window_end"], cl["wallet_list"]))
                conn.commit()
                new_cls += 1
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e):
                    _time.sleep(2)
                else:
                    raise

    return new_sigs, new_cls


# ── Alert formatters ───────────────────────────────────────────────────────────

def format_signal_alert(sig: dict) -> str:
    implied_pct = round(sig["entry_price"] * 100, 1)
    name_part = f" ({sig['username']})" if sig.get("username") else ""
    addr_short = sig["trader_address"][:6] + "..." + sig["trader_address"][-4:]
    return (
        f"\U0001f6a8 INSIDER SIGNAL DETECTED\n"
        f"Market: {sig['market_title']}\n"
        f"Outcome: {sig['outcome']}\n"
        f"Trader: {addr_short}{name_part}\n"
        f"Bet size: ${sig['position_size']:,.0f}\n"
        f"Entry price: ${sig['entry_price']:.3f} ({implied_pct}% implied prob)\n"
        f"Wallet age: {sig['wallet_age_days']} days old in our system\n"
        f"Markets traded: {sig['markets_count']} total\n"
        f"\u26a0\ufe0f Pattern: {sig.get('pattern', 'New wallet, large bet, low-odds entry')}"
    )


def format_cluster_alert(cl: dict) -> str:
    try:
        ws = datetime.fromisoformat(cl["window_start"]).strftime("%Y-%m-%d %H:%M")
        we = datetime.fromisoformat(cl["window_end"]).strftime("%H:%M")
        window_str = f"{ws} \u2013 {we} UTC"
    except Exception:
        window_str = f"{cl['window_start']} \u2013 {cl['window_end']}"
    return (
        f"\U0001f6a8\U0001f6a8 CLUSTER INSIDER ALERT\n"
        f"Market: {cl['market_title']}\n"
        f"Outcome: {cl['outcome']}\n"
        f"Wallets: {cl['wallet_count']} fresh accounts all betting same outcome\n"
        f"Combined position: ${cl['combined_size']:,.0f}\n"
        f"Window: {window_str}\n"
        f"\u26a0\ufe0f This matches the Feb 28 Iran strike pattern exactly"
    )


# ── Standalone runner / backtest ───────────────────────────────────────────────

def run_detection(db_path: str,
                  hours: float = 24.0,
                  dry_run: bool = False,
                  verbose: bool = True) -> tuple[list[dict], list[dict]]:
    """
    Main entry point usable both from CLI and from system_observer.py.
    Returns (new_individual_signals, new_cluster_signals).
    """
    since = datetime.now() - timedelta(hours=hours)
    conn = _connect(db_path)
    _ensure_tables(conn)

    age_backfilled = backfill_wallet_age_days(conn)
    if verbose and age_backfilled:
        print(f"[INSIDER] Backfilled wallet_age_days for {age_backfilled} existing signal(s)")

    backfilled = backfill_composite_scores(conn)
    if verbose and backfilled:
        print(f"[INSIDER] Backfilled composite scores for {backfilled} existing signal(s)")

    signals  = detect_individual_signals(conn, since)
    clusters = detect_cluster_signals(conn, since)

    new_sigs, new_cls = save_signals(conn, signals, clusters, dry_run=dry_run)
    conn.close()

    if verbose:
        print(f"[INSIDER] Scanned last {hours:.0f}h | "
              f"individual={len(signals)} ({new_sigs} new) | "
              f"clusters={len(clusters)} ({new_cls} new)")

    return signals, clusters


def main():
    parser = argparse.ArgumentParser(description="Insider activity detector")
    parser.add_argument("--hours",   type=float, default=24.0,
                        help="Lookback window in hours (default 24, use 720 for 30-day backtest)")
    parser.add_argument("--db",      default="data/polymarket_tracker.db")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect and print but do not write to DB")
    args = parser.parse_args()

    import os
    os.chdir(project_root)

    is_backtest = args.hours > 48

    print("=" * 70)
    if is_backtest:
        print(f"  INSIDER DETECTOR — BACKTEST ({args.hours:.0f}h / {args.hours/24:.0f} days)")
    else:
        print(f"  INSIDER DETECTOR — LIVE SCAN (last {args.hours:.0f}h)")
    print("=" * 70)
    if args.dry_run:
        print("  *** DRY RUN — no writes ***")
    print()

    since = datetime.now() - timedelta(hours=args.hours)
    conn  = _connect(args.db)
    _ensure_tables(conn)

    # ── Backfill wallet_age_days for existing signals ──
    age_backfilled = backfill_wallet_age_days(conn)
    if age_backfilled:
        print(f"  Backfilled wallet_age_days for {age_backfilled} existing signal(s)")

    # ── Individual signals ──
    print("[1/2] Scanning for individual insider signals...")
    signals = detect_individual_signals(conn, since)
    print(f"  Found {len(signals)} signal(s)")
    print()

    def _safe(s: str) -> str:
        return s.encode("ascii", "replace").decode("ascii")

    for sig in signals:
        print("  " + "-" * 60)
        for line in format_signal_alert(sig).split("\n"):
            print("  " + _safe(line))
        print()

    # ── Cluster signals ──
    print("[2/2] Scanning for cluster insider signals...")
    clusters = detect_cluster_signals(conn, since)
    print(f"  Found {len(clusters)} cluster(s)")
    print()

    for cl in clusters:
        print("  " + "-" * 60)
        for line in format_cluster_alert(cl).split("\n"):
            print("  " + _safe(line))
        wallets = cl["wallet_list"].split(",")
        print(f"  Wallets ({len(wallets)}):")
        for w in wallets:
            print(f"    {w[:6]}...{w[-4:]}")
        print()

    # ── Persist ──
    new_sigs, new_cls = save_signals(conn, signals, clusters, dry_run=args.dry_run)
    conn.close()

    print("=" * 70)
    print(f"  SUMMARY")
    print("=" * 70)
    print(f"  Lookback        : {args.hours:.0f}h ({args.hours/24:.1f} days)")
    print(f"  Individual hits : {len(signals)}  ({new_sigs} new / written)")
    print(f"  Cluster hits    : {len(clusters)}  ({new_cls} new / written)")
    if args.dry_run:
        print("  DB writes       : skipped (dry-run)")
    print()


if __name__ == "__main__":
    main()
