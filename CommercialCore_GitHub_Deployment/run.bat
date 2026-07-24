@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  py -3.12 -m venv .venv 2>nul || py -m venv .venv
  if errorlevel 1 (
    echo.
    echo Python 3.12 or later is required.
    echo Install Python from python.org and select "Add Python to PATH".
    pause
    exit /b 1
  )
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

echo.
echo CommercialCore is starting at http://127.0.0.1:8000
echo Keep this window open while using the application.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
