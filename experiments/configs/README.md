# Simulation Configurations

Configuration files for the simulation framework.

## Available Configs

### config_simulation.json
**Production configuration** optimized for ELO validation.

- 100 traders (5 elite, 15 good, 50 average, 30 poor)
- 50 markets with **80% resolved** (40 resolved markets)
- 2,000 trades distributed across markets
- High trade frequency for better signal

**Use for:** Standard ELO validation and testing

### config_quick.json.example
**Fast testing configuration** for rapid iteration.

- 50 traders
- 20 markets (60% resolved)
- 500 trades
- Lower trade frequencies

**Use for:** Quick smoke tests during development

### config_stress.json.example
**Large-scale configuration** for stress testing.

- 500 traders
- 200 markets (70% resolved)
- 10,000 trades
- Higher trade frequencies

**Use for:** Performance testing and scalability validation

## Configuration Format

```json
{
  "seed": 42,
  "description": "Configuration description",

  "traders": {
    "total": 100,
    "distribution": {
      "elite": 0.05,
      "good": 0.15,
      "average": 0.50,
      "poor": 0.30
    },
    "skill_ranges": {
      "elite": [0.65, 0.80],
      "good": [0.55, 0.63],
      "average": [0.47, 0.54],
      "poor": [0.30, 0.46]
    },
    "volume_ranges": {
      "elite": [10000, 100000],
      "good": [5000, 50000],
      "average": [1000, 20000],
      "poor": [500, 10000]
    },
    "trade_frequency": {
      "elite": [30, 50],
      "good": [20, 40],
      "average": [10, 30],
      "poor": [5, 20]
    }
  },

  "markets": {
    "total": 50,
    "resolved_ratio": 0.80,
    "category": "Geopolitics",
    "days_old_range": [1, 90]
  },

  "trades": {
    "total": 2000,
    "buy_sell_ratio": 0.80,
    "trades_per_market_range": [20, 50]
  },

  "options": {
    "clear_database": false,
    "validate": true,
    "verbose": true
  }
}
```

## Key Parameters

### Trader Distribution
- **elite** (5%): Top performers, 65-80% win rate
- **good** (15%): Above average, 55-63% win rate
- **average** (50%): Average traders, 47-54% win rate
- **poor** (30%): Below average, 30-46% win rate

### Resolved Ratio
**Critical for ELO validation** - determines how many markets have outcomes.

- **80%+** recommended for accurate ELO calculation
- **60-70%** acceptable for quick tests
- **<60%** insufficient signal for validation

### Trade Frequency
Number of trades per trader across all markets. Higher frequencies provide:
- More data points for ELO calculation
- Better statistical significance
- Improved correlation with skill

## Creating Custom Configs

1. Copy an example file:
   ```bash
   cp config_simulation.json my_config.json
   ```

2. Modify parameters as needed

3. Run simulation:
   ```bash
   py scripts/simulation/seed_test_data.py experiments/configs/my_config.json
   ```

## Notes

- Files with `.example` extension are templates (tracked in git)
- Actual config files (`*.json`) are gitignored
- Always use `seed` for reproducible results
- Higher `resolved_ratio` improves ELO accuracy
