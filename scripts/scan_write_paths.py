#!/usr/bin/env python3
"""
Write-path census scanner. Walks both repos' .py files and regex-matches
INSERT [OR x] INTO / UPDATE ... SET / DELETE FROM against every table name
in data/polymarket_tracker.db, capturing file:line and a snippet per match.

Feeds brain/decisions/2026-08-19-write-path-census.md (trading-swarm).

Method and its stated limitation: this is regex-on-source-text, not an AST
or a live query trace. It misses dynamically constructed table/column
names (e.g. f"UPDATE {table} SET ...") and anything built through an
abstraction layer this codebase doesn't appear to use. Absence of a hit
here is not proof of absence -- treat this as a first-pass map, not an
exhaustive one.

Read-only. Writes one JSON artifact per run (timestamped, not overwritten).
"""

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "polymarket_tracker.db")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "characterizations")
DEFAULT_ROOTS = [
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # first-repo
    os.path.expanduser("~/trading-swarm"),
]
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules"}


def get_tables(db_path: str) -> list[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    return [r[0] for r in rows]


def build_patterns(tables: list[str]):
    table_re = "|".join(sorted(set(tables), key=len, reverse=True))
    return [
        ("INSERT", re.compile(rf"INSERT\s+(OR\s+\w+\s+)?INTO\s+({table_re})\b", re.IGNORECASE)),
        ("UPDATE", re.compile(rf"UPDATE\s+({table_re})\b", re.IGNORECASE)),
        ("DELETE", re.compile(rf"DELETE\s+FROM\s+({table_re})\b", re.IGNORECASE)),
    ]


def scan(roots: list[str], patterns) -> list[dict]:
    results = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, "r", errors="replace") as f:
                        text = f.read()
                except Exception:
                    continue
                for kind, pat in patterns:
                    for m in pat.finditer(text):
                        line_no = text.count("\n", 0, m.start()) + 1
                        table = m.group(2) if kind == "INSERT" else m.group(1)
                        snippet = text[m.start(): m.start() + 300].replace("\n", " | ")
                        results.append({
                            "file": os.path.relpath(path, os.path.expanduser("~")),
                            "line": line_no,
                            "kind": kind,
                            "table": table,
                            "snippet": snippet,
                        })
    results.sort(key=lambda r: (r["table"], r["file"], r["line"]))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--out-dir", default=OUT_DIR)
    args = ap.parse_args()

    tables = get_tables(args.db)
    patterns = build_patterns(tables)
    results = scan(args.roots, patterns)

    by_table = {}
    for r in results:
        by_table.setdefault(r["table"], set()).add(r["file"])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": os.path.abspath(args.db),
        "roots_scanned": args.roots,
        "tables_total": len(tables),
        "total_matches": len(results),
        "files_per_table": {t: sorted(files) for t, files in sorted(by_table.items())},
        "matches": results,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out_dir, f"write_path_census_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)

    print(f"tables_total={len(tables)} total_matches={len(results)}")
    for t in sorted(by_table):
        print(f"  {t}: {len(by_table[t])} files")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
