@echo off
REM ====================================================================
REM  RESTART MONITORING WITH POSITION TRACKER FIX
REM ====================================================================
REM
REM  This script:
REM  1. Verifies position tracker is integrated
REM  2. Stops any running monitoring process
REM  3. Starts monitoring with position tracking active
REM  4. Shows live P&L logs
REM
REM ====================================================================

echo.
echo ====================================================================
echo   MONITORING RESTART SCRIPT
echo   Position Tracker Integration Fix
echo ====================================================================
echo.

REM Step 1: Verify position tracker integration
echo [1/4] Verifying position tracker integration...
echo.
py scripts\test_position_tracker.py

echo.
echo If you see "Position tracker is fully integrated" above, continue.
echo Otherwise, fix integration issues first.
echo.
pause

REM Step 2: Stop any running monitoring processes
echo.
echo [2/4] Stopping any running monitoring processes...
taskkill /F /IM python.exe >nul 2>&1
if errorlevel 1 (
    echo       No python.exe processes found
) else (
    echo       [OK] Killed python.exe processes
)
timeout /t 2 /nobreak >nul

REM Step 3: Start monitoring with position tracking
echo.
echo [3/4] Starting monitoring system...
echo.
echo ====================================================================
echo   MONITORING STARTED
echo   Watch for [P^&L] messages indicating position tracking activity
echo ====================================================================
echo.
echo Expected output every 15 minutes:
echo   [P^&L] Updating position tracking...
echo   [P^&L] Processing 1323 active traders...
echo   [P^&L] [OK] Updated P^&L for 456 traders
echo.
echo Press Ctrl+C to stop monitoring
echo.
echo ====================================================================
echo.

REM Run monitoring with proper Python module syntax
py -m monitoring.main

echo.
echo [4/4] Monitoring stopped
echo.
pause
