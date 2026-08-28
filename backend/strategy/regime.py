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

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HS300_PATH = os.path.join(_ROOT, "data", "hs300.json")
REGIME_PATH = os.path.join(_ROOT, "data", "regime.json")

# 策略-环境适配表 (根据各策略因子特征标注):
#   F价值Tilt / A价值 既攻又守(价值防御), 熊/震荡更稳; B反转/动量 牛市强; C低波动 防御.
STRATEGY_ENV = {
    "牛市": ["F价值Tilt", "D多因子", "B反转"],   # 顺周期/动量/全因子进攻
    "震荡": ["F价值Tilt", "A价值", "C低波动"],   # 价值+低波防御, 少动
    "熊市": ["A价值", "C低波动", "F价值Tilt"],   # 纯价值/低波, 防守优先
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


def run() -> dict:
    """主入口: 读 hs300 → 分类 → 落库 data/regime.json → 返回结果."""
    data = _load_hs300()
    if not data or len(data["closes"]) < 60:
        return {"error": "hs300 数据不足"}
    cls = classify(data["closes"])
    regime_cn = cls["regime_cn"]
    out = {
        "as_of": data["dates"][-1] if data["dates"] else None,
        "regime": cls["regime"], "regime_cn": regime_cn,
        "score": cls["score"], "sys_risk": cls["sys_risk"],
        "suggest_strategy": suggest_strategy(regime_cn),
        "suggest_list": STRATEGY_ENV.get(regime_cn, [DEFAULT_STRATEGY]),
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
