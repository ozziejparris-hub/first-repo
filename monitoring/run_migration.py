"""
Run database migration to add api_id column.

This is a one-time migration script.
Safe to run multiple times (idempotent).
"""

from database import Database


def main():
    print("\n" + "="*70)
    print("DATABASE MIGRATION: Add api_id Column")
    print("="*70 + "\n")

    db = Database("data/polymarket_tracker.db")

    print("Running migration...")
    db.migrate_add_api_id_column()

    print("\n[OK] Migration complete!")
    print("\nNext steps:")
    print("1. Run: python monitoring/backfill_market_ids.py --test --limit 10")
    print("2. If test looks good, run: python monitoring/backfill_market_ids.py")
    print("3. Run: python monitoring/check_market_resolutions.py --check")
    print()


if __name__ == "__main__":
    main()
