# -*- coding: utf-8 -*-
"""Path helpers for the web API server (frozen/dev safe)."""
import os
import sys

if getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 打包后数据的默认位置不变(exe旁 data/), 外壳可通过环境变量改为本地用户目录
DATA_DIR = os.environ.get("SC_DATA_DIR") or os.path.join(PROJECT_DIR, "data")
KLINE_DB = os.path.join(DATA_DIR, "kline.db")
CACHE_DB = os.path.join(DATA_DIR, "stock_cache.db")
FUND_DB = os.path.join(DATA_DIR, "fundamental.db")
FUND_ARB_DB = os.path.join(DATA_DIR, "fund_arb.db")
SIM_DB = os.path.join(DATA_DIR, "sim_trade.db")
CONFIG_DIR = os.path.join(PROJECT_DIR, "backend", "configs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
PAPER_RUNS_PATH = os.path.join(DATA_DIR, "paper_runs.json")

os.makedirs(DATA_DIR, exist_ok=True)
