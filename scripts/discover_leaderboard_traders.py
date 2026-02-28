#!/usr/bin/env python3
"""
Leaderboard Trader Discovery — Channel 1 discovery.

Since Polymarket has no public leaderboard API, this script performs an
exhaustive sweep: it takes the top N most-traded geopolitics markets from
our database and fetches all recent participants from each market via the
Polymarket Data API.

Any trader found across those markets who isn't already in our database is
evaluated:
  - Fetch their full trade history
  - Count how many distinct geopolitics markets they've traded
  - If they meet the minimum threshold (3+ geo markets, 10+ trades, $1k+
    volume) → add to traders table with discovery_source='leaderboard'

This captures low-frequency high-conviction traders like Magamyman who trade
rarely but in large size across our target markets.

Usage:
    python scripts/discover_leaderboard_traders.py
    python scripts/discover_leaderboard_traders.py --limit 100 --dry-run
    python scripts/discover_leaderboard_traders.py --db data/polymarket_tracker.db
"""

import sys
import re
import json
import time
import sqlite3
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Project root ─────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ── Constants ─────────────────────────────────────────────────────────────────
TRADES_API      = "https://data-api.polymarket.com/trades"
REQUEST_DELAY   = 1.0
REQUEST_TIMEOUT = 15
MAX_RETRIES     = 2
MIN_GEO_MARKETS = 3
MIN_TRADES      = 10
MIN_VOLUME      = 1000.0


# ── Keyword filter (inlined from monitoring/monitor.py) ─────────────────────
EXCLUSION_KEYWORDS = [
    'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'xrp', 'ripple',
    'solana', 'sol', 'dogecoin', 'doge', 'cardano', 'ada',
    'price above', 'price below', 'up or down', 'dip to $',
    'fdv above', 'fdv >', 'fdv>', 'market cap >', 'market cap>',
    'one day after launch', 'day after launch', '1 day after launch',
    'airdrop', 'token launch', 'token airdrop',
    'gold close between', 'gold price', 'gold hits', 'gold hit', 'gold reaches',
    'gold above', 'gold below', 'gold closes', 'price of gold',
    'nvda', 'nvidia', 'tsla', 'tesla', 'aapl', 'apple',
    'msft', 'microsoft', 'googl', 'google', 'amzn', 'amazon',
    'meta', 'pltr', 'palantir', 'zm', 'zoom',
    'close at $', 'close above $', 'close below $',
    'finish week', 'quarterly earnings', 'beat earnings',
    'spread:', 'o/u ', 'over/under', 'moneyline',
    '(-', '(+',
    'touchdown', 'anytime touchdown', 'first touchdown',
    'nfl', 'nba', 'mlb', 'nhl', 'mls',
    'premier league', 'champions league',
    'serie a', 'bundesliga', 'ligue 1', 'la liga',
    'super bowl', 'world series', 'stanley cup',
    'win the championship', 'make the playoffs',
    'australian open', 'wimbledon', 'french open', 'us open',
    'wta', 'tennis championship', 'tennis open',
    'merida open', 'rio open', 'open akron',
    'atp 250', 'atp 500', 'wta 250',
    'ufc', 'mma', 'nascar', 'pga tour',
    'formula 1', 'formula one', 'f1 ',
    'grand prix', 'grand slam',
    'barcelona', 'manchester', 'real madrid', 'bayern',
    'liverpool', 'chelsea', 'arsenal', 'psg',
    'win on 2025', 'win on 202',
    'cruzeiro', 'flamengo', 'palmeiras', 'corinthians',
    'ohio state', 'georgia tech', 'alabama', 'michigan',
    'championship', 'playoff', 'vs.', 'game', 'match',
    'warriors', 'thunder', 'lakers', 'celtics', 'cowboys',
    'patriots', 'bills', 'chiefs', 'bengals',
    'maple leafs', 'bruins', 'atp',
    'academy award', 'oscar', 'oscars', 'grammy', 'grammys',
    'emmy', 'emmys', 'tony awards', 'golden globe', 'bafta',
    'cannes', 'sundance',
    'nominated for best', 'win best actor', 'win best actress',
    'win best director', 'win best picture', 'win best film',
    'best supporting actor', 'best supporting actress',
    'best documentary', 'best animated', 'best song',
    'best film editing', 'costume', 'editing', 'gross', 'grossing',
    'season', 'performance',
    'songwriter of the year', 'album of the year', 'record of the year',
    'most streamed', 'streamed on spotify', 'spotify',
    'movie', 'film', 'documentary', 'box office', 'opening weekend',
    'streamer of the year', 'twitch', 'kai cenat',
    'miss universe', 'miss world', 'beauty pageant',
    'venezuela', 'thailand', 'canada',
    'album', 'taylor swift',
    'temperature', 'highest temperature', 'weather',
    '#1 free app', 'app store', 'chatgpt', 'threads',
    'apple app store', 'google play',
    '#1 searched athlete', 'most searched', 'google searches',
    'caitlin clark', 'cristiano ronaldo', 'shohei ohtani',
    'simone biles', 'lamine yamal',
    'elon musk', 'tweet', 'x post',
    'fed rate', 'interest rate', 'stock market', 'sp500', 's&p',
    'esports', 'e-sports', 'gaming tournament',
    'major', 'starladder', 'iem', 'intel extreme masters',
    'blast', 'esl', 'pgl', 'faceit', 'dreamhack',
    'worlds', 'masters', 'champions', 'the international',
    'epic league', 'weplay', 'gamers galaxy', 'rog',
    'bo3', 'bo5', 'map winner',
    'g2 esports', 'team vitality', 'fnatic', 'astralis',
    'natus vincere', "na'vi", 'navi', 'furia',
    'team falcons', 'ninjas in pyjamas', 'faze clan', 'faze',
    'cloud9', 'team liquid', 'team spirit', 'heroic',
    'mousesports', 'mouz', 'complexity', 'parivision',
    'tyloo', 'eternal fire', 'saw', 'imperial',
    '9 pandas', 'betboom', 'virtus.pro', 'virtus pro',
    'ence', 'big', 'godsent', 'og esports',
    't1 esports', 'gen.g', 'drx', 'jd gaming',
    'edward gaming', 'royal never give up', 'fpx',
    'nongshim', 'kt rolster', 'dplus', 'geng', 'kwangdong',
    'hanwha', 'diplus', 'sandbox gaming',
    'cs:go', 'csgo', 'counter-strike', 'counter strike', 'cs2',
    'league of legends', 'lol:', 'valorant', 'dota 2', 'dota2', 'dota',
    'overwatch', 'fortnite', 'rocket league', 'apex legends',
    'call of duty', 'rainbow six',
    'test match', 'odi', 't20', 'cricket world cup', 'ashes',
    'ipl', 'big bash', 'county championship',
    'rugby world cup', 'six nations', 'tri nations', 'super rugby',
    'rugby championship', 'rugby league',
    'match on', 'game on', 'fixture', 'vs on', 'versus on',
]


