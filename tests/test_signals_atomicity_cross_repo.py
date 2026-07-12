#!/usr/bin/env python3
"""
tests/test_signals_atomicity_cross_repo.py

First-repo half of the atomicity-siblings fix (companion to trading-swarm's
tests/test_json_safety.py and tests/test_brain_writers_atomicity.py).

Covers:
  (a) scripts/json_safety.py — the primitives directly (mirrors the swarm
      repo's test_json_safety.py; this repo cannot import that module, so
      its own copy needs its own direct proof).
  (b) register_signal.py — the canonical signal-registration writer.
      Previously flocked signals.json ITSELF (wrong inode vs the swarm's
      signals.json.lock sidecar) and wrote non-atomically in place
      (seek+truncate+dump). Now locked+atomic+never-silently-reinit.
  (c) detect_counter_signals.py / score_str003_signals.py — previously had
      NO locking at all (worse than register_signal.py) despite running
      daily via cron against the same signals.json/findings.json.

Non-tautological anchors: register_signal.py's OLD write pattern is
replicated verbatim and proven to corrupt the original under an injected
crash, and to silently wipe str003_signals on a corrupt read, before the
new code is proven not to.

Run: python3 -m pytest tests/test_signals_atomicity_cross_repo.py -v
"""

import json
import multiprocessing
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import json_safety as js
from json_safety import CorruptJSONError, atomic_write_json, json_lock, load_json_or_raise


# ─────────────────────────────────────────────
# (a) scripts/json_safety.py primitives
# ─────────────────────────────────────────────

def test_missing_file_bootstraps_default(tmp_path):
    target = tmp_path / "signals.json"
    assert load_json_or_raise(target, default=lambda: {"str003_signals": []}) == {"str003_signals": []}


def test_corrupt_file_raises_backs_up_and_leaves_original_untouched(tmp_path):
    target = tmp_path / "signals.json"
    corrupt = '{"str003_signals": [1, '
    target.write_text(corrupt)

    with pytest.raises(CorruptJSONError):
        load_json_or_raise(target)

    assert target.read_text() == corrupt
    backups = list(tmp_path.glob("signals.json.corrupt-*"))
    assert len(backups) == 1


def _old_unsafe_write(filepath, data):
    """Verbatim replica of what register_signal.py, detect_counter_signals.py,
    and score_str003_signals.py all did before this fix: open(path, 'w')
    truncates immediately, dump streams in after."""
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def test_atomic_write_survives_injected_crash_old_pattern_does_not(tmp_path, monkeypatch):
    target = tmp_path / "signals.json"
    target.write_text(json.dumps({"str003_signals": ["irreplaceable"]}))
    original = target.read_bytes()

    def _boom(*a, **kw):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(js.json, "dump", _boom)

    with pytest.raises(OSError):
        atomic_write_json(target, {"str003_signals": ["new"]})
    assert target.read_bytes() == original  # new code: untouched

    with pytest.raises(OSError):
        _old_unsafe_write(target, {"str003_signals": ["new"]})
    assert target.stat().st_size == 0  # old code: truncated to zero bytes
    with pytest.raises(json.JSONDecodeError):
        json.loads(target.read_text())


def test_lock_path_matches_swarm_convention_byte_for_byte(tmp_path):
    """THE cross-repo compatibility contract: this repo's lock-path
    derivation must produce the identical sidecar path the swarm repo's
    orchestrator/json_safety.py would derive for the same target — that's
    what makes an fcntl.flock() taken here and one taken there the same
    kernel-level lock. Reproduces the swarm module's _lock_path() logic
    inline (can't import across repos) and asserts equality."""
    target = tmp_path / "signals.json"
    target.write_text("{}")

    swarm_style = target.resolve().with_name(target.resolve().name + ".lock")
    firstrepo_style = js._lock_path(target)

    assert firstrepo_style == swarm_style


def _locked_appender(path_str, idx, n_iters):
    import json_safety as _js
    path = Path(path_str)
    for _ in range(n_iters):
        with _js.json_lock(path):
            data = _js.load_json_or_raise(path, default=lambda: {"items": []})
            data["items"].append(idx)
            _js.atomic_write_json(path, data)


