# -*- coding: utf-8 -*-
"""Research blueprint — regime, metrics, strategy describe."""
from flask import Blueprint, request

from ..envelope import ok, err

bp = Blueprint("research", __name__, url_prefix="/api/research")


@bp.route("/regime", methods=["GET"])
def get_regime():
    """Current market regime (bull/bear/range) from HS300."""
    try:
        from backend.strategy.regime import run as regime_run
        data = regime_run()
        return ok(data)
    except Exception as e:
        return err(500, "regime_failed", str(e), retriable=False)


@bp.route("/metrics", methods=["POST"])
def compute_metrics():
    """Compute full metrics from a NAV sequence."""
    body = request.get_json(force=True, silent=True) or {}
    nav = body.get("nav")
    if not nav or not isinstance(nav, list) or len(nav) < 2:
        return err(400, "bad_nav", "nav must be a list with >=2 points", retriable=False)
    try:
        from backend.strategy.metrics import full_metrics
        bench = body.get("bench")
        dates = body.get("dates")
        result = full_metrics(nav, bench=bench, dates=dates)
        return ok(result)
    except Exception as e:
        return err(500, "metrics_failed", str(e), retriable=False)


@bp.route("/strategy/describe", methods=["POST"])
def describe_strategy():
    """Describe a strategy contract in Chinese."""
    body = request.get_json(force=True, silent=True) or {}
    if not body:
        return err(400, "empty_body", "empty body", retriable=False)
    try:
        from backend.strategy.describe import describe_contract
        data = describe_contract(body)
        return ok(data)
    except Exception as e:
        return err(500, "describe_failed", str(e), retriable=False)


@bp.route("/factors", methods=["GET"])
def get_factors():
    """List available factor groups and descriptions."""
    factors = [
        {"id": "BP", "name": "市净率倒数", "group": "价值", "desc": "股价/每股净资产的倒数，越高越便宜"},
        {"id": "EP", "name": "市盈率倒数", "group": "价值", "desc": "每股收益/股价，越高越便宜"},
        {"id": "REVERSAL_20", "name": "20日反转", "group": "动量", "desc": "过去20日收益率取反，捕捉超跌反弹"},
        {"id": "REVERSAL_60", "name": "60日反转", "group": "动量", "desc": "过去60日收益率取反"},
        {"id": "VOLATILITY_20", "name": "20日波动率", "group": "风险", "desc": "20日收益率标准差，低波优先"},
        {"id": "VOLUME_RATIO", "name": "量比", "group": "情绪", "desc": "当日成交量/5日均量"},
        {"id": "PRICE_POS", "name": "价格位置", "group": "技术", "desc": "当前价在20日高低点中的位置"},
    ]
    return ok(factors)


@bp.route("/strategies", methods=["GET"])
def get_strategies():
    """List available strategy contracts with Chinese descriptions (真实5策略, 与桌面版一致)."""
    try:
        from frontend.plugins.research.worker import _strategy_contracts
        from backend.strategy.describe import describe_contract
        out = []
        for name, c in _strategy_contracts(20).items():
            desc = ""
            try:
                d = describe_contract(c)
                desc = d.get("summary") or d.get("desc") or str(d)
            except Exception:
                try:
                    desc = " + ".join(c.factors)
                except Exception:
                    desc = ""
            # 安全转 str(避免前端收到 list/dict 无法渲染)
            facs = [str(x) for x in (getattr(c, "factors", None) or [])]
            out.append({
                "id": name, "name": name, "kind": "multi_factor" if len(facs) > 1 else "single",
                "factors": facs, "desc": desc or f"{' + '.join(facs)} 多因子策略",
                "rebalance_bars": getattr(c, "rebalance_bars", 20),
                "top_k_pct": getattr(c, "top_k_pct", 0.2),
                "use_tilt": getattr(c, "use_tilt", False),
            })
        return ok(out)
    except Exception as e:
        return err(500, "strategies_failed", str(e), retriable=False)
