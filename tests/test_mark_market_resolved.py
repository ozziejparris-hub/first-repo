#!/usr/bin/env python3
"""
Unit tests for monitoring.resolution_writer.mark_market_resolved() and its
ranking comparator, against a fresh in-memory SQLite DB matching the
post-Stage-0 markets schema. Never touches production.

Design: brain/decisions/2026-08-19-canonical-resolution-write-design.md §A1/A2/B/C.

Per standing discipline, these tests must be capable of failing against a
deliberately broken comparator -- demonstrated at the bottom of this file
(run with --demonstrate-failure), not merely asserted.
"""

import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.resolution_writer import mark_market_resolved, EVIDENCE_RANK


def fresh_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            resolved BOOLEAN DEFAULT 0,
            winning_outcome TEXT,
            resolution_date TIMESTAMP,
            resolution_recorded_at TIMESTAMP,
            resolution_evidence_source TEXT,
            resolution_evidence_detail TEXT
        )
    """)
    return conn


def seed(conn, market_id, resolved=0, winning_outcome=None, resolution_date=None,
         resolution_evidence_source=None):
    conn.execute(
        "INSERT INTO markets (market_id, resolved, winning_outcome, resolution_date, "
        "resolution_evidence_source) VALUES (?, ?, ?, ?, ?)",
        (market_id, resolved, winning_outcome, resolution_date, resolution_evidence_source),
    )
    conn.commit()


PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}")


def run_all_tests(mmr=mark_market_resolved):
    """All tests as one function so a broken comparator can be swapped in
    via the `mmr` parameter for the falsifiability demonstration below."""
    global PASSED, FAILED
    PASSED = FAILED = 0

    print("[T1] unresolved market, first write -- always accepted")
    conn = fresh_conn()
    seed(conn, "m1", resolved=0)
    r = mmr(conn, "m1", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="clob")
    check("accepted=True on first write", r.accepted is True)
    check("previous_value is None (row was unresolved)", r.previous_value is None)
    row = conn.execute("SELECT resolved, winning_outcome, resolution_evidence_source FROM markets WHERE market_id='m1'").fetchone()
    check("actually wrote resolved=1", row[0] == 1)
    check("actually wrote winning_outcome", row[1] == "Yes")
    check("actually wrote evidence_source", row[2] == "clob")

    print("\n[T2] higher rank (clob) overwrites lower rank (gamma)")
    conn = fresh_conn()
    seed(conn, "m2", resolved=1, winning_outcome="No", resolution_evidence_source="gamma")
    r = mmr(conn, "m2", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="clob")
    check("accepted=True (clob outranks gamma)", r.accepted is True)
    check("previous_value shows the prior gamma claim", r.previous_value is not None
          and r.previous_value["winning_outcome"] == "No")
    row = conn.execute("SELECT winning_outcome, resolution_evidence_source FROM markets WHERE market_id='m2'").fetchone()
    check("value actually changed to the clob proposal", row == ("Yes", "clob"))

    print("\n[T3] lower rank (gamma) does NOT overwrite higher rank (clob)")
    conn = fresh_conn()
    seed(conn, "m3", resolved=1, winning_outcome="Yes", resolution_evidence_source="clob")
    r = mmr(conn, "m3", winning_outcome="No", resolution_event_time=None,
            evidence_source="gamma")
    check("accepted=False (gamma cannot outrank clob)", r.accepted is False)
    check("reason names existing outranking", "existing value ranks higher" in r.reason)
    row = conn.execute("SELECT winning_outcome, resolution_evidence_source FROM markets WHERE market_id='m3'").fetchone()
    check("stored value UNCHANGED (still clob's Yes)", row == ("Yes", "clob"))

    print("\n[T4] same-rank, matching proposed value -- silent no-op")
    conn = fresh_conn()
    seed(conn, "m4", resolved=1, winning_outcome="Yes", resolution_evidence_source="gamma")
    r = mmr(conn, "m4", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="manual_verified")  # same rank (2) as gamma, per A1
    check("accepted=False (same-rank match is a no-op)", r.accepted is False)
    check("reason names a matching no-op, not a flag", "matches existing" in r.reason)
    row = conn.execute("SELECT winning_outcome, resolution_evidence_source FROM markets WHERE market_id='m4'").fetchone()
    check("stored value unchanged, still gamma's tag (not overwritten by manual_verified)",
          row == ("Yes", "gamma"))

    print("\n[T5] same-rank, DIFFERING proposed value -- flagged, not overwritten")
    conn = fresh_conn()
    seed(conn, "m5", resolved=1, winning_outcome="Yes", resolution_evidence_source="gamma")
    r = mmr(conn, "m5", winning_outcome="No", resolution_event_time=None,
            evidence_source="hydration_fill")  # same rank (2) as gamma
    check("accepted=False (flagged, not silently discarded, not overwritten)", r.accepted is False)
    check("reason is the flagged-disagreement branch, not the matching no-op branch",
          r.reason == "flagged: same-rank disagreement")
    row = conn.execute("SELECT winning_outcome, resolution_evidence_source FROM markets WHERE market_id='m5'").fetchone()
    check("stored value UNCHANGED (first-wins: gamma's Yes retained, not hydration_fill's No)",
          row == ("Yes", "gamma"))

    print("\n[T6] dry_run makes no write, even when the proposal would be accepted")
    conn = fresh_conn()
    seed(conn, "m6", resolved=0)
    r = mmr(conn, "m6", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="clob", dry_run=True)
    check("accepted=True (dry_run still reports what WOULD happen)", r.accepted is True)
    check("written_value populated for caller inspection", r.written_value is not None)
    row = conn.execute("SELECT resolved, winning_outcome FROM markets WHERE market_id='m6'").fetchone()
    check("row NOT actually written (resolved still 0)", row[0] == 0)
    check("winning_outcome NOT actually written", row[1] is None)

    print("\n[T7] untagged legacy value (resolved=1, evidence_source NULL) -- treated as unranked, improvable")
    conn = fresh_conn()
    seed(conn, "m7", resolved=1, winning_outcome="Yes", resolution_evidence_source=None)
    r = mmr(conn, "m7", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="gamma")
    check("accepted=True (any real evidence_source can improve on an untagged legacy value)",
          r.accepted is True)

    print("\n[T8] winning_outcome=None rejected unless allow_no_winner=True")
    conn = fresh_conn()
    seed(conn, "m8", resolved=0)
    r = mmr(conn, "m8", winning_outcome=None, resolution_event_time=None,
            evidence_source="gamma")
    check("accepted=False without allow_no_winner", r.accepted is False)
    r2 = mmr(conn, "m8", winning_outcome=None, resolution_event_time=None,
             evidence_source="gamma", allow_no_winner=True)
    check("accepted=True with allow_no_winner=True", r2.accepted is True)

    print("\n[T9] resolution_date 3-tier fallback: event_time > existing proxy > write-time")
    conn = fresh_conn()
    seed(conn, "m9a", resolved=0, resolution_date="2026-01-01 00:00:00")  # existing proxy
    r = mmr(conn, "m9a", winning_outcome="Yes", resolution_event_time=None,
            evidence_source="gamma")
    row = conn.execute("SELECT resolution_date FROM markets WHERE market_id='m9a'").fetchone()
    check("no event_time given, existing proxy PRESERVED (not overwritten by write-time)",
          row[0] == "2026-01-01 00:00:00")

    conn2 = fresh_conn()
    seed(conn2, "m9b", resolved=0, resolution_date=None)
    event_time = datetime(2026, 3, 15, 12, 0, 0)
    r2 = mmr(conn2, "m9b", winning_outcome="Yes", resolution_event_time=event_time,
              evidence_source="clob")
    row2 = conn2.execute("SELECT resolution_date FROM markets WHERE market_id='m9b'").fetchone()
    # sqlite3's default adapter serializes datetime -> str on write and never
    # deserializes back on plain read; compare against str(event_time), the
    # same representation SQLite itself stores, not the original object.
    check("true event_time given, used directly", row2[0] == str(event_time))

    return PASSED, FAILED


if __name__ == "__main__":
    if "--demonstrate-failure" in sys.argv:
        # Falsifiability demonstration: swap in a deliberately broken
        # comparator (rank comparison flipped) and show these same tests
        # now fail, proving they are not vacuously true.
        import monitoring.resolution_writer as rw

        def broken_mmr(conn, market_id, **kwargs):
            # Deliberately invert the ranking direction.
            orig = dict(rw.EVIDENCE_RANK)
            rw.EVIDENCE_RANK["clob"], rw.EVIDENCE_RANK["gamma"] = 2, 1
            try:
                return rw.mark_market_resolved(conn, market_id, **kwargs)
            finally:
                rw.EVIDENCE_RANK.clear()
                rw.EVIDENCE_RANK.update(orig)

        print("=== DEMONSTRATING FAILURE with a deliberately inverted ranking ===\n")
        p, f = run_all_tests(mmr=broken_mmr)
        print(f"\n{p} passed, {f} failed (expect failures here -- this proves the tests are not tautological)")
        sys.exit(0 if f > 0 else 1)  # exit 0 only if we DID see failures as expected
    else:
        p, f = run_all_tests()
        print(f"\n{p} passed, {f} failed")
        sys.exit(1 if f else 0)
