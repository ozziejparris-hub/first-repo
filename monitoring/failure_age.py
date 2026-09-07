#!/usr/bin/env python3
"""
monitoring/failure_age.py — failure-age tracking + accepted-failures register.

The layer beneath alert *delivery*. A check can fail persistently and, before
this module, nothing escalated: check_canonical_definitions.py returned exit 1
every day for ~75 days (2026-06-24 → 2026-09-07), logged daily, escalated never;
test_backtest_window_population.py fails every run and became "chronic" by habit,
not by decision.

This module makes two things explicit:

  1. FAILURE AGE. Each individual finding carries a first_seen timestamp, so a
     message can say "failing 12d" instead of repeating the finding text. Age is
     computed from first_seen, never from the state file's mtime, and survives
     process restarts (it lives in the state file).

  2. ACCEPTED FAILURES. A separate register (config/accepted_failures.json)
     lists findings that a human (Oscar) has DELIBERATELY accepted, each with a
     review_by date. A failing check WITH a current register entry is EXPECTED
     and does not alert. Past its review_by it alerts again as "review due".
     Nothing in this module ever writes to the register.

Design contract (see brain/decisions/2026-09-07-failure-age-tracking.md):
  - stdlib only, no first-repo imports — any consumer can import this safely.
  - Pure functions where possible; the only I/O is load_state / save_state /
    load_register, and load_register NEVER writes.
  - Robust to a missing or corrupt state file: fall back to treating every
    finding as newly seen, record that fact in the state file
    (prior_state_status), and flag each seeded finding age_unknown_at_first_seen.
  - No invented history. A finding present at the first run under this schema
    gets *today* as first_seen, with age_unknown_at_first_seen = true. It is
    never back-dated.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Iterable, Optional

# Bump when the on-disk state-file shape changes. A file whose schema_version
# does not match is treated as "pre-age-schema" (reseeded), not as corrupt.
SCHEMA_VERSION = 2

# The one register. Relative to the repo root (this file is monitoring/, so
# parent.parent is the root). Consumers may override by passing an explicit path.
REGISTER_PATH = Path(__file__).resolve().parent.parent / "config" / "accepted_failures.json"

_MAX_PRIOR_EPISODES = 5
_MAX_MESSAGE_LINES = 15
_MAX_LISTED_PER_SECTION = 6


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 instant (trailing 'Z' tolerated). Returns tz-aware UTC."""
    txt = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(s: str) -> date:
    """Parse a YYYY-MM-DD calendar date. Raises ValueError on anything else."""
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def age_days(first_seen_utc: str, ref: datetime) -> int:
    """Whole days between first_seen and ref. Never negative."""
    try:
        delta = ref - _parse_dt(first_seen_utc)
    except (ValueError, TypeError):
        return 0
    return max(0, delta.days)


def _age_str(first_seen_utc: str, ref: datetime) -> str:
    n = age_days(first_seen_utc, ref)
    return "today" if n == 0 else f"{n}d"


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------

def _empty_state(prior_state_status: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "findings": {},
        "resolved_history": {},
        "prior_state_status": prior_state_status,
    }


def _quarantine(path: Path) -> None:
    """Copy a corrupt state file aside for forensics before we overwrite it."""
    try:
        stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, path.with_suffix(path.suffix + f".corrupt-{stamp}"))
    except OSError:
        pass


