# -*- coding: utf-8 -*-
"""策略蓝图 —— 展示实盘策略（pali）真正的决策结果。

董事长 2026-10-17 定调：*"开发软件要尽量为策略服务"*。
软件原先的「选股」是 `compute_factor_picks()` 全市场扫描，**与实盘无关**；
本蓝图负责把实盘策略的产出（决策 CSV + 排雷 JSON）如实暴露给界面。

## 只读
所有端点都**只读**策略侧文件，不做任何写操作，也不改策略参数。
参数仅有一个可选的 `date`（查询历史某日决策）。

## 口径
`pred` / `ff20` / `rank` / 排雷 `level` **一律原样透传**，软件侧不加工、不换算。
排雷缺失时标 `UNKNOWN` —— **未知 ≠ PASS**（本项目铁律之九），且 `buyable=false`。
"""
from flask import Blueprint, request

from ..envelope import ok, err
from .. import strategy_source as ss

bp = Blueprint("strategy", __name__, url_prefix="/api/strategy")


@bp.route("/picks")
def picks():
    """实盘策略的最新决策（含每条候选的排雷结论与"可否买入"）。

    查询参数：
      date=YYYYMMDD   可选；不传取最新
    """
    date8 = (request.args.get("date") or "").strip() or None
    if date8 is not None and not (date8.isdigit() and len(date8) == 8):
        return err(400, "bad_date", "date 需为 8 位 yyyymmdd")
    return ok(ss.strategy_picks(date8))


@bp.route("/dates")
def dates():
    """可用的决策日期列表（供界面做历史回看）。"""
    return ok({"dates": ss.list_decisions(60)})


@bp.route("/risk")
def risk():
    """最新一份排雷结果（全量，按 code 索引）。"""
    return ok(ss.latest_risk_check())


@bp.route("/meta")
def meta():
    """策略数据源的健康信息：路径、可用性、**池边界** —— 便于排查"为什么候选少了"。

    注意：`pool.size` 是**当前策略池**的大小（扩池后会变），
    调用方不要假设它是 100。
    """
    import os
    out = ss.output_dir()
    pinfo = ss.pool_info()
    return ok({
        'stockml_dir': ss.SM_DIR,
        'output_dir': out,
        'exists': os.path.isdir(out),
        'pool': pinfo,
        'pool_size': pinfo.get('size'),
        'risk_top_n': ss.RISK_TOP_N,
        'decisions': ss.list_decisions(5),
        'has_risk_check': ss.latest_risk_check().get('available'),
    })


@bp.route("/pool/reload", methods=["POST"])
def reload_pool():
    """池元数据缓存重载 —— **扩池后**若策略侧换了 pool_meta.json，调这个不用重启后端。"""
    ss.recount_pool()
    return ok(ss.pool_info(), message="池元数据已重载")
