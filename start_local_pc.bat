@echo off
rem ResearchFlow: double-click to set up (first time only) and start the app.
title ResearchFlow
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_local_pc.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not finish. Read the message above, fix it, and run this file again.
  pause
  exit /b 1
)

echo Starting the backend on http://127.0.0.1:8000 ...
start "ResearchFlow backend (close to stop)" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000"

echo Starting the frontend on http://localhost:5173 ...
start "ResearchFlow frontend (close to stop)" /d "%~dp0frontend" cmd /k "npm run dev"

rem Wait until the frontend answers, then open the browser (up to about 60 seconds).
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -UseBasicParsing http://localhost:5173 -TimeoutSec 2 | Out-Null; exit 0}catch{Start-Sleep 1}}; exit 1"
start "" http://localhost:5173

echo.
echo ResearchFlow is running at http://localhost:5173
echo To stop it, close the two server windows.
timeout /t 8 >nul
