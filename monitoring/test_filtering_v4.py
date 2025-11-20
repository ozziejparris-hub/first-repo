#!/usr/bin/env python3
"""
Test comprehensive filtering V4 - fixes for missed patterns.

Tests the new "price of" crypto pattern and improved vs. regex.
"""

import re


def should_exclude_market(market_title: str) -> bool:
    """Test version matching monitor.py logic."""
    title = market_title
    title_lower = market_title.lower()

    # ===== CRYPTO PATTERN 1: "PRICE OF" (NEW) =====
    if "price of" in title_lower:
        crypto_names = [
            'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol',
            'xrp', 'ripple', 'bnb', 'binance', 'cardano', 'ada',
            'dogecoin', 'doge', 'polygon', 'matic', 'avalanche', 'avax',
            'chainlink', 'link'
        ]

        price_indicators = [
            'be above $', 'be less than $', 'be below $', 'be between $',
            'above $', 'less than $', 'below $'
        ]

        has_crypto = any(crypto in title_lower for crypto in crypto_names)
        has_price_indicator = any(indicator in title_lower for indicator in price_indicators)

        if has_crypto and has_price_indicator:
            return True  # EXCLUDE

    # ===== CRYPTO PATTERN 2-4 =====
    if "up or down" in title_lower:
        return True

    if "dip to $" in title_lower:
        return True

    crypto_names = ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'xrp']
    price_verbs = ['reach $', 'hit $', 'close above', 'finish week', 'all time high']

    if any(crypto in title_lower for crypto in crypto_names):
        if any(verb in title_lower for verb in price_verbs):
            return True

    # ===== SPORTS: VS. PATTERN (IMPROVED REGEX) =====
    if re.search(r'\bvs\.?\b', title, re.IGNORECASE):
        military_keywords = ['military', 'clash', 'engagement', 'war', 'conflict']
        if not any(keyword in title_lower for keyword in military_keywords):
            return True

    if 'end in a draw' in title_lower:
        return True

    # ===== SPORTS TEAMS =====
    sports_teams = ['penguins', 'predators', 'thunder', 'hornets', 'nets', 'magic',
                   'clippers', 'mavericks', 'warriors', 'lakers', 'celtics', 'pelicans']
    if any(team in title_lower for team in sports_teams):
        # Check for both "vs" and "vs." variations
        if any(ind in title_lower for ind in [' vs.', ' vs ', 'win on ', 'beat ']):
            return True

    # ===== ENTERTAINMENT (NEW PATTERNS) =====
    if 'spotify' in title_lower:
        if any(ind in title_lower for ind in ['top', 'most streamed', '#1', 'artist']):
            return True

    if 'miss universe' in title_lower or 'miss world' in title_lower:
        return True

    if 'box office' in title_lower or 'opening weekend' in title_lower:
        return True

    if 'app store' in title_lower and '#1' in title:
        return True

    # ===== SPORTS LEAGUES (NEW) =====
    sports_leagues = [
        'nfl', 'nba', 'nhl', 'mlb', 'mls',
        'champions league', 'uefa',
        'premier league', 'la liga',
        'super bowl', 'stanley cup',
        'afc west', 'nfc east',  # Added NFC East
        'playoff', 'championship'
    ]

    if any(league in title_lower for league in sports_leagues):
        # Exception: World Cup qualifying
        if 'world cup' in title_lower and 'qualifying' in title_lower:
            pass
        else:
            return True

    # ===== TRADITIONAL SPORTS KEYWORDS =====
    traditional_sports = ['cowboys', 'patriots', 'yankees']
    if any(keyword in title_lower for keyword in traditional_sports):
        return True

    return False


