import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Optional, Dict
from .database import Database
from .polymarket_client import PolymarketClient
from .trader_analyzer import TraderAnalyzer
from .position_tracker import PositionTracker
from .background_pnl_worker import BackgroundPnLWorker

# Telegram imports removed - all notifications handled by System Observer

_monitor_logger = logging.getLogger('monitor')

# AI Filtering Configuration
AI_FILTERING_ENABLED = True  # Toggle AI filtering on/off
AI_FILTER_MODE = "hybrid"  # Options: "keywords_only", "hybrid", "ai_only"


def safe_print(message: str, fallback: str = None):
    """
    Safe print that handles Windows console encoding errors.

    Args:
        message: The message to print
        fallback: Optional fallback message if printing fails
    """
    try:
        print(message)
    except (OSError, UnicodeEncodeError):
        if fallback:
            try:
                print(fallback)
            except (OSError, UnicodeEncodeError):
                pass  # Give up if even fallback fails
        # Silently skip if no fallback or fallback also fails


class PolymarketMonitor:
    """Main monitoring service that coordinates all components."""

    def __init__(self, polymarket_api_key: str,
                 check_interval: int = 900,  # 900 seconds = 15 minutes
                 ai_agent = None):  # AI agent for intelligent categorization
        """
        Initialize Polymarket Monitor.

        Args:
            polymarket_api_key: Polymarket API key
            check_interval: Check interval in seconds (default: 900 = 15 min)
            ai_agent: Optional AI agent for intelligent categorization

        Note:
            Telegram notifications completely disabled in monitoring.
            All notifications are handled by System Observer.
            This eliminates Telegram rate limit issues.
        """
        self.db = Database()
        self.polymarket = PolymarketClient(polymarket_api_key)

        # Telegram completely disabled - all notifications via System Observer
        self.telegram = None
        self.elo_bot = None
        self.elo_scheduler = None

        self.analyzer = TraderAnalyzer(self.db, self.polymarket)
        self.position_tracker = PositionTracker(self.db)  # CRITICAL: P&L tracking

        # Flat logger name mirrors the watchdog pattern (direct child of root).
        self.pnl_worker = BackgroundPnLWorker(
            self.db, self.position_tracker,
            logger=logging.getLogger('pnl_worker'),
        )

        self.ai_agent = ai_agent  # Store AI agent
        self.check_interval = check_interval
        self.is_running = False

        # Cache for AI categorization to avoid repeated API calls
        self.ai_cache: Dict[str, bool] = {}

        safe_print("[MONITOR] [OK] Telegram disabled - Observer handles all notifications")

    def request_stop(self):
        """Request the monitor to stop."""
        safe_print("[STOP] Stop requested via Telegram")
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
                safe_print(f"[AI FILTER] [EXCLUDED] Excluding: {market_title[:50]}... (AI classified as non-geopolitics)", "[AI FILTER] [EXCLUDED] Excluding market (AI classified as non-geopolitics)")
                should_exclude = True
            elif 'KEEP' in response_text.upper():
                safe_print(f"[AI FILTER] Keeping: {market_title[:50]}... (AI classified as geopolitics)", "[AI FILTER] Keeping market (AI classified as geopolitics)")
                should_exclude = False
            else:
                # If AI response unclear, check for category keywords
                exclude_categories = ['SPORTS', 'CRYPTO', 'STOCKS', 'ENTERTAINMENT', 'OTHER', 'WEATHER']
                if any(cat in response_text.upper() for cat in exclude_categories):
                    safe_print(f"[AI FILTER] [EXCLUDED] Excluding: {market_title[:50]}... (AI: {response_text.strip()})", f"[AI FILTER] [EXCLUDED] Excluding market (AI: {response_text.strip()})")
                    should_exclude = True
                else:
                    safe_print(f"[AI FILTER] Keeping: {market_title[:50]}... (AI: {response_text.strip()})", f"[AI FILTER] Keeping market (AI: {response_text.strip()})")
                    should_exclude = False

            # Cache the result
            self.ai_cache[market_title] = should_exclude
            return should_exclude

        except Exception as e:
            safe_print(f"[AI FILTER] [WARNING] AI categorization failed: {e}")
            safe_print(f"[AI FILTER] → Defaulting to INCLUDE (conservative): {market_title[:50]}...", "[AI FILTER] → Defaulting to INCLUDE (conservative)")
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

            # CRYPTO AIRDROPS & TOKEN LAUNCHES
            'fdv above', 'fdv >', 'fdv>', 'market cap >', 'market cap>',
            'one day after launch', 'day after launch', '1 day after launch',
            'airdrop', 'token launch', 'token airdrop',

            # GOLD PRICE PREDICTIONS
            'gold close between', 'gold price', 'gold hits', 'gold hit', 'gold reaches',
            'gold above', 'gold below', 'gold closes', 'price of gold',

            # STOCKS - Major tickers and patterns
            'nvda', 'nvidia', 'tsla', 'tesla', 'aapl', 'apple',
            'msft', 'microsoft', 'googl', 'google', 'amzn', 'amazon',
            'meta', 'pltr', 'palantir', 'zm', 'zoom',
            'close at $', 'close above $', 'close below $',
            'finish week', 'quarterly earnings', 'beat earnings',

            # SPORTS BETTING - Critical patterns
            'spread:', 'o/u ', 'over/under', 'moneyline',
            '(-', '(+',  # Point spreads like "Bills (-5.5)"
            'touchdown', 'anytime touchdown', 'first touchdown',

            # SPORTS LEAGUES & CHAMPIONSHIPS
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

            # SOCCER/FOOTBALL - Major teams
            'barcelona', 'manchester', 'real madrid', 'bayern',
            'liverpool', 'chelsea', 'arsenal', 'psg',
            'win on 2025', 'win on 202',  # Match date patterns

            # BRAZILIAN FOOTBALL
            'cruzeiro', 'flamengo', 'palmeiras', 'corinthians',

            # COLLEGE SPORTS
            'ohio state', 'georgia tech', 'alabama', 'michigan',

            # TRADITIONAL SPORTS - Teams and keywords
            'championship', 'playoff', 'vs.', 'game', 'match',
            'warriors', 'thunder', 'lakers', 'celtics', 'cowboys',
            'patriots', 'bills', 'chiefs', 'bengals',
            'maple leafs', 'bruins', 'atp', 

            # ENTERTAINMENT - AWARDS & NOMINATIONS
            'academy award', 'oscar', 'oscars', 'grammy', 'grammys',
            'emmy', 'emmys', 'tony awards', 'golden globe', 'bafta',
            'cannes', 'sundance',
            'nominated for best', 'win best actor', 'win best actress',
            'win best director', 'win best picture', 'win best film',
            'best supporting actor', 'best supporting actress',
            'best documentary', 'best animated', 'best song',
            'best film editing', 'costume', 'editing', 'gross', 'grossing',
            'season', 'performance',

            # ENTERTAINMENT - MUSIC
            'songwriter of the year', 'album of the year', 'record of the year',
            'most streamed', 'streamed on spotify', 'spotify',

            # ENTERTAINMENT - MEDIA & STREAMING
            'movie', 'film', 'documentary', 'box office', 'opening weekend',
            'streamer of the year', 'twitch', 'kai cenat',

            # ENTERTAINMENT - BEAUTY PAGEANTS
            'miss universe', 'miss world', 'beauty pageant',
            'venezuela', 'thailand', 'canada',  # Common Miss Universe countries

            # ENTERTAINMENT - MISC
            'album', 'taylor swift',

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
            'bo3', 'bo5', 'map winner',

            # ESPORTS - Common team names (CS:GO, Valorant, LoL, Dota 2)
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

            # ESPORTS - Game titles
            'cs:go', 'csgo', 'counter-strike', 'counter strike', 'cs2',
            'league of legends', 'lol:', 'valorant', 'dota 2', 'dota2', 'dota',
            'overwatch', 'fortnite', 'rocket league', 'apex legends',
            'call of duty', 'rainbow six',

            # CRICKET/RUGBY
            'test match', 'odi', 't20', 'cricket world cup', 'ashes',
            'ipl', 'big bash', 'county championship',
            'rugby world cup', 'six nations', 'tri nations', 'super rugby',
            'rugby championship', 'rugby league',

            # GENERIC MATCH TERMS
            'match on', 'game on', 'fixture', 'vs on', 'versus on',

            # CLIMATE / WEATHER (137 active markets)
            'hurricane', 'named storm', 'tropical storm', 'tornado',
            'earthquake', 'wildfire', 'flood', 'drought',
            'temperature record', 'celsius', 'fahrenheit',
            'measles', 'pandemic', 'outbreak', 'epidemic',

            # OIL / COMMODITIES (153 active markets — price bets)
            'wti crude', 'brent crude', 'crude oil price',
            'oil price', 'price per barrel', 'barrel',
            'natural gas price', 'lumber price', 'wheat price',
            'corn price', 'soybean',

            # EQUITY INDICES / STOCKS
            'spy ', 'qqq ', 's&p 500', 'nasdaq', 'dow jones',
            'nifty', 'ftse', 'dax ', 'cac 40',
            'vix ', 'volatility index',
            'largest company', 'market cap end',

            # IPO MARKETS
            'ipo closing', 'ipo market cap', 'ipo by',
            'spacex ipo', 'kraken ipo', 'stripe ipo',
            'going public',

            # OLYMPICS / INTERNATIONAL GAMES
            'olympics', 'olympic games', 'medal count',
            'gold medal', 'podium finish',
            'commonwealth games', 'asian games', 'pan american',

            # VIDEO GAMES / GAMING (non-esports)
            'game launch', 'steam sales', 'launch day sales',
            'game of the year', 'goty',
            'copies sold', 'day one sales',

            # SOCIAL MEDIA POST COUNT MARKETS
            'post 200+', 'post 100+', 'posts from april',
            'posts from may', 'posts this week',
            'tweets this week', 'truth social posts',

            # REALITY TV / COMPETITION SHOWS
            'survivor', 'big brother', 'bachelor', 'bachelorette',
            'dancing with the stars', 'american idol', 'x factor',
            'love island', 'drag race',

            # AWARDS NOT ALREADY COVERED
            'booker prize', 'pulitzer', 'nobel prize',
            'man booker', 'hugo award',

            # MISCELLANEOUS NICHE
            'alien', 'ufo', 'bigfoot', 'paranormal',
            'will aliens', 'extraterrestrial',
            'lottery', 'powerball', 'mega millions',

            # INFLUENCER / YOUTUBE
            'mrbeast', 'million subscribers', 'subscribers by',

            # BOXING / COMBAT SPORTS (non-MMA)
            'go the distance', 'fight to go',

            # SPORTS DIVISION / CONFERENCE AWARDS
            'pro football draft',
            'pacific division', 'atlantic division',
            'metropolitan division', 'central division',
            'pacific conference', 'atlantic conference',
        ]

        title_lower = market_title.lower()

        # Check if any exclusion keyword is in the title
        for keyword in exclusion_keywords:
            if keyword in title_lower:
                # Log which keyword triggered the exclusion (use safe encoding for Windows)
                safe_print(f"[FILTER] Matched keyword: '{keyword}'", fallback="[FILTER] Keyword matched")
                return True

        # REGEX PATTERN DETECTION - Catches patterns that keywords might miss

        # PATTERN: Spread betting (captures any point spread like "(-5.5)")
        if re.search(r'spread:.*\(-?\d+\.?\d*\)', title_lower):
            safe_print(f"[FILTER] Matched pattern: sports spread betting")
            return True  # EXCLUDE sports spread betting

        # PATTERN: Over/Under betting (captures "O/U 61.5")
        if re.search(r'o/u\s+\d+\.?\d*', title_lower):
            safe_print(f"[FILTER] Matched pattern: over/under betting")
            return True  # EXCLUDE over/under bets

        # PATTERN: Stock price ranges "$XXX-$YYY"
        if re.search(r'close at \$\d+-\$\d+', title_lower):
            safe_print(f"[FILTER] Matched pattern: stock price range")
            return True  # EXCLUDE stock price predictions

        # PATTERN: Gold price ranges "$X-$Y" (e.g., "gold close between $3500 and $3600")
        if re.search(r'gold.*\$\d+.*and.*\$\d+', title_lower):
            safe_print(f"[FILTER] Matched pattern: gold price range")
            return True  # EXCLUDE gold price predictions

        # PATTERN: "Will [Team] win on [Date]" - Soccer/sports matches
        if re.search(r'will \w+ win on 20\d{2}-\d{2}-\d{2}', title_lower):
            safe_print(f"[FILTER] Matched pattern: sports match with date")
            return True  # EXCLUDE soccer/sports matches

        # PATTERN: Beauty pageants (Miss Universe, Miss World, etc.)
        if 'miss universe' in title_lower or 'miss world' in title_lower:
            safe_print(f"[FILTER] Matched pattern: beauty pageant")
            return True  # EXCLUDE beauty pageants

        # PATTERN: "#1 searched" or "#1 app" rankings
        if '#1' in title_lower and any(x in title_lower for x in ['searched', 'app', 'free app']):
            safe_print(f"[FILTER] Matched pattern: ranking/popularity")
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

                # Words that prove this is geopolitics, not a tournament
                _geo_guard = ['election', 'president', 'presidential', 'minister',
                              'parliament', 'vote', 'war', 'treaty', 'senate', 'congress',
                              'referendum', 'campaign', 'primary', 'ceasefire']

                for indicator in tournament_indicators:
                    if indicator in tournament_part:
                        if not any(word in tournament_part for word in _geo_guard):
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

        # Structural patterns that catch sports regardless of team/player names
        sport_patterns = [
            r'.+:\s*.+\s+vs\s+.+',        # "City/Tournament: Player vs Player"
            r'^exact score:',              # Exact score betting
            r'anytime goalscorer',         # Soccer goalscorer markets
            r'^map \d+:',                  # Esports map betting
            r'leading at halftime',        # Soccer halftime markets
            r'xauusd|xagusd|wti crude',   # Commodity tickers
            r'nhl.*(trophy|division|conference)',  # NHL awards
            r'nba.*(trophy|division|conference)', # NBA awards
            r'\d+\s*-\s*\d+.*\?$',       # Score prediction format
            # Post count markets (Will X post N-M posts from DATE to DATE?)
            r'post\s+\d+[-–]\d+\s+posts',
            r'post\s+\d+\+\s+posts',
            # Price target markets (Will X hit $N by DATE?)
            r'hit \(high\)',
            r'hit \(low\)',
            r'hit \$[\d,]+',
            # Goalscorer / player performance
            r'top .* goal scorer',
            r'anytime (goal|try|touchdown)',
            r'first (goal|try|touchdown)',
            # NFL draft pick markets
            r'drafted \d+(st|nd|rd|th) overall',
            # "Will X say Y during Z" trivial speech markets
            r'will .+ say ".+" during',
            # Press briefing lateness markets
            r'be \d+[-–]\d+ minutes late',
        ]
        for pattern in sport_patterns:
            if re.search(pattern, title_lower):
                return True  # EXCLUDE structural sports pattern

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
            safe_print(f"[KEYWORD FILTER] [EXCLUDED] Excluding: {market_title[:50]}...",
                      fallback="[KEYWORD FILTER] [EXCLUDED] Market excluded by keyword")
            return True  # EXCLUDE via keywords

        # FAST PATH: Strong geopolitics signals skip AI (performance optimization)
        geopolitics_signals = [
            'election', 'president', 'presidential', 'war', 'strike', 'military',
            'sanctions', 'treaty', 'diplomat', 'congress', 'senate',
            'prime minister', 'parliament', 'government', 'minister',
            'ukraine', 'russia', 'china', 'israel', 'gaza', 'iran',
            'nato', 'un security', 'policy', 'tariff', 'peace deal',
            'middle east',
        ]

        if any(signal in market_title.lower() for signal in geopolitics_signals):
            safe_print(f"[FAST PATH] Strong geopolitics signal: {market_title[:50]}...", "[FAST PATH] Strong geopolitics signal")
            return False  # INCLUDE without AI check

        # LAYER 2: AI categorization for ambiguous cases
        if AI_FILTERING_ENABLED and AI_FILTER_MODE in ["hybrid", "ai_only"] and self.ai_agent:
            safe_print(f"[AI PATH] Checking ambiguous market: {market_title[:50]}...", "[AI PATH] Checking ambiguous market")
            return await self._ai_categorization_check(market_title)

        # FALLBACK: Conservative default (include if uncertain)
        safe_print(f"[DEFAULT] No match, including: {market_title[:50]}...", "[DEFAULT] No match, including market")
        return False

    async def initial_scan(self):
        """
        Perform initial scan to identify successful traders.

        Telegram notifications disabled - Observer handles all notifications.
        """
        safe_print("Starting initial scan for successful traders...")

        newly_flagged = self.analyzer.scan_for_successful_traders()
        summary = self.analyzer.get_flagged_traders_summary()

        safe_print(f"[OK] Initial scan complete. Flagged {newly_flagged} traders.")
        safe_print(f"[INFO] {summary}")

    async def check_for_new_trades(self):
        """Check for new trades from flagged traders."""
        flagged_traders = self.db.get_flagged_traders()

        if not flagged_traders:
            safe_print("No flagged traders to monitor yet.")
            return 0

        safe_print(f"Monitoring {len(flagged_traders)} flagged traders...")

        # Strategy: Fetch all recent trades and filter for our flagged traders
        # This is more efficient than calling get_trader_history() for each trader
        safe_print("Fetching recent trades from Polymarket...")
        all_recent_trades = self.polymarket.get_market_trades(market_id=None, limit=500)

        safe_print(f"[OK] Fetched {len(all_recent_trades)} recent trades")
        _monitor_logger.info(f"Fetched {len(all_recent_trades)} recent trades")

        # Convert flagged traders to a set for fast lookup
        flagged_set = set(flagged_traders)

        # Filter for trades from our flagged traders
        relevant_trades = []
        for trade in all_recent_trades:
            trader = trade.get('proxyWallet')
            if trader in flagged_set:
                relevant_trades.append((trader, trade))

        safe_print(f"Found {len(relevant_trades)} trades from flagged traders")

        new_trades_count = 0
        duplicate_count = 0
        excluded_count = 0

        for trader_address, trade in relevant_trades:
            # Extract trade information
            trade_id = trade.get('transactionHash') or trade.get('id')
            if not trade_id:
                safe_print(f"[WARNING] Trade missing ID, skipping...")
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
                    # Defend against millisecond timestamps (e.g. if
                    # Polymarket Data API ever migrates to ms format)
                    # Values > 1e10 are milliseconds, divide to get seconds
                    ts = timestamp_raw / 1000 if timestamp_raw > 1e10 else timestamp_raw
                    timestamp = datetime.fromtimestamp(ts)
                else:
                    timestamp = datetime.fromisoformat(str(timestamp_raw).replace('Z', '+00:00'))
            except:
                timestamp = datetime.now()

            # Store market information if we haven't seen it before
            self.db.store_market_from_trade(trade)

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
                safe_print(f"NEW: {trader_address[:10]}... traded {shares:.1f} @ ${price:.3f} in {market_title[:30]}...",
                          fallback=f"NEW: {trader_address[:10]}... traded {shares:.1f} @ ${price:.3f}")

                # ============================================================
                # BETTING INTELLIGENCE ALERTS
                # ============================================================
                if self.elo_bot:
                    try:
                        # Check if elite trader (top 10)
                        rank_data = self.db.get_trader_rank(trader_address)

                        if rank_data and rank_data['rank'] <= 10:
                            # Send elite trader alert
                            trade_data = {
                                'market_title': market_title,
                                'outcome': outcome,
                                'shares': shares,
                                'price': price,
                                'side': side,
                                'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S')
                            }

                            await self.elo_bot.send_elite_trader_alert(
                                trader_address,
                                trade_data
                            )
                            safe_print(f"[BETTING INTEL] Elite alert sent for Rank #{rank_data['rank']}")

                            # Check for large position
                            await self.elo_bot.send_large_position_alert(trader_address, trade_data)

                            # Check for contrarian signal (need market consensus)
                            # Market consensus = current price
                            market_consensus = price if outcome.upper() == 'YES' else (1 - price)
                            await self.elo_bot.send_contrarian_alert(trader_address, trade_data, market_consensus)

                            # Check for win streak
                            streak_data = self.db.get_trader_win_streak(trader_address, min_streak=3)
                            if streak_data:
                                await self.elo_bot.send_win_streak_alert(trader_address, streak_data)

                    except Exception as e:
                        safe_print(f"[BETTING INTEL] Warning: Alert failed: {e}",
                                  fallback="[BETTING INTEL] Warning: Alert failed")
            else:
                duplicate_count += 1

        safe_print(f"[OK] New trades: {new_trades_count} | Already seen: {duplicate_count} | Excluded (crypto/sports): {excluded_count}")
        return new_trades_count

    async def notify_new_trades(self):
        """Send bundled notifications for trades that haven't been notified yet."""
        unnotified_trades = self.db.get_unnotified_trades()

        if not unnotified_trades:
            return

        safe_print(f"Processing {len(unnotified_trades)} trade notifications...",
                  fallback="Processing trade notifications...")

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

        safe_print(f"Bundled into {len(trades_by_trader)} traders")

        # Telegram notifications disabled - Observer handles all notifications

        # Mark all as notified
        for trade in unnotified_trades:
            self.db.mark_trade_notified(trade['trade_id'])

    def _update_activity_timestamp(self):
        """
        Update last activity timestamp in database for system observer.

        This allows the system observer to detect if monitoring has frozen/hung.
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Create monitoring_status table if it doesn't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monitoring_status (
                    id INTEGER PRIMARY KEY,
                    last_activity TIMESTAMP,
                    last_cycle_count INTEGER,
                    process_id INTEGER
                )
            """)

            import os
            process_id = os.getpid()

            cursor.execute("""
                INSERT OR REPLACE INTO monitoring_status (id, last_activity, process_id)
                VALUES (1, datetime('now'), ?)
            """, (process_id,))

            conn.commit()
            conn.close()

        except Exception as e:
            safe_print(f"[WARNING] Failed to update activity timestamp: {e}")

    async def update_position_tracking(self) -> int:
        """
        Update position tracking and P&L for all active traders.

        OPTIMIZED to prevent blocking:
        - Processes traders in batches
        - Yields control to event loop between traders
        - Batch commits to reduce database locks

        Returns:
            int: Number of traders with updated P&L
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Get all traders with trades (focus on active ones)
        # OPTIMIZATION: Reduced from 30 days to 7 days to reduce load by ~75%
        # This cuts processing from 773 traders → ~200 traders
        cursor.execute("""
            SELECT DISTINCT trader_address
            FROM trades
            WHERE timestamp > datetime('now', '-7 days')
            ORDER BY timestamp DESC
        """)

        active_traders = [row[0] for row in cursor.fetchall()]
        conn.close()

        safe_print(f"[P&L] Processing {len(active_traders)} active traders...")

        # DIAGNOSTIC: Identify whale traders (1000+ trades) that may cause timeouts
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trader_address, COUNT(*) as trade_count
            FROM trades
            WHERE timestamp > datetime('now', '-7 days')
            GROUP BY trader_address
            HAVING COUNT(*) > 1000
            ORDER BY trade_count DESC
            LIMIT 5
        """)
        whale_traders = cursor.fetchall()
        conn.close()

        if whale_traders:
            safe_print("\n[P&L] [DIAGNOSTIC] Whale traders detected (1000+ trades):")
            for trader, count in whale_traders:
                safe_print(f"  {trader[:10]}... : {count:,} trades")
            safe_print("")

        traders_updated = 0
        traders_skipped = 0
        batch_size = 10  # Process 10 traders at a time

        for i in range(0, len(active_traders), batch_size):
            batch = active_traders[i:i + batch_size]

            for batch_index, trader_address in enumerate(batch):
                try:
                    # START TIMING - Diagnostic for rate limiting detection
                    import time
                    start_time = time.time()
                    trader_number = i + batch_index + 1

                    # CRITICAL FIX: Check trade count before processing
                    # Traders with 2000+ trades cause O(n²) explosion in FIFO matching
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM trades
                        WHERE trader_address = ?
                    """, (trader_address,))
                    trade_count = cursor.fetchone()[0]
                    conn.close()

                    # Skip traders with too many trades (prevents timeout)
                    if trade_count > 2000:
                        safe_print(f"[P&L] [SKIP] Trader #{trader_number} ({trader_address[:10]}...) has {trade_count:,} trades (too many, skipping)")
                        traders_skipped += 1
                        continue

                    # Match trades into positions
                    # (This is CPU-intensive but unavoidable)
                    positions = self.position_tracker.match_trades_for_trader(trader_address, verbose=False)

                    # END TIMING - Report slow traders (API rate limiting indicator)
                    elapsed = time.time() - start_time

                    # DIAGNOSTIC: Report slow traders
                    if elapsed > 5.0:
                        safe_print(f"[P&L] [SLOW] Trader #{trader_number} ({trader_address[:10]}..., {trade_count} trades) took {elapsed:.1f}s (possible rate limit or large dataset)")

                    if not positions:
                        continue

                    # CRITICAL: Save positions to database
                    for position in positions:
                        self.db.insert_position(position)

                    # Calculate aggregate P&L metrics
                    closed_positions = [p for p in positions if p.status == 'closed']
                    open_positions = [p for p in positions if p.status == 'open']

                    if closed_positions:
                        realized_pnl = sum(p.realized_pnl for p in closed_positions if p.realized_pnl)
                        avg_roi = sum(p.roi_percent for p in closed_positions if p.roi_percent) / len(closed_positions)

                        # Update trader table with P&L data
                        conn = self.db.get_connection()
                        cursor = conn.cursor()

                        cursor.execute("""
                            UPDATE traders
                            SET realized_pnl = ?,
                                avg_roi = ?,
                                roi_percentage = ?,
                                closed_positions = ?,
                                open_positions = ?
                            WHERE address = ?
                        """, (
                            realized_pnl,
                            avg_roi,
                            avg_roi,  # roi_percentage
                            len(closed_positions),
                            len(open_positions),
                            trader_address
                        ))

                        conn.commit()
                        conn.close()

                        traders_updated += 1

                except Exception as e:
                    safe_print(f"[P&L] [ERROR] Failed for trader {trader_address[:10]}: {e}")
                    continue

            # CRITICAL: Yield control to event loop after each batch
            # This prevents blocking for long periods
            await asyncio.sleep(0.1)  # 100ms break between batches

            if i + batch_size < len(active_traders):
                safe_print(f"[P&L] Progress: {min(i + batch_size, len(active_traders))}/{len(active_traders)} traders processed...")

        # Summary reporting
        if traders_skipped > 0:
            safe_print(f"\n[P&L] Summary: {traders_updated} updated, {traders_skipped} skipped (too many trades)")

        return traders_updated

    async def monitoring_loop(self):
        """Main monitoring loop that runs every check_interval."""
        cycle_count = 0

        while self.is_running:
            cycle_count += 1
            safe_print(f"\n{'='*60}")
            safe_print(f"Monitoring Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            safe_print(f"{'='*60}")

            try:
                # Check for new trades
                new_trades = await self.check_for_new_trades()

                # Telegram notifications disabled - Observer handles all notifications
                # (notify_new_trades still marks trades as notified in database)
                if new_trades > 0:
                    await self.notify_new_trades()

                # Periodically re-scan for new successful traders (every 10 cycles)
                if cycle_count % 10 == 0:
                    safe_print("\nPerforming periodic trader re-scan...")
                    newly_flagged = self.analyzer.scan_for_successful_traders()
                    if newly_flagged > 0:
                        safe_print(f"[OK] Found {newly_flagged} new successful traders!")
                        # Telegram notifications disabled - Observer handles notifications

                # Check for market resolutions (every 10 cycles)
                if cycle_count % 10 == 0:
                    safe_print("\nPeriodic resolution check (cycle #{})...".format(cycle_count))

                    # Get statistics before resolution check
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM markets")
                    total_markets = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
                    resolved_count = cursor.fetchone()[0]
                    conn.close()

                    safe_print(f"[MONITOR] Current DB state: {total_markets} total markets, {resolved_count} resolved")

                    newly_resolved = self.analyzer.check_market_resolutions()

                    if newly_resolved > 0:
                        safe_print(f"[MONITOR] {newly_resolved} new resolution(s) found!")
                        # Telegram notifications disabled - Observer handles notifications
                    else:
                        safe_print(f"[MONITOR] No new resolutions found (markets are long-dated)")

                # OLD P&L CODE - DISABLED (background worker handles this now)
                # Position tracking with timeout protection (prevents freezing)
                # safe_print("\n[P&L] Updating position tracking (with timeout protection)...")
                # try:
                #     # Run with 5-minute timeout to prevent blocking
                #     positions_updated = await asyncio.wait_for(
                #         self.update_position_tracking(),
                #         timeout=300  # 5 minutes max
                #     )
                #     if positions_updated > 0:
                #         safe_print(f"[P&L] [OK] Updated P&L for {positions_updated} traders")
                #     else:
                #         safe_print(f"[P&L] No traders needed P&L updates")
                # except asyncio.TimeoutError:
                #     safe_print(f"[P&L] [WARNING] Position tracking timed out after 5 minutes - skipping this cycle")
                # except Exception as e:
                #     safe_print(f"[P&L] [ERROR] Position tracking failed: {e}")
                #     import traceback
                #     safe_print(f"[P&L] Traceback: {traceback.format_exc()}")

                # NEW: P&L handled by background worker (no action needed here)
                safe_print("\n[P&L] Background worker handling position tracking continuously")

                # Update activity timestamp for system observer
                self._update_activity_timestamp()

                safe_print(f"\n[OK] Cycle complete. Next check in {self.check_interval // 60} minutes.")
                _monitor_logger.info(f"Cycle complete. Next check in {self.check_interval // 60} minutes.")

            except Exception as e:
                import traceback
                import logging

                # Get full traceback
                error_traceback = traceback.format_exc()

                # Log to console and file
                safe_print(f"[ERROR] Error in monitoring cycle: {e}")
                safe_print(f"[ERROR] Full traceback:\n{error_traceback}")

                # Log to monitoring.log
                logger = logging.getLogger(__name__)
                logger.error(f"Error in monitoring cycle: {e}")
                logger.error(f"Full traceback:\n{error_traceback}")

                # Telegram notifications disabled - Observer monitors logs and sends alerts

            # Wait for next cycle or until stop is requested
            for _ in range(self.check_interval):
                if not self.is_running:
                    break
                await asyncio.sleep(1)

        safe_print("\n[STOP] Monitoring loop stopped")

    async def _watchdog_loop(self):
        """
        Heartbeat loop that writes to the log every 5 minutes unconditionally.

        This runs as a separate asyncio task and is completely independent of
        the monitoring and P&L loops. Its sole purpose is to ensure that
        logs/monitoring.log gets an mtime update every 5 minutes even when
        another coroutine is blocked or slow — so the System Observer can
        distinguish a true freeze from a slow-but-alive cycle.
        """
        import logging
        watchdog_logger = logging.getLogger('watchdog')
        safe_print("[WATCHDOG] Heartbeat loop started (every 5 minutes)")

        while self.is_running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                if self.is_running:
                    msg = f"[WATCHDOG] Heartbeat — monitor alive at {datetime.now().strftime('%H:%M:%S')}"
                    safe_print(msg)
                    watchdog_logger.info(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                safe_print(f"[WATCHDOG] Error: {e}")

    async def start(self):
        """
        Start the monitoring service.

        Telegram completely disabled - all notifications via System Observer.
        This eliminates Telegram rate limit issues.
        """
        safe_print("\n" + "="*70)
        safe_print("  POLYMARKET MONITOR STARTED")
        safe_print("  Telegram: DISABLED (Observer handles all notifications)")
        safe_print("  Position tracking: BACKGROUND WORKER")
        safe_print("  Database: Active")
        safe_print("="*70 + "\n")

        self.is_running = True

        # Perform initial scan
        await self.initial_scan()

        # Start watchdog heartbeat (independent of all other loops)
        # Store reference: Python 3.12 keeps only weak refs to tasks; discarding
        # the return value allows GC to collect the task before it runs.
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name='watchdog'
        )
        safe_print("[MONITOR] Watchdog heartbeat started\n")

        # Start background P&L worker (non-blocking)
        self._pnl_task = asyncio.create_task(
            self.pnl_worker.start(), name='pnl_worker'
        )
        safe_print("[MONITOR] Background P&L worker started\n")

        # Give both tasks one event-loop iteration to run their startup code
        # (log their first INFO line) before the monitoring loop takes over.
        await asyncio.sleep(0)

        # Start monitoring loop
        await self.monitoring_loop()

    async def stop(self):
        """
        Stop the monitoring service gracefully.

        Telegram completely disabled - no cleanup needed.
        """
        safe_print("\n[STOP] Stopping Polymarket Monitor...")
        self.is_running = False

        # NEW: Stop background P&L worker
        if hasattr(self, 'pnl_worker'):
            self.pnl_worker.stop()

        # Telegram completely disabled - no bot cleanup needed
        # (self.telegram = None, self.elo_bot = None)

        safe_print("[OK] Monitor stopped successfully\n")


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
        safe_print("\n[WARNING] Keyboard interrupt received")
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
        safe_print("[ERROR] Missing required environment variables!")
        safe_print("Please ensure POLYMARKET_API_KEY and TELEGRAM_BOT_TOKEN are set in .env")
        exit(1)

    asyncio.run(main(POLYMARKET_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
