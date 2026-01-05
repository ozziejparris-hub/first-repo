@echo off
echo Starting Polymarket Monitoring System...
cd /d "%~dp0"
py -m monitoring.main
