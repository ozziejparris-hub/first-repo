#!/usr/bin/env python3
"""
Fix expired-but-unresolved markets that still have open positions.

Data quality fix only — no logic changes to the monitoring system.
Run after: python3 scripts/backup_database.py

Tasks performed:
  1. Fix 10 api_id-confirmed markets (resolved NO via Gamma API)
  2. Fix Russia/Ukraine ceasefire Jan 23 2026 market (resolved NO)
  3. Fix Bitcoin >$75K Dec 2025 market (resolved YES — BTC hit ~$100K)
  4. Fix corrupt end_dates for 2026 midterm markets (562803, 562802)
  5. Write manual review report for remaining no-api_id expired markets
  6. Requeue affected traders for P&L recalculation
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "polymarket_tracker.db"
REPORT_PATH = PROJECT_ROOT / "logs" / "expired_no_api_id_review.txt"

# Confirmed resolved NO via Gamma API (outcomePrices ["0","1"])
API_ID_NO_MARKETS = [706279, 537485, 537486, 604490, 676713, 676715, 531202, 701290, 801450, 679231]

# Russia/Ukraine ceasefire by Jan 23 2026 — expired, confirmed resolved NO
# NOTE: title was previously updated to "Q2 2026" in a prior session but
#       end_date 2026-01-23 confirms this is the expired Jan market.
CEASEFIRE_CONDITION_ID = "0x7b629fc0b14bece5d568e748f7a8c7c472f90833e9a00c3d4cc3c49e267f194c"

# Bitcoin >$75K by Dec 2025 — confirmed resolved YES (BTC hit ~$100K in Nov 2025)
BITCOIN_CONDITION_ID = "0x466b12e1092b1453907ff1f0f08f15c56e97f4c9b347c3f6e03d7c04e84b1de3"

# 2026 midterm markets: Gamma shows end_date 2026-11-03, our DB has wrong 2025-07-11
CORRUPT_END_DATES = [
    (562803, "2026-11-03T00:00:00Z"),  # Republican House control
    (562802, "2026-11-03T00:00:00Z"),  # Democratic House control
]

# Titles with garbled/suspect content to flag in the report
SUSPECT_KEYWORDS = ["merger", " TDs ", "LeBron"]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _synthetic_close_sql(winning_outcome: str) -> str:
    """Return the UPDATE SQL for synthetically closing positions given a winning outcome."""
    win = winning_outcome  # "Yes" or "No"
    lose = "No" if win == "Yes" else "Yes"
    return f"""
        UPDATE positions
        SET status = 'closed',
            exit_avg_price = CASE WHEN outcome = '{win}' THEN 1.0 ELSE 0.0 END,
            exit_total_received = CASE WHEN outcome = '{win}' THEN remaining_shares ELSE 0.0 END,
            realized_pnl = CASE WHEN outcome = '{win}'
                THEN remaining_shares - entry_total_cost
                ELSE -entry_total_cost END,
            exit_timestamp = datetime('now'),
            roi_percent = CASE WHEN outcome = '{win}'
                THEN ((remaining_shares - entry_total_cost) / NULLIF(entry_total_cost, 0)) * 100
                ELSE -100.0 END,
            is_synthetic_close = 1,
            last_updated = datetime('now')
        WHERE market_id = ?
        AND status = 'open'
    """


def _resolve_market_and_close(cur, condition_id: str, winning_outcome: str) -> tuple[int, float]:
    """
    Mark a market resolved and synthetically close all open positions.
    Returns (positions_closed, capital_closed).
    """
    # Collect affected traders and position stats before closing
    rows = cur.execute(
        "SELECT outcome, COUNT(*) as cnt, COALESCE(SUM(entry_total_cost), 0) as cap "
        "FROM positions WHERE market_id = ? AND status = 'open' GROUP BY outcome",
        (condition_id,),
    ).fetchall()

    pos_count = sum(r["cnt"] for r in rows)
    capital = sum(r["cap"] for r in rows)

    # Mark market resolved
    cur.execute(
        "UPDATE markets SET resolved=1, winning_outcome=?, resolution_date=datetime('now') "
        "WHERE condition_id = ? AND resolved = 0",
        (winning_outcome, condition_id),
    )

    # Synthetic close all open positions
    close_sql = _synthetic_close_sql(winning_outcome)
    cur.execute(close_sql, (condition_id,))

    return pos_count, capital


def fix_api_id_markets(cur) -> tuple[int, float, list[str]]:
    print("\n" + "=" * 60)
    print("TASK 1 — Fix 10 api_id-confirmed markets (resolved NO)")
    print("=" * 60)

    total_pos = 0
    total_cap = 0.0
    condition_ids = []

    for api_id in API_ID_NO_MARKETS:
        row = cur.execute(
            "SELECT condition_id, title, resolved FROM markets WHERE api_id = ?",
            (api_id,),
        ).fetchone()

        if not row:
            print(f"  [{api_id}] SKIP — not found in DB")
            continue
        if row["resolved"] == 1:
            print(f"  [{api_id}] SKIP — already resolved: {row['title'][:55]}")
            continue

        cid = row["condition_id"]
        condition_ids.append(cid)

        pos_count, capital = _resolve_market_and_close(cur, cid, "No")
        total_pos += pos_count
        total_cap += capital

        print(f"  [{api_id}] {(row['title'] or '')[:55]}")
        print(f"         → resolved=No  {pos_count} pos closed  ${capital:,.2f}")

    print(f"\n  Subtotal: {total_pos} positions, ${total_cap:,.2f}")
    return total_pos, total_cap, condition_ids


def fix_ceasefire_market(cur) -> tuple[int, float]:
    print("\n" + "=" * 60)
    print("TASK 2 — Fix Russia/Ukraine ceasefire Jan 2026 (resolved NO)")
    print("=" * 60)

    row = cur.execute(
        "SELECT title, end_date, resolved FROM markets WHERE condition_id = ?",
        (CEASEFIRE_CONDITION_ID,),
    ).fetchone()

    if not row:
        print("  ERROR: Market not found!")
        return 0, 0.0
    if row["resolved"] == 1:
        print("  SKIP — already resolved")
        return 0, 0.0

    print(f"  Title    : {row['title']}")
    print(f"  end_date : {row['end_date']}")
    print(f"  cid      : {CEASEFIRE_CONDITION_ID}")

    outcome_rows = cur.execute(
        "SELECT outcome, COUNT(*) as cnt, SUM(entry_total_cost) as cap "
        "FROM positions WHERE market_id = ? AND status = 'open' GROUP BY outcome",
        (CEASEFIRE_CONDITION_ID,),
    ).fetchall()
    for r in outcome_rows:
        print(f"  Positions {r['outcome']:3s}: {r['cnt']} pos  ${r['cap']:,.2f}")

    pos_count, capital = _resolve_market_and_close(cur, CEASEFIRE_CONDITION_ID, "No")
    print(f"\n  → resolved=No  {pos_count} pos closed  ${capital:,.2f}")
    return pos_count, capital


def fix_bitcoin_market(cur) -> tuple[int, float]:
    print("\n" + "=" * 60)
    print("TASK 3 — Fix Bitcoin >$75K Dec 2025 (resolved YES)")
    print("=" * 60)

    row = cur.execute(
        "SELECT title, end_date, resolved FROM markets WHERE condition_id = ?",
        (BITCOIN_CONDITION_ID,),
    ).fetchone()

    if not row:
        print("  ERROR: Market not found!")
        return 0, 0.0
    if row["resolved"] == 1:
        print("  SKIP — already resolved")
        return 0, 0.0

    print(f"  Title    : {row['title']}")
    print(f"  end_date : {row['end_date']}")

    outcome_rows = cur.execute(
        "SELECT outcome, COUNT(*) as cnt, SUM(entry_total_cost) as cap "
        "FROM positions WHERE market_id = ? AND status = 'open' GROUP BY outcome",
        (BITCOIN_CONDITION_ID,),
    ).fetchall()
    for r in outcome_rows:
        print(f"  Positions {r['outcome']:3s}: {r['cnt']} pos  ${r['cap']:,.2f}")

    pos_count, capital = _resolve_market_and_close(cur, BITCOIN_CONDITION_ID, "Yes")
    print(f"\n  → resolved=Yes  {pos_count} pos closed  ${capital:,.2f}")
    return pos_count, capital


def fix_corrupt_end_dates(cur):
    print("\n" + "=" * 60)
    print("TASK 4 — Fix corrupt end_dates for 2026 midterm markets")
    print("=" * 60)

    for api_id, correct_end_date in CORRUPT_END_DATES:
        row = cur.execute(
            "SELECT condition_id, title, end_date, resolved FROM markets WHERE api_id = ?",
            (api_id,),
        ).fetchone()

        if not row:
            print(f"  [{api_id}] NOT FOUND")
            continue

        print(f"  [{api_id}] {(row['title'] or '')[:55]}")
        print(f"         old end_date : {row['end_date']}")
        print(f"         new end_date : {correct_end_date}")
        print(f"         resolved     : {row['resolved']}  (positions NOT closed)")

        cur.execute(
            "UPDATE markets SET end_date = ? WHERE api_id = ?",
            (correct_end_date, api_id),
        )
        print("         → end_date corrected")


def requeue_traders(cur, all_condition_ids: list[str]) -> int:
    print("\n" + "=" * 60)
    print("TASK 6 — Requeue affected traders for P&L recalculation")
    print("=" * 60)

    if not all_condition_ids:
        print("  No condition_ids to requeue.")
        return 0

    placeholders = ",".join("?" * len(all_condition_ids))
    trader_rows = cur.execute(
        f"SELECT DISTINCT trader_address FROM positions WHERE market_id IN ({placeholders})",
        all_condition_ids,
    ).fetchall()

    addresses = [r["trader_address"] for r in trader_rows]
    if not addresses:
        print("  No traders found.")
        return 0

    addr_placeholders = ",".join("?" * len(addresses))
    cur.execute(
        f"UPDATE traders SET pnl_last_updated = NULL, pnl_update_priority = 1 "
        f"WHERE address IN ({addr_placeholders})",
        addresses,
    )
    print(f"  → {len(addresses)} traders requeued (pnl_last_updated=NULL, priority=1)")
    return len(addresses)


def write_manual_review_report(cur) -> int:
    print("\n" + "=" * 60)
    print("TASK 5 — Write manual review report for no-api_id markets")
    print("=" * 60)

    fixed_ids = (CEASEFIRE_CONDITION_ID, BITCOIN_CONDITION_ID)
    rows = cur.execute(
        """
        SELECT m.condition_id, m.title, m.category, m.end_date,
               COUNT(p.position_id) as open_positions,
               SUM(p.entry_total_cost) as capital
        FROM markets m
        JOIN positions p ON p.market_id = m.market_id
        WHERE p.status = 'open'
        AND m.resolved = 0
        AND (m.api_id IS NULL OR m.api_id = '')
        AND m.end_date < datetime('now')
        AND m.end_date IS NOT NULL
        AND m.condition_id NOT IN (?, ?)
        GROUP BY m.condition_id
        ORDER BY capital DESC
        """,
        fixed_ids,
    ).fetchall()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "EXPIRED UNRESOLVED MARKETS — NO api_id — MANUAL REVIEW REQUIRED",
        f"Generated : {datetime.now(timezone.utc).isoformat()}",
        f"Total     : {len(rows)} markets",
        "",
    ]

    high = [r for r in rows if (r["capital"] or 0) >= 10_000]
    low = [r for r in rows if (r["capital"] or 0) < 10_000]

    lines += [
        f"HIGH PRIORITY (>=$10K capital) — {len(high)} markets",
        "=" * 80,
    ]
    for r in high:
        title = r["title"] or "(no title)"
        suspect = ""
        if any(k.lower() in title.lower() for k in SUSPECT_KEYWORDS):
            suspect = "  [DATA_QUALITY_SUSPECT]"
        lines += [
            f"Title     : {title}{suspect}",
            f"Condition : {r['condition_id']}",
            f"Category  : {r['category']}  |  end_date: {r['end_date']}",
            f"Positions : {r['open_positions']}  |  Capital: ${(r['capital'] or 0):,.2f}",
            "-" * 80,
        ]

    lines += [
        "",
        f"LOW PRIORITY (<$10K capital) — {len(low)} markets",
        "=" * 80,
    ]
    for r in low:
        title = r["title"] or "(no title)"
        suspect = "  [DATA_QUALITY_SUSPECT]" if any(k.lower() in title.lower() for k in SUSPECT_KEYWORDS) else ""
        lines.append(
            f"{title}{suspect}  |  {r['condition_id']}  |  {r['end_date']}  |  ${(r['capital'] or 0):,.2f}"
        )

    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"  Written : {REPORT_PATH}")
    print(f"  HIGH    : {len(high)} markets")
    print(f"  LOW     : {len(low)} markets")
    return len(rows)


def verify(cur) -> tuple[int, float]:
    remaining = cur.execute(
        """
        SELECT COUNT(DISTINCT p.market_id) as markets,
               COUNT(*) as positions,
               COALESCE(SUM(p.entry_total_cost), 0) as capital
        FROM positions p
        JOIN markets m ON m.market_id = p.market_id
        WHERE p.status = 'open'
        AND m.resolved = 0
        AND m.end_date < datetime('now')
        AND m.end_date IS NOT NULL
        """
    ).fetchone()
    return remaining["positions"], remaining["capital"]


def main():
    print("=" * 60)
    print("  FIX EXPIRED UNRESOLVED MARKETS")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    conn = connect()
    try:
        with conn:
            cur = conn.cursor()

            t1_pos, t1_cap, t1_cids = fix_api_id_markets(cur)
            t2_pos, t2_cap = fix_ceasefire_market(cur)
            t3_pos, t3_cap = fix_bitcoin_market(cur)
            fix_corrupt_end_dates(cur)
            write_manual_review_report(cur)

            all_cids = t1_cids + [CEASEFIRE_CONDITION_ID, BITCOIN_CONDITION_ID]
            requeued = requeue_traders(cur, all_cids)

        total_pos = t1_pos + t2_pos + t3_pos
        total_cap = t1_cap + t2_cap + t3_cap

        remaining_pos, remaining_cap = verify(conn.cursor())

        print("\n" + "=" * 60)
        print("  FINAL SUMMARY")
        print("=" * 60)
        print(f"  Task 1 (10 api_id markets) : {t1_pos} positions closed  ${t1_cap:,.2f}")
        print(f"  Task 2 (ceasefire Jan 2026): {t2_pos} positions closed  ${t2_cap:,.2f}")
        print(f"  Task 3 (bitcoin >$75K)     : {t3_pos} positions closed  ${t3_cap:,.2f}")
        print(f"  Task 4 (end_date fixes)    : 2 markets corrected (not closed)")
        print(f"  Task 6 (trader requeue)    : {requeued} traders requeued")
        print(f"  ─────────────────────────────────────────────────")
        print(f"  TOTAL CLOSED               : {total_pos} positions  ${total_cap:,.2f}")
        print(f"  REMAINING OPEN/EXPIRED     : {remaining_pos} positions  ${remaining_cap:,.2f}")
        print("=" * 60)

    except Exception as exc:
        print(f"\n  ERROR: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
