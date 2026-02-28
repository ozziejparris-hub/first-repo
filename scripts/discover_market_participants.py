#!/usr/bin/env python3
"""
Discover Market Participants — Channel 2 discovery.

For every high-signal geopolitics market in our DB (those with 3+ flagged
traders already positioned), fetch ALL recent participants from the Polymarket
API. Any wallet address not yet in our database is added for ELO evaluation.

This ensures that for any market where elite traders are active, we capture
every other participant — including low-frequency high-conviction traders like
Magamyman who never surface in the rolling 500-trade feed.

Usage:
    python scripts/discover_market_participants.py
    python scripts/discover_market_participants.py --min-elite-traders 2
    python scripts/discover_market_participants.py --db data/polymarket_tracker.db --dry-run
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
TRADES_API     = "https://data-api.polymarket.com/trades"
REQUEST_DELAY  = 1.0
REQUEST_TIMEOUT = 15
MAX_RETRIES    = 2
MIN_GEO_MARKETS = 3    # Minimum distinct geopolitics markets to flag a new trader
MIN_TRADES      = 10   # Minimum trade count to even evaluate
MIN_VOLUME      = 1000.0  # Minimum $ volume to evaluate ($1k — lower than main system for discovery)


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
    """Return True if the market title passes the geopolitics filter."""
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
    """Fetch up to 500 recent trades for a market conditionId."""
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
    """Fetch up to 500 trades for a specific trader address."""
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


class MarketParticipantDiscovery:
    def __init__(self, db_path: str, min_elite_traders: int = 3, dry_run: bool = False):
        self.db_path = db_path
        self.min_elite_traders = min_elite_traders
        self.dry_run = dry_run

    def run(self):
        print("=" * 70)
        print("  Market Participant Discovery — Channel 2")
        print(f"  Min elite traders per market: {self.min_elite_traders}")
        print(f"  Dry run: {self.dry_run}")
        print("=" * 70)

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_columns(conn)
        cur = conn.cursor()

        # ── [1/4] Find high-signal markets ───────────────────────────────────
        # Only consider markets with recent activity (last 90 days) so the
        # Polymarket API still serves their trades.
        print(f"\n[1/4] Finding high-signal markets ({self.min_elite_traders}+ flagged traders, last 90 days)...")
        cur.execute("""
            SELECT tr.market_id, COUNT(DISTINCT tr.trader_address) AS elite_count,
                   MAX(COALESCE(m.title, tr.market_title)) AS title
            FROM trades tr
            JOIN traders t ON tr.trader_address = t.address
            LEFT JOIN markets m ON tr.market_id = m.market_id
            WHERE t.is_flagged = 1
              AND tr.timestamp >= datetime('now', '-90 days')
            GROUP BY tr.market_id
            HAVING elite_count >= ?
            ORDER BY elite_count DESC
            LIMIT 30
        """, (self.min_elite_traders,))
        markets = cur.fetchall()
        print(f"      Found {len(markets)} high-signal markets.")

        if not markets:
            print("      No qualifying markets found. Exiting.")
            conn.close()
            return

        # ── [2/4] Load existing trader addresses ─────────────────────────────
        print(f"\n[2/4] Loading existing trader addresses...")
        cur.execute("SELECT address FROM traders")
        known_addresses = {row[0].lower() for row in cur.fetchall()}
        print(f"      {len(known_addresses)} traders already in database.")

        # ── [3/4] Sweep market participants ──────────────────────────────────
        print(f"\n[3/4] Sweeping {len(markets)} markets for new participants...\n")

        all_new_addresses: dict[str, str] = {}  # address -> market_title

        for idx, (market_id, elite_count, title) in enumerate(markets, 1):
            title_short = (title or market_id)[:55].encode("ascii", "replace").decode("ascii")
            print(f"  [{idx:>2}/{len(markets)}] {title_short}")
            print(f"         Elite traders: {elite_count}  |  Market: {market_id[:20]}...")

            trades = _fetch_market_trades(market_id)

            new_in_market = 0
            for trade in trades:
                wallet = (trade.get("proxyWallet") or trade.get("maker") or "").lower()
                if wallet and wallet not in known_addresses and wallet not in all_new_addresses:
                    all_new_addresses[wallet] = title or market_id
                    new_in_market += 1

            print(f"         New addresses found: {new_in_market} (total new so far: {len(all_new_addresses)})")

            if idx < len(markets):
                time.sleep(REQUEST_DELAY)

        print(f"\n      Total new unique addresses to evaluate: {len(all_new_addresses)}")

        # ── [4/4] Evaluate and store new traders ─────────────────────────────
        print(f"\n[4/4] Evaluating {len(all_new_addresses)} new addresses...\n")

        added        = 0
        flagged      = 0
        skipped_thin = 0
        failed       = 0

        for i, (address, source_market) in enumerate(all_new_addresses.items(), 1):
            trades = _fetch_trader_trades(address)

            if not trades:
                failed += 1
                if i <= 5:
                    print(f"  {i:>4}/{len(all_new_addresses)}  {address[:12]}  -> no trades returned")
                time.sleep(REQUEST_DELAY)
                continue

            # Tally geopolitics markets and volume
            geo_markets   = set()
            total_volume  = 0.0
            total_trades  = len(trades)

            for t in trades:
                title = (t.get("title") or "").strip()
                size  = float(t.get("size", 0) or 0)
                price = float(t.get("price", 0) or 0)
                total_volume += size * price

                if title and _is_geopolitics(title):
                    geo_markets.add(title)

            # Resolve username from trade data (trades include name/pseudonym)
            username = None
            for t in trades:
                name = (t.get("name") or "").strip()
                pseudo = (t.get("pseudonym") or "").strip()
                if name and not name.startswith("0x"):
                    username = name
                    break
                if pseudo and not pseudo.startswith("0x"):
                    username = pseudo
                    break

            is_flagged = (
                len(geo_markets) >= MIN_GEO_MARKETS
                and total_trades  >= MIN_TRADES
                and total_volume  >= MIN_VOLUME
            )

            status = "FLAG" if is_flagged else ("thin" if total_trades < MIN_TRADES else "---")

            if total_trades < MIN_TRADES:
                skipped_thin += 1
            else:
                if i <= 20 or is_flagged:
                    name_display = (username or "(anon)")[:20].encode("ascii", "replace").decode("ascii")
                    print(
                        f"  {i:>4}/{len(all_new_addresses)}  {address[:12]}  "
                        f"geo={len(geo_markets):>2}  vol=${total_volume:>9,.0f}  "
                        f"trades={total_trades:>4}  [{status}]  {name_display}"
                    )

            if not self.dry_run:
                cur.execute("""
                    INSERT INTO traders (
                        address, total_trades, successful_trades, win_rate,
                        total_volume, is_flagged, discovery_source, username, last_updated
                    ) VALUES (?, ?, 0, 0.0, ?, ?, 'market_scan', ?, ?)
                    ON CONFLICT(address) DO NOTHING
                """, (address, total_trades, total_volume, is_flagged, username, datetime.now()))
                conn.commit()

            added += 1
            if is_flagged:
                flagged += 1

            # Update known set so duplicates across markets aren't re-added
            known_addresses.add(address)

            time.sleep(REQUEST_DELAY)

        conn.close()

        # ── Summary ───────────────────────────────────────────────────────────
        print()
        print("=" * 70)
        print("  RESULTS — Market Participant Discovery")
        print("=" * 70)
        print(f"  Markets swept:          {len(markets)}")
        print(f"  New addresses found:    {len(all_new_addresses)}")
        print(f"  Traders added to DB:    {added}")
        print(f"  Newly flagged:          {flagged}")
        print(f"  Too few trades (<{MIN_TRADES}):  {skipped_thin}")
        print(f"  API failures:           {failed}")
        if self.dry_run:
            print(f"  (DRY RUN — no writes performed)")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Discover participants in high-signal geopolitics markets."
    )
    parser.add_argument("--db", default="data/polymarket_tracker.db",
                        help="Path to SQLite database")
    parser.add_argument("--min-elite-traders", type=int, default=3,
                        help="Min flagged traders per market to qualify (default: 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch but don't write to database")
    args = parser.parse_args()

    discovery = MarketParticipantDiscovery(
        db_path=args.db,
        min_elite_traders=args.min_elite_traders,
        dry_run=args.dry_run,
    )
    discovery.run()


if __name__ == "__main__":
    main()
