# -*- coding: utf-8 -*-
"""逐 bar 因子计算 — 为回测器构建每根 K 线的 `values` 字典。

KEY 全部大写，与 factor_engine/dsl.evaluate 的 args 对应。包含：
  基础价量: CLOSE/OPEN/HIGH/LOW/VOLUME/AMOUNT
  均线:     MA5/MA10/MA20/MA60
  MACD:     MACD_DIF/MACD_DEA/MACD_HIST
  摆动:     RSI6/RSI14
  布林:     BOLL_UPPER/BOLL_MID/BOLL_LOWER
  派生:     CHANGE_PCT/VOL_RATIO_5/PRICE_POS_20
  布尔(0/1): MA5_GT_MA10/MA10_GT_MA20/CLOSE_GT_MA20
  金叉死叉(0/1): MA5_CROSS_UP_MA10/MA5_CROSS_DOWN_MA10/MACD_CROSS_UP/MACD_CROSS_DOWN
"""

from backend.indicators import calc_ma, calc_macd, calc_rsi, calc_bollinger


def _ff(arr):
    """前向填充：value<=0 或 None 的位置，用最近一个有效值替代（处理停牌日）。"""
    out = []
    last = None
    for v in arr:
        v = float(v) if v is not None else 0.0
        if v > 0:
            last = v
        out.append(v if v > 0 else (last if last else 0.0))
    return out


def _avg(arr):
    return sum(arr) / len(arr) if arr else None


def compute_factor_series(klines):
    """对按时间升序的 K 线，返回 [{factor: value}, ...]（与 bars 对齐，长度相同）。

    None 表示该位置因子尚未形成（warmup），DSL 条件对它应判 False。
    """
    if not klines:
        return []

    closes = _ff([k.get("close", 0) for k in klines])
    opens = _ff([k.get("open", 0) for k in klines])
    highs = _ff([k.get("high", 0) for k in klines])
    lows = _ff([k.get("low", 0) for k in klines])
    volumes = _ff([k.get("volume", 0) for k in klines])
    amounts = [float(k.get("amount", 0) or 0) for k in klines]

    n = len(closes)
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    dif, dea, hist = calc_macd(closes)
    rsi6 = calc_rsi(closes, 6)
    rsi14 = calc_rsi(closes, 14)
    bu, bm, bl = calc_bollinger(closes)

    def f(x):
        return None if (x is None or x != x) else round(float(x), 6)

    series = []
    for i in range(n):
        d = {}
        d["CLOSE"] = f(closes[i])
        d["OPEN"] = f(opens[i])
        d["HIGH"] = f(highs[i])
        d["LOW"] = f(lows[i])
        d["VOLUME"] = f(volumes[i])
        d["AMOUNT"] = f(amounts[i])

        if ma5[i] is not None:
            d["MA5"] = f(ma5[i])
        if ma10[i] is not None:
            d["MA10"] = f(ma10[i])
        if ma20[i] is not None:
            d["MA20"] = f(ma20[i])
        if ma60[i] is not None:
            d["MA60"] = f(ma60[i])
        if dif[i] is not None:
            d["MACD_DIF"] = f(dif[i])
        if dea[i] is not None:
            d["MACD_DEA"] = f(dea[i])
        if hist[i] is not None:
            d["MACD_HIST"] = f(hist[i])
        if rsi6[i] is not None:
            d["RSI6"] = f(rsi6[i])
        if rsi14[i] is not None:
            d["RSI14"] = f(rsi14[i])
        if bu[i] is not None:
            d["BOLL_UPPER"] = f(bu[i])
        if bm[i] is not None:
            d["BOLL_MID"] = f(bm[i])
        if bl[i] is not None:
            d["BOLL_LOWER"] = f(bl[i])

        # 涨跌幅 (小数, 0.01=1%)
        if i > 0 and closes[i - 1] > 0:
            d["CHANGE_PCT"] = f(closes[i] / closes[i - 1] - 1)

        # 5日量比 (今日量 / 前5日均量)
        if i >= 5:
            prev5 = volumes[i - 5:i]
            if _avg(prev5) and _avg(prev5) > 0:
                d["VOL_RATIO_5"] = f(volumes[i] / _avg(prev5))

        # 20日价格位置 (0~1)
        if i >= 19:
            win_h = max(highs[i - 19:i + 1])
            win_l = min(lows[i - 19:i + 1])
            if win_h > win_l:
                d["PRICE_POS_20"] = f((closes[i] - win_l) / (win_h - win_l))

        # 截面研究因子(与 factor_research 一致, 使研究-生成的因子可对应)
        if i >= 20 and closes[i - 20] > 0:
            d["MOMENTUM_20"] = f(closes[i] / closes[i - 20] - 1)
        if i >= 60 and closes[i - 60] > 0:
            d["MOMENTUM_60"] = f(closes[i] / closes[i - 60] - 1)
        if i >= 5 and closes[i - 5] > 0:
            d["REVERSAL_5"] = f(-(closes[i] / closes[i - 5] - 1))
        if i >= 20:
            win = closes[i - 19:i + 1]
            rets = [win[j] / win[j - 1] - 1 for j in range(1, 20) if win[j - 1] > 0]
            if len(rets) >= 2:
                m = sum(rets) / len(rets)
                var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
                d["VOLATILITY_20"] = f(var ** 0.5)

        # 布尔因子
        if ma5[i] is not None and ma10[i] is not None:
            d["MA5_GT_MA10"] = 1 if ma5[i] > ma10[i] else 0
        if ma10[i] is not None and ma20[i] is not None:
            d["MA10_GT_MA20"] = 1 if ma10[i] > ma20[i] else 0
        if ma20[i] is not None:
            d["CLOSE_GT_MA20"] = 1 if closes[i] > ma20[i] else 0

        # 金叉/死叉
        if i > 0 and ma5[i] is not None and ma10[i] is not None \
                and ma5[i - 1] is not None and ma10[i - 1] is not None:
            d["MA5_CROSS_UP_MA10"] = 1 if (ma5[i] > ma10[i] and ma5[i - 1] <= ma10[i - 1]) else 0
            d["MA5_CROSS_DOWN_MA10"] = 1 if (ma5[i] < ma10[i] and ma5[i - 1] >= ma10[i - 1]) else 0
        if i > 0 and dif[i] is not None and dea[i] is not None \
                and dif[i - 1] is not None and dea[i - 1] is not None:
            d["MACD_CROSS_UP"] = 1 if (dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]) else 0
            d["MACD_CROSS_DOWN"] = 1 if (dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]) else 0

        series.append(d)
    return series
