# -*- coding: utf-8 -*-
"""组合级价值tilt 分配器 + 市场宽度第三路开关 的确定性验证(延续 value_hard_rule 的测试模式)。

验证 portfolio_value_alloc / market_breadth:_fraction_gt_ma 的规则正确性:
  ①三路信号多数决融合(顺风增配1.5/中性1.0/逆风减配0.3) —— 覆盖 favor/headwind/平局/空输入
  ②市场宽度(破年线占比) → 弱市/强市/中性 标签
  ③(可选)用真实跨板块池跑一次 market_breadth() 显示当前真实宽度。
运行: C:/Python314/python.exe backend/agent/verify_portfolio_tilt_alloc.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import pandas as pd

from backend.agent.decision_gate import (  # noqa: E402
    portfolio_value_alloc, market_breadth, _fraction_gt_ma,
    PORTFOLIO_W_FAV, PORTFOLIO_W_NEU, PORTFOLIO_W_HEAD,
)


def _alloc(index=None, breadth=None, spread=None) -> dict:
    return portfolio_value_alloc(index, breadth, spread)


def test_alloc_cases() -> list:
    """(name, index_tilt, breadth, value_spread, 期望tilt_label, 期望w)"""
    return [
        ("全顺风(指数/宽度/价差都指价值)", {"value_tilt": "value_favorable"},
         {"tilt": "value_favorable"}, 1.0, "value_favorable", PORTFOLIO_W_FAV),
        ("全逆风(都指成长领涨)", {"value_tilt": "value_headwind"},
         {"tilt": "value_headwind"}, 0.0, "value_headwind", PORTFOLIO_W_HEAD),
        ("二顺一逆 → 顺风", {"value_tilt": "value_favorable"},
         {"tilt": "value_favorable"}, 0.0, "value_favorable", PORTFOLIO_W_FAV),
        ("二逆一顺 → 逆风", {"value_tilt": "value_headwind"},
         {"tilt": "value_headwind"}, 1.0, "value_headwind", PORTFOLIO_W_HEAD),
        ("平局(中性+顺+逆) → 中性", {"value_tilt": "value_neutral"},
         {"tilt": "value_favorable"}, 0.0, "value_neutral", PORTFOLIO_W_NEU),
        ("全空(无信号) → 中性", {}, {}, None, "value_neutral", PORTFOLIO_W_NEU),
        ("值缺省(None) → 中性", None, None, None, "value_neutral", PORTFOLIO_W_NEU),
        ("宽度中性一角 → 中性(指数顺+价差顺+宽度中性=2顺1平→顺风) 错误样例: 实为顺风",
         {"value_tilt": "value_favorable"}, {"tilt": "value_neutral"}, 1.0,
         "value_favorable", PORTFOLIO_W_FAV),
    ]


def _mk_panel(n_above: int, n_below: int, ma: int = 250) -> dict:
    """造一个 close panel: n_above 只股 close>MA, n_below 只 close<MA. 用确定性序列."""
    frames = {}
    for i in range(n_above):
        # 持续上行 → 长期 close > MA
        vals = [float(10 + 0.02 * j) for j in range(ma + 30)]
        frames[f"a{i}"] = pd.DataFrame({"close": vals},
                                       index=pd.date_range("2024-01-01", periods=len(vals), freq="D"))
    for i in range(n_below):
        # 持续下行 → 长期 close < MA
        vals = [float(10 - 0.02 * j) for j in range(ma + 30)]
        frames[f"b{i}"] = pd.DataFrame({"close": vals},
                                       index=pd.date_range("2024-01-01", periods=len(vals), freq="D"))
    return frames


def test_breadth_cases() -> list:
    return [
        ("宽度>60%(涌升) → headwind", _mk_panel(8, 2), "value_headwind"),
        ("宽度<50%(破位) → favorable", _mk_panel(2, 8), "value_favorable"),
        ("中性(50~60%) → neutral", _mk_panel(5, 5), "value_neutral"),
        ("空面板 → neutral", {}, "value_neutral"),
    ]


def run() -> int:
    fails = 0
    print("=== 组合级价值tilt 分配器 + 市场宽度第三路开关 验证 ===")
    print("\n[① portfolio_value_alloc 多数决融合]")
    for name, it, br, sp, exp_label, exp_w in test_alloc_cases():
        # 最后一例是错误样例, 单独处理
        if "错误样例" in name:
            continue
        r = _alloc(it, br, sp)
        ok = (r["tilt_label"] == exp_label) and (r["w_value"] == exp_w)
        print(f"  {'✓' if ok else '✗'} {name}: 得到 {r['tilt_label']} w={r['w_value']} "
              f"(期望 {exp_label} w={exp_w}) | signal_parts={r['signal_parts']}")
        fails += 0 if ok else 1

    # 手写最后一个边界(宽度中性一角)
    r = _alloc({"value_tilt": "value_favorable"}, {"tilt": "value_neutral"}, 1.0)
    ok = r["tilt_label"] == "value_favorable"
    print(f"  {'✓' if ok else '✗'} 宽度中性一角(指数顺+价差顺+宽度平) → 顺风: 得 {r['tilt_label']} w={r['w_value']}")
    fails += 0 if ok else 1

    print("\n[② market_breadth / _fraction_gt_ma 破年线占比]")
    for name, panel, exp in test_breadth_cases():
        br = market_breadth(close_panel=panel)
        ok = br["tilt"] == exp
        print(f"  {'✓' if ok else '✗'} {name}: 宽度={br['breadth']} tilt={br['tilt']} (期望 {exp})")
        fails += 0 if ok else 1

    # 实时宽度(跨板块均衡池)
    print("\n[③ 真实市场宽度(跨板块均衡池, 约287只)]")
    try:
        live = market_breadth()
        print(f"  ✓ 真实宽度: breadth={live['breadth']:.2%} tilt={live['tilt']} | {live.get('reason','')}")
    except Exception as e:
        print(f"  ✗ 真实宽度失败: {type(e).__name__}: {str(e)[:120]}")
        fails += 1

    print("\n── 结论 ──")
    print(f"  组合级 value_tilt: 价值层权重随三路信号多数决调节(收缩增配/扩张减配), 非单票二值开关。")
    print(f"  市场宽度: 破250日年线占比 <50%→价值顺风(弱市), >60%→价值逆风(强市)。")
    print(f"  结果: {'全部通过' if fails == 0 else f'失败 {fails} 例'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
