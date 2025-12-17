@echo off
echo Starting System Health Observer...

REM Wait 30 seconds for monitoring to start (if starting both)
timeout /t 30 /nobreak

REM Run observer (will auto-detect or prompt)
python scripts\run_system_observer.py

pause