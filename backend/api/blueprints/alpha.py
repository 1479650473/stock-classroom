# -*- coding: utf-8 -*-
"""Alpha blueprint — 因子公式挖掘（AlphaGPT 式：公式搜索 + 回测奖励）。

POST /api/alpha/mine              启动一次挖掘 (job，进度走 /api/jobs/<id>/stream)
POST /api/alpha/walkforward       启动滚动窗口验证 (job)
GET  /api/alpha/runs              历史运行列表（默认最近 20 次）
GET  /api/alpha/run/<id>          单次运行详情（含产出的公式与指标）
GET  /api/alpha/meta              可选参数与默认值（前端表单用）
"""
from __future__ import annotations

from flask import Blueprint, request

from ..envelope import ok, err, int_arg
from .. import jobman

bp = Blueprint("alpha", __name__, url_prefix="/api/alpha")

_INT_KEYS = ("codes", "pop", "gens", "max_nodes", "topk", "hold", "top", "folds",
             "train_months", "test_months", "combo")


def _payload(body: dict, kind: str) -> dict:
    p = {"kind": kind}
    for k in _INT_KEYS:
        if body.get(k) is not None:
            try:
                p[k] = int(body[k])
            except (TypeError, ValueError):
                pass
    for k in ("start", "end"):
        if body.get(k):
            p[k] = str(body[k])
    if body.get("train_ratio") is not None:
        try:
            p["train_ratio"] = float(body["train_ratio"])
        except (TypeError, ValueError):
            pass
    return p


def _runner(payload, on_progress):
    from backend.alpha import pipeline as PL
    payload = dict(payload or {})
    kind = payload.pop("kind", "mine")
    if kind == "walkforward":
        return PL.walk_forward(payload, progress=lambda ev: on_progress(ev))
    return PL.mine(payload, progress=lambda ev: on_progress(ev))


@bp.route("/meta", methods=["GET"])
def meta():
    from backend.alpha.pipeline import DEFAULTS
    from backend.alpha.panel import FEATURE_NAMES
    from backend.alpha.dsl import OPS
    return ok({"defaults": DEFAULTS, "features": list(FEATURE_NAMES),
               "operators": list(OPS.keys())})


@bp.route("/mine", methods=["POST"])
def mine():
    body = request.get_json(force=True, silent=True) or {}
    job = jobman.submit("alpha", _runner, _payload(body, "mine"))
    return ok({"job": job})


@bp.route("/walkforward", methods=["POST"])
def walkforward():
    body = request.get_json(force=True, silent=True) or {}
    job = jobman.submit("alpha", _runner, _payload(body, "walkforward"))
    return ok({"job": job})


@bp.route("/runs", methods=["GET"])
def runs():
    from backend.alpha import store
    kind = request.args.get("kind") or None
    limit = int_arg(request.args.get("limit"), 20, 1, 200)
    items = store.list_runs(limit=limit, kind=kind)
    for it in items:                       # 列表里不带大字段，减小响应
        it.pop("history", None)
    return ok({"items": items})


@bp.route("/run/<int:rid>", methods=["GET"])
def run_detail(rid: int):
    from backend.alpha import store
    d = store.get_run(rid)
    if d is None:
        return err(404, "not_found", "运行不存在", retriable=False)
    return ok(d)
