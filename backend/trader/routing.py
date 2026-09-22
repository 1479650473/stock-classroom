# -*- coding: utf-8 -*-
"""结构分类与"客观提示"（借鉴 PA_Agent 的 pattern_routing + prompt_engineering 策略手册）。

PA_Agent 的做法：阶段一把市场归类（trading_range / trending_tr / 通道 / 楔形 / 铁丝网…），
再据此**加载对应的策略文件**（比如震荡区间只做顺 direction 一侧、中间 1/3 不交易）。

我们不做"加载策略文件"这种硬绑定（我们的理念是风格由模型自定），改成**给出分类 + 客观提示**：
  · 分类来自程序算的事实（structure.py 的区间位置/波段结构/突破质量/铁丝网 + bars.py 的棒级信号）；
  · 提示写的是"这类状态下的常见处理与风险"，**不是指令**，模型可以照做也可以不照做。

对 A 股只做多的口径改写（T+1、无做空、涨跌停），分类与提示见 CLASSES。
"""
from __future__ import annotations

#: 分类 → 客观提示（"常见处理 / 主要风险"），全部按 A 股只做多口径改写
CLASSES = {
    "uptrend_pullback": {
        "label": "上升趋势·回踩中",
        "常见处理": "顺结构回踩（不破前低/均线）是趋势里相对低风险的位置。回踩后常见两类入场时机："
                    "**H1**（第一腿回撤后首根突破前棒高点）偏激进，信号棒弱时通常等 **H2**（第二腿后"
                    "再次突破）；H3 常演变为楔形，不宜盲目当 H2 用",
        "主要风险": "跌破最近摆动低点则结构由 HH+HL 转弱；T+1 下当天买不能当天卖",
    },
    "uptrend_breakout": {
        "label": "上升趋势·突破",
        "常见处理": "突破要分层看：**影线试探/收盘未站稳的突破多数失败（资料口径 70~80%）**；"
                    "**收盘站稳且未快速收回的存活突破**，约 60% 能走到区间高度（条件概率，不是任"
                    "何突破都六成能成）。因此常见处理是等「存活」或等回踩不破（回测）再动",
        "主要风险": "A 股涨停买不进、次日高开回落；追高潮（连续大阳后）被套概率高",
    },
    "range_upper": {
        "label": "区间上沿",
        "常见处理": "区间上 1/3 追多的胜率通常低于中下部；等回到中部或下沿再评估",
        "主要风险": "假突破后快速回落；上沿追进往往成为区间内的套牢盘",
    },
    "range_lower": {
        "label": "区间下沿",
        "常见处理": "下沿是观察位而非自动买点：等「下沿 + 结构不再走低 + 信号棒跟随」再考虑",
        "主要风险": "下沿破位后进入下跌趋势；接飞刀的典型亏损形态",
    },
    "range_middle": {
        "label": "区间中部/粘滞",
        "常见处理": "中部 1/3 是两边都不占优的位置。**铁丝网/粘滞区的优先级高于入场信号**："
                    "一旦判定为铁丝网（紧凑度低于阈值、或近 10 根高度重叠+十字星/小实体），"
                    "常见处理是先不参与，等它明确突破或走宽",
        "主要风险": "反复止损（磨人区），交易成本累积",
    },
    "downtrend": {
        "label": "下降趋势/破位",
        "常见处理": "只做多的账户在下行结构里默认空仓等待结构修复",
        "主要风险": "抢反弹被套；跌破箱体下沿后常有连续下杀",
    },
    "failed_breakout": {
        "label": "突破失败/影线试探",
        "常见处理": "影线试探（刺破关键位但收盘收回）、突破后 1~2 根无跟随并回到原区间 —— 这类"
                    "「未确认」突破按资料口径失败率 70~80%，常见处理是等确认或等二次信号（H2/L2）",
        "主要风险": "把试探当突破买入，通常当天/次日即被套；趋势中也有约 80% 的反转尝试会失败",
    },
    "spike": {
        "label": "急涨段（spike）",
        "常见处理": "急涨段本身不追；等它转成通道或区间回踩，位置更好",
        "主要风险": "高潮棒后常见急速回撤；A 股情绪股尤其明显",
    },
    "unknown": {"label": "状态不明", "常见处理": "数据或结构不足以归类，谨慎对待", "主要风险": "误解结构"},
}

#: 给模型看的路由表（紧凑版，进上下文）
TABLE_TEXT = "结构分类参考（程序按客观特征归类，提示是常见处理与风险，不是指令）：\n" + "\n".join(
    f"· {v['label']}：{v['常见处理']}｜风险：{v['主要风险']}" for k, v in CLASSES.items()
    if k != "unknown")


def classify(structure: dict, bars: dict | None = None) -> str:
    """按结构 + 棒级事实归类（顺序即优先级）。"""
    s = structure or {}
    b = bars or {}
    if not s.get("ok"):
        return "unknown"
    pos = s.get("position")
    struct = str(s.get("swing_structure") or "")
    bq = str(s.get("breakout_quality") or "none")
    bw = bool(s.get("barbwire"))
    last = (b.get("last") or {}) if isinstance(b, dict) else {}
    # 急涨：最新一根波动 ≥2.5×ATR 且近期连阳，或 5 日累计涨幅显著
    try:
        rng_atr = float(last.get("range_atr") or 0)
        streak = int(b.get("streak") or 0)
    except Exception:
        rng_atr, streak = 0.0, 0
    if bq == "broke_down" or (struct.startswith("下降") and (pos or 1) <= 0.35):
        return "downtrend"
    if bq in ("failed", "wick_probe"):
        return "failed_breakout"
    if rng_atr >= 2.5 and streak >= 2:
        return "spike"
    if bq in ("surviving", "close_breakout") and struct.startswith("上升"):
        return "uptrend_breakout"
    if struct.startswith("上升"):
        if pos is not None and pos >= 0.75:
            return "uptrend_breakout" if bq in ("surviving", "close_breakout") else "range_upper"
        if pos is not None and pos <= 0.35:
            return "uptrend_pullback"
        return "uptrend_pullback" if not bw else "range_middle"
    if bw or (pos is not None and 0.35 < pos < 0.75):
        return "range_middle"
    if pos is not None and pos >= 0.667:
        return "range_upper"
    if pos is not None and pos <= 0.333:
        return "range_lower"
    return "unknown"


def note_for(key: str) -> str:
    c = CLASSES.get(key) or CLASSES["unknown"]
    return f"{c['label']}——{c['常见处理']}（风险：{c['主要风险']}）"


def classify_code(code: str, as_of: str) -> dict:
    """一只股票的分类结果（结构 + 棒级一起看）。"""
    try:
        from . import structure as st_mod, bars as bars_mod
        s = st_mod.compute_cached(code, as_of)
        b = bars_mod.compute(code, as_of, n=30)
    except Exception:
        return {"ok": False, "key": "unknown", "label": CLASSES["unknown"]["label"]}
    if not s.get("ok"):
        return {"ok": False, "key": "unknown", "label": CLASSES["unknown"]["label"], "note": s.get("reason", "")}
    key = classify(s, b)
    return {"ok": True, "key": key, "label": CLASSES[key]["label"], "note": note_for(key),
            "position": s.get("position"), "structure": s.get("swing_structure"),
            "breakout_quality": s.get("breakout_quality"), "barbwire": s.get("barbwire")}
