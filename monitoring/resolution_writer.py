"""
Canonical market-resolution write path.

mark_market_resolved() -- the single function that should decide
markets.resolved / winning_outcome / resolution_date / resolution_recorded_at
/ resolution_evidence_source / resolution_evidence_detail, per the design in
brain/decisions/2026-08-19-canonical-resolution-write-design.md (§C), built
in this session's Stage 0 (see 2026-08-19-stage0-implementation.md).

STAGE 0 STATUS: this function is called by nothing. None of the 13 writers
characterized in 2026-08-19-market-resolution-write-cluster.md have been
migrated to call it. Migrating a writer is a separate, later task (Stage 1
onward, design §G). Do not wire this into any writer without a dedicated
migration task and its own before/after verification.

Source-ranking model (design §A1/A2), encoded as EVIDENCE_RANK below:
  Rank 1 (highest): "clob"             -- CLOB API token.winner, a direct
                                           declaration, not an inference.
  Rank 2 (tied):     "gamma"            -- Gamma API outcomePrices>=0.99
                     "manual_verified"  -- a human confirmed the outcome by
                                           reading Gamma at some point and
                                           hardcoded it (fix_expired_unresolved.py).
                                           Design §A1: "no basis was found to
                                           rank it above or below [gamma] --
                                           stated as equal rather than
                                           inventing a distinction."
                     "hydration_fill"   -- hydrate_stub_markets.py's
                                           fill-only-if-empty writes. Design
                                           §A1's Rank-2 row explicitly lists
                                           writer #11 alongside #3/#7/#8/#9/#10
                                           -- same rank, not a separate tier;
                                           no special-cased comparator logic
                                           for this source beyond the generic
                                           same-rank policy (design §B: "any
                                           future Rank-1 or Rank-2 writer...
                                           inherits this same policy by
                                           construction").

A market whose existing row has resolved=1 but resolution_evidence_source
IS NULL (i.e. resolved by a non-canonical writer, before this function
existed, or bypassing it) has no recorded rank. This case is not spelled
out verbatim in the design text -- resolved as: an untagged existing value
is treated as lower-ranked than any real, tagged evidence_source, so a
canonical-path proposal can always improve on a legacy, unranked value.
Documented here as an explicit interpretation, not asserted as literal
design text -- see 2026-08-19-stage0-implementation.md for the full
justification.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

log = logging.getLogger("resolution_writer")

EvidenceSource = Literal["clob", "gamma", "manual_verified", "hydration_fill"]

# Lower number = higher authority, matching the design's own "Rank 1
# (highest)" phrasing directly.
EVIDENCE_RANK: dict[str, int] = {
    "clob": 1,
    "gamma": 2,
    "manual_verified": 2,
    "hydration_fill": 2,
}

# An existing resolved=1 row with no resolution_evidence_source recorded
# (pre-canonical, or a non-canonical writer bypassed this function) is
# ranked below every real evidence source -- see module docstring.
_UNRANKED = 99


@dataclass(frozen=True)
class ResolutionWriteResult:
    accepted: bool
    reason: str
    previous_value: Optional[dict]
    written_value: Optional[dict]


def _row_dict(row: sqlite3.Row | tuple) -> dict:
    resolved, winning_outcome, resolution_date, resolution_evidence_source = row
    return {
        "resolved": bool(resolved),
        "winning_outcome": winning_outcome,
        "resolution_date": resolution_date,
        "resolution_evidence_source": resolution_evidence_source,
    }


def mark_market_resolved(
    conn: sqlite3.Connection,
    market_id: str,
    *,
    winning_outcome: Optional[str],
    allow_no_winner: bool = False,
    resolution_event_time: Optional[datetime],
    evidence_source: EvidenceSource,
    evidence_detail: Optional[str] = None,
    dry_run: bool = False,
) -> ResolutionWriteResult:
    """
    The single canonical write path for markets.resolved / winning_outcome /
    resolution_date and their provenance columns. Always sets resolved=1 on
    an accepted write -- this function has no "unresolve" path (see
    trg_resolved_no_unresolve, which enforces the same invariant at the DB
    level as a backstop).

    Never raises for a routine rejection (existing value outranks the
    proposal, or a same-rank match) -- see design §C for why. Does raise on
    a genuine programming error (missing required argument, market_id not a
    string, etc.) via normal Python exceptions, since those are not routine.
    """
    if winning_outcome is None and not allow_no_winner:
        result = ResolutionWriteResult(
            accepted=False,
            reason="rejected: winning_outcome required unless allow_no_winner=True",
            previous_value=None,
            written_value=None,
        )
        log.warning("mark_market_resolved(%s): %s", market_id, result.reason)
        return result

    if evidence_source not in EVIDENCE_RANK:
        # Defensive: Literal is not enforced at runtime by the interpreter.
        result = ResolutionWriteResult(
            accepted=False,
            reason=f"rejected: unknown evidence_source {evidence_source!r}",
            previous_value=None,
            written_value=None,
        )
        log.warning("mark_market_resolved(%s): %s", market_id, result.reason)
        return result

    new_rank = EVIDENCE_RANK[evidence_source]

    row = conn.execute(
        "SELECT resolved, winning_outcome, resolution_date, resolution_evidence_source "
        "FROM markets WHERE market_id = ?",
        (market_id,),
    ).fetchone()

    if row is None:
        result = ResolutionWriteResult(
            accepted=False,
            reason="rejected: market_id not found",
            previous_value=None,
            written_value=None,
        )
        log.warning("mark_market_resolved(%s): %s", market_id, result.reason)
        return result

    prev_resolved, prev_winning_outcome, prev_resolution_date, prev_evidence_source = row

    # Design §C: previous_value is None "if row was unresolved" -- read
    # literally, not merely "not found". A prior resolved=1 claim is what
    # gets represented; an unresolved (or not-found) row has no prior claim
    # to show.
    previous_value = _row_dict(row) if prev_resolved else None

    if not prev_resolved:
        accept = True
        reason = "written"
    else:
        if prev_evidence_source is None:
            accept = True
            reason = "written: existing value has no recorded evidence_source (pre-canonical), proposal accepted"
        else:
            existing_rank = EVIDENCE_RANK.get(prev_evidence_source, _UNRANKED)
            if new_rank < existing_rank:
                accept = True
                reason = "written: proposed evidence outranks existing"
            elif new_rank > existing_rank:
                accept = False
                reason = "no-op: existing value ranks higher than proposed"
            else:
                if prev_winning_outcome == winning_outcome:
                    accept = False
                    reason = "no-op: same-rank value matches existing"
                else:
                    accept = False
                    reason = "flagged: same-rank disagreement"

    if not accept:
        level = logging.WARNING if reason.startswith("flagged") else logging.INFO
        log.log(level, "mark_market_resolved(%s): %s (existing=%r, proposed_winning_outcome=%r, "
                        "proposed_evidence_source=%r)",
                 market_id, reason, previous_value, winning_outcome, evidence_source)
        return ResolutionWriteResult(
            accepted=False, reason=reason, previous_value=previous_value, written_value=None,
        )

    now = datetime.now()
    # Design §D's 3-tier resolution_date fallback: best-known event-time,
    # else whatever is already there (e.g. a monitor.py end_date proxy --
    # that write path is explicitly out of scope, see design §H, but its
    # existing value should not be clobbered by write-time noise here),
    # else -- only when nothing else is available -- write-time.
    if resolution_event_time is not None:
        resolution_date_value = resolution_event_time
    elif prev_resolution_date is not None:
        resolution_date_value = prev_resolution_date
    else:
        resolution_date_value = now

    written_value = {
        "resolved": True,
        "winning_outcome": winning_outcome,
        "resolution_date": resolution_date_value,
        "resolution_evidence_source": evidence_source,
    }

    if dry_run:
        log.info("mark_market_resolved(%s): [DRY RUN] would write %s (%s)",
                  market_id, written_value, reason)
        return ResolutionWriteResult(
            accepted=True, reason=reason, previous_value=previous_value, written_value=written_value,
        )

    conn.execute(
        """
        UPDATE markets
        SET resolved = 1,
            winning_outcome = ?,
            resolution_date = ?,
            resolution_recorded_at = ?,
            resolution_evidence_source = ?,
            resolution_evidence_detail = ?
        WHERE market_id = ?
        """,
        (winning_outcome, resolution_date_value, now, evidence_source, evidence_detail, market_id),
    )
    log.info("mark_market_resolved(%s): %s -> %s", market_id, reason, written_value)

    return ResolutionWriteResult(
        accepted=True, reason=reason, previous_value=previous_value, written_value=written_value,
    )
