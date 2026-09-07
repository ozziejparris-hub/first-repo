#!/usr/bin/env python3
"""
Drift guard: detect hardcoded geo_elo thresholds used as gate logic instead of
referencing monitoring.column_definitions (cd) constants.

Checks:
  1. Python Compare expressions — geo_elo / geo_elo_active compared to a raw
     numeric threshold (2175 / 1800 / 1400 / 1000 / 500).
  2. SQL string literals — string constants (outside docstrings and print/log
     calls) containing a raw "geo_elo[_active] >= NUMBER" comparison.
  3. Pool C gate copy-paste — SQL strings hardcoding the Pool C populate
     statement or geo_resolved_trades_count threshold instead of using
     cd.POOL_C_POPULATE_SQL / cd.POOL_C_GATE_WHERE / cd.refresh_pool_c.

NOT flagged (cosmetic text):
  - Docstrings (first statement of module / function / class body)
  - String arguments inside print() / logger.info() / log.*() calls
  - Source comments (#)
  - monitoring/column_definitions.py  (the canonical source)
  - this script itself

Exit: 0 = clean, 1 = drift found.

Usage:
  python scripts/check_canonical_definitions.py
"""
import ast
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Persisted (disk) signature of the last-observed violation set, so the
# alert only fires when something actually changed -- not identically every
# day forever. See brain/decisions/2026-09-07-telegram-remediation.md Part 3.
STATE_PATH = ROOT / "data" / ".canonical_drift_state.json"

EXEMPT_FILES: frozenset[Path] = frozenset({
    ROOT / "monitoring" / "column_definitions.py",
    Path(__file__).resolve(),
})

# Numeric threshold values that must come from cd constants, never hardcoded.
GATE_THRESHOLDS: frozenset[int] = frozenset({2175, 1800, 1400, 1000, 500})

# Regex: raw threshold comparison inside a string literal (SQL context)
_THRESH_ALTS = "|".join(str(t) for t in sorted(GATE_THRESHOLDS, reverse=True))
RE_RAW_THRESHOLD = re.compile(
    r"\bgeo_elo(?:_active)?\s*>=\s*(?:" + _THRESH_ALTS + r")\b"
)
# Only flag strings that look like SQL — uppercase keywords distinguish SQL from
# English description strings (e.g. argparse description with lowercase "where")
RE_SQL_CONTEXT = re.compile(r"\b(?:SELECT|WHERE|UPDATE|INSERT|DELETE|FROM)\b")

# Pool C: full populate UPDATE hardcoded instead of cd.POOL_C_POPULATE_SQL
RE_POOL_C_INLINE_UPDATE = re.compile(
    r"SET\s+geo_accuracy_pool\s*=\s*1\s+WHERE\b", re.IGNORECASE
)
# Pool C: gate condition hardcoded (geo_resolved_trades_count is unique to Pool C gate)
RE_POOL_C_GATE_COND = re.compile(r"geo_resolved_trades_count\s*>=\s*\d+")

# Call attributes treated as cosmetic / logging (comparisons inside their args
# describe thresholds, not enforce them)
_LOG_ATTRS: frozenset[str] = frozenset({
    "print", "info", "debug", "warning", "warn", "error", "critical", "exception",
})


# ---------------------------------------------------------------------------
# Docstring detection
# ---------------------------------------------------------------------------

