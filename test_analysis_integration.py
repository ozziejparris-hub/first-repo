"""
Test script for analysis scheduler integration.

Tests analysis execution and Telegram report formatting.
"""

import asyncio
import sys
import os

# Add monitoring module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitoring.system_observer import SystemObserver


async def test_data_sufficiency():
    """Test data sufficiency check only (no analysis run)."""

    print("="*70)
    print("  DATA SUFFICIENCY CHECK (No Analysis Run)")
    print("="*70)
    print()

    # Import scheduler
    from analysis.analysis_scheduler import AnalysisScheduler

    scheduler = AnalysisScheduler(
        db_path='data/polymarket_tracker.db',
        send_alerts=False
    )

    # Check data sufficiency
    print("Checking if system has sufficient data for analysis...")
    sufficiency = scheduler.check_data_sufficiency()

    print("\n[RESULTS]")
    print(f"  Data sufficient: {sufficiency.get('sufficient', False)}")
    print(f"  Resolved markets: {sufficiency.get('resolved_markets', 0)}")
    print(f"  Active traders: {sufficiency.get('active_traders', 0)}")
    print(f"  Total trades: {sufficiency.get('total_trades', 0)}")
    print(f"  Shared markets: {sufficiency.get('shared_markets', 0)}")

    if sufficiency.get('sufficient'):
        print("\n[OK] System ready for analysis")
    else:
        print("\n[WARNING] Insufficient data")
        if sufficiency.get('missing_requirements'):
            print("\n[MISSING REQUIREMENTS]")
            for req in sufficiency['missing_requirements']:
                print(f"  • {req}")

        if sufficiency.get('recommendations'):
            print("\n[RECOMMENDATIONS]")
            for rec in sufficiency['recommendations']:
                print(f"  • {rec}")

    print("\n" + "="*70)


async def test_run_analysis():
    """Test running analysis (no Telegram send)."""

    print("="*70)
    print("  RUN ANALYSIS (No Telegram)")
    print("="*70)
    print()

    # Get credentials from environment or use dummy values for testing
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN', 'dummy_token_for_testing')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '0')

    observer = SystemObserver(telegram_token, chat_id)

    print("Running comprehensive analysis...")
    print("This may take 5-10 minutes...")
    print()

    results = await observer._run_analysis_scheduler()

    print("\n[RESULTS]")
    print(f"  Success: {results['success']}")
    print(f"  Data sufficient: {results['data_sufficient']}")

    if results['success']:
        print(f"  Reports generated: {len(results['reports_generated'])}")
        if results['reports_generated']:
            print("\n[REPORTS]")
            for report in results['reports_generated']:
                print(f"    • {report}")

        if results.get('summary'):
            print(f"\n[SUMMARY] (first 500 chars)")
            print(results['summary'][:500])
            print("...")
    else:
        print(f"  Error: {results.get('error', 'Unknown')}")

    print("\n" + "="*70)


async def test_full_integration():
    """Test full integration with Telegram send."""

    print("="*70)
    print("  FULL TEST (With Telegram)")
    print("="*70)
    print()

    # Get credentials from environment
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not telegram_token or not chat_id:
        print("[ERROR] Missing Telegram credentials")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
        return False

    print("[1/2] Initializing System Observer...")
    observer = SystemObserver(telegram_token, chat_id)
    print("[OK] System Observer initialized")
    print()

    print("[2/2] Running analysis and sending to Telegram...")
    print("This may take 5-10 minutes...")
    results = await observer._run_analysis_scheduler()

    if results['success']:
        print("\n[OK] Analysis complete!")
        print("\nSending summary to Telegram...")
        success = await observer.telegram.send_analysis_summary(results)

        if success:
            print("[OK] Analysis summary sent!")
            print()
            print("="*70)
            print("Check your Telegram bot for the analysis summary message")
            print("="*70)
            return True
        else:
            print("[ERROR] Failed to send to Telegram")
            return False
    else:
        print(f"\n[ERROR] Analysis failed: {results.get('error')}")
        return False


def main():
    """Main entry point."""

    import argparse

    parser = argparse.ArgumentParser(description='Test analysis scheduler integration')
    parser.add_argument('--mode', choices=['check-only', 'run-analysis', 'full'],
                       default='check-only',
                       help='Test mode: check-only, run-analysis, or full')

    args = parser.parse_args()

    try:
        if args.mode == 'check-only':
            print("\nRunning DATA SUFFICIENCY CHECK...\n")
            asyncio.run(test_data_sufficiency())
            sys.exit(0)

        elif args.mode == 'run-analysis':
            print("\nRunning ANALYSIS (no Telegram)...\n")
            asyncio.run(test_run_analysis())
            sys.exit(0)

        elif args.mode == 'full':
            print("\nRunning FULL TEST (with Telegram)...\n")
            result = asyncio.run(test_full_integration())
            sys.exit(0 if result else 1)

    except KeyboardInterrupt:
        print("\n\n[ERROR] Test interrupted by user")
        sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
