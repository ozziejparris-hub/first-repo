#!/usr/bin/env python3
"""
Verification for the two tranche-2 driver defects fixed 2026-08-22
(2026-08-22-tranche2-driver-fixes.md). Proves both fixes work in the
direction that matters AND that the fixes do not weaken the one condition
that must still pause.

Uses an in-memory SQLite database (":memory:") with a minimal `markets`
table -- the exact columns monitoring/resolution_writer.py's
mark_market_resolved() reads and writes, nothing else. NEVER opens the
production database. Calls the real, unmodified mark_market_resolved()
directly, so the reason strings compared against ACCEPTED_REASONS are the
function's actual output, not hand-transcribed text.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from monitoring.resolution_writer import mark_market_resolved

DRIVER_PATH = Path(__file__).parent / "tranche2_write.py"


def load_driver_accepted_reasons():
    """Import tranche2_write.py's post-fix ACCEPTED_REASONS as live code,
    not a copy-pasted set -- so this test fails if the driver's constant
    ever drifts from what's actually checked."""
    spec = importlib.util.spec_from_file_location("tranche2_write_under_test", DRIVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    # tranche2_write.py imports scripts.backfill_market_dates and requests
    # at module level, executed on load -- these are safe, side-effect-free
    # imports (no DB connection opened, no network call made merely by
    # importing).
    spec.loader.exec_module(mod)
    return mod.ACCEPTED_REASONS


def get_pre_fix_accepted_reasons():
    """The exact ACCEPTED_REASONS set from the pre-fix commit (1a54ad7),
    read from git history directly -- not retyped -- so the 'would this
    have failed before' claim is checked against the actual prior code."""
    import subprocess
    old_source = subprocess.run(
        ["git", "show", "1a54ad7:data/characterizations/tranche2_execution/tranche2_write.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    ns = {}
    # Extract just the ACCEPTED_REASONS literal via exec of that one
    # assignment -- avoids executing the rest of the pre-fix module (which
    # has the same import-time side effects as above, harmless, but
    # unnecessary here).
    start = old_source.index("ACCEPTED_REASONS = {")
    end = old_source.index("}", start) + 1
    exec(old_source[start:end], ns)
    return ns["ACCEPTED_REASONS"]


def make_test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY,
            resolved INTEGER,
            winning_outcome TEXT,
            resolution_date TIMESTAMP,
            resolution_recorded_at TIMESTAMP,
            resolution_evidence_source TEXT,
            resolution_evidence_detail TEXT
        )
    """)
    return conn


def main():
    results = {}

    # --- Case A: same-rank MATCH (the exact batch-1 kill-test scenario) ---
    conn = make_test_db()
    conn.execute(
        "INSERT INTO markets (market_id, resolved, winning_outcome, resolution_date, "
        "resolution_evidence_source) VALUES (?, 1, 'Yes', '2026-08-22 14:43:40', 'clob')",
        ("TEST_MATCH",),
    )
    conn.commit()
    result_match = mark_market_resolved(
        conn, "TEST_MATCH",
        winning_outcome="Yes",  # same as existing -- a re-attempt confirming the same CLOB answer
        resolution_event_time=None,
        evidence_source="clob",
        evidence_detail="token.winner",
        dry_run=False,
    )
    results["same_rank_match"] = {
        "reason": result_match.reason,
        "accepted": result_match.accepted,
    }
    conn.close()

    # --- Case B: same-rank DISAGREEMENT (must still pause) ---
    conn = make_test_db()
    conn.execute(
        "INSERT INTO markets (market_id, resolved, winning_outcome, resolution_date, "
        "resolution_evidence_source) VALUES (?, 1, 'No', '2026-08-22 14:43:40', 'clob')",
        ("TEST_DISAGREE",),
    )
    conn.commit()
    result_disagree = mark_market_resolved(
        conn, "TEST_DISAGREE",
        winning_outcome="Yes",  # differs from existing 'No' -- a genuine same-rank disagreement
        resolution_event_time=None,
        evidence_source="clob",
        evidence_detail="token.winner",
        dry_run=False,
    )
    results["same_rank_disagreement"] = {
        "reason": result_disagree.reason,
        "accepted": result_disagree.accepted,
    }
    conn.close()

    # --- Case C: cross-rank overwrite (the other gap found by enumeration) ---
    conn = make_test_db()
    conn.execute(
        "INSERT INTO markets (market_id, resolved, winning_outcome, resolution_date, "
        "resolution_evidence_source) VALUES (?, 1, 'Yes', '2026-08-22 14:43:40', 'gamma')",
        ("TEST_CROSSRANK",),
    )
    conn.commit()
    result_crossrank = mark_market_resolved(
        conn, "TEST_CROSSRANK",
        winning_outcome="Yes",
        resolution_event_time=None,
        evidence_source="clob",  # rank 1, outranks existing gamma (rank 2)
        evidence_detail="token.winner",
        dry_run=False,
    )
    results["cross_rank_overwrite"] = {
        "reason": result_crossrank.reason,
        "accepted": result_crossrank.accepted,
    }
    conn.close()

    print("=== Real mark_market_resolved() outputs (unmodified function, isolated in-memory DB) ===")
    for k, v in results.items():
        print(f"  {k}: reason={v['reason']!r} accepted={v['accepted']}")

    pre_fix = get_pre_fix_accepted_reasons()
    post_fix = load_driver_accepted_reasons()

    print(f"\n=== Pre-fix ACCEPTED_REASONS (git 1a54ad7) === {pre_fix}")
    print(f"=== Post-fix ACCEPTED_REASONS (this driver, live import) === {post_fix}")

    checks = []

    # Defect 1, direction 1: match must be accepted (whitelisted) post-fix,
    # and must NOT have been whitelisted pre-fix (proving this is a real fix,
    # not a no-op).
    match_reason = results["same_rank_match"]["reason"]
    checks.append((
        "same-rank MATCH was NOT whitelisted pre-fix (proves the bug existed)",
        match_reason not in pre_fix,
    ))
    checks.append((
        "same-rank MATCH IS whitelisted post-fix (proves the fix works)",
        match_reason in post_fix,
    ))

    # Defect 1, direction 2: disagreement must NOT be whitelisted, pre- or
    # post-fix (the fix must not have accidentally loosened this).
    disagree_reason = results["same_rank_disagreement"]["reason"]
    checks.append((
        "same-rank DISAGREEMENT was NOT whitelisted pre-fix",
        disagree_reason not in pre_fix,
    ))
    checks.append((
        "same-rank DISAGREEMENT is STILL NOT whitelisted post-fix (still pauses)",
        disagree_reason not in post_fix,
    ))

    # Bonus: the cross-rank-overwrite gap found by full enumeration.
    crossrank_reason = results["cross_rank_overwrite"]["reason"]
    checks.append((
        "cross-rank overwrite was NOT whitelisted pre-fix (a second real gap, found by enumeration)",
        crossrank_reason not in pre_fix,
    ))
    checks.append((
        "cross-rank overwrite IS whitelisted post-fix",
        crossrank_reason in post_fix,
    ))

    # Defect 2: skip-list predicate. The driver's actual skip-list condition
    # is `if result.reason in ACCEPTED_REASONS: resolved_ids.add(...)` --
    # verify this predicate directly against the three real reasons above,
    # plus confirm an "open"/"indeterminate" classification never reaches
    # mark_market_resolved() at all (checked by code inspection, not
    # re-derived here, since those classifications short-circuit before any
    # mark_market_resolved() call in the driver's own loop).
    checks.append((
        "skip-list predicate (reason in ACCEPTED_REASONS) is TRUE for same-rank match",
        match_reason in post_fix,
    ))
    checks.append((
        "skip-list predicate is FALSE for same-rank disagreement (must remain re-attemptable)",
        disagree_reason not in post_fix,
    ))
    checks.append((
        "skip-list predicate is TRUE for cross-rank overwrite (confirmed resolved via our write)",
        crossrank_reason in post_fix,
    ))

    print("\n=== Checks ===")
    all_pass = True
    for desc, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {desc}")

    print(f"\n{'ALL CHECKS PASSED' if all_pass else 'CHECKS FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
