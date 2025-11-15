#!/usr/bin/env python3
"""
Test script for CRYPTO PRICE FILTERING.

The sports filtering worked great, but 90% of notifications are now
crypto price predictions. This test focuses on stronger crypto filtering.
"""


def is_sports_or_noise(market_title):
    """
    Return True if market should be EXCLUDED.

    Focus: CRYPTO PRICE SPECULATION (the new main noise source)
    """
    title = market_title
    title_lower = title.lower()

    # ===== CRYPTO PRICE SPECULATION (CRITICAL) =====

    # Pattern 1: "Up or Down" - ALWAYS crypto speculation
    if "up or down" in title_lower:
        return True  # EXCLUDE - 100% crypto markets

    # Pattern 2: "Dip to $" - crypto price markets
    if "dip to $" in title_lower:
        return True  # EXCLUDE

    # Pattern 3: Comprehensive crypto price predictions
    # Full names AND tickers to catch both formats
    crypto_names = [
        'bitcoin', 'btc',
        'ethereum', 'eth',
        'solana', 'sol',
        'xrp', 'ripple',
        'bnb', 'binance',
        'cardano', 'ada',
        'dogecoin', 'doge',
        'polygon', 'matic',
        'avalanche', 'avax',
        'chainlink', 'link'
    ]

    # Price prediction verbs
    price_verbs = [
        'reach $', 'hit $', 'close above', 'close between',
        'finish week', 'all time high', 'dip to', 'be between $'
    ]

    # If has crypto name + price verb = price prediction
    if any(crypto in title_lower for crypto in crypto_names):
        if any(verb in title_lower for verb in price_verbs):
            return True  # EXCLUDE crypto price prediction

    # ===== SPORTS (existing filters) =====

    # Team vs Team
    if ' vs. ' in title:  # Case sensitive - note the period
        military_keywords = ['military', 'clash', 'engagement', 'war', 'conflict']
        if not any(keyword in title_lower for keyword in military_keywords):
            return True  # EXCLUDE sports

    # Draw betting
    if 'end in a draw' in title_lower:
        return True  # EXCLUDE

    # Sports betting terminology
    if any(term in title for term in ['Total Sets:', 'O/U ', 'Spread:']):
        return True  # EXCLUDE

    # ===== ENTERTAINMENT =====

    # Gaming awards
    if 'game of the year' in title_lower or 'game awards' in title_lower:
        return True  # EXCLUDE

    # YouTube/MrBeast
    if 'mrbeast' in title_lower or 'video get' in title_lower:
        return True  # EXCLUDE

    # ===== STOCK PRICE (not policy) =====

    stock_tickers = [
        'aapl', 'apple',
        'msft', 'microsoft',
        'tsla', 'tesla',
        'amzn', 'amazon',
        'googl', 'google'
    ]

    if any(ticker in title_lower for ticker in stock_tickers):
        price_indicators = ['finish week', 'close above', 'largest company']
        if any(indicator in title_lower for indicator in price_indicators):
            return True  # EXCLUDE stock price bets

    return False  # KEEP - this is a good market!


