"""
monitoring/relevance_classifier_prompt.py
==========================================
The LLM-stage prompt for the geo/elections relevance classifier — stage 2
of the cascade (stage 1 is monitoring/relevance_prefilter.py).

Design    : brain/decisions/2026-08-31-relevance-classifier-design.md
            (e601648) §1.3, §2.4, §2.8, §2.9, and "WHAT REMAINS UNSPECIFIED"
            (which named this file as the remaining, undrafted piece).
Prior art : scripts/backfill_market_categories.py (M9) — CLASSIFY_PROMPT.
            This prompt is an adaptation of M9's, not a rewrite from
            scratch: same model, same reply-format contract (numbered
            JSON array), same {i+1: dict} batch convention. Two required
            departures from M9, both from the design, both explained below
            so a future reader does not reintroduce either.

DEPARTURE 1 — "be conservative, default Unknown" is DROPPED.
--------------------------------------------------------------
M9's prompt tells the model: "IMPORTANT: Be conservative. If unsure,
classify as Unknown." That instruction suits M9's *candidate set*: M9's
input is pre-filtered by a 37-keyword LIKE clause (KEYWORD_FILTER), so
everything M9 shows the model already contains a geo/elec-suggestive
token, and M9's job is mostly to catch the keyword filter's false
positives (e.g. "Iran" the boxer vs. "Iran" the country) — conservatism
there trades a little recall for a lot of precision, cheaply, because the
keyword filter already discarded almost everything.

This classifier's LLM stage sees a *different* population: the residual
left over AFTER monitoring/relevance_prefilter.py's deterministic
exclusion pass has already removed the ~83% of markets that are
recognisable template families (crypto, weather, sports, esports, stocks,
commodities, entertainment, novelty). There is no keyword pre-filter
upstream of this stage (design §1.3: "no 37-keyword pre-filter... it
reaches only 2.5% of the population and over-selects 2-3x; it is the
wrong gate"). Every market this prompt sees has already survived a
title/slug screen designed to be safe to exclude on, not a screen
designed to suggest relevance. Telling the model to default to
NotRelevant here does not trade recall for precision against an
already-narrowed candidate set the way it does for M9 — it just
re-inflates the false-negative rate on exactly the ambiguous population
the cascade exists to adjudicate (design §2.4: "the residual is exactly
the zone where LLM judgment is needed"). Hence: dropped, not carried
forward. Do not re-add a "when unsure, prefer NotRelevant" instruction to
this prompt without re-deriving why M9's version does not transfer.

DEPARTURE 2 — SLUG INPUTS, not title alone.
--------------------------------------------
M9 shows the model `title` only. This prompt shows four fields per
market: `title`, `market_slug`, `event_slug`, `event_title` — the same
four the design's §1.2/§1.3 slug characterisation was built on, staged
in `relevance_slug_staging` by the two Gamma slug-fetch runs
(2026-08-31 swept, 2026-09-01 unswept). Design §1.3: "LLM stage: title +
market.slug + event.slug + event.title, concatenated, one market per
line." `event.slug`/`event.title` in particular carry the clearest
positive signal for Elections (`-election-`, `-primary-`,
`-parliamentary-`, `nominee-for-`, `-governor`, `mayoral-election`) and
are often the only place a geopolitics market states its subject plainly
(design §1.2's examples: `usisrael-strikes-iran-by`,
`israel-withdraws-from-lebanon-by`) — a title alone (e.g. a truncated or
generic phrasing) can under-signal what the slug states outright.

CATEGORY DEFINITIONS — the SAME rubric the gate sets were hand-labelled
against (design §2.9 / §3.10), verbatim in substance, so the classifier
and the held-out gate share one standard and a disagreement is a real
disagreement, not two different rubrics talking past each other. Do not
edit these definitions without re-reading design §3.10 first — the gate
labels in brain/decisions/gate-sets-2026-09-01/labels.csv were fixed
against this exact wording before this file existed, and drifting the
prompt's definitions away from them after the fact would be exactly the
kind of after-the-result tuning the gate is designed to catch.

OUTPUT VOCABULARY: {Geopolitics, Elections, NotRelevant} — NOT M9's
{Geopolitics, Elections, Unknown}. "Unknown" already means "never
classified" for markets.category (design §2.6); reusing it as an LLM
output would collide with that meaning. "NotRelevant" is the classifier's
explicit negative decision, recorded in category_classification_log
(§2.7) but never written to markets.category — a NotRelevant market
simply stays 'Unknown' in the table (§2.6, "it writes nothing when the
decision is 'not relevant'").

WHAT THIS FILE IS NOT: it is not the wrapper, has no imports, makes no
network call, and is not itself executable. monitoring/relevance_classifier.py
imports PROMPT_TEMPLATE from here and does the calling. Keeping the prompt
text in its own file (design's own "remains unspecified" item) means it
can be read and revised by a future session without touching the harness
code around it.
"""

PROMPT_TEMPLATE = """\
You are classifying prediction-market questions for research relevance.

Classify each market as Geopolitics, Elections, or NotRelevant, using ONLY \
the fields given for that market.

Geopolitics = the market's resolution turns on state action, armed \
conflict, diplomacy, sanctions, treaties, territorial control, or an \
international-relations event (e.g. a country's military or foreign-policy \
action, a ceasefire, a border or territorial dispute, an international \
summit outcome).

Elections = the market's resolution turns on a vote, candidate, seat, \
primary, nomination, coalition, or party-leadership outcome, OR on the \
official conduct of a named political figure acting in their political \
capacity (this includes "will X say/announce/post ..." markets scoped to \
a politician's political event or role — treat these as Elections, not \
NotRelevant).

NotRelevant = everything else: sports, esports, crypto, weather, stocks, \
commodities, entertainment, novelty/religion, celebrity/personal-life \
markets, or any market whose resolution does not turn on the definitions \
above. If a market mentions a country, a public figure, or a \
geopolitics-adjacent word only incidentally (e.g. as part of a sports \
team name, a tournament name, or a location label) and its actual \
resolution condition is not political or geopolitical, classify it \
NotRelevant.

If a market plausibly fits BOTH Geopolitics and Elections (e.g. a tariff \
or government-shutdown market), pick whichever is the closer fit — do not \
default to NotRelevant to avoid the choice. Confidence reflects how \
clear-cut the category call is, not whether the market is relevant at all.

Each market below is given as four fields: its display title, its \
Polymarket market slug, its parent event's slug, and its parent event's \
title. All four describe the same market; read all four before deciding \
— the slug or event title sometimes states the subject more plainly than \
the title does.

{numbered_list}

Reply with ONLY a JSON array, no other text, no markdown, no explanation:
[{{"id": 1, "category": "Geopolitics/Elections/NotRelevant", "confidence": "HIGH/LOW"}}]
"""

# Per-market entry format fed into {numbered_list} above. Kept as a
# constant (not inlined in the wrapper) so the two are reviewable together.
MARKET_ENTRY_TEMPLATE = """\
{index}. title: {title}
   market_slug: {market_slug}
   event_slug: {event_slug}
   event_title: {event_title}"""
