@echo off
REM Starts the Free Food Map at http://localhost:8765 and keeps it updated while this window is open.
cd /d "%~dp0"
python serve.py %*
pause
