# -*- coding: utf-8 -*-
import os, sys, time, webbrowser, threading

BASE = os.path.dirname(os.path.abspath(__file__))

# Find backend/ in exe dir or _internal/
BE = os.path.join(BASE, "_internal", "backend")
if not os.path.isdir(BE):
    BE = os.path.join(BASE, "backend")
if os.path.isdir(BE):
    sys.path.insert(0, BE)
DD = os.path.join(BASE, "data")

# Clean proxy
for k in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"]:
    os.environ.pop(k, None)
os.environ["no_proxy"] = "*"

print(f"[SC] Data: {DD}")

import app, data_manager

# Patch DB paths
app.DB_PATH       = os.path.join(DD, "stock_cache.db")
app.KLINE_DB_PATH = os.path.join(DD, "kline.db")
data_manager.KLINE_DB  = os.path.join(DD, "kline.db")
data_manager.CACHE_DB  = os.path.join(DD, "stock_cache.db")
data_manager.DATA_DIR  = DD

print("[SC] http://127.0.0.1:5000")
t = threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open("http://127.0.0.1:5000")), daemon=True)
t.start()
app.app.run(host="127.0.0.1", port=5000)
