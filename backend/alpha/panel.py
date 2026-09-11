# -*- coding: utf-8 -*-
"""面板数据层 —— kline.db → [股票 × 交易日] 的特征面板与目标收益。

要点：
  - **严格 as-of**：特征只用 t 及之前的数据（滚动窗口一律 `np.cumsum` 或 `_delay` 实现）；
  - **截面标准化**：每个交易日在股票维做 robust z（中位数/MAD，clip ±5），
    这样公式里的加减乘除在各日之间可比（AlphaGPT 的 times.py 用的是时序 robust_norm，
    面板数据下截面标准化更合适）；
  - **可交易掩码**：一字板/停牌不可成交（次日开盘涨幅 ≥9.8% 视为买不到，
    跌幅 ≤-9.8% 视为卖不出）；
  - **目标收益**：open-to-open，`target[t] = open[t+2]/open[t+1] - 1`
    （t 日收盘出信号 → t+1 开盘买 → t+2 开盘卖，与 times.py 一致，天然防前视）。
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..api.paths import KLINE_DB

#: 特征名 → 计算函数（输入是 [N,T] 的原始面板，输出同形状）
FEATURE_NAMES: Tuple[str, ...] = (
    "RET1", "RET5", "RET20", "VOL_CHG", "VOL_RATIO", "TURN_RATIO",
    "TREND20", "TREND60", "RSI14", "MACD_H", "CLOSE_POS", "AMP",
    "HL_RANGE", "AMT_TREND", "HIGH20_GAP", "LOW20_GAP", "LOG_AMT20", "VOL20",
)


def _pct_change(px: np.ndarray, d: int) -> np.ndarray:
    out = np.zeros_like(px)
    if px.shape[1] > d:
        out[:, d:] = px[:, d:] / (px[:, :-d] + 1e-9) - 1.0
    return out.astype(np.float32)


def _rolling_mean(x: np.ndarray, d: int) -> np.ndarray:
    c = np.cumsum(x, axis=1, dtype=np.float32)
    out = np.zeros_like(x)
    n = x.shape[1]
    idx = np.arange(1, min(d, n) + 1, dtype=np.float32)
    out[:, :min(d, n)] = c[:, :min(d, n)] / idx[None, :]
    if n > d:
        out[:, d:] = (c[:, d:] - c[:, :-d]) / float(d)
    return out


def _rolling_std(x: np.ndarray, d: int) -> np.ndarray:
    m = _rolling_mean(x, d)
    m2 = _rolling_mean(x * x, d)
    return np.sqrt(np.maximum(m2 - m * m, 0.0)).astype(np.float32)


def _rolling_max(x: np.ndarray, d: int) -> np.ndarray:
    out = np.zeros_like(x)
    n = x.shape[1]
    for t in range(n):
        lo = max(0, t - d + 1)
        out[:, t] = x[:, lo:t + 1].max(axis=1)
    return out


def _rolling_min(x: np.ndarray, d: int) -> np.ndarray:
    out = np.zeros_like(x)
    n = x.shape[1]
    for t in range(n):
        lo = max(0, t - d + 1)
        out[:, t] = x[:, lo:t + 1].min(axis=1)
    return out


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.zeros_like(close)
    diff[:, 1:] = close[:, 1:] - close[:, :-1]
    up = np.maximum(diff, 0.0)
    dn = np.maximum(-diff, 0.0)
    au = _rolling_mean(up, period)
    ad = _rolling_mean(dn, period)
    return (100.0 - 100.0 / (1.0 + au / (ad + 1e-9))).astype(np.float32)


def _ema(x: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.zeros_like(x)
    out[:, 0] = x[:, 0]
    for t in range(1, x.shape[1]):
        out[:, t] = alpha * x[:, t] + (1 - alpha) * out[:, t - 1]
    return out


# ───────────────────────── 数据加载 ─────────────────────────

def pick_universe(limit: int = 400, min_amount: float = 5e7, lookback_days: int = 120,
                  exclude_st: bool = True, as_of: Optional[str] = None) -> List[str]:
    """按成交额挑流动性最好的 limit 只（默认剔除 ST/退市）。

    as_of 非空时，只用 **该日之前** 的成交额排序，并要求股票在该日之前已有行情
    （避免用未来流动性选池造成的选择偏误与前视）。
    """
    con = sqlite3.connect(KLINE_DB)
    try:
        rows = con.execute(
            "SELECT code, name, status FROM stock_list WHERE status='active' ORDER BY code").fetchall()
        names = {str(c): str(n or "") for c, n, _ in rows}
        codes = [c for c in names if c[:2] in ("60", "00", "30", "68")]
        if exclude_st:
            codes = [c for c in codes if "ST" not in names[c].upper()]
        if as_of:
            end_s = as_of.replace("-", "")
            cal = [r[0] for r in con.execute(
                "SELECT DISTINCT date FROM kline_daily WHERE date<? ORDER BY date DESC LIMIT ?",
                (end_s, lookback_days))]
        else:
            cal = [r[0] for r in con.execute(
                "SELECT DISTINCT date FROM kline_daily ORDER BY date DESC LIMIT ?", (lookback_days,))]
        if not cal:
            return codes[:limit]
        lo = min(cal)
        ph = ",".join("?" for _ in codes)
        amt = {}
        for code, s in con.execute(
                f"SELECT code, SUM(amount) FROM kline_daily WHERE date>=? AND code IN ({ph}) GROUP BY code",
                [lo] + codes):
            amt[str(code)] = float(s or 0)
        ranked = sorted(codes, key=lambda c: -amt.get(c, 0))
        out = [c for c in ranked if amt.get(c, 0) >= min_amount][:limit]
        return out or ranked[:limit]
    finally:
        con.close()


def load_panel(codes: List[str], start: str, end: str) -> Dict[str, object]:
    """读取 [N × T] 面板。start/end 为 YYYY-MM-DD。"""
    con = sqlite3.connect(KLINE_DB)
    try:
        s, e = start.replace("-", ""), end.replace("-", "")
        dates = [str(r[0]) for r in con.execute(
            "SELECT DISTINCT date FROM kline_daily WHERE date>=? AND date<=? ORDER BY date", (s, e))]
        di = {d: i for i, d in enumerate(dates)}
        ni = {c: i for i, c in enumerate(codes)}
        N, T = len(codes), len(dates)
        f = {k: np.zeros((N, T), dtype=np.float32) for k in
             ("open", "high", "low", "close", "volume", "amount", "turnover")}
        ph = ",".join("?" for _ in codes)
        cur = con.execute(
            f"SELECT code,date,open,high,low,close,volume,amount,turnover FROM kline_daily "
            f"WHERE date>=? AND date<=? AND code IN ({ph})", [s, e] + codes)
        for row in cur:
            code, d = str(row[0]), str(row[1])
            i, j = ni.get(code), di.get(d)
            if i is None or j is None:
                continue
            for k, v in zip(("open", "high", "low", "close", "volume", "amount", "turnover"), row[2:]):
                f[k][i, j] = float(v or 0.0)
        names = {}
        for c, n in con.execute(f"SELECT code,name FROM stock_list WHERE code IN ({ph})", codes):
            names[str(c)] = str(n or "")
        return {"codes": codes, "dates": dates, "fields": f, "names": names}
    finally:
        con.close()


def _cs_norm(x: np.ndarray) -> np.ndarray:
    """截面 robust z（逐日、跨股票），NaN→0。"""
    out = np.zeros_like(x)
    med = np.nanmedian(x, axis=0, keepdims=True)
    mad = np.nanmedian(np.abs(x - med), axis=0, keepdims=True) + 1e-6
    z = (x - med) / mad
    z = np.clip(z, -5, 5)
    z = np.where(np.isfinite(z), z, 0.0)
    return z.astype(np.float32)


def build_features(fields: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """由原始面板派生出公式可用的特征（全部因果、截面标准化）。"""
    close = fields["close"]
    high, low, open_ = fields["high"], fields["low"], fields["open"]
    vol, amt, turn = fields["volume"], fields["amount"], fields["turnover"]

    tradable = (close > 0).astype(np.float32)
    ret1 = _pct_change(close, 1) * tradable
    vol_ma20 = _rolling_mean(vol, 20)
    amt_ma20 = _rolling_mean(amt, 20)
    turn_ma20 = _rolling_mean(turn, 20)
    rng = np.where(high > low, (high - low), 1.0)
    feats_raw = {
        "RET1": ret1,
        "RET5": _pct_change(close, 5) * tradable,
        "RET20": _pct_change(close, 20) * tradable,
        "VOL_CHG": vol / (vol_ma20 + 1e-9) - 1.0,
        "VOL_RATIO": vol / (vol_ma20 + 1e-9),
        "TURN_RATIO": turn / (turn_ma20 + 1e-9),
        "TREND20": close / (_rolling_mean(close, 20) + 1e-9) - 1.0,
        "TREND60": close / (_rolling_mean(close, 60) + 1e-9) - 1.0,
        "RSI14": _rsi(close, 14),
        "MACD_H": _ema(close, 12) - _ema(close, 26),
        "CLOSE_POS": (close - low) / rng,
        "AMP": (high - low) / (close + 1e-9),
        "HL_RANGE": (high - low) / (close + 1e-9),
        "AMT_TREND": amt / (amt_ma20 + 1e-9) - 1.0,
        "HIGH20_GAP": close / (_rolling_max(high, 20) + 1e-9) - 1.0,
        "LOW20_GAP": close / (_rolling_min(low, 20) + 1e-9) - 1.0,
        # 市值代理：20 日均成交额的对数（截面标准化后保留相对大小关系）
        "LOG_AMT20": np.log(amt_ma20 + 1.0),
        # 20 日已实现波动（波动率风格因子，同时用于风格中性化）
        "VOL20": _rolling_std(ret1, 20),
    }
    feats = {k: _cs_norm(v) for k, v in feats_raw.items()}
    feats["_TRADABLE"] = tradable
    return feats


def build_target(fields: Dict[str, np.ndarray], fee_round_trip: float = 0.0) -> np.ndarray:
    """open-to-open 目标收益：target[t] = open[t+2]/open[t+1]-1。"""
    open_ = fields["open"]
    t1 = np.zeros_like(open_)
    t2 = np.zeros_like(open_)
    if open_.shape[1] > 1:
        t1[:, :-1] = open_[:, 1:]
    if open_.shape[1] > 2:
        t2[:, :-2] = open_[:, 2:]
    ok = (t1 > 0) & (t2 > 0)
    ret = np.zeros_like(open_)
    ret[ok] = t2[ok] / t1[ok] - 1.0
    return ret.astype(np.float32)


def trade_masks(fields: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """可买/可卖掩码（涨跌停一字板、停牌）。"""
    close, open_ = fields["close"], fields["open"]
    prev_close = np.zeros_like(close)
    prev_close[:, 1:] = close[:, :-1]
    next_open = np.zeros_like(open_)
    next_open[:, :-1] = open_[:, 1:]
    gap = np.zeros_like(open_)
    ok = (prev_close > 0) & (next_open > 0)
    gap[ok] = next_open[ok] / prev_close[ok] - 1.0
    suspended = (next_open <= 0)
    limit_up = ok & (gap >= 0.098)
    limit_down = ok & (gap <= -0.098)
    can_buy = ~suspended & ~limit_up
    can_sell = ~suspended & ~limit_down
    return {"can_buy": can_buy, "can_sell": can_sell, "gap": gap}


#: 风格因子（中性化用）：市值代理 + 波动
STYLE_FACTORS: Tuple[str, ...] = ("LOG_AMT20", "VOL20")


def neutralize(sig: np.ndarray, feats: Dict[str, np.ndarray],
               mask: np.ndarray, styles: Tuple[str, ...] = STYLE_FACTORS) -> np.ndarray:
    """截面风格中性化：每个交易日把信号对 [1, 风格因子…] 做 OLS，取残差。

    目的：把"小市值 / 高波动"这类可以整体押注的风格暴露从信号里剥离，
    只留下与风格无关的选股信息（否则超额很难区分是 alpha 还是风格 beta）。
    """
    Xs = [feats.get(n) for n in styles if feats.get(n) is not None]
    if not Xs:
        return sig
    N, T = sig.shape
    out = np.zeros_like(sig)
    m_all = mask if mask.dtype == bool else mask > 0
    for t in range(T):
        m = m_all[:, t]
        cnt = int(m.sum())
        if cnt < 30:
            continue
        y = sig[m, t].astype(np.float64)
        X = np.column_stack([np.ones(cnt, dtype=np.float64)] + [s[m, t].astype(np.float64) for s in Xs])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except Exception:
            continue
        out[m, t] = (y - X @ beta).astype(np.float32)
    return out


def build_neutralizer(feats: Dict[str, np.ndarray], mask: np.ndarray,
                      styles: Tuple[str, ...] = STYLE_FACTORS) -> Dict:
    """为风格中性化预计算每日设计矩阵（向量化版本，比逐日 lstsq 快 5~10 倍）。"""
    N, T = next(iter(feats.values())).shape
    m = (mask if mask.dtype == bool else mask > 0).T              # [T, N]
    cols = [feats[n] for n in styles if feats.get(n) is not None]
    k = 1 + len(cols)
    X = np.zeros((T, N, k), dtype=np.float32)
    X[:, :, 0] = m
    for i, c in enumerate(cols, start=1):
        X[:, :, i] = np.where(m, c.T, 0.0)
    return {"X": X, "mask": m, "k": k}


def neutralize_apply(sig: np.ndarray, nz: Dict) -> np.ndarray:
    """用预计算的投影剥离风格：逐日 OLS 残差（不含截距项的拟合部分）。"""
    X, m, k = nz["X"], nz["mask"], nz["k"]
    Y = np.where(m, sig.T, 0.0).astype(np.float32)                # [T, N]
    XtX = np.einsum("tnk,tnl->tkl", X, X)
    Xty = np.einsum("tnk,tn->tk", X, Y)
    reg = (1e-6 * np.eye(k, dtype=np.float32))[None, :, :]
    beta = np.linalg.solve(XtX + reg, Xty[..., None])[..., 0]     # [T, k]
    pred = np.einsum("tnk,tk->tn", X, beta)
    res = np.where(m, Y - pred, 0.0)
    return res.T.astype(np.float32)


def split_index(dates: List[str], train_ratio: float = 0.8) -> int:
    return int(len(dates) * train_ratio)
