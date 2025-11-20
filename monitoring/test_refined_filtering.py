#!/usr/bin/env python3
"""
Test script for REFINED market filtering.

Focuses on the critical patterns still getting through:
- " vs. " team matches
- "end in a draw" betting
- Price predictions for stocks/crypto
- Sports betting terminology
"""


def is_sports_or_noise(market_title: str) -> bool:
    """
    Refined exclusion filter.
    Returns True if market should be EXCLUDED.
    """
    title = market_title
    title_lower = market_title.lower()

    # ===== PATTERN 1: TEAM VS TEAM =====
    # Match " vs. " with spaces (case-sensitive to avoid matching "vs" in words)
    if ' vs. ' in title or ' vs ' in title_lower:
        # EXCEPTION: Keep if military/geopolitics context
        military_keywords = ['military', 'clash', 'engagement', 'war', 'conflict',
                           'ceasefire', 'invasion', 'battle', 'strike']
        has_military_context = any(keyword in title_lower for keyword in military_keywords)

        if not has_military_context:
            return True  # EXCLUDE: Sports match

    # ===== PATTERN 2: DRAW BETTING =====
    if 'end in a draw' in title_lower:
        return True  # EXCLUDE: Sports draw betting

    # ===== PATTERN 3: SPORTS BETTING TERMINOLOGY =====
    sports_betting_terms = [
        'total sets:',
        'o/u ',  # Over/Under with space
        'spread:',
        'over/under',
        'total points:',
        'total goals:'
    ]

    for term in sports_betting_terms:
        if term in title_lower:
            return True  # EXCLUDE: Sports betting

    # ===== PATTERN 4: PRICE PREDICTIONS (not policy) =====
    # Asset names (stocks and crypto)
    asset_names = [
        'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol',
        'xrp', 'bnb', 'cardano', 'ada', 'doge', 'dogecoin',
        'gold', 'silver', 'oil',  # Commodities
        'aapl', 'apple', 'msft', 'microsoft', 'tsla', 'tesla',
        'googl', 'google', 'amzn', 'amazon', 'meta', 'nvidia'
    ]

    # Price prediction indicators
    price_indicators = [
        'finish week',
        'be between $',
        'hit $',
        'reach $',
        'close above $',
        'close below $',
        'close between $',
        'all time high',
        'price of',
        'ath ',  # All-time high abbreviation
        'above $',
        'below $',
        'trade above',
        'trade below'
    ]

    has_asset = any(asset in title_lower for asset in asset_names)
    has_price = any(indicator in title_lower for indicator in price_indicators)

    if has_asset and has_price:
        # EXCEPTION: Keep if it's about Fed/central bank POLICY
        policy_keywords = [
            'fed ', 'ecb ', 'bank of japan', 'interest rate',
            'federal reserve', 'central bank', 'policy', 'meeting',
            'bps', 'basis points', 'rate cut', 'rate hike'
        ]
        has_policy_context = any(keyword in title_lower for keyword in policy_keywords)

        if not has_policy_context:
            return True  # EXCLUDE: Price prediction

    # ===== PATTERN 5: ENTERTAINMENT/YOUTUBE =====
    entertainment_keywords = [
        'mrbeast',
        'video get',
        'youtube views',
        'views by',
        'million views',
        'streaming views'
    ]

    for keyword in entertainment_keywords:
        if keyword in title_lower:
            return True  # EXCLUDE: Entertainment

    # ===== PATTERN 6: CRYPTO/GAMING TOURNAMENTS =====
    # Keep "World Cup" (geopolitics), exclude gaming/crypto tournaments
    if 'cup' in title_lower:
        tournament_keywords = ['uniswap', 'gaming', 'esports', 'league']
        if any(keyword in title_lower for keyword in tournament_keywords):
            return True  # EXCLUDE: Gaming/crypto tournament

    # ===== PATTERN 7: OBVIOUS TEAM NAMES =====
    # Additional sports team patterns that slip through
    obvious_sports_teams = [
        'penguins', 'predators', 'thunder', 'hornets', 'nets', 'magic',
        'clippers', 'mavericks', 'warriors', 'lakers', 'celtics',
        'wolverines', 'horned frogs', 'bulldogs', 'red storm',
        'memphis', 'east carolina', 'yale', 'tcu', 'michigan'
    ]

    # Only exclude if it looks like team vs team or game betting
    has_team = any(team in title_lower for team in obvious_sports_teams)
    looks_like_game = any(indicator in title_lower for indicator in [' vs ', 'win on ', 'beat ', 'defeat'])

    if has_team and looks_like_game:
        return True  # EXCLUDE: Sports game

    return False  # KEEP this market


