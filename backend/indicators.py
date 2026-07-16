"""
技术指标计算模块
为K线数据计算 MACD / RSI / BOLL
"""
import math


def calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD: 返回 (dif, dea, histogram)"""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [None]*len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]
    dea = ema([d if d is not None else 0 for d in dif], signal)  # 用0填None避免ema报错
    # 把dea里对应dif为None的位置也设None
    for i in range(len(closes)):
        if dif[i] is None:
            dea[i] = None
    macd_hist = [None]*len(closes)
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            macd_hist[i] = (dif[i] - dea[i]) * 2
    return dif, dea, macd_hist


def calc_rsi(closes, period=14):
    """RSI"""
    rsi = [None] * len(closes)
    if len(closes) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    if len(gains) < period:
        return rsi
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        idx = i + 1  # 对应 closes 里的索引（第i个gains对应closes[i+1]）
        if avg_loss == 0:
            rsi[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[idx] = round(100 - 100/(1+rs), 2)
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
    return rsi


def calc_bollinger(closes, period=20, k=2):
    """布林带: 返回 (upper, mid, lower)"""
    upper, mid, lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None); mid.append(None); lower.append(None)
            continue
        window = closes[i-period+1:i+1]
        ma = sum(window) / period
        variance = sum((x - ma)**2 for x in window) / period
        std = math.sqrt(variance)
        mid.append(round(ma, 2))
        upper.append(round(ma + k * std, 2))
        lower.append(round(ma - k * std, 2))
    return upper, mid, lower


def calc_ma(closes, period):
    """简单移动平均"""
    ma = []
    for i in range(len(closes)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(round(sum(closes[i-period+1:i+1]) / period, 2))
    return ma


def ema(data, period):
    """指数移动平均"""
    result = []
    if len(data) < period:
        return [None] * len(data)
    sma = sum(data[:period]) / period
    result.extend([None] * (period-1) + [sma])
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        result.append((data[i] - result[-1]) * multiplier + result[-1])
    return result


def enrich_kline(raw_data):
    """给一组K线数据加所有指标，兼容多种字段名
    
    修复：停牌日 close=0 → 前向填充为最近一个非零值，避免 MA/MACD/RSI 计算偏差。
    """
    # 兼容不同数据源的字段名
    def get(row, keys, default=None):
        for k in keys:
            if k in row: return row[k]
        return default
    
    # 提取 close 并做前向填充（处理停牌日 close=0）
    closes_raw = []
    for r in raw_data:
        v = get(r, ['close', '收盘'])
        closes_raw.append(float(v) if v is not None else 0.0)
    
    # 前向填充：close=0 的位置用前一个非零值替代
    last_valid = None
    closes = []
    for v in closes_raw:
        if v > 0:
            last_valid = v
        closes.append(v if v > 0 else (last_valid if last_valid else 0.0))
    
    # 同时修正 raw_data 中的 close 字段（避免前端显示 0）
    for i, r in enumerate(raw_data):
        if closes_raw[i] <= 0 and closes[i] > 0:
            # 只在 copy 里改，不修改原始引用
            r = dict(r)
            r['close'] = closes[i]
            r['_close_filled'] = True  # 标记被填充过
            raw_data[i] = r
    
    # MA
    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    
    # MACD
    dif, dea, macd = calc_macd(closes)
    
    # RSI
    rsi_6 = calc_rsi(closes, 6)
    rsi_14 = calc_rsi(closes, 14)
    
    # BOLL
    boll_upper, boll_mid, boll_lower = calc_bollinger(closes)
    
    result = []
    for i, r in enumerate(raw_data):
        result.append({
            **r,
            'ma5': ma5[i], 'ma10': ma10[i], 'ma20': ma20[i], 'ma60': ma60[i],
            'dif': round(dif[i], 4) if dif[i] is not None else None,
            'dea': round(dea[i], 4) if dea[i] is not None else None,
            'macd': round(macd[i], 4) if macd[i] is not None else None,
            'rsi6': rsi_6[i], 'rsi14': rsi_14[i],
            'boll_upper': boll_upper[i], 'boll_mid': boll_mid[i], 'boll_lower': boll_lower[i],
        })
    return result
