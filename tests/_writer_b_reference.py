"""
Verbatim re-implementation of production Writer B's formula
(scripts/apply_full_elo_modifiers.py lines ~155-201), used ONLY by the
Stage-1 zero-diff equivalence test and the live-data validation script.

Not a test file itself (no test_ prefix — run_tests.py won't collect it).
Kept deliberately separate from analysis/comprehensive_elo_formula.py: this
module exists so the two independent formulas can be diffed against each
other, not to share code with the thing being verified.

If apply_full_elo_modifiers.py's formula internals ever change, this file
must be updated to match, or the equivalence test is comparing against a
stale reference.
"""

from typing import Optional


def _confidence_cap(closed: int) -> float:
    if closed >= 20:
        return 2.20
    if closed >= 10:
        return 2.00
    if closed >= 5:
        return 1.80
    if closed >= 3:
        return 1.60
    if closed >= 2:
        return 1.45
    return 1.30


def writer_b_reference(base_elo: float, mult_raw: float, closed_pos: int,
                        resolved_count: int) -> Optional[float]:
    """
    Returns the comprehensive_elo Writer B would write for this trader today,
    or None if Writer B would SKIP this trader entirely (the copy-trader
    exclusion: mult_raw == 0.0 causes `continue` in the real script — this
    trader is never written, so there is no "production value" to diff
    against; the equivalence test must not treat this as a comparable case).
    """
    mult = mult_raw
    if mult == 0.0:
        return None

    cap = _confidence_cap(closed_pos)
    mult = min(mult, cap) if mult > 1.0 else mult

    if mult > 1.0 and resolved_count < 10:
        mult = 1.0

    if mult < 1.0 and base_elo >= 2000:
        loss_amplifier = 1.30
        mult = 1.0 - ((1.0 - mult) * loss_amplifier)

    if base_elo >= 2500:
        dampening = 0.60
    elif base_elo >= 2000:
        dampening = 0.80
    else:
        dampening = 1.00
    new_elo = base_elo + (base_elo * (mult - 1.0) * dampening)

    new_elo = min(new_elo, 3500.0)
    return new_elo
