#!/usr/bin/env python3
"""
Test crypto market INCLUSION filtering (inverted logic).

The crypto tracker INCLUDES only crypto markets and EXCLUDES everything else.
This is the opposite of the geopolitics tracker.
"""

import re


def should_include_market(market_title: str) -> bool:
    """
    Test version matching monitor.py _should_include_market() logic.
    Returns True if market should be INCLUDED (kept for tracking).
    """
    title = market_title
    title_lower = market_title.lower()

    # List of crypto names (both full names AND tickers)
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
        'chainlink', 'link',
        'polkadot', 'dot',
        'shiba', 'shib',
        'litecoin', 'ltc',
        'uniswap', 'uni',
        'pepe'
    ]

    # ===== PATTERN 1: "UP OR DOWN" - HIGHEST PRIORITY =====
    if "up or down" in title_lower:
        return True  # INCLUDE

    # ===== PATTERN 2: "DIP TO $" =====
    if "dip to $" in title_lower:
        return True  # INCLUDE

    # ===== PATTERN 3: "PRICE OF [CRYPTO]" =====
    if "price of" in title_lower:
        price_indicators = [
            'be above $', 'be less than $', 'be below $', 'be between $',
            'above $', 'less than $', 'below $', 'reach $', 'hit $'
        ]

        has_crypto = any(crypto in title_lower for crypto in crypto_names)
        has_price_indicator = any(indicator in title_lower for indicator in price_indicators)

        if has_crypto and has_price_indicator:
            return True  # INCLUDE

    # ===== PATTERN 4: CRYPTO + PRICE PREDICTION VERBS =====
    price_verbs = [
        'reach $', 'hit $', 'close above', 'close between', 'close below',
        'finish week', 'all time high', 'ath ', 'new high', 'new low',
        'trade above', 'trade below', 'be between $', 'be above $', 'be below $'
    ]

    has_crypto = any(crypto in title_lower for crypto in crypto_names)
    has_price_verb = any(verb in title_lower for verb in price_verbs)

    if has_crypto and has_price_verb:
        return True  # INCLUDE

    # ===== DEFAULT: EXCLUDE =====
    return False


