"""Read-only: recompute Objective-1 intersection cohort (the metric_v2f_intersection_cohort
computation) against whatever DB is passed. No writes, no --persist. Prints the trader set
+ diffs vs the persisted snapshot. Used post-drain and again in the scratch-copy falsifiable test."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../../../../../../projects/first-repo")
sys.path.insert(0, "/home/parison/projects/first-repo")
from scripts.trader_skill_metric_v2 import db_connect
from scripts.trader_skill_metric_v2f import load_entries, full_population_cohort, EFFECT_BAR, M_CHOSEN

db = sys.argv[1] if len(sys.argv) > 1 else "data/polymarket_tracker.db"
out = sys.argv[2] if len(sys.argv) > 2 else None
conn = db_connect(db)
entries = load_entries(conn, verbose=False)
pairs, eb_full, sig95 = full_population_cohort(entries, conn, verbose=False)
inter = set(eb_full[(eb_full['trader'].isin(set(sig95['trader']))) & (eb_full['shrunk_mean'] >= EFFECT_BAR)]['trader'])
inter = sorted(inter)
persisted = sorted(r[0] for r in conn.execute("SELECT trader FROM metric_v2f_intersection_cohort"))
conn.close()
ps = set(persisted); rs = set(inter)
print(f"db={db}")
print(f"recomputed Objective-1 intersection cohort: n={len(inter)}")
print(f"persisted metric_v2f_intersection_cohort:    n={len(persisted)}")
print(f"entered (in recompute, not persisted): {len(rs-ps)}")
print(f"left    (in persisted, not recompute): {len(ps-rs)}")
print(f"stable (in both): {len(rs&ps)}")
if len(rs-ps) <= 40: print("  ENTERED:", sorted(rs-ps))
if len(ps-rs) <= 40: print("  LEFT:   ", sorted(ps-rs))
if out:
    json.dump({"db": db, "n_recomputed": len(inter), "recomputed": inter,
               "n_persisted": len(persisted), "entered": sorted(rs-ps), "left": sorted(ps-rs),
               "stable_n": len(rs&ps)}, open(out, "w"), indent=2)
    print(f"[json] {out}")