def _is_geopolitics(title: str) -> bool:
    tl = title.lower()
    for kw in EXCLUSION_KEYWORDS:
        if kw in tl:
            return False
    if re.search(r'spread:.*\(-?\d+\.?\d*\)', tl):
        return False
    if re.search(r'o/u\s+\d+\.?\d*', tl):
        return False
    if re.search(r'close at \$\d+-\$\d+', tl):
        return False
    if re.search(r'gold.*\$\d+.*and.*\$\d+', tl):
        return False
    return True


def _fetch_market_trades(market_id: str) -> list:
    url = f"{TRADES_API}?market={market_id}&limit=500"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read())
                return data if isinstance(data, list) else []
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(2)
    return []


def _fetch_trader_trades(address: str) -> list:
    url = f"{TRADES_API}?user={address}&limit=500"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read())
                return data if isinstance(data, list) else []
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(2)
    return []


def _ensure_columns(conn: sqlite3.Connection):
    for ddl in [
        "ALTER TABLE traders ADD COLUMN discovery_source TEXT DEFAULT 'live_feed'",
        "ALTER TABLE traders ADD COLUMN watched INTEGER DEFAULT 0",
        "ALTER TABLE traders ADD COLUMN username TEXT",
    ]:
        try:
            conn.execute(ddl)
            col = ddl.split("ADD COLUMN")[1].strip().split()[0]
            print(f"[DB] Added '{col}' column to traders table.")
        except sqlite3.OperationalError:
            pass
    conn.commit()


