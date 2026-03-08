@echo off
:: ============================================================
::  Polymarket Monitor - Detached Startup Script
::
::  Add to Windows Startup folder or Task Scheduler so
::  monitoring survives VSCode restarts and PC reboots.
::
::  This script delegates to start_detached.py which uses
::  subprocess.Popen with DETACHED_PROCESS + CREATE_NO_WINDOW
::  so the Python processes are fully independent of any
::  terminal, VSCode, or this batch window.
:: ============================================================

cd /d "C:\Users\Oscar\Projects\first-repo"

:: Activate virtual environment if present
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python scripts\start_detached.py
