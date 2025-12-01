#!/usr/bin/env python3
"""
Test Market Filtering Script

Tests the enhanced market filtering to ensure entertainment, sports, crypto airdrops,
and gold price predictions are being filtered out while keeping geopolitics/economics.
"""

import sys
import os
import re

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test markets - should be EXCLUDED
SHOULD_EXCLUDE = [
    # Entertainment - Awards
    "Will Chloé Zhao win Best Director at the 98th Academy Awards?",
    "Will Dune: Part Three win Best Picture at the 98th Academy Awards?",
    "Will someone win an Oscar for a role in The Brutalist?",
    "Parasite: Best Picture at the 2020 Oscars?",
    "Will Taylor Swift win Album of the Year at the 2026 Grammys?",

    # Entertainment - Music/Streaming
    "Will Ordinary by Alex Warren be the most streamed album?",
    "Will Sabrina Carpenter's 'Short n' Sweet' be the most streamed album on Spotify in 2024?",
    "Will Kai Cenat be the Streamer of the Year?",

    # Sports - Touchdowns
    "Jaylen Warren: Anytime Touchdown",
    "Will Patrick Mahomes score the first touchdown?",

    # Sports - Leagues/Championships
    "Will the Lakers make the playoffs in 2025?",
    "Manchester United to win the Premier League?",
    "Super Bowl 2026: Chiefs vs. Bills?",

    # Crypto Airdrops
    "Lighter market cap (FDV) >$2B one day after launch?",
    "Will the token airdrop have FDV above $1B?",
    "Market cap > $500M day after launch?",

    # Gold Price Predictions
    "Will Gold close between $3500 and $3600 at the end of December?",
    "Gold price above $4000 in 2025?",
    "Will gold hit $3800 by February?",
]

# Test markets - should be KEPT (not excluded)
SHOULD_KEEP = [
    # Geopolitics
    "Will Trump win the 2024 presidential election?",
    "Will Russia invade Ukraine in 2025?",
    "Will there be a ceasefire in Gaza by March 2025?",
    "Will Netanyahu remain Prime Minister through 2025?",

    # Economics & Policy
    "TikTok sale announced in 2025?",
    "Will Larry Ellison/Oracle acquire TikTok?",
    "Enhanced ACA premium tax credits extended in 2025?",
    "Will the 10-year Treasury yield hit 4.6% in 2025?",
    "Will US GDP growth in Q4 2025 be greater than 3.5%?",
    "Will the Federal Reserve cut interest rates in Q1 2025?",

    # Tech Policy
    "Will the US ban TikTok in 2025?",
    "Will Congress pass AI regulation by end of 2025?",
]


def test_keyword_exclusion(market_title: str) -> tuple[bool, str]:
    """
    Simulate the _keyword_exclusion_check logic from monitor.py.
    Returns (should_exclude, reason)
    """
    # Define EXCLUSION keywords - same as monitor.py
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

        # SPORTS BETTING
        'spread:', 'o/u ', 'over/under', 'moneyline',
        'touchdown', 'anytime touchdown', 'first touchdown',

        # SPORTS LEAGUES & CHAMPIONSHIPS
        'nfl', 'nba', 'mlb', 'nhl', 'mls',
        'premier league', 'champions league',
        'super bowl', 'world series', 'stanley cup',
        'win the championship', 'make the playoffs',

        # ENTERTAINMENT - AWARDS & NOMINATIONS
        'academy award', 'oscar', 'oscars', 'grammy', 'grammys',
        'emmy', 'emmys', 'tony awards', 'golden globe', 'bafta',
        'cannes', 'sundance',
        'nominated for best', 'win best actor', 'win best actress',
        'win best director', 'win best picture', 'win best film',
        'best supporting actor', 'best supporting actress',
        'best documentary', 'best animated', 'best song',
        'best film editing',

        # ENTERTAINMENT - MUSIC
        'songwriter of the year', 'album of the year', 'record of the year',
        'most streamed', 'streamed on spotify', 'spotify',

        # ENTERTAINMENT - MEDIA & STREAMING
        'movie', 'film', 'documentary', 'box office', 'opening weekend',
        'streamer of the year', 'twitch', 'kai cenat',
    ]

    title_lower = market_title.lower()

    # Check keyword matches
    for keyword in exclusion_keywords:
        if keyword in title_lower:
            return (True, f"keyword: '{keyword}'")

    # Check regex patterns
    if re.search(r'gold.*\$\d+.*and.*\$\d+', title_lower):
        return (True, "pattern: gold price range")

    if re.search(r'spread:.*\(-?\d+\.?\d*\)', title_lower):
        return (True, "pattern: sports spread betting")

    return (False, "no match")


def run_tests():
    """Run all test cases and report results."""
    print("="*80)
    print("MARKET FILTERING TEST SUITE")
    print("="*80 + "\n")

    # Test exclusions
    print("Testing markets that SHOULD BE EXCLUDED:")
    print("-"*80)

    exclude_passed = 0
    exclude_failed = 0

    for market in SHOULD_EXCLUDE:
        should_exclude, reason = test_keyword_exclusion(market)

        if should_exclude:
            print(f"[PASS] Excluded: {market[:60]}...")
            print(f"   Reason: {reason}\n")
            exclude_passed += 1
        else:
            print(f"[FAIL] NOT excluded: {market}")
            print(f"   This market should have been filtered!\n")
            exclude_failed += 1

    # Test inclusions
    print("\n" + "="*80)
    print("Testing markets that SHOULD BE KEPT (not excluded):")
    print("-"*80)

    keep_passed = 0
    keep_failed = 0

    for market in SHOULD_KEEP:
        should_exclude, reason = test_keyword_exclusion(market)

        if not should_exclude:
            print(f"[PASS] Kept: {market[:60]}...")
            keep_passed += 1
        else:
            print(f"[FAIL] Incorrectly excluded: {market}")
            print(f"   Reason: {reason}")
            print(f"   This geopolitics/economics market should NOT be filtered!\n")
            keep_failed += 1

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Exclusion Tests: {exclude_passed}/{len(SHOULD_EXCLUDE)} passed")
    print(f"Inclusion Tests: {keep_passed}/{len(SHOULD_KEEP)} passed")
    print(f"\nTotal: {exclude_passed + keep_passed}/{len(SHOULD_EXCLUDE) + len(SHOULD_KEEP)} tests passed")

    if exclude_failed > 0 or keep_failed > 0:
        print(f"\n[WARNING] {exclude_failed + keep_failed} test(s) failed!")
        return False
    else:
        print("\n[SUCCESS] All tests passed!")
        return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
