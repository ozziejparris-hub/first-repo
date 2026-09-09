"""Falsifiable test — revert the manifest's trade_ids to 'pending' in the SCRATCH DB only.
Asserts scratch path is not production. Read production only to load the manifest."""
import sqlite3, json, sys
SCRATCHDB = sys.argv[1]
MANIFEST  = sys.argv[2]
assert SCRATCHDB != "data/polymarket_tracker.db" and "scratch" in SCRATCHDB, f"refuse: {SCRATCHDB}"
m = json.load(open(MANIFEST))
tids = [r["trade_id"] for r in m["manifest"]]
assert len(tids) == len(set(tids)) == 24390, f"manifest trade_id count {len(tids)}/{len(set(tids))}"
c = sqlite3.connect(SCRATCHDB)
c.execute("PRAGMA busy_timeout=30000")
# how many are currently NOT pending in scratch (should be all 24390, drained)
before = c.execute(f"SELECT COUNT(*) FROM trades WHERE trade_id IN ({','.join('?'*len(tids))}) AND trade_result='pending'", tids).fetchone()[0]
cur = c.cursor()
n = 0
for i in range(0, len(tids), 1000):
    chunk = tids[i:i+1000]
    cur.executemany("UPDATE trades SET trade_result='pending' WHERE trade_id=?", [(t,) for t in chunk])
    n += cur.rowcount if cur.rowcount and cur.rowcount>0 else len(chunk)
c.commit()
after = c.execute(f"SELECT COUNT(*) FROM trades WHERE trade_id IN ({','.join('?'*len(tids))}) AND trade_result='pending'", tids).fetchone()[0]
# scratch check_pending_geo
cpg = c.execute("""SELECT COUNT(*) FROM trades tr JOIN markets m ON m.market_id=tr.market_id
  WHERE tr.trade_result='pending' AND m.resolved=1 AND (m.trade_gap_flag=0 OR m.trade_gap_flag IS NULL)
  AND m.category IN ('Geopolitics','Elections')""").fetchone()[0]
c.close()
print(f"manifest trade_ids: {len(tids)}")
print(f"already-pending in scratch before revert: {before}")
print(f"pending among manifest ids AFTER revert: {after}  (expect 24390)")
print(f"scratch check_pending_geo after revert: {cpg}  (pre-drain baseline was 24390)")
