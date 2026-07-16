@echo off
REM =============================================
REM 每日收盘后数据维护 (2026-07-13 v2.0)
REM 使用 daily_maintenance.py 全量更新
REM 通过 Task Scheduler 自动触发（周一~周五 16:00）
REM =============================================
cd /d "D:\小光工作区\projects\stock-classroom"
python scripts\daily_maintenance.py
