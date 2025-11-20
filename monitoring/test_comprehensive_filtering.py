#!/usr/bin/env python3
"""
Test script for comprehensive market filtering.

Tests the updated _should_exclude_market() logic with real-world examples.
"""

import re


def should_exclude_market(market_title: str) -> bool:
    """
    Test version of the exclusion filter.
    Returns True if market should be EXCLUDED.
    """
    title_lower = market_title.lower()

    # ===== PATTERN 1: INTERNATIONAL SPORTS MATCHES =====
    # Updated regex to handle multi-word country names
    sports_match_pattern = r'will\s+[\w\s]+\s+win\s+on\s+\d{4}-\d{2}-\d{2}'
    if re.search(sports_match_pattern, title_lower):
        geopolitics_context = ['war', 'conflict', 'election', 'invasion', 'battle', 'ceasefire']
        has_geopolitics_context = any(word in title_lower for word in geopolitics_context)

        if not has_geopolitics_context:
            return True  # EXCLUDE: Sports match

    # ===== PATTERN 2: ESPORTS =====
    esports_keywords = [
        'counter-strike', 'counter strike', 'cs:go', 'cs2',
        'valorant', 'league of legends', 'lol', 'dota', 'dota 2',
        'overwatch', 'rocket league', 'starcraft',
        '(bo1)', '(bo3)', '(bo5)',
        ' vs ', ' v ', ' versus '
    ]

    for keyword in esports_keywords:
        if keyword in title_lower:
            if any(indicator in title_lower for indicator in [' vs ', ' v ', '(bo', 'versus']):
                return True  # EXCLUDE: Esports

    # ===== PATTERN 3: SPREADS =====
    if market_title.startswith('Spread:'):
        return True  # EXCLUDE: Sports spread

    # ===== PATTERN 4: CRYPTO PRICE PREDICTIONS =====
    crypto_keywords = [
        'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol',
        'xrp', 'ripple', 'cardano', 'ada', 'dogecoin', 'doge',
        'polkadot', 'dot', 'polygon', 'matic', 'avalanche', 'avax'
    ]

    price_indicators = [
        'dip to $', 'reach $', 'hit $', 'above $', 'below $',
        '>$', '<$', 'price above', 'price below',
        'will.*hit.*\\$\\d+', 'will.*reach.*\\$\\d+',
        'up or down'
    ]

    has_crypto = any(keyword in title_lower for keyword in crypto_keywords)
    has_price_indicator = any(
        indicator in title_lower or re.search(indicator, title_lower)
        for indicator in price_indicators
    )

    if has_crypto and has_price_indicator:
        return True  # EXCLUDE: Crypto price

    # ===== PATTERN 5: TRADITIONAL SPORTS =====
    traditional_sports_keywords = [
        'nfl', 'nba', 'mlb', 'nhl', 'mls',
        'super bowl', 'world series', 'stanley cup', 'nba finals',
        'championship', 'playoff', 'playoffs',
        'warriors', 'lakers', 'celtics', 'heat', 'bulls', 'knicks',
        'cowboys', 'patriots', 'chiefs', 'eagles', 'packers',
        'yankees', 'red sox', 'dodgers', 'mets', 'cubs',
        'maple leafs', 'bruins', 'canadiens', 'rangers',
        'touchdown', 'home run', 'goal', 'field goal', 'penalty kick',
        'quarterback', 'pitcher', 'goalie'
    ]

    for keyword in traditional_sports_keywords:
        if keyword in title_lower:
            return True  # EXCLUDE: Sports

    # ===== PATTERN 6: ENTERTAINMENT/CELEBRITY =====
    entertainment_keywords = [
        'elon musk', 'taylor swift', 'kanye', 'kardashian',
        'oscar', 'grammy', 'emmy', 'golden globe',
        'movie', 'film', 'album', 'song', 'concert',
        'tweet', 'twitter', 'x post', 'instagram post',
        'tiktok', 'youtube', 'spotify'
    ]

    for keyword in entertainment_keywords:
        if keyword in title_lower:
            return True  # EXCLUDE: Entertainment

    # ===== PATTERN 7: STOCK MARKET =====
    stock_keywords = [
        's&p 500', 'sp500', 's&p500', 'dow jones', 'nasdaq',
        'stock market', 'stock price', 'share price'
    ]

    policy_context = ['fed', 'ecb', 'central bank', 'interest rate', 'policy', 'meeting']
    has_policy_context = any(word in title_lower for word in policy_context)

    if not has_policy_context:
        for keyword in stock_keywords:
            if keyword in title_lower:
                return True  # EXCLUDE: Stock market

    return False  # PASS: Keep this market


