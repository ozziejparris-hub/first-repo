# Polymarket Trader Tracker - Troubleshooting

Common issues and solutions.

## Telegram Issues

### "Conflict: terminated by other getUpdates request"

**Status:** ✅ FIXED (as of 2026-01-03)

**Cause:** Multiple bot instances polling same token

**Solution (Already Implemented):**
- Both bots run in send-only mode (no polling)
- No conflicts possible

**If it still occurs:**
```bash
# Kill all Python processes
taskkill /F /IM python.exe  # Windows
pkill -f python             # Linux/Mac

# Start monitoring once
python -m monitoring.main
```

**See:** [TELEGRAM_CONFLICT_FIX_SUMMARY.md](TELEGRAM_CONFLICT_FIX_SUMMARY.md)

### "Chat ID not configured"

**Cause:** Missing `TELEGRAM_CHAT_ID` in `.env`

**Solution:**
```bash
python scripts/get_telegram_chat_id.py
```
1. Run script
2. Send message to your bot
3. Copy chat ID to `.env`

### No Telegram notifications

**Checklist:**
- ✅ `TELEGRAM_BOT_TOKEN` in `.env`?
- ✅ `TELEGRAM_CHAT_ID` in `.env`?
- ✅ Bot started successfully (no errors)?
- ✅ Trades actually happening? (check database)

**Test:**
```bash
python scripts/test_telegram_bot_integration.py
```

## Database Issues

### "Database is locked"

**Cause:** Multiple monitoring instances running

**Solution:**
```bash
# Kill all instances
taskkill /F /IM python.exe  # Windows
pkill -f "monitoring.main"  # Linux/Mac

# Start only one
python -m monitoring.main
```

### "No such table: traders"

**Cause:** Database not initialized

**Solution:**
- Delete `data/polymarket_tracker.db`
- Restart monitoring (auto-creates tables)

```bash
python -m monitoring.main
```

### Database corruption

**Solution:**
```bash
# Restore from backup
cp data/backups/polymarket_tracker.db.backup_YYYYMMDD data/polymarket_tracker.db
```

## ELO Issues

### Slow ELO calculation

**Symptom:** Takes >30 seconds per trader

**Solution:** ✅ Already fixed with caching (1 hour TTL)

**Verify caching works:**
```bash
python scripts/test_elo_caching.py
```

**Expected:** Second run should be 45x faster

### Missing ELO ratings

**Symptom:** `comprehensive_elo` is NULL

**Solution:**
```bash
# 1. Build positions
python scripts/build_positions_historical.py

# 2. Recalculate ELO
python scripts/recalculate_comprehensive_elo.py
```

### Stale ELO ratings

**Symptom:** Ratings don't update after new trades

**Solution:**
```bash
# Force full recalculation
python scripts/recalculate_comprehensive_elo.py
```

## API Issues

### Polymarket "403 Access Denied"

**Cause:** API requires authentication

**Solution:**
1. Get API key from Polymarket
2. Add to `.env`:
   ```env
   POLYMARKET_API_KEY=your_key_here
   ```
3. Or use public data only (limited features)

### Polymarket rate limiting

**Symptom:** "429 Too Many Requests"

**Solution:**
- Monitoring has built-in rate limiting
- Increase `MONITORING_INTERVAL` in monitor.py
- Wait and retry

### API returns empty data

**Cause:** No active markets in geopolitical categories

**Solution:**
- Normal during quiet periods
- Monitoring will resume when markets appear

## Performance Issues

### High memory usage

**Normal:** 50-100 MB
**High:** >500 MB

**Solution:**
```bash
# Restart monitoring
# Memory should return to normal
python -m monitoring.main
```

### Monitoring cycle too slow

**Target:** <10 seconds per cycle
**Actual (with caching):** ~9 seconds

**If slower:**
1. Check ELO caching is enabled (it is)
2. Reduce number of tracked traders
3. Run full ELO updates less frequently

## Import Errors

### "No module named 'monitoring'"

**Cause:** Running from wrong directory

**Solution:**
```bash
cd /path/to/first-repo  # Project root
python -m monitoring.main
```

### "No module named 'telegram'"

**Cause:** Dependencies not installed

**Solution:**
```bash
pip install -r requirements.txt
```

### "No module named 'analysis'"

**Cause:** Analysis package not in path

**Solution:**
- Ensure you're in project root
- Analysis should be sibling to monitoring

## System Observer Issues

### Observer won't start

**Check dependencies:**
```bash
pip install -r requirements.txt
```

**Check Ollama/Mistral (for AI Phase 2):**
- Ollama must be running locally
- Mistral model must be installed

**Test:**
```bash
python scripts/run_system_observer.py
```

### AI analysis not working

**Cause:** Ollama not running or model not available

**Solution:**
1. Install Ollama
2. Pull Mistral model:
   ```bash
   ollama pull mistral
   ```
3. Start Ollama service
4. Restart observer

## File Migration Issues

### Scripts moved to scripts/

**Old paths (before 2026-01-03):**
```bash
python test_polymarket.py  # ❌ Old
```

**New paths:**
```bash
python scripts/test_polymarket.py  # ✅ New
```

**See:** [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md)

### Database not in data/

**Old:** `polymarket_tracker.db` in root
**New:** `data/polymarket_tracker.db`

**If monitoring can't find database:**
- Check `data/` directory exists
- Database should auto-create on first run

## Still Having Issues?

### Diagnostic Scripts

**Check database schema:**
```bash
python scripts/check_schema.py
```

**Check ELO status:**
```bash
python scripts/check_elo_status.py
```

**Test end-to-end:**
```bash
python scripts/test_end_to_end_integration.py
```

### Get Help

1. Check logs: `logs/monitoring.log`
2. Review `CURRENT_STRUCTURE.md` for project layout
3. Check [SETUP.md](SETUP.md) for configuration
4. Review [MONITORING.md](MONITORING.md) for system details
5. Check `archive/` for historical notes on fixes

### Enable Debug Logging

**File:** `monitoring/main.py`

Add at top:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Restart monitoring for detailed logs.

## Quick Reference

| Issue | Command |
|-------|---------|
| Kill all Python | `taskkill /F /IM python.exe` |
| Start monitoring | `python -m monitoring.main` |
| Start observer | `python scripts/run_system_observer.py` |
| Recalculate ELO | `python scripts/recalculate_comprehensive_elo.py` |
| View rankings | `python scripts/view_trader_rankings.py` |
| Get chat ID | `python scripts/get_telegram_chat_id.py` |
| Test Telegram | `python scripts/test_telegram_bot_integration.py` |
| Verify ELO | `python scripts/verify_elo_correctness.py` |
| Build positions | `python scripts/build_positions_historical.py` |

## Related Documentation

- [SETUP.md](SETUP.md) - Installation guide
- [MONITORING.md](MONITORING.md) - How monitoring works
- [ELO_SYSTEM.md](ELO_SYSTEM.md) - ELO system explained
- [SYSTEM_OBSERVER.md](SYSTEM_OBSERVER.md) - Observer guide
- [TELEGRAM_CONFLICT_FIX_SUMMARY.md](TELEGRAM_CONFLICT_FIX_SUMMARY.md) - Telegram fix details
