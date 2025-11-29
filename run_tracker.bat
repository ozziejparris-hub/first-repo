@echo off
echo Starting Polymarket Tracker...
cd /d %~dp0
call .venv\Scripts\activate.bat
python -m monitoring.main
pause