@echo off
chcp 65001 >nul
REM update_daily.bat - scheduled daily A-share quant data refresh
REM Uses project venv (.update-venv\Scripts\python.exe) - independent of system Python path
cd /d "D:\小光工作区\projects\stock-classroom"
".update-venv\Scripts\python.exe" "D:\小光工作区\projects\stock-classroom\backend\update_daily.py" %*
