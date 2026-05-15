# Research Directions

## ELO System Improvements

### ELO-IMP-001 — Dollar-weighted ROI in pnl_modifier (2026-05-15)

**Problem:** roi_modifier in unified_elo_system.py uses AVG(roi_percent) — an unweighted
position-count average. This misclassifies high-conviction traders who make many small
speculative bets alongside few large winning positions. Their avg_roi is dragged negative
by the small losers even when dollar-weighted ROI is strongly positive.

**Evidence:** Wickier ($141K realized P&L, $660K+ all-time volume) received pnl_modifier=0.6
due to negative avg_roi from small position count average, despite being a known profitable
geopolitics specialist.

**Proposed fix:** Replace AVG(roi_percent) with dollar-weighted ROI:
dollar_weighted_roi = SUM(realized_pnl) / SUM(entry_total_cost)

**Impact:** HIGH — affects all traders with mixed conviction sizing strategies. Current
formula systematically undervalues the most sophisticated traders.

**Pre-registration required:** Yes — must define success criteria before changing the formula.
Changes to ELO calculation require quant-research-agent pre-registration and backtest validation.

**Owner:** quant-research-agent
**Status:** IDENTIFIED — awaiting pre-registration
