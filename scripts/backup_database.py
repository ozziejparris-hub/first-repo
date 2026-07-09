#!/usr/bin/env python3
"""Backup database before cleanup."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

def main():
    # Try multiple possible database locations
    possible_paths = [
        Path('monitoring/data/markets.db'),
        Path('data/polymarket_tracker.db'),
        Path('polymarket_tracker.db')
    ]

    db_path = None
    for path in possible_paths:
        if path.exists():
            db_path = path
            break

    if not db_path:
        print(f"[ERROR] Database not found in any of: {[str(p) for p in possible_paths]}")
        return 1

    backup_dir = Path('backups')
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'markets_{timestamp}.db'

    # Online backup API: safe against a live WAL-mode writer, unlike a raw
    # file copy which can capture a torn/inconsistent snapshot mid-write.
    print(f"[BACKUP] Running online backup of {db_path} to {backup_path}...")
    source_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(backup_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    print(f"[BACKUP] Verifying integrity of {backup_path}...")
    check_conn = sqlite3.connect(str(backup_path))
    try:
        result = check_conn.execute("PRAGMA integrity_check;").fetchone()[0]
    except sqlite3.DatabaseError as e:
        # A severely corrupt file (e.g. truncated) fails to even run the
        # check, raising here instead of returning a non-'ok' row.
        result = str(e)
    finally:
        check_conn.close()

    if result != 'ok':
        print(f"[ERROR] Backup failed integrity check: {backup_path}")
        print(f"        {result}")
        backup_path.unlink()
        return 1

    size_mb = backup_path.stat().st_size / 1024 / 1024
    print(f"[OK] Backup created: {backup_path}")
    print(f"     Size: {size_mb:.1f} MB")
    return 0

if __name__ == '__main__':
    sys.exit(main())
