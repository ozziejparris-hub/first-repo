# Quick Fix Scripts

Utility scripts for common database maintenance and troubleshooting tasks.

## Available Scripts

### 1. Clean Orphaned Records

**Script:** `clean_orphaned_records.py`

**Purpose:** Remove trades and positions that reference non-existent traders

**When to use:**
- System Observer reports orphaned records warning
- After manual database modifications
- Database integrity check fails

**Usage:**
```bash
python scripts/quick_fixes/clean_orphaned_records.py
```

**What it does:**
- Finds trades without corresponding trader records
- Finds positions without corresponding trader records
- Deletes orphaned records
- Reports how many records were cleaned

**Safe to run:** Yes, only deletes invalid data

---

### 2. Vacuum Database

**Script:** `vacuum_database.py`

**Purpose:** Reclaim unused space and optimize database

**When to use:**
- Database size is growing excessively
- Query performance is slow
- After deleting many records
- Regular maintenance (monthly recommended)

**Usage:**
```bash
python scripts/quick_fixes/vacuum_database.py
```

**What it does:**
- Reclaims unused space from deleted records
- Defragments database file
- Updates query planner statistics (ANALYZE)
- Reports space saved

**Safe to run:** Yes, but takes a few minutes for large databases

**Note:** Close DB Browser or any other programs accessing the database first

---

### 3. Rebuild Indexes

**Script:** `rebuild_indexes.py`

**Purpose:** Recreate database indexes for better performance

**When to use:**
- Queries are running slowly
- After bulk data imports
- Database corruption suspected
- Regular maintenance (quarterly recommended)

**Usage:**
```bash
python scripts/quick_fixes/rebuild_indexes.py
```

**What it does:**
- Reindexes all database tables
- Refreshes query optimization statistics
- Reports progress for each table

**Safe to run:** Yes, improves performance

---

## Maintenance Schedule

### Weekly
- Monitor System Observer reports for issues

### Monthly
- Run `vacuum_database.py` to optimize storage

### Quarterly
- Run `rebuild_indexes.py` to optimize queries

### As Needed
- Run `clean_orphaned_records.py` if warnings appear

---

## Troubleshooting

### "Database is locked" Error

**Cause:** Another program is accessing the database

**Fix:**
1. Close DB Browser for SQLite
2. Stop monitoring system if running
3. Check for duplicate processes: `tasklist | findstr python`
4. Kill stuck processes: `taskkill /F /IM python.exe`

### Script Hangs

**Cause:** Large database operation in progress

**Fix:**
- Wait patiently (vacuum can take 5-10 minutes for large DBs)
- Check Task Manager to verify Python process is active
- Don't interrupt - may corrupt database

### No Space Saved

**Cause:** Database was already optimal

**Result:**
- This is normal if vacuum was run recently
- No action needed

---

## Advanced Usage

### Custom Database Path

All scripts accept custom database path:

```python
# In Python
from scripts.quick_fixes.vacuum_database import vacuum_database
vacuum_database('path/to/custom.db')
```

### Batch Maintenance

Create a batch file to run all maintenance tasks:

```batch
@echo off
echo Running database maintenance...
python scripts/quick_fixes/clean_orphaned_records.py
python scripts/quick_fixes/vacuum_database.py
python scripts/quick_fixes/rebuild_indexes.py
echo Maintenance complete!
pause
```

---

## Safety Notes

- **Always backup database before major operations**
- Scripts are read-only where possible
- Deletions only target invalid/orphaned data
- No trader, trade, or position data is modified (only removed if orphaned)
- System Observer will detect if maintenance is needed

---

## Integration with System Observer

System Observer automatically detects when these scripts are needed:

**Orphaned Records:**
```
⚠️ WARNING
[DATABASE] 1,234 trades reference non-existent traders

Fix: py scripts/quick_fixes/clean_orphaned_records.py
```

**Slow Queries:**
```
⚠️ WARNING
[PERFORMANCE] Slow database queries: 1,250ms avg

Fix: 1. Add indexes
     2. Vacuum database
     3. Consider WAL mode
```

**Large Database:**
```
⚠️ WARNING
[DATABASE] Database very large: 5,234 MB

Recommended: py scripts/quick_fixes/vacuum_database.py
```

Simply copy/paste the suggested command to fix the issue!
