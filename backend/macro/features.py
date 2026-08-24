# -*- coding: utf-8 -*-
"""全球宏观 regime 合成 — 把各原始序列压成"当前宏观状态"。

对每个指标算：最新值(日期) / 20日变化 / 60日变化 / 20-60均线趋势；
sp500_vol 由标普收益年化波动派生(VIX 无稳定源)。并给出类别级、整体级可读标签。
"""
import math
from datetime import datetime

from .catalog import by_key


def _fresh(date_str, max_days=30):
    try:
        d = datetime.strptime(str(date_str), "%Y%m%d")
        return (datetime.now() - d).days <= max_days
    except Exception:
        return False


def _pct(series, n):
    if len(series) < n + 1:
        return None
    base = series[-1 - n][1]
    if not base:
        return None
    return series[-1][1] / base - 1.0


def _trend(series, fast, slow):
    if len(series) < slow:
        return None
    f = sum(v for _, v in series[-fast:]) / fast
    s = sum(v for _, v in series[-slow:]) / slow
    if s == 0:
        return None
    return 1 if f > s else -1


def _vol(series, n=20):
    if len(series) < n + 1:
        return None
    rets = []
    for i in range(len(series) - n, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev:
            rets.append(cur / prev - 1.0)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def compute_regime(series_map: dict) -> dict:
    """series_map: {key: [(date, value), ...]}。返回 {key: 特征dict} + _category 汇总。"""
    series_map = dict(series_map)
    sp = series_map.get("sp500") or []
    if sp:
        series_map["sp500_vol"] = sp          # 用 sp500 序列派生 vol(标记为 computed)

    feats = {}
    for key, series in series_map.items():
        meta = by_key(key)
        feat = {"ok": bool(series)}
        if series:
            feat["latest_date"] = series[-1][0]
            feat["latest"] = series[-1][1]
            feat["chg20d"] = _pct(series, 20)
            feat["chg60d"] = _pct(series, 60)
            feat["trend_20_60"] = _trend(series, 20, 60)
            if key == "sp500_vol":
                feat["latest"] = _vol(series, 20)
                feat["unit"] = "%"
        feats[key] = feat
    feats["_category"] = _category(series_map, feats)
    return feats


def _cat(feats, key, field, default=None):
    d = feats.get(key, {})
    v = d.get(field, default)
    return v


def _category(series_map, feats) -> dict:
    def arrow(x):
        return None if x is None else ("↑" if x > 0 else ("↓" if x < 0 else "→"))

    def pct_str(x):
        return None if x is None else f"{x * 100:+.1f}%"

    eq_trend = _cat(feats, "sp500", "trend_20_60")
    eq_label = ("风险偏好(risk-on)" if eq_trend == 1 else
                "risk-off" if eq_trend == -1 else "中性")
    eq = {
        "label": f"全球股市 {eq_label}",
        "sp500_chg20d": pct_str(_cat(feats, "sp500", "chg20d")),
        "nasdaq_chg20d": pct_str(_cat(feats, "nasdaq", "chg20d")),
        "hsi_chg20d": pct_str(_cat(feats, "hsi", "chg20d")),
        "vol20d": (_cat(feats, "sp500_vol", "latest") if _cat(feats, "sp500_vol", "ok") else None),
    }

    usd_date = _cat(feats, "usdcny", "latest_date")
    usd_chg = _cat(feats, "usdcny", "chg20d")
    usd_lvl = _cat(feats, "usdcny", "latest")
    if usd_date and _fresh(usd_date):
        if usd_chg is not None:
            fx_label = ("美元走强(人民币贬值)" if usd_chg > 0.005 else
                        "美元走弱(人民币升值)" if usd_chg < -0.005 else "汇率平稳")
            fx = {"label": f"汇率资金 {fx_label}({usd_lvl})",
                  "usdcny_chg20d": pct_str(usd_chg), "usdcny_level": usd_lvl}
        else:
            fx = {"label": f"汇率资金 美元/人民币 {usd_lvl}(实时, 历史源受限)",
                  "usdcny_chg20d": None, "usdcny_level": usd_lvl}
    else:
        fx = {"label": "汇率资金 数据待更新(美元/人民币源受限)", "usdcny_chg20d": None, "usdcny_level": None}

    us10y_trend = _cat(feats, "us10y", "trend_20_60")
    curve = _cat(feats, "us10y_2y", "latest")
    rate_label = "美债利率上行" if us10y_trend == 1 else ("美债利率下行" if us10y_trend == -1 else "美债利率平稳")
    if curve is not None and curve < 0:
        rate_label += "·收益率倒挂"
    rate = {
        "label": f"利率流动性 {rate_label}",
        "us10y": _cat(feats, "us10y", "latest"),
        "cn10y": _cat(feats, "cn10y", "latest"),
        "us10y_2y": curve,
    }

    gold = _cat(feats, "gold", "chg20d"); oil = _cat(feats, "oil", "chg20d")
    copper = _cat(feats, "copper", "chg20d")
    com = {
        "label": f"商品通胀  金{pct_str(gold)} 油{pct_str(oil)} 铜{pct_str(copper)}",
        "gold_chg20d": pct_str(gold), "oil_chg20d": pct_str(oil), "copper_chg20d": pct_str(copper),
    }

    vol = _cat(feats, "sp500_vol", "latest")
    vol_label = "高波动(risk-off)" if (vol or 0) > 25 else ("低波动" if (vol or 0) < 12 else "中等波动")
    volatility = {"label": f"波动率情绪 {vol_label}", "sp500_vol20d": (f"{round(vol,2)}%" if vol is not None else None)}

    return {"equity": eq, "fx": fx, "rate": rate, "commodity": com, "vol": volatility,
            "overall": f"{eq['label']} | {fx['label']} | {rate['label']} | {com['label']} | {volatility['label']}"}
