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

        # 基本面价值/质量因子(由 attach_kline_fundamentals 注入 kline dict, 点时间)
        for _fk in ("EP", "BP", "ROE"):
            _v = klines[i].get(_fk) if i < len(klines) else None
            if _v is not None:
                d[_fk] = f(_v)

        # BP 均线(供单标的回放用相对估值条件: BP < BP_MA120 = 相对便宜)
        # 当前 bar 的 BP 在 d 里, 历史 BP 从已建好的 series 取(series 只含 i 之前的 bar)
        if "BP" in d and i >= 20:
            _bp_hist = [series[j].get("BP") for j in range(max(0, i - 119), i)]
            _bp_hist.append(d["BP"])
            _bp_hist = [x for x in _bp_hist if x is not None]
            if len(_bp_hist) >= 60:
                d["BP_MA120"] = f(sum(_bp_hist) / len(_bp_hist))
                d["BP_MA20"] = f(sum(_bp_hist[-20:]) / min(20, len(_bp_hist)))

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
        # 动量 (close/close[N]-1)
        for mwin in (5, 10, 20, 40, 60):
            if i >= mwin and closes[i - mwin] > 0:
                d[f"MOMENTUM_{mwin}"] = f(closes[i] / closes[i - mwin] - 1)
        # 反转 (-(close/close[N]-1))
        for rwin in (5, 10, 20):
            if i >= rwin and closes[i - rwin] > 0:
                d[f"REVERSAL_{rwin}"] = f(-(closes[i] / closes[i - rwin] - 1))
        # 波动 (近 N 日日收益标准差, ddof=1; 对应研究 rolling(N).std())
        for vwin in (5, 10, 20, 60):
            if i >= vwin:
                win = closes[i - vwin:i + 1]
                rets = [win[j] / win[j - 1] - 1 for j in range(1, vwin) if win[j - 1] > 0]
                if len(rets) >= 2:
                    m = sum(rets) / len(rets)
                    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
                    d[f"VOLATILITY_{vwin}"] = f(var ** 0.5)
        # RSI_14 (与研究面板 RSI 同概念; 复用 indicators Wilder RSI)
        if rsi14[i] is not None:
            d["RSI_14"] = f(rsi14[i])

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
