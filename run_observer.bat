@echo off
echo Starting System Health Observer...

REM Change to project directory (IMPORTANT for Task Scheduler)
cd /d C:\Users\Oscar\Projects\first-repo

REM Remove timeout (Task Scheduler's 2-minute delay handles this)

REM Run observer (will auto-detect)
python scripts\run_system_observer.py

pause