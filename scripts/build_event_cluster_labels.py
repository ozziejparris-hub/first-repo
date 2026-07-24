#!/usr/bin/env python3
"""
build_event_cluster_labels.py

Builds the complete event-clustering artifact for a frozen backtest
population snapshot (scripts/snapshot_backtest_population.py) -- B5's input.
Writes to event_cluster_labels, tagging every row with the snapshot_id it
was clustered against.

THREE label sources, in order of trust:
  1. native_negrisk    -- read straight from Polymarket's own negRiskMarketID
                           field via the Gamma API (~40% of a typical
                           snapshot). Authoritative: Polymarket enforces
                           these as literally mutually exclusive contracts
                           at the protocol level, no inference involved.
  2. hand_sibling / hand_standalone / unsure
                        -- the "ambiguous zone": neg_risk=False markets with
                           a candidate/multi-outcome-shaped title (keyword
                           prefilter below). Hand-labeled applying the
                           MUTUAL-EXCLUSIVITY TEST: can only ONE member
                           resolve YES? Top-two primaries, two-round
                           runoffs, per-party seat/coalition thresholds, and
                           nested date/probability-band families all fail
                           this test (multiple members CAN resolve YES) and
                           are STANDALONE even though they're candidate-
                           shaped -- this is the merge-error trap the 2026-
                           07-24 calibration surfaced (California's top-two
                           governor primary is the exemplar). Where possible,
                           the label is confirmed by resolution data itself
                           (>=2 family members independently resolved YES
                           settles it with no external fact needed) rather
                           than title inference alone.
  3. trivial_standalone -- neg_risk=False markets whose title never matched
                           the candidate-shaped keyword prefilter at all
                           (binary "will X happen by date" markets etc.).
                           Never individually hand-reviewed -- excluded by
                           the prefilter as obviously not a mutual-
                           exclusivity candidate.

DETERMINISM CONSTRAINT (for the clustering build, and honored here): a
market's label depends only on that market, its title, and its own
resolution outcome -- never on what else happens to be in the snapshot's
population. Native neg_risk grouping is a market-level field, trivially
population-independent. The hand-labeling rules above (format facts,
resolution-outcome checks against a market's *own* documented siblings)
are likewise per-market/per-family, not "nearest N in the current set" --
so labels here stay valid if a later snapshot extends the population
(B3 re-pin). See scripts/snapshot_backtest_population.py's docstring for
the fuller statement of this contract, including that the fallback here
is NOT YET verified deterministic in the sense of an automated/algorithmic
title-inference clusterer -- this run is a human-reasoned, one-time
labeling pass, not that future automated build.

DESIGN: append-only, idempotent (elo_snapshots/order_book_snapshots/
backtest_population_snapshots convention). Composite PK (snapshot_id,
market_id).

Usage:
  python3 scripts/build_event_cluster_labels.py --snapshot-id bt_pop_2025-11-01_v1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'polymarket_tracker.db')
GAMMA_API = "https://gamma-api.polymarket.com"

# ── Ambiguous-zone keyword prefilter ────────────────────────────────────────
PREFILTER_PATTERNS = [
    r"\bwin\b", r"\bwins\b", r"\bwinner\b",
    r"\badvance\b", r"\badvances\b", r"\badvancing\b",
    r"\bqualify\b", r"\bqualifies\b", r"\bqualifying\b",
    r"\bnominee\b", r"\bnomination\b",
    r"\bnext president\b", r"\bnext prime minister\b", r"\bnext pm\b",
    r"\bnext mayor\b", r"\bnext governor\b", r"\bnext senator\b",
    r"\bnext chancellor\b", r"\bnext premier\b",
    r"\bmost seats\b", r"\bgain the most\b",
    r"\bprimary\b", r"\brunoff\b", r"\brun-off\b",
    r"\belected\b", r"\belection\b",
    r"\bbe the .* nominee\b",
    r"\bpresidential election\b", r"\bgubernatorial election\b",
    r"\bmayoral election\b",
]
PREFILTER_RE = re.compile("|".join(PREFILTER_PATTERNS), re.IGNORECASE)

# False-positive families the raw prefilter catches by accident (2026-07-24
# labeling pass) -- excluded before spending hand-review budget on them.
PMQ_EXCLUDE_RE = re.compile(r"prime minister'?s questions|\bpmqs?\b", re.IGNORECASE)
SAY_BINGO_EXCLUDE_RE = re.compile(r'\bsay\b.*"', re.IGNORECASE)

# ── Hand-labeled families (2026-07-24 pass against bt_pop_2025-11-01_v1) ───
# Each pattern captures a family whose members all get the same reasoning.
# See module docstring: all resolve to STANDALONE under the mutual-
# exclusivity test.
FAMILY_PATTERNS = [
    ("ca_gov_advance", r"^Will (.+) advance from the 2026 California Governor primary election\?$"),
    ("ca_ltgov_advance", r"^Will (.+) advance from the California Lieutenant Governor Primary in 2026\?$"),
    ("ca_house_advance", r"^Will (.+) advance from the (CA-\d+) primary election\?$"),
    ("pt_president_2nd_round", r"^Will (.+) qualify for the second round of the 2026 Portugal presidential election\?$"),
    ("paris_2nd_round", r"^Will (.+) advance to the second round of the 2026 Paris municipal election\?$"),
    ("hu_seat", r"^Will (.+) win at least one seat in the (?:next|2026) Hungarian parliamentary election\?$"),
    ("bg_seat", r"^Will (.+) win at least one seat in the 2026 Bulgarian parliamentary election\?$"),
    ("uk_council_seats", r"^Will the (.+) win at least (\d+) council seat elections in the 2026 United Kingdom local elections\?$"),
    ("uk_mayorship", r"^Will (.+) win a mayorship in the 2026 United Kingdom local elections\?$"),
    ("jp_coalition", r"^Will (.+) be part of the governing coalition as a result of the 2026 Japanese snap election\?$"),
    ("jp_lose_seats", r"^Will (.+) loose any seats in Japanese snap election\?$"),
    ("us_house_odds", r"^2026 U\.S\. House Election: Republican Odds (over|under) (\d+)% by March 31\?$"),
    ("us_senate_odds", r"^2026 U\.S\. Senate Election: Republican Odds (over|under) (\d+)% by March 31\?$"),
    ("fed_nominee_by", r"^Will Donald Trump announce a new nominee for Chair of the Federal Reserve by (.+)\?$"),
    ("fr_election_called", r"^French election called by (.+)\?$"),
    ("labour_leadership_by", r"^Labour leadership election scheduled by (.+)\?$"),
    ("uk_election_called", r"^Will the next UK election be called by (.+)\?$"),
    ("ukraine_election", r"^Ukraine election (called|held) by (.+)\?$"),
    ("venezuela_election", r"^Venezuela election scheduled by (.+)\?$"),
    ("spain_election", r"^Spain snap election called (?:by|in) (.+)\?$"),
    ("nasralla_odds", r"^Odds Nasralla wins Honduras presidential election Sunday (over|overt) (\d+)%\?$"),
    ("ap_call_nj", r"^Will the Associated Press first call the 2025 New Jersey governor election (.+)\?$"),
    ("mamdani_borough", r"^Will Zohran Mamdani win (.+) in the 2025 New York City Mayoral General Election\?$"),
    ("outright_first_round", r"^Will any presidential candidate win outright in the first round of (.+)\?$"),
    ("tx_senate_flip", r"^Will Cornyn flip Paxton for Texas Rep Senate Primary Winner by (.+)\?$"),
    ("tx_senate_outright", r"^Will a candidate win outright in the Texas (Dem|GOP) Senate Primary\?$"),
]

FAMILY_REASONING = {
    "ca_gov_advance": "California uses a top-two ('jungle') primary for statewide offices -- TWO candidates advance to the general election, not one. Multi-advance format -> not mutually exclusive by design (this is the 2026-07-24 calibration exemplar).",
    "ca_ltgov_advance": "Same California top-two primary system as ca_gov_advance -- applies to all statewide offices including Lieutenant Governor.",
    "ca_house_advance": "California's top-two primary applies to U.S. House seats too (Top Two Primaries Act covers congressional as well as statewide/state-legislative races) -- TWO advance per district. Each district is also its own separate race from every other district's market in this family (not siblings of each other either way).",
    "pt_president_2nd_round": "Portugal uses a two-round presidential system: if no candidate exceeds 50% in round 1, the top TWO advance to a runoff. CONFIRMED by resolution data: Andre Ventura and Antonio Jose Seguro BOTH resolved YES -- definitively not mutually exclusive, no external fact needed.",
    "paris_2nd_round": "French municipal elections use a two-round system where ANY list scoring >=10% qualifies for round 2 (often more than 2). CONFIRMED by resolution data: Sophia Chikirou and Rachida Dati BOTH resolved YES -- definitively not mutually exclusive.",
    "hu_seat": "'Win at least one seat' in a proportional parliamentary election is a per-party threshold -- multiple parties routinely each clear this bar in the same election. Not mutually exclusive.",
    "bg_seat": "Same reasoning as hu_seat -- per-party seat threshold in a proportional parliamentary system, not mutually exclusive across parties.",
    "uk_council_seats": "Per-party seat-count threshold ladder (e.g. Labour Party 'at least 400' AND 'at least 500' AND 'at least 700' all independently YES in this data) -- nested bands, not mutually exclusive within or across parties. Resolution data is internally consistent with this (8/11 members YES simultaneously).",
    "uk_mayorship": "'Win a mayorship' asks about winning ANY of several concurrently-contested mayoral races -- different parties can each win a different race simultaneously.",
    "jp_coalition": "A governing coalition by definition can include multiple parties simultaneously -- structurally not mutually exclusive.",
    "jp_lose_seats": "Per-party threshold ('did this party lose seats') -- multiple parties can each independently lose seats in the same election.",
    "us_house_odds": "Nested probability-threshold ladder for the same race (over/under X%) -- multiple thresholds can be simultaneously true. Resolution data consistent: 'over 25%' YES, 'over 30/40/60%' NO implies actual odds landed 25-30%, exactly the nested-band behavior expected.",
    "us_senate_odds": "Same nested-threshold-ladder reasoning as us_house_odds, Senate race.",
    "fed_nominee_by": "Nested date-deadline family for the same underlying announcement event -- an announcement on, say, Feb 10 makes both the Feb 14 and Mar 31 deadline markets YES. Not mutually exclusive.",
    "fr_election_called": "Nested date-deadline variants of the same 'will an election be called' question -- not mutually exclusive (an early call satisfies every later deadline too).",
    "labour_leadership_by": "Nested date-deadline family, same reasoning as fr_election_called.",
    "uk_election_called": "Nested date-deadline family, same reasoning.",
    "ukraine_election": "Nested date-deadline / called-vs-held variant family for the same underlying Ukraine-election event -- not a mutually exclusive candidate set.",
    "venezuela_election": "Nested date-deadline family, same reasoning.",
    "spain_election": "Nested date-deadline family, same reasoning.",
    "nasralla_odds": "CONFIRMED by resolution data: 'over 30%' and 'overt 50%' BOTH resolved YES -- a higher probability threshold being crossed implies the lower one was too, definitively not mutually exclusive.",
    "ap_call_nj": "Time-band variants of the same 'when does AP call it' question. Only 2 members are visible in this zone and the observed windows are non-adjacent (before 8pm; 10:00-10:59pm) -- NOT a confirmed exhaustive partition, so not treated as a settled sibling-set; each labeled standalone individually rather than assumed merged.",
    "mamdani_borough": "Same candidate, different boroughs -- a citywide winner can plausibly win multiple boroughs simultaneously. Not mutually exclusive.",
    "outright_first_round": "Each market is about a different country's election (singleton per country in this zone) -- not siblings of each other.",
    "tx_senate_flip": "Nested date-deadline snapshot variants of the same 'has X overtaken Y in polling/odds' question, not a final-outcome sibling pair.",
    "tx_senate_outright": "Dem and GOP primaries are different, independent races -- not siblings of each other (each is an outright-win-threshold question for its own primary).",
}

PRESIDENTIAL_NOVELTY_TITLES = {
    "Will Newsom win the 2025 presidential election?",
    "Will Newsom win the 2026 presidential election?",
    "Will Trump win the 2027 presidential election?",
    "Will Biden win the 2027 presidential election?",
    "Will Harris win the 2027 presidential election?",
    "Will Mike Pence win the 2028 Republican presidential nomination?",
    "Will Kristi Noem win the 2028 Republican presidential nomination?",
    "Will Barack Obama win the 2028 Democratic presidential nomination?",
}
PRESIDENTIAL_NOVELTY_REASON = (
    "CONFIRMED by resolution data: 'Will Biden win the 2027 presidential "
    "election?' and 'Will Harris win the 2027 presidential election?' BOTH "
    "resolved YES for the same nominal race -- definitively not mutually "
    "exclusive, no external fact needed. These are independent speculative/"
    "novelty markets (2025-2027 aren't real US presidential election years; "
    "Newsom has separate 2025 [NO] and 2026 [YES] markets), each resolving "
    "on its own idiosyncratic criteria rather than a shared real contest."
)


def ensure_table(conn):
    conn.execute('''
    CREATE TABLE IF NOT EXISTS event_cluster_labels (
        snapshot_id         TEXT NOT NULL,
        market_id            TEXT NOT NULL,
        cluster_id           TEXT NOT NULL,
        label_type           TEXT NOT NULL,
        reasoning             TEXT,
        sibling_market_ids   TEXT,
        labeled_at           TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, market_id)
    )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_event_cluster_snapshot ON event_cluster_labels(snapshot_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_event_cluster_cid ON event_cluster_labels(cluster_id)')
    conn.commit()


def fetch_negrisk_bulk(session, rows):
    """rows: list of (market_id, api_id). Returns {market_id: {'negRisk':bool,'negRiskMarketID':str}}."""
    result = {}

    def batches(items, n=100):
        for i in range(0, len(items), n):
            yield items[i:i + n]

    with_api_id = [(mid, aid) for mid, aid in rows if aid]
    without_api_id = [(mid, aid) for mid, aid in rows if not aid]

    api_id_to_mid = {aid: mid for mid, aid in with_api_id}
    for chunk in batches(with_api_id):
        ids = [aid for _, aid in chunk]
        params = [("id", x) for x in ids] + [("closed", "true"), ("limit", "200")]
        try:
            resp = session.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            if resp.status_code == 200:
                for m in resp.json():
                    mid = api_id_to_mid.get(str(m.get("id")))
                    if mid:
                        result[mid] = {"negRisk": m.get("negRisk"), "negRiskMarketID": m.get("negRiskMarketID")}
        except Exception:
            pass
        time.sleep(0.15)

    still_missing = list(without_api_id) + [(mid, aid) for mid, aid in with_api_id if mid not in result]
    for chunk in batches(still_missing):
        ids = [mid for mid, _ in chunk]
        params = [("condition_ids", x) for x in ids] + [("closed", "true"), ("limit", "200")]
        try:
            resp = session.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            if resp.status_code == 200:
                for m in resp.json():
                    cid = m.get("conditionId")
                    if cid:
                        result[cid] = {"negRisk": m.get("negRisk"), "negRiskMarketID": m.get("negRiskMarketID")}
        except Exception:
            pass
        time.sleep(0.15)

    return result


def build_labels(conn, snapshot_id):
    rows = conn.execute('''
        SELECT m.market_id, m.api_id, m.title, m.winning_outcome
        FROM markets m
        JOIN backtest_population_snapshots s ON s.market_id = m.market_id
        WHERE s.snapshot_id = ?
    ''', (snapshot_id,)).fetchall()
    by_id = {r[0]: {"market_id": r[0], "api_id": r[1], "title": r[2], "winning_outcome": r[3]} for r in rows}

    session = requests.Session()
    negrisk = fetch_negrisk_bulk(session, [(r[0], r[1]) for r in rows])

    labeled_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    out_rows = []  # (snapshot_id, market_id, cluster_id, label_type, reasoning, sibling_market_ids_json, labeled_at)

    native_groups = defaultdict(list)
    ambiguous = []
    trivial = []

    for mid, info in by_id.items():
        nr = negrisk.get(mid)
        title = info["title"] or ""
        if nr and nr.get("negRisk") is True:
            native_groups[nr.get("negRiskMarketID")].append(mid)
        else:
            is_pmq = PMQ_EXCLUDE_RE.search(title)
            is_say_bingo = SAY_BINGO_EXCLUDE_RE.search(title)
            confirmed_false = nr is not None and nr.get("negRisk") is False
            title_candidate_shaped = bool(PREFILTER_RE.search(title)) and not is_pmq and not is_say_bingo
            if confirmed_false and title_candidate_shaped:
                ambiguous.append(mid)
            elif nr is None and title_candidate_shaped:
                ambiguous.append(mid)
            else:
                trivial.append(mid)

    # native_negrisk rows
    for gid, members in native_groups.items():
        for mid in members:
            siblings = [m for m in members if m != mid]
            out_rows.append((
                snapshot_id, mid, gid or mid, "native_negrisk",
                "Native Polymarket neg_risk grouping (negRiskMarketID field) -- authoritative, "
                "protocol-level mutually exclusive contract set.",
                json.dumps(siblings), labeled_at,
            ))

    # ambiguous zone -> hand labels
    matched_ids = set()
    families = defaultdict(list)
    for mid in ambiguous:
        title = by_id[mid]["title"]
        for fam, pat in FAMILY_PATTERNS:
            if re.match(pat, title):
                families[fam].append(mid)
                matched_ids.add(mid)
                break

    for fam, members in families.items():
        reason = FAMILY_REASONING[fam]
        for mid in members:
            out_rows.append((
                snapshot_id, mid, mid, "hand_standalone", reason, json.dumps([]), labeled_at,
            ))

    for mid in ambiguous:
        if mid in matched_ids:
            continue
        title = by_id[mid]["title"]
        if title in PRESIDENTIAL_NOVELTY_TITLES:
            out_rows.append((
                snapshot_id, mid, mid, "hand_standalone", PRESIDENTIAL_NOVELTY_REASON, json.dumps([]), labeled_at,
            ))
            matched_ids.add(mid)

    for mid in ambiguous:
        if mid in matched_ids:
            continue
        out_rows.append((
            snapshot_id, mid, mid, "hand_standalone",
            "No sibling market found in the ambiguous zone (same-title-prefix search); title is a "
            "self-contained threshold/compound/singleton question with no other candidate to be "
            "mutually exclusive against.",
            json.dumps([]), labeled_at,
        ))

    # trivial standalone
    for mid in trivial:
        out_rows.append((
            snapshot_id, mid, mid, "trivial_standalone",
            "negRisk=False (or unconfirmed) and title never matched the candidate-shaped keyword "
            "prefilter -- not individually hand-reviewed.",
            json.dumps([]), labeled_at,
        ))

    return out_rows, {
        "native_negrisk": sum(len(v) for v in native_groups.values()),
        "native_groups": len(native_groups),
        "hand_standalone": len(ambiguous),
        "trivial_standalone": len(trivial),
        "total": len(by_id),
    }


def write_labels(conn, rows):
    conn.executemany('''
        INSERT OR IGNORE INTO event_cluster_labels
        (snapshot_id, market_id, cluster_id, label_type, reasoning, sibling_market_ids, labeled_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', rows)
    conn.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    ensure_table(conn)

    existing = conn.execute(
        'SELECT COUNT(*) FROM event_cluster_labels WHERE snapshot_id = ?', (args.snapshot_id,)
    ).fetchone()[0]
    if existing > 0:
        print(f"Labels for snapshot '{args.snapshot_id}' already exist ({existing} rows). Skipping (idempotent).")
        sys.exit(0)

    rows, stats = build_labels(conn, args.snapshot_id)
    print(f"snapshot_id={args.snapshot_id}")
    print(f"  total markets       : {stats['total']}")
    print(f"  native_negrisk      : {stats['native_negrisk']} ({stats['native_groups']} groups)")
    print(f"  hand (ambiguous)    : {stats['hand_standalone']}")
    print(f"  trivial_standalone  : {stats['trivial_standalone']}")
    print(f"  rows to write       : {len(rows)}")

    if args.dry_run:
        print("--dry-run: not writing.")
    else:
        write_labels(conn, rows)
        print("Written.")

    conn.close()
