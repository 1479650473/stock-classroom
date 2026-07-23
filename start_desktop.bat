@echo off
chcp 65001 >nul
cd /d "D:\小光工作区\projects\stock-classroom"
echo.
echo === stock-classroom v4.0 ===
echo 启动中...
echo.
C:\Python314\python.exe desktop_app.py
if errorlevel 1 (
  echo.
  echo 启动失败，查看上方错误信息
  pause >nul
)
pause
