"""
bot_detection.py

Identifies traders exhibiting automated/bot-like behaviour patterns and
classifies them into one of three bot types.

Detection signals (ANY two must fire to flag — single signals have too
many innocent explanations):
  1. > 50% of trades in Crypto markets AND the market resolved in < 24 hours
     (short-duration crypto arbitrage is a common bot pattern)
  2. Win rate >= 90% over >= 30 trades
     (near-perfect win rate at scale is statistically implausible for humans)
  3. Position sizing consistency: stddev of trade shares < 10% of mean
     over >= 30 trades (automated fixed-size orders)

A wallet flagged by >= 2 of these 3 signals is marked bot_suspect = 1,
then classified into one of three types:

  SPEED_ARBITRAGE    — >50% Crypto, avg entry <48h from close, >10 trades/day
                       Edge is latency-based. Excluded from signals.
                       copyable_edge = False

  NEWS_PROCESSING    — >50% Geo/Econ/Elections, avg entry <168h from close,
                       >5 trades/day. Edge is information speed.
                       copyable_edge = True (partially)

  SYSTEMATIC_RESEARCH — >50% Geo/Econ/Elections, <=5 trades/day,
                        win_rate >= 0.55. Edge is analytical discipline.
                        copyable_edge = True (fully valuable)

Adds bot_suspect (BOOLEAN), bot_type (TEXT), copyable_edge (BOOLEAN) columns
to traders if missing. Does NOT delete any data.

Usage:
    python scripts/bot_detection.py
    python scripts/bot_detection.py --dry-run   # no DB writes, no Telegram
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB   = os.path.join(_REPO, 'data', 'polymarket_tracker.db')

CRYPTO_CATEGORY     = 'Crypto'
RESEARCH_CATEGORIES = ('Geopolitics', 'Economics', 'Elections')
CRYPTO_FRACTION     = 0.50       # > 50% trades in short crypto markets
MARKET_DURATION_HRS = 24         # hours — "short-duration" threshold for S1
WIN_RATE_THRESH     = 0.90       # 90%+ win rate (S2)
WIN_RATE_MIN_TRADES = 30         # minimum trades to apply win rate signal
SIZING_CV_THRESH    = 0.10       # coefficient of variation < 10% (S3)
SIZING_MIN_TRADES   = 30         # minimum trades for sizing signal
MIN_SIGNALS         = 2          # need this many signals to flag

# Classification thresholds
SPEED_ARB_MAX_HRS   = 48         # avg hours-to-close at entry
SPEED_ARB_MIN_FREQ  = 10.0       # trades per day
NEWS_MAX_HRS        = 168        # avg hours-to-close (1 week)
NEWS_MIN_FREQ       = 5.0        # trades per day
RESEARCH_MIN_WR     = 0.55       # win rate floor for systematic research
RESEARCH_MAX_FREQ   = 5.0        # trades per day (patient, not rapid)
RESEARCH_CAT_FRAC   = 0.50       # fraction in geo/econ/elections
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add bot_suspect, bot_type, copyable_edge columns if absent."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(traders)")
    cols = {r["name"] for r in cur.fetchall()}

    added = []
    if "bot_suspect" not in cols:
        cur.execute(
            "ALTER TABLE traders ADD COLUMN bot_suspect BOOLEAN NOT NULL DEFAULT 0"
        )
        added.append("bot_suspect")
    if "bot_type" not in cols:
        cur.execute("ALTER TABLE traders ADD COLUMN bot_type TEXT")
        added.append("bot_type")
    if "copyable_edge" not in cols:
        cur.execute("ALTER TABLE traders ADD COLUMN copyable_edge BOOLEAN")
        added.append("copyable_edge")

    if added:
        conn.commit()
        print(f"[BOT] Added columns to traders: {', '.join(added)}")
    else:
        print("[BOT] bot_suspect / bot_type / copyable_edge columns already exist")


# ---------------------------------------------------------------------------
# Original detection signals (unchanged)
# ---------------------------------------------------------------------------

def _signal1_crypto_short(conn: sqlite3.Connection) -> set[str]:
    """
    Traders where >50% of their trades are in Crypto markets that resolved
    within 24 hours of their end_date.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT trader_address
        FROM (
            SELECT
                t.trader_address,
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN t.market_category = :cat
                         AND (
                             m.market_id IS NULL
                             OR (
                                 m.resolution_date IS NOT NULL
                                 AND m.end_date     IS NOT NULL
                                 AND ABS(
                                     julianday(m.resolution_date)
                                     - julianday(m.end_date)
                                 ) * 24.0 < :hrs
                             )
                         )
                        THEN 1.0 ELSE 0.0
                    END
                ) AS crypto_short
            FROM trades t
            LEFT JOIN markets m ON m.market_id = t.market_id
            GROUP BY t.trader_address
            HAVING total >= :min_trades
        )
        WHERE (crypto_short / total) > :frac
    """, {
        "cat":        CRYPTO_CATEGORY,
        "hrs":        MARKET_DURATION_HRS,
        "frac":       CRYPTO_FRACTION,
        "min_trades": WIN_RATE_MIN_TRADES,
    })
    return {r["trader_address"] for r in cur.fetchall()}


def _signal2_win_rate(conn: sqlite3.Connection) -> set[str]:
    """Traders with win_rate >= 90% over >= 30 trades."""
    cur = conn.cursor()
    cur.execute("""
        SELECT address FROM traders
        WHERE win_rate    >= :wr
          AND total_trades >= :min_t
    """, {"wr": WIN_RATE_THRESH, "min_t": WIN_RATE_MIN_TRADES})
    return {r["address"] for r in cur.fetchall()}


def _signal3_uniform_sizing(conn: sqlite3.Connection) -> set[str]:
    """
    Traders whose trade share sizes have a coefficient of variation < 10%.
    CV = sqrt(Var) / mean < 0.10  →  Var < (0.10 * mean)²
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT trader_address
        FROM (
            SELECT
                trader_address,
                COUNT(*)       AS n,
                AVG(shares)    AS avg_s,
                AVG(shares * shares) - AVG(shares) * AVG(shares) AS var_s
            FROM trades
            GROUP BY trader_address
            HAVING n    >= :min_t
               AND avg_s > 0
        )
        WHERE var_s < (:cv * avg_s) * (:cv * avg_s)
    """, {"min_t": SIZING_MIN_TRADES, "cv": SIZING_CV_THRESH})
    return {r["trader_address"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Classification — per-trader feature extraction
# ---------------------------------------------------------------------------

def _fetch_trader_features(conn: sqlite3.Connection, addresses: set[str]) -> dict[str, dict]:
    """
    For each address return:
      crypto_frac      : fraction of trades in Crypto
      research_frac    : fraction in Geo/Econ/Elections
      avg_hrs_to_close : avg hours between trade entry and market end_date (BUY only)
      trades_per_day   : trade frequency
      win_rate         : from traders table
    """
    if not addresses:
        return {}

    ph = ",".join("?" * len(addresses))
    addr_list = list(addresses)
    cur = conn.cursor()

    # Category fractions
    cur.execute(f"""
        SELECT trader_address,
               SUM(CASE WHEN market_category = 'Crypto' THEN 1.0 ELSE 0.0 END) / COUNT(*) AS crypto_frac,
               SUM(CASE WHEN market_category IN ('Geopolitics','Economics','Elections')
                        THEN 1.0 ELSE 0.0 END) / COUNT(*) AS research_frac,
               COUNT(*) AS n,
               (julianday(MAX(timestamp)) - julianday(MIN(timestamp))) AS span_days
        FROM trades
        WHERE trader_address IN ({ph})
        GROUP BY trader_address
    """, addr_list)
    rows = {r["trader_address"]: dict(r) for r in cur.fetchall()}

    # Avg hours-to-close at entry (BUY trades with known end_date)
    cur.execute(f"""
        SELECT t.trader_address,
               AVG((julianday(m.end_date) - julianday(t.timestamp)) * 24.0) AS avg_hrs
        FROM trades t
        JOIN markets m ON m.market_id = t.market_id
        WHERE t.trader_address IN ({ph})
          AND t.side = 'BUY'
          AND m.end_date IS NOT NULL
        GROUP BY t.trader_address
    """, addr_list)
    hrs = {r["trader_address"]: r["avg_hrs"] for r in cur.fetchall()}

    # Win rate from traders table
    cur.execute(f"""
        SELECT address, win_rate, total_trades
        FROM traders
        WHERE address IN ({ph})
    """, addr_list)
    wr = {r["address"]: (r["win_rate"], r["total_trades"]) for r in cur.fetchall()}

    features = {}
    for addr in addresses:
        td = rows.get(addr, {})
        n         = td.get("n", 0)
        span      = td.get("span_days") or 1.0
        span      = max(span, 1.0)
        w, trades = wr.get(addr, (0.0, 0))
        features[addr] = {
            "crypto_frac":      td.get("crypto_frac") or 0.0,
            "research_frac":    td.get("research_frac") or 0.0,
            "avg_hrs_to_close": hrs.get(addr),          # None if no market join
            "trades_per_day":   n / span,
            "win_rate":         w or 0.0,
            "total_trades":     trades,
        }
    return features


def _classify(features: dict) -> tuple[str | None, bool | None]:
    """
    Return (bot_type, copyable_edge) for one trader's feature dict.

    Rules checked in priority order:
      1. SPEED_ARBITRAGE  — crypto-focused, fast entry, high frequency
      2. NEWS_PROCESSING  — research categories, fast entry, moderate-high frequency
      3. SYSTEMATIC_RESEARCH — research categories, patient, consistent win rate
    """
    crypto_frac   = features["crypto_frac"]
    research_frac = features["research_frac"]
    avg_hrs       = features["avg_hrs_to_close"]  # may be None
    freq          = features["trades_per_day"]
    wr            = features["win_rate"]

    # SPEED_ARBITRAGE
    if (crypto_frac > CRYPTO_FRACTION
            and (avg_hrs is None or avg_hrs < SPEED_ARB_MAX_HRS)
            and freq > SPEED_ARB_MIN_FREQ):
        return "SPEED_ARBITRAGE", False

    # NEWS_PROCESSING
    if (research_frac > RESEARCH_CAT_FRAC
            and (avg_hrs is None or avg_hrs < NEWS_MAX_HRS)
            and freq > NEWS_MIN_FREQ):
        return "NEWS_PROCESSING", True

    # SYSTEMATIC_RESEARCH
    if (research_frac > RESEARCH_CAT_FRAC
            and freq <= RESEARCH_MAX_FREQ
            and wr >= RESEARCH_MIN_WR):
        return "SYSTEMATIC_RESEARCH", True

    return None, None


# ---------------------------------------------------------------------------
# Leaderboard helpers
# ---------------------------------------------------------------------------

def _top50(conn: sqlite3.Connection, exclude: set[str] | None = None) -> list[dict]:
    cur = conn.cursor()
    if exclude:
        ph = ",".join("?" * len(exclude))
        cur.execute(f"""
            SELECT address, comprehensive_elo, total_trades, win_rate, username, bot_type
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
              AND address NOT IN ({ph})
            ORDER BY comprehensive_elo DESC
            LIMIT 50
        """, list(exclude))
    else:
        cur.execute("""
            SELECT address, comprehensive_elo, total_trades, win_rate, username, bot_type
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 50
        """)
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Flag + classify
# ---------------------------------------------------------------------------

def _flag_and_classify(
    conn: sqlite3.Connection,
    suspects: set[str],
    type_map: dict[str, tuple[str | None, bool | None]],
) -> int:
    """Write bot_suspect=1, bot_type, copyable_edge for all suspects."""
    if not suspects:
        return 0
    cur = conn.cursor()
    rows = []
    for addr in suspects:
        btype, cedge = type_map.get(addr, (None, None))
        rows.append((1, btype, cedge, addr))
    cur.executemany(
        "UPDATE traders SET bot_suspect=?, bot_type=?, copyable_edge=? WHERE address=?",
        rows,
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(
    suspects: set[str],
    s1: set[str],
    s2: set[str],
    s3: set[str],
    type_map: dict[str, tuple[str | None, bool | None]],
    top50_all: list[dict],
    top50_clean: list[dict],
) -> str:
    suspects_in_top50 = [r for r in top50_all if r["address"] in suspects]

    # Count by type
    type_counts: dict[str, int] = {}
    for btype, _ in type_map.values():
        if btype:
            type_counts[btype] = type_counts.get(btype, 0) + 1
    unclassified = sum(1 for bt, _ in type_map.values() if bt is None)

    # Systematic research traders (high-value signal sources)
    systematic = [
        addr for addr, (bt, _) in type_map.items() if bt == "SYSTEMATIC_RESEARCH"
    ]

    lines = [
        "\U0001f916 *Bot Detection Report*",
        f"Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "*Detection signals (>=2 required to flag):*",
        f"  S1 (>50% short crypto trades): {len(s1):,} traders",
        f"  S2 (win rate >=90%, >=30 trades): {len(s2):,} traders",
        f"  S3 (uniform position sizing): {len(s3):,} traders",
        "",
        f"*Flagged (>=2 signals): {len(suspects):,} traders*",
        f"  SPEED_ARBITRAGE (excluded from signals):       {type_counts.get('SPEED_ARBITRAGE', 0)}",
        f"  NEWS_PROCESSING (flag for caution):            {type_counts.get('NEWS_PROCESSING', 0)}",
        f"  SYSTEMATIC_RESEARCH (keep — valuable signal):  {type_counts.get('SYSTEMATIC_RESEARCH', 0)}",
        f"  Unclassified:                                  {unclassified}",
        f"  In current top-50 ELO: {len(suspects_in_top50)}",
    ]

    if suspects_in_top50:
        lines += ["", "*Bot suspects in top-50 leaderboard:*"]
        for r in suspects_in_top50:
            name  = r.get("username") or r["address"][:12] + "..."
            sigs  = [s for s, pool in [("S1", s1), ("S2", s2), ("S3", s3)]
                     if r["address"] in pool]
            btype = type_map.get(r["address"], (None,))[0] or "?"
            lines.append(
                f"  {name}  ELO={r['comprehensive_elo']:.0f}"
                f"  [{'+'.join(sigs)}]  type={btype}"
            )
    else:
        lines.append("  No bot suspects in current top-50.")

    if systematic:
        lines += ["", "*SYSTEMATIC_RESEARCH traders (high-value signal sources):*"]
        cur = None  # we don't have a conn here — use top50 data if available
        for addr in systematic[:10]:
            match = next((r for r in top50_all if r["address"] == addr), None)
            if match:
                name = match.get("username") or addr[:14] + "..."
                lines.append(
                    f"  {name}  ELO={match['comprehensive_elo']:.0f}"
                    f"  WR={match['win_rate']*100:.0f}%"
                )
            else:
                lines.append(f"  {addr[:20]}...")
        if len(systematic) > 10:
            lines.append(f"  ... and {len(systematic)-10} more")
    else:
        lines += ["", "No SYSTEMATIC_RESEARCH traders found in current dataset."]

    lines += [
        "",
        f"*Top-10 leaderboard with SPEED_ARBITRAGE excluded*:",
    ]
    for i, r in enumerate(top50_clean[:10], 1):
        name  = r.get("username") or r["address"][:12] + "..."
        btype = r.get("bot_type") or ""
        tag   = f"  [{btype}]" if btype else ""
        lines.append(
            f"  {i:>2}. {name:<22} ELO={r['comprehensive_elo']:.0f}"
            f"  T={r['total_trades']}  WR={r['win_rate']*100:.0f}%{tag}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Telegram dispatch
# ---------------------------------------------------------------------------

def _send_telegram(message: str) -> None:
    try:
        sys.path.insert(0, _REPO)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_REPO, ".env"))
        token   = os.getenv("telegram_alerts_token")
        chat_id = os.getenv("telegram_chat_id")
        if not token or not chat_id:
            print("[BOT] Telegram credentials not found in .env — skipping send")
            return
        from monitoring.telegram_health_bot import TelegramHealthBot
        bot = TelegramHealthBot(token=token, chat_id=chat_id)
        bot._send_message(message)
        print("[BOT] Report sent to Telegram")
    except Exception as e:
        print(f"[BOT] Telegram error: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_bot_detection(dry_run: bool = False) -> dict:
    print("[BOT] Starting bot detection scan...")
    conn = _get_conn()

    _ensure_columns(conn)

    print("[BOT] Computing Signal 1 (short crypto markets)...")
    s1 = _signal1_crypto_short(conn)
    print(f"  {len(s1):,} traders")

    print("[BOT] Computing Signal 2 (high win rate)...")
    s2 = _signal2_win_rate(conn)
    print(f"  {len(s2):,} traders")

    print("[BOT] Computing Signal 3 (uniform position sizing)...")
    s3 = _signal3_uniform_sizing(conn)
    print(f"  {len(s3):,} traders")

    # Flag if >= MIN_SIGNALS signals fire
    signal_counts: dict[str, int] = {}
    for addr in s1 | s2 | s3:
        signal_counts[addr] = (
            (1 if addr in s1 else 0)
            + (1 if addr in s2 else 0)
            + (1 if addr in s3 else 0)
        )
    suspects = {a for a, n in signal_counts.items() if n >= MIN_SIGNALS}
    print(f"[BOT] Suspects (>={MIN_SIGNALS} signals): {len(suspects):,}")

    # Classify each suspect
    print("[BOT] Classifying suspects by bot type...")
    features = _fetch_trader_features(conn, suspects)
    type_map: dict[str, tuple[str | None, bool | None]] = {
        addr: _classify(feat) for addr, feat in features.items()
    }

    # Type counts for reporting
    for btype in ("SPEED_ARBITRAGE", "NEWS_PROCESSING", "SYSTEMATIC_RESEARCH"):
        n = sum(1 for bt, _ in type_map.values() if bt == btype)
        if n:
            print(f"  {btype}: {n}")

    # Only exclude SPEED_ARBITRAGE from leaderboard clean view
    speed_arb = {a for a, (bt, _) in type_map.items() if bt == "SPEED_ARBITRAGE"}

    top50_all   = _top50(conn)
    top50_clean = _top50(conn, exclude=speed_arb)

    report = _build_report(suspects, s1, s2, s3, type_map, top50_all, top50_clean)
    safe = report.encode("ascii", errors="replace").decode("ascii")
    print("\n" + safe.replace("*", "") + "\n")

    if not dry_run:
        written = _flag_and_classify(conn, suspects, type_map)
        print(f"[BOT] Flagged/classified {written} traders in DB")
        _send_telegram(report)
    else:
        print("[BOT] DRY RUN — no DB writes, no Telegram")

    conn.close()
    return {
        "flagged":             len(suspects),
        "speed_arbitrage":     sum(1 for bt, _ in type_map.values() if bt == "SPEED_ARBITRAGE"),
        "news_processing":     sum(1 for bt, _ in type_map.values() if bt == "NEWS_PROCESSING"),
        "systematic_research": sum(1 for bt, _ in type_map.values() if bt == "SYSTEMATIC_RESEARCH"),
        "s1": len(s1), "s2": len(s2), "s3": len(s3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot trader detection with type classification")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report only — no DB writes, no Telegram")
    args = parser.parse_args()
    result = run_bot_detection(dry_run=args.dry_run)
    print(
        f"[BOT] Done — {result['flagged']} flagged  "
        f"(SA={result['speed_arbitrage']}  NP={result['news_processing']}  "
        f"SR={result['systematic_research']})"
    )


if __name__ == "__main__":
    main()
