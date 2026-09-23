# -*- coding: utf-8 -*-
"""回测奖励 —— 把一条因子信号评成分数（遗传/RL 搜索的适应度）。

与 AlphaGPT 的差别（按 A 股规则）：
  - 组合模式：每日按因子值取 **Top-K 等权**，T+1 开盘买入、T+2 开盘卖出（open-to-open），
    买入当天按可买掩码过滤（一字涨停买不到），卖出受跌停掩码限制；
  - 费用：佣金万 2.5（双边）+ 印花税千 1（卖出）≈ 单边万 3.5 / 双边万 6；
  - 惩罚：换手过高、空仓日过多、位置过于集中；
  - 同时给出**截面 Rank IC**（信息系数）作为因子质量的独立视角。

适应度（搜索目标，只用训练段）：
    fitness = IC_IR + 0.35 * clip(sortino_topk, -3, 6) - 2.0 * max(0, void_ratio - 0.35)
其中 IC_IR = mean(daily rank IC) / std(rank IC)，刻画因子的稳定预测力。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

#: 单边成本（佣金万2.5 + 卖出印花税千1 摊到单边 ≈ 万3.5；再加滑点万1.5）
DEFAULT_COST_ONE_WAY = 0.0005
TRADING_DAYS = 244


def _rank_ic(sig: np.ndarray, tgt: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """逐日截面 Rank IC（Spearman），向量化（scipy.rankdata axis=0）。"""
    try:
        from scipy.stats import rankdata as _rd
    except Exception:                                     # 无 scipy 时退回循环
        return _rank_ic_loop(sig, tgt, mask)
    m = mask if mask.dtype == bool else mask > 0
    cnt = m.sum(axis=0)
    s = np.where(m, sig, np.nan)
    y = np.where(m, tgt, np.nan)
    rs = _rd(s, axis=0)                 # NaN 排最后，非 NaN 元素的秩不变
    ry = _rd(y, axis=0)
    rs = np.where(m, rs, 0.0)
    ry = np.where(m, ry, 0.0)
    n = np.maximum(cnt, 1)
    rs = rs - (rs.sum(axis=0) / n)[None, :]
    ry = ry - (ry.sum(axis=0) / n)[None, :]
    num = (rs * ry).sum(axis=0)
    den = np.sqrt((rs * rs).sum(axis=0) * (ry * ry).sum(axis=0))
    ic = np.where((den > 1e-12) & (cnt >= 20), num / (den + 1e-12), 0.0)
    return np.nan_to_num(ic).astype(np.float32)


def _rank_ic_loop(sig: np.ndarray, tgt: np.ndarray, mask: np.ndarray) -> np.ndarray:
    T = sig.shape[1]
    out = np.zeros(T, dtype=np.float32)
    for t in range(T):
        m = mask[:, t]
        if m.sum() < 20:
            continue
        s = sig[m, t]
        y = tgt[m, t]
        if np.all(s == s[0]) or np.all(y == y[0]):
            continue
        sr = _rankdata(s)
        yr = _rankdata(y)
        sr = sr - sr.mean()
        yr = yr - yr.mean()
        den = np.sqrt((sr * sr).sum() * (yr * yr).sum())
        if den <= 0:
            continue
        out[t] = float((sr * yr).sum() / den)
    return out


def _rankdata(x: np.ndarray) -> np.ndarray:
    """平均秩（scipy 缺失时代替）。"""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=np.float32)
    ranks[order] = np.arange(1, len(x) + 1, dtype=np.float32)
    # 处理并列
    xs = x[order]
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return ranks


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = 1.0 - equity / (peak + 1e-12)
    return float(np.max(dd)) if dd.size else 0.0


def evaluate(sig: np.ndarray, target: np.ndarray, masks: Dict[str, np.ndarray],
             sl: slice, top_k: int = 20, cost_one_way: float = DEFAULT_COST_ONE_WAY,
             bench_daily: Optional[np.ndarray] = None, hold: int = 1,
             neutralize_fn=None) -> Dict[str, float]:
    """在 sl 指定的时间段上评估信号。sig/target 形状 [N, T]。

    bench_daily：可选，等权股票池的日收益序列（长度 T）。给了之后就额外给出
    **超额收益**指标（组合日收益 - 池日收益），搜索目标改用超额 Sortino，
    否则“高收益”可能只是押中了上涨的股票池。
    hold：持有天数。1 = 每日换仓；>1 时用 **重叠建仓（tranche）** 实现：
    每天建 1/hold 的仓、持有 hold 天，等价于对每日选股矩阵做 hold 日滚动平均，
    换手与交易成本随之降到约 1/hold（实测日频 0.55 换手 ≈ 13%/年成本，是主要拖累）。
    """
    N, T = sig.shape
    idx = np.arange(T)[sl]
    if idx.size < 30:
        return {"fitness": -3.0, "valid": 0.0, "ic": 0.0, "ic_ir": 0.0, "ret": 0.0,
                "ann": 0.0, "sharpe": 0.0, "sortino": 0.0, "maxdd": 0.0,
                "turnover": 1.0, "void_ratio": 1.0, "win_rate": 0.0, "n_days": float(idx.size)}

    if neutralize_fn is not None:
        sig = neutralize_fn(sig)
    tg = target[:, idx]
    can_buy = (masks["can_buy"][:, idx] > 0)
    if "_tradable" in masks:
        tradable = (masks["_tradable"][:, idx] > 0.5)
    else:
        tradable = np.ones_like(can_buy, dtype=bool)
    s_all = sig[:, idx]

    # 只在可买且原始数据存在的股票里选
    ok_all = can_buy & tradable
    score = np.where(ok_all, s_all, -np.inf)

    k = min(top_k, N)
    part = np.argpartition(-score, k - 1, axis=0)[:k]            # [k, T] 每日 Top-K
    finite = np.isfinite(score)
    sel_ok = np.take_along_axis(finite, part, axis=0)             # [k, T]
    sel_ret = np.take_along_axis(tg, part, axis=0)
    vals = np.where(sel_ok, sel_ret, np.nan)
    with np.errstate(invalid="ignore"):
        daily_ret = np.nanmean(vals, axis=0)
    held = sel_ok.sum(axis=0)                                     # 每日实际持仓数
    valid_day = (held > 0) & np.isfinite(daily_ret)

    # 换手：与前一日持仓集合的差异比例（向量化）
    M = np.zeros((N, idx.size), dtype=bool)
    np.put_along_axis(M, part, sel_ok, axis=0)
    held_f = np.maximum(held, 1).astype(np.float32)
    Mf = M.astype(np.float32) / held_f[None, :]                    # 每日等权组合权重
    if hold > 1 and idx.size > hold:
        # 重叠建仓：W = 过去 hold 天权重的平均（等价于每天建 1/hold 仓、持有 hold 天）
        c = np.cumsum(Mf, axis=1, dtype=np.float64)
        W = np.zeros_like(Mf)
        W[:, :hold] = c[:, :hold] / float(hold)
        W[:, hold:] = (c[:, hold:] - c[:, :-hold]) / float(hold)
    else:
        W = Mf
    tg0 = np.nan_to_num(tg)
    daily_free = (W * tg0).sum(axis=0)
    dw = np.abs(np.diff(W, axis=1)).sum(axis=0) if idx.size > 1 else np.zeros(0)
    turn = np.concatenate([[1.0], dw]) if idx.size > 1 else np.ones(1)
    daily = daily_free - cost_one_way * turn
    valid_day = (W.sum(axis=0) > 0) & np.isfinite(daily)
    daily = np.where(valid_day, daily, 0.0)
    void = int((~valid_day).sum())
    idx_size = int(idx.size)

    equity = np.cumprod(1.0 + daily)
    total = float(equity[-1] - 1.0)
    ann = float(equity[-1] ** (TRADING_DAYS / max(1, idx_size)) - 1.0) if equity[-1] > 0 else -1.0
    mu = float(np.mean(daily))
    sd = float(np.std(daily)) + 1e-9
    downside = daily[daily < 0]
    dsd = float(np.std(downside)) + 1e-9 if downside.size > 5 else sd
    sharpe = mu / sd * np.sqrt(TRADING_DAYS)
    sortino = mu / dsd * np.sqrt(TRADING_DAYS)
    maxdd = _max_drawdown(equity)
    win = float((daily > 0).sum()) / max(1, int((daily != 0).sum()))
    void_ratio = void / float(idx_size)

    # 超额（相对等权股票池）
    ex_ann = ex_sortino = ex_sharpe = 0.0
    ex_dd = 0.0
    if bench_daily is not None and bench_daily.size >= (sl.stop or bench_daily.size):
        ex = daily - bench_daily[idx]
        emu, esd = float(np.mean(ex)), float(np.std(ex)) + 1e-9
        edown = ex[ex < 0]
        edsd = float(np.std(edown)) + 1e-9 if edown.size > 5 else esd
        ex_sharpe = emu / esd * np.sqrt(TRADING_DAYS)
        ex_sortino = emu / edsd * np.sqrt(TRADING_DAYS)
        ex_eq = np.cumprod(1.0 + ex)
        ex_ann = float(ex_eq[-1] ** (TRADING_DAYS / max(1, idx_size)) - 1.0) if ex_eq[-1] > 0 else -1.0
        ex_dd = _max_drawdown(ex_eq)

    # IC 口径：只在"有行情的股票"上算相关，**不能叠加次日涨停过滤**——
    # A 股的短期反转/投机类信号恰好集中在次日涨停的样本上（实测：20 日反转 IC
    # 从 +0.0050 掉到 0.0000），混入可买性约束会把信号本身抹掉，搜索会变成瞎子。
    # 可买性只用于组合构建（score 处已经过滤）。
    ics = _rank_ic(s_all, tg, tradable)
    ic = float(np.mean(ics))
    ic_ir = float(np.mean(ics) / (np.std(ics) + 1e-9))
    turn_mean = float(np.mean(turn))

    # ── 成本压力测试（借鉴 AlphaMaster 的多目标奖励）：2× 成本下是否仍为正 ──
    # 为什么：组合的唯一死因就是成本（实测 H=5 在 10bp 就见底）——"低费率下好看"不算结论。
    daily_2x = daily_free - 2.0 * cost_one_way * turn
    daily_2x = np.where(valid_day, daily_2x, 0.0)
    eq2 = np.cumprod(1.0 + daily_2x)
    ann_2x = float(eq2[-1] ** (TRADING_DAYS / max(1, idx_size)) - 1.0) if eq2[-1] > 0 else -1.0
    ex_ann_2x = 0.0
    if bench_daily is not None and bench_daily.size >= (sl.stop or bench_daily.size):
        ex2 = daily_2x - bench_daily[idx]
        eqe2 = np.cumprod(1.0 + ex2)
        ex_ann_2x = float(eqe2[-1] ** (TRADING_DAYS / max(1, idx_size)) - 1.0) if eqe2[-1] > 0 else -1.0
    cost_breakeven_bp = float(np.mean(daily_free - (bench_daily[idx] if bench_daily is not None else 0.0))
                              / (2.0 * max(turn_mean, 1e-9)) * 1e4) if turn_mean > 0 else 0.0

    # ── 敞口/集中度（借鉴 AlphaMaster 的 exposure / beta-neutral 惩罚）──
    # 说明：我们做多头的组合，不做"因子中性"，但要知道**是不是靠押注某个方向赚钱**。
    #  · pool_beta：组合日收益对池日收益的回归斜率（>1 = 加杠杆式暴露，<1 = 防守）
    #  · top_weight_hhi：持仓权重集中度（HHI，等权时 ≈ 1/k）
    #  · side_share：组合收益里"与池同向"的占比（越高越像 beta 搬运工）
    pool_beta = 0.0
    side_share = 0.0
    if bench_daily is not None and bench_daily.size >= (sl.stop or bench_daily.size):
        b = bench_daily[idx]
        bv = float(np.var(b)) + 1e-12
        pool_beta = float(np.cov(daily, b, bias=True)[0, 1] / bv)
        both = ((daily > 0) & (b > 0)) | ((daily < 0) & (b < 0))
        side_share = float(both.mean())
    hhi = float(np.mean((W ** 2).sum(axis=0)))

    # 目标以因子预测力（IC_IR）为主，组合超额只做轻量正则：
    # 只用组合收益当目标会搜出“押中股票池 beta”的伪因子（实测过），IC 驱动的泛化更好。
    target_sortino = ex_sortino if bench_daily is not None else sortino
    fit = 2.0 * ic_ir + 0.2 * float(np.clip(target_sortino, -3.0, 6.0)) - 2.0 * max(0.0, void_ratio - 0.35)
    if not np.isfinite(fit):
        fit = -3.0
    return {"fitness": float(fit), "valid": 1.0, "ic": ic, "ic_ir": ic_ir, "ret": total,
            "ann": ann, "sharpe": float(sharpe), "sortino": float(sortino), "maxdd": maxdd,
            "turnover": turn_mean, "void_ratio": float(void_ratio), "win_rate": win,
            "ex_ann": ex_ann, "ex_sharpe": float(ex_sharpe), "ex_sortino": float(ex_sortino),
            "ex_maxdd": float(ex_dd), "n_days": float(idx_size),
            # 成本压力与敞口（2026-09-24 新增，借鉴 AlphaMaster 的多目标奖励）
            "ann_2x_cost": ann_2x, "ex_ann_2x_cost": ex_ann_2x,
            "cost_breakeven_bp": cost_breakeven_bp,
            "pool_beta": pool_beta, "side_share": side_share, "weight_hhi": hhi}


def bench_series(target: np.ndarray, masks: Dict[str, np.ndarray]) -> np.ndarray:
    """等权股票池日收益（可交易股票的目标收益均值），作为基准。"""
    ok = (masks["can_buy"] > 0)
    if "_tradable" in masks:
        ok = ok & (masks["_tradable"] > 0.5)
    cnt = ok.sum(axis=0)
    tot = np.where(ok, target, 0.0).sum(axis=0)
    b = np.where(cnt > 0, tot / np.maximum(cnt, 1), 0.0)
    return np.nan_to_num(b).astype(np.float32)


def combine_signals(sigs: list, weights: Optional[list] = None) -> np.ndarray:
    """多因子合成：每个信号先截面 rank 归一，再按权重加权（默认等权）。"""
    if not sigs:
        raise ValueError("empty")
    N, T = sigs[0].shape
    acc = np.zeros((N, T), dtype=np.float32)
    ws = weights or [1.0] * len(sigs)
    tot = float(sum(ws)) or 1.0
    try:
        from scipy.stats import rankdata as _rd
    except Exception:
        _rd = None
    for s, w in zip(sigs, ws):
        if _rd is not None:
            r = (_rd(s, axis=0) / max(1, N)).astype(np.float32)
        else:
            r = np.zeros_like(s)
            for t in range(T):
                r[:, t] = _rankdata(s[:, t]) / max(1, N)
        acc += (w / tot) * r
    return acc.astype(np.float32)


def signal_correlation(a: np.ndarray, b: np.ndarray, mask: Optional[np.ndarray] = None,
                       sample_days: int = 40) -> float:
    """两条信号的平均截面相关（抽样若干天，避免全量开销）。"""
    T = a.shape[1]
    step = max(1, T // sample_days)
    cors = []
    for t in range(0, T, step):
        x, y = a[:, t], b[:, t]
        if mask is not None:
            m = mask[:, t]
            x, y = x[m], y[m]
        if x.size < 20:
            continue
        sx, sy = np.std(x), np.std(y)
        if sx <= 1e-9 or sy <= 1e-9:
            continue
        cors.append(float(np.corrcoef(x, y)[0, 1]))
    return float(np.mean(cors)) if cors else 0.0
