
import os, time, sqlite3

log = 'logs/monitoring.log'
age_min = (time.time() - os.path.getmtime(log)) / 60
print(f'Log last written: {age_min:.1f} minutes ago')
print('STATUS:', 'OK' if age_min < 20 else 'POSSIBLY STUCK')

conn = sqlite3.connect('data/polymarket_tracker.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM traders WHERE comprehensive_elo IS NOT NULL')
print(f'Traders with ELO: {cur.fetchone()[0]:,}')
cur.execute("SELECT COUNT(*) FROM positions WHERE status='closed'")
print(f'Closed positions: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM trader_stats WHERE total_roi_pct IS NOT NULL")
print(f'P&L coverage: {cur.fetchone()[0]:,}')
conn.close()


