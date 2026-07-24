@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call run.bat
call .venv\Scripts\activate
python seed_test_clients.py
echo.
echo Test clients loaded.
pause
