# -*- coding: utf-8 -*-
"""Report blueprint — 回测/因子报告（自包含 HTML，浏览器可直接打开或另存）。

GET  /api/report/composite?date=     固定权重因子组合的验证报告（全期 + 10 折样本外）
GET  /api/report/factor-zoo          因子体检榜报告（Top 因子表）
POST /api/report/backtest            通用：提交 {title, dates, equity|returns, metrics, trades} → HTML
"""
from __future__ import annotations

import json
import os

from flask import Blueprint, Response, request

from ..envelope import ok, err, int_arg
from ..paths import DATA_DIR

bp = Blueprint("report", __name__, url_prefix="/api/report")


def _html(body: str, filename: str = "") -> Response:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if filename:
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return Response(body, headers=headers)


@bp.route("/composite", methods=["GET"])
def composite_report():
    """因子组合验证报告（读 data/alpha_composite.json）。"""
    from backend.strategy.report import build_report
    path = os.path.join(str(DATA_DIR), "alpha_composite.json")
    if not os.path.exists(path):
        return err(404, "not_found", "尚未生成组合验证报告（先运行 composite_test.py）", retriable=False)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    folds = data.get("folds") or []
    meta = data.get("meta") or {}
    full = data.get("full") or {}
    # 用每折样本外超额拼一条等权"组合净值曲线"（近似直观展示）
    eq, dates = [1.0], []
    for f in folds:
        eq.append(eq[-1] * (1.0 + float(f.get("oos_ex") or 0.0)))
        dates.append(str(f.get("test", "")).split("~")[-1])
    trades = [{"date": f.get("test"), "code": f"折{f.get('fold')}", "name": "样本外超额",
               "side": "", "qty": "", "price": "",
               "pnl": f"{float(f.get('oos_ex') or 0) * 100:+.1f}%",
               "pnl_pct": f"{float(f.get('oos_sortino') or 0):+.2f}",
               "reason": f"IC {float(f.get('oos_ic') or 0):+.4f} / 回撤 {float(f.get('oos_dd') or 0) * 100:.1f}%"}
              for f in folds]
    body = build_report(
        title="因子组合验证报告",
        subtitle=f"组合：{' '.join(meta.get('components') or [])} · 持有 {meta.get('hold')} 天 · "
                 f"Top{meta.get('top_k')} · 成本单边 5bp",
        series=eq, dates=dates, metrics=full, trades=trades,
        notes=("口径：等权 rank 合成，无搜索无挑选偏差；每折独立（训练窗口只用于选公式，"
               "测试窗口只用于评估）。曲线为各折样本外超额串起来，仅用于直观展示稳定性，"
               "不代表连续实盘净值。"))
    return _html(body, "alpha_composite_report.html")


@bp.route("/factor-zoo", methods=["GET"])
def factor_zoo_report():
    """因子体检榜报告（读 data/factor_zoo.json）。"""
    from backend.strategy.report import build_report
    path = os.path.join(str(DATA_DIR), "factor_zoo.json")
    if not os.path.exists(path):
        return err(404, "not_found", "尚未生成因子体检（先运行 factor_zoo.py）", retriable=False)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    meta = data.get("meta") or {}
    rows = sorted(data.get("factors") or [], key=lambda r: -abs(float(r.get("ic_neutral") or 0)))
    top = int_arg(request.args.get("top"), 30, 1, 200)
    picks = rows[:top]
    trades = [{"date": r.get("factor"),
               "code": f"IC(中性) {float(r.get('ic_neutral') or 0):+.4f}",
               "name": f"IC(1日) {float(r.get('ic') or 0):+.4f}",
               "side": f"IC(20日) {float(r.get('ic20') or 0):+.4f}",
               "qty": f"{float(r.get('ex_ann') or 0) * 100:+.1f}%",
               "price": f"{float(r.get('ex_neutral') or 0) * 100:+.1f}%",
               "pnl": f"{float(r.get('ex_sortino') or 0):+.2f}",
               "pnl_pct": f"{float(r.get('maxdd') or 0) * 100:.1f}%",
               "reason": f"半年为正 {r.get('seg_pos')}/{int(r.get('n_seg') or 0) - 1}"}
              for r in picks]
    body = build_report(
        title="因子体检榜",
        subtitle=(f"{meta.get('codes')} 只 × {meta.get('days')} 日 · Top{top} · "
                  f"等权池年化 {(float(meta.get('pool_ann') or 0)) * 100:+.1f}%"
                  " · 列：因子 / IC(中性) / IC(1日) / IC(20日) / 超额年化 / 超额(中性) / Sortino / 回撤 / 半年为正"),
        series=[1.0] + [1.0 + float(r.get("ic_neutral") or 0) for r in picks[:60]],
        metrics={"days": float(meta.get("days") or 0)},
        trades=trades,
        notes=("判读：IC(中性) 是剥离市值/波动后的排序预测力，|IC| ≥ 0.005 才算有信号；"
               "「超额为正但多空价差为负」的因子（如低波动类）是风格 beta，不是选股能力。"))
    return _html(body, "factor_zoo_report.html")


@bp.route("/backtest", methods=["POST"])
def backtest_report():
    """通用报告：前端把回测结果 POST 上来，直接返回可打开的 HTML。"""
    from backend.strategy.report import build_report
    body = request.get_json(force=True, silent=True) or {}
    series = body.get("equity") or body.get("returns") or body.get("series")
    if not series:
        return err(400, "bad_request", "缺少 equity / returns 序列", retriable=False)
    html_body = build_report(
        title=str(body.get("title") or "回测报告"),
        subtitle=str(body.get("subtitle") or ""),
        series=series, dates=body.get("dates"), metrics=body.get("metrics") or {},
        trades=body.get("trades"), notes=body.get("notes"))
    return _html(html_body, "backtest_report.html")
