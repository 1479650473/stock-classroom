
"""条件 DSL 求值器 — 将 JSON 条件树翻译为布尔结果"""


NUMERIC_OPS = {
    "gt": lambda v, t: v > t,
    "gte": lambda v, t: v >= t,
    "lt": lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: abs(v - t) < 1e-9 if isinstance(t, (int, float)) else v == t,
    "neq": lambda v, t: abs(v - t) >= 1e-9 if isinstance(t, (int, float)) else v != t,
}


def _resolve_arg(arg, values: dict) -> float:
    """解析参数：字符串查因子值，数字直接返回，布尔转 0/1"""
    if isinstance(arg, (int, float)):
        return float(arg)
    if isinstance(arg, bool):
        return 1.0 if arg else 0.0
    if isinstance(arg, str):
        v = values.get(arg)
        if v is None:
            return None
        return float(v)
    return None


def evaluate(condition: dict, values: dict) -> bool:
    """递归求值一条条件（JSON 节点）。

    支持的节点类型：
      gt/gte/lt/lte/eq/neq: {"type": "gt", "args": ["MA5", "MA10"]}
      between:               {"type": "between", "args": ["VOL_RATIO_5", 1.5, 3.0]}
      cross_above:           {"type": "cross_above", "args": ["MACD_DIF", "MACD_DEA"], "prev": {"MACD_DIF": 0.1, "MACD_DEA": 0.2}}
      cross_below:           {"type": "cross_below", "args": ["MACD_DIF", "MACD_DEA"]}
      and/or/not:            {"type": "and", "args": [cond1, cond2]}
      true:                  {"type": "true"}  — 始终通过
    """
    cond_type = condition.get("type")
    args = condition.get("args", [])
    prev_vals = condition.get("prev", {})

    # ── 逻辑组合 ──
    if cond_type == "and":
        for sub in args:
            if not evaluate(sub, values):
                return False
        return True

    if cond_type == "or":
        for sub in args:
            if evaluate(sub, values):
                return True
        return False

    if cond_type == "not":
        if not args:
            return False
        return not evaluate(args[0], values)

    if cond_type == "true":
        return True

    # ── 数值比较 ──
    if cond_type in NUMERIC_OPS:
        if len(args) < 2:
            return False
        v = _resolve_arg(args[0], values)
        t = _resolve_arg(args[1], values)
        if v is None or t is None:
            return False
        return NUMERIC_OPS[cond_type](v, t)

    # ── 区间 ──
    if cond_type == "between":
        if len(args) < 3:
            return False
        v = _resolve_arg(args[0], values)
        lo = _resolve_arg(args[1], values)
        hi = _resolve_arg(args[2], values)
        if v is None or lo is None or hi is None:
            return False
        return lo <= v <= hi

    # ── 上穿 / 下穿 ──
    if cond_type == "cross_above":
        if len(args) < 2:
            return False
        cur_v = _resolve_arg(args[0], values)
        cur_t = _resolve_arg(args[1], values)
        prev_v = _resolve_arg(args[0], prev_vals) if prev_vals else None
        prev_t = _resolve_arg(args[1], prev_vals) if prev_vals else None
        if None in (cur_v, cur_t, prev_v, prev_t):
            return False
        return prev_v <= prev_t and cur_v > cur_t

    if cond_type == "cross_below":
        if len(args) < 2:
            return False
        cur_v = _resolve_arg(args[0], values)
        cur_t = _resolve_arg(args[1], values)
        prev_v = _resolve_arg(args[0], prev_vals) if prev_vals else None
        prev_t = _resolve_arg(args[1], prev_vals) if prev_vals else None
        if None in (cur_v, cur_t, prev_v, prev_t):
            return False
        return prev_v >= prev_t and cur_v < cur_t

    return False


def evaluate_indicator_conditions(conditions: list[dict], values: dict) -> list[dict]:
    """评测一个指标下的所有条件，返回 [{passed, score, max, reason, raw_args}]"""
    results = []
    for cond in conditions:
        try:
            passed = evaluate(cond, values)
        except Exception:
            passed = False
        raw_score = cond.get("score", 0)
        max_score = cond.get("max", abs(raw_score))
        results.append({
            "cond_type": cond.get("type", ""),
            "passed": passed,
            "score": raw_score if passed else 0.0,
            "max_score": max_score,
            "reason": cond.get("reason", ""),
            "raw_args": cond.get("args", []),
        })
    return results
