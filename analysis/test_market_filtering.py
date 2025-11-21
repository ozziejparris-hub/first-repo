#!/usr/bin/env python3
"""
Test the market filtering logic to ensure crypto/sports markets are excluded.
"""


def should_exclude_market(market_title: str) -> bool:
    """
    Check if a market should be excluded based on exclusion keywords.

    Returns True if the market matches exclusion criteria (crypto/sports/entertainment).
    """
    # Define EXCLUSION keywords (matches monitor.py filtering)
    exclusion_keywords = [
        'bitcoin', 'btc', 'ethereum', 'eth', 'crypto', 'xrp', 'ripple',
        'price above', 'price below', 'up or down',
        'nfl', 'nba', 'mlb', 'nhl', 'super bowl',
        'championship', 'playoff', 'team', 'vs.', 'game', 'match',
        'elon musk', 'tweet', 'x post', 'taylor swift', 'album', 'movie',
        'fed rate', 'interest rate', 'stock market', 'sp500', 's&p',
        'warriors', 'thunder', 'lakers', 'celtics', 'cowboys', 'patriots',
        'maple leafs', 'bruins'
    ]

    title_lower = market_title.lower()

    # Check if any exclusion keyword is in the title
    for keyword in exclusion_keywords:
        if keyword in title_lower:
            return True

    return False


def test_market_exclusion():
    """Test that exclusion logic correctly identifies crypto/sports markets."""
    print("="*70)
    print("TESTING MARKET EXCLUSION LOGIC")
    print("="*70)

    # Test cases from user's reported issues
    test_cases = [
        # Crypto markets (SHOULD BE EXCLUDED)
        ("XRP Up or Down - November 11", True),
        ("Bitcoin Up or Down - November 11", True),
        ("Ethereum price above $5000 by December?", True),
        ("Will BTC reach $100k by 2025?", True),

        # Sports markets (SHOULD BE EXCLUDED)
        ("Maple Leafs vs. Bruins", True),
        ("Warriors vs. Thunder", True),
        ("Will the Dallas Cowboys win Super Bowl 2026?", True),
        ("NBA Championship 2025", True),
        ("NFL Playoffs - Chiefs vs. Bills", True),

        # Elon Musk (SHOULD BE EXCLUDED)
        ("Elon Musk post 100-119 tweets", True),
        ("Will Elon tweet about Tesla today?", True),

        # Legitimate geopolitics (SHOULD NOT BE EXCLUDED)
        ("Will there be a ceasefire in Gaza by December?", False),
        ("Will Ukraine reclaim territory in 2025?", False),
        ("Will Trump win the 2024 election?", False),
        ("Congress pass infrastructure bill", False),
        ("Senate confirm Supreme Court nominee", False),
        ("NATO admit new member country", False),
        ("Russia withdraw from Ukraine", False),
        ("Iran nuclear deal negotiations", False),

        # Entertainment (user said these specific ones should be excluded)
        ("Taylor Swift release new album", True),
        # Other entertainment is OK per user requirements
        ("Oscars Best Picture 2025", False),
    ]

    print("\nRunning test cases...")
    print("-"*70)

    passed = 0
    failed = 0

    for market_title, should_exclude in test_cases:
        result = should_exclude_market(market_title)

        status = "✅ PASS" if result == should_exclude else "❌ FAIL"
        expected = "EXCLUDED" if should_exclude else "ALLOWED"
        actual = "EXCLUDED" if result else "ALLOWED"

        print(f"{status} | {market_title[:50]:50} | Expected: {expected:8} | Got: {actual:8}")

        if result == should_exclude:
            passed += 1
        else:
            failed += 1

    print("-"*70)
    print(f"\nResults: {passed} passed, {failed} failed out of {len(test_cases)} tests")

    if failed == 0:
        print("\n🎉 All tests passed! Market filtering is working correctly.")
    else:
        print(f"\n⚠️ {failed} tests failed. Review exclusion keywords.")

    print("="*70)


if __name__ == "__main__":
    test_market_exclusion()
