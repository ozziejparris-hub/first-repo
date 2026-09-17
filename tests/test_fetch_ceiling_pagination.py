#!/usr/bin/env python3
"""
tests/test_fetch_ceiling_pagination.py

Proves the fix for the ingestion fetch ceiling found in the 2026-09-17
diagnosis (trading-swarm
brain/decisions/2026-09-17-oos-hash-methodology-and-cycle-compounding.md)
and fixed 2026-09-17 (trading-swarm
brain/decisions/2026-09-17-ingestion-fetch-ceiling-fix.md).

Root cause: check_for_new_trades() took ONE snapshot of
limit=500 platform-wide trades per cycle, with no pagination and an
"after" (last_trade_timestamp) parameter confirmed IGNORED server-side
(tested directly 2026-09-17 with both ISO and unix-epoch values --
identical "most recent" results regardless). Live measurement: 500
platform trades span roughly 20-50 seconds of real activity. At the
observed 75-205 minute cycle gaps, one 500-row snapshot captured on the
order of 0.15-2% of the window -- everything else scrolled off the feed
before the next cycle could look. The fix pages backward with
`offset` (confirmed to paginate reliably, unlike `after`) at the API's
real 10,000-row cap (confirmed by direct testing; the previous 500 was
an unexamined client-side constant) until reaching last_trade_timestamp.

Section 1 reproduces the OLD single-snapshot behaviour against a
synthetic multi-page fixture with flagged-trader trades deliberately
scattered across pages 1 AND 3 -- i.e. a shape a single snapshot cannot
reach. Section 2 proves the NEW `_fetch_recent_trades_paginated()`
reaches all of them. A test where both approaches found the same trades
would prove nothing; the fixture is built specifically so they diverge.

Section 3 confirms pagination stops as soon as the cursor is covered
(not exhaustively page 1..N always) -- the mechanism that keeps a normal
cadence cheap (1-2 pages) even though a large gap can walk back many
pages. Section 4 confirms the defensive MAX_FETCH_PAGES_PER_CYCLE cap
bounds worst-case cost per cycle. Section 5 proves the 429 backoff path
in PolymarketClient.get_market_trades() actually retries and succeeds,
not just that the code exists. Section 6 confirms every page fetch goes
through asyncio.to_thread (off the event loop) -- the property that lets
pagination avoid reintroducing the starvation the cycle-wait fix
addressed.
"""

import asyncio
import inspect
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from monitoring import monitor as monitor_module
from monitoring.polymarket_client import PolymarketClient

PolymarketMonitor = monitor_module.PolymarketMonitor