class LeaderboardDiscovery:
    def __init__(self, db_path: str, market_limit: int = 50, dry_run: bool = False):
        self.db_path     = db_path
        self.market_limit = market_limit
        self.dry_run     = dry_run

    def run(self):
        print("=" * 70)
        print("  Leaderboard Trader Discovery — Channel 1")
        print(f"  Market sweep limit: top {self.market_limit} markets by trade count")
        print(f"  Min geo markets for flagging: {MIN_GEO_MARKETS}")
        print(f"  Dry run: {self.dry_run}")
        print("=" * 70)

        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_columns(conn)
        cur = conn.cursor()

        # ── [1/5] Select top markets ──────────────────────────────────────────
        # Use markets with RECENT activity (last 90 days) so the API still
        # serves trades for them — old/closed markets return 0 from the API.
        print(f"\n[1/5] Selecting top {self.market_limit} active markets (last 90 days)...")
        cur.execute("""
            SELECT tr.market_id, COUNT(*) as trade_cnt,
                   MAX(COALESCE(m.title, tr.market_title)) as title
            FROM trades tr
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE tr.timestamp >= datetime('now', '-90 days')
            GROUP BY tr.market_id
            ORDER BY trade_cnt DESC
            LIMIT ?
        """, (self.market_limit,))
        markets = cur.fetchall()
        print(f"      Found {len(markets)} markets.")

        # ── [2/5] Load existing trader addresses ─────────────────────────────
        print(f"\n[2/5] Loading existing trader addresses from DB...")
        cur.execute("SELECT address FROM traders")
        known_addresses = {row[0].lower() for row in cur.fetchall()}
        print(f"      {len(known_addresses)} traders already known.")

        # ── [3/5] Sweep markets for new addresses ────────────────────────────
        print(f"\n[3/5] Sweeping {len(markets)} markets for new participant wallets...\n")

        # address -> (source_market_title, username_from_trade)
        new_addresses: dict[str, tuple[str, str | None]] = {}

        for idx, (market_id, trade_cnt, title) in enumerate(markets, 1):
            title_short = (title or market_id)[:55].encode("ascii", "replace").decode("ascii")
            print(f"  [{idx:>2}/{len(markets)}] {title_short}  (DB trades: {trade_cnt})")

            market_trades = _fetch_market_trades(market_id)

            new_here = 0
            for t in market_trades:
                wallet = (t.get("proxyWallet") or t.get("maker") or "").lower()
                if not wallet:
                    continue
                if wallet in known_addresses or wallet in new_addresses:
                    continue
                # Grab inline username if available
                name   = (t.get("name") or "").strip()
                pseudo = (t.get("pseudonym") or "").strip()
                username = None
                if name and not name.startswith("0x"):
                    username = name
                elif pseudo and not pseudo.startswith("0x"):
                    username = pseudo
                new_addresses[wallet] = (title or market_id, username)
                new_here += 1

            print(f"         New wallets this market: {new_here} | Total new: {len(new_addresses)}")

            if idx < len(markets):
                time.sleep(REQUEST_DELAY)

        print(f"\n      Total new unique addresses to evaluate: {len(new_addresses)}")

        if not new_addresses:
            print("\n      No new addresses found. All market participants already known.")
            conn.close()
            return

        # ── [4/5] Evaluate each new address (writes incrementally) ───────────
        # Re-fetch known addresses so we can skip any already inserted by a
        # previous interrupted run (resume capability).
        cur.execute("SELECT address FROM traders")
        known_addresses = {row[0].lower() for row in cur.fetchall()}

        candidates = [(addr, info) for addr, info in new_addresses.items()
                      if addr not in known_addresses]
        skipped_resume = len(new_addresses) - len(candidates)
        if skipped_resume:
            print(f"      Skipping {skipped_resume} already-inserted addresses (resume).")

        print(f"\n[4/5] Evaluating {len(candidates)} candidates (writes after each, resumable)...\n")

        added   = 0
        flagged = 0
        failed  = 0
        results = []  # kept for summary only

        for i, (address, (source_title, inline_username)) in enumerate(candidates, 1):
            trades = _fetch_trader_trades(address)

            if not trades:
                failed += 1
                time.sleep(REQUEST_DELAY)
                continue

            geo_markets  = set()
            total_volume = 0.0
            total_trades = len(trades)
            username     = inline_username

            for t in trades:
                title  = (t.get("title") or "").strip()
                size   = float(t.get("size",  0) or 0)
                price  = float(t.get("price", 0) or 0)
                total_volume += size * price

                if title and _is_geopolitics(title):
                    geo_markets.add(title)

                if username is None:
                    name   = (t.get("name") or "").strip()
                    pseudo = (t.get("pseudonym") or "").strip()
                    if name and not name.startswith("0x"):
                        username = name
                    elif pseudo and not pseudo.startswith("0x"):
                        username = pseudo

            should_flag = (
                len(geo_markets) >= MIN_GEO_MARKETS
                and total_trades  >= MIN_TRADES
                and total_volume  >= MIN_VOLUME
            )
            status = "FLAG" if should_flag else "---"

            if i <= 30 or should_flag:
                name_disp = (username or "(anon)")[:18].encode("ascii", "replace").decode("ascii")
                print(
                    f"  {i:>4}/{len(candidates)}  {address[:12]}  "
                    f"geo={len(geo_markets):>2}  vol=${total_volume:>9,.0f}  "
                    f"trades={total_trades:>4}  [{status}]  {name_disp}"
                )

            results.append((address, len(geo_markets), total_trades, total_volume, username, should_flag, status))

            # Write immediately so progress survives interruption
            if not self.dry_run:
                for _attempt in range(5):
                    try:
                        cur.execute("""
                            INSERT INTO traders (
                                address, total_trades, successful_trades, win_rate,
                                total_volume, is_flagged, discovery_source, username, last_updated
                            ) VALUES (?, ?, 0, 0.0, ?, ?, 'leaderboard', ?, ?)
                            ON CONFLICT(address) DO NOTHING
                        """, (address, total_trades, total_volume, should_flag, username, datetime.now()))
                        if cur.rowcount > 0:
                            added += 1
                            if should_flag:
                                flagged += 1
                        # Commit every 50 inserts to keep WAL small
                        if added % 50 == 0:
                            conn.commit()
                        break
                    except sqlite3.OperationalError as e:
                        if "locked" in str(e):
                            time.sleep(3)
                        else:
                            raise

            if i < len(candidates):
                time.sleep(REQUEST_DELAY)

        if not self.dry_run:
            conn.commit()

        # ── [5/5] Summary ─────────────────────────────────────────────────────
        print(f"\n[5/5] Done.")

        conn.close()

        # ── Summary ───────────────────────────────────────────────────────────
        flagged_count = sum(1 for r in results if r[5])

        print()
        print("=" * 70)
        print("  RESULTS — Leaderboard Discovery")
        print("=" * 70)
        print(f"  Markets swept:          {len(markets)}")
        print(f"  New addresses found:    {len(new_addresses)}")
        print(f"  Evaluated:              {len(results)}")
        print(f"  Traders added to DB:    {added}")
        print(f"  Newly flagged:          {flagged}")
        print(f"  Meet criteria (total):  {flagged_count}")
        print(f"  API failures:           {failed}")
        if self.dry_run:
            print(f"  (DRY RUN — no writes)")

        if flagged_count > 0:
            print(f"\n  Top flagged discoveries (by volume):")
            flagged_results = [(r[0], r[1], r[2], r[3], r[4]) for r in results if r[5]]
            flagged_results.sort(key=lambda x: x[3], reverse=True)
            for addr, geo_ct, trades, vol, username in flagged_results[:10]:
                name_safe = (username or "(anon)").encode("ascii", "replace").decode("ascii")
                print(f"    {addr[:12]}  geo={geo_ct}  trades={trades}  vol=${vol:,.0f}  {name_safe}")

        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Sweep top geopolitics markets to discover new traders."
    )
    parser.add_argument("--db", default="data/polymarket_tracker.db",
                        help="Path to SQLite database")
    parser.add_argument("--limit", type=int, default=50,
                        help="Number of top markets to sweep (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch but don't write to database")
    args = parser.parse_args()

    discovery = LeaderboardDiscovery(
        db_path=args.db,
        market_limit=args.limit,
        dry_run=args.dry_run,
    )
    discovery.run()


if __name__ == "__main__":
    main()
