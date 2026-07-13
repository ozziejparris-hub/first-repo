"""
Canonical comprehensive_elo formula — a pure function, no DB I/O, no imports
from the ELO system.

This is the single formula both writers (Sunday full recalc / Writer A, and
the daily incremental pass / Writer B) will call once the ELO arc migration
(O-7 / RQ-CONTESTED-001) lands. See the design doc for full context:
  ~/trading-swarm/brain/decisions/2026-07-06-elo-arc-design-FABLE.md
  (read the CORRECTION section first — it fixes two bugs in the original
  formula draft: the bonus term used to leak an independent W_bonus=1.0
  regardless of w_beh, and soft cap / floor were applied unconditionally.
  Both are fixed here: bonus shares w_beh with the multiplier, and
  apply_soft_cap / apply_floor are explicit caller-controlled parameters.)

W_BEH = 0.0 — resolved 2026-07-12 (Stage 0b). The behavioral validation study
found behavioral_modifier's incremental R^2 over base ELO + pnl_modifier is
0.00018 (n=21,218) — a well-powered null, not underpowered. See
~/trading-swarm/brain/decisions/2026-07-12-behavioral-validation-study-STAGE-0B.md
Flip via Stage 4's one-constant rollback/launch mechanism if better evidence
arrives later — do not hardcode 0.0 at call sites, use this constant.
"""

from dataclasses import dataclass
from typing import Optional

W_BEH = 0.0


@dataclass(frozen=True)
class EloResult:
    """Full audit trail for one compute_comprehensive_elo call."""
    comp: float
    pnl_gated: float
    beh_applied: float
    gain_pnl: float
    gain_beh: float
    damp: float
    cap_applied: str  # "none" | any of "soft"/"hard"/"floor" joined with "+"


def _confidence_cap(closed: int) -> float:
    """Max trusted P&L multiplier by closed-position count. Identical to
    apply_full_elo_modifiers.py's _confidence_cap — production reference."""
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
    return 1.30  # 1 closed position


def _dampening(base: float) -> float:
    if base >= 2500:
        return 0.60
    if base >= 2000:
        return 0.80
    return 1.00


def compute_comprehensive_elo(
    base: float,
    beh_mult: float,
    bonus: float,
    pnl_raw: float,
    closed: int,
    resolved: int,
    w_beh: float = W_BEH,
    apply_soft_cap: bool = True,
    apply_floor: bool = True,
) -> EloResult:
    """
    Inputs (per trader):
      base     = base_category_elo (re-derived Sunday; read from DB daily)
      beh_mult = behavioral multiplier, stored range [0.80, 1.40]
      bonus    = behavioral ELO bonus, stored range [-100, +100]
                 (kelly/patience; timing EXCLUDED per design §3.4 — pass
                 has_timing=False upstream when computing bonus, not here)
      pnl_raw  = P&L multiplier from positions table, stored range [0.40, 2.50]
                 (the RAW combined_multiplier, i.e. UnifiedELOSystem
                 .calculate_pnl_multiplier()['combined_multiplier'] — NOT
                 the already-gated traders.pnl_modifier column. Feeding an
                 already-gated value back in here will double-apply the
                 confidence cap / thin-sample gate / loss amplifier.)
      closed   = closed_positions count, from pnl_cache/positions — NOT
                 traders.closed_positions (design §7.1: the contested column)
      resolved = resolved_trades_count

      w_beh: behavioral weight. Both the multiplicative term and the bonus
        term scale by this SAME weight (see module docstring — this is the
        2026-07-06 correction; there is no separate w_bonus).
      apply_soft_cap, apply_floor: caller-controlled bounds switches, NOT
        tunable weights. Stage 2 calls with both False (reproduces Writer
        B's actual production bounds — hard cap only). Stage 3+ calls with
        both True.

    Returns EloResult with the full audit trail.
    """
    # P&L gain — Writer B's guards, verbatim.
    pnl_gated = min(pnl_raw, _confidence_cap(closed))
    if pnl_gated > 1.0 and resolved < 10:
        pnl_gated = 1.0  # thin-sample gate
    if pnl_gated < 1.0 and base >= 2000:
        pnl_gated = 1.0 - (1.0 - pnl_gated) * 1.30  # asymmetric loss amplification
    gain_pnl = base * (pnl_gated - 1.0)

    # Behavioral gain — bounded and gated. Both halves scale by the same w_beh.
    if resolved < 10:
        beh_applied = 1.0
        gain_beh = 0.0
    else:
        beh_applied = 1.0 + (beh_mult - 1.0) * w_beh
        gain_beh = base * (beh_applied - 1.0) + bonus * w_beh

    damp = _dampening(base)
    comp = base + (gain_pnl + gain_beh) * damp

    caps = []
    if apply_soft_cap:
        soft_cap_value = 1500 + resolved * 150
        if comp > soft_cap_value:
            caps.append("soft")
        comp = min(comp, soft_cap_value)
    if comp > 3500:
        caps.append("hard")
    comp = min(comp, 3500.0)
    if apply_floor:
        if comp < 400:
            caps.append("floor")
        comp = max(comp, 400.0)

    return EloResult(
        comp=comp,
        pnl_gated=pnl_gated,
        beh_applied=beh_applied,
        gain_pnl=gain_pnl,
        gain_beh=gain_beh,
        damp=damp,
        cap_applied="+".join(caps) if caps else "none",
    )
