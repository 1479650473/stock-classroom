# -*- coding: utf-8 -*-
"""stock-classroom Web API 服务入口 (v5.0 前端的后端).

用法:
    python run_web.py            # 127.0.0.1:5000
    python run_web.py --port 5001
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, os.path.join(ROOT, "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.api.server import create_app


def main():
    port = 5000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        try:
            port = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            pass
    app = create_app()
    print("[stock-classroom] Web API 启动: http://127.0.0.1:%d" % port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
