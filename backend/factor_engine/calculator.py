
"""因子计算层 — 从 K 线数据计算所有技术指标因子值"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


# ── 辅助指标计算 ─────────────────────────────────────────────
def _calc_ma(closes, period):
    ma = []
    for i in range(len(closes)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(round(sum(closes[i - period + 1 : i + 1]) / period, 2))
    return ma


def _calc_ema(data, period):
    result = []
    if len(data) < period:
        return [None] * len(data)
    sma = sum(data[:period]) / period
    result.extend([None] * (period - 1) + [sma])
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        result.append((data[i] - result[-1]) * multiplier + result[-1])
    return result


def _calc_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    dif = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]
    dea = _calc_ema([d if d is not None else 0 for d in dif], signal)
    for i in range(len(closes)):
        if dif[i] is None:
            dea[i] = None
    macd_hist = [None] * len(closes)
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            macd_hist[i] = (dif[i] - dea[i]) * 2
    return dif, dea, macd_hist


def _calc_rsi(closes, period=14):
    rsi = [None] * len(closes)
    if len(closes) < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    if len(gains) < period:
        return rsi
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        idx = i + 1
        if avg_loss == 0:
            rsi[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[idx] = round(100 - 100 / (1 + rs), 2)
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    return rsi


def _calc_bollinger(closes, period=20, k=2):
    upper, mid, lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            mid.append(None)
            lower.append(None)
            continue
        window = closes[i - period + 1 : i + 1]
        ma = sum(window) / period
        variance = sum((x - ma) ** 2 for x in window) / period
        std = math.sqrt(variance)
        mid.append(round(ma, 2))
        upper.append(round(ma + k * std, 2))
        lower.append(round(ma - k * std, 2))
    return upper, mid, lower


# ── 因子注册表 ─────────────────────────────────────────────
# 每个条目: (依赖的 K 线根数, 计算函数)
# 计算函数签名为 (closes, highs, lows, volumes, amounts, intermediates) -> float

_FACTORY: dict[str, tuple[int, callable]] = {}


def register_factor(factor_id: str, min_klines: int = 1):
    """装饰器：注册一个因子到工厂"""

    def wrapper(func):
        _FACTORY[factor_id] = (min_klines, func)
        return func

    return wrapper


# ── 因子实现 ─────────────────────────────────────────────

@register_factor("CLOSE")
def _f_close(closes, highs, lows, volumes, amounts, inter):
    return closes[-1] if closes else None


@register_factor("OPEN")
def _f_open(closes, highs, lows, volumes, amounts, inter):
    return inter["opens"][-1] if inter.get("opens") else None


@register_factor("HIGH")
def _f_high(closes, highs, lows, volumes, amounts, inter):
    return highs[-1] if highs else None


@register_factor("LOW")
def _f_low(closes, highs, lows, volumes, amounts, inter):
    return lows[-1] if lows else None


@register_factor("VOLUME")
def _f_volume(closes, highs, lows, volumes, amounts, inter):
    return volumes[-1] if volumes else None


@register_factor("CHANGE_PCT")
def _f_change_pct(closes, highs, lows, volumes, amounts, inter):
    if len(closes) < 2:
        return None
    prev = closes[-2]
    return ((closes[-1] - prev) / prev * 100) if prev else None


@register_factor("AMP")
def _f_amp(closes, highs, lows, volumes, amounts, inter):
    if len(closes) < 2:
        return None
    return (highs[-1] - lows[-1]) / closes[-2] * 100 if closes[-2] else None


@register_factor("MA5", min_klines=5)
def _f_ma5(closes, highs, lows, volumes, amounts, inter):
    return inter["ma5"][-1]


@register_factor("MA10", min_klines=10)
def _f_ma10(closes, highs, lows, volumes, amounts, inter):
    return inter["ma10"][-1]


@register_factor("MA20", min_klines=20)
def _f_ma20(closes, highs, lows, volumes, amounts, inter):
    return inter["ma20"][-1]


@register_factor("MA60", min_klines=60)
def _f_ma60(closes, highs, lows, volumes, amounts, inter):
    return inter["ma60"][-1]


@register_factor("MA5_GT_MA10", min_klines=10)
def _f_ma5_gt_ma10(closes, highs, lows, volumes, amounts, inter):
    if inter["ma5"][-1] is None or inter["ma10"][-1] is None:
        return None
    return 1.0 if inter["ma5"][-1] > inter["ma10"][-1] else 0.0


@register_factor("MA10_GT_MA20", min_klines=20)
def _f_ma10_gt_ma20(closes, highs, lows, volumes, amounts, inter):
    if inter["ma10"][-1] is None or inter["ma20"][-1] is None:
        return None
    return 1.0 if inter["ma10"][-1] > inter["ma20"][-1] else 0.0


@register_factor("MA_ALIGN_SCORE", min_klines=20)
def _f_ma_align_score(closes, highs, lows, volumes, amounts, inter):
    """均线排列评分：完全多头+3，完全空头-3"""
    c = closes[-1]
    m5 = inter["ma5"][-1]
    m10 = inter["ma10"][-1]
    m20 = inter["ma20"][-1]
    if None in (c, m5, m10, m20):
        return None
    score = 0
    if c > m5:
        score += 1
    if m5 > m10:
        score += 1
    if m10 > m20:
        score += 1
    return float(score) if score >= 0 else float(score)


@register_factor("CLOSE_GT_MA5", min_klines=5)
def _f_close_gt_ma5(closes, highs, lows, volumes, amounts, inter):
    if closes[-1] is None or inter["ma5"][-1] is None:
        return None
    return 1.0 if closes[-1] > inter["ma5"][-1] else 0.0


@register_factor("CLOSE_GT_MA10", min_klines=10)
def _f_close_gt_ma10(closes, highs, lows, volumes, amounts, inter):
    if closes[-1] is None or inter["ma10"][-1] is None:
        return None
    return 1.0 if closes[-1] > inter["ma10"][-1] else 0.0


@register_factor("CLOSE_GT_MA20", min_klines=20)
def _f_close_gt_ma20(closes, highs, lows, volumes, amounts, inter):
    if closes[-1] is None or inter["ma20"][-1] is None:
        return None
    return 1.0 if closes[-1] > inter["ma20"][-1] else 0.0


@register_factor("CLOSE_GT_MA60", min_klines=60)
def _f_close_gt_ma60(closes, highs, lows, volumes, amounts, inter):
    if closes[-1] is None or inter["ma60"][-1] is None:
        return None
    return 1.0 if closes[-1] > inter["ma60"][-1] else 0.0


@register_factor("MA5_SLOPE", min_klines=6)
def _f_ma5_slope(closes, highs, lows, volumes, amounts, inter):
    """MA5 斜率：1=向上, 0=走平, -1=向下"""
    arr = inter["ma5"]
    cur, prev = arr[-1], arr[-2]
    if cur is None or prev is None:
        return None
    if cur > prev * 1.001:
        return 1.0
    if cur < prev * 0.999:
        return -1.0
    return 0.0


@register_factor("MACD_DIF", min_klines=26)
def _f_macd_dif(closes, highs, lows, volumes, amounts, inter):
    return inter["macd_dif"][-1]


@register_factor("MACD_DEA", min_klines=26)
def _f_macd_dea(closes, highs, lows, volumes, amounts, inter):
    return inter["macd_dea"][-1]


@register_factor("MACD_BAR", min_klines=26)
def _f_macd_bar(closes, highs, lows, volumes, amounts, inter):
    return inter["macd_hist"][-1]


@register_factor("MACD_ABOVE_ZERO", min_klines=26)
def _f_macd_above_zero(closes, highs, lows, volumes, amounts, inter):
    d, e = inter["macd_dif"][-1], inter["macd_dea"][-1]
    if d is None or e is None:
        return None
    return 1.0 if d > 0 and e > 0 else 0.0


@register_factor("MACD_CROSS", min_klines=27)
def _f_macd_cross(closes, highs, lows, volumes, amounts, inter):
    """返回：1=金叉, -1=死叉, 0=无交叉"""
    d_cur, d_prev = inter["macd_dif"][-1], inter["macd_dif"][-2]
    e_cur, e_prev = inter["macd_dea"][-1], inter["macd_dea"][-2]
    if None in (d_cur, d_prev, e_cur, e_prev):
        return None
    if d_prev <= e_prev and d_cur > e_cur:
        return 1.0  # 金叉
    if d_prev >= e_prev and d_cur < e_cur:
        return -1.0  # 死叉
    return 0.0


@register_factor("MACD_BAR_RISING", min_klines=27)
def _f_macd_bar_rising(closes, highs, lows, volumes, amounts, inter):
    h_cur, h_prev = inter["macd_hist"][-1], inter["macd_hist"][-2]
    if h_cur is None or h_prev is None:
        return None
    return 1.0 if h_cur > h_prev else 0.0


@register_factor("RSI6", min_klines=7)
def _f_rsi6(closes, highs, lows, volumes, amounts, inter):
    return inter["rsi6"][-1]


@register_factor("RSI14", min_klines=15)
def _f_rsi14(closes, highs, lows, volumes, amounts, inter):
    return inter["rsi14"][-1]


@register_factor("RSI_OVERSOLD", min_klines=15)
def _f_rsi_oversold(closes, highs, lows, volumes, amounts, inter):
    v = inter["rsi14"][-1]
    if v is None:
        return None
    return 1.0 if v < 30 else 0.0


@register_factor("RSI_OVERBOUGHT", min_klines=15)
def _f_rsi_overbought(closes, highs, lows, volumes, amounts, inter):
    v = inter["rsi14"][-1]
    if v is None:
        return None
    return 1.0 if v > 70 else 0.0


@register_factor("BOLL_UP", min_klines=20)
def _f_boll_up(closes, highs, lows, volumes, amounts, inter):
    return inter["boll_up"][-1]


@register_factor("BOLL_MID", min_klines=20)
def _f_boll_mid(closes, highs, lows, volumes, amounts, inter):
    return inter["boll_mid"][-1]


@register_factor("BOLL_DN", min_klines=20)
def _f_boll_dn(closes, highs, lows, volumes, amounts, inter):
    return inter["boll_dn"][-1]


@register_factor("BOLL_POS", min_klines=20)
def _f_boll_pos(closes, highs, lows, volumes, amounts, inter):
    up, mid, dn = inter["boll_up"][-1], inter["boll_mid"][-1], inter["boll_dn"][-1]
    if None in (up, dn) or up == dn:
        return None
    return (closes[-1] - dn) / (up - dn)


@register_factor("VOL_RATIO_5", min_klines=5)
def _f_vol_ratio_5(closes, highs, lows, volumes, amounts, inter):
    avg = sum(volumes[-5:]) / 5
    return volumes[-1] / avg if avg else None


@register_factor("VOL_RATIO_10", min_klines=10)
def _f_vol_ratio_10(closes, highs, lows, volumes, amounts, inter):
    avg = sum(volumes[-10:]) / 10
    return volumes[-1] / avg if avg else None


@register_factor("VOL_UP_WITH_PRICE", min_klines=6)
def _f_vol_up_with_price(closes, highs, lows, volumes, amounts, inter):
    """量增价涨：今日成交量 > 5日均量*1.2 且 收盘 > 开盘"""
    avg = sum(volumes[-5:]) / 5
    opens = inter["opens"]
    if avg <= 0 or not opens:
        return None
    return 1.0 if (volumes[-1] > avg * 1.2 and closes[-1] > opens[-1]) else 0.0


@register_factor("PRICE_POS_20", min_klines=20)
def _f_price_pos_20(closes, highs, lows, volumes, amounts, inter):
    h20 = max(highs[-20:])
    l20 = min(lows[-20:])
    if h20 == l20:
        return 0.5
    return (closes[-1] - l20) / (h20 - l20)


@register_factor("PRICE_POS_60", min_klines=60)
def _f_price_pos_60(closes, highs, lows, volumes, amounts, inter):
    h60 = max(highs[-60:])
    l60 = min(lows[-60:])
    if h60 == l60:
        return 0.5
    return (closes[-1] - l60) / (h60 - l60)


@register_factor("PRICE_CHANGE_5D", min_klines=6)
def _f_price_change_5d(closes, highs, lows, volumes, amounts, inter):
    return ((closes[-1] - closes[-6]) / closes[-6] * 100) if closes[-6] else None


@register_factor("PRICE_CHANGE_10D", min_klines=11)
def _f_price_change_10d(closes, highs, lows, volumes, amounts, inter):
    return ((closes[-1] - closes[-11]) / closes[-11] * 100) if closes[-11] else None


@register_factor("PRICE_CHANGE_20D", min_klines=21)
def _f_price_change_20d(closes, highs, lows, volumes, amounts, inter):
    return ((closes[-1] - closes[-21]) / closes[-21] * 100) if closes[-21] else None


@register_factor("CONSECUTIVE_UP", min_klines=2)
def _f_consecutive_up(closes, highs, lows, volumes, amounts, inter):
    opens = inter["opens"]
    if not opens:
        return None
    cnt = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > opens[i]:
            cnt += 1
        else:
            break
    return float(cnt)


@register_factor("CONSECUTIVE_DOWN", min_klines=2)
def _f_consecutive_down(closes, highs, lows, volumes, amounts, inter):
    opens = inter["opens"]
    if not opens:
        return None
    cnt = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < opens[i]:
            cnt += 1
        else:
            break
    return float(cnt)


# ── 因子计算器 ─────────────────────────────────────────────

class FactorCalculator:
    """从 K 线数据计算所有注册的因子值"""

    def __init__(self, klines: list[dict]):
        self._raw = klines
        self._intermediates: dict = {}  # 中间计算结果缓存
        self.values: dict[str, float] = {}  # 最终因子值

    def compute_all(self) -> dict[str, float]:
        """计算所有注册因子，返回 {factor_id: value}"""
        self._precompute_intermediates()
        for fid, (min_k, func) in _FACTORY.items():
            if len(self._raw) < min_k:
                self.values[fid] = None
                continue
            try:
                self.values[fid] = func(
                    self._intermediates["closes"],
                    self._intermediates["highs"],
                    self._intermediates["lows"],
                    self._intermediates["volumes"],
                    self._intermediates["amounts"],
                    self._intermediates,
                )
            except Exception:
                self.values[fid] = None
        return self.values

    def get(self, factor_id: str):
        """按需获取单个因子值"""
        if factor_id in self.values:
            return self.values[factor_id]
        if factor_id not in _FACTORY:
            return None
        min_k, func = _FACTORY[factor_id]
        if len(self._raw) < min_k:
            self.values[factor_id] = None
            return None
        if not self._intermediates:
            self._precompute_intermediates()
        try:
            v = func(
                self._intermediates["closes"],
                self._intermediates["highs"],
                self._intermediates["lows"],
                self._intermediates["volumes"],
                self._intermediates["amounts"],
                self._intermediates,
            )
        except Exception:
            v = None
        self.values[factor_id] = v
        return v

    def _precompute_intermediates(self):
        """预计算所有中间数组，供因子使用"""
        if self._intermediates:
            return
        closes = [k["close"] for k in self._raw]
        highs = [k["high"] for k in self._raw]
        lows = [k["low"] for k in self._raw]
        volumes = [k["volume"] for k in self._raw]
        amounts = [k.get("amount", 0) for k in self._raw]
        opens = [k["open"] for k in self._raw]

        inter = {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "amounts": amounts,
            "opens": opens,
            "ma5": _calc_ma(closes, 5),
            "ma10": _calc_ma(closes, 10),
            "ma20": _calc_ma(closes, 20),
            "ma60": _calc_ma(closes, 60),
            "rsi6": _calc_rsi(closes, 6),
            "rsi14": _calc_rsi(closes, 14),
        }
        macd_dif, macd_dea, macd_hist = _calc_macd(closes)
        inter["macd_dif"] = macd_dif
        inter["macd_dea"] = macd_dea
        inter["macd_hist"] = macd_hist
        boll_up, boll_mid, boll_dn = _calc_bollinger(closes)
        inter["boll_up"] = boll_up
        inter["boll_mid"] = boll_mid
        inter["boll_dn"] = boll_dn

        self._intermediates = inter

    @classmethod
    def list_factors(cls) -> list[dict]:
        """列出所有注册的因子（供调试和界面使用）"""
        return [
            {"id": fid, "min_klines": min_k}
            for fid, (min_k, _) in sorted(_FACTORY.items())
        ]


def compute_factors(klines: list[dict]) -> dict[str, float]:
    """快捷函数：计算并返回所有因子值"""
    calc = FactorCalculator(klines)
    return calc.compute_all()
