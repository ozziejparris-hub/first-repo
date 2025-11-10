# Polymarket API Setup Guide

## Current Status

The Polymarket Gamma API (`https://gamma-api.polymarket.com`) **requires authentication** as of November 2025. Public/unauthenticated access returns `403 Access Denied`.

## Getting API Access

### Option 1: Official Polymarket API Key

1. Visit [Polymarket.com](https://polymarket.com)
2. Create an account or log in
3. Navigate to Developer/API settings
4. Generate an API key

**Note**: As of 2025, Polymarket may have specific requirements or tiers for API access.

### Option 2: Use Polymarket's Official Python Client

Instead of accessing the REST API directly, you can use Polymarket's official Python client:

```bash
pip install py-clob-client
```

This client handles authentication and provides a cleaner interface.

### Option 3: Alternative Data Sources

If you can't get direct API access:

- **The Graph Subgraph**: Polymarket data is indexed on The Graph
- **Web Scraping**: Less reliable but possible for public data
- **Third-party APIs**: Some services aggregate Polymarket data

## Configuration

### 1. Create `.env` File

```bash
cp .env.example .env
```

### 2. Add Your Credentials

Edit `.env`:

```env
# Polymarket API
POLYMARKET_API_KEY=your_polymarket_api_key_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Optional: Your Telegram Chat ID
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Test Connection

```bash
python test_polymarket.py
```

## Troubleshooting

### 403 Access Denied

**Cause**: API requires authentication

**Solutions**:
1. Ensure you have a valid API key in `.env`
2. Check if your API key is active/valid
3. Verify you're using the correct authentication header format
4. Consider using the official `py-clob-client` instead

### API Key Format

The updated `polymarket_client.py` tries multiple authentication header formats:
- `Authorization: Bearer <key>`
- `X-API-Key: <key>`
- `APIKEY: <key>`

If none work, the API structure may have changed.

### Rate Limiting

If you get rate limit errors:
- Reduce polling frequency
- Implement exponential backoff
- Consider caching data locally

## Code Changes Made

### polymarket_client.py

**Improved**:
- ✅ Correct API parameters (`closed=False`, `archived=False`)
- ✅ Multiple authentication header formats
- ✅ Better error handling and debugging
- ✅ Response format detection (list vs dict)
- ✅ `test_connection()` method
- ✅ `get_all_markets()` for debugging

### test_polymarket.py

**Added comprehensive tests**:
- Raw API calls with/without auth
- Different authentication header formats
- Client connection testing
- Market fetching and filtering

## Alternative: Using Official Python Client

If direct API access continues to be problematic, here's how to use the official client:

```python
from py_clob_client.client import ClobClient

# Initialize client
client = ClobClient(
    key=POLYMARKET_API_KEY,
    chain_id=137  # Polygon
)

# Get markets
markets = client.get_markets()
```

## Support

If you're still having issues:
1. Check [Polymarket Documentation](https://docs.polymarket.com/)
2. Review the official [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
3. Contact Polymarket support for API access questions

## Next Steps

1. ✅ Get valid Polymarket API key
2. ✅ Configure `.env` file
3. ✅ Run `python test_polymarket.py`
4. ✅ If successful, run `python main.py` to start tracking