class TestResults:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def ok(self, name):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"  [PASS] {name}")

    def fail(self, name, reason):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")

    def check(self, name, cond, reason=""):
        self.ok(name) if cond else self.fail(name, reason or "condition was False")

    def summary(self):
        print(f"\n{'='*70}\n  TEST SUMMARY\n{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        pct = self.tests_passed / max(1, self.tests_run) * 100
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        for name, reason in self.failures:
            print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


def _bare_monitor(last_trade_timestamp):
    """
    A PolymarketMonitor with only the attributes _fetch_recent_trades_paginated()
    touches, built via __new__ to skip __init__ (which unconditionally opens
    the production DB and constructs live network/worker objects neither
    this method nor its tests need).
    """
    m = PolymarketMonitor.__new__(PolymarketMonitor)
    m.last_trade_timestamp = last_trade_timestamp
    m.polymarket = None  # replaced per-test with a fake
    return m


def _mk_trade(ts, addr="0xother"):
    return {
        "proxyWallet": addr, "timestamp": ts, "conditionId": "0xm",
        "title": "seeded", "outcome": "Yes", "size": 10, "price": 0.5,
        "side": "BUY", "transactionHash": f"tx{ts}", "asset": "ASSET1",
    }


class _FakePaginatedFeed:
    """
    Simulates the real Data API's /trades?limit&offset behaviour: a single
    newest-first, strictly-non-increasing-by-timestamp list, sliced by
    offset/limit. Records every call for assertions.
    """
    def __init__(self, all_trades_newest_first):
        self.all_trades = all_trades_newest_first
        self.calls = []

    def get_market_trades(self, market_id=None, limit=100, offset=0, max_retries=3):
        self.calls.append({"market_id": market_id, "limit": limit, "offset": offset})
        return self.all_trades[offset:offset + limit]


def _old_single_snapshot(feed, limit=500):
    """
    Reproduction of the REMOVED old behaviour: one un-paginated call,
    limit=500, offset=0. The shipped code no longer has this shape (see
    PolymarketMonitor._fetch_recent_trades_paginated); reimplementing it
    here is the only way to demonstrate what it used to do, matching the
    convention in tests/test_backfill_market_categories_pagination.py.
    """
    return feed.get_market_trades(market_id=None, limit=limit, offset=0)


def run_tests() -> bool:
    r = TestResults()

    # ── Build a fixture: 3 pages of 500 trades each (1500 total, page_limit
    # 500 to keep the fixture small and readable), newest first. A flagged
    # trader's trades sit at the very front (page 1, easy) AND buried in
    # page 3 (position 1250) -- a single limit=500 snapshot structurally
    # cannot reach the page-3 ones no matter what "after" value is passed,
    # since "after" is confirmed ignored server-side.
    print("\n[SETUP] Building a 3-page synthetic feed with flagged trades on pages 1 and 3")
    print("-" * 50)
    base_ts = 2_000_000_000
    trades = []
    for i in range(1500):
        ts = base_ts - i  # strictly decreasing -> newest first
        if i in (5, 12):  # page 1: within the first 500
            trades.append(_mk_trade(ts, addr="0xFLAGGED"))
        elif i in (1250, 1300):  # page 3: offset 1000-1499
            trades.append(_mk_trade(ts, addr="0xFLAGGED"))
        else:
            trades.append(_mk_trade(ts, addr="0xother"))
    oldest_ts_in_fixture = base_ts - 1499

    def _flagged_count(trade_list):
        return sum(1 for t in trade_list if t.get("proxyWallet") == "0xFLAGGED")

    # ── Section 1: OLD single-snapshot behaviour misses the page-3 trades ──
    print("\n[SECTION 1] OLD single-snapshot (limit=500, no pagination)")
    print("-" * 50)

    feed1 = _FakePaginatedFeed(trades)
    old_result = _old_single_snapshot(feed1, limit=500)
    r.check("T1a  OLD fetch returns exactly 500 rows (page 1 only)",
            len(old_result) == 500, f"Got {len(old_result)}")
    r.check("T1b  OLD fetch makes exactly 1 API call",
            len(feed1.calls) == 1, f"Got {len(feed1.calls)} calls")
    r.check(
        "T1c  OLD fetch finds only the 2 flagged trades on page 1, misses "
        "the 2 on page 3 -- structurally cannot reach them regardless of "
        "any 'after'/cursor value, since that parameter is ignored server-side",
        _flagged_count(old_result) == 2,
        f"Found {_flagged_count(old_result)} flagged trades, expected 2 (of 4 total in fixture)",
    )

    # ── Section 2: NEW paginated fetch reaches all of them ──────────────────
    print("\n[SECTION 2] NEW _fetch_recent_trades_paginated() reaches all pages")
    print("-" * 50)

    feed2 = _FakePaginatedFeed(trades)
    m2 = _bare_monitor(last_trade_timestamp=None)  # cold start handled separately in Section 3
    m2.polymarket = feed2

    # Simulate a non-cold-start cursor set exactly at the fixture's oldest
    # trade, so pagination must walk all the way to (and including) page 3
    # to cover it -- but no further, since the fixture has nothing older.
    from datetime import datetime
    m2.last_trade_timestamp = datetime.fromtimestamp(oldest_ts_in_fixture)

    with patch.object(monitor_module, "FETCH_PAGE_LIMIT", 500), \
         patch.object(monitor_module, "MAX_FETCH_PAGES_PER_CYCLE", 10):
        new_result, pages = asyncio.run(m2._fetch_recent_trades_paginated())

    r.check("T2a  NEW fetch walks multiple pages to reach the cursor",
            pages == 3, f"Got {pages} pages")
    r.check("T2b  NEW fetch returns all 1500 rows across those pages",
            len(new_result) == 1500, f"Got {len(new_result)}")
    r.check(
        "T2c  NEW fetch finds all 4 flagged trades -- both page 1 and the "
        "ones buried on page 3 that a single snapshot cannot reach",
        _flagged_count(new_result) == 4,
        f"Found {_flagged_count(new_result)} flagged trades, expected 4",
    )
    r.check(
        "T2d  the differential is real: NEW found strictly more flagged "
        "trades than OLD on the identical fixture/window",
        _flagged_count(new_result) > _flagged_count(old_result),
        f"NEW={_flagged_count(new_result)} OLD={_flagged_count(old_result)} "
        "-- a test where these were equal would prove nothing",
    )

    # ── Section 3: pagination stops as soon as the cursor is covered ───────
    print("\n[SECTION 3] Pagination stops early when the cursor is covered (cheap normal case)")
    print("-" * 50)

    feed3 = _FakePaginatedFeed(trades)
    m3 = _bare_monitor(last_trade_timestamp=datetime.fromtimestamp(base_ts - 5))  # just past page 1's start
    m3.polymarket = feed3
    with patch.object(monitor_module, "FETCH_PAGE_LIMIT", 500), \
         patch.object(monitor_module, "MAX_FETCH_PAGES_PER_CYCLE", 10):
        result3, pages3 = asyncio.run(m3._fetch_recent_trades_paginated())
    r.check(
        "T3a  a cursor near the front stops pagination after 1 page -- "
        "normal-cadence cycles stay cheap, not always walking the max",
        pages3 == 1, f"Got {pages3} pages",
    )

    # ── Section 4: the defensive page cap bounds worst-case cost ───────────
    print("\n[SECTION 4] MAX_FETCH_PAGES_PER_CYCLE bounds worst-case cost")
    print("-" * 50)

    feed4 = _FakePaginatedFeed(trades)
    # Cursor far older than the fixture covers -> would need more pages than
    # the fixture even has; cap should still stop the loop, not hang or
    # exhaust memory pulling forever.
    m4 = _bare_monitor(last_trade_timestamp=datetime.fromtimestamp(0))
    m4.polymarket = feed4
    with patch.object(monitor_module, "FETCH_PAGE_LIMIT", 500), \
         patch.object(monitor_module, "MAX_FETCH_PAGES_PER_CYCLE", 2):
        result4, pages4 = asyncio.run(m4._fetch_recent_trades_paginated())
    r.check("T4a  pagination stops at the cap (2), not the 3 pages the fixture has",
            pages4 == 2, f"Got {pages4} pages")
    r.check("T4b  only the capped pages' rows are returned (1000, not 1500)",
            len(result4) == 1000, f"Got {len(result4)}")

    # ── Section 5: the 429 backoff path actually retries and succeeds ──────
    print("\n[SECTION 5] PolymarketClient.get_market_trades() 429 backoff (real retry, not just code)")
    print("-" * 50)

    call_log = []

    class _Resp:
        def __init__(self, status, payload=None):
            self.status_code = status
            self._payload = payload or []
        def json(self):
            return self._payload

    def _flaky_get(url, params=None, timeout=None):
        call_log.append(params.get("offset", 0))
        if len(call_log) <= 2:
            return _Resp(429)
        return _Resp(200, [_mk_trade(1234567890)])

    client = PolymarketClient(api_key=None)
    with patch("monitoring.polymarket_client.requests.get", side_effect=_flaky_get), \
         patch("monitoring.polymarket_client.time.sleep") as mock_sleep:
        t0 = time.monotonic()
        result5 = client.get_market_trades(market_id=None, limit=10, offset=0, max_retries=3)
        elapsed5 = time.monotonic() - t0

    r.check(
        "T5a  get_market_trades() retries past two 429s and returns the "
        "eventual 200's data, not an empty list",
        len(result5) == 1,
        f"Got {result5}",
    )
    r.check("T5b  exactly 3 attempts were made (2 failures + 1 success)",
            len(call_log) == 3, f"Got {len(call_log)} attempts")
    r.check(
        "T5c  backoff actually sleeps between retries (mocked, but called "
        "with increasing wait -- 1s then 2s) rather than retrying instantly",
        mock_sleep.call_args_list == [((1,),), ((2,),)],
        f"Got sleep calls: {mock_sleep.call_args_list}",
    )
    r.check("T5d  test ran fast (sleep mocked) despite exercising the real backoff code path",
            elapsed5 < 1.0, f"elapsed={elapsed5:.3f}s")

    # 429 that never clears: give up cleanly with [], not raise or hang.
    def _always_429(url, params=None, timeout=None):
        return _Resp(429)
    with patch("monitoring.polymarket_client.requests.get", side_effect=_always_429), \
         patch("monitoring.polymarket_client.time.sleep"):
        result5b = client.get_market_trades(market_id=None, limit=10, offset=0, max_retries=3)
    r.check("T5e  sustained 429 gives up cleanly and returns [] (fail-soft, not raise/hang)",
            result5b == [], f"Got {result5b}")

    # ── Section 6: every page fetch is off the event loop ───────────────────
    print("\n[SECTION 6] Pagination cannot reintroduce starvation -- every call is asyncio.to_thread")
    print("-" * 50)

    # Strip the docstring first (same reasoning as
    # test_monitoring_loop_wait_shutdown.py Section 1: it quotes code shapes
    # in prose, which must not produce a false positive/negative here).
    src_full = inspect.getsource(PolymarketMonitor._fetch_recent_trades_paginated)
    first_quote = src_full.index('"""')
    second_quote = src_full.index('"""', first_quote + 3) + 3
    src = src_full[second_quote:]

    r.check(
        "T6a  the page-fetch call site uses asyncio.to_thread (moved off "
        "the event loop), matching the existing pattern used elsewhere in "
        "this file for blocking calls",
        "await asyncio.to_thread(" in src,
        "page fetch is not wrapped in asyncio.to_thread",
    )
    r.check(
        "T6b  no direct (un-awaited-to-thread) call to "
        "self.polymarket.get_market_trades(...) remains in this method -- "
        "it's only ever passed BY REFERENCE (no trailing parens) as the "
        "function argument to asyncio.to_thread",
        "self.polymarket.get_market_trades(" not in src,
        "a direct blocking call to get_market_trades is present",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
