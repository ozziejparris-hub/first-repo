@echo off
REM ====================================================================
REM  POLYMARKET TRACKING SYSTEM - UNIFIED LAUNCHER
REM ====================================================================
REM
REM  Starts all components:
REM  1. Monitoring System (every 15 min)
REM  2. System Observer (auto health checks + ELO updates)
REM
REM ====================================================================

echo.
echo ====================================================================
echo   POLYMARKET TRACKING SYSTEM
echo   Unified Launcher
echo ====================================================================
echo.
echo Starting all components...
echo.

REM Change to project directory
cd /d "%~dp0\.."

REM Start monitoring in new window (using standard entry point)
echo [1/2] Starting Monitoring System (Telegram-safe, position tracking enabled)...
START "Polymarket Monitoring" cmd /k "cd /d %~dp0\.. && py -m monitoring"
timeout /t 3 /nobreak >nul

REM Start system observer in new window
echo [2/2] Starting System Observer...
START "System Observer + Auto ELO" cmd /k "py scripts/run_system_observer.py"
timeout /t 2 /nobreak >nul

echo.
echo ====================================================================
echo   ALL SYSTEMS STARTED
echo ====================================================================
echo.
echo Terminal 1: Monitoring System
echo   - Trade tracking every 15 minutes
echo   - Position P^&L updates
echo.
echo Terminal 2: System Observer
echo   - Health monitoring
echo   - Auto ELO updates (every 24h or when needed)
echo   - Telegram notifications
echo.
echo Check Telegram for hourly status reports!
echo.
echo To stop: Close both terminal windows or Ctrl+C
echo ====================================================================
echo.
pause
