#!/bin/bash
# Runs at 03:00 UTC Sunday — before daily_maintenance wakes at 06:00
# Gives ELO recalc 3 hours to finish before monitoring peak activity
cd /home/parison/projects/first-repo
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting Sunday ELO recalculation" >> logs/sunday_elo.log
python3 scripts/recalculate_comprehensive_elo.py \
  --skip-correlation --skip-contrarian --skip-advanced-metrics \
  >> logs/sunday_elo.log 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Sunday ELO recalculation complete" >> logs/sunday_elo.log