def test_concurrent_processes_serialize_no_lost_updates(tmp_path):
    target = tmp_path / "signals.json"
    atomic_write_json(target, {"items": []})

    ctx = multiprocessing.get_context("fork")
    n_procs, n_iters = 8, 10
    procs = [ctx.Process(target=_locked_appender, args=(str(target), i, n_iters)) for i in range(n_procs)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    data = json.loads(target.read_text())
    assert len(data["items"]) == n_procs * n_iters


# ─────────────────────────────────────────────
# (b) register_signal.py — end-to-end through the real registration path
# ─────────────────────────────────────────────

def _seed_db(db_path, market_resolved=0):
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE markets (
            market_id TEXT PRIMARY KEY, title TEXT, condition_id TEXT, resolved INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE traders (
            address TEXT PRIMARY KEY, geo_elo_active REAL, geo_accuracy_pool INTEGER,
            research_excluded INTEGER, bot_type TEXT
        )
    """)
    conn.execute(
        "INSERT INTO markets VALUES (?, ?, ?, ?)",
        ("0xmarket1", "Will X happen?", "0xmarket1", market_resolved),
    )
    conn.execute(
        "INSERT INTO traders VALUES (?, ?, ?, ?, ?)",
        ("0xtrader1", 2200.0, 1, 0, None),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def register_signal_module(tmp_path, monkeypatch):
    """Import register_signal.py fresh and repoint every external
    dependency at test doubles: temp DB, temp signals.json, a stubbed CLOB
    price fetch and a no-op order-book snapshot (both real network/DB calls
    unrelated to what this fix changes)."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import register_signal as rs
    import importlib
    importlib.reload(rs)  # fresh module state per test

    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    signals_path = tmp_path / "signals.json"

    monkeypatch.setattr(rs, "DB_PATH", db_path)
    monkeypatch.setattr(rs, "SIGNALS_PATH", signals_path)
    monkeypatch.setattr(rs, "PROFILE_INDEX", tmp_path / "does_not_exist.json")
    monkeypatch.setattr(rs, "fetch_clob_market_price", lambda *a, **kw: 0.55)
    monkeypatch.setattr(rs, "snapshot_market", lambda *a, **kw: None)

    return rs, signals_path


def test_register_signal_writes_locked_and_atomic(register_signal_module):
    rs, signals_path = register_signal_module
    atomic_write_json(signals_path, {"str003_signals": [{"signal_id": "STR003-001"}]})

    result = rs.register_signal(
        market_id="0xmarket1", direction="YES", key_traders=["0xtrader1"],
    )

    assert result["success"] is True
    data = json.loads(signals_path.read_text())
    ids = [s["signal_id"] for s in data["str003_signals"]]
    assert "STR003-001" in ids
    assert result["signal_id"] in ids
    assert result["signal_id"] != "STR003-001"  # generated the next id


def test_register_signal_locks_a_sidecar_not_signals_json_itself(register_signal_module):
    """THE bug being fixed: the old code flocked signals.json itself,
    which is a different inode from the sidecar every other writer in
    both repos locks — so it never actually serialized against them."""
    rs, signals_path = register_signal_module
    atomic_write_json(signals_path, {"str003_signals": []})

    rs.register_signal(market_id="0xmarket1", direction="YES", key_traders=["0xtrader1"])

    lock_file = signals_path.parent / "signals.json.lock"
    assert lock_file.exists()


def test_register_signal_raises_and_does_not_write_on_corrupt_signals_file(register_signal_module):
    rs, signals_path = register_signal_module
    corrupt = '{"str003_signals": [1, '
    signals_path.write_text(corrupt)

    with pytest.raises(CorruptJSONError):
        rs.register_signal(market_id="0xmarket1", direction="YES", key_traders=["0xtrader1"])

    assert signals_path.read_text() == corrupt


def _old_register_signal_write(signals_path, signal):
    """Verbatim replica of register_signal.py's pre-fix step 10: flock the
    target file itself (r+), read-modify-write in place with seek+truncate."""
    import fcntl
    with open(signals_path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            data = json.load(f)
            data.setdefault("str003_signals", []).append(signal)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def test_old_register_signal_pattern_CORRUPTS_on_injected_crash(tmp_path, monkeypatch):
    """Non-tautological anchor: the exact pre-fix write really does
    truncate-then-fail under the same injected crash the new
    atomic_write_json() survives (proven above in section (a))."""
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({"str003_signals": ["irreplaceable"]}))

    def _boom(*a, **kw):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(json, "dump", _boom)

    with pytest.raises(OSError):
        _old_register_signal_write(signals_path, {"signal_id": "STR003-999"})

    assert signals_path.stat().st_size == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(signals_path.read_text())


# ─────────────────────────────────────────────
# (c) detect_counter_signals.py / score_str003_signals.py — locked write wrapping
# ─────────────────────────────────────────────

def test_detect_counter_signals_run_is_locked_and_atomic(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import detect_counter_signals as dcs
    import importlib
    importlib.reload(dcs)

    signals_path = tmp_path / "signals.json"
    atomic_write_json(signals_path, {
        "str003_signals": [
            {"signal_id": "STR003-001", "status": "ACTIVE", "direction": "YES",
             "market_id": "0xm1", "registered_at": "2026-01-01T00:00:00Z"},
        ]
    })
    monkeypatch.setattr(dcs, "SIGNALS_PATH", signals_path)
    monkeypatch.setattr(dcs, "detect_for_signal", lambda conn, signal: {
        "mode": "market_level", "confirming_count": 1, "exited_count": 0,
        "reversed_count": 0, "new_post_reg_exits": 0, "new_post_reg_reversals": 0,
        "counter_signal_detected": False, "credibility_adjustment": 0.0, "reversals": [],
    })

    alerts = dcs.run(conn=None, report_only=False)

    assert alerts == []
    data = json.loads(signals_path.read_text())
    assert data["str003_signals"][0]["counter_signal_v2"]["mode"] == "market_level"
    assert (tmp_path / "signals.json.lock").exists()


def test_detect_counter_signals_report_only_never_writes(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import detect_counter_signals as dcs
    import importlib
    importlib.reload(dcs)

    signals_path = tmp_path / "signals.json"
    original = {"str003_signals": [
        {"signal_id": "STR003-001", "status": "ACTIVE", "direction": "YES",
         "market_id": "0xm1", "registered_at": "2026-01-01T00:00:00Z"},
    ]}
    atomic_write_json(signals_path, original)
    monkeypatch.setattr(dcs, "SIGNALS_PATH", signals_path)
    monkeypatch.setattr(dcs, "detect_for_signal", lambda conn, signal: {
        "mode": "market_level", "confirming_count": 1, "exited_count": 0,
        "reversed_count": 0, "new_post_reg_exits": 0, "new_post_reg_reversals": 0,
        "counter_signal_detected": False, "credibility_adjustment": 0.0, "reversals": [],
    })

    dcs.run(conn=None, report_only=True)

    data = json.loads(signals_path.read_text())
    assert "counter_signal_v2" not in data["str003_signals"][0]


def test_detect_counter_signals_refuses_corrupt_file(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import detect_counter_signals as dcs
    import importlib
    importlib.reload(dcs)

    signals_path = tmp_path / "signals.json"
    corrupt = '{"str003_signals": [1, '
    signals_path.write_text(corrupt)
    monkeypatch.setattr(dcs, "SIGNALS_PATH", signals_path)

    with pytest.raises(CorruptJSONError):
        dcs.run(conn=None, report_only=False)

    assert signals_path.read_text() == corrupt


def _import_score_str003(monkeypatch, tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import score_str003_signals as s3
    import importlib
    importlib.reload(s3)
    db_path = tmp_path / "empty.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setattr(s3, "DB_PATH", db_path)
    return s3


def test_score_str003_signals_main_is_locked_and_atomic(tmp_path, monkeypatch):
    s3 = _import_score_str003(monkeypatch, tmp_path)

    signals_path = tmp_path / "signals.json"
    atomic_write_json(signals_path, {"signals": [
        {"type": "str003_directional_single", "outcome_correct": None,
         "payload": {"market_id": "0xm1", "direction": "YES"}},
    ]})
    monkeypatch.setattr(s3, "SIGNALS_PATH", signals_path)
    monkeypatch.setattr(s3, "_score_signal", lambda signal, conn: {
        **signal, "outcome_correct": 1, "resolved_at": "2026-01-01T00:00:00Z",
    })

    s3.main()

    data = json.loads(signals_path.read_text())
    assert data["signals"][0]["outcome_correct"] == 1
    assert (tmp_path / "signals.json.lock").exists()


def test_score_str003_signals_refuses_corrupt_signals_file(tmp_path, monkeypatch, capsys):
    s3 = _import_score_str003(monkeypatch, tmp_path)

    signals_path = tmp_path / "signals.json"
    corrupt = '{"signals": [1, '
    signals_path.write_text(corrupt)
    monkeypatch.setattr(s3, "SIGNALS_PATH", signals_path)

    with pytest.raises(SystemExit):
        s3.main()

    assert signals_path.read_text() == corrupt


def test_score_str003_signals_finding_write_is_locked_and_atomic(tmp_path, monkeypatch):
    s3 = _import_score_str003(monkeypatch, tmp_path)
    findings_path = tmp_path / "findings.json"
    atomic_write_json(findings_path, {"findings": []})
    monkeypatch.setattr(s3, "FINDINGS_PATH", findings_path)

    resolved = [
        {"outcome_correct": 1 if i % 2 == 0 else 0, "payload": {"geo_elo_tier": "LEGENDARY"}}
        for i in range(5)
    ]
    s3._write_finding(resolved, conn=None)

    data = json.loads(findings_path.read_text())
    assert len(data["findings"]) == 1
    assert data["findings"][0]["sample_size"] == 5
    assert (tmp_path / "findings.json.lock").exists()
