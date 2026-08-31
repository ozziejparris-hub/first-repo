#!/usr/bin/env python3
"""
tests/test_relevance_prefilter.py

Unit tests for monitoring/relevance_prefilter.py — the deterministic EXCLUSION
pre-filter, stage 1 of the geo/elections relevance classifier cascade.

Design : brain/decisions/2026-08-31-relevance-classifier-design.md (e601648)
         §1.2, §1.3, §2.4
Record : brain/decisions/2026-08-31-prefilter-implementation.md

Covers, per the implementation-task requirements:
  T1  the four documented substring-trap cases EXCLUDE:
        "Warsaw" temperature, "Warriors" spread, "Presidents Cup" (golf),
        "China Grand Prix" (F1)
  T2  the four documented true-positives are RESIDUAL:
        paris-mayoral-election-runoff, sachsen-anhalt-parliamentary,
        usisrael-strikes-iran, NY-10 House
  T3  every documented template family EXCLUDEs a representative title
  T4  a spread of documented geo/elec titles are all RESIDUAL
  T5  substring-trap guards: the EXCLUDE is attributed to the *documented*
      family, never to a bare "war"/"president"/"china" token (which the
      module does not contain)
  T6  edge cases (None / "" / whitespace / non-str) are RESIDUAL
  T7  DEMONSTRATION that the tests are non-vacuous: with EXCLUDE_PATTERNS
      emptied, the T1 cases all come back RESIDUAL (the filter is doing the
      work, not the assertions)

Run:  python3 tests/test_relevance_prefilter.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from monitoring import relevance_prefilter as rp
from monitoring.relevance_prefilter import prefilter, prefilter_family, EXCLUDE, RESIDUAL


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
        if self.failures:
            print("\n  FAILURES:")
            for n, why in self.failures:
                print(f"    - {n}: {why}")
        print(f"{'='*70}")
        return self.tests_failed == 0


# ---------------------------------------------------------------------------
# Fixtures — titles are documented in the cited decision docs / the task prompt.
# ---------------------------------------------------------------------------

# T1: the four required-EXCLUDE substring-trap cases (implementation-task prompt).
TRAP_EXCLUDE = [
    ("Will the highest temperature in Warsaw be 23°C on May 26?", "weather"),
    ("Spread: Warriors (-3.5)",                                   "sports_line"),
    ("Will Sam Burns score the most points at the Presidents Cup?", "sports_league"),
    ("Will Liam Lawson win the 2025 China Grand Prix?",           "sports_league"),
]

# T2: the four required-RESIDUAL documented true-positives
# (2026-08-31-relevance-classifier-design.md §1.2; ce35996 / ingest-defect doc).
TRUE_POSITIVES_RESIDUAL = [
    "Will the Emmanuel Grégoire List win the most citywide list votes in the "
    "runoff of the 2026 Paris municipal election by 5–10%?",              # paris-mayoral-election-runoff
    "Will Grüne win at least 7% of all valid second votes?",             # sachsen-anhalt-parliamentary
    "Will US or Israel strike Iran by January 11, 2026?",                # usisrael-strikes-iran
    "Will the Democratic Party candidate win the 2026 NY-10 House election?",  # ny-10-house-margin-of-victory
]

# T3: one representative documented title per EXCLUDE family.
FAMILY_EXCLUDE = [
    ("crypto_updown",      "Bitcoin Up or Down - May 23, 7:50AM-7:55AM ET"),
    ("crypto_price_level", "Will the price of Ethereum be above $2,500 on March 17?"),
    ("weather",            "Will the lowest temperature in Shanghai be 17°C on May 12?"),
    ("sports_line",        "Niagara Purple Eagles vs. Howard Bison: O/U 145.5"),
    ("sports_line",        "Games Total: O/U 2.5"),
    ("sports_prop",        "Kel'el Ware: Rebounds O/U 6.5"),
    ("sports_prop",        "Julio César Enciso: 1+ goals"),
    ("sports_match_date",  "Will CD Palestino win on 2026-05-26?"),
    ("sports_set_map",     "Set 1 Winner: Eala vs Zheng"),
    ("sports_set_map",     "Set Handicap: Tien (-1.5) vs Basavareddy (+1.5)"),
    ("esports",            "LoL: Lodis vs Forsaken (BO1) - Rift Legends Group Stage"),
    ("esports",            "Counter-Strike: Team Nemesis vs CYBERSHOKE Esports (BO3) - NODWIN Clutch Series"),
    ("sports_league",      "NBA: Will the Mavericks beat the Grizzlies by more than 5.5 points in their December 4 matchup?"),
    ("sports_league",      "Will Armenia win Eurovision 2026?"),
    ("stocks",             "Will Micron Technology, Inc. (MU) hit (LOW) $960 Week of June 29 2026?"),
    ("stocks",             "Will Tesla (TSLA) finish week of March 9 above $390?"),
    ("commodities",        "WTI Crude Oil (WTI) closes above $103 on May 15?"),
    ("entertainment",      "Will Timothée Chalamet be nominated for Best Actor at the 98th Academy Awards?"),
    ("entertainment",      "Will \"NEVER ENOUGH - Turnstile\" win Best Rock Album at the 68th Grammy Awards?"),
    ("novelty_religion",   "Will the second coming happen in 2026?"),
]

# T4: documented geo/elec titles that must stay RESIDUAL (not template-excluded).
GEO_ELEC_RESIDUAL = [
    "Will Anamaria Gavrilă win the Romanian presidential election?",
    "Will David Jolly be the Democratic nominee for Florida Governor?",
    "Will Russia abandon Syrian naval base before April?",
    "Will there be a US government shutdown before December 31?",
    "Odds of Russia x Ukraine ceasefire on Friday?",
    "Will Trump remove 10% blanket tariff before July?",
    "Will Steven Del Duca win the 2026 Vaughan mayoral election?",
    "Haiti elections delayed again?",
    "Israel withdraws from Lebanon by August 31, 2026?",
    "Will Trump say \"America First\" this week?",
    "US x Iran permanent peace deal by August 31, 2026?",
    "Will Delyan Peevski win the next Bulgarian presidential election?",
]


def t1_traps_exclude(r):
    print("\n--- T1: documented substring-trap cases must EXCLUDE ---")
    for title, _fam in TRAP_EXCLUDE:
        r.check(f"T1 EXCLUDE: {title[:55]!r}", prefilter(title) == EXCLUDE,
                f"got {prefilter(title)}")


def t2_true_positives_residual(r):
    print("\n--- T2: documented geo/elec true-positives must be RESIDUAL ---")
    for title in TRUE_POSITIVES_RESIDUAL:
        r.check(f"T2 RESIDUAL: {title[:55]!r}", prefilter(title) == RESIDUAL,
                f"got {prefilter(title)} (family={prefilter_family(title)})")


def t3_families_exclude(r):
    print("\n--- T3: every documented template family EXCLUDEs a representative title ---")
    for expected_family, title in FAMILY_EXCLUDE:
        got = prefilter(title)
        fam = prefilter_family(title)
        r.check(f"T3 EXCLUDE [{expected_family}]: {title[:48]!r}", got == EXCLUDE,
                f"got {got}, family={fam}")


def t4_geo_elec_residual(r):
    print("\n--- T4: a spread of documented geo/elec titles must all be RESIDUAL ---")
    for title in GEO_ELEC_RESIDUAL:
        r.check(f"T4 RESIDUAL: {title[:55]!r}", prefilter(title) == RESIDUAL,
                f"got {prefilter(title)} (family={prefilter_family(title)})")


def t5_trap_attribution(r):
    print("\n--- T5: trap EXCLUDEs are attributed to the documented family, "
          "not a bare war/president/china token ---")
    for title, expected_family in TRAP_EXCLUDE:
        fam = prefilter_family(title)
        r.check(f"T5 family: {title[:48]!r} -> {expected_family}", fam == expected_family,
                f"got family={fam}")
    # the module carries no such single-word token at all
    src = (REPO_ROOT / "monitoring" / "relevance_prefilter.py").read_text()
    for banned in ("r\"war\"", "'war'", "r\"president\"", "'president'",
                   "r\"china\"", "'china'"):
        r.check(f"T5 no bare token literal {banned}", banned not in src,
                f"found {banned} as a pattern literal")


def t6_edge_cases(r):
    print("\n--- T6: None / empty / whitespace / non-str titles are RESIDUAL ---")
    for val in (None, "", "   ", "\t\n", 12345, ["not", "a", "string"], object()):
        r.check(f"T6 RESIDUAL for {val!r:.40}", prefilter(val) == RESIDUAL,
                f"got {prefilter(val)}")


def t7_non_vacuous(r):
    print("\n--- T7: DEMONSTRATION — with EXCLUDE_PATTERNS emptied, the T1 cases "
          "come back RESIDUAL (the filter, not the assertions, does the work) ---")
    saved = rp.EXCLUDE_PATTERNS
    try:
        rp.EXCLUDE_PATTERNS = []
        for title, _fam in TRAP_EXCLUDE:
            got = prefilter(title)
            r.check(f"T7 empty-filter RESIDUAL: {title[:45]!r}", got == RESIDUAL,
                    f"empty filter still returned {got} — test would be vacuous")
        # and a real positive is unchanged (still RESIDUAL) — sanity
        r.check("T7 empty-filter positive still RESIDUAL",
                prefilter(TRUE_POSITIVES_RESIDUAL[0]) == RESIDUAL, "unexpected")
    finally:
        rp.EXCLUDE_PATTERNS = saved
    # restored
    r.check("T7 restored: Warsaw case EXCLUDEs again",
            prefilter(TRAP_EXCLUDE[0][0]) == EXCLUDE, "restore failed")


def main():
    r = TestResults()
    t1_traps_exclude(r)
    t2_true_positives_residual(r)
    t3_families_exclude(r)
    t4_geo_elec_residual(r)
    t5_trap_attribution(r)
    t6_edge_cases(r)
    t7_non_vacuous(r)
    ok = r.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
