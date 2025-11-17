# Polymarket Crypto Tracker

A specialized monitoring system that tracks successful traders in cryptocurrency price prediction markets on Polymarket.

## Overview

This is a **crypto-focused** variant of the geopolitics tracker. It uses **inverted filtering logic**:
- **INCLUDES**: Crypto "Up or Down" markets and price predictions
- **EXCLUDES**: Geopolitics, sports, entertainment, and all non-crypto markets

## What It Tracks

### Crypto Markets Included:
1. 🪙 **"Up or Down" markets** - Short-term price speculation (e.g., "Bitcoin Up or Down - November 14, 6:00PM")
2. 🪙 **"Dip to $X" markets** - Price floor predictions (e.g., "Will Bitcoin dip to $94,000?")
3. 🪙 **"Price of [crypto]" markets** - Exact price predictions (e.g., "Will the price of Bitcoin be above $96,000?")
4. 🪙 **Price prediction verbs** - General crypto price markets (reach $, hit $, ATH, etc.)

### Cryptocurrencies Tracked:
- **Major**: BTC, ETH, SOL, XRP
- **Altcoins**: ADA, BNB, AVAX, MATIC, LINK, DOT, UNI
- **Meme Coins**: DOGE, SHIB, PEPE
- **Others**: LTC, and more

### Market Categories:
- BTC (Bitcoin)
- ETH (Ethereum)
- SOL (Solana)
- XRP (Ripple)
- Major Altcoins (ADA, BNB, AVAX, MATIC, LINK, DOT)
- Meme Coins (DOGE, SHIB, PEPE)
- Other Crypto

## Key Differences from Geopolitics Tracker

| Feature | Geopolitics Tracker | Crypto Tracker |
|---------|-------------------|----------------|
| **Filtering Logic** | EXCLUDE crypto/sports | INCLUDE ONLY crypto |
| **Check Interval** | 15 minutes | 10 minutes |
| **Database** | `polymarket_tracker.db` | `polymarket_crypto_tracker.db` |
| **Categories** | Elections, Geopolitics, Economics | BTC, ETH, SOL, XRP, Altcoins, Meme Coins |
| **Focus** | World events | Price predictions |

## Setup

1. **Install dependencies** (same as geopolitics tracker):
   ```bash
   pip install -r ../requirements.txt
   ```

2. **Configure environment variables** in `.env`:
   ```
   POLYMARKET_API_KEY=your_api_key
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id  # Optional
   ```

3. **Run the tracker**:
   ```bash
   python main.py
   ```

## Testing

Run the comprehensive test suite:
```bash
python test_crypto_inclusion.py
```

**Expected results**: 100% accuracy on 49 test markets (28 crypto + 21 non-crypto)

## How It Works

1. **Initial Scan**: Identifies successful crypto traders (70%+ win rate, 20+ trades)
2. **Monitoring Loop**: Checks for new trades every 10 minutes
3. **Filtering**: Only includes crypto price prediction markets
4. **Categorization**: Auto-categorizes by coin/token (BTC, ETH, SOL, etc.)
5. **Notifications**: Sends bundled Telegram alerts for flagged trader activity

## Filtering Patterns

### Pattern Priority (highest to lowest):

1. **"Up or Down"** - `"Bitcoin Up or Down - November 14, 6:00PM"`
   - Always crypto speculation markets

2. **"Dip to $"** - `"Will Bitcoin dip to $94,000 November 10-16?"`
   - Crypto price floor predictions

3. **"Price of [crypto]"** - `"Will the price of Bitcoin be above $96,000?"`
   - Exact price predictions

4. **Crypto + Price Verbs** - `"Will Ethereum reach $10,000 by end of year?"`
   - General crypto price predictions (reach $, hit $, ATH, etc.)

### Non-Crypto Markets (Excluded):
- ❌ Geopolitics (elections, wars, diplomacy)
- ❌ Sports (team vs team, championships, playoffs)
- ❌ Entertainment (Spotify, box office, awards)
- ❌ Economics/Policy (Fed rates, GDP, tariffs)

## Database Schema

Same as geopolitics tracker:
- `traders` - Successful trader profiles
- `trades` - Trade history from flagged traders
- `markets` - Market metadata

Database file: `data/polymarket_crypto_tracker.db` (separate from geopolitics tracker)

## Files

- `monitor.py` - Main monitoring service with inverted filtering
- `database.py` - SQLite database operations
- `polymarket_client.py` - Polymarket API client
- `telegram_bot.py` - Telegram notifications
- `trader_analyzer.py` - Trader performance analysis
- `main.py` - Entry point
- `test_crypto_inclusion.py` - Comprehensive test suite

## Example Notifications

```
🪙 CRYPTO TRADER ALERT

Trader: 0x1234...5678
Win Rate: 75.5% (45/60 trades)

Recent Activity:
📈 Bitcoin Up or Down - 6:00PM
   Bought 500 shares @ $0.52

📈 Will BTC reach $100,000 by Dec 31?
   Bought 250 shares @ $0.68

Market Categories: BTC (2 trades)
```

## Performance

- **Check Interval**: 10 minutes (faster than geopolitics tracker)
- **Test Accuracy**: 100% on 49 test markets
- **Pattern Coverage**:
  - 25% "Up or Down" markets
  - 21% "Dip to $" markets
  - 14% "Price of" markets
  - 40% Other crypto price predictions

## Notes

- This tracker runs **independently** from the geopolitics tracker
- Both can run simultaneously without conflicts (separate databases)
- Optimized for high-frequency crypto price speculation markets
- 10-minute check interval captures rapid market activity

## Support

For issues or questions, refer to the main project documentation or create an issue in the repository.
