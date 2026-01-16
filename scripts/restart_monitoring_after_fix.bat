@echo off
REM Restart monitoring after Telegram rate limit fix

echo.
echo ======================================================================
echo   RESTART MONITORING - After Telegram Rate Limit Fix
echo ======================================================================
echo.

echo [1/3] Killing old monitoring process...
taskkill /F /IM python.exe >nul 2>&1
if errorlevel 1 (
    echo       No python.exe processes found
) else (
    echo       Killed python.exe processes
)
timeout /t 2 /nobreak >nul

echo.
echo [2/3] Verifying fix applied...
findstr /C:"max_retries=3" monitoring\telegram_bot.py >nul
if errorlevel 1 (
    echo       [!] WARNING: max_retries not found in telegram_bot.py
    echo       [!] Fix may not be applied correctly
) else (
    echo       [OK] Retry limit verified
)

findstr /C:"notification_cooldown = 1800" monitoring\telegram_bot.py >nul
if errorlevel 1 (
    echo       [!] WARNING: cooldown not set to 1800
    echo       [!] Fix may not be applied correctly
) else (
    echo       [OK] Cooldown verified (30 minutes)
)

echo.
echo [3/3] Starting monitoring...
echo.
echo       Process will run in this window
echo       Press Ctrl+C to stop
echo.
echo       Expected behavior:
echo         - Market scans every 15 minutes
echo         - Trade processing
echo         - If rate limit: "[RATE LIMIT] Attempt X/3" then "[SKIP]"
echo         - System continues (not stuck)
echo.
echo ======================================================================
echo.

python -m monitoring.main
