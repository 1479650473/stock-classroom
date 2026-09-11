# -*- coding: utf-8 -*-
"""遗传搜索 —— 在公式空间里找适应度最高的因子（纯 numpy，无新依赖）。

搜索对象就是 dsl 里的 token 树：
  - 初始种群：随机合法树；
  - 选择：锦标赛；
  - 交叉：两个父代各取一个子树互换（保持 arity 合法）；
  - 变异：替换一个随机子树，或整棵树重置；
  - 精英保留 + 去重（token 序列相同只保留一个）。

为什么先用遗传而不是 AlphaGPT 的 Transformer+REINFORCE：
  1. 公式空间不大（十几个算子 + 十几个特征，深度 ≤ 4），遗传搜索够用；
  2. 不引入 torch 依赖（打包体积），也更好解释、可复现；
  3. 后续可把遗传的种群当作 RL 的引导（阶段 B 再评估，见 docs）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .dsl import OP_ARITY, OP_NAMES, decode, interpret, random_tree, subtree_spans


@dataclass
class Candidate:
    tokens: List[str]
    score: float = -9.9
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class GAResult:
    best: List[Candidate]
    history: List[float]
    n_eval: int


class GASearch:
    def __init__(self, features: Tuple[str, ...], evaluate_fn: Callable[[List[str]], Tuple[float, dict]],
                 population: int = 300, generations: int = 40, max_nodes: int = 12,
                 elite: int = 10, tournament: int = 4, crossover_rate: float = 0.6,
                 mutate_rate: float = 0.4, seed: int = 7, verbose: bool = True):
        self.features = features
        self.evaluate_fn = evaluate_fn
        self.pop_size = population
        self.generations = generations
        self.max_nodes = max_nodes
        self.elite = elite
        self.tournament = tournament
        self.crossover_rate = crossover_rate
        self.mutate_rate = mutate_rate
        self.rng = np.random.default_rng(seed)
        self.py_rng = random.Random(seed)
        self.verbose = verbose
        self.n_eval = 0

    # ── 遗传操作 ──
    def _rand_tree(self) -> List[str]:
        return random_tree(self.rng, self.features, self.max_nodes)

    def _pick_subtree(self, tokens: List[str]) -> Tuple[int, int]:
        spans = subtree_spans(tokens)
        if not spans:
            return 0, len(tokens)
        return spans[self.py_rng.randrange(len(spans))]

    def _crossover(self, a: List[str], b: List[str]) -> List[str]:
        (as_, ae) = self._pick_subtree(a)
        (bs, be) = self._pick_subtree(b)
        child = a[:as_] + b[bs:be] + a[ae:]
        return child if len(child) <= self.max_nodes * 2 else a

    def _mutate(self, tokens: List[str]) -> List[str]:
        if self.py_rng.random() < 0.25:
            return self._rand_tree()
        (s, e) = self._pick_subtree(tokens)
        new_sub = self._rand_tree()
        child = tokens[:s] + new_sub + tokens[e:]
        return child if len(child) <= self.max_nodes * 2 else new_sub

    def _tournament(self, pop: List[Candidate]) -> Candidate:
        picks = [pop[self.py_rng.randrange(len(pop))] for _ in range(self.tournament)]
        return max(picks, key=lambda c: c.score)

    # ── 主循环 ──
    def run(self, seed_tokens: Optional[List[List[str]]] = None) -> GAResult:
        pop: List[Candidate] = [Candidate(t) for t in (seed_tokens or [])]
        seen = {tuple(c.tokens) for c in pop}
        while len(pop) < self.pop_size:
            t = self._rand_tree()
            if tuple(t) in seen:
                continue
            seen.add(tuple(t))
            pop.append(Candidate(t))

        history: List[float] = []
        for gen in range(self.generations):
            for c in pop:
                if c.score <= -9.0:
                    sc, mt = self.evaluate_fn(c.tokens)
                    c.score, c.metrics = sc, mt
                    self.n_eval += 1
            pop.sort(key=lambda c: -c.score)
            history.append(pop[0].score)
            if self.verbose:
                best = pop[0]
                print(f"  gen {gen + 1:>3}/{self.generations}  best {pop[0].score:6.3f}  "
                      f"ic {best.metrics.get('ic', 0):+.4f}  ic_ir {best.metrics.get('ic_ir', 0):+.3f}  "
                      f"ann {best.metrics.get('ann', 0) * 100:+6.1f}%  "
                      f"maxdd {best.metrics.get('maxdd', 0) * 100:5.1f}%  "
                      f"| {decode(best.tokens)}", flush=True)
            if gen == self.generations - 1:
                break
            nxt: List[Candidate] = [Candidate(c.tokens, c.score, c.metrics) for c in pop[:self.elite]]
            seen = {tuple(c.tokens) for c in nxt}
            guard = 0
            while len(nxt) < self.pop_size and guard < self.pop_size * 30:
                guard += 1
                if self.py_rng.random() < self.crossover_rate:
                    child = self._crossover(self._tournament(pop).tokens, self._tournament(pop).tokens)
                else:
                    child = self._tournament(pop).tokens
                if self.py_rng.random() < self.mutate_rate:
                    child = self._mutate(child)
                if tuple(child) in seen:
                    continue
                seen.add(tuple(child))
                nxt.append(Candidate(child))
            pop = nxt
        pop.sort(key=lambda c: -c.score)
        return GAResult(best=pop, history=history, n_eval=self.n_eval)


def dedupe(cands: List[Candidate], corr_fn: Callable[[List[str], List[str]], float],
           top: int = 10, max_corr: float = 0.85) -> List[Candidate]:
    """按相关性去重：贪心保留高分的、互相不太像的公式。"""
    out: List[Candidate] = []
    for c in cands:
        if len(out) >= top:
            break
        if all(corr_fn(c.tokens, o.tokens) <= max_corr for o in out):
            out.append(c)
    return out
