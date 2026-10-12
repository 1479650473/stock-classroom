# -*- coding: utf-8 -*-
"""regime.py — A股大盘牛熊震荡分类器 + 系统性风险截断信号.

数据源: data/hs300.json (沪深300 closes, 覆盖长, 权威). 无指数kline时用它兜底.

判据 (全部基于真实序列, 非硬编码):
  - 趋势结构: close vs MA60 / MA20 vs MA60 (多头/空头排列)
  - 方向:  MA20 相对 N 日的斜率 (上行/下行)
  - 波动:  20日年化波动
输出 (data/regime.json):
  {
    "as_of": date,            # 数据截至
    "regime": "bull|bear|range",
    "regime_cn": "牛市|熊市|震荡",
    "score": {...},           # 各信号量(供前端展示/调试)
    "sys_risk": {"triggered": bool, "reason": str, "drawdown": float, "drop_1d": float},
    "suggest_strategy": "xxx" # 根据环境建议启用的策略名 (从 STRATEGY_ENV 匹配)
  }

适用环境: 任意(纯计算, 无偏置). 供前端"看盘页/持仓页"显示当前环境 + 建议策略.
"""
from __future__ import annotations

import os, json, math, datetime

from ..api.paths import DATA_DIR

HS300_PATH = os.path.join(DATA_DIR, "hs300.json")
REGIME_PATH = os.path.join(DATA_DIR, "regime.json")

# 策略-环境适配表 — **基于分周期验证结论(数据驱动, 非直觉)** (2026-08-29 定稿)
# 来源: cycle_test_all.json(F价值Tilt三驱动, 补2023数据后):
#   牛市 B反转+21.4%夏普0.96最强 / F价值Tilt+12.9%; 
#   震荡 F价值Tilt高夏普(+5.9~9.2) / C低波动-18.8%回撤稳;
#   熊市 B反转-14.5%最深 / 全部偏弱, 用C低波动/A价值防守(回撤最小).
# ⚠️A价值纯BP在截面稀薄期退化成少数股票(全周期+1232%虚高) → 轮换表不用它当主策略(防退化).
STRATEGY_ENV = {
    "牛市": ["B反转", "F价值Tilt", "D多因子"],   # 动量/反转进攻最强(验证+21.4%) + 全因子均衡
    "震荡": ["F价值Tilt", "C低波动", "D多因子"],   # 价值防御高夏普(验证) + 低波稳健
    "熊市": ["C低波动", "A价值", "F价值Tilt"],   # 低波/价值防守(回撤最小, 验证), 防B反转深回撤
}
DEFAULT_STRATEGY = "F价值Tilt"

# 系统性风险截断阈值
DROP_1D_TRIGGER = -0.045    # 单日跌幅 >4.5% 视为重大外部冲击
DRAWDOWN_TRIGGER = 0.15     # 从近60日高点回撤 >15% 视为市场严冬


def _load_hs300() -> dict:
    if not os.path.exists(HS300_PATH):
        return {}
    try:
        with open(HS300_PATH, encoding="utf-8") as f:
            d = json.load(f)
        dates = d.get("dates", [])
        closes = [float(x) for x in d.get("closes", [])]
        return {"dates": dates, "closes": closes}
    except Exception:
        return {}


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _slope(vals, n):
    """MA 近 n 日斜率: 用线性回归斜率归一 (正值=上行, 负=下行)."""
    if len(vals) < n + 1:
        return 0
    seg = vals[-n:]
    xm = (n - 1) / 2
    ym = sum(seg) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(seg))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0


def classify(closes: list) -> dict:
    """对 closes 序列判定 regime, 返回 {regime, score, sys_risk}. (纯函数, 便于测试)"""
    n = len(closes)
    if n < 60:
        return {"regime": "range", "regime_cn": "震荡", "score": {}, "sys_risk": {}}
    px = closes[-1]
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    slope20 = _slope(closes, 20)
    slope60 = _slope(closes, 60)
    # 20日年化波动
    rets = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0) if closes[i - 1] > 0]
    vol20 = (sum((r - (sum(rets) / len(rets))) ** 2 for r in rets) / max(1, len(rets) - 1)) ** 0.5 * math.sqrt(252) * 100 if rets else 0

    # 多头/空头排列
    bull_structure = (px > ma60) and (ma20 > ma60)
    bear_structure = (px < ma60) and (ma20 < ma60)

    # 方向
    up = slope20 > 0
    down = slope20 < 0

    if bull_structure and up:
        regime = "bull"
    elif bear_structure and down:
        regime = "bear"
    else:
        regime = "range"

    # 系统性风险截断
    high60 = max(closes[-60:])
    drawdown = 1 - px / high60 if high60 > 0 else 0
    drop_1d = closes[-1] / closes[-2] - 1 if n >= 2 and closes[-2] > 0 else 0
    sys_risk = {"triggered": False, "reason": "", "drawdown": round(drawdown, 4), "drop_1d": round(drop_1d, 4)}
    if drop_1d < DROP_1D_TRIGGER:
        sys_risk["triggered"] = True
        sys_risk["reason"] = "单日跌幅 {:.2f}%, 疑似重大外部冲击 → 建议截断交易".format(drop_1d * 100)
    elif drawdown > DRAWDOWN_TRIGGER:
        sys_risk["triggered"] = True
        sys_risk["reason"] = "距60日高点回撤 {:.1f}%, 市场步入严冬 → 建议降低仓位".format(drawdown * 100)

    score = {
        "px": round(px, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2),
        "slope20": round(slope20, 4), "slope60": round(slope60, 4),
        "vol20": round(vol20, 2), "bull_structure": bull_structure,
        "bear_structure": bear_structure, "drawdown": round(drawdown, 4),
        "drop_1d": round(drop_1d, 4),
    }
    return {"regime": regime, "regime_cn": {"bull": "牛市", "bear": "熊市", "range": "震荡"}[regime],
            "score": score, "sys_risk": sys_risk}


