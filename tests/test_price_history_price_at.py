#!/usr/bin/env python3
"""
tests/test_price_history_price_at.py

Proves monitoring/price_history.py::price_at() at its edges (B1b-prices,
2026-07-23 scoping + build). Network is mocked throughout via
patch.object(price_history, 'fetch_price_history_window', ...) -- these
tests never make a real CLOB call.

Non-tautological by design: T1/T1b and T2/T2b each pair the correct
behavior with a small inline "naive" implementation that a plausible bug
would produce, and assert the naive version gives the WRONG answer on the
same mocked data. If price_at() were rewritten to match either naive
version, these tests would catch it.

T1   No point at or before T -> None (not the nearest point regardless of
     side -- a naive nearest-point implementation would wrongly return a
     future point).
T1b  The naive nearest-point implementation is shown to disagree with
     price_at() on the same data (proves T1 is discriminating, not
     tautological).
T2   A stale point (found within the lookback window, but hours before T)
     is returned WITH staleness_hours populated -- not silently dropped.
T2b  A naive silently-drops-stale implementation is shown to disagree with
     price_at() on the same data (proves T2 is discriminating).
T3   lookback_hours exceeding the flat 15-day CLOB interval cap raises
     PriceAtError rather than silently querying (and 400ing) or clamping
     unnoticed.
T4   token_id=None (or any request that yields no data) returns None, not
     an exception.
T5   resolve_token_id() takes the DB shortcut (clob_token_id_yes already
     populated) without making any network call.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import monitoring.price_history as ph


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
        print(f"\n{'='*70}")
        print(f"  TEST SUMMARY")
        print(f"{'='*70}")
        print(f"  Tests run    : {self.tests_run}")
        pct = self.tests_passed / max(1, self.tests_run) * 100
        print(f"  Passed       : {self.tests_passed}  ({pct:.0f}%)")
        print(f"  Failed       : {self.tests_failed}")
        if self.failures:
            print(f"\n  FAILURES:")
            for name, reason in self.failures:
                print(f"    - {name}: {reason}")
        print(f"{'='*70}")
        return self.tests_failed == 0


def naive_nearest_point_price_at(points, T):
    """A plausible bug: pick whichever point is closest in absolute time,
    regardless of whether it's before or after T. Used only to prove T1 is
    discriminating -- never imported by production code."""
    if not points:
        return None
    T_epoch = int(T.timestamp())
    closest = min(points, key=lambda p: abs(p[0] - T_epoch))
    return closest[1]


def naive_drops_stale_price_at(points, T, staleness_cap_hours=6.0):
    """A plausible bug: silently return None if the last point before T is
    stale, instead of surfacing staleness for the caller to decide. Used
    only to prove T2 is discriminating -- never imported by production code."""
    if not points:
        return None
    T_epoch = int(T.timestamp())
    at_or_before = [p for p in points if p[0] <= T_epoch]
    if not at_or_before:
        return None
    point_ts, price = at_or_before[-1]
    staleness_hours = (T_epoch - point_ts) / 3600.0
    if staleness_hours > staleness_cap_hours:
        return None  # the bug: silently drops instead of surfacing
    return price


def run_tests() -> bool:
    r = TestResults()
    T = datetime(2025, 12, 15, 12, 0, 0, tzinfo=timezone.utc)

    print("\n[SECTION] T1/T1b -- no point at or before T")
    print("-" * 50)
    # All mocked points are AFTER T -- the market's curve hadn't started
    # (or CLOB's window only has post-T data). Correct answer: None.
    points_all_after = [
        (int((T + timedelta(hours=1)).timestamp()), 0.5),
        (int((T + timedelta(hours=2)).timestamp()), 0.6),
    ]
    with patch.object(ph, 'fetch_price_history_window', return_value=(points_all_after, None)):
        result = ph.price_at('tok', T, lookback_hours=6)
    r.check(
        "T1  no point at-or-before T returns None (not the nearest point)",
        result is None,
        f"Expected None, got {result!r}",
    )
    naive_result = naive_nearest_point_price_at(points_all_after, T)
    r.check(
        "T1b naive nearest-point implementation disagrees on the same data "
        "(proves T1 is discriminating, not tautological)",
        naive_result is not None and naive_result != result,
        f"Expected naive to wrongly return a price (got {naive_result!r}), "
        f"disagreeing with the correct None",
    )

    print("\n[SECTION] T2/T2b -- stale point surfaced, not dropped")
    print("-" * 50)
    # One point 10 hours before T, within the (wide) lookback window but
    # past the FABLE 6h staleness cap. Correct answer: returned, with
    # staleness_hours ~10, not None.
    stale_point_ts = int((T - timedelta(hours=10)).timestamp())
    points_stale = [(stale_point_ts, 0.42)]
    with patch.object(ph, 'fetch_price_history_window', return_value=(points_stale, None)):
        result = ph.price_at('tok', T, lookback_hours=24)
    r.check(
        "T2  stale point (10h old) is returned, not silently dropped to None",
        result is not None,
        f"Expected a (price, point_ts, staleness_hours) tuple, got None",
    )
    if result is not None:
        price, point_ts, staleness_hours = result
        r.check(
            "T2  staleness_hours is populated and reflects the true 10h gap",
            abs(staleness_hours - 10.0) < 0.01,
            f"Expected staleness_hours ~10.0, got {staleness_hours}",
        )
        r.check(
            "T2  price is the actual stale value (0.42), not a fabricated fill",
            price == 0.42,
            f"Expected price 0.42, got {price}",
        )
    naive_result = naive_drops_stale_price_at(points_stale, T)
    r.check(
        "T2b naive silently-drops-stale implementation disagrees on the same "
        "data (proves T2 is discriminating, not tautological)",
        naive_result is None and result is not None,
        f"Expected naive to wrongly return None (stale-drop bug), "
        f"disagreeing with the correct surfaced price",
    )

    print("\n[SECTION] T3 -- flat 15-day interval cap")
    print("-" * 50)
    raised = False
    try:
        ph.price_at('tok', T, lookback_hours=(ph.MAX_INTERVAL_DAYS * 24) + 1)
    except ph.PriceAtError:
        raised = True
    r.check(
        "T3  lookback_hours beyond the flat 15-day cap raises PriceAtError "
        "(loud failure, not a silent 400 or a silent clamp)",
        raised,
        "Expected PriceAtError to be raised",
    )
    # Exactly at the cap boundary must NOT raise (only exceeding it should).
    with patch.object(ph, 'fetch_price_history_window', return_value=([], None)):
        try:
            ph.price_at('tok', T, lookback_hours=ph.MAX_INTERVAL_DAYS * 24)
            at_boundary_ok = True
        except ph.PriceAtError:
            at_boundary_ok = False
    r.check(
        "T3b lookback_hours exactly at the 15-day cap does not raise",
        at_boundary_ok,
        "Expected no exception at the boundary itself",
    )

    print("\n[SECTION] T4 -- no data / no token never raises")
    print("-" * 50)
    with patch.object(ph, 'fetch_price_history_window', return_value=(None, 'no-response')):
        try:
            result = ph.price_at(None, T, lookback_hours=6)
            no_exception = True
        except Exception as e:
            no_exception = False
            result = None
            exc = e
    r.check(
        "T4  token_id=None / no-data response returns None cleanly, no exception",
        no_exception and result is None,
        f"Expected None with no exception, got exception" if not no_exception else f"Expected None, got {result!r}",
    )

    print("\n[SECTION] T5 -- resolve_token_id DB shortcut makes no network call")
    print("-" * 50)
    market = {'clob_token_id_yes': 'already_known_token', 'condition_id': None, 'market_id': None}
    with patch.object(ph, 'http_get') as mock_http:
        token_id, source, note = ph.resolve_token_id(market)
    r.check(
        "T5  DB shortcut returns the stored token without calling http_get",
        token_id == 'already_known_token' and source == 'db' and not mock_http.called,
        f"Expected ('already_known_token', 'db', None) with 0 http_get calls, "
        f"got ({token_id!r}, {source!r}, {note!r}), http_get.called={mock_http.called}",
    )

    return r.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
