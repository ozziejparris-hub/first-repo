import asyncio
import re
import time
from datetime import datetime
from typing import Optional, Dict
from .database import Database
from .polymarket_client import PolymarketClient
from .telegram_bot import TelegramNotifier
from .trader_analyzer import TraderAnalyzer

# AI Filtering Configuration
AI_FILTERING_ENABLED = True  # Toggle AI filtering on/off
AI_FILTER_MODE = "hybrid"  # Options: "keywords_only", "hybrid", "ai_only"


class PolymarketMonitor:
    """Main monitoring service that coordinates all components."""

    def __init__(self, polymarket_api_key: str, telegram_token: str,
                 telegram_chat_id: Optional[str] = None,
                 check_interval: int = 900,  # 900 seconds = 15 minutes
                 ai_agent = None):  # AI agent for intelligent categorization
        self.db = Database()
        self.polymarket = PolymarketClient(polymarket_api_key)
        self.telegram = TelegramNotifier(telegram_token, telegram_chat_id)
        self.analyzer = TraderAnalyzer(self.db, self.polymarket)
        self.ai_agent = ai_agent  # Store AI agent
        self.check_interval = check_interval
        self.is_running = False

        # Cache for AI categorization to avoid repeated API calls
        self.ai_cache: Dict[str, bool] = {}

        # Set stop callback
        self.telegram.set_stop_callback(self.request_stop)

    def request_stop(self):
        """Request the monitor to stop."""
        print("🛑 Stop requested via Telegram")
        self.is_running = False

    async def _ai_categorization_check(self, market_title: str) -> bool:
        """
        Use AI to determine if market should be excluded.

        Returns True = EXCLUDE, False = INCLUDE
        """
        # Check cache first
        if market_title in self.ai_cache:
            return self.ai_cache[market_title]

        try:
            # Call Mistral via Pydantic AI
            result = await self.ai_agent.run(
                f"Categorize this Polymarket prediction market:\n\n"
                f"Title: {market_title}\n\n"
                f"IMPORTANT: Vague 'Will [country/team] win?' without context is usually SPORTS.\n"
                f"- Geopolitics example: 'Will José Antonio Kast win the Chilean presidential election?' (specific)\n"
                f"- Sports example: 'Will Australia win?' (vague, no election/government context)\n\n"
                f"Categories:\n"
                f"- GEOPOLITICS: Elections, wars, international relations, diplomacy, government policy\n"
                f"- ECONOMICS: Fed rates, GDP, inflation, trade policy, economic indicators\n"
                f"- SPORTS: Any sports betting, spreads, game outcomes, athlete performance, vague match predictions\n"
                f"- CRYPTO: Cryptocurrency prices, Bitcoin, Ethereum, Solana, etc.\n"
                f"- STOCKS: Stock prices, earnings, company performance\n"
                f"- ENTERTAINMENT: Movies, music, celebrities, beauty pageants, app rankings\n"
                f"- OTHER: Weather, personal predictions, misc\n\n"
                f"Respond with ONLY the category name (one word).\n"
                f"If it's clearly GEOPOLITICS or ECONOMICS, respond: KEEP\n"
                f"Otherwise, respond: EXCLUDE"
            )

            # Parse AI response - try multiple attribute access methods
            response_text = ""
            if hasattr(result, 'data'):
                response_text = str(result.data)
            elif hasattr(result, 'output'):
                response_text = str(result.output)
            elif hasattr(result, 'text'):
                response_text = str(result.text)
            else:
                response_text = str(result)

            # Check if AI says to exclude
            should_exclude = False
            if 'EXCLUDE' in response_text.upper():
                print(f"[AI FILTER] ❌ Excluding: {market_title[:50]}... (AI classified as non-geopolitics)")
                should_exclude = True
            elif 'KEEP' in response_text.upper():
                print(f"[AI FILTER] ✓ Keeping: {market_title[:50]}... (AI classified as geopolitics)")
                should_exclude = False
            else:
                # If AI response unclear, check for category keywords
                exclude_categories = ['SPORTS', 'CRYPTO', 'STOCKS', 'ENTERTAINMENT', 'OTHER', 'WEATHER']
                if any(cat in response_text.upper() for cat in exclude_categories):
                    print(f"[AI FILTER] ❌ Excluding: {market_title[:50]}... (AI: {response_text.strip()})")
                    should_exclude = True
                else:
                    print(f"[AI FILTER] ✓ Keeping: {market_title[:50]}... (AI: {response_text.strip()})")
                    should_exclude = False

            # Cache the result
            self.ai_cache[market_title] = should_exclude
            return should_exclude

        except Exception as e:
            print(f"[AI FILTER] ⚠️ AI categorization failed: {e}")
            print(f"[AI FILTER] → Defaulting to INCLUDE (conservative): {market_title[:50]}...")
            return False  # Default to INCLUDE if AI fails

    def _keyword_exclusion_check(self, market_title: str) -> bool:
        """
        Fast keyword-based filtering.

        Returns True if the market matches exclusion criteria (crypto/sports/entertainment/esports).
        """
        # Define EXCLUSION keywords - comprehensive list for non-geopolitics markets
        exclusion_keywords = [
            # CRYPTO - Major cryptocurrencies
            'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'xrp', 'ripple',
            'solana', 'sol', 'dogecoin', 'doge', 'cardano', 'ada',
            'price above', 'price below', 'up or down', 'dip to $',

            # STOCKS - Major tickers and patterns
            'nvda', 'nvidia', 'tsla', 'tesla', 'aapl', 'apple',
            'msft', 'microsoft', 'googl', 'google', 'amzn', 'amazon',
            'meta', 'pltr', 'palantir', 'zm', 'zoom',
            'close at $', 'close above $', 'close below $',
            'finish week', 'quarterly earnings', 'beat earnings',

            # SPORTS BETTING - Critical patterns
            'spread:', 'o/u ', 'over/under', 'moneyline',
            '(-', '(+',  # Point spreads like "Bills (-5.5)"

            # SOCCER/FOOTBALL - Major teams
            'barcelona', 'manchester', 'real madrid', 'bayern',
            'liverpool', 'chelsea', 'arsenal', 'psg',
            'win on 2025', 'win on 202',  # Match date patterns

            # BRAZILIAN FOOTBALL
            'cruzeiro', 'flamengo', 'palmeiras', 'corinthians',

            # COLLEGE SPORTS
            'ohio state', 'georgia tech', 'alabama', 'michigan',

            # TRADITIONAL SPORTS - Teams and keywords
            'nfl', 'nba', 'mlb', 'nhl', 'super bowl',
            'championship', 'playoff', 'vs.', 'game', 'match',
            'warriors', 'thunder', 'lakers', 'celtics', 'cowboys',
            'patriots', 'bills', 'chiefs', 'bengals',
            'maple leafs', 'bruins',

            # ENTERTAINMENT
            'miss universe', 'miss world', 'beauty pageant',
            'venezuela', 'thailand', 'canada',  # Common Miss Universe countries
            'album', 'movie', 'taylor swift',

            # WEATHER
            'temperature', 'highest temperature', 'weather',

            # APP RANKINGS
            '#1 free app', 'app store', 'chatgpt', 'threads',
            'apple app store', 'google play',

            # ATHLETE SEARCHES
            '#1 searched athlete', 'most searched', 'google searches',
            'caitlin clark', 'cristiano ronaldo', 'shohei ohtani',
            'simone biles', 'lamine yamal',

            # OTHER NON-GEOPOLITICS
            'elon musk', 'tweet', 'x post',
            'fed rate', 'interest rate', 'stock market', 'sp500', 's&p',

            # ESPORTS - Direct keywords
            'esports', 'e-sports', 'gaming tournament',

            # ESPORTS - Tournament keywords (future-proof across all games)
            'major', 'starladder', 'iem', 'intel extreme masters',
            'blast', 'esl', 'pgl', 'faceit', 'dreamhack',
            'worlds', 'masters', 'champions', 'the international',
            'epic league', 'weplay', 'gamers galaxy', 'rog',

            # ESPORTS - Common team names (CS:GO, Valorant, LoL, Dota 2)
            'g2 esports', 'team vitality', 'fnatic', 'astralis',
            'natus vincere', "na'vi", 'navi', 'furia',
            'team falcons', 'ninjas in pyjamas', 'faze clan',
            'cloud9', 'team liquid', 'team spirit', 'heroic',
            'mousesports', 'mouz', 'complexity', 'parivision',
            'tyloo', 'eternal fire', 'saw', 'imperial',
            '9 pandas', 'betboom', 'virtus.pro', 'virtus pro',
            'ence', 'big', 'godsent', 'og esports',
            't1 esports', 'gen.g', 'drx', 'jd gaming',
            'edward gaming', 'royal never give up', 'fpx',

            # ESPORTS - Game titles
            'cs:go', 'csgo', 'counter-strike', 'counter strike',
            'league of legends', 'valorant', 'dota 2', 'dota2',
            'overwatch', 'fortnite', 'rocket league', 'apex legends',
            'call of duty', 'rainbow six',

            # CRICKET/RUGBY
            'test match', 'odi', 't20', 'cricket world cup', 'ashes',
            'ipl', 'big bash', 'county championship',
            'rugby world cup', 'six nations', 'tri nations', 'super rugby',
            'rugby championship', 'rugby league',

            # GENERIC MATCH TERMS
            'match on', 'game on', 'fixture', 'vs on', 'versus on'
        ]

        title_lower = market_title.lower()

        # Check if any exclusion keyword is in the title
        for keyword in exclusion_keywords:
            if keyword in title_lower:
                return True

        # REGEX PATTERN DETECTION - Catches patterns that keywords might miss

        # PATTERN: Spread betting (captures any point spread like "(-5.5)")
        if re.search(r'spread:.*\(-?\d+\.?\d*\)', title_lower):
            return True  # EXCLUDE sports spread betting

        # PATTERN: Over/Under betting (captures "O/U 61.5")
        if re.search(r'o/u\s+\d+\.?\d*', title_lower):
            return True  # EXCLUDE over/under bets

        # PATTERN: Stock price ranges "$XXX-$YYY"
        if re.search(r'close at \$\d+-\$\d+', title_lower):
            return True  # EXCLUDE stock price predictions

        # PATTERN: "Will [Team] win on [Date]" - Soccer/sports matches
        if re.search(r'will \w+ win on 20\d{2}-\d{2}-\d{2}', title_lower):
            return True  # EXCLUDE soccer/sports matches

        # PATTERN: Beauty pageants (Miss Universe, Miss World, etc.)
        if 'miss universe' in title_lower or 'miss world' in title_lower:
            return True  # EXCLUDE beauty pageants

        # PATTERN: "#1 searched" or "#1 app" rankings
        if '#1' in title_lower and any(x in title_lower for x in ['searched', 'app', 'free app']):
            return True  # EXCLUDE ranking markets

        # ESPORTS PATTERN DETECTION: "Will [Team] win the [Tournament]?"
        # This catches esports markets even if team/tournament names aren't in our keyword list
        if title_lower.startswith('will ') and ' win the ' in title_lower:
            # Extract what comes after "win the" to check if it's a tournament context
            parts = title_lower.split(' win the ')
            if len(parts) >= 2:
                tournament_part = parts[1]

                # Indicators this is likely an esports/gaming tournament:
                tournament_indicators = [
                    # Year patterns (tournaments often have years)
                    '2024', '2025', '2026', '2027',
                    # Generic tournament words that appear in esports but not politics
                    'tournament', 'cup', 'league', 'season',
                ]

                for indicator in tournament_indicators:
                    if indicator in tournament_part:
                        return True

                # Check if the team name (before "win the") contains typical esports markers
                team_part = parts[0].replace('will ', '')
                esports_team_markers = [
                    'team ', 'clan', 'gaming', 'esports', 'e-sports',
                ]

                for marker in esports_team_markers:
                    if marker in team_part:
                        return True

        # ===== VAGUE SPORTS MATCH DETECTION =====
        # Short, context-free "Will X win?" = likely sports
        # These lack the specificity of geopolitics ("Will X win the presidential election?")
        if len(market_title) < 50:
            # Pattern: "Will [name] win?" with no context
            if re.search(r'^will [\w\s]+ win(\?)?$', title_lower.strip()):
                # Check if it has geopolitics context
                geo_context = ['election', 'president', 'presidential', 'minister',
                               'parliament', 'vote', 'campaign', 'primary', 'referendum']

                if not any(ctx in title_lower for ctx in geo_context):
                    return True  # EXCLUDE vague match without geopolitics context

        # ===== SPORTS COUNTRY/TEAM IN NON-GEOPOLITICS CONTEXT =====
        # Countries that appear frequently in cricket, rugby, soccer betting
        sports_entities = [
            # Cricket/Rugby nations
            'australia', 'england', 'india', 'pakistan', 'south africa',
            'new zealand', 'sri lanka', 'west indies', 'bangladesh',
            # Soccer nations (when in sports context)
            'brazil', 'argentina', 'france', 'germany', 'spain',
            'italy', 'portugal', 'netherlands', 'belgium',
            # US Sports cities
            'boston', 'new york', 'chicago', 'philadelphia',
            'dallas', 'houston', 'miami', 'seattle'
        ]

        for entity in sports_entities:
            if entity in title_lower and 'win' in title_lower:
                # Check for geopolitics markers
                geo_markers = ['election', 'vote', 'president', 'minister',
                               'parliament', 'policy', 'government', 'referendum']
                if not any(marker in title_lower for marker in geo_markers):
                    return True  # EXCLUDE country without geopolitics context

        # ===== MATCH WITH DATE PATTERN =====
        # "Will X win on [date]" or "Will X win [month] [day]" = sports match
        if re.search(r'will \w+ win (on )?(20\d{2}[-/]\d{2}[-/]\d{2}|\w+ \d{1,2})', title_lower):
            # Check if it's NOT an election date
            if 'election' not in title_lower and 'vote' not in title_lower:
                return True  # EXCLUDE match with specific date

        return False

    async def _should_exclude_market(self, market_title: str) -> bool:
        """
        HYBRID FILTERING: Two-layer approach for maximum accuracy.

        Layer 1: Fast keyword check (catches 80% of cases)
        Layer 2: AI categorization (catches remaining 20% of ambiguous cases)

        Returns True to EXCLUDE, False to INCLUDE.
        """
        # LAYER 1: Fast keyword filtering (existing comprehensive patterns)
        if self._keyword_exclusion_check(market_title):
            print(f"[KEYWORD FILTER] ❌ Excluding: {market_title[:50]}...")
            return True  # EXCLUDE via keywords

        # FAST PATH: Strong geopolitics signals skip AI (performance optimization)
        geopolitics_signals = [
            'election', 'president', 'presidential', 'war', 'strike', 'military',
            'sanctions', 'treaty', 'diplomat', 'congress', 'senate',
            'prime minister', 'parliament', 'government', 'minister',
            'ukraine', 'russia', 'china', 'israel', 'gaza', 'iran',
            'nato', 'un security', 'policy', 'tariff', 'peace deal'
        ]

        if any(signal in market_title.lower() for signal in geopolitics_signals):
            print(f"[FAST PATH] ✓ Strong geopolitics signal: {market_title[:50]}...")
            return False  # INCLUDE without AI check

        # LAYER 2: AI categorization for ambiguous cases
        if AI_FILTERING_ENABLED and AI_FILTER_MODE in ["hybrid", "ai_only"] and self.ai_agent:
            print(f"[AI PATH] Checking ambiguous market: {market_title[:50]}...")
            return await self._ai_categorization_check(market_title)

        # FALLBACK: Conservative default (include if uncertain)
        print(f"[DEFAULT] ✓ No match, including: {market_title[:50]}...")
        return False

    async def initial_scan(self):
        """Perform initial scan to identify successful traders."""
        print("🔍 Starting initial scan for successful traders...")
        await self.telegram.send_message("🔍 Starting initial trader scan...")

        newly_flagged = self.analyzer.scan_for_successful_traders()

        summary = self.analyzer.get_flagged_traders_summary()
        await self.telegram.send_message(
            f"✅ Initial scan complete!\n\n"
            f"Found {newly_flagged} new successful traders.\n\n"
            f"{summary}"
        )

        print(f"✅ Initial scan complete. Flagged {newly_flagged} traders.")

    async def check_for_new_trades(self):
        """Check for new trades from flagged traders."""
        flagged_traders = self.db.get_flagged_traders()

        if not flagged_traders:
            print("No flagged traders to monitor yet.")
            return 0

        print(f"Monitoring {len(flagged_traders)} flagged traders...")

        # Strategy: Fetch all recent trades and filter for our flagged traders
        # This is more efficient than calling get_trader_history() for each trader
        print("Fetching recent trades from Polymarket...")
        all_recent_trades = self.polymarket.get_market_trades(market_id=None, limit=500)

        print(f"✅ Fetched {len(all_recent_trades)} recent trades")

        # Convert flagged traders to a set for fast lookup
        flagged_set = set(flagged_traders)

        # Filter for trades from our flagged traders
        relevant_trades = []
        for trade in all_recent_trades:
            trader = trade.get('proxyWallet')
            if trader in flagged_set:
                relevant_trades.append((trader, trade))

        print(f"📊 Found {len(relevant_trades)} trades from flagged traders")

        new_trades_count = 0
        duplicate_count = 0
        excluded_count = 0

        for trader_address, trade in relevant_trades:
            # Extract trade information
            trade_id = trade.get('transactionHash') or trade.get('id')
            if not trade_id:
                print(f"⚠️ Trade missing ID, skipping...")
                continue

            market_id = trade.get('conditionId') or trade.get('market')
            outcome = trade.get('outcome', 'Unknown')
            shares = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            side = trade.get('side', 'unknown')
            timestamp_raw = trade.get('timestamp')
            market_title = trade.get('title', 'Unknown Market')

            # CHECK: Skip trades from excluded markets (crypto/sports/entertainment)
            if await self._should_exclude_market(market_title):
                excluded_count += 1
                continue

            # Parse timestamp
            try:
                if isinstance(timestamp_raw, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp_raw)
                else:
                    timestamp = datetime.fromisoformat(str(timestamp_raw).replace('Z', '+00:00'))
            except:
                timestamp = datetime.now()

            # Try to add trade to database
            is_new = self.db.add_trade(
                trade_id=trade_id,
                trader_address=trader_address,
                market_id=market_id,
                market_title=market_title,
                market_category='Geopolitics',
                outcome=outcome,
                shares=shares,
                price=price,
                side=side,
                timestamp=timestamp
            )

            if is_new:
                new_trades_count += 1
                print(f"📝 NEW: {trader_address[:10]}... traded {shares:.1f} @ ${price:.3f} in {market_title[:30]}...")
            else:
                duplicate_count += 1

        print(f"✅ New trades: {new_trades_count} | Already seen: {duplicate_count} | Excluded (crypto/sports): {excluded_count}")
        return new_trades_count

    async def notify_new_trades(self):
        """Send bundled notifications for trades that haven't been notified yet."""
        unnotified_trades = self.db.get_unnotified_trades()

        if not unnotified_trades:
            return

        print(f"Processing {len(unnotified_trades)} trade notifications...")

        # Bundle trades by trader
        trades_by_trader = {}
        for trade in unnotified_trades:
            trader = trade['trader_address']
            if trader not in trades_by_trader:
                trades_by_trader[trader] = []
            trades_by_trader[trader].append(trade)

        # Get trader stats for all traders
        trader_stats_map = {}
        for trader in trades_by_trader.keys():
            stats = self.db.get_trader_stats(trader)
            if stats:
                trader_stats_map[trader] = stats

        print(f"Bundled into {len(trades_by_trader)} traders")

        # Send bundled notifications
        await self.telegram.send_bundled_trade_alerts(trades_by_trader, trader_stats_map)

        # Mark all as notified
        for trade in unnotified_trades:
            self.db.mark_trade_notified(trade['trade_id'])

    async def monitoring_loop(self):
        """Main monitoring loop that runs every check_interval."""
        cycle_count = 0

        while self.is_running:
            cycle_count += 1
            print(f"\n{'='*60}")
            print(f"Monitoring Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")

            try:
                # Check for new trades
                new_trades = await self.check_for_new_trades()

                # Send notifications for new trades
                if new_trades > 0:
                    await self.notify_new_trades()

                # Periodically re-scan for new successful traders (every 10 cycles)
                if cycle_count % 10 == 0:
                    print("\n🔄 Performing periodic trader re-scan...")
                    newly_flagged = self.analyzer.scan_for_successful_traders()
                    if newly_flagged > 0:
                        await self.telegram.send_message(
                            f"🆕 Found {newly_flagged} new successful traders!"
                        )

                # Check for market resolutions (every 10 cycles)
                if cycle_count % 10 == 0:
                    print("\n🎯 Checking for resolved markets...")
                    newly_resolved = self.analyzer.check_market_resolutions()
                    if newly_resolved > 0:
                        await self.telegram.send_message(
                            f"✅ {newly_resolved} market(s) resolved! Win rate data updated."
                        )

                print(f"\n✅ Cycle complete. Next check in {self.check_interval // 60} minutes.")

            except Exception as e:
                print(f"❌ Error in monitoring cycle: {e}")
                await self.telegram.send_message(f"⚠️ Error in monitoring: {str(e)}")

            # Wait for next cycle or until stop is requested
            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                await asyncio.sleep(1)

        print("\n🛑 Monitoring loop stopped")

    async def start(self):
        """Start the monitoring service."""
        print("🚀 Starting Polymarket Monitor...")
        self.is_running = True

        # Initialize Telegram bot
        await self.telegram.initialize()
        await self.telegram.start_polling()

        # Send startup message
        await self.telegram.send_message(
            "🚀 <b>Polymarket Monitor Started!</b>\n\n"
            "Monitoring geopolitical markets for successful trader activity.\n\n"
            "Use /stop to stop the service remotely."
        )

        # Perform initial scan
        await self.initial_scan()

        # Start monitoring loop
        await self.monitoring_loop()

    async def stop(self):
        """Stop the monitoring service gracefully."""
        print("🛑 Stopping Polymarket Monitor...")
        self.is_running = False

        await self.telegram.send_message("👋 Polymarket Monitor stopped.")
        await self.telegram.stop()

        print("✅ Monitor stopped successfully")


async def main(polymarket_api_key: str, telegram_token: str,
               telegram_chat_id: Optional[str] = None,
               ai_agent = None):
    """Main entry point for the monitor."""
    monitor = PolymarketMonitor(
        polymarket_api_key=polymarket_api_key,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        check_interval=900,  # 15 minutes
        ai_agent=ai_agent  # Pass AI agent for intelligent categorization
    )

    try:
        await monitor.start()
    except KeyboardInterrupt:
        print("\n⚠️ Keyboard interrupt received")
    finally:
        await monitor.stop()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Optional

    if not POLYMARKET_API_KEY or not TELEGRAM_BOT_TOKEN:
        print("❌ Missing required environment variables!")
        print("Please ensure POLYMARKET_API_KEY and TELEGRAM_BOT_TOKEN are set in .env")
        exit(1)

    asyncio.run(main(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
