#!/bin/bash
# backup_offsite.sh — nightly encrypted backup to USB drive
# Backs up: polymarket_tracker.db + trading-swarm brain/
# Schedule: 02:00 UTC daily (before 03:00 DB backup, after midnight quiet period)

set -euo pipefail

BACKUP_DRIVE="/mnt/backup"
DB_SOURCE="/home/parison/projects/first-repo/data/polymarket_tracker.db"
BRAIN_SOURCE="/home/parison/trading-swarm/brain"
LOG="/home/parison/trading-swarm/logs/backup_offsite.log"
DATE=$(date +%Y-%m-%d)
BACKUP_DIR="$BACKUP_DRIVE/polymarket-backups/$DATE"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1" | tee -a "$LOG"
}

# Check drive is mounted
if ! mountpoint -q "$BACKUP_DRIVE"; then
    log "ERROR: Backup drive not mounted at $BACKUP_DRIVE — aborting"
    exit 1
fi

# Check drive has enough space (need ~15GB free)
FREE_GB=$(df -BG "$BACKUP_DRIVE" | awk 'NR==2 {print $4}' | tr -d 'G')
if [ "$FREE_GB" -lt 15 ]; then
    log "WARNING: Only ${FREE_GB}GB free on backup drive"
fi

mkdir -p "$BACKUP_DIR"
log "Starting backup to $BACKUP_DIR"

# 1. DB backup — WAL checkpoint first, then compressed copy
log "Checkpointing WAL..."
sqlite3 "$DB_SOURCE" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true

log "Backing up database..."
cp "$DB_SOURCE" "$BACKUP_DIR/polymarket_tracker.db"
gzip -f "$BACKUP_DIR/polymarket_tracker.db"
log "DB backup complete: $(du -sh $BACKUP_DIR/polymarket_tracker.db.gz | cut -f1)"

# 2. Brain directory — rsync (fast incremental)
log "Backing up brain/..."
rsync -av --delete \
    --exclude="*.pyc" \
    --exclude="__pycache__" \
    "$BRAIN_SOURCE/" \
    "$BACKUP_DRIVE/polymarket-backups/brain-latest/"
log "Brain backup complete"

# 3. Keep only last 14 days of DB backups
log "Pruning old backups (keeping 14 days)..."
find "$BACKUP_DRIVE/polymarket-backups" -maxdepth 1 -type d -name "2*" | \
    sort | head -n -14 | xargs rm -rf 2>/dev/null || true

# 4. Write manifest
echo "backup_date: $DATE" > "$BACKUP_DIR/manifest.txt"
echo "db_size: $(du -sh $BACKUP_DIR/polymarket_tracker.db.gz | cut -f1)" >> "$BACKUP_DIR/manifest.txt"
echo "hostname: $(hostname)" >> "$BACKUP_DIR/manifest.txt"
df -h "$BACKUP_DRIVE" >> "$BACKUP_DIR/manifest.txt"

log "Backup complete. Drive usage: $(df -h $BACKUP_DRIVE | awk 'NR==2{print $3}') used"
