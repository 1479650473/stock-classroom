# scripts/ — 辅助脚本

> 每日数据自动化已统一到 **`backend/update_daily.py`**（由 Windows 计划任务 `StockClassroom-DailyUpdate`
> 调用 `backend/update_daily.bat` 执行，触发时间 17:00）。

## 每日数据更新（当前）

```bat
rem 手动跑一次（使用项目固定 venv .update-venv）
backend\update_daily.bat

rem 只更新量化池 K 线（跳过基本面/纸面盘等）
backend\update_daily.bat --pool-only
```

流程：全市场 K 线增量 → 基本面 → 纸面盘 → 净值快照 → regime → 事件驱动池 → 个股深挖
→ 持仓守护(预览) → **AI 操盘手决策**。结果写入 `data/update_marker.json` 与 `logs/update_daily_YYYYMMDD.log`。

## 已移除的旧脚本

`daily_maintenance.py` / `update_daily.ps1` / `update_daily.bat` / `daily_stock_update.xml` 属于旧架构
（依赖已删除的 `run_server.py` + `backend/app.py` 旧 API，且未安装到系统任务），已删除。

## 其他

- `generate_logo.py`：一次性生成项目 logo 资源。
