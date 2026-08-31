"""
monitoring/relevance_prefilter.py
=================================
Deterministic EXCLUSION pre-filter — stage 1 of the geo/elections relevance
classifier cascade.

Design    : brain/decisions/2026-08-31-relevance-classifier-design.md
            (e601648) §1.2, §1.3, §2.4, §2.5
Schema    : first-repo 26ba190 (category_source, category_classification_log)
Record    : brain/decisions/2026-08-31-prefilter-implementation.md
            (token provenance, coverage figures, per-family breakdown, tests)

WHAT THIS IS
------------
    prefilter(title) -> "EXCLUDE" | "RESIDUAL"

A pure function. No DB, no network, no writes, no category, no side effects.

    EXCLUDE  — the title matches a *documented* non-geo template family
               (crypto up/down, crypto price level, weather, sports betting
               lines, sports/esports set-map winners, esports, sports leagues
               & tournaments, stocks, commodities, entertainment awards,
               novelty/religion) with near-zero false-negative risk. It will
               NOT be sent to the LLM stage.
    RESIDUAL — everything else. The LLM stage decides
               (Geopolitics / Elections / NotRelevant). RESIDUAL is the safe
               default: an ambiguous, unusual, or unrecognised title is never
               excluded here.

WHAT THIS IS *NOT*
-----------------
There is deliberately **no** positive ELECTION_TOKENS / GEOPOLITICS_TOKENS
list. A positive keyword list is exactly what M9 (backfill_market_categories.py)
uses, and it over-selects true geo/elec by 2–3× while reaching only ~2.5 % of
the population (2026-08-30-category-classifier-investigation.md;
2026-08-31-relevance-classifier-design.md §1.3). Positive classification is the
LLM's job. This module only ever moves a title *out* of the LLM's queue when it
is a recognised template; it never asserts a title *is* geo/elec.

SUBSTRING-TRAP GUARDS
--------------------
The documented failures of bare-substring matching
(2026-08-31-relevance-classifier-design.md §1.2, and the implementation-task
prompt):

    "war"       is a substring of  "Warsaw", "Warriors", "Warhawks"
    "president" is a substring of  "Presidents Cup"  (golf)
    "china"     is a substring of  "China Grand Prix" (Formula 1)

This module avoids them structurally:

  * It carries **no** "war" / "president" / "china" token at all — there is no
    positive list.
  * Every pattern is either a ``\\b``-anchored word / multi-word phrase, or a
    structural regex (``O/U 2.5``, ``(-3.5)``, ``Up or Down -``,
    ``temperature in ... be``, ``(BO3)``), never a bare substring.
  * "Presidents Cup" and "China Grand Prix" are caught by the *multi-word*
    sports-tournament phrases ``\\bpresidents cup\\b`` and ``\\bgrand prix\\b``,
    not by any single-word token.

TITLE-ONLY
----------
This build matches on ``title`` only. The full design pre-filter also consults
``event.slug`` / ``event.title`` (§1.3), which require a Gamma fetch (the LLM
stage's job, out of scope here). Adding slug matching can only *add* exclusions,
never remove one, so the coverage measured here is a lower bound.
"""

from __future__ import annotations

import re
from typing import Optional

EXCLUDE = "EXCLUDE"
RESIDUAL = "RESIDUAL"

_F = re.IGNORECASE

