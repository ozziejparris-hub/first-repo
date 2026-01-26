@echo off
REM ====================================================================
REM  VIEW P&L POSITION TRACKING LOGS (LIVE)
REM ====================================================================
REM
REM  Shows live P&L activity from monitoring logs
REM  Uses PowerShell's Get-Content -Wait (like tail -f)
REM
REM ====================================================================

echo.
echo ====================================================================
echo   LIVE P^&L POSITION TRACKING LOGS
echo ====================================================================
echo.
echo Watching for [P^&L] activity in monitoring logs...
echo Press Ctrl+C to stop
echo.
echo ====================================================================
echo.

REM Check if log file exists
if not exist "logs\monitoring_console.log" (
    echo [ERROR] Log file not found: logs\monitoring_console.log
    echo.
    echo Monitoring may not be running or logs directory doesn't exist.
    echo.
    pause
    exit /b 1
)

REM Use PowerShell to tail the log file and filter for P&L messages
powershell -Command "Get-Content -Path 'logs\monitoring_console.log' -Wait -Tail 50 | Where-Object { $_ -match '\[P&L\]' }"

echo.
pause
