# 叶瞬光量化选股系统

A 股量化选股桌面应用。Flask 后端 + PyQt5 桌面端 + SQLite 本地缓存。

## 快速启动

```bash
# 1. 启动后端 (端口 5000)
C:\Python314\python.exe run_server.py

# 2. 启动桌面端 (另一个窗口)
C:\Python314\python.exe desktop_app.py
# 或双击 start_desktop.bat
```

## 系统要求

- Python 3.14+
- 依赖: `pip install -r requirements.txt`
- 磁盘: ~600MB (含数据库)

## 文档

- **[TECH_MANUAL.md](TECH_MANUAL.md)** — 完整技术手册（架构、模块、问题记录）
- **[选股体系-数据需求梳理.md](选股体系-数据需求梳理.md)** — 数据需求文档
- **[数据字典/](数据字典/)** — AKShare 数据字典

## 项目结构

```
├─ run_server.py       Flask 后端入口
├─ desktop_app.py      PyQt5 桌面主程序
├─ frontend/           前端组件
│  ├─ kline_chart_v2.py  K线图组件
│  └─ panels/            独立面板模块
├─ backend/            后端数据层
│  ├─ app.py             Flask API
│  ├─ data_manager.py    数据管理
│  └─ indicators.py      技术指标
├─ data/               数据库
│  ├─ kline.db           (505MB, 341万行)
│  └─ stock_cache.db
├─ scripts/            数据维护
└─ docs/               文档
```

*详细说明见 [TECH_MANUAL.md](TECH_MANUAL.md)*
