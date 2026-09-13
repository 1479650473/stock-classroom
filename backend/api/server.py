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

from flask import Flask, Response
from flask_cors import CORS


def create_app():
    app = Flask(__name__)
    # 本地桌面应用: 只允许 Tauri webview 与 vite dev origin
    CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173",
                       "tauri://localhost", "https://tauri.localhost"])

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
    # Agent 操盘台 (SSE tool-calling 聊天)
    from .blueprints import agent_chat
    app.register_blueprint(agent_chat.bp)
    # 自主策略进化闭环 (分阶段 job)
    from .blueprints import optimize
    app.register_blueprint(optimize.bp)
    # AI 定时自主交易 (后台线程)
    from .blueprints import scheduler_bp
    app.register_blueprint(scheduler_bp.bp)
    scheduler_bp.ensure_started()
    # 策略回放器 (K线逐日回放: 买卖点/持仓高亮)
    from .blueprints import replay
    app.register_blueprint(replay.bp)
    # AI 操盘手 (长期自主 LLM 交易员: 专属账户 + 每日决策 + 长期记忆)
    from .blueprints import trader
    app.register_blueprint(trader.bp)
    # 因子挖掘 (公式搜索 + 回测奖励, AlphaGPT 式)
    from .blueprints import alpha
    app.register_blueprint(alpha.bp)
    # 回测/因子报告 (自包含 HTML)
    from .blueprints import report as report_bp
    app.register_blueprint(report_bp.bp)
    # 通知/告警 (任务失败、每日自动化异常、webhook 可选)
    from .blueprints import notify_bp
    app.register_blueprint(notify_bp.bp)
    # ETF (全市场列表/单只K线/多只归一化对比)
    from .blueprints import etf
    app.register_blueprint(etf.bp)
    # 个股资金流日频 (历史查询)
    from .blueprints import fund_flow
    app.register_blueprint(fund_flow.bp)
    # Agent Gateway v1 (/api/agent/v1) — 能力分级 R/W/B/T + 审计/幂等/限流，供外部 agent/MCP 调用
    from backend.agent.routes import register as register_agent_gateway
    register_agent_gateway(app)
    from backend.agent import store as agent_store
    agent_store.ensure_schema()

    # Prometheus 指标（文本格式）+ JSON 视图（供前端/看板）
    @app.route("/metrics")
    def metrics_endpoint():
        from backend import metrics as _m
        return Response(_m.render_prometheus(_m.collect()), mimetype="text/plain; version=0.0.4")

    @app.route("/api/system/metrics")
    def metrics_json():
        from backend import metrics as _m
        return {"code": 0, "data": _m.collect(), "message": "ok"}

    @app.route("/")
    def root():
        return {"service": "stock-classroom-web", "version": "5.1",
                "hint": "前端由 Tauri/Vue 提供; 这里是 API 服务"}

    return app