def _docstring_node_ids(tree: ast.AST) -> frozenset[int]:
    """Return id()s of ast.Constant nodes that are module/function/class docstrings."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return frozenset(ids)


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------

class DriftVisitor(ast.NodeVisitor):
    def __init__(self, docstring_ids: frozenset[int]) -> None:
        self.violations: list[tuple[int, str]] = []
        self._docstring_ids = docstring_ids
        # Each entry: True if the enclosing Call is a print/log function
        self._call_stack: list[bool] = []

    def _cosmetic(self) -> bool:
        return any(self._call_stack)

    # ---- call context tracking -------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_log = (
            (isinstance(func, ast.Name) and func.id in _LOG_ATTRS)
            or (isinstance(func, ast.Attribute) and func.attr in _LOG_ATTRS)
        )
        self._call_stack.append(is_log)
        self.generic_visit(node)
        self._call_stack.pop()

    # ---- gate 1: Python-level comparisons --------------------------------

    def visit_Compare(self, node: ast.Compare) -> None:
        if not self._cosmetic():
            geo = self._geo_name(node.left)
            if geo:
                for cmp in node.comparators:
                    if (isinstance(cmp, ast.Constant)
                            and isinstance(cmp.value, (int, float))
                            and int(cmp.value) in GATE_THRESHOLDS):
                        self.violations.append((
                            node.lineno,
                            f"Python comparison `{geo} >= {int(cmp.value)}` "
                            f"— replace with cd.GEO_ELO_* constant",
                        ))
        self.generic_visit(node)

    # ---- gate 2 & 3: SQL string literals ---------------------------------

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        if id(node) in self._docstring_ids:
            return
        if self._cosmetic():
            return

        val = node.value

        m = RE_RAW_THRESHOLD.search(val)
        if m and RE_SQL_CONTEXT.search(val):
            self.violations.append((
                node.lineno,
                f"SQL string contains `{m.group()}` "
                f"— use cd.LEGENDARY_GATE_WHERE or cd.GEO_ELO_* constant",
            ))
            return  # one report per string is enough

        if RE_POOL_C_INLINE_UPDATE.search(val):
            self.violations.append((
                node.lineno,
                "Pool C populate SQL hardcoded in string "
                "— use cd.POOL_C_POPULATE_SQL or cd.refresh_pool_c(conn)",
            ))
        elif RE_POOL_C_GATE_COND.search(val):
            self.violations.append((
                node.lineno,
                "Pool C gate condition (geo_resolved_trades_count) hardcoded "
                "— use cd.POOL_C_GATE_WHERE",
            ))

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _geo_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and "geo_elo" in node.id:
            return node.id
        if isinstance(node, ast.Attribute) and "geo_elo" in node.attr:
            return node.attr
        return None


# ---------------------------------------------------------------------------
# Telegram alert
# ---------------------------------------------------------------------------

async def _send_telegram_async(token: str, chat_id: str, message: str) -> None:
    from telegram import Bot
    bot = Bot(token=token)
    MAX = 4000
    if len(message) <= MAX:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML",
                               read_timeout=15, write_timeout=15)
    else:
        for chunk in [message[i:i+MAX] for i in range(0, len(message), MAX)]:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML",
                                   read_timeout=15, write_timeout=15)


def send_telegram_alert(violations: list) -> None:
    # Fixed 2026-09-07: this was the one sender (of every Telegram sender
    # audited across both repos) missing a credential self-load -- cron's
    # `source .env_trading` never exports its unexported VAR=value lines to
    # this script's Python subprocess, so bare os.getenv() always returned
    # None here even though audit_invariants.py, run daily right before this
    # step, works via this exact call. See
    # brain/decisions/2026-09-07-canonical-enforcement-part1-stop.md §1.4 and
    # brain/decisions/2026-09-07-telegram-remediation.md Part 3.
    from dotenv import load_dotenv
    load_dotenv("/home/parison/.env_trading")

    token   = os.getenv("telegram_alerts_token")
    chat_id = os.getenv("telegram_chat_id")
    if not token or not chat_id:
        print("[TELEGRAM] Credentials not found — skipping alert.", file=sys.stderr)
        return
    lines = [
        "<b>⚠️ Canonical Definitions Drift Detected</b>",
        f"{len(violations)} violation(s) found:\n",
    ]
    for rel, lineno, msg in violations[:20]:
        lines.append(f"  • {rel}:{lineno}  {msg}")
    if len(violations) > 20:
        lines.append(f"  … and {len(violations) - 20} more")
    lines.append("\nFix: replace hardcoded thresholds with constants from monitoring/column_definitions.py")
    try:
        asyncio.run(_send_telegram_async(token, chat_id, "\n".join(lines)))
        print("[TELEGRAM] Alert sent.")
    except Exception as exc:
        print(f"[TELEGRAM] Failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Change detection (added 2026-09-07 -- see
# brain/decisions/2026-09-07-telegram-remediation.md Part 3)
# ---------------------------------------------------------------------------

def violation_signature(violations: list[tuple[Path, int, str]]) -> list[str]:
    """
    Stable, order-independent signature of a violation set: (file, message)
    only -- deliberately excludes line number, so a violation whose line
    shifted due to an unrelated edit elsewhere in the file doesn't look like
    a "new" finding.
    """
    return sorted(f"{rel}:{msg}" for rel, _lineno, msg in violations)


def load_previous_signature() -> list[str] | None:
    try:
        return json.loads(STATE_PATH.read_text())["violations"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def save_signature(signature: list[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"violations": signature}, indent=2))


def should_alert(signature: list[str], previous_signature: list[str] | None) -> bool:
    """
    True only if there ARE violations AND the set changed since the last
    observed state -- an unchanged violation set (the same 7 violations,
    every day, for 11 weeks) is not news.
    """
    if not signature:
        return False
    if previous_signature is None:
        return True
    return signature != previous_signature


# ---------------------------------------------------------------------------
# Per-file check
# ---------------------------------------------------------------------------

def check_file(path: Path) -> list[tuple[int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as e:
        return [(0, f"Cannot read file: {e}")]
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [(0, f"SyntaxError: {e}")]

    visitor = DriftVisitor(_docstring_node_ids(tree))
    visitor.visit(tree)
    return visitor.violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(alert: bool = False) -> int:
    py_files = sorted(
        f for f in ROOT.rglob("*.py")
        if f.resolve() not in EXEMPT_FILES
    )

    all_violations: list[tuple[Path, int, str]] = []
    for path in py_files:
        for lineno, msg in check_file(path):
            all_violations.append((path.relative_to(ROOT), lineno, msg))

    signature = violation_signature(all_violations)
    previous_signature = load_previous_signature()

    if all_violations:
        print(
            f"[check_canonical_definitions] DRIFT DETECTED "
            f"— {len(all_violations)} violation(s):\n"
        )
        for rel, lineno, msg in all_violations:
            print(f"  {rel}:{lineno}  {msg}")
        print(
            f"\nFix: replace hardcoded thresholds / gate conditions with constants from\n"
            f"     monitoring/column_definitions.py"
        )
        # Bug-only gate (2026-09-07): alert only if the violation set changed
        # since the last observed run -- an unchanged set is not news. See
        # brain/decisions/2026-09-07-telegram-remediation.md Part 3.
        if alert:
            if should_alert(signature, previous_signature):
                send_telegram_alert(all_violations)
            else:
                print("[check_canonical_definitions] unchanged from last observed run — suppressing alert")
        save_signature(signature)
        return 1

    print(
        f"[check_canonical_definitions] CLEAN "
        f"— 0 violations across {len(py_files)} Python files."
    )
    save_signature(signature)
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert", action="store_true",
                        help="Send Telegram alert if drift violations are found")
    args = parser.parse_args()
    sys.exit(main(alert=args.alert))
