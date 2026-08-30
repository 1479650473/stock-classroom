# -*- coding: utf-8 -*-
"""Web API v2 — create_app factory.

Serves the Tauri/Vue frontend. Binds 127.0.0.1 only (local desktop app).
Heavy work goes through the JobManager; all responses use the uniform envelope.
"""
import os
import sys

# Make both flat backend modules (data_manager, akshare_source, indicators, ...)
# and package modules (backend.agent.*, backend.trade_engine.*) importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND = os.path.join(_ROOT, "backend")
for _p in (_ROOT, _BACKEND):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 清除代理环境变量(避免 AKShare 走代理失败), 与 app.py 一致
for _k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"]:
    os.environ.pop(_k, None)

from flask import Flask
from flask_cors import CORS


def create_app():
    app = Flask(__name__)
    CORS(app)

    # 全局异常 -> 统一错误信封(避免裸露 HTML 错误页)
    from .envelope import err

    @app.errorhandler(404)
    def _404(e):
        return err(404, "not_found", "接口不存在")

    @app.errorhandler(405)
    def _405(e):
        return err(405, "method_not_allowed", "方法不允许")

    @app.errorhandler(500)
    def _500(e):
        return err(500, "server_error", "服务器内部错误")

    @app.errorhandler(Exception)
    def _unhandled(e):
        return err(500, "unhandled", str(e))

    from .blueprints import system, jobs_bp, market, trade, kline, picks, overview, research, agentops, pipeline, trainer
    for mod in (system, jobs_bp, market, trade, kline, picks, overview, research, agentops, pipeline, trainer):
        app.register_blueprint(mod.bp)
    # v2 研究交互(回测/因子研究/组合纸面盘/策略对比) — 复用桌面版研究能力
    from .blueprints import research_v2
    app.register_blueprint(research_v2.bp)

    @app.route("/")
    def root():
        return {"service": "stock-classroom-web", "version": "5.0",
                "hint": "前端由 Tauri/Vue 提供; 这里是 API 服务"}

    return app
