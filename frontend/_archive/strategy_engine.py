"""
选股评分引擎 — score_stock() 六维评分（0-100分）

评分维度：
  1. 当日涨跌幅（±20分）
  2. 换手率（±10分）
  3. 价格区间（±5分）
  4. 成交量活跃度（±10分）
  5. 技术面：均线排列 + MACD + RSI + MA60 + 量价关系（±45分）
  6. 综合上下限压缩至 0-100

AISignal / AIStrategy / TradeManager 等类已移至 archive/ai_strategy.py
供 backtest_engine.py 回测使用。
"""

def score_stock(code: str, name: str, price: float, change_pct: float,
                volume: int, turnover: float, kline_data: list = None):
    """对单只股票进行六维评分，返回 0-100 的分数 + 理由列表"""

    score = 50
    reasons = []

    # 维度1: 当日涨跌幅
    if change_pct > 5:
        score += 20
        reasons.append(f'强势上涨{change_pct:.1f}%')
    elif change_pct > 2:
        score += 12
        reasons.append(f'稳步上涨{change_pct:.1f}%')
    elif change_pct > 0:
        score += 5
    elif change_pct > -2:
        score -= 5
    elif change_pct > -5:
        score -= 12
    else:
        score -= 20

    # 维度2: 换手率
    if 2 < turnover < 10:
        score += 10
        reasons.append(f'换手活跃{turnover:.1f}%')
    elif 1 < turnover <= 2:
        score += 5
    elif turnover > 15:
        score -= 5

    # 维度3: 价格区间
    if 5 < price < 50:
        score += 5
        reasons.append('价格适中')
    elif price > 200:
        score -= 3

    # 维度4: 成交量
    if volume > 50000000:
        score += 10
        reasons.append('交投活跃')
    elif volume > 10000000:
        score += 5
    elif volume < 1000000:
        score -= 10
        reasons.append('成交清淡')

    # 维度5: 技术面（需要至少20天K线）
    if kline_data and len(kline_data) >= 20:
        closes = [k['close'] for k in kline_data]
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20

        # 均线排列
        if price > ma5 > ma10 > ma20:
            score += 15
            reasons.append('均线多头排列')
        elif price < ma5 < ma10 < ma20:
            score -= 15
            reasons.append('均线空头排列')
        elif price > ma5:
            score += 5

        # 趋势
        if closes[-1] > closes[-5]:
            score += 5
        if closes[-1] > closes[-10]:
            score += 3

        # MACD
        last = kline_data[-1]
        if last.get('macd') is not None and last.get('dif') is not None:
            prev = kline_data[-2]
            if last['macd'] > 0 and prev.get('macd', 0) <= 0:
                score += 8
                reasons.append('MACD金叉')
            elif last['macd'] < 0 and prev.get('macd', 0) >= 0:
                score -= 8
                reasons.append('MACD死叉')
            elif last['macd'] > 0:
                score += 4
                reasons.append('MACD多头')
            else:
                score -= 2

        # RSI
        if last.get('rsi14') is not None:
            rsi = last['rsi14']
            if rsi < 30:
                score += 8
                reasons.append('RSI超卖')
            elif rsi > 70:
                score -= 8
                reasons.append('RSI超买')
            elif rsi > 50:
                score += 3

        # MA60
        if last.get('ma60') is not None and last['ma60'] > 0:
            if price > last['ma60']:
                score += 5
                reasons.append('站上MA60')
            else:
                score -= 5
                reasons.append('MA60下方')

        # 量价关系
        if len(kline_data) >= 5:
            avg_vol = sum(k['volume'] for k in kline_data[-5:]) / 5
            if volume > avg_vol * 1.5 and change_pct > 0:
                score += 5
                reasons.append('放量上涨')
            elif volume < avg_vol * 0.5:
                score -= 3
                reasons.append('缩量')

    score = max(0, min(100, score))
    return {
        'score': round(score, 1),
        'reasons': reasons,
        'rating': '\u2605\u2605\u2605' if score >= 70 else ('\u2605\u2605' if score >= 50 else '\u2605')
    }
