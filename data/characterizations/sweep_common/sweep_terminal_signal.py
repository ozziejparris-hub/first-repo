#!/usr/bin/env python3
"""
data/characterizations/sweep_common/sweep_terminal_signal.py

Fix 2 of 2026-08-23-sweep-safety-fixes.md
(2026-08-23-sweep-inhibitor-survey.md, 752cdbd; wired per
2026-08-21-discovery-gap-closure-prereg.md's amendment, 23630ee).

The sweep currently gives no automated indication that a detached segment
finished or died. Segment 2's own persistent monitor (task bkl2qudts) died
silently with its launching session and left only "[killed]" -- no report,
no terminal-state notification. Segment 2's clean 121/121 finish was only
confirmed by a human reading the checkpoint and log directly, after the
fact.

This module provides the two pieces a future segment driver
(segment3_write.py or later -- NOT created or launched by this task) must
call at its exit points:

  write_terminal_marker(...) -- a small JSON file distinct from the
  per-batch checkpoint. The checkpoint says how far a run got; this says
  WHY it stopped (COMPLETE / ABORTED / MAINTENANCE-STOPPED / EXCEPTION),
  which the checkpoint alone cannot express -- a checkpoint frozen at
  batch 87 looks identical whether the run is still going, paused for the
  night, or dead. Written atomically (temp file + os.replace), the same
  pattern segment2_write.py's write_checkpoint() already uses.

  send_telegram_terminal(message) -- a synchronous, fire-and-forget
  Telegram send for TERMINAL states only (completion or abort), never
  per-batch. Modeled directly on the established, already-battle-tested
  pattern in scripts/audit_invariants.py's send_telegram_alert() /
  _send_telegram_async() -- a plain asyncio.run(...) wrapper around
  python-telegram-bot's Bot.send_message, reading credentials from the
  same telegram_alerts_token / telegram_chat_id environment variables
  that script already uses. Deliberately NOT
  monitoring/telegram_bot.py's TelegramNotifier class, which is built for
  a long-lived, bidirectional polling bot (command handlers, /start,
  /stop) -- far more machinery than a one-shot message from a short-lived
  script needs, and it isn't designed to be spun up and torn down once
  per process exit.

  GUARANTEE: send_telegram_terminal() never raises. Any failure --
  missing credentials, network error, Telegram API error, an import
  error, anything -- is caught inside the function and logged to stderr;
  it returns False rather than propagating. A Telegram outage must never
  affect the sweep's own exit code or leave the terminal marker unwritten
  -- callers should call write_terminal_marker() first, unconditionally,
  and treat send_telegram_terminal()'s return value as informational only.

CALL PATTERN a driver should follow (see
tests/test_sweep_terminal_signal.py for a worked demonstration of all
three paths against this exact module, exercised directly -- no segment
was run to produce it):

    try:
        ... existing batch loop, exactly as segment2_write.py's ...
    except Exception as exc:
        write_terminal_marker(marker_path, status="EXCEPTION", ...,
                               reason=f"{type(exc).__name__}: {exc}")
        send_telegram_terminal(f"[SWEEP] segmentN CRASHED: {exc}")
        raise  # do not swallow the real error -- the marker is in
               # addition to normal failure, not a replacement for it
    else:
        status = "ABORTED" if aborted else ("COMPLETE" if done else ...)
        write_terminal_marker(marker_path, status=status, ..., reason=abort_reason)
        send_telegram_terminal(f"[SWEEP] segmentN {status}: "
                                f"{batches_completed}/{n_batches} batches")

NOT wired into segment2_write.py. That segment already ran to completion
(commit b3f4aea) before this module existed; retrofitting a completed,
already-committed driver after the fact would misstate what code actually
produced segment 2's results, which this project's own reproducibility
discipline (prereg §G) treats as a hard line. This module is for the
NEXT driver to import, not a rewrite of the last one.

LIMITATION, stated plainly, not implied away: a hard kill (SIGKILL,
power loss, an OOM-kill) gives the process no chance to run ANY exit
code, including everything in this module. No marker is written and no
Telegram message is sent in that case -- nothing in userspace can trap
SIGKILL, and this module does not pretend otherwise. The absence of BOTH
a terminal marker and a recent checkpoint (per
scripts/daily_maintenance.py's companion checkpoint-recency check, Fix 1)
is itself the signal a hard kill leaves behind. A human or an automated
watcher checking on a segment must read "no marker, stale checkpoint" as
"probably killed," not wait for a report that a hard kill made
impossible to produce.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The driver's own existing status vocabulary (segment2_write.py's final
# print block: COMPLETE / ABORTED / MAINTENANCE-STOPPED / STOPPED
# (incomplete)) plus EXCEPTION, added here for the one terminal state that
# vocabulary never needed before -- reused, not reinvented.
VALID_STATUSES = frozenset({
    "COMPLETE", "ABORTED", "MAINTENANCE-STOPPED", "STOPPED (incomplete)", "EXCEPTION",
})


def write_terminal_marker(
    marker_path,
    status: str,
    batches_completed: int,
    n_batches: int,
    cumulative_processed: int,
    cumulative_tally: dict,
    reason: str = None,
) -> dict:
    """
    Write a terminal-state marker atomically (temp file + os.replace, so a
    crash mid-write cannot leave a corrupt marker on disk -- identical
    pattern to the per-batch checkpoint). Returns the state dict written,
    for the caller to log or assert against in tests.

    status must be one of VALID_STATUSES -- raises ValueError otherwise.
    This function is deliberately NOT fail-open the way the recency check
    (Fix 1) is: a marker recording the wrong thing is worse than no
    marker at all, so a caller passing a bad status should find out
    immediately, not have it silently written anyway.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown status {status!r}; must be one of {sorted(VALID_STATUSES)}")

    marker_path = Path(marker_path)
    state = {
        "status": status,
        "reason": reason,
        "batches_completed": batches_completed,
        "n_batches": n_batches,
        "cumulative_processed": cumulative_processed,
        "cumulative_tally": cumulative_tally,
        "written_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_suffix(marker_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, marker_path)
    return state


async def _send_telegram_async(token: str, chat_id: str, message: str) -> None:
    from telegram import Bot
    bot = Bot(token=token)
    MAX = 4000
    text = message if len(message) <= MAX else message[:MAX] + "\n...[truncated]"
    await bot.send_message(
        chat_id=chat_id, text=text, parse_mode="HTML",
        read_timeout=15, write_timeout=15,
    )


def send_telegram_terminal(message: str) -> bool:
    """
    Best-effort terminal-state notification. Returns True on a confirmed
    send, False on ANY failure (missing credentials, network error, API
    error, import error) -- never raises. Callers must treat False as
    informational, not fatal: the driver's exit code and its terminal
    marker (write_terminal_marker, above) are independent of whether this
    call succeeds.
    """
    try:
        token = os.getenv("telegram_alerts_token")
        chat_id = os.getenv("telegram_chat_id")
        if not token or not chat_id:
            print("[TELEGRAM] Credentials not found -- skipping terminal notification.", file=sys.stderr)
            return False
        asyncio.run(_send_telegram_async(token, chat_id, message))
        print("[TELEGRAM] Terminal notification sent.")
        return True
    except Exception as exc:
        print(f"[TELEGRAM] Terminal notification failed (non-fatal): {exc}", file=sys.stderr)
        return False