def test_crypto_filtering():
    """Test the crypto price filtering."""

    print("="*70)
    print("CRYPTO PRICE FILTERING TEST")
    print("="*70)

    # Markets that SHOULD BE EXCLUDED
    should_exclude = [
        # "Up or Down" crypto markets (always speculation)
        "Bitcoin Up or Down - November 14, 6:00PM-6:15PM ET",
        "BTC Up or Down - November 14, 6:00PM-6:15PM ET",
        "Ethereum Up or Down on November 15?",
        "ETH Up or Down on November 15?",
        "Solana Up or Down - November 14, 6PM ET",
        "SOL Up or Down - November 14, 6PM ET",
        "XRP Up or Down on November 15?",

        # "Dip to $" crypto price markets
        "Will Bitcoin dip to $94,000 November 10-16?",
        "Will BTC dip to $94,000 November 10-16?",
        "Will Ethereum dip to $2,600 in November?",
        "Will ETH dip to $2,600 in November?",
        "Will Solana dip to $130 November 10-16?",
        "Will SOL dip to $130 November 10-16?",

        # Other crypto price predictions
        "Will the price of Bitcoin be between $96,000 and $98,000",
        "Will Ethereum reach $10,000 by end of year?",
        "Will SOL hit $200 in November?",

        # Sports (from previous filter)
        "Penguins vs. Predators",
        "Thunder vs. Hornets",

        # Gaming/Entertainment
        "Will Death Stranding 2 win Game of the Year",
    ]

    # Markets that SHOULD BE KEPT
    should_keep = [
        # Geopolitics
        "Will Putin meet with Zelenskyy in 2025?",
        "China x Taiwan military clash by December 31?",
        "Will Israel strike 3 countries in November 2025?",
        "Russia x Ukraine ceasefire in 2025?",
        "Maduro out by November 30, 2025?",

        # Economics/Policy (NOT price predictions)
        "Fed decreases interest rates by 50+ bps",
        "Bank of Japan increases interest rates by 25 bps",
        "Will the ECB announce no change at the December meeting?",

        # Elections
        "Will Franco Parisi win the Chilean presidential election?",
        "Will Călin Georgescu be the next Mayor of Bucharest?",

        # Other geopolitics
        "Will there be a ceasefire in Gaza by March 2025?",
        "Evacuation of Tehran ordered in 2025?",
    ]

    print("\n🚫 TESTING CRYPTO/NOISE MARKETS THAT SHOULD BE EXCLUDED:")
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

    print("\n✅ TESTING VALUABLE MARKETS THAT SHOULD BE KEPT:")
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

    # Pattern breakdown
    print("\n" + "="*70)
    print("CRYPTO PATTERN DETECTION BREAKDOWN:")
    print("-"*70)

    pattern_counts = {
        '"Up or Down"': 0,
        '"Dip to $"': 0,
        'Crypto + Price Verb': 0,
        'Sports (vs.)': 0,
        'Gaming/Entertainment': 0,
    }

    for market in should_exclude:
        if 'up or down' in market.lower():
            pattern_counts['"Up or Down"'] += 1
        elif 'dip to $' in market.lower():
            pattern_counts['"Dip to $"'] += 1
        elif any(crypto in market.lower() for crypto in ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol']):
            if any(verb in market.lower() for verb in ['reach', 'hit', 'be between']):
                pattern_counts['Crypto + Price Verb'] += 1
        elif ' vs. ' in market:
            pattern_counts['Sports (vs.)'] += 1
        elif 'game of the year' in market.lower():
            pattern_counts['Gaming/Entertainment'] += 1

    for pattern, count in pattern_counts.items():
        if count > 0:
            print(f"  {pattern}: {count} markets")

    print("\n" + "="*70)

    # Impact analysis
    crypto_total = pattern_counts['"Up or Down"'] + pattern_counts['"Dip to $"'] + pattern_counts['Crypto + Price Verb']
    print("\n💡 IMPACT ANALYSIS:")
    print(f"  Crypto price markets: {crypto_total}/{total_exclude} ({crypto_total/total_exclude*100:.0f}%)")
    print(f"  Sports markets: {pattern_counts['Sports (vs.)']}/{total_exclude} ({pattern_counts['Sports (vs.)']/total_exclude*100:.0f}%)")
    print(f"  Other noise: {total_exclude - crypto_total - pattern_counts['Sports (vs.)']}/{total_exclude}")

    print("\n" + "="*70)

    # Return success
    if excluded_incorrectly == 0 and kept_incorrectly == 0:
        print("\n🎉 ALL TESTS PASSED! Crypto filter working perfectly.")
        print("\nThis filter will eliminate the 90% crypto noise while keeping")
        print("all valuable geopolitics, elections, and economics markets.")
        return True
    else:
        print(f"\n⚠️ {excluded_incorrectly + kept_incorrectly} errors detected. Review filter logic.")
        return False


if __name__ == "__main__":
    test_crypto_filtering()
