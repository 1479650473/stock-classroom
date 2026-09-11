@echo off
chcp 65001 >nul
REM update_daily.bat - scheduled daily A-share quant data refresh
REM Uses project venv (.update-venv\Scripts\python.exe) - independent of system Python path
REM Locates project root via %~dp0 (this file lives in backend\) to avoid hardcoding Chinese paths
cd /d "%~dp0.."
set "PY=%~dp0..\.update-venv\Scripts\python.exe"
set "SCRIPT=%~dp0update_daily.py"

"%PY%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

REM first run failed (rc=%RC%) -> wait 60s and retry once (source flakiness)
echo [update_daily] first attempt failed (rc=%RC%), retrying in 60s...
timeout /t 60 /nobreak >nul
"%PY%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
exit /b %RC%