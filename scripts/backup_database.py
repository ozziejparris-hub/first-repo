#!/usr/bin/env python3
"""Backup database before cleanup."""

import shutil
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
        return

    backup_dir = Path('backups')
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'markets_{timestamp}.db'

    print(f"[BACKUP] Copying {db_path} to {backup_path}...")
    shutil.copy2(db_path, backup_path)

    size_mb = backup_path.stat().st_size / 1024 / 1024
    print(f"[OK] Backup created: {backup_path}")
    print(f"     Size: {size_mb:.1f} MB")

if __name__ == '__main__':
    main()
