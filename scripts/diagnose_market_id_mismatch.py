#!/usr/bin/env python3
"""
Diagnose why trades aren't matching with resolved markets.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.database import Database


def diagnose_market_id_mismatch():
    """Diagnose the market ID mismatch issue."""
    print("="*70)
    print("MARKET ID MISMATCH DIAGNOSTIC")
    print("="*70)

    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()

    # Check trades table
    print("\n[1] TRADES TABLE - market_id format:")
    print("-"*70)
    cursor.execute("SELECT market_id, market_title FROM trades LIMIT 10")
    trade_samples = cursor.fetchall()

    if trade_samples:
        for market_id, title in trade_samples[:3]:
            try:
                safe_title = title[:60].encode('ascii', 'replace').decode('ascii')
            except:
                safe_title = "TITLE WITH SPECIAL CHARS"
            print(f"  ID: {market_id}")
            print(f"  Title: {safe_title}")
            print(f"  Length: {len(market_id)}")
            print(f"  Format: {'HEX (0x...)' if market_id.startswith('0x') else 'OTHER'}")
            print()
    else:
        print("  No trades found!")

    # Check markets table
    print("[2] MARKETS TABLE - market_id format:")
    print("-"*70)
    cursor.execute("SELECT market_id, title FROM markets WHERE resolved = 1 LIMIT 10")
    market_samples = cursor.fetchall()

    if market_samples:
        for market_id, title in market_samples[:3]:
            try:
                safe_title = title[:60].encode('ascii', 'replace').decode('ascii')
            except:
                safe_title = "TITLE WITH SPECIAL CHARS"
            print(f"  ID: {market_id}")
            print(f"  Title: {safe_title}")
            print(f"  Length: {len(str(market_id))}")
            print(f"  Format: {'HEX (0x...)' if str(market_id).startswith('0x') else 'NUMERIC or OTHER'}")
            print()
    else:
        print("  No resolved markets found!")

    # Check if conditionId or condition_id exists in markets
    print("[3] MARKETS TABLE - Available ID fields:")
    print("-"*70)
    cursor.execute("PRAGMA table_info(markets)")
    columns = cursor.fetchall()
    id_fields = [col[1] for col in columns if 'id' in col[1].lower()]
    print(f"  ID-related columns: {id_fields}")

    # If condition_id exists, check its format
    if 'condition_id' in id_fields or 'conditionId' in id_fields:
        field = 'condition_id' if 'condition_id' in id_fields else 'conditionId'
        print(f"\n  Checking {field} format:")
        cursor.execute(f"SELECT {field}, title FROM markets WHERE resolved = 1 AND {field} IS NOT NULL LIMIT 3")
        condition_samples = cursor.fetchall()
        for cond_id, title in condition_samples:
            try:
                safe_title = title[:60].encode('ascii', 'replace').decode('ascii')
            except:
                safe_title = "TITLE WITH SPECIAL CHARS"
            print(f"    {field}: {cond_id}")
            print(f"    Title: {safe_title}")
            print()

    # Check for matching
    print("[4] MATCHING TEST:")
    print("-"*70)

    if trade_samples and market_samples:
        # Get one trade market_id
        test_trade_id = trade_samples[0][0]
        print(f"  Testing with trade market_id: {test_trade_id[:50]}...")

        # Try to find in markets by market_id
        cursor.execute("SELECT COUNT(*) FROM markets WHERE market_id = ? AND resolved = 1", (test_trade_id,))
        match_market_id = cursor.fetchone()[0]
        print(f"  Matches in markets.market_id: {match_market_id}")

        # Try condition_id if it exists
        if 'condition_id' in id_fields:
            cursor.execute("SELECT COUNT(*) FROM markets WHERE condition_id = ? AND resolved = 1", (test_trade_id,))
            match_condition_id = cursor.fetchone()[0]
            print(f"  Matches in markets.condition_id: {match_condition_id}")

        # Try api_id conversion (conditionId -> id)
        cursor.execute("SELECT api_id, market_id, condition_id FROM markets WHERE resolved = 1 LIMIT 1")
        sample_market = cursor.fetchone()
        if sample_market:
            print(f"\n  Sample market structure:")
            print(f"    api_id: {sample_market[0]}")
            print(f"    market_id: {sample_market[1]}")
            if len(sample_market) > 2:
                print(f"    condition_id: {sample_market[2]}")

    # Summary
    print("\n" + "="*70)
    print("DIAGNOSIS SUMMARY")
    print("="*70)

    cursor.execute("SELECT COUNT(DISTINCT market_id) FROM trades")
    unique_trade_markets = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM markets WHERE resolved = 1")
    resolved_markets = cursor.fetchone()[0]

    print(f"Unique markets in trades: {unique_trade_markets}")
    print(f"Resolved markets: {resolved_markets}")

    if trade_samples and market_samples:
        trade_format = "HEX" if trade_samples[0][0].startswith('0x') else "OTHER"
        market_format = "HEX" if str(market_samples[0][0]).startswith('0x') else "NUMERIC/OTHER"

        print(f"\nFormat mismatch detected:")
        print(f"  trades.market_id: {trade_format}")
        print(f"  markets.market_id: {market_format}")

        if trade_format != market_format:
            print("\n[ISSUE] Format mismatch - IDs cannot be directly matched!")
            print("\n[SOLUTION] Need to:")
            if 'condition_id' in id_fields:
                print("  1. Update get_trades_for_market() to match on condition_id")
                print("  2. Update trade_evaluator to use condition_id from markets")
            else:
                print("  1. Add condition_id column to markets table")
                print("  2. Populate it from conditionId field")
                print("  3. Update get_trades_for_market() to match on condition_id")

    conn.close()


if __name__ == "__main__":
    diagnose_market_id_mismatch()
