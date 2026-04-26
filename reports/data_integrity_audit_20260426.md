# Data Integrity Audit — 2026-04-25
## Flags Applied

### LP_ARTIFACT (4 traders)
Traders at ELO 3323-3326 who achieved high ELO through
market-making on a single malformed market
('Will Iran recognize Iran by June 2025?').
2,661-2,766 trades each, ~32% YES / 68% NO on a NO-resolving
market. ELO gain reflects LP volume not predictive skill.
Flagged: bot_suspect=1, bot_type='LP_ARTIFACT'

### THIN_SAMPLE_ARTIFACT (17 traders)
Traders at ELO 2699-2702 with only 6-9 resolved trades.
Cluster pattern suggests calculation artifact (same code
path hit by traders going 6/6 or 7/7 on high-difficulty
markets in a single batch). Statistically unreliable.
Flagged: bot_suspect=1, bot_type='THIN_SAMPLE_ARTIFACT'

### research_excluded column added
Convenience filter for all research queries.
Excludes: bot_suspect=1, wash_trade_suspect=1,
resolved_trades_count < 20, elo <= 300.
Total excluded: 79,987 traders
Remaining clean research pool: 6,829 traders

## Standard Research Query Filters
All future RQ scripts must include:
  WHERE research_excluded = 0
  AND t.timestamp <= datetime('now')
  JOIN markets m ON m.market_id = t.market_id  -- not condition_id
