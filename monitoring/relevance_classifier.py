"""
monitoring/relevance_classifier.py
===================================
LLM stage of the geo/elections relevance classifier cascade (stage 2;
stage 1 is monitoring/relevance_prefilter.py's deterministic exclusion).

Design    : brain/decisions/2026-08-31-relevance-classifier-design.md
            (e601648) §2.6, §2.8, §2.9.
Prompt    : monitoring/relevance_classifier_prompt.py — see that file's
            docstring for the two required departures from M9's prompt.
Record    : brain/decisions/2026-09-03-classifier-llm-stage.md.
Prior art : scripts/backfill_market_categories.py (M9) — same model
            (Qwen3-Coder via Ollama), same reply-format contract
            (numbered JSON array), same batch/retry shape. This module is
            meant to eventually subsume M9 (design §2.8), after the
            validation gate passes — not before.

WHAT THIS MODULE DOES
----------------------
classify_batch(markets) -> list[ClassificationResult]

Takes a list of market dicts {market_id, title, market_slug, event_slug,
event_title}, calls the LLM in batches, and returns one ClassificationResult
per input market_id (same count, order not guaranteed to match input order
across batch boundaries — callers needing input order should re-sort by
the market_id they supplied).

WHAT THIS MODULE DOES NOT DO (§2.6 — enforced structurally, not just by
convention)
-----------------------------------------------------------------------
This module contains NO sqlite3 import, NO database connection, and NO
UPDATE/INSERT/DELETE statement anywhere in it. It does not read the DB
either — callers fetch markets and pass them in as plain dicts. It
returns results; nothing in this module writes them anywhere. A caller
that wants to write markets.category / trades.market_category /
category_classification_log does so itself, following design §2.6's
guarded-UPDATE shape (WHERE category='Unknown') — that write path is a
separate, later task, not part of this module.

Per the task this module was built under: it has NOT been run against
brain/decisions/gate-sets-2026-09-01/ (set_a/b/c, labels.csv) or the
11,967-row pre-classified corpus. Those are the held-out validation gate,
used once, deliberately, as its own task. See the record doc for the
informal (non-gate) smoke test this module WAS exercised against.

BATCH SIZE
----------
DEFAULT_BATCH_SIZE = 20, unchanged from M9, after checking the arithmetic
rather than assuming it still holds (see the record doc for the full
calculation): the added slug fields make each market ~4x longer than
M9's title-only line (244 chars/market at the DB's actual average field
lengths, vs. M9's ~60), but a 20-market batch is still only ~1,900 prompt
tokens + ~300 completion tokens ~ 2,200 tokens total. The real risk this
task asked about was never the model's native context (262,144 tokens,
per `ollama show`) — it was Ollama's per-request `num_ctx`, which M9
never set and which the Ollama API defaults to a much smaller value than
the model supports if the caller omits it. This module does not rely on
that default: it sets num_ctx explicitly (OLLAMA_NUM_CTX below) to a
value with wide margin over the ~2,200-token estimate, so batch size did
not need to shrink to fit — the context budget was made adequate instead
of the batch made smaller.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from monitoring.relevance_classifier_prompt import MARKET_ENTRY_TEMPLATE, PROMPT_TEMPLATE

log = logging.getLogger("relevance_classifier")

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3-coder:30b-a3b-q4_K_M"  # same model as M9 (backfill_market_categories.py)
OLLAMA_TIMEOUT = 120  # seconds, matches M9

# Explicit per-request context window (see module docstring "BATCH SIZE").
# Not the model's native max (262,144) -- a deliberately generous but
# bounded budget for THIS prompt shape, set explicitly because Ollama's
# /api/generate defaults num_ctx to something much smaller than the
# model's native context when the caller omits it, and M9 omits it.
OLLAMA_NUM_CTX = 8192

DEFAULT_BATCH_SIZE = 20  # unchanged from M9 -- see module docstring

CATEGORY_VALUES = frozenset({"Geopolitics", "Elections", "NotRelevant"})
CONFIDENCE_VALUES = frozenset({"HIGH", "LOW"})


@dataclass(frozen=True)
class ClassificationResult:
    market_id: str
    # None means classification FAILED for this market (network error,
    # unparseable response, missing id, or an out-of-vocabulary value) --
    # distinct from the model genuinely deciding NotRelevant. Callers must
    # not treat category=None the same as category="NotRelevant".
    category: Optional[str]
    confidence: Optional[str]
    raw_response: str  # the raw per-item JSON text, or an error description


def _build_prompt(markets: list[dict]) -> str:
    entries = [
        MARKET_ENTRY_TEMPLATE.format(
            index=i + 1,
            title=m.get("title") or "",
            market_slug=m.get("market_slug") or "",
            event_slug=m.get("event_slug") or "",
            event_title=m.get("event_title") or "",
        )
        for i, m in enumerate(markets)
    ]
    return PROMPT_TEMPLATE.format(numbered_list="\n".join(entries))


def _call_ollama(prompt: str, model: str) -> Optional[str]:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX},
    }).encode()

    req = urllib.request.Request(
        OLLAMA_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        log.error(f"Ollama request failed: {e}")
        return None


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    return "\n".join(line for line in lines if not line.startswith("```")).strip()


def _parse_response(raw_text: str) -> Optional[list[dict]]:
    cleaned = _strip_markdown_fence(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Ollama response as JSON: {e} | raw={raw_text[:200]!r}")
        return None
    if not isinstance(parsed, list):
        log.error(f"Expected a JSON array, got {type(parsed).__name__} | raw={raw_text[:200]!r}")
        return None
    return parsed


def _classify_one_batch(markets: list[dict], model: str) -> list[ClassificationResult]:
    """markets: 1 <= len <= DEFAULT_BATCH_SIZE (or caller's chosen batch_size)."""
    prompt = _build_prompt(markets)
    raw_text = _call_ollama(prompt, model)

    if raw_text is None:
        return [
            ClassificationResult(
                market_id=m["market_id"],
                category=None,
                confidence=None,
                raw_response="ERROR: Ollama request failed (see log)",
            )
            for m in markets
        ]

    parsed = _parse_response(raw_text)
    if parsed is None:
        return [
            ClassificationResult(
                market_id=m["market_id"],
                category=None,
                confidence=None,
                raw_response=f"ERROR: unparseable response: {raw_text[:500]}",
            )
            for m in markets
        ]

    id_to_market = {i + 1: m for i, m in enumerate(markets)}
    results_by_index: dict[int, ClassificationResult] = {}

    for item in parsed:
        idx = item.get("id")
        market = id_to_market.get(idx)
        if market is None:
            log.warning(f"Ollama returned unknown id={idx!r}, ignoring")
            continue

        category = item.get("category")
        confidence = item.get("confidence")
        item_raw = json.dumps(item)

        if category not in CATEGORY_VALUES or confidence not in CONFIDENCE_VALUES:
            log.warning(
                f"market_id={market['market_id']} out-of-vocabulary response: {item_raw}"
            )
            results_by_index[idx] = ClassificationResult(
                market_id=market["market_id"],
                category=None,
                confidence=None,
                raw_response=f"ERROR: out-of-vocabulary response: {item_raw}",
            )
            continue

        results_by_index[idx] = ClassificationResult(
            market_id=market["market_id"],
            category=category,
            confidence=confidence,
            raw_response=item_raw,
        )

    # Any market the model's array simply omitted an entry for.
    results = []
    for i, m in enumerate(markets):
        idx = i + 1
        if idx in results_by_index:
            results.append(results_by_index[idx])
        else:
            log.warning(f"market_id={m['market_id']} missing from Ollama response")
            results.append(
                ClassificationResult(
                    market_id=m["market_id"],
                    category=None,
                    confidence=None,
                    raw_response="ERROR: id missing from Ollama response array",
                )
            )
    return results


def classify_batch(
    markets: list[dict],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: str = OLLAMA_MODEL,
) -> list[ClassificationResult]:
    """
    Classify a list of markets as Geopolitics / Elections / NotRelevant.

    markets: list of {market_id, title, market_slug, event_slug, event_title}.
             market_slug/event_slug/event_title may be None or "" (e.g. a
             market the slug fetch marked not_found) -- rendered as empty
             fields; title-only classification still proceeds.

    Returns one ClassificationResult per input market (same total count).
    Writes nothing anywhere -- see module docstring.
    """
    results: list[ClassificationResult] = []
    for start in range(0, len(markets), batch_size):
        chunk = markets[start : start + batch_size]
        results.extend(_classify_one_batch(chunk, model))
    return results
