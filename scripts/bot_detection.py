"""
bot_detection.py

Identifies traders exhibiting automated/bot-like behaviour patterns.

Detection signals (ANY two must fire to flag — single signals have too
many innocent explanations):
  1. > 50% of trades in Crypto markets AND the market resolved in < 24 hours
     (short-duration crypto arbitrage is a common bot pattern)
  2. Win rate >= 90% over >= 30 trades
     (near-perfect win rate at scale is statistically implausible for humans)
  3. Position sizing consistency: stddev of trade shares < 10% of mean
     over >= 30 trades (automated fixed-size orders)

A wallet flagged by >= 2 of these 3 signals is marked bot_suspect = 1.

Adds bot_suspect column (BOOLEAN, default 0) to traders if missing.
Does NOT delete any data.

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
CRYPTO_FRACTION     = 0.50       # > 50% trades in short crypto markets
MARKET_DURATION_HRS = 24         # hours — "short-duration" threshold
WIN_RATE_THRESH     = 0.90       # 90%+ win rate
WIN_RATE_MIN_TRADES = 30         # minimum trades to apply win rate signal
SIZING_CV_THRESH    = 0.10       # coefficient of variation < 10%
SIZING_MIN_TRADES   = 30         # minimum trades for sizing signal
MIN_SIGNALS         = 2          # need this many signals to flag
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(traders)")
    cols = {r["name"] for r in cur.fetchall()}
    if "bot_suspect" not in cols:
        cur.execute(
            "ALTER TABLE traders ADD COLUMN bot_suspect BOOLEAN NOT NULL DEFAULT 0"
        )
        conn.commit()
        print("[BOT] Added bot_suspect column to traders table")
    else:
        print("[BOT] bot_suspect column already exists")


# ---------------------------------------------------------------------------
# Signal queries
# ---------------------------------------------------------------------------

def _signal1_crypto_short(conn: sqlite3.Connection) -> set[str]:
    """
    Traders where >50% of their trades are in Crypto markets that resolved
    within 24 hours of their end_date.

    Joins trades → markets on market_id to get resolution timing.
    Falls back to trades.market_category = 'Crypto' for trades whose market
    is not in the markets table.
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
                             m.market_id IS NULL          -- market not in table: count as short
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
        WHERE win_rate   >= :wr
          AND total_trades >= :min_t
    """, {"wr": WIN_RATE_THRESH, "min_t": WIN_RATE_MIN_TRADES})
    return {r["address"] for r in cur.fetchall()}


def _signal3_uniform_sizing(conn: sqlite3.Connection) -> set[str]:
    """
    Traders whose trade share sizes have a coefficient of variation < 10%.
    Uses the identity: Var(X) = E[X²] - E[X]²
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
            HAVING n   >= :min_t
               AND avg_s > 0
        )
        WHERE var_s < (:cv * avg_s) * (:cv * avg_s)
    """, {"min_t": SIZING_MIN_TRADES, "cv": SIZING_CV_THRESH})
    return {r["trader_address"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Leaderboard helpers
# ---------------------------------------------------------------------------

def _top50(conn: sqlite3.Connection, exclude: set[str] | None = None) -> list[dict]:
    cur = conn.cursor()
    if exclude:
        ph = ",".join("?" * len(exclude))
        cur.execute(f"""
            SELECT address, comprehensive_elo, total_trades, win_rate, username
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
              AND address NOT IN ({ph})
            ORDER BY comprehensive_elo DESC
            LIMIT 50
        """, list(exclude))
    else:
        cur.execute("""
            SELECT address, comprehensive_elo, total_trades, win_rate, username
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
            ORDER BY comprehensive_elo DESC
            LIMIT 50
        """)
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Flag + report
# ---------------------------------------------------------------------------

def _flag_suspects(conn: sqlite3.Connection, suspects: set[str]) -> int:
    if not suspects:
        return 0
    cur = conn.cursor()
    cur.executemany(
        "UPDATE traders SET bot_suspect = 1 WHERE address = ?",
        [(a,) for a in suspects],
    )
    conn.commit()
    return cur.rowcount


def _build_report(
    suspects: set[str],
    s1: set[str],
    s2: set[str],
    s3: set[str],
    top50_all: list[dict],
    top50_clean: list[dict],
) -> str:
    suspects_in_top50 = [r for r in top50_all if r["address"] in suspects]

    lines = [
        "🤖 *Bot Detection Report*",
        f"Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "*Detection signals (>=2 required to flag):*",
        f"  S1 (>50% short crypto trades): {len(s1):,} traders",
        f"  S2 (win rate >=90%, >=30 trades): {len(s2):,} traders",
        f"  S3 (uniform position sizing): {len(s3):,} traders",
        "",
        f"*Flagged (>=2 signals): {len(suspects):,} traders*",
        f"  In current top-50 ELO: {len(suspects_in_top50)}",
    ]

    if suspects_in_top50:
        lines.append("")
        lines.append("*Bot suspects in top-50 leaderboard:*")
        for r in suspects_in_top50:
            name = r.get("username") or r["address"][:12] + "..."
            sigs = []
            if r["address"] in s1: sigs.append("S1")
            if r["address"] in s2: sigs.append("S2")
            if r["address"] in s3: sigs.append("S3")
            lines.append(
                f"  {name}  ELO={r['comprehensive_elo']:.0f}  [{'+'.join(sigs)}]"
            )
    else:
        lines.append("  No bot suspects found in current top-50.")

    lines += [
        "",
        f"*Top-10 leaderboard with bot suspects removed* ({len(suspects):,} excluded):",
    ]
    for i, r in enumerate(top50_clean[:10], 1):
        name = r.get("username") or r["address"][:12] + "..."
        lines.append(
            f"  {i:>2}. {name:<22} ELO={r['comprehensive_elo']:.0f}"
            f"  T={r['total_trades']}  WR={r['win_rate']*100:.0f}%"
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

    _ensure_column(conn)

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

    top50_all   = _top50(conn)
    top50_clean = _top50(conn, exclude=suspects)

    report = _build_report(suspects, s1, s2, s3, top50_all, top50_clean)
    safe = report.encode("ascii", errors="replace").decode("ascii")
    print("\n" + safe.replace("*", "") + "\n")

    if not dry_run:
        written = _flag_suspects(conn, suspects)
        print(f"[BOT] Flagged {written} traders in DB")
        _send_telegram(report)
    else:
        print("[BOT] DRY RUN — no DB writes, no Telegram")

    conn.close()
    return {
        "flagged": len(suspects),
        "s1": len(s1), "s2": len(s2), "s3": len(s3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot trader detection")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report only — no DB writes, no Telegram")
    args = parser.parse_args()
    result = run_bot_detection(dry_run=args.dry_run)
    print(f"[BOT] Done — {result['flagged']} traders flagged")


if __name__ == "__main__":
    main()
