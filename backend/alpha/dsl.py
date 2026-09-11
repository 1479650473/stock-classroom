# -*- coding: utf-8 -*-
"""因子公式 DSL —— 特征表 + 算子表 + 栈式 VM（numpy 面板实现）。

设计取自 AlphaGPT（`model_core/ops.py` + `vm.py` + `times.py` 的 Polish 记法），
按 A 股面板数据重写：

    公式 = 一串 token（前序/Polish 记法），用栈求值；
    每个 token 要么是**特征**（[股票 × 交易日] 的二维数组），要么是**算子**；
    求值结果是一条截面因子值：第 t 列是"截至 t 日收盘可得的信息"算出的分数。

关键约定
    - 所有数组形状 [N, T]（N=股票数，T=交易日数），float32；
    - **无前视**：特征只用 t 及之前的数据；求值只用逐元素/向后取值的算子；
    - 公式合法性由构造保证（递归建树 / 交叉变异时保持 arity），非法公式求值返回 None。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

EPS = 1e-9


# ───────────────────────── 算子 ─────────────────────────

def _delay(x: np.ndarray, d: int) -> np.ndarray:
    """向后平移 d 天：第 t 列取 t-d 列（前面补 0），保证只用历史。"""
    if d <= 0:
        return x
    out = np.zeros_like(x)
    out[:, d:] = x[:, :-d]
    return out


def _op_gate(cond: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """condition > 0 取 x，否则取 y（截面逐元素）。"""
    m = (cond > 0).astype(np.float32)
    return m * x + (1.0 - m) * y


def _op_jump(x: np.ndarray) -> np.ndarray:
    """极端跳变：逐股票 zscore 超过 3 的部分。"""
    mu = x.mean(axis=1, keepdims=True)
    sd = x.std(axis=1, keepdims=True) + EPS
    z = (x - mu) / sd
    return np.maximum(z - 3.0, 0.0).astype(np.float32)


def _op_decay(x: np.ndarray) -> np.ndarray:
    return (x + 0.8 * _delay(x, 1) + 0.6 * _delay(x, 2)).astype(np.float32)


def _op_ts_mean(x: np.ndarray, d: int) -> np.ndarray:
    """过去 d 日均值（含当日）—— 严格因果的移动平均。"""
    out = np.zeros_like(x)
    c = np.cumsum(x, axis=1, dtype=np.float32)
    out[:, :d] = c[:, :d] / np.arange(1, min(d, x.shape[1]) + 1, dtype=np.float32)[None, :min(d, x.shape[1])]
    if x.shape[1] > d:
        out[:, d:] = (c[:, d:] - c[:, :-d]) / float(d)
    return out


def _op_ts_std(x: np.ndarray, d: int) -> np.ndarray:
    m = _op_ts_mean(x, d)
    m2 = _op_ts_mean(x * x, d)
    return np.sqrt(np.maximum(m2 - m * m, 0.0)).astype(np.float32)


def _op_ts_zscore(x: np.ndarray, d: int) -> np.ndarray:
    return ((x - _op_ts_mean(x, d)) / (_op_ts_std(x, d) + EPS)).astype(np.float32)


def _op_ts_delta(x: np.ndarray, d: int) -> np.ndarray:
    return (x - _delay(x, d)).astype(np.float32)


#: 名称 → (arity, 求值函数)。arity=0 留给特征 token。
OPS: Dict[str, Tuple[int, Callable]] = {
    "ADD": (2, lambda a, b: (a + b).astype(np.float32)),
    "SUB": (2, lambda a, b: (a - b).astype(np.float32)),
    "MUL": (2, lambda a, b: (a * b).astype(np.float32)),
    "DIV": (2, lambda a, b: (a / (np.abs(b) + 1e-6)).astype(np.float32)),
    "MAX": (2, lambda a, b: np.maximum(a, b)),
    "MIN": (2, lambda a, b: np.minimum(a, b)),
    "NEG": (1, lambda a: (-a).astype(np.float32)),
    "ABS": (1, lambda a: np.abs(a)),
    "SIGN": (1, lambda a: np.sign(a).astype(np.float32)),
    "GATE": (3, _op_gate),
    "JUMP": (1, _op_jump),
    "DECAY": (1, _op_decay),
    "DELAY1": (1, lambda a: _delay(a, 1)),
    "MEAN5": (1, lambda a: _op_ts_mean(a, 5)),
    "MEAN20": (1, lambda a: _op_ts_mean(a, 20)),
    "STD20": (1, lambda a: _op_ts_std(a, 20)),
    "ZSCORE20": (1, lambda a: _op_ts_zscore(a, 20)),
    "DELTA5": (1, lambda a: _op_ts_delta(a, 5)),
}

OP_NAMES: Tuple[str, ...] = tuple(OPS.keys())
OP_ARITY: Dict[str, int] = {k: v[0] for k, v in OPS.items()}


# ───────────────────────── VM ─────────────────────────

def interpret(tokens: List[str], feats: Dict[str, np.ndarray]) -> Optional[np.ndarray]:
    """求值（Polish/前缀记法：算子在前、操作数在后）。

    实现上反向遍历 token 序列，即变成后缀（RPN）求值（与 AlphaGPT `times.py`
    的 `solve_one` 一致）。非法公式/常数结果返回 None。
    """
    stack: List[np.ndarray] = []
    try:
        for tk in reversed(tokens):
            if tk in OPS:
                arity, fn = OPS[tk]
                if len(stack) < arity:
                    return None
                args = [stack.pop() for _ in range(arity)]
                args.reverse()
                res = fn(*args)
            else:
                arr = feats.get(tk)
                if arr is None:
                    return None
                res = arr
            if res.dtype != np.float32:
                res = res.astype(np.float32)
            if not np.isfinite(res).all():
                res = np.nan_to_num(res, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32)
            stack.append(res)
    except Exception:
        return None
    if len(stack) != 1:
        return None
    out = stack[0]
    if out.shape != next(iter(feats.values())).shape:
        return None
    if float(out.std()) < 1e-6:      # 常数因子无意义
        return None
    return out


def decode(tokens: List[str]) -> str:
    """token 序列 → 人类可读公式。"""
    stream = list(tokens)

    def parse() -> str:
        if not stream:
            raise ValueError("empty")
        tk = stream.pop(0)
        if tk in OPS:
            arity = OP_ARITY[tk]
            args = [parse() for _ in range(arity)]
            return f"{tk}({','.join(args)})"
        return tk

    try:
        s = parse()
        return s if not stream else s + "  [尾部多余 token]"
    except Exception:
        return "<非法公式>"


def token_list(expr: str) -> List[str]:
    """人类可读公式 → token 序列（供手工输入的公式用）。"""
    import re
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr) if t]


# ───────────────────────── 随机建树（遗传搜索用） ─────────────────────────

def random_tree(rng: np.random.Generator, features: Tuple[str, ...],
                max_nodes: int = 12) -> List[str]:
    """生成一棵合法公式树（节点数 ≤ max_nodes）。"""
    budget = {"n": max(1, int(rng.integers(2, max_nodes + 1)))}

    def build() -> List[str]:
        # 叶子：特征
        if budget["n"] <= 1 or rng.random() < 0.35:
            budget["n"] -= 1
            return [features[int(rng.integers(len(features)))]]
        name = OP_NAMES[int(rng.integers(len(OP_NAMES)))]
        arity = OP_ARITY[name]
        budget["n"] -= 1
        if budget["n"] < arity:
            budget["n"] = 1
            return [features[int(rng.integers(len(features)))]]
        return [name] + [t for _ in range(arity) for t in build()]

    return build()


def count_nodes(tokens: List[str]) -> int:
    return len(tokens)


def subtree_spans(tokens: List[str]) -> List[Tuple[int, int]]:
    """列出所有子树 [start, end) 区间（token 序列的 Polish 结构）。"""
    spans: List[Tuple[int, int]] = []
    i = 0
    while i < len(tokens):
        start = i
        need = 1
        j = i
        while j < len(tokens) and need > 0:
            need -= 1
            if tokens[j] in OPS:
                need += OP_ARITY[tokens[j]]
            j += 1
        if need == 0:
            spans.append((start, j))
        i = j
    return spans