def test_crypto_inclusion():
    """Test the crypto inclusion filtering (inverted logic)."""

    print("=" * 70)
    print("CRYPTO TRACKER - INCLUSION FILTERING TEST")
    print("=" * 70)

    # Markets that SHOULD BE INCLUDED (crypto markets)
    should_include = [
        # "Up or Down" crypto markets - HIGHEST PRIORITY
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

        # "Price of [crypto]" patterns
        "Will the price of Bitcoin be above $96,000 on November 17?",
        "Will the price of Ethereum be less than $3,000 on November 16?",
        "Will the price of XRP be above $2.20 on November 21?",
        "Will the price of Solana be above $140 on November 20?",

        # Other crypto price predictions
        "Will Bitcoin reach $100,000 by December 2025?",
        "Will Ethereum hit $5,000 by end of year?",
        "Will SOL hit $200 in November?",
        "Will XRP close above $1.50 on November 20?",
        "Will BTC all time high by December 31?",
        "Will Ethereum finish week above $3,200?",

        # Altcoins
        "Will Cardano (ADA) reach $1 in November?",
        "Will Polygon (MATIC) hit $2 by December?",
        "Will Avalanche close above $50?",
        "Will Dogecoin reach $0.50 in 2025?",
        "Will Chainlink be above $30?",
    ]

    # Markets that SHOULD BE EXCLUDED (non-crypto)
    should_exclude = [
        # Geopolitics (should be excluded from crypto tracker)
        "Will José Antonio Kast win the Chilean presidential election?",
        "Will Evelyn Matthei win the Chilean presidential election?",
        "Will Israel strike Gaza on November 16?",
        "Will Russia capture Pokrovsk by November 30?",
        "US x Venezuela military engagement by December 31?",
        "Will Trump talk to Volodymyr Zelenskyy in November?",
        "Will Putin meet with Zelenskyy in 2025?",

        # Economics/Policy
        "Fed decreases interest rates by 25 bps",
        "Will the EU impose new tariffs on US goods in 2025?",
        "Will the ECB announce no change at the December meeting?",
        "Bank of Japan increases interest rates by 25 bps",

        # Sports
        "Warriors vs. Pelicans",
        "Lakers vs. Celtics",
        "Penguins vs. Predators",
        "Thunder vs. Hornets",
        "Will the Cowboys win the NFC East?",

        # Entertainment
        "Will Bad Bunny be the top Spotify artist for 2025?",
        "Will The Weeknd be the most streamed Spotify artist?",
        "Will Miss Universe be from Canada?",
        "Will 'The Running Man' Opening Weekend Box Office be above $50M?",
        "Will Bayern Munich win the 2025–26 Champions League?",
    ]

    print("\n🪙 TESTING CRYPTO MARKETS THAT SHOULD BE INCLUDED:")
    print("-" * 70)

    included_correctly = 0
    included_incorrectly = 0

    for market in should_include:
        result = should_include_market(market)
        status = "✅ INCLUDED" if result else "❌ EXCLUDED (ERROR)"

        if result:
            included_correctly += 1
        else:
            included_incorrectly += 1

        print(f"{status}: {market}")

    print("\n🚫 TESTING NON-CRYPTO MARKETS THAT SHOULD BE EXCLUDED:")
    print("-" * 70)

    excluded_correctly = 0
    excluded_incorrectly = 0

    for market in should_exclude:
        result = should_include_market(market)
        status = "✅ EXCLUDED" if not result else "❌ INCLUDED (ERROR)"

        if not result:
            excluded_correctly += 1
        else:
            excluded_incorrectly += 1

        print(f"{status}: {market}")

    # Summary
    print("\n" + "=" * 70)
    print("FILTERING SUMMARY:")
    print("-" * 70)

    total_include = len(should_include)
    total_exclude = len(should_exclude)
    total_markets = total_include + total_exclude

    print(f"Crypto markets that should be INCLUDED: {total_include}")
    print(f"  ✅ Correctly included: {included_correctly}")
    print(f"  ❌ Incorrectly excluded: {included_incorrectly}")
    print(f"  Accuracy: {included_correctly / total_include * 100:.1f}%")

    print(f"\nNon-crypto markets that should be EXCLUDED: {total_exclude}")
    print(f"  ✅ Correctly excluded: {excluded_correctly}")
    print(f"  ❌ Incorrectly included: {excluded_incorrectly}")
    print(f"  Accuracy: {excluded_correctly / total_exclude * 100:.1f}%")

    print(f"\nOVERALL ACCURACY: {(included_correctly + excluded_correctly) / total_markets * 100:.1f}%")
    print(f"Total markets tested: {total_markets}")

    # Pattern breakdown
    print("\n" + "=" * 70)
    print("CRYPTO PATTERN DETECTION:")
    print("-" * 70)

    up_or_down_count = sum(1 for m in should_include if 'up or down' in m.lower())
    dip_to_count = sum(1 for m in should_include if 'dip to $' in m.lower())
    price_of_count = sum(1 for m in should_include if 'price of' in m.lower())
    other_crypto_count = total_include - up_or_down_count - dip_to_count - price_of_count

    print(f"  'Up or Down' markets: {up_or_down_count}/{total_include} ({up_or_down_count / total_include * 100:.1f}%)")
    print(f"  'Dip to $' markets: {dip_to_count}/{total_include} ({dip_to_count / total_include * 100:.1f}%)")
    print(f"  'Price of' markets: {price_of_count}/{total_include} ({price_of_count / total_include * 100:.1f}%)")
    print(f"  Other crypto price predictions: {other_crypto_count}/{total_include} ({other_crypto_count / total_include * 100:.1f}%)")

    print("\n" + "=" * 70)

    if included_incorrectly == 0 and excluded_incorrectly == 0:
        print("\n🎉 ALL TESTS PASSED! Crypto inclusion filtering works perfectly.")
        print("\nThe crypto tracker will ONLY track crypto markets and ignore everything else.")
        print("This is the opposite of the geopolitics tracker.")
        return True
    else:
        print(f"\n⚠️ {included_incorrectly + excluded_incorrectly} errors detected.")
        return False


if __name__ == "__main__":
    test_crypto_inclusion()
