@echo off
REM Stop Correlation Matrix Analysis
REM This script finds and stops correlation_matrix.py if it's running

echo ============================================================
echo   STOP CORRELATION MATRIX ANALYSIS
echo ============================================================
echo.

echo Searching for running correlation processes...
echo.

REM Find Python processes
wmic process where "name='python.exe' or name='pythonw.exe'" get ProcessId,CommandLine 2>nul | findstr /i "correlation" > temp_corr_procs.txt

REM Check if any found
for /f %%i in ('type temp_corr_procs.txt ^| find /c /v ""') do set COUNT=%%i

if %COUNT%==0 (
    echo [OK] No correlation processes found
    echo.
    echo System Observer should be running normally.
    del temp_corr_procs.txt
    pause
    exit /b 0
)

echo Found correlation process running!
echo.
type temp_corr_procs.txt
echo.

echo [WARNING] This will stop the correlation analysis.
echo Progress will be lost unless checkpoints are enabled.
echo.
set /p CONFIRM="Stop correlation process? (Y/N): "

if /i "%CONFIRM%" neq "Y" (
    echo.
    echo [CANCELLED] Correlation process still running
    del temp_corr_procs.txt
    pause
    exit /b 0
)

echo.
echo Stopping correlation processes...

REM Kill processes
for /f "tokens=1" %%p in (temp_corr_procs.txt) do (
    taskkill /PID %%p /F 2>nul
    if errorlevel 1 (
        echo [ERROR] Could not stop process %%p
    ) else (
        echo [OK] Stopped process %%p
    )
)

del temp_corr_procs.txt

echo.
echo ============================================================
echo [OK] Correlation analysis stopped
echo ============================================================
echo.
echo System Observer should now work normally.
echo.

pause
