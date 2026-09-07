#!/usr/bin/env python3
"""
Characterize the last_checked/requeue-gate stranding defect, first quantified
narratively in trading-swarm's brain/decisions/2026-08-30-canonical-writer-column-gap.md
(commit 96be474: 195,625 of 214,413 clob-resolved markets stranded, 8,077 open
positions across 1,983 distinct traders) and brain/decisions/2026-08-30-end-to-end-
verification.md (commit 9041ab8: the earlier 4,991/594 reading the same day).

Neither of those figures was produced by a committed script or backed by a
persisted market/trader ID list -- both were ad-hoc queries quoted narratively
into a decision doc ([V]-tagged, meaning "read directly this session", not
"reproducible by a third party"). This script exists so the figure never again
depends on trusting a paragraph: every predicate below is executable, not
described, and every run persists the exact market ID list and trader address
list it counted (the Objective-1 membership-list gap named in the 2026-08-16
audit -- see brain/decisions/2026-08-16-canonical-infrastructure-recon.md --
repeated here since for a defect this size).

Definitions (all parameterised, defaults match the 08-30 doc's stated values):

  POPULATION   -- "clob-resolved markets": markets.resolved = 1 AND
                  markets.resolution_evidence_source = 'clob'. This is the
                  subset the 08-30 doc scoped its 214,413 figure to; it does
                  NOT include the small resolved-via-'gamma' or
                  'hydration_fill' populations, which the doc never
                  characterized separately.

  STRANDED     -- population AND datetime(last_checked) <= datetime(baseline).
                  baseline defaults to 2026-08-14T00:00:00 (the pre-sweep
                  baseline named in the 08-30 doc); --baseline overrides it.
                  A market at or before baseline cannot have had its
                  last_checked bumped by anything the sweep itself did, so it
                  is permanently invisible to requeue_resolved_market_traders.py's
                  `datetime(last_checked) > datetime(last_run)` gate for any
                  last_run at or after that point.

  OPEN POSITION -- positions.status = 'open'. This is not a fresh choice: it is
                  the exact predicate requeue_resolved_market_traders.py:113
                  itself uses to decide which traders it would touch.

  AFFECTED TRADER -- DISTINCT positions.trader_address, joined to the stranded
                  market population on positions.market_id = markets.market_id,
                  filtered to status='open'. Same join shape as
                  requeue_resolved_market_traders.py:110-115 (which builds its
                  market-id IN-list first, then queries positions against it);
                  --selfcheck recomputes the trader set via that literal
                  IN-list style as an independent code path and asserts an
                  exact match.

Read-only against the production DB throughout. Writes one JSON artifact per
run (timestamped, not overwritten), persisting the full stranded market_id
list, the full affected trader_address list, and the open position_id list
alongside the generating parameters.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
DEFAULT_BASELINE = "2026-08-14T00:00:00"  # pre-sweep baseline, 2026-08-30-canonical-writer-column-gap.md

POPULATION_WHERE = "m.resolved = 1 AND m.resolution_evidence_source = 'clob'"


def population_market_ids(conn):
    rows = conn.execute(f"SELECT m.market_id FROM markets m WHERE {POPULATION_WHERE}").fetchall()
    return set(r[0] for r in rows)


def stranded_market_ids(conn, baseline):
    rows = conn.execute(f"""
        SELECT m.market_id FROM markets m
        WHERE {POPULATION_WHERE} AND datetime(m.last_checked) <= datetime(?)
    """, (baseline,)).fetchall()
    return set(r[0] for r in rows)


def open_positions_on_markets_via_join(conn, baseline):
    """Affected open positions/traders, JOIN style."""
    rows = conn.execute(f"""
        SELECT p.position_id, p.trader_address, p.market_id
        FROM positions p JOIN markets m ON p.market_id = m.market_id
        WHERE {POPULATION_WHERE} AND datetime(m.last_checked) <= datetime(?)
          AND p.status = 'open'
    """, (baseline,)).fetchall()
    return rows


def affected_traders_via_in_list(conn, market_ids):
    """Independent re-derivation matching requeue_resolved_market_traders.py:110-115's
    literal two-step shape (market-id IN-list computed first, then queried against
    positions) -- used only by --selfcheck to cross-check the JOIN-style result above."""
    if not market_ids:
        return set()
    mids = sorted(market_ids)
    placeholders = ",".join("?" * len(mids))
    rows = conn.execute(f"""
        SELECT DISTINCT trader_address FROM positions
        WHERE status = 'open' AND market_id IN ({placeholders})
    """, mids).fetchall()
    return set(r[0] for r in rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--baseline", default=DEFAULT_BASELINE,
                     help="stranded predicate cutoff: last_checked <= this timestamp (default: pre-sweep baseline, 2026-08-14T00:00:00)")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations"))
    ap.add_argument("--selfcheck", action="store_true",
                     help="recompute affected traders via requeue_resolved_market_traders.py's own IN-list join shape and assert exact match against the JOIN-style result")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    population = population_market_ids(conn)
    stranded = stranded_market_ids(conn, args.baseline)
    open_rows = open_positions_on_markets_via_join(conn, args.baseline)

    open_position_ids = sorted(set(r[0] for r in open_rows))
    affected_traders = sorted(set(r[1] for r in open_rows))
    affected_markets_with_open_positions = sorted(set(r[2] for r in open_rows))

    selfcheck_result = None
    if args.selfcheck:
        traders_join = set(affected_traders)
        traders_in_list = affected_traders_via_in_list(conn, stranded)
        match = traders_join == traders_in_list
        selfcheck_result = {
            "traders_via_join": len(traders_join),
            "traders_via_in_list": len(traders_in_list),
            "exact_match": match,
        }
        print(f"[selfcheck] JOIN-style traders: {len(traders_join)}  IN-list-style traders: {len(traders_in_list)}  match={match}")
        if not match:
            print("[selfcheck] FAILED: the two equivalent-by-construction queries diverged -- "
                  "this is a real bug (both are pure SQL, no randomness), not measurement noise.",
                  file=sys.stderr)
            sys.exit(1)
        print("[selfcheck] PASSED: exact match, as expected for two equivalent SQL formulations")

        # internal invariants, independent of any external oracle (Part 1 found none to check against)
        assert stranded <= population, "stranded set must be a subset of the population by construction"
        assert set(open_position_ids) == set(r[0] for r in open_rows), "position_id list must be internally consistent"
        print(f"[selfcheck] stranded ({len(stranded)}) is a subset of population ({len(population)}): OK")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "params": {
            "baseline": args.baseline,
            "population_predicate": POPULATION_WHERE,
            "stranded_predicate": f"{POPULATION_WHERE} AND datetime(last_checked) <= datetime('{args.baseline}')",
            "open_position_predicate": "positions.status = 'open'",
        },
        "population_market_count": len(population),
        "stranded_market_count": len(stranded),
        "stranded_market_ids": sorted(stranded),
        "open_position_count": len(open_position_ids),
        "open_position_ids": open_position_ids,
        "affected_market_count_with_open_positions": len(affected_markets_with_open_positions),
        "affected_trader_count": len(affected_traders),
        "affected_trader_addresses": affected_traders,
        "selfcheck": selfcheck_result,
        "note": "This script has no committed predecessor to reconcile against -- see "
                "brain/decisions/2026-09-07-stranded-markets-figure-reconciliation.md Part 1. "
                "It establishes the defect's current scope as a fresh, reproducible measurement, "
                "not a reconciliation of the 8,077/1,983 figure.",
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"last_checked_stranded_markets_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"population={len(population)} stranded={len(stranded)} "
          f"({100.0 * len(stranded) / len(population):.1f}%) "
          f"open_positions={len(open_position_ids)} affected_traders={len(affected_traders)}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