def test_filtering():
    """Test the filtering with real-world examples."""

    # Markets that should be EXCLUDED
    excluded_markets = [
        # International sports matches
        "Will Italy win on 2025-11-13?",
        "Will Canada win on 2025-11-13?",
        "Will Armenia win on 2025-11-16?",
        "Will Jamaica win on 2025-11-13?",
        "Will Suriname win on 2025-11-13?",
        "Will Luxembourg win on 2025-11-14?",
        "Will Northern Ireland win on 2025-11-17?",
        "Will Faroe Islands win on 2025-11-14?",
        "Will Ecuador win on 2025-11-13?",

        # Esports
        "Counter-Strike: Passion UA vs paiN (BO3)",
        "Valorant: Bonk vs BLX CORP (BO1)",
        "Counter-Strike: 9z vs Sharks (BO3)",

        # Spreads
        "Spread: Suns (-4.5)",
        "Spread: Panthers (-1.5)",

        # Crypto price predictions
        "Will Solana dip to $130 November 10-16?",
        "Will Bitcoin reach $100k by December 2025?",
        "Will Ethereum hit $5000?",

        # Traditional sports
        "Will the Lakers win the NBA championship?",
        "Super Bowl LVIII winner",
        "Will the Cowboys make the playoffs?",
    ]

    # Markets that should PASS (keep)
    kept_markets = [
        # Elections
        "Will Călin Georgescu be the next Mayor of Bucharest?",
        "Will Crin Antonescu be the next Mayor of Bucharest?",
        "Will Trump win the 2024 Presidential Election?",
        "Will the Senate confirm the new Supreme Court nominee?",

        # Geopolitics
        "Will Putin meet with Zelenskyy in 2025?",
        "Evacuation of Tehran ordered in 2025?",
        "Will Israel annex any territory by December 31?",
        "Will Italy invade Albania by 2026?",  # Country name but geopolitical action
        "Will there be a ceasefire in Gaza by March 2025?",

        # Economics
        "Will the ECB announce no change at the December meeting?",
        "Will the Fed raise interest rates in Q1 2025?",
        "Will US GDP growth exceed 3% in 2025?",

        # Business
        "Will Microsoft be the largest company in the world?",
        "Will Apple be the largest company in the world?",

        # Climate
        "Will global temperature increase by 1.5°C in 2025?",
    ]

    print("="*70)
    print("COMPREHENSIVE MARKET FILTERING TEST")
    print("="*70)

    # Test excluded markets
    print("\n🚫 TESTING MARKETS THAT SHOULD BE EXCLUDED:")
    print("-"*70)

    excluded_correctly = 0
    excluded_incorrectly = 0

    for market in excluded_markets:
        result = should_exclude_market(market)
        status = "✅ EXCLUDED" if result else "❌ KEPT (ERROR)"

        if result:
            excluded_correctly += 1
        else:
            excluded_incorrectly += 1

        print(f"{status}: {market}")

    # Test kept markets
    print("\n✅ TESTING MARKETS THAT SHOULD BE KEPT:")
    print("-"*70)

    kept_correctly = 0
    kept_incorrectly = 0

    for market in kept_markets:
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

    total_excluded = len(excluded_markets)
    total_kept = len(kept_markets)
    total_markets = total_excluded + total_kept

    print(f"Markets that should be EXCLUDED: {total_excluded}")
    print(f"  ✅ Correctly excluded: {excluded_correctly}")
    print(f"  ❌ Incorrectly kept: {excluded_incorrectly}")
    print(f"  Accuracy: {excluded_correctly/total_excluded*100:.1f}%")

    print(f"\nMarkets that should be KEPT: {total_kept}")
    print(f"  ✅ Correctly kept: {kept_correctly}")
    print(f"  ❌ Incorrectly excluded: {kept_incorrectly}")
    print(f"  Accuracy: {kept_correctly/total_kept*100:.1f}%")

    print(f"\nOVERALL ACCURACY: {(excluded_correctly + kept_correctly)/total_markets*100:.1f}%")
    print(f"Total markets tested: {total_markets}")

    # Pattern breakdown
    print("\n" + "="*70)
    print("PATTERN DETECTION BREAKDOWN:")
    print("-"*70)

    pattern_counts = {
        'International Sports': 0,
        'Esports': 0,
        'Spreads': 0,
        'Crypto Prices': 0,
        'Traditional Sports': 0,
        'Elections (KEPT)': 0,
        'Geopolitics (KEPT)': 0,
        'Economics (KEPT)': 0,
        'Business (KEPT)': 0,
    }

    # Count international sports
    for market in excluded_markets:
        if re.search(r'will\s+\w+\s+win\s+on\s+\d{4}-\d{2}-\d{2}', market.lower()):
            pattern_counts['International Sports'] += 1
        elif any(keyword in market.lower() for keyword in ['counter-strike', 'valorant', '(bo']):
            pattern_counts['Esports'] += 1
        elif market.startswith('Spread:'):
            pattern_counts['Spreads'] += 1
        elif any(keyword in market.lower() for keyword in ['solana', 'bitcoin', 'ethereum']):
            pattern_counts['Crypto Prices'] += 1
        elif any(keyword in market.lower() for keyword in ['lakers', 'cowboys', 'super bowl']):
            pattern_counts['Traditional Sports'] += 1

    for market in kept_markets:
        if any(keyword in market.lower() for keyword in ['mayor', 'president', 'election', 'senate']):
            pattern_counts['Elections (KEPT)'] += 1
        elif any(keyword in market.lower() for keyword in ['putin', 'zelenskyy', 'israel', 'ceasefire', 'invade']):
            pattern_counts['Geopolitics (KEPT)'] += 1
        elif any(keyword in market.lower() for keyword in ['ecb', 'fed', 'gdp']):
            pattern_counts['Economics (KEPT)'] += 1
        elif any(keyword in market.lower() for keyword in ['microsoft', 'apple', 'company']):
            pattern_counts['Business (KEPT)'] += 1

    for pattern, count in pattern_counts.items():
        if count > 0:
            print(f"  {pattern}: {count} markets")

    print("\n" + "="*70)

    # Return success
    if excluded_incorrectly == 0 and kept_incorrectly == 0:
        print("\n🎉 ALL TESTS PASSED! Filter working perfectly.")
        return True
    else:
        print(f"\n⚠️ {excluded_incorrectly + kept_incorrectly} errors detected. Review filter logic.")
        return False


if __name__ == "__main__":
    test_filtering()
