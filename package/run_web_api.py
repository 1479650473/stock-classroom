# -*- coding: utf-8 -*-
"""Web API 后端 PyInstaller 入口 (打包为单文件 sidecar).

Tauri 壳启动时拉起本程序(127.0.0.1:5000), 前端同源访问。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    ROOT = os.path.dirname(sys.executable)

for _p in (ROOT, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 确保 data/ 与 configs 指向 exe 旁
os.environ.setdefault("SC_WORKDIR", ROOT)

from backend.api.server import create_app

if __name__ == "__main__":
    port = 5000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        try:
            port = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            pass
    app = create_app()
    print(f"[stock-api] listening on 127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