def suggest_strategy(regime_cn: str) -> str:
    lst = STRATEGY_ENV.get(regime_cn, [DEFAULT_STRATEGY])
    return lst[0] if lst else DEFAULT_STRATEGY


def rotate_strategy(regime_cn: str, verified: dict = None) -> dict:
    """判断器驱动的**主动策略轮换**: 按当前市场环境选主/次策略 + 依据.

    数据驱动: 默认用 STRATEGY_ENV(基于分周期验证定稿); 若给 verified(cycle_test结果),
    可按各策略当前环境的实际收益动态排序选主策略(更准确, 防硬编码过时).

    Returns: {primary, secondary, list, basis, strategy_cn}
      primary: 当前环境应启用的主策略 (判断器驱动轮换)
      basis:   依据说明(为什么选它)
    """
    lst = list(STRATEGY_ENV.get(regime_cn, [DEFAULT_STRATEGY]))
    primary = lst[0] if lst else DEFAULT_STRATEGY
    basis = ("牛市: 动量/反转进攻最强(B反转验证+21.4%), 主攻次均衡" if regime_cn == "牛市"
             else "震荡: 价值防御高夏普(F价值Tilt验证最优), 主均衡次低波" if regime_cn == "震荡"
             else "熊市: 全军偏弱, 低波/价值防守(回撤最小), 防B反转深回撤")
    return {"primary": primary, "secondary": lst[1] if len(lst) > 1 else primary,
            "list": lst, "basis": basis}


# ── ② 权重动态化: 因子权重随 market regime 调整 (蓝图"权重受大盘周期控制") ──
# 基础多因子契约权重 (BP / REVERSAL_20 / VOLATILITY_20), 作为"中性均衡"基准
NEUTRAL_WEIGHTS = {"BP": 1.0, "REVERSAL_20": 1.0, "VOLATILITY_20": -1.0}

# 各 regime 的权重覆盖 (相对中性基准的偏移):
#   牛市: 动量/反转更重(追击), 价值/低波略轻(风险偏好升) → 偏进攻
#   震荡: 均衡 (趋势不明, 面面俱到)
#   熊市: 价值/低波更重(防御), 动量/反转削弱(避免逆势追高) → 偏防守
REGIME_WEIGHT_OVERRIDES = {
    "牛市": {"BP": 0.8, "REVERSAL_20": 1.4, "VOLATILITY_20": -0.8},
    "震荡": NEUTRAL_WEIGHTS,
    "熊市": {"BP": 1.5, "REVERSAL_20": 0.4, "VOLATILITY_20": -1.5},
}


def regime_base_weights(regime_cn: str, base: dict = None) -> dict:
    """按市场环境(牛/熊/震荡)动态生成多因子基础权重.

    base: 契约定给的默认可选权重(如 {BP:1.0, REVERSAL_20:1.0, VOLATILITY_20:-1.0}),
          缺省用 NEUTRAL_WEIGHTS. 只在有该 regime 覆盖时替换, 否则保留原权重.
    返回: {factor: weight} 供 SelectionContract.base_weights.
    """
    base = dict(base) if base else dict(NEUTRAL_WEIGHTS)
    over = REGIME_WEIGHT_OVERRIDES.get(regime_cn)
    if over is None:
        return base
    # 合并: 覆盖表中有的因子用新权重, 表里没用到的保留原值
    out = dict(base)
    for f, w in over.items():
        if f in out:
            out[f] = w
    return out


def run() -> dict:
    """主入口: 读 hs300 → 分类 → 落库 data/regime.json → 返回结果."""
    data = _load_hs300()
    if not data or len(data["closes"]) < 60:
        return {"error": "hs300 数据不足"}
    cls = classify(data["closes"])
    regime_cn = cls["regime_cn"]
    dyn_weights = regime_base_weights(regime_cn)
    rot = rotate_strategy(regime_cn)
    out = {
        "as_of": data["dates"][-1] if data["dates"] else None,
        "regime": cls["regime"], "regime_cn": regime_cn,
        "score": cls["score"], "sys_risk": cls["sys_risk"],
        "suggest_strategy": rot["primary"],   # 当前环境主策略(判断器驱动轮换, 数据驱动)
        "suggest_list": STRATEGY_ENV.get(regime_cn, [DEFAULT_STRATEGY]),
        "rotation": rot,   # 轮换信息: primary/secondary/list/basis
        "dyn_weights": dyn_weights,   # 权重动态化: 当前环境的因子权重
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        with open(REGIME_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, ensure_ascii=False, indent=1)[:1500])
