#!/usr/bin/env python3
"""
Validate and correct market titles in the DB against the Polymarket Gamma API.

Targets markets that matter most:
  - Markets with open positions held by legendary traders (ELO > 2175,
    research_excluded=0, resolved_trades_count >= 20, bot_type IS NULL)
  - Markets referenced in the last 30 days by any research-pool trader

For each target market, fetches the current title from the Gamma API via the
direct /markets/{api_id} endpoint and updates the DB if the title has drifted.
Markets without a numeric api_id are skipped (cannot be looked up directly).

Usage:
    python scripts/verify_market_titles.py            # live run
    python scripts/verify_market_titles.py --dry-run  # log mismatches only
"""

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).parent.parent
DB_PATH = _REPO_ROOT / "data" / "polymarket_tracker.db"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
REQUEST_TIMEOUT = 5   # seconds per API call
SLEEP_BETWEEN = 1.0   # seconds between requests


TARGET_MARKETS_SQL = """
SELECT DISTINCT m.condition_id, m.api_id, m.title
FROM markets m
WHERE m.condition_id IN (
    SELECT DISTINCT p.market_id FROM positions p
    JOIN traders t ON t.address = p.trader_address
    WHERE t.comprehensive_elo > 2175
      AND t.research_excluded = 0
      AND t.resolved_trades_count >= 20
      AND t.bot_type IS NULL
      AND p.status = 'open'
)
OR m.condition_id IN (
    SELECT DISTINCT tr.market_id FROM trades tr
    JOIN traders t ON t.address = tr.trader_address
    WHERE t.research_excluded = 0
      AND tr.timestamp >= datetime('now', '-30 days')
)
"""


def fetch_api_title(session: requests.Session, api_id: str) -> str | None:
    """Return the current title from the Gamma API, or None on failure."""
    try:
        resp = session.get(f"{GAMMA_API_BASE}/markets/{api_id}", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            market = data[0] if data else None
        else:
            market = data
        if not market:
            return None
        return market.get("question") or market.get("title") or None
    except Exception as e:
        print(f"  [WARN] API error for api_id={api_id}: {e}")
        return None


def send_telegram(message: str) -> None:
    async def _send(msg: str) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.expanduser("~/.env_trading"))
            token = os.getenv("telegram_alerts_token")
            chat_id = os.getenv("telegram_chat_id")
            if not token or not chat_id:
                print("[WARN] Telegram credentials not found in ~/.env_trading")
                return
            sys.path.insert(0, str(_REPO_ROOT))
            from monitoring.telegram_health_bot import TelegramHealthBot
            bot = TelegramHealthBot(token=token, chat_id=chat_id)
            await bot._send_message(msg)
        except Exception as e:
            print(f"[WARN] Telegram send failed: {e}")

    asyncio.run(_send(message))


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and correct market titles against Gamma API")
    parser.add_argument("--dry-run", action="store_true", help="Log mismatches but make no DB writes")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    run_start = time.time()
    print(f"[verify_market_titles] {'DRY RUN — ' if args.dry_run else ''}starting at {datetime.now():%Y-%m-%d %H:%M:%S}")

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    try:
        rows = conn.execute(TARGET_MARKETS_SQL).fetchall()
    except Exception as e:
        print(f"[ERROR] Failed to query target markets: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    print(f"[verify_market_titles] {len(rows):,} markets to check")

    session = requests.Session()
    checked = 0
    updated = 0
    skipped_no_id = 0
    skipped_api_err = 0
    update_log: list[dict] = []

    for condition_id, api_id, db_title in rows:
        if not api_id:
            skipped_no_id += 1
            continue

        checked += 1
        if checked > 1:
            time.sleep(SLEEP_BETWEEN)

        api_title = fetch_api_title(session, api_id)

        if api_title is None:
            skipped_api_err += 1
            continue

        api_title_clean = api_title.strip()
        db_title_clean = (db_title or "").strip()

        if api_title_clean == db_title_clean:
            continue

        # Mismatch found
        print(f"  [MISMATCH] condition_id={condition_id[:20]}… api_id={api_id}")
        print(f"    DB : {db_title_clean!r}")
        print(f"    API: {api_title_clean!r}")

        if not args.dry_run:
            try:
                conn.execute(
                    "UPDATE markets SET title = ? WHERE condition_id = ?",
                    (api_title_clean, condition_id),
                )
                conn.commit()
                print(f"    → updated")
                updated += 1
            except Exception as e:
                print(f"  [ERROR] DB update failed for condition_id={condition_id[:20]}…: {e}")
                skipped_api_err += 1
        else:
            print(f"    → (dry-run, not written)")
            updated += 1

        update_log.append({"condition_id": condition_id, "old": db_title_clean, "new": api_title_clean})

    conn.close()
    elapsed = time.time() - run_start

    tag = "DRY RUN" if args.dry_run else "DONE"
    print(f"\n[verify_market_titles] {tag}")
    print(f"  Markets checked       : {checked:,}")
    print(f"  Titles {'would update' if args.dry_run else 'updated'}       : {updated:,}")
    print(f"  Skipped (no api_id)   : {skipped_no_id:,}")
    print(f"  Skipped (API errors)  : {skipped_api_err:,}")
    print(f"  Run time              : {elapsed:.1f}s")

    if updated > 0 and not args.dry_run:
        lines = [f"• {e['old']!r}\n  → {e['new']!r}" for e in update_log]
        msg = (
            f"📝 <b>Market title corrections ({updated})</b>\n\n"
            + "\n\n".join(lines)
        )
        send_telegram(msg)


if __name__ == "__main__":
    main()