def test_filtering_v4():
    """Test the V4 filtering updates."""

    print("="*70)
    print("COMPREHENSIVE FILTERING V4 - TEST MISSED PATTERNS")
    print("="*70)

    # Markets that SHOULD BE EXCLUDED
    should_exclude = [
        # NEW: "price of" crypto patterns (was being missed!)
        "Will the price of Bitcoin be above $96,000 on November 17?",
        "Will the price of Ethereum be less than $3,000 on November 16?",
        "Will the price of XRP be above $2.20 on November 21?",
        "Will the price of Solana be above $140 on November 20?",

        # Team vs Team (improved regex)
        "Warriors vs. Pelicans",
        "Lakers vs. Celtics",

        # Previous crypto patterns (should still work)
        "Bitcoin Up or Down - November 14, 6:00PM",
        "Will Bitcoin dip to $94,000 November 10-16?",

        # NEW: Entertainment patterns
        "Will Bad Bunny be the top Spotify artist for 2025?",
        "Will The Weeknd be the most streamed Spotify artist?",
        "Will Miss Universe be from Canada?",
        "Will 'The Running Man' Opening Weekend Box Office be above $50M?",

        # NEW: Sports leagues
        "Will Bayern Munich win the 2025–26 Champions League?",
        "Will the Cowboys win the NFC East?",
    ]

    # Markets that SHOULD BE KEPT
    should_keep = [
        # Elections
        "Will José Antonio Kast win the Chilean presidential election?",
        "Will Evelyn Matthei win the Chilean presidential election?",

        # Economics/Policy
        "Fed decreases interest rates by 25 bps",
        "Will the EU impose new tariffs on US goods in 2025?",

        # Geopolitics
        "Will Israel strike Gaza on November 16?",
        "Will Russia capture Pokrovsk by November 30?",
        "US x Venezuela military engagement by December 31?",
        "Will Trump talk to Volodymyr Zelenskyy in November?",
    ]

    print("\n🚫 TESTING MARKETS THAT SHOULD BE EXCLUDED:")
    print("-"*70)

    excluded_correctly = 0
    excluded_incorrectly = 0

    for market in should_exclude:
        result = should_exclude_market(market)
        status = "✅ EXCLUDED" if result else "❌ KEPT (ERROR)"

        if result:
            excluded_correctly += 1
        else:
            excluded_incorrectly += 1

        print(f"{status}: {market}")

    print("\n✅ TESTING MARKETS THAT SHOULD BE KEPT:")
    print("-"*70)

    kept_correctly = 0
    kept_incorrectly = 0

    for market in should_keep:
        result = should_exclude_market(market)
        status = "✅ KEPT" if not result else "❌ EXCLUDED (ERROR)"

        if not result:
            kept_correctly += 1
        else:
            kept_incorrectly += 1

        print(f"{status}: {market}")

    # Summary
    print("\n" + "="*70)
    print("FILTERING SUMMARY:")
    print("-"*70)

    total_exclude = len(should_exclude)
    total_keep = len(should_keep)
    total_markets = total_exclude + total_keep

    print(f"Markets that should be EXCLUDED: {total_exclude}")
    print(f"  ✅ Correctly excluded: {excluded_correctly}")
    print(f"  ❌ Incorrectly kept: {excluded_incorrectly}")
    print(f"  Accuracy: {excluded_correctly/total_exclude*100:.1f}%")

    print(f"\nMarkets that should be KEPT: {total_keep}")
    print(f"  ✅ Correctly kept: {kept_correctly}")
    print(f"  ❌ Incorrectly excluded: {kept_incorrectly}")
    print(f"  Accuracy: {kept_correctly/total_keep*100:.1f}%")

    print(f"\nOVERALL ACCURACY: {(excluded_correctly + kept_correctly)/total_markets*100:.1f}%")
    print(f"Total markets tested: {total_markets}")

    # Pattern breakdown
    print("\n" + "="*70)
    print("NEW PATTERN DETECTION:")
    print("-"*70)

    price_of_count = sum(1 for m in should_exclude if 'price of' in m.lower())
    vs_count = sum(1 for m in should_exclude if 'vs.' in m or 'vs ' in m.lower())
    spotify_count = sum(1 for m in should_exclude if 'spotify' in m.lower())
    miss_universe_count = sum(1 for m in should_exclude if 'miss universe' in m.lower())
    box_office_count = sum(1 for m in should_exclude if 'box office' in m.lower())
    sports_league_count = sum(1 for m in should_exclude if any(l in m.lower() for l in ['champions league', 'nfc east']))

    print(f"  'price of' crypto: {price_of_count} markets (NEW - was being missed!)")
    print(f"  vs. sports: {vs_count} markets (improved regex)")
    print(f"  Spotify: {spotify_count} markets (NEW)")
    print(f"  Miss Universe: {miss_universe_count} markets (NEW)")
    print(f"  Box Office: {box_office_count} markets (NEW)")
    print(f"  Sports Leagues: {sports_league_count} markets (NEW)")

    print("\n" + "="*70)

    if excluded_incorrectly == 0 and kept_incorrectly == 0:
        print("\n🎉 ALL TESTS PASSED! V4 filtering fixes work perfectly.")
        print("\nThe 'price of' pattern was the critical missing piece.")
        print("Your Telegram notifications should now be clean!")
        return True
    else:
        print(f"\n⚠️ {excluded_incorrectly + kept_incorrectly} errors detected.")
        return False


if __name__ == "__main__":
    test_filtering_v4()
