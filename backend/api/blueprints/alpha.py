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


@bp.route("/composite", methods=["GET"])
def composite():
    """固定权重因子组合的候选池（-1日反转/-5日反转/-远离60日高点/-小市值）。"""
    from backend.alpha import composite as C
    ref = request.args.get("date") or None
    top = int_arg(request.args.get("top"), 12, 1, 50)
    return ok(C.snapshot(ref, top_n=top))


@bp.route("/zoo", methods=["GET"])
def zoo():
    """因子体检榜：factor_zoo.py 产出的全量因子指标（IC/中性化/超额/分段稳定）。"""
    import json as _json
    import os as _os
    from ..paths import DATA_DIR
    path = _os.path.join(str(DATA_DIR), "factor_zoo.json")
    if not _os.path.exists(path):
        return ok({"meta": {}, "factors": [], "hint": "尚未运行 factor_zoo.py"})
    with open(path, encoding="utf-8") as f:
        data = _json.load(f)
    top = int_arg(request.args.get("top"), 200, 1, 500)
    sort = str(request.args.get("sort") or "ic")
    rows = data.get("factors") or []
    if sort == "ic_neutral":
        rows.sort(key=lambda r: -abs(float(r.get("ic_neutral") or 0)))
    elif sort == "ex_ann":
        rows.sort(key=lambda r: -float(r.get("ex_ann") or 0))
    else:
        rows.sort(key=lambda r: -abs(float(r.get("ic") or 0)))
    return ok({"meta": data.get("meta") or {}, "sort": sort, "factors": rows[:top]})


@bp.route("/composite_report", methods=["GET"])
def composite_report():
    """组合因子验证报告（composite_test.py 产出：全期指标 + 10 折样本外）。"""
    import json as _json
    import os as _os
    from ..paths import DATA_DIR
    path = _os.path.join(str(DATA_DIR), "alpha_composite.json")
    if not _os.path.exists(path):
        return ok({"meta": {}, "folds": [], "hint": "尚未运行 composite_test.py"})
    with open(path, encoding="utf-8") as f:
        return ok(_json.load(f))


@bp.route("/factor-analysis", methods=["GET"])
def factor_analysis():
    """单因子分析（Alphalens 风格）：分位组合 / 多空 / IC 衰减 / 成本敏感性。

    结果按 (factor, sign, codes, start, end, quantiles) 缓存到 data/，当天重复调用不重算。
    """
    import json as _json
    import os as _os
    from ..paths import DATA_DIR
    factor = str(request.args.get("factor") or "RET20")
    sign = float(request.args.get("sign") or 1)
    codes = int_arg(request.args.get("codes"), 300, 50, 2000)
    quantiles = int_arg(request.args.get("quantiles"), 10, 5, 20)
    start = str(request.args.get("start") or "2016-01-01")
    end = str(request.args.get("end") or "2025-12-31")
    cache = _os.path.join(str(DATA_DIR), f"factor_analysis_{factor}_{'p' if sign > 0 else 'n'}_{codes}_{quantiles}.json")
    if _os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                data = _json.load(f)
            if data.get("meta", {}).get("end") == end.replace("-", ""):
                return ok(data)
        except Exception:
            pass
    from backend.alpha import factor_analysis as FA
    res = FA.analyze(factor, sign, codes=codes, start=start, end=end, quantiles=quantiles)
    if res.get("error"):
        return err(400, "bad_factor", res["error"], retriable=False)
    try:
        with open(cache, "w", encoding="utf-8") as f:
            _json.dump(res, f, ensure_ascii=False)
    except Exception:
        pass
    return ok(res)


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
