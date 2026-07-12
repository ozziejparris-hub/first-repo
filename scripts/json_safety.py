#!/usr/bin/env python3
"""
json_safety.py — shared safe-JSON primitives for every writer of
trading-swarm's brain/*.json files from this repo.

Companion file: /home/parison/trading-swarm/orchestrator/json_safety.py
(separate repo — cannot import this one, kept behaviourally identical by
hand). The property that actually makes cross-repo writes safe is NOT
"same implementation" — it's the LOCK PATH: both derive
`<resolved target>.lock` the same way, so an fcntl.flock() taken here and
an fcntl.flock() taken by the sibling file are the same kernel-level lock
on the same inode, regardless of which repo/process/language took it. If
you ever change the lock-path derivation in _lock_path() below, change it
in the sibling file too — otherwise cross-repo writes silently stop
serializing (see tests/test_cross_repo_lock.py in the swarm repo for the
proof).

Three protections, each separately load-bearing (Fable swarm audit Area
1.3, and the atomicity-sibling fixes that followed it — register_signal.py,
detect_counter_signals.py, score_str003_signals.py all write
trading-swarm/brain/signals.json and/or findings.json and must serialize
against the swarm's own orchestrator, run_feedback_loop_agent.py, and
ollama_agent_loop.py):

  1. json_lock(path) — fcntl exclusive lock on a SIDECAR file (<path>.lock),
     never the target file itself. Hold it across the ENTIRE
     read-modify-write, not just the write half — locking only the write
     still lets two readers both load stale data and lose an update.
  2. atomic_write_json(path, data) — temp file in the same directory,
     fsync, os.replace. A crash mid-write leaves the ORIGINAL untouched.
     Rolls the previous file forward into <path>.bak first.
  3. load_json_or_raise(path, default) — a genuinely missing file
     bootstraps `default`; a file that exists but won't parse is backed
     up untouched and RAISES CorruptJSONError. Never silently
     reinitializes over an unrecovered original.
"""

import fcntl
import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class CorruptJSONError(Exception):
    """`path` exists but failed to parse. Never auto-recover from this —
    it must surface as a loud error, not a silent data-destroying reinit."""

    def __init__(self, path, original):
        self.path = Path(path)
        self.original = original
        super().__init__(f"{self.path}: {original}")


def _lock_path(path: Path) -> Path:
    """Sidecar lock file for `path`. Resolves `path` first (symlinks, '..')
    so two callers spelling the same file differently — or two separate
    repos with their own hardcoded absolute constants — converge on the
    identical lock file / inode. THIS is the cross-repo compatibility
    contract; keep it byte-identical to the sibling module."""
    resolved = path.resolve()
    return resolved.with_name(resolved.name + ".lock")


@contextmanager
def json_lock(path):
    """Exclusive lock serializing every read-modify-write of `path` across
    processes, repos, and languages — anything that flocks the same
    sidecar path mutually excludes everything else that does. Blocking
    (not LOCK_NB): the second caller waits, it does not skip its turn."""
    path = Path(path)
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.touch(exist_ok=True)
    with open(lock_file, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _backup_corrupt_file(path: Path) -> Path:
    """Forensic copy of a corrupt file, timestamped so repeated corruption
    events don't clobber each other's evidence."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{ts}")
    shutil.copy2(path, backup)
    return backup


def load_json_or_raise(path, default=None):
    """Load JSON at `path`. Returns `default` (called if callable, else
    used as-is; `{}` if `default` is None) ONLY when the file is
    genuinely missing — legitimate first-run bootstrap. If it exists but
    won't parse, back it up untouched and raise CorruptJSONError. Callers
    must not catch this and fall back to a fresh skeleton — that
    collapses "missing" and "corrupt" into the exact silent-wipe bug this
    module exists to kill."""
    path = Path(path)
    if not path.exists():
        return default() if callable(default) else (default if default is not None else {})
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        backup = _backup_corrupt_file(path)
        log.error(
            f"CORRUPT {path} — refusing to reinitialize. Original left on "
            f"disk untouched; forensic copy at {backup}. Parse error: {e}"
        )
        raise CorruptJSONError(path, e) from e


def atomic_write_json(path, data, keep_bak=True):
    """Write JSON crash-safely: temp file in the same directory (so
    os.replace is atomic — same filesystem), fsync before replace. A
    reader, or a crash mid-write, only ever observes the fully-old or
    fully-new file, never a truncated one. Rolls the previous file
    forward into <path>.bak first (cheap last-known-good insurance)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if keep_bak and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
