#!/bin/bash
cd /home/parison/projects/first-repo
python3 -c "
import sys
sys.path.insert(0, '.')
from scripts.fast_resolution_check import FastResolutionChecker
checker = FastResolutionChecker('data/polymarket_tracker.db')
total = 0
for _ in range(7):  # 7 x 300 = 2100 markets max
    count = checker.run_stale_clob_pass(stale_limit=300, test_mode=False)
    total += count
    if count < 20:
        break
checker.run_recent_overdue_pass(limit=200, test_mode=False)
print(f'Weekly sweep complete: {total} resolved')
" >> /home/parison/trading-swarm/logs/weekly_resolution_sweep.log 2>&1
