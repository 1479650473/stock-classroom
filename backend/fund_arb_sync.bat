@echo off
chcp 65001 >nul
REM fund_arb_sync.bat - evening sync for LOF arbitrage data (list / purchase limits / daily bars / NAV)
REM Why a separate task: update_daily runs at 17:00, but the same-day fund NAV is usually
REM published after 19:00, so the panel can only fall back to the previous aligned day.
REM Running again at 22:30 picks up the current-day NAV.
REM Uses the project venv; paths are derived from %~dp0 (no hardcoded paths).
REM NOTE: keep this file ASCII-only - CJK comments break cmd line parsing (codepage).
cd /d "%~dp0.."
set "PY=%~dp0..\.update-venv\Scripts\python.exe"
set "LOGDIR=%~dp0..\data\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

"%PY%" -m backend.fund.sync --daily >> "%LOGDIR%\fund_arb_sync.log" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" exit /b 0

REM first attempt failed (source flakiness) -> wait 60s and retry once
echo [fund_arb_sync] first attempt failed (rc=%RC%), retrying in 60s... >> "%LOGDIR%\fund_arb_sync.log"
timeout /t 60 /nobreak >nul
"%PY%" -m backend.fund.sync --daily >> "%LOGDIR%\fund_arb_sync.log" 2>&1
exit /b %ERRORLEVEL%
