"""
wash_trade_audit.py

Identifies wallets exhibiting wash-trade patterns in the trades table.

Detection signals (ALL must fire to flag — avoids false-positives on
normal open/close trading):
  1. Wallet has both BUY and SELL trades in the same market
  2. At least one BUY→SELL round-trip in that market completes in < 60 seconds

A wallet triggering signal 1 alone is a normal position closer.
A wallet triggering both 1 and 2 has an economic-purpose-free round-trip
that resembles wash trading.

Additional informational signal (reported but not used for flagging alone):
  3. > 80% of trades at price < $0.01  (penny/dust trades)

Adds wash_trade_suspect column (BOOLEAN, default 0) to traders if missing.
Flags suspected wallets. Does NOT delete any data.

Usage:
    python scripts/wash_trade_audit.py
    python scripts/wash_trade_audit.py --dry-run   # no DB writes, no Telegram
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
_REPO   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB     = os.path.join(_REPO, 'data', 'polymarket_tracker.db')
ROUND_TRIP_SECS = 60
PENNY_THRESHOLD = 0.01
PENNY_FRACTION  = 0.80
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection) -> None:
    """Add wash_trade_suspect column if absent."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(traders)")
    cols = {r["name"] for r in cur.fetchall()}
    if "wash_trade_suspect" not in cols:
        cur.execute(
            "ALTER TABLE traders ADD COLUMN wash_trade_suspect BOOLEAN NOT NULL DEFAULT 0"
        )
        conn.commit()
        print("[WASH] Added wash_trade_suspect column to traders table")
    else:
        print("[WASH] wash_trade_suspect column already exists")


# ---------------------------------------------------------------------------
# Signal queries
# ---------------------------------------------------------------------------

def _signal1_both_sides(conn: sqlite3.Connection) -> set[str]:
    """Wallets with BUY and SELL in at least one shared market."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT trader_address
        FROM (
            SELECT trader_address, market_id,
                   SUM(CASE WHEN side='BUY'  THEN 1 ELSE 0 END) AS buys,
                   SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS sells
            FROM trades
            GROUP BY trader_address, market_id
        )
        WHERE buys > 0 AND sells > 0
    """)
    return {r["trader_address"] for r in cur.fetchall()}


def _signal2_rapid_roundtrip(
    conn: sqlite3.Connection,
    candidate_addrs: set[str],
) -> set[str]:
    """
    Among *candidate_addrs* (already known to have both sides), find wallets
    with at least one BUY→SELL round-trip in the same market under 60 seconds.

    Scoping to candidates first reduces the self-join from O(N²) on 1M rows
    to O(k²) on the small candidate set (~217 wallets).
    """
    if not candidate_addrs:
        return set()

    suspects: set[str] = set()
    cur = conn.cursor()

    # Process one wallet at a time to keep each query tiny
    for addr in candidate_addrs:
        cur.execute("""
            SELECT 1
            FROM   trades a
            JOIN   trades b
              ON   b.trader_address = a.trader_address
             AND   b.market_id      = a.market_id
             AND   b.side           = 'SELL'
             AND   b.trade_id      != a.trade_id
            WHERE  a.trader_address = ?
              AND  a.side           = 'BUY'
              AND  (
                  CAST(strftime('%s', b.timestamp) AS INTEGER)
                  - CAST(strftime('%s', a.timestamp) AS INTEGER)
              ) BETWEEN 0 AND ?
            LIMIT  1
        """, (addr, ROUND_TRIP_SECS))
        if cur.fetchone():
            suspects.add(addr)

    return suspects


