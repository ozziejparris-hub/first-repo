#!/usr/bin/env python3
"""Quick script to analyze correlation for simulation traders only."""

import argparse
import sqlite3
import sys
import math
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _sim_db_guard import add_sim_db_args, resolve_sim_db

parser = argparse.ArgumentParser(description='Analyze correlation for simulation traders')
add_sim_db_args(parser)
args = parser.parse_args()

conn = sqlite3.connect(resolve_sim_db(args))
c = conn.cursor()

cutoff = (datetime.now() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

c.execute('''
    SELECT win_rate, comprehensive_elo
    FROM traders
    WHERE last_updated > ?
    AND comprehensive_elo IS NOT NULL
    AND total_trades > 0
    ORDER BY win_rate DESC
''', (cutoff,))

data = c.fetchall()
n = len(data)

# Calculate Pearson correlation
sum_wr = sum(wr for wr, _ in data)
sum_elo = sum(elo for _, elo in data)
sum_wr_elo = sum(wr * elo for wr, elo in data)
sum_wr2 = sum(wr * wr for wr, _ in data)
sum_elo2 = sum(elo * elo for _, elo in data)

numerator = n * sum_wr_elo - sum_wr * sum_elo
denominator = math.sqrt((n * sum_wr2 - sum_wr**2) * (n * sum_elo2 - sum_elo**2))
correlation = numerator / denominator if denominator > 0 else 0

print("=" * 70)
print("  SIMULATION TRADERS CORRELATION ANALYSIS")
print("=" * 70)
print()
print(f"Sample size: {n} traders")
print(f"Win Rate <-> ELO Correlation: r = {correlation:.3f}")
print()

if correlation > 0.7:
    print("[OK] Strong positive correlation - ELO accurately reflects skill!")
elif correlation > 0.5:
    print("[WARN] Moderate correlation - ELO somewhat reflects skill")
else:
    print("[FAIL] Weak correlation - ELO may not reflect skill accurately")

print()

# Analyze buckets
buckets = {
    'Elite (>60%)': [],
    'Good (50-60%)': [],
    'Average (45-50%)': [],
    'Poor (<45%)': []
}

for wr, elo in data:
    if wr > 0.60:
        buckets['Elite (>60%)'].append(elo)
    elif wr >= 0.50:
        buckets['Good (50-60%)'].append(elo)
    elif wr >= 0.45:
        buckets['Average (45-50%)'].append(elo)
    else:
        buckets['Poor (<45%)'].append(elo)

print("Average ELO by Win Rate Bucket:")
for bucket, elos in buckets.items():
    if elos:
        avg_elo = sum(elos) / len(elos)
        min_elo = min(elos)
        max_elo = max(elos)
        print(f"  {bucket:<20} {avg_elo:>8.1f}  (range: {min_elo:.1f}-{max_elo:.1f}, n={len(elos)})")

print()
print("=" * 70)

conn.close()
