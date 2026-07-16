"""评分调度器 - 串联因子计算 + 条件评测 + 加权汇总"""
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Optional

from .models import (
    StockScore, FactorGroupResult, IndicatorResult,
    ConditionResult, ScorecardConfig,
)
from .calculator import FactorCalculator
from .dsl import evaluate_indicator_conditions
from .config import load_config
from .filters import apply_filters, DEFAULT_FILTERS


def _clamp(v, lo, hi):
    if v is None:
        return 0.0
    return max(float(lo), min(float(hi), float(v)))


class FactorScorer:
    """多因子评分主调度器"""

    def __init__(self, config=None, config_path=None):
        if config is not None:
            self.config = config
        else:
            self.config = load_config(config_path)

    def score_stock(self, code, name, klines):
        calc = FactorCalculator(klines)
        factor_values = calc.compute_all()

        groups_result = []
        for group_cfg in self.config.groups:
            indicators = group_cfg.get("indicators", [])
            group_max = float(group_cfg.get("max_score", group_cfg.get("weight", 0)))
            group_min = float(group_cfg.get("min_score", -group_max))

            indicator_results = []
            group_raw = 0.0

            for ind_cfg in indicators:
                conditions = ind_cfg.get("conditions", [])
                ind_id = ind_cfg.get("id", "?")
                ind_name = ind_cfg.get("name", ind_id)

                cond_results_raw = evaluate_indicator_conditions(conditions, factor_values)
                ind_score = 0.0
                ind_max = 0.0
                cond_results = []
                for cr in cond_results_raw:
                    cond_results.append(ConditionResult(
                        cond_type=cr["cond_type"],
                        passed=cr["passed"],
                        score=cr["score"],
                        max_score=cr["max_score"],
                        reason=cr["reason"],
                        raw_args=cr.get("raw_args", []),
                    ))
                    ind_score += cr["score"]
                    ind_max += cr["max_score"]

                ind_config_max = float(ind_cfg.get("max_score", ind_max)) if ind_max > 0 else 0.0
                ind_config_min = float(ind_cfg.get("min_score", -ind_config_max))
                ind_score_clamped = _clamp(ind_score, ind_config_min, ind_config_max)

                indicator_results.append(IndicatorResult(
                    indicator_id=ind_id, name=ind_name,
                    score=ind_score_clamped, max_score=ind_config_max,
                    min_score=ind_config_min, conditions=cond_results,
                ))
                group_raw += ind_score_clamped

            group_raw_clamped = _clamp(group_raw, group_min, group_max)
            weight = float(group_cfg.get("weight", 0))
            groups_result.append(FactorGroupResult(
                group_id=group_cfg["id"],
                name=group_cfg.get("name", group_cfg["id"]),
                weight=weight, raw_score=group_raw_clamped,
                max_score=group_max, min_score=group_min,
                weighted_score=group_raw_clamped, indicators=indicator_results,
            ))

        total = sum(g.raw_score for g in groups_result)
        total = _clamp(total, 0.0, 100.0)

        return StockScore(
            code=code, name=name, total_score=total,
            groups=groups_result, factors=factor_values,
        )

    @staticmethod
    def _get_candidates(db_path):
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT code, name FROM stock_list WHERE status='active' ORDER BY code"
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            code = str(r[0]); name = str(r[1])
            if code[:2] not in ("60", "00", "30", "68"):
                continue
            result.append((code, name))
        return result

    @staticmethod
    def _get_batch_klines(db_path, codes, limit=60, ref_date=None):
        if not codes:
            return {}

        conn = sqlite3.connect(db_path)
        try:
            # 确定参考日期和截止日期
            if ref_date:
                # 回测模式: 使用指定的参考日期
                target_date = ref_date
                dt = datetime.strptime(target_date, "%Y%m%d")
            else:
                # 实时模式: 使用数据库中最新的日期
                latest = conn.execute("SELECT MAX(date) FROM kline_daily").fetchone()[0]
                target_date = latest
                dt = datetime.strptime(target_date, "%Y%m%d")

            # 计算下界日期（limit*2.5 日历日之前）
            cutoff = (dt - timedelta(days=int(limit * 2.5))).strftime("%Y%m%d")

            result = defaultdict(list)
            bs = 200
            for batch_start in range(0, len(codes), bs):
                bc = codes[batch_start:batch_start + bs]
                ph = ",".join("?" for _ in bc)
                # 加 date <= target_date 条件实现时间回溯
                sql = ("SELECT code, date, open, high, low, close, volume, amount "
                       "FROM kline_daily WHERE code IN (%s) AND date >= ? AND date <= ? "
                       "ORDER BY code, date" % ph)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, bc + [cutoff, target_date]).fetchall()
                for row in rows:
                    c = str(row["code"])
                    result[c].append({
                        "date": row["date"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]),
                        "amount": float(row["amount"]) if row["amount"] else 0,
                    })
        finally:
            conn.close()

        trimmed = {}
        for code, klines in result.items():
            if len(klines) > limit:
                klines = klines[-limit:]
            trimmed[code] = klines
        return trimmed

    def score_batch(self, db_path, top_n=20, min_klines=10,
                    progress_cb=None, timeout_seconds=0, ref_date=None,
                    filters=None):
        """批量评分所有候选股票

        Args:
            db_path: SQLite 数据库路径
            top_n: 返回前 N 名
            min_klines: 最少 K 线根数（不足则跳过）
            progress_cb: 进度回调 (已完成数, 总数)
            timeout_seconds: 超时秒数（0=不限时）
            ref_date: 参考日期 YYYYMMDD 格式，None=使用最新数据
            filters: 过滤配置 dict，None=使用默认过滤
            filters: 过滤配置 dict，None=使用默认过滤
        """
        t0 = time.time()
        candidates = self._get_candidates(db_path)
        if filters is not None:
            candidates = apply_filters(candidates, filters, db_path)
        else:
            candidates = apply_filters(candidates, DEFAULT_FILTERS, db_path)
        codes = [c[0] for c in candidates]
        name_map = dict(candidates)
        results = []
        total = len(codes)
        if not codes:
            return results

        all_klines = self._get_batch_klines(db_path, codes, limit=self.config.data_window, ref_date=ref_date)
        if progress_cb:
            progress_cb(0, total)

        for i, code in enumerate(codes):
            if timeout_seconds > 0 and (time.time() - t0) > timeout_seconds:
                break
            klines = all_klines.get(code, [])
            if len(klines) < min_klines:
                continue
            name = name_map.get(code, "?")
            try:
                score = self.score_stock(code, name, klines)
                results.append(score)
            except Exception:
                continue
            if progress_cb and (i % 100 == 0 or i == total - 1):
                progress_cb(i, total)

        results.sort(key=lambda x: x.total_score, reverse=True)
        return results[:top_n]

    def score_custom_list(self, db_path, codes, min_klines=10, ref_date=None, filters=None):
        """对指定代码列表评分

        Args:
            db_path: SQLite 数据库路径
            codes: 股票代码列表
            min_klines: 最少 K 线根数
            ref_date: 参考日期 YYYYMMDD 格式，None=使用最新数据
            filters: 过滤配置 dict，None=使用默认过滤
        """
        name_map = {}
        conn = sqlite3.connect(db_path)
        try:
            ph = ",".join("?" for _ in codes)
            for row in conn.execute(
                "SELECT code, name FROM stock_list WHERE code IN (%s)" % ph, codes
            ):
                name_map[str(row[0])] = str(row[1])
        finally:
            conn.close()

        all_klines = self._get_batch_klines(db_path, codes, limit=self.config.data_window, ref_date=ref_date)
        results = []
        for code in codes:
            klines = all_klines.get(code, [])
            if len(klines) < min_klines:
                continue
            name = name_map.get(code, "?")
            try:
                score = self.score_stock(code, name, klines)
                results.append(score)
            except Exception:
                continue
        results.sort(key=lambda x: x.total_score, reverse=True)
        return results

    def explain(self, score):
        lines = ["%s(%s) 总分: %.1f" % (score.name, score.code, score.total_score)]
        for g in score.groups:
            lines.append("  [%s] %.1f/%s (原始: %.1f)" % (
                g.name, g.weighted_score, g.max_score, g.raw_score))
            for ind in g.indicators:
                passes = [c for c in ind.conditions if c.passed and c.score != 0]
                if passes:
                    parts = []
                    for c in passes:
                        if c.score > 0:
                            parts.append("%s+%d" % (c.reason, int(c.score)))
                        else:
                            parts.append("%s%d" % (c.reason, int(c.score)))
                    lines.append("    %s: %s" % (ind.name, ", ".join(parts)))
        return "\n".join(lines)
