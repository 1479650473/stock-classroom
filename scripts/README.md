# 定时任务配置

每日收盘后自动更新 A 股 K 线数据。

## 安装定时任务

```powershell
# 以管理员身份运行
schtasks /CREATE /XML "D:\小光工作区\projects\stock-classroom\scripts\daily_stock_update.xml" /TN "叶初\每日股票数据更新"
```

## 手动运行

```powershell
powershell -ExecutionPolicy Bypass -File "D:\小光工作区\projects\stock-classroom\scripts\update_daily.ps1"
```

或：

```cmd
D:\小光工作区\projects\stock-classroom\scripts\update_daily.bat
```

## 任务配置

- 触发器：每天 16:00（收盘后），重复每 5 分钟，持续 30 分钟
- 操作：`powershell.exe -ExecutionPolicy Bypass -File scripts\update_daily.ps1`
- 失败时：每隔 5 分钟重试一次，最多 3 次

## 日志

更新日志写入 `scripts/update_daily.log`，每次运行追加。
