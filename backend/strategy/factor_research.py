# -*- coding: utf-8 -*-
"""截面因子研究引擎 — 移植自 QuantDinger 的 strategy_v2/factor_research.py。

对给定个股池(points-in-time frames)，按 factor 值分组，评估因子有效性：
IC / ICIR / IC正率 / 20期滚动IC / 分组累计收益 / 多空 / 月度单调性 / 换手与成本 /
因子相关性。用于"论证策略所选因子是否有效"，而非只靠单标的拟合。

frames: {symbol: pd.DataFrame(index=date, columns=[open,high,low,close,volume,...], 可含 industry)}
(与 QuantDinger 相同：信号用 close 时点可见，入场用 next open，出场 open 后 N 根 —— 无前视)
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd


class FactorResearchEngine:
    def run(
        self,
        *,
        frames: Mapping[str, pd.DataFrame],
        factor_id: str,
        start_date: Any,
        end_date: Any,
        groups: int = 5,
        holding_period: int = 5,
        commission: float = 0.0005,
        slippage: float = 0.0005,
        neutralize_industry: bool = False,
        compute_correlation: bool = True,
    ) -> dict[str, Any]:
        groups = max(2, min(10, int(groups or 5)))
        holding_period = max(1, int(holding_period or 5))
        factor_name = str(factor_id or "momentum_20").strip().lower()
        prepared = {
            symbol: frame.sort_index().loc[
                (frame.index >= pd.Timestamp(start_date)) & (frame.index <= pd.Timestamp(end_date))
            ].copy()
            for symbol, frame in frames.items()
        }
        close = self._panel(prepared, "close")
        open_price = self._panel(prepared, "open")
        if close.empty or open_price.empty:
            raise ValueError("factorResearchNoData")
        factor = self._factor_panel(prepared, factor_name, close)
        entry = open_price.shift(-1)
        exit_price = open_price.shift(-(holding_period + 1))
        forward_return = exit_price / entry - 1.0
        industry = self._industry_panel(prepared, close.index)
        research_dates = list(close.index[::holding_period])

        ic_rows, group_rows = [], []
        group_returns = {i: [] for i in range(1, groups + 1)}
        previous_members = {i: set() for i in range(1, groups + 1)}
        rank_autocorrelations = []
        previous_ranks = None
        total_obs, valid_obs = 0, 0

        for timestamp in research_dates:
            values = factor.loc[timestamp].replace([math.inf, -math.inf], pd.NA)
            returns = forward_return.loc[timestamp].replace([math.inf, -math.inf], pd.NA)
            total_obs += int(len(values))
            valid = pd.concat([values.rename("factor"), returns.rename("return")], axis=1).dropna()
            valid_obs += int(len(valid))
            if neutralize_industry and not valid.empty:
                sectors = industry.loc[timestamp].reindex(valid.index).fillna("Unclassified")
                valid["factor"] = valid["factor"] - valid.groupby(sectors)["factor"].transform("mean")
            if len(valid) < max(3, groups):
                continue
            ranks = valid["factor"].rank(method="average", pct=True)
            ic = float(ranks.corr(valid["return"].rank(method="average", pct=True), method="pearson"))
            ic_rows.append({"time": str(pd.Timestamp(timestamp)), "value": 0.0 if pd.isna(ic) else ic})
            if previous_ranks is not None:
                aligned = pd.concat([previous_ranks, ranks], axis=1).dropna()
                if len(aligned) >= 3:
                    ac = aligned.iloc[:, 0].rank(method="average").corr(
                        aligned.iloc[:, 1].rank(method="average"), method="pearson")
                    if not pd.isna(ac):
                        rank_autocorrelations.append(float(ac))
            previous_ranks = ranks

            labels = pd.qcut(valid["factor"].rank(method="first"), q=min(groups, len(valid)),
                             labels=False) + 1
            for group in range(1, groups + 1):
                members = set(valid.index[labels == group])
                if not members:
                    continue
                gross = float(valid.loc[list(members), "return"].mean())
                prev = previous_members[group]
                turnover = 1.0 if not prev else 1.0 - len(prev & members) / max(len(prev | members), 1)
                cost = turnover * 2.0 * (max(0.0, commission) + max(0.0, slippage))
                net = gross - cost
                previous_members[group] = members
                group_returns[group].append((pd.Timestamp(timestamp), gross, net))
                group_rows.append({"time": str(timestamp), "group": group, "grossReturn": gross,
                                   "netReturn": net, "turnover": turnover, "members": sorted(members)})

        if not ic_rows:
            raise ValueError("factorResearchInsufficientObservations")
        ic_series = pd.Series([float(i["value"]) for i in ic_rows], dtype="float64")
        ic_mean = float(ic_series.mean()) if not ic_series.empty else 0.0
        ic_std = float(ic_series.std(ddof=1)) if len(ic_series) > 1 else 0.0
        icir = ic_mean / ic_std * math.sqrt(252.0 / holding_period) if ic_std > 0 else 0.0
        rolling = ic_series.rolling(20, min_periods=5).mean()
        for idx, item in enumerate(ic_rows):
            item["rolling"] = None if pd.isna(rolling.iloc[idx]) else float(rolling.iloc[idx])

        curves, final_by_group = [], []
        for group, values in group_returns.items():
            gross_nav = net_nav = 1.0
            points = []
            for timestamp, gross, net in values:
                gross_nav *= 1.0 + gross
                net_nav *= 1.0 + net
                points.append({"time": str(timestamp), "gross": gross_nav, "net": net_nav})
            curves.append({"group": group, "points": points, "finalGross": gross_nav, "finalNet": net_nav})
            final_by_group.append(net_nav)

        long_short = self._long_short_curve(group_returns.get(groups, []), group_returns.get(1, []))
        monotonicity = 0.0
        if len(final_by_group) >= 3:
            monotonicity = float(pd.Series(range(1, len(final_by_group) + 1)).rank().corr(
                pd.Series(final_by_group).rank(), method="pearson"))
        coverage = valid_obs / total_obs if total_obs else 0.0
        avg_turnover = sum(float(g["turnover"]) for g in group_rows) / len(group_rows) if group_rows else 0.0
        half = max(1, len(ic_series) // 2)
        first_half, second_half = ic_series.iloc[:half], ic_series.iloc[half:]

        return {
            "factorId": factor_name, "rankIc": ic_mean, "icir": icir,
            "icPositiveRate": float((ic_series > 0).mean()) if not ic_series.empty else 0.0,
            "icSeries": ic_rows, "groupCurves": curves, "longShortCurve": long_short,
            "groupObservations": group_rows, "monotonicity": 0.0 if pd.isna(monotonicity) else monotonicity,
            "coverage": coverage, "missingRate": 1.0 - coverage, "averageTurnover": avg_turnover,
            "grossLongShortReturn": float(long_short[-1]["gross"] - 1.0) if long_short else 0.0,
            "netLongShortReturn": float(long_short[-1]["net"] - 1.0) if long_short else 0.0,
            "neutralized": bool(neutralize_industry),
            "factorCorrelation": self._factor_correlation(prepared, close)
            if compute_correlation else None,
            "stability": {"firstHalfIc": float(first_half.mean()) if not first_half.empty else 0.0,
                           "secondHalfIc": float(second_half.mean()) if not second_half.empty else 0.0,
                           "rankAutocorrelation": sum(rank_autocorrelations) / len(rank_autocorrelations)
                           if rank_autocorrelations else 0.0},
            "executionAssumptions": {"signal": "close_point_in_time", "entry": "next_bar_open",
                                     "exit": f"open_after_{holding_period}_bars",
                                     "commission": commission, "slippage": slippage},
        }

    @staticmethod
    def _panel(frames: Mapping[str, pd.DataFrame], field: str) -> pd.DataFrame:
        cols = {s: pd.to_numeric(frame[field], errors="coerce")
                for s, frame in frames.items() if field in frame.columns}
        return pd.DataFrame(cols).sort_index()

    def _factor_panel(self, frames, factor_id, close) -> pd.DataFrame:
        fid = str(factor_id or "momentum_20").strip().lower()
        if fid.startswith("momentum"):
            return close.pct_change(self._suffix_number(fid, 20))
        if fid.startswith("volatility"):
            return close.pct_change().rolling(self._suffix_number(fid, 20)).std()
        if fid.startswith("reversal"):
            return -close.pct_change(self._suffix_number(fid, 5))
        if fid.startswith("skew"):
            return close.pct_change().rolling(self._suffix_number(fid, 20)).skew()
        if fid.startswith("kurt"):
            return close.pct_change().rolling(self._suffix_number(fid, 20)).kurt()
        if fid == "rsi14":
            return self._rsi(close, 14)
        return close.pct_change(20)  # 未知 → 退化为 momentum20

    @staticmethod
    def _rsi(close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Wilder 相对强弱指数(横截面向量化)。avg_loss→0 时 RSI 趋于 100。"""
        delta = close.diff()
        gain = delta.clip(lower=0.0).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
        loss = (-delta.clip(upper=0.0)).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
        rs = gain / loss.replace(0.0, pd.NA)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        return rsi.fillna(100.0)

    @staticmethod
    def _suffix_number(value: str, default: int) -> int:
        try:
            return max(1, int(value.rsplit("_", 1)[-1]))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _industry_panel(frames, index):
        cols = {}
        for s, frame in frames.items():
            if "industry" in frame.columns:
                cols[s] = frame["industry"].reindex(index).ffill()
        return pd.DataFrame(cols, index=index)

    @staticmethod
    def _long_short_curve(long_values, short_values):
        short_map = {ts: (g, n) for ts, g, n in short_values}
        gross_nav = net_nav = 1.0
        points = []
        for ts, long_g, long_n in long_values:
            if ts not in short_map:
                continue
            short_g, short_n = short_map[ts]
            gross_nav *= 1.0 + long_g - short_g
            net_nav *= 1.0 + long_n - short_n
            points.append({"time": str(ts), "gross": gross_nav, "net": net_nav})
        return points

    def _factor_correlation(self, frames, close):
        factors = {
            "momentum_20": close.pct_change(20),
            "momentum_60": close.pct_change(60),
            "reversal_5": -close.pct_change(5),
            "reversal_20": -close.pct_change(20),
            "volatility_20": close.pct_change().rolling(20).std(),
            "volatility_60": close.pct_change().rolling(60).std(),
            "skew_20": close.pct_change().rolling(20).skew(),
        }
        stacked = {n: p.stack(future_stack=True) for n, p in factors.items()}
        matrix = pd.DataFrame(stacked).rank().corr().fillna(0.0)
        return {"factors": list(matrix.columns),
                "matrix": [[float(matrix.loc[r, c]) for c in matrix.columns] for r in matrix.index]}
