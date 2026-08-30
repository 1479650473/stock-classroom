# -*- coding: utf-8 -*-
"""Path helpers for the web API server (frozen/dev safe)."""
import os
import sys

if getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(PROJECT_DIR, "data")
KLINE_DB = os.path.join(DATA_DIR, "kline.db")
CACHE_DB = os.path.join(DATA_DIR, "stock_cache.db")
FUND_DB = os.path.join(DATA_DIR, "fundamental.db")
SIM_DB = os.path.join(DATA_DIR, "sim_trade.db")
CONFIG_DIR = os.path.join(PROJECT_DIR, "backend", "configs")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
PAPER_RUNS_PATH = os.path.join(DATA_DIR, "paper_runs.json")

os.makedirs(DATA_DIR, exist_ok=True)
