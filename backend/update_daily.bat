@echo off
REM update_daily.bat — Windows 计划任务入口: 每日收盘后自动刷新 A股量化数据
REM 调用 backend\update_daily.py (K线池+基本面+纸面盘), 完成后写 data\update_marker.json
cd /d "D:\小光工作区\projects\stock-classroom"
"C:\Python314\python.exe" "D:\小光工作区\projects\stock-classroom\backend\update_daily.py" %*