def test_refined_filtering():
    """Test the refined filtering with real-world examples."""

    print("="*70)
    print("REFINED MARKET FILTERING TEST")
    print("="*70)

    # Markets that SHOULD BE EXCLUDED
    should_exclude = [
        "Penguins vs. Predators",
        "Will Luxembourg vs. Germany end in a draw?",
        "Will the price of Bitcoin be between $96,000 and $98,000",
        "Will Apple (AAPL) finish week of November 10 above $280?",
        "Total Sets: O/U 2.5",
        "Will MrBeast's trap video get 65 million views?",
        "Thunder vs. Hornets",
        "Nets vs. Magic",
        "Michigan Wolverines vs. TCU Horned Frogs",
        "Clippers vs. Mavericks",
        "Memphis vs. East Carolina",
        "Yale Bulldogs vs. St. John's Red Storm",
        "Will Kazakhstan vs. Belgium end in a draw?",
        "Will Gibraltar vs. Montenegro end in a draw?",
        "Will Morocco vs. Mozambique end in a draw?",
        "Will Gold close above $5000",
        "XRP all time high by December 31?",
        "Will Ethereum hit $10,000 by end of year?",
        "Uniswap Cup winner 2025"
    ]

    # Markets that SHOULD BE KEPT
    should_keep = [
        "China x Taiwan military clash by December 31?",
        "US x Venezuela military engagement by December 31?",
        "Will Israel strike 3 countries in November 2025?",
        "Russia x Ukraine ceasefire in 2025?",
        "Fed decreases interest rates by 50+ bps",
        "Will Franco Parisi win the Chilean presidential election?",
        "Maduro out by November 30, 2025?",
        "Bank of Japan increases interest rates by 25 bps",
        "Will Putin meet with Zelenskyy in 2025?",
        "Will the ECB announce no change at the December meeting?",
        "Will Călin Georgescu be the next Mayor of Bucharest?",
        "Will there be a ceasefire in Gaza by March 2025?"
    ]

    print("\n🚫 TESTING MARKETS THAT SHOULD BE EXCLUDED:")
    print("-"*70)

    excluded_correctly = 0
    excluded_incorrectly = 0

    for market in should_exclude:
        result = is_sports_or_noise(market)
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
        result = is_sports_or_noise(market)
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

    # Detailed breakdown
    print("\n" + "="*70)
    print("PATTERN DETECTION BREAKDOWN:")
    print("-"*70)

    pattern_counts = {
        'Team vs Team': 0,
        'Draw Betting': 0,
        'Sports Betting Terms': 0,
        'Price Predictions': 0,
        'Entertainment': 0,
        'Tournaments': 0,
        'Obvious Teams': 0
    }

    for market in should_exclude:
        if ' vs. ' in market or ' vs ' in market.lower():
            pattern_counts['Team vs Team'] += 1
        elif 'end in a draw' in market.lower():
            pattern_counts['Draw Betting'] += 1
        elif any(term in market.lower() for term in ['total sets', 'o/u', 'spread']):
            pattern_counts['Sports Betting Terms'] += 1
        elif any(term in market.lower() for term in ['price of', 'finish week', 'close above', 'hit $', 'all time high']):
            pattern_counts['Price Predictions'] += 1
        elif 'mrbeast' in market.lower() or 'video get' in market.lower():
            pattern_counts['Entertainment'] += 1
        elif 'cup' in market.lower():
            pattern_counts['Tournaments'] += 1

    for pattern, count in pattern_counts.items():
        if count > 0:
            print(f"  {pattern}: {count} markets")

    print("\n" + "="*70)

    # Return success
    if excluded_incorrectly == 0 and kept_incorrectly == 0:
        print("\n🎉 ALL TESTS PASSED! Refined filter working perfectly.")
        return True
    else:
        print(f"\n⚠️ {excluded_incorrectly + kept_incorrectly} errors detected. Review filter logic.")
        return False


if __name__ == "__main__":
    test_refined_filtering()