# ---------------------------------------------------------------------------
# EXCLUDE_PATTERNS
# ---------------------------------------------------------------------------
# Each entry is (family, compiled_regex).  A title is EXCLUDE if it matches
# ANY pattern; the family of the FIRST match is what the per-family coverage
# breakdown attributes it to, so the list is ordered roughly by expected
# frequency (design / category-investigation samples: crypto ~44 %, sports
# ~27 %, weather ~13 %).  Match order does not affect the EXCLUDE/RESIDUAL
# result.
#
# PROVENANCE of every family is one (or more) of:
#   [D1] 2026-08-31-relevance-classifier-design.md §1.2 family table + token list
#   [D2] 2026-08-30-category-classifier-investigation.md §Part-3 sample
#        breakdown + §"deterministic title-template pre-classifier" (4 rigid
#        templates) + skip-sample rows
#   [D3] market_filter.py / detect_insider_activity.py `_EXCLUSION_KEYWORDS`,
#        as enumerated in 2026-08-31-geo-scoping-inventory.md (M8/M11) and
#        2026-08-31-local-llm-consolidation-assessment.md §2.10
#   [P]  the four required-EXCLUDE strings named in the implementation-task
#        prompt ("Presidents Cup", "China Grand Prix", ...)
# No live population titles were inspected while drafting these lists.
# ---------------------------------------------------------------------------
EXCLUDE_PATTERNS = [

    # ── crypto up/down ──────────────────────────────────────────────────
    # Family: "Crypto up/down"  [D1 crypto-updown][D2 "<ASSET> Up or Down - "]
    # Template: "<COIN> Up or Down - <time>" / "<COIN> Up or Down on <date>?"
    # / "<TICKER> (TICKER) Up or Down".  "up or down" is a Polymarket
    # price-tick template phrase and appears in ~no geopolitics/elections title.
    ("crypto_updown", re.compile(r"\bup\s*or\s*down\b", _F)),

    # ── crypto / asset price level ─────────────────────────────────────
    # Family: "Crypto price level"  [D1 solana-above-on-…, ethereum-above-on-…]
    # Template: "Will (the price of) <COIN> be above/below/reach/hit $N …" and
    # "<COIN> above <N> on <date>".  Requires a coin name AND a
    # comparison-to-a-number, so it will not fire on a non-price sentence that
    # merely mentions a coin.
    ("crypto_price_level", re.compile(
        r"\b(bitcoin|btc|ethereum|eth|ether|solana|\bsol\b|xrp|ripple|dogecoin|"
        r"doge|cardano|\bada\b|\bbnb\b|litecoin|\bltc\b|tron|\btrx\b|avalanche|"
        r"avax|polkadot|\bdot\b|chainlink|shiba|\bpepe\b|polygon|\bmatic\b|"
        r"zcash|\bzec\b)\b"
        r".{0,40}?\b(above|below|over|under|greater than|less than|at least|"
        r"reach|reaches|hit|hits|be at|dip to|climb to|drop to|close at)\b"
        r"\s*\$?\s*[\d,]+", _F)),

    # ── weather ───────────────────────────────────────────────────────
    # Family: "Weather"  [D1 highest-temperature-in-<city>-on-<date>]
    #                    [D2 "Will the highest/lowest temperature in <CITY>"]
    ("weather", re.compile(
        r"\b(highest|lowest|high|low)\s+temperature\s+in\b", _F)),
    ("weather", re.compile(
        r"\btemperature\s+in\s+[A-Za-z .'\-]+?\s+be\b", _F)),
    ("weather", re.compile(
        r"\b(will it (rain|snow)\b|amount of (rain|snow(fall)?)\b|"
        r"total (rain|snow(fall)?)\b|inches of (rain|snow)\b)", _F)),

    # ── sports betting lines ─────────────────────────────────────────
    # Family: "sports line"  [D1 `: O/U `, `Spread:`, ` vs. `]
    #   [D2 §alt-route(2): " vs. " + (O/U | Spread: | Moneyline | Both Teams to
    #    Score | end in a draw)]  [D2 skip-sample: "Spread: Warriors (-3.5)",
    #    "Games Total: O/U 2.5", "Niagara Purple Eagles vs. Howard Bison: O/U"]
    ("sports_line", re.compile(r"\bo\s*/?\s*u\s*\d", _F)),        # "O/U 2.5", ": O/U 145.5"
    ("sports_line", re.compile(r"\bover\s*/\s*under\b", _F)),
    ("sports_line", re.compile(r"^\s*spread\s*:", _F)),           # "Spread: Clippers (-3.5)"
    ("sports_line", re.compile(r"\bspread\s*:\s*[A-Za-z].{0,40}\([+-]\d", _F)),
    ("sports_line", re.compile(r"\([+-]\d+(?:\.\d+)?\)", _F)),    # point spread "(-3.5)" / "(+1.5)"
    ("sports_line", re.compile(r"\bmoneyline\b", _F)),
    ("sports_line", re.compile(r"\bboth teams to score\b", _F)),
    ("sports_line", re.compile(r"\bend in a draw\b", _F)),
    ("sports_line", re.compile(r"^\s*exact score\s*:", _F)),
    ("sports_line", re.compile(r"^\s*games?\s+total\s*:\s*o\s*/?\s*u", _F)),
    ("sports_line", re.compile(
        r"\b(1h|2h|first half|second half|first quarter|second quarter|"
        r"third quarter|fourth quarter|1st inning|first period)\b"
        r".{0,25}\b(o\s*/?\s*u|over/under|moneyline|total|spread)\b", _F)),
    ("sports_line", re.compile(
        r"\b(total\s+)?corners\b.{0,15}\b(o\s*/?\s*u|over/under|\d)", _F)),

    # ── sports player props ─────────────────────────────────────────
    # Family: "sports line" (player-prop sub-shape)  [D2 skip-sample:
    # "Kel'el Ware: Rebounds O/U 6.5", "Julio César Enciso: 1+ goals",
    # "Johan Manzambi: 3+ shots"]
    ("sports_prop", re.compile(
        r":\s*(rebounds|points|assists|goals|shots|saves|blocks|steals|"
        r"turnovers|passing yards|rushing yards|receiving yards|touchdowns|"
        r"home runs|\bhits\b|strikeouts|three[- ]pointers|3[- ]pointers|"
        r"pra|double[- ]double|triple[- ]double)\b\s*(o\s*/?\s*u|over/under)?\s*\d",
        _F)),
    ("sports_prop", re.compile(
        r":\s*\d+\+\s+(goals|shots|assists|points|rebounds|saves|tackles|"
        r"passes|aces|kills)\b", _F)),

    # ── sports match by date ──────────────────────────────────────
    # Family: sports (single-match template)  [D2 skip/sample: "Will CD
    # Palestino win on 2026-05-26?", "Will Fulham FC win on 2026-02-15?",
    # "Will Legia Warszawa win on 2025-11-27?"]  A date-anchored
    # "win on YYYY-MM-DD" is the Polymarket single-fixture form; elections
    # read "win the 20xx … election".
    ("sports_match_date", re.compile(r"\bwin on \d{4}-\d{2}-\d{2}\b", _F)),

    # ── sports / esports set & map winners ──────────────────────
    # Family: sports/esports  [D1 slug set-shape][D2 §alt-route(2) "Set N
    # Winner:"]  e.g. "Set 1 Winner: Eala vs Zheng", "Map 1 Winner",
    # "Set Handicap: Tien (-1.5) vs ...", "Total Sets O/U".
    ("sports_set_map", re.compile(
        r"\b(set|map|game|frame|leg|end)\s*\d+\s+winner\b", _F)),
    ("sports_set_map", re.compile(r"\btotal\s+sets\b\s*(o\s*/?\s*u|over/under|\d)", _F)),
    ("sports_set_map", re.compile(r"\b(set|map)\s*handicap\b", _F)),

    # ── esports ────────────────────────────────────────────────
    # Family: "Esports (game code)"  [D1 dota2-, cs2-, lol-, mlbb- slugs]
    #   [D2 §alt-route(2) "(BO3)"/"(BO5)"]  Title forms: "LoL: A vs B",
    #   "Counter-Strike: A vs B - Map 1 Winner", "Dota 2: …", "Valorant: …",
    #   "MLBB: …", plus best-of markers anywhere in the title.
    ("esports", re.compile(
        r"^\s*(lol|league of legends|dota\s*2?|counter[- ]?strike|cs\s*:?\s*go|"
        r"cs2|valorant|overwatch\s*2?|rocket league|mlbb|mobile legends|pubg|"
        r"apex legends|rainbow six|\br6\b|starcraft\s*2?|hearthstone|"
        r"king of glory|honor of kings|call of duty|\bcod\b|smite|"
        r"brawl stars|clash royale|teamfight tactics|\btft\b|"
        r"world of warcraft|\bwow\b)\s*[:\-]", _F)),
    ("esports", re.compile(r"\(\s*bo\s*[1357]\s*\)", _F)),        # "(BO3)", "(BO5)"
    ("esports", re.compile(r"\bmap\s*\d+\s*(winner|handicap|total|score)\b", _F)),

    # ── sports leagues & tournaments ──────────────────────────
    # Family: "Sports (league code)"  [D1 nba-, epl-, mlb-, fifwc-, wta-, cwbb-
    #   slugs]  plus the league / tournament vocabulary enumerated in
    #   market_filter.py / detect_insider_activity.py `_EXCLUSION_KEYWORDS`
    #   [D3].  Multi-word phrases catch the documented substring traps:
    #     "Presidents Cup" (golf)  -> \bpresidents cup\b        [P]
    #     "China Grand Prix" (F1)  -> \bgrand prix\b            [P]
    #   Every token is \b-anchored.  Tokens that could collide with a
    #   geopolitics phrase (bare "F1" ~ "F1 visa"; bare "US Open" ~ "US open
    #   its borders") are deliberately omitted.
    ("sports_league", re.compile(
        r"\b(nba|wnba|nfl|nhl|mlb|mls|ncaa|ncaaf|ncaab|"
        r"epl|efl|ufc|\bmma\b|\bpfl\b|bellator|\bpga\b|lpga|"
        r"\batp\b|\bwta\b|\bitf\b|nascar|indycar|motogp|"
        r"formula\s*1|formula\s*one|"
        r"\bkbo\b|\bnpb\b|cpbl|\bkhl\b|\bahl\b|euroleague|"
        r"\bnrl\b|\bafl\b|super rugby|six nations|"
        r"\bipl\b|\bbbl\b|\bpsl\b|the hundred)\b", _F)),
    ("sports_league", re.compile(
        r"\b(super bowl|world series|stanley cup|nba finals|nba playoffs|"
        r"march madness|final four|world cup|club world cup|"
        r"champions league|europa league|conference league|"
        r"premier league|la\s?liga|bundesliga|serie a|ligue 1|eredivisie|"
        r"primeira liga|scottish premiership|"
        r"grand prix|presidents cup|ryder cup|solheim cup|"
        r"masters tournament|the masters\b|the open championship|"
        r"pga championship|the players championship|"
        r"wimbledon|roland garros|australian open|french open|"
        r"kentucky derby|preakness|belmont stakes|breeders' cup|"
        r"tour de france|giro d'italia|vuelta a espa|"
        r"olympic\s+games|\bolympics\b|paralympic|commonwealth games|"
        r"asian games|pan american games|"
        r"copa america|copa libertadores|copa sudamericana|"
        r"gold cup|nations league|africa cup of nations|afcon|"
        r"uefa euro|euro 20\d\d|davis cup|billie jean king cup|laver cup|"
        r"the ashes|heineken cup|"
        r"eurovision|ballon d'or|the best fifa)\b", _F)),

    # ── stocks / equities ──────────────────────────────────
    # Family: stocks  [D3 'close at $', 'close above $', 'close below $',
    #   'finish week', 'quarterly earnings', 'beat earnings']  [D2 skip/sample:
    #   "Will Micron Technology, Inc. (MU) hit (LOW) $960 Week of …",
    #   "Will Tesla (TSLA) finish week of March 9 above $…",
    #   "Will Alphabet Inc. (GOOGL) hit (HIGH) $…"]
    #   Ticker parenthetical is required to be 2–5 uppercase letters so it
    #   does not collide with party abbreviations "(R)" / "(D)" / "(I)".
    ("stocks", re.compile(
        r"\([A-Z]{2,5}\)\s*(hit\b|finish\b|close\b|be (above|below)\b|"
        r"up or down\b)", _F)),
    ("stocks", re.compile(r"\bfinish\s+(the\s+)?week\s+(of\s+)?\w", _F)),
    ("stocks", re.compile(r"\bhit \(\s*(low|high)\s*\)\s*\$", _F)),
    ("stocks", re.compile(r"\bcloses?\s+(at|above|below)\s*\$", _F)),
    ("stocks", re.compile(
        r"\b(quarterly earnings|beat earnings|earnings per share|"
        r"report (its )?earnings|earnings call)\b", _F)),
    ("stocks", re.compile(
        r"\b(s&p 500|s&p500|nasdaq(-100| composite)?|dow jones|"
        r"russell 2000|ftse 100|nikkei 225|\bqqq\b|\bspy\b|\bvix\b)\b"
        r".{0,25}\b(above|below|close|up or down|hit|reach|\d)", _F)),

    # ── commodities ───────────────────────────────────────
    # Family: "Commodities / misc"  [D1 crude-oil, rodeo]
    #   [D3 'gold close between', 'gold price', 'price of gold',
    #    'gold above/below/reaches']  [D2 sample: "Will WTI Crude Oil (WTI)
    #    settle at $110 on April 8?"]
    ("commodities", re.compile(r"\b(wti|brent)?\s*crude oil\b", _F)),
    ("commodities", re.compile(
        r"\bprice of (gold|oil|silver|copper|natural gas|wheat|corn|"
        r"soybeans?|coffee|sugar|cocoa|platinum|palladium)\b", _F)),
    ("commodities", re.compile(
        r"\bgold\b.{0,25}?\b(close|price|above|below|reach|reaches|hit|hits|"
        r"between|settle)\b\s*\$?\s*[\d,]", _F)),
    ("commodities", re.compile(
        r"\bnatural gas\b.{0,25}?\b(above|below|close|settle|reach|\$)", _F)),
    ("commodities", re.compile(r"\b(bareback|saddle bronc|bull riding|"
                               r"steer wrestling|barrel racing|team roping|"
                               r"tie-down roping)\b", _F)),  # rodeo events [D1]

    # ── entertainment / awards ──────────────────────────
    # Family: entertainment  [D3 'oscars', 'grammy', 'emmy', 'golden globe',
    #   'academy award', 'box office', 'billboard', 'spotify']  [D2 skip-sample:
    #   "nominated for Best Actor at the 98th [Oscars]",
    #   "\"NEVER ENOUGH - Turnstile\" win Best Rock Album",
    #   "Elden Ring: Nightreign win Game of the Year",
    #   "\"Choosin' Texas - Ella Langley\" ... Billboard 200"]
    #   [D  2026-08-30-geo-backlog-and-category-reach.md: Eurovision]
    ("entertainment", re.compile(
        r"\bbest\s+(actor|actress|picture|director|film|"
        r"animated (feature|film)|documentary( feature)?|original song|"
        r"original score|supporting (actor|actress)|cinematography|"
        r"animation|rock album|new artist|record of the year|"
        r"song of the year|album of the year|visual effects|"
        r"adapted screenplay|original screenplay|"
        r"game of the year)\b", _F)),
    ("entertainment", re.compile(
        r"\b(academy awards?|the oscars?\b|\bemmys?\b|\bgrammys?\b|golden globe|"
        r"\bbaftas?\b|tony award|"
        r"billboard\s+(hot\s*100|200|global)|"
        r"rotten tomatoes|tomatometer|metacritic|"
        r"box office|opening weekend|"
        r"first[- ]week (box office|streams|sales)|"
        r"spotify\s+(streams|chart|global|monthly listeners)|"
        r"most[- ]streamed|#1 on (spotify|the billboard|apple music))\b", _F)),

    # ── novelty / religion ─────────────────────────────
    # Family: novelty  [D3 'jesus', 'christ', 'rapture', 'antichrist',
    #   'second coming', 'bible']
    ("novelty_religion", re.compile(
        r"\b(the second coming|the rapture\b|antichrist|"
        r"(will )?jesus (christ )?(returns?|come back|be seen)|"
        r"will god\b|will the world end|end of the world (happen|occur|by)|"
        r"alien(s)? (make )?(first )?contact|extraterrestrial (life|contact)|"
        r"\bbigfoot\b|loch ness monster)\b", _F)),
]


def prefilter_family(title: Optional[str]) -> Optional[str]:
    """
    Return the family name of the first EXCLUDE_PATTERNS entry that matches
    ``title``, or ``None`` if the title is RESIDUAL.

    A ``None`` / empty / whitespace-only / non-str title is RESIDUAL — the
    pre-filter never excludes something it cannot read.
    """
    if not isinstance(title, str):
        return None
    t = title.strip()
    if not t:
        return None
    for family, pattern in EXCLUDE_PATTERNS:
        if pattern.search(t):
            return family
    return None


def prefilter(title: Optional[str]) -> str:
    """Return ``EXCLUDE`` if the title matches a documented non-geo template
    family, else ``RESIDUAL``. Pure; see module docstring."""
    return EXCLUDE if prefilter_family(title) is not None else RESIDUAL


# Distinct family names, in list order — used by the coverage harness.
FAMILIES = list(dict.fromkeys(fam for fam, _ in EXCLUDE_PATTERNS))
