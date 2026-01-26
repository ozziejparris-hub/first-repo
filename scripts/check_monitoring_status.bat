@echo off
REM ====================================================================
REM  CHECK MONITORING & POSITION TRACKING STATUS
REM ====================================================================
REM
REM  Quick status check showing:
REM  1. If monitoring is running
REM  2. Position tracker integration status
REM  3. Recent P&L activity
REM  4. Position counts
REM
REM ====================================================================

echo.
echo ====================================================================
echo   MONITORING SYSTEM STATUS CHECK
echo ====================================================================
echo.

REM Check if python.exe is running (monitoring active)
echo [1] Checking if monitoring is running...
tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul
if errorlevel 1 (
    echo     [WARNING] No python.exe processes found
    echo     Monitoring is NOT running
) else (
    echo     [OK] python.exe is running
)

echo.
echo [2] Position tracker integration status...
echo.
py scripts\test_position_tracker.py
echo.

echo [3] Checking recent P^&L activity in logs...
echo.
if not exist "logs\monitoring_console.log" (
    echo     [WARNING] Log file not found
    echo     Monitoring may not have run yet
) else (
    echo     Last 10 P^&L log entries:
    echo     ----------------------------------------
    powershell -Command "Get-Content -Path 'logs\monitoring_console.log' -Tail 100 | Where-Object { $_ -match '\[P&L\]' } | Select-Object -Last 10"
    echo     ----------------------------------------
)

echo.
echo [4] Database position counts...
echo.
py -c "import sqlite3; conn = sqlite3.connect('data/polymarket_tracker.db'); cursor = conn.cursor(); cursor.execute('SELECT COUNT(*) FROM positions'); total = cursor.fetchone()[0]; cursor.execute('SELECT COUNT(*) FROM positions WHERE status=\"closed\"'); closed = cursor.fetchone()[0]; cursor.execute('SELECT COUNT(*) FROM positions WHERE status=\"open\"'); open_pos = cursor.fetchone()[0]; print(f'     Total positions: {total:,}'); print(f'     Closed: {closed:,}'); print(f'     Open: {open_pos:,}'); conn.close()"

echo.
echo ====================================================================
echo   STATUS CHECK COMPLETE
echo ====================================================================
echo.
pause
