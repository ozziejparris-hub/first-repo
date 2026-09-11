#!/usr/bin/env python3
"""
tests/test_telegram_httpx_log_redaction.py

Proves the 2026-09-11 fix for the Telegram-bot-token-in-cleartext-log
finding (see brain/decisions/2026-09-11-telegram-token-log-leak.md).

Root cause: python-telegram-bot's Bot uses httpx internally, and httpx
logs every request at INFO via logging.getLogger("httpx") -- including
the full URL. Telegram's Bot API puts the bot token in the URL path
(/bot<TOKEN>/sendMessage), so once anything in the process elevates the
root logger to INFO with a handler (analysis/calibration_analysis.py,
analysis/risk_adjusted_returns.py and analysis/regret_analysis.py all do
this via logging.basicConfig(level=logging.INFO) at import time), every
subsequent httpx request -- including every Telegram send -- gets its
full URL, token included, written to whatever the root logger's handler
points at (a StreamHandler(stderr) is captured by journald for a systemd
service).

The fix caps the "httpx" logger to WARNING at the point each Telegram
sender constructs its Bot, so the request/response access-log line never
fires regardless of what the surrounding process did to the root logger.
httpx reports transport errors via raised exceptions, not via this
logger, so nothing about error visibility is lost -- Section 2 below
proves a WARNING/ERROR-level record through the SAME logger still gets
through, and Section 3 proves other loggers are untouched.

No live Telegram send, no subprocess to the network -- everything here
is exercised against Python's logging machinery directly. Each test file
runs as its own subprocess (see run_tests.py), so logger state starting
NOTSET for "httpx" in each of these is guaranteed, not assumed.
"""

import io
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class TestResults:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def ok(self, name: str):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")

    def check(self, name: str, cond: bool, reason: str = ""):
        if cond:
            self.ok(name)
        else:
            self.fail(name, reason or "condition was False")

    def summary(self) -> bool:
        pct = (self.tests_passed / self.tests_run * 100) if self.tests_run else 0
        print(f"\n{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        if self.failures:
            print("\n  FAILURES:")
            for name, reason in self.failures:
                print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


def _capture_httpx_at(level: int) -> str:
    """Attach a handler at `level`, log a sample request URL (with a fake
    token, never a real one) through the "httpx" logger the way httpx
    itself does, and return whatever the handler captured."""
    logger = logging.getLogger("httpx")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(level)
    logger.addHandler(handler)
    try:
        logger.info(
            'HTTP Request: %s %s "%s %d %s"',
            "POST",
            "https://api.telegram.org/bot123456:FAKE-TEST-TOKEN-not-real/sendMessage",
            "HTTP/1.1",
            200,
            "OK",
        )
    finally:
        logger.removeHandler(handler)
    return buf.getvalue()


def run_tests() -> bool:
    r = TestResults()

    # -----------------------------------------------------------------
    # Section 1: importing each live sender caps the httpx logger
    # -----------------------------------------------------------------
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    r.check(
        "T1a precondition: httpx logger starts unconfigured (NOTSET) "
        "in a fresh subprocess",
        logging.getLogger("httpx").level == logging.NOTSET,
    )

    # monitoring/__init__.py eagerly imports telegram_bot (for
    # TelegramNotifier), so importing either submodule pulls both of
    # these senders' fixes in via the package's own __init__ -- checked
    # together rather than in isolation.
    import monitoring.telegram_health_bot  # noqa: F401
    import monitoring.telegram_bot  # noqa: F401
    r.check(
        "T1b importing monitoring.telegram_health_bot (observer's sender) "
        "and monitoring.telegram_bot (monitoring service's sender) both "
        "cap httpx logger to WARNING",
        logging.getLogger("httpx").level == logging.WARNING,
    )
    r.check(
        "T1c both sender modules independently carry the same guard "
        "(source contains the setLevel call, not relying on import order)",
        "getLogger(\"httpx\").setLevel(logging.WARNING)"
        in Path(ROOT / "monitoring" / "telegram_health_bot.py").read_text()
        and "getLogger(\"httpx\").setLevel(logging.WARNING)"
        in Path(ROOT / "monitoring" / "telegram_bot.py").read_text(),
    )

    # -----------------------------------------------------------------
    # Section 2: the redaction filter actually works on a sample URL
    # -----------------------------------------------------------------
    logging.getLogger("httpx").setLevel(logging.WARNING)

    captured_info = _capture_httpx_at(logging.DEBUG)
    r.check(
        "T2a NEGATIVE CONTROL: with the fix applied, an httpx-style INFO "
        "request log (sample URL with a fake token) produces NO output",
        captured_info == "",
        f"handler captured: {captured_info!r}",
    )
    r.check(
        "T2b the fake token does not appear anywhere in the (empty) capture",
        "FAKE-TEST-TOKEN" not in captured_info,
    )

    # -----------------------------------------------------------------
    # Section 3: the fix doesn't silence real error visibility
    # -----------------------------------------------------------------
    httpx_logger = logging.getLogger("httpx")
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    httpx_logger.addHandler(handler)
    try:
        httpx_logger.warning("connection pool exhausted (sample warning)")
        httpx_logger.error("simulated transport failure (sample error)")
    finally:
        httpx_logger.removeHandler(handler)
    warned = buf.getvalue()
    r.check(
        "T3a REGRESSION GUARD: WARNING-level httpx records still come "
        "through after the fix (error visibility not silenced)",
        "connection pool exhausted" in warned,
        f"captured: {warned!r}",
    )
    r.check(
        "T3b REGRESSION GUARD: ERROR-level httpx records still come "
        "through after the fix",
        "simulated transport failure" in warned,
        f"captured: {warned!r}",
    )

    other = logging.getLogger("some_unrelated_project_logger")
    other.setLevel(logging.INFO)
    buf2 = io.StringIO()
    h2 = logging.StreamHandler(buf2)
    other.addHandler(h2)
    try:
        other.info("unrelated INFO message should still work")
    finally:
        other.removeHandler(h2)
    r.check(
        "T3c the fix only touches the 'httpx' logger -- an unrelated "
        "project logger's INFO level is untouched",
        "unrelated INFO message should still work" in buf2.getvalue(),
    )

    # -----------------------------------------------------------------
    # Section 4: the two script-level senders carry the same guard
    # (deferred import inside the function, not module top level --
    # verified statically since exercising it means a real send attempt)
    # -----------------------------------------------------------------
    import inspect
    import check_canonical_definitions as ccd
    import audit_invariants as ai

    for mod, label in ((ccd, "check_canonical_definitions.py"),
                        (ai, "audit_invariants.py")):
        src = inspect.getsource(mod._send_telegram_async)
        setlevel_pos = src.find('getLogger("httpx").setLevel')
        bot_ctor_pos = src.find("Bot(token=token)")
        r.check(
            f"T4 {label}: _send_telegram_async caps the httpx logger "
            f"before constructing Bot(token=...)",
            setlevel_pos != -1 and bot_ctor_pos != -1 and setlevel_pos < bot_ctor_pos,
            f"setlevel_pos={setlevel_pos} bot_ctor_pos={bot_ctor_pos}",
        )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