def _signal3_penny_trades(conn: sqlite3.Connection) -> set[str]:
    """Informational: wallets where >80% of trades are at price < $0.01."""
    cur = conn.cursor()
    cur.execute("""
        SELECT trader_address
        FROM (
            SELECT trader_address,
                   COUNT(*) AS n,
                   SUM(CASE WHEN price < :thresh THEN 1.0 ELSE 0.0 END) AS penny
            FROM trades
            GROUP BY trader_address
            HAVING n >= 5
        )
        WHERE (penny / n) > :frac
    """, {"thresh": PENNY_THRESHOLD, "frac": PENNY_FRACTION})
    return {r["trader_address"] for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Leaderboard helpers
# ---------------------------------------------------------------------------

def _top50(conn: sqlite3.Connection, exclude: set[str] | None = None) -> list[dict]:
    cur = conn.cursor()
    if exclude:
        placeholders = ",".join("?" * len(exclude))
        cur.execute(f"""
            SELECT address, comprehensive_elo, total_trades, win_rate, username
            FROM traders
            WHERE comprehensive_elo IS NOT NULL
              AND address NOT IN ({placeholders})
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


def _elo_1500_count(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM traders WHERE comprehensive_elo >= 1500")
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Flag + report
# ---------------------------------------------------------------------------

def _flag_suspects(conn: sqlite3.Connection, suspects: set[str]) -> int:
    """Set wash_trade_suspect = 1 for all suspected wallets. Returns rows written."""
    if not suspects:
        return 0
    cur = conn.cursor()
    cur.executemany(
        "UPDATE traders SET wash_trade_suspect = 1 WHERE address = ?",
        [(a,) for a in suspects],
    )
    conn.commit()
    return cur.rowcount


def _build_report(
    suspects: set[str],
    s1: set[str],
    s2: set[str],
    s3: set[str],
    total_elo1500: int,
    top50_all: list[dict],
    top50_clean: list[dict],
) -> str:
    flagged_elo1500 = len({a for a in suspects
                           if any(r for r in top50_all if r["address"] == a)})
    # How many of the flagged are ELO >= 1500
    pct_elo1500 = (
        len(s1 & s2) / total_elo1500 * 100.0 if total_elo1500 else 0.0
    )

    flagged_in_top50 = [r for r in top50_all if r["address"] in suspects]

    lines = [
        "🚨 *Wash Trade Audit Report*",
        f"Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"*Detection criteria*",
        f"  Signal 1 (BUY+SELL same market): {len(s1):,} wallets",
        f"  Signal 2 (round-trip < {ROUND_TRIP_SECS}s): {len(s2):,} wallets",
        f"  Signal 3 (>80% penny trades, info only): {len(s3):,} wallets",
        "",
        f"*Flagged (S1 AND S2)*: {len(suspects):,} traders",
        f"  Of ELO >= 1500 traders ({total_elo1500:,}): {pct_elo1500:.1f}% flagged",
        f"  Suspects in current top-50: {len(flagged_in_top50)}",
    ]

    if flagged_in_top50:
        lines.append("")
        lines.append("*Suspects found in top-50 leaderboard:*")
        for r in flagged_in_top50:
            name = r.get("username") or r["address"][:12] + "..."
            lines.append(f"  {name}  ELO={r['comprehensive_elo']:.0f}")

    lines += [
        "",
        f"*Top-10 leaderboard with suspects removed* ({len(suspects):,} excluded):",
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
            print("[WASH] Telegram credentials not found in .env — skipping send")
            return
        from monitoring.telegram_health_bot import TelegramHealthBot
        bot = TelegramHealthBot(token=token, chat_id=chat_id)
        bot._send_message(message)
        print("[WASH] Report sent to Telegram")
    except Exception as e:
        print(f"[WASH] Telegram error: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_wash_trade_audit(dry_run: bool = False) -> dict:
    print("[WASH] Starting wash trade audit...")
    conn = _get_conn()

    _ensure_column(conn)

    print("[WASH] Computing Signal 1 (same-market BUY+SELL)...")
    s1 = _signal1_both_sides(conn)
    print(f"  {len(s1):,} wallets")

    print("[WASH] Computing Signal 2 (round-trip < 60s, scoped to S1 candidates)...")
    s2 = _signal2_rapid_roundtrip(conn, s1)
    print(f"  {len(s2):,} wallets")

    print("[WASH] Computing Signal 3 (penny trades, informational)...")
    s3 = _signal3_penny_trades(conn)
    print(f"  {len(s3):,} wallets")

    suspects = s1 & s2
    print(f"[WASH] Suspects (S1 AND S2): {len(suspects):,}")

    total_elo1500 = _elo_1500_count(conn)
    top50_all   = _top50(conn)
    top50_clean = _top50(conn, exclude=suspects)

    report = _build_report(suspects, s1, s2, s3, total_elo1500, top50_all, top50_clean)
    safe = report.encode("ascii", errors="replace").decode("ascii")
    print("\n" + safe.replace("*", "") + "\n")

    if not dry_run:
        written = _flag_suspects(conn, suspects)
        print(f"[WASH] Flagged {written} traders in DB")
        _send_telegram(report)
    else:
        print("[WASH] DRY RUN — no DB writes, no Telegram")

    conn.close()
    return {"flagged": len(suspects), "s1": len(s1), "s2": len(s2), "s3": len(s3)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Wash trade audit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report only — no DB writes, no Telegram")
    args = parser.parse_args()
    result = run_wash_trade_audit(dry_run=args.dry_run)
    print(f"[WASH] Done — {result['flagged']} traders flagged")


if __name__ == "__main__":
    main()
