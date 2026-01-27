@echo off
REM ====================================================================
REM  RESTART TELEGRAM-SAFE MONITORING
REM ====================================================================
REM
REM  This version:
REM  - NO Telegram messages from monitoring (observer handles all)
REM  - Position tracking ALWAYS enabled
REM  - No rate limit hangs
REM  - Activity timestamps for health checks
REM
REM ====================================================================

echo.
echo ====================================================================
echo   TELEGRAM-SAFE MONITORING RESTART
echo   NO rate limit issues
echo   Position tracking: ENABLED
echo   Notifications via System Observer only
echo ====================================================================
echo.

REM Step 1: Stop any running monitoring processes
echo [1/3] Stopping any running monitoring processes...
taskkill /F /IM python.exe >nul 2>&1
if errorlevel 1 (
    echo       No python.exe processes found
) else (
    echo       [OK] Killed python.exe processes
)
timeout /t 2 /nobreak >nul

REM Step 2: Verify position tracker integration
echo.
echo [2/3] Verifying position tracker integration...
echo.
py scripts\test_position_tracker.py

echo.
echo If you see "Position tracker is fully integrated" above, continue.
echo Otherwise, fix integration issues first.
echo.
pause

REM Step 3: Start Telegram-safe monitoring
echo.
echo [3/3] Starting Telegram-safe monitoring...
echo.
echo ====================================================================
echo   MONITORING STARTED (Telegram-Safe Mode)
echo ====================================================================
echo.
echo Expected output every 15 minutes:
echo   Monitoring Cycle #N
echo   [P^&L] Updating position tracking...
echo   [P^&L] [OK] Updated P^&L for XXX traders
echo   [OK] Cycle complete
echo.
echo NO Telegram messages will be sent from monitoring
echo System Observer handles ALL notifications
echo.
echo Press Ctrl+C to stop monitoring
echo.
echo ====================================================================
echo.

REM Run Telegram-safe monitoring
py monitoring/main_telegram_safe.py

echo.
echo Monitoring stopped
echo.
pause