def load_state(path) -> dict:
    """
    Return a state dict, ALWAYS. Never raises.

    prior_state_status records what we found on disk:
      "ok"             — a valid schema-2 file; findings carry real history
      "missing"        — no file yet (genuine first run)
      "corrupt"        — file existed but was unreadable / wrong shape
                         (a .corrupt-<ts> copy is left beside it)
      "pre_age_schema" — a file from before failure-age tracking
                         (the flat {"violations": [...]} / {"issues": [...]} shape)

    For every status other than "ok", reconcile() will stamp today's date as
    first_seen for all current findings and set age_unknown_at_first_seen.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        return _empty_state("missing")
    except (json.JSONDecodeError, ValueError, OSError):
        _quarantine(p)
        return _empty_state("corrupt")

    if not isinstance(raw, dict):
        _quarantine(p)
        return _empty_state("corrupt")

    if raw.get("schema_version") != SCHEMA_VERSION:
        # Old flat signature file, or a version we don't understand: reseed,
        # do not try to interpret it. No invented history.
        return _empty_state("pre_age_schema")

    findings = raw.get("findings")
    if not isinstance(findings, dict):
        _quarantine(p)
        return _empty_state("corrupt")

    clean: dict = {}
    for key, val in findings.items():
        if isinstance(val, dict) and isinstance(val.get("first_seen_utc"), str):
            clean[key] = {
                "first_seen_utc": val["first_seen_utc"],
                "last_seen_utc": val.get("last_seen_utc", val["first_seen_utc"]),
                "age_unknown_at_first_seen": bool(val.get("age_unknown_at_first_seen", False)),
                "reported_at_utc": val.get("reported_at_utc"),
            }
            if isinstance(val.get("prior_episodes"), list):
                clean[key]["prior_episodes"] = val["prior_episodes"]
            if isinstance(val.get("review_due_alerted_on"), str):
                clean[key]["review_due_alerted_on"] = val["review_due_alerted_on"]

    hist = raw.get("resolved_history")
    return {
        "schema_version": SCHEMA_VERSION,
        "findings": clean,
        "resolved_history": hist if isinstance(hist, dict) else {},
        "prior_state_status": "ok",
    }


def save_state(path, state: dict, now: datetime, *, check: str = "") -> None:
    """Persist state as pretty JSON. Creates the parent dir."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema_version": SCHEMA_VERSION,
        "check": check,
        "updated_at_utc": now.isoformat(),
        "prior_state_status": state.get("prior_state_status", "ok"),
        "findings": state.get("findings", {}),
        "resolved_history": state.get("resolved_history", {}),
    }
    p.write_text(json.dumps(out, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# reconcile — the core age-tracking step
# ---------------------------------------------------------------------------

def reconcile(state: dict, current_keys: Iterable[str], now: datetime) -> tuple[dict, dict]:
    """
    Pure. Given the prior state and the finding keys observed THIS run, return
    (new_state, classification).

    classification = {
        "new":      [keys that were not tracked before this run],
        "ongoing":  [keys tracked before and still present],
        "resolved": [keys tracked before and absent this run],
        "returned": [subset of "new" that has a prior resolved episode — it
                     went away and came back; a NEW first_seen, not the old one],
        "prior_state_status": <passed through from state>,
    }

    A returned finding gets a fresh first_seen (today). Its earlier episode is
    kept under new_state["findings"][key]["prior_episodes"] for context, but the
    age clock restarts — a finding that was fixed and regressed is a new problem.
    """
    prior = state.get("findings", {})
    prior_status = state.get("prior_state_status", "ok")
    resolved_history = {k: list(v) for k, v in state.get("resolved_history", {}).items()}
    age_unknown = prior_status != "ok"
    ts = now.isoformat()

    seen: list[str] = list(dict.fromkeys(current_keys))  # dedupe, preserve order
    new_findings: dict = {}
    cls = {"new": [], "ongoing": [], "resolved": [], "returned": [],
           "prior_state_status": prior_status}

    for key in seen:
        if key in prior:
            f = dict(prior[key])
            f["last_seen_utc"] = ts
            new_findings[key] = f
            cls["ongoing"].append(key)
        else:
            f = {
                "first_seen_utc": ts,
                "last_seen_utc": ts,
                "age_unknown_at_first_seen": age_unknown,
                "reported_at_utc": None,
            }
            past = resolved_history.pop(key, None)
            if past:
                f["prior_episodes"] = past[-_MAX_PRIOR_EPISODES:]
                cls["returned"].append(key)
            new_findings[key] = f
            cls["new"].append(key)

    for key, f in prior.items():
        if key not in new_findings:
            resolved_history.setdefault(key, []).append({
                "first_seen_utc": f.get("first_seen_utc"),
                "last_seen_utc": f.get("last_seen_utc"),
                "reported_at_utc": f.get("reported_at_utc"),
            })
            resolved_history[key] = resolved_history[key][-_MAX_PRIOR_EPISODES:]
            cls["resolved"].append(key)

    new_state = {
        "schema_version": SCHEMA_VERSION,
        "findings": new_findings,
        "resolved_history": resolved_history,
        "prior_state_status": prior_status,
    }
    return new_state, cls


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

_REGISTER_REQUIRED = ("finding_key", "accepted_by", "accepted_on", "reason", "review_by")


def load_register(path=REGISTER_PATH) -> dict:
    """
    Read the accepted-failures register. Returns {"entries": {finding_key: entry}}.
    NEVER writes. Missing file -> empty. Malformed file / entry -> that entry is
    skipped with a stderr note; the rest still load.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text())
    except FileNotFoundError:
        return {"entries": {}}
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"[failure_age] register {p} unreadable ({exc}) — treating as empty",
              file=sys.stderr)
        return {"entries": {}}

    entries: dict = {}
    accepted = raw.get("accepted") if isinstance(raw, dict) else None
    if not isinstance(accepted, list):
        return {"entries": {}}

    for e in accepted:
        if not isinstance(e, dict):
            continue
        if not all(isinstance(e.get(k), str) and e.get(k).strip() for k in _REGISTER_REQUIRED):
            print(f"[failure_age] register entry missing required fields — skipped: {e!r}",
                  file=sys.stderr)
            continue
        try:
            _parse_date(e["review_by"])
        except ValueError:
            print(f"[failure_age] register entry {e['finding_key']!r} has an "
                  f"unparseable review_by ({e['review_by']!r}) — skipped", file=sys.stderr)
            continue
        entries[e["finding_key"]] = e
    return {"entries": entries}


def _register_status(entry: Optional[dict], now: datetime) -> str:
    """'unexpected' (no entry) | 'expected' (entry, in window) | 'review_due' (entry, past review_by)."""
    if entry is None:
        return "unexpected"
    try:
        review_by = _parse_date(entry["review_by"])
    except (ValueError, KeyError):
        return "unexpected"
    return "review_due" if now.date() > review_by else "expected"


# ---------------------------------------------------------------------------
# evaluate — decide what (if anything) to say
# ---------------------------------------------------------------------------

class Decision:
    __slots__ = ("report_new", "review_due", "resolved", "ongoing_context")

    def __init__(self):
        self.report_new: list[str] = []      # unexpected, not yet reported to Oscar
        self.review_due: list[str] = []      # register entry past its review_by, once/day
        self.resolved: list[str] = []        # was reported, now gone, not an accepted finding
        self.ongoing_context: list[str] = [] # unexpected, already reported — "also still failing"

    @property
    def should_send(self) -> bool:
        return bool(self.report_new or self.review_due or self.resolved)


def evaluate(classification: dict, register: dict, new_state: dict, now: datetime,
             alertable_keys: Optional[Iterable[str]] = None) -> Decision:
    """
    Pure. Turn a reconcile() classification + the register into a Decision.

    alertable_keys: if given, only these keys may appear in a message (the rest
    are tracked on disk for their age but never alert — used by the diagnostic
    report to age-track warnings without letting them trigger a send).
    """
    d = Decision()
    entries = register.get("entries", {})
    findings = new_state.get("findings", {})
    hist = new_state.get("resolved_history", {})
    allow = set(alertable_keys) if alertable_keys is not None else None

    def permitted(k: str) -> bool:
        return allow is None or k in allow

    for key in classification.get("new", []) + classification.get("ongoing", []):
        if not permitted(key):
            continue
        status = _register_status(entries.get(key), now)
        f = findings.get(key, {})
        if status == "expected":
            continue  # accepted and in-window: never appears anywhere but the state file
        if status == "review_due":
            if f.get("review_due_alerted_on") != now.date().isoformat():
                d.review_due.append(key)
            continue
        # unexpected
        if key in classification.get("new", []) or not f.get("reported_at_utc"):
            d.report_new.append(key)
        else:
            d.ongoing_context.append(key)

    for key in classification.get("resolved", []):
        if not permitted(key):
            continue
        episodes = hist.get(key) or []
        last = episodes[-1] if episodes else {}
        if not last.get("reported_at_utc"):
            continue  # Oscar was never told it was failing; silent resolution
        if _register_status(entries.get(key), now) == "expected":
            continue  # an accepted finding resolving is not urgent news
        d.resolved.append(key)

    return d


# ---------------------------------------------------------------------------
# render — the part Oscar reads
# ---------------------------------------------------------------------------

def _short(key: str, width: int = 96) -> str:
    """
    'canonical_definitions::scripts/foo.py::SQL string contains ...'
        -> 'scripts/foo.py — SQL string contains ...'
    'diagnostic::issue::[DATABASE] Database is LOCKED ...'
        -> '[DATABASE] Database is LOCKED ...'
    """
    parts = key.split("::")
    if len(parts) >= 3:
        body = f"{parts[1]} — {'::'.join(parts[2:])}"
    elif len(parts) == 2:
        body = parts[1]
    else:
        body = key
    body = " ".join(body.split())
    return body if len(body) <= width else body[: width - 1] + "…"


def render_message(check_title: str, decision: Decision, new_state: dict,
                   now: datetime, state_path) -> Optional[str]:
    """
    Terse plain-text message for the paste-at-session-start workflow, or None if
    there is nothing to send. Leads with what changed; new findings first; shows
    age for anything not new; never mentions accepted-and-in-window findings;
    no counts, no "healthy" content. Capped at 15 lines.
    """
    if not decision.should_send:
        return None

    findings = new_state.get("findings", {})
    hist = new_state.get("resolved_history", {})
    lines = [f"{check_title} — {now.date().isoformat()}", ""]

    def _emit(keys: list[str], fmt) -> None:
        if not keys:
            return
        shown = sorted(keys)[:_MAX_LISTED_PER_SECTION]
        for k in shown:
            lines.append(fmt(k))
        extra = len(keys) - len(shown)
        if extra > 0:
            lines.append(f"  … and {extra} more — see {Path(state_path).name}")

    # Genuinely-new findings vs. findings only seeded today because the prior
    # state was missing/corrupt/pre-age-schema. The second group is not "new" --
    # its true age is unknown -- so it gets an honest, distinct line. This is a
    # one-time artefact of a state-file migration; after this run they carry a
    # reported_at_utc and fall silent.
    genuinely_new = [k for k in decision.report_new
                     if not findings.get(k, {}).get("age_unknown_at_first_seen")]
    seeded_today = [k for k in decision.report_new
                    if findings.get(k, {}).get("age_unknown_at_first_seen")]
    _emit(genuinely_new, lambda k: f"! NEW  {_short(k)}")
    _emit(seeded_today,
          lambda k: f"tracking (age unknown)  {_short(k)} — counting from "
                    f"{(findings.get(k, {}).get('first_seen_utc', now.isoformat()))[:10]}")

    def _rd(k: str) -> str:
        f = findings.get(k, {})
        return f"review due  {_short(k)} — failing {_age_str(f.get('first_seen_utc', now.isoformat()), now)}"
    _emit(decision.review_due, _rd)

    def _rs(k: str) -> str:
        ep = (hist.get(k) or [{}])[-1]
        fs = ep.get("first_seen_utc") or now.isoformat()
        return f"resolved  {_short(k)} — was failing {_age_str(fs, now)}"
    _emit(decision.resolved, _rs)

    if decision.ongoing_context:
        ctx = "; ".join(
            f"{_short(k, 60)} {_age_str(findings.get(k, {}).get('first_seen_utc', now.isoformat()), now)}"
            for k in sorted(decision.ongoing_context)[:_MAX_LISTED_PER_SECTION]
        )
        lines += ["", f"also still failing: {ctx}"]

    lines += ["", f"state: {state_path}"]

    if len(lines) > _MAX_MESSAGE_LINES:
        lines = lines[: _MAX_MESSAGE_LINES - 1] + [f"… truncated — see {state_path}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# mark_reported — call ONLY after a message actually went out
# ---------------------------------------------------------------------------

def mark_reported(new_state: dict, decision: Decision, now: datetime) -> None:
    """Mutates new_state: record that Oscar has now been shown these findings."""
    ts = now.isoformat()
    today = now.date().isoformat()
    findings = new_state.get("findings", {})
    for key in decision.report_new + decision.ongoing_context:
        if key in findings:
            findings[key]["reported_at_utc"] = ts
    for key in decision.review_due:
        if key in findings:
            findings[key]["reported_at_utc"] = ts
            findings[key]["review_due_alerted_on"] = today
