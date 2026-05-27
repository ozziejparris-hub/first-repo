#!/usr/bin/env python3
"""
RQ1.1 — ELO Persistence Analysis (June 2026 Rerun)
Pre-registration: brain/strategy-notes/rq1-1-preregistration-2026-06-01.md
Pre-registered: 2026-05-13

Do not adjust thresholds or methodology after observing results.
"""

import sqlite3
import json
import sys
import os
import statistics
from datetime import datetime, timezone
from scipy import stats

DB_PATH = "/home/parison/projects/first-repo/data/polymarket_tracker.db"
SIGNALS_PATH = "/home/parison/trading-swarm/brain/signals.json"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_OUTPUT = os.path.join(OUTPUT_DIR, "rq1_1_rerun_june2026.json")
MD_OUTPUT = os.path.join(OUTPUT_DIR, "rq1_1_rerun_june2026_ranked.md")

# Fixed period boundaries — do not change (pre-registration §3.1)
PERIOD_1_END = '2026-04-01'
PERIOD_2_START = '2026-04-01'
PERIOD_2_END = '2026-06-01'

CONTRACT_CLEAN_POOL_MIN = 10000  # amended 2026-05-27: pool grew from ~493 to ~12,223 (leaderboard discovery)
CONTRACT_CLEAN_POOL_MAX = 20000
CONTRACT_CLEAN_MARKETS_MIN = 11000


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def write_signal(signal_type, payload):
    """Append a pending signal to trading-swarm brain/signals.json."""
    try:
        with open(SIGNALS_PATH, 'r') as f:
            signals_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        signals_data = {"signals": [], "pending": []}

    if "pending" not in signals_data:
        signals_data["pending"] = []

    signal = {
        "from": "quant-research-agent",
        "to": "orchestrator",
        "type": signal_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    signals_data["pending"].append(signal)

    with open(SIGNALS_PATH, 'w') as f:
        json.dump(signals_data, f, indent=2)

    print(f"[SIGNAL] Written to signals.json: type={signal_type}")


def validate_contract(conn):
    """Query 1 — Integration Contract Validation (pre-registration §4 Query 1)."""
    print("[CONTRACT] Running integration contract validation...")
    row = conn.execute("""
        SELECT
          (SELECT COUNT(*)
           FROM traders
           WHERE research_excluded = 0)              AS clean_pool,

          (SELECT COUNT(*)
           FROM markets
           WHERE resolved = 1
             AND (trade_gap_flag = 0
                  OR trade_gap_flag IS NULL))        AS clean_markets,

          (SELECT journal_mode
           FROM pragma_journal_mode())               AS wal_mode
    """).fetchone()

    clean_pool = row["clean_pool"]
    clean_markets = row["clean_markets"]
    wal_mode = row["wal_mode"]

    print(f"  clean_pool={clean_pool}  clean_markets={clean_markets}  wal_mode={wal_mode}")

    violations = []
    if clean_pool < CONTRACT_CLEAN_POOL_MIN or clean_pool > CONTRACT_CLEAN_POOL_MAX:
        violations.append(
            f"clean_pool={clean_pool} outside expected range "
            f"[{CONTRACT_CLEAN_POOL_MIN}, {CONTRACT_CLEAN_POOL_MAX}]"
        )
    if clean_markets < CONTRACT_CLEAN_MARKETS_MIN:
        violations.append(f"clean_markets={clean_markets} < minimum {CONTRACT_CLEAN_MARKETS_MIN}")
    if wal_mode != "wal":
        violations.append(f"wal_mode={wal_mode!r} — expected 'wal'")

    if violations:
        print(f"[CONTRACT VIOLATION] {violations}")
        write_signal("contract_violation", {
            "violations": violations,
            "clean_pool": clean_pool,
            "clean_markets": clean_markets,
            "wal_mode": wal_mode,
        })
        sys.exit(1)

    print("[CONTRACT] Passed.")
    return clean_pool, clean_markets


def check_sample_size_gate(conn):
    """Query 2 — Sample Size Gate. Hard exit if n < 30 (pre-registration §4 Query 2)."""
    print("[GATE] Checking sample size (minimum n=30 required)...")
    row = conn.execute("""
        SELECT COUNT(*) AS qualifying_n
        FROM traders tr
        WHERE tr.research_excluded = 0
          AND tr.elo_period1_cutoff IS NOT NULL

          AND (
            SELECT COUNT(*)
            FROM positions p
            JOIN markets m ON m.market_id = p.market_id
            WHERE p.trader_address = tr.address
              AND m.resolution_date < '2026-04-01'
              AND m.resolved = 1
              AND m.winning_outcome IN ('Yes', 'No')
              AND m.winning_outcome IS NOT NULL
              AND p.outcome IN ('Yes', 'No')
              AND p.entry_avg_price > 0
              AND p.entry_avg_price < 1
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          ) >= 20

          AND (
            SELECT COUNT(*)
            FROM positions p
            JOIN markets m ON m.market_id = p.market_id
            WHERE p.trader_address = tr.address
              AND m.resolution_date >= '2026-04-01'
              AND m.resolution_date <  '2026-06-01'
              AND m.resolved = 1
              AND m.winning_outcome IN ('Yes', 'No')
              AND m.winning_outcome IS NOT NULL
              AND p.outcome IN ('Yes', 'No')
              AND p.entry_avg_price > 0
              AND p.entry_avg_price < 1
              AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
          ) >= 20
    """).fetchone()

    n = row["qualifying_n"]
    print(f"  qualifying_n={n}")

    if n < 30:
        print(f"[HARD STOP] n={n} < 30. Insufficient data — halting and signalling.")
        write_signal("rq1_1_insufficient_n", {
            "qualifying_n": n,
            "minimum_required": 30,
            "period_1_end": PERIOD_1_END,
            "period_2_start": PERIOD_2_START,
            "period_2_end": PERIOD_2_END,
            "reason": (
                f"Only {n} traders meet both period ≥20-position requirements. "
                "Period 2 has not accumulated enough resolved markets. "
                "Reschedule for July 1 2026."
            ),
            "next_run": "2026-07-01",
        })
        sys.exit(0)

    print(f"[GATE] Passed — n={n} >= 30.")
    return n


def fetch_period_positions(conn, period_label, date_filter_sql):
    """Fetch raw position data for one period. Returns dict: address -> [brier_component, ...]."""
    rows = conn.execute(f"""
        SELECT
            p.trader_address,
            p.outcome           AS pos_outcome,
            p.entry_avg_price   AS entry_price,
            m.winning_outcome   AS win_outcome
        FROM positions p
        JOIN markets m  ON m.market_id   = p.market_id
        JOIN traders tr ON tr.address    = p.trader_address
        WHERE m.resolved = 1
          AND m.winning_outcome IN ('Yes', 'No')
          AND m.winning_outcome IS NOT NULL
          AND m.winning_outcome NOT IN ('unknown', '')
          AND p.outcome IN ('Yes', 'No')
          AND p.entry_avg_price > 0
          AND p.entry_avg_price < 1
          AND tr.research_excluded = 0
          AND tr.elo_period1_cutoff IS NOT NULL
          AND {date_filter_sql}
          AND (m.trade_gap_flag = 0 OR m.trade_gap_flag IS NULL)
    """).fetchall()

    trader_data = {}
    for row in rows:
        addr = row["trader_address"]
        entry = row["entry_price"]
        # Normalise to YES-probability space (pre-registration §3.3)
        p_yes = entry if row["pos_outcome"] == 'Yes' else 1.0 - entry
        actual_yes = 1.0 if row["win_outcome"] == 'Yes' else 0.0
        brier_component = (p_yes - actual_yes) ** 2
        trader_data.setdefault(addr, []).append(brier_component)

    print(f"  [{period_label}] {len(rows)} positions across {len(trader_data)} traders.")
    return trader_data


def compute_brier_scores(trader_data, min_positions=20):
    """Return dict: address -> {brier, n} for traders meeting the minimum position floor."""
    return {
        addr: {"brier": statistics.mean(comps), "n": len(comps)}
        for addr, comps in trader_data.items()
        if len(comps) >= min_positions
    }


def fetch_elo_data(conn):
    """Query 5 — ELO data. Uses elo_period1_cutoff exclusively (pre-registration §3.2)."""
    rows = conn.execute("""
        SELECT
            address,
            elo_period1_cutoff,
            total_trades,
            comprehensive_elo
        FROM traders
        WHERE research_excluded = 0
          AND elo_period1_cutoff IS NOT NULL
    """).fetchall()
    return {row["address"]: dict(row) for row in rows}


def determine_verdict(r, p, n):
    """Apply locked pass/fail criteria (pre-registration §5). Signs: r < 0 is pass direction."""
    if n < 30:
        return "NOISE_FAIL", "n < 30 — insufficient sample size"
    if r <= -0.40 and p < 0.05:
        return "STRONG_PASS", "ELO strongly predicts future accuracy — proceed to RQ3.2 and Phase 5 gate"
    if -0.40 < r <= -0.25:
        return "WEAK_PASS", "Directionally correct, insufficient magnitude — proceed with caution; monitor for 4 more weeks"
    if r > 0 and p < 0.05:
        return "DIRECTIONAL_FAIL", "ELO anti-predicts accuracy — system premise fails; trigger stopping-rule review"
    return "INCONCLUSIVE", "No reliable signal — extend Period 2 to September 1, 2026 and rerun"


def check_stopping_rule(r, p, n):
    """Section 6: halt only when all three conditions are met."""
    return r > 0 and p < 0.05 and n >= 50


def main():
    print("=" * 60)
    print("RQ1.1 — ELO Persistence (June 2026 Rerun)")
    print(f"Period 1 : before {PERIOD_1_END}")
    print(f"Period 2 : {PERIOD_2_START} to {PERIOD_2_END}")
    print("=" * 60)

    # Guard: never overwrite existing output files (pre-registration §8)
    for path, label in [(JSON_OUTPUT, "JSON results"), (MD_OUTPUT, "Ranked table")]:
        if os.path.exists(path):
            print(f"[ERROR] {label} output already exists: {path}")
            print("  Pre-registration forbids overwriting existing results.")
            print("  Delete the file manually before re-running.")
            sys.exit(1)

    run_timestamp = datetime.now(timezone.utc).isoformat()
    conn = connect_db()

    # Step 1: contract validation
    clean_pool, clean_markets = validate_contract(conn)

    # Step 2: sample size gate — hard exit if n < 30
    _ = check_sample_size_gate(conn)

    # Step 3: Period 1 positions (for position count confirmation)
    print("[QUERY] Fetching Period 1 positions...")
    p1_data = fetch_period_positions(
        conn, "Period1",
        "m.resolution_date < '2026-04-01'"
    )
    p1_brier = compute_brier_scores(p1_data, min_positions=20)

    # Step 4: Period 2 positions (for Brier score in correlation)
    print("[QUERY] Fetching Period 2 positions...")
    p2_data = fetch_period_positions(
        conn, "Period2",
        "m.resolution_date >= '2026-04-01' AND m.resolution_date < '2026-06-01'"
    )
    p2_brier = compute_brier_scores(p2_data, min_positions=20)

    # Step 5: ELO data
    print("[QUERY] Fetching ELO data...")
    elo_data = fetch_elo_data(conn)
    conn.close()

    # Merge: trader must appear in all three (P1 ≥20 positions, P2 ≥20 positions, non-NULL ELO)
    qualified_traders = []
    for addr in p1_brier:
        if addr not in p2_brier or addr not in elo_data:
            continue
        elo_val = elo_data[addr]["elo_period1_cutoff"]
        if elo_val is None:
            continue
        qualified_traders.append({
            "address": addr,
            "elo_period1_cutoff": elo_val,
            "comprehensive_elo": elo_data[addr]["comprehensive_elo"],
            "total_trades": elo_data[addr]["total_trades"],
            "period1_n": p1_brier[addr]["n"],
            "period2_n": p2_brier[addr]["n"],
            "period2_brier": p2_brier[addr]["brier"],
        })

    n = len(qualified_traders)
    print(f"[MERGE] {n} traders qualify after intersection of P1/P2 Brier + ELO filters.")

    if n < 30:
        print(f"[HARD STOP] Post-merge n={n} < 30. Writing rq1_1_insufficient_n signal.")
        write_signal("rq1_1_insufficient_n", {
            "qualifying_n": n,
            "minimum_required": 30,
            "reason": (
                f"Post-merge only {n} traders meet P1 ≥20, P2 ≥20, and non-NULL elo_period1_cutoff. "
                "Reschedule for July 1 2026."
            ),
            "next_run": "2026-07-01",
        })
        sys.exit(0)

    # Correlations
    elo_values = [t["elo_period1_cutoff"] for t in qualified_traders]
    brier_values = [t["period2_brier"] for t in qualified_traders]

    pearson_r, pearson_p = stats.pearsonr(elo_values, brier_values)
    spearman_r, spearman_p = stats.spearmanr(elo_values, brier_values)

    print(f"[RESULT] Pearson  r={pearson_r:.4f}  p={pearson_p:.4f}  n={n}")
    print(f"[RESULT] Spearman r={spearman_r:.4f}  p={spearman_p:.4f}")

    verdict, next_action = determine_verdict(pearson_r, pearson_p, n)
    stopping_rule = check_stopping_rule(pearson_r, pearson_p, n)

    print(f"[VERDICT] {verdict}")
    print(f"[NEXT ACTION] {next_action}")
    if stopping_rule:
        print("[STOPPING RULE TRIGGERED] r > 0, p < 0.05, n ≥ 50 — ELO research program must halt.")

    # Write JSON results
    results = {
        "rq": "RQ1.1",
        "run_timestamp": run_timestamp,
        "period_1_end": PERIOD_1_END,
        "period_2_start": PERIOD_2_START,
        "period_2_end": PERIOD_2_END,
        "n_qualifying_traders": n,
        "pearson_r": round(pearson_r, 6),
        "pearson_p": round(pearson_p, 6),
        "spearman_r": round(spearman_r, 6),
        "spearman_p": round(spearman_p, 6),
        "verdict": verdict,
        "stopping_rule_triggered": stopping_rule,
        "next_action": next_action,
        "elo_source": "elo_period1_cutoff",
        "trade_gap_flag_applied": True,
        "period_split_method": "fixed_2026-04-01",
        "contract_validation": {
            "clean_pool": clean_pool,
            "clean_markets": clean_markets,
        },
        "qualified_traders": qualified_traders,
    }

    with open(JSON_OUTPUT, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"[OUTPUT] {JSON_OUTPUT}")

    # Write Markdown ranked table (sorted by ELO descending)
    sorted_traders = sorted(qualified_traders, key=lambda x: x["elo_period1_cutoff"], reverse=True)
    md_lines = [
        "# RQ1.1 — Qualifying Traders Ranked by ELO (June 2026)",
        "",
        f"**Run:** {run_timestamp}",
        f"**n:** {n}  |  **Pearson r:** {pearson_r:.4f}  |  **p:** {pearson_p:.4f}  |  "
        f"**Spearman r:** {spearman_r:.4f}  |  **Verdict:** {verdict}",
        "",
        "| Rank | Address (truncated) | ELO Period1 | Comprehensive ELO | P2 Brier | P1 n | P2 n | Total Trades |",
        "|------|---------------------|-------------|-------------------|----------|------|------|--------------|",
    ]
    for i, t in enumerate(sorted_traders, 1):
        addr_short = t["address"][:10] + "..." + t["address"][-6:]
        md_lines.append(
            f"| {i} | {addr_short} | {t['elo_period1_cutoff']:.1f} | "
            f"{t['comprehensive_elo']:.1f} | {t['period2_brier']:.4f} | "
            f"{t['period1_n']} | {t['period2_n']} | {t['total_trades']} |"
        )
    md_lines += [
        "",
        f"*Sorted by elo_period1_cutoff descending. "
        f"trade_gap_flag filter applied. "
        f"Period 2: {PERIOD_2_START} to {PERIOD_2_END}.*",
    ]

    with open(MD_OUTPUT, 'w') as f:
        f.write('\n'.join(md_lines) + '\n')
    print(f"[OUTPUT] {MD_OUTPUT}")

    # Write orchestrator signal
    signal_type = "stopping_rule_triggered" if stopping_rule else "rq1_1_complete"
    signal_payload = {
        "verdict": verdict,
        "pearson_r": round(pearson_r, 6),
        "pearson_p": round(pearson_p, 6),
        "n": n,
        "stopping_rule_triggered": stopping_rule,
        "next_action": next_action,
        "results_path": "brain/agent-outputs/quant-research/RQ1.1/rq1_1_rerun_june2026.json",
    }
    if stopping_rule:
        signal_payload["spearman_r"] = round(spearman_r, 6)
        signal_payload["spearman_p"] = round(spearman_p, 6)

    write_signal(signal_type, signal_payload)

    print("=" * 60)
    print(f"RQ1.1 complete. Verdict: {verdict}")
    print("=" * 60)


if __name__ == "__main__":
    main()
