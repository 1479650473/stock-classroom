@echo off
chcp 65001 >nul
REM update_daily.bat - scheduled daily A-share quant data refresh
REM Uses project venv (.update-venv\Scripts\python.exe) - independent of system Python path
REM Locates project root via %~dp0 (this file lives in backend\) to avoid hardcoding Chinese paths
cd /d "%~dp0.."
set "PY=%~dp0..\.update-venv\Scripts\python.exe"
set "SCRIPT=%~dp0update_daily.py"
set "RUNLOG=%~dp0..\data\logs\update_daily_exitcodes.log"

REM ---- 追加式诊断记录（2026-10-14 新增）----
REM 背景：run 被 STATUS_CONTROL_C_EXIT(0xC000013A) 终止于收尾之前，而 Task Scheduler 的
REM Operational 日志默认关闭、启用需管理员权限，拿不到终止事件。这里自留一份
REM 「每次 python 尝试的退出码 + 起止时间」，不需要提权，供看门狗与人工判断。
if not exist "%~dp0..\data\logs" mkdir "%~dp0..\data\logs"

>>"%RUNLOG%" echo [%DATE% %TIME%] attempt=1 start
"%PY%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
>>"%RUNLOG%" echo [%DATE% %TIME%] attempt=1 exit=%RC%
if "%RC%"=="0" exit /b 0

REM first run failed (rc=%RC%) -> wait 60s and retry once (source flakiness)
echo [update_daily] first attempt failed (rc=%RC%), retrying in 60s...
>>"%RUNLOG%" echo [%DATE% %TIME%] attempt=1 FAILED rc=%RC% -^> retry in 60s
timeout /t 60 /nobreak >nul
>>"%RUNLOG%" echo [%DATE% %TIME%] attempt=2 start
"%PY%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
>>"%RUNLOG%" echo [%DATE% %TIME%] attempt=2 exit=%RC%
exit /b %RC%
