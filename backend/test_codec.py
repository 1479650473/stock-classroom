# -*- coding: utf-8 -*-
"""codec / resilience 单元测试。

运行:  python backend/test_codec.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from codec import normalize_a_code, ak_symbol  # noqa: E402
from resilience import retry_with_backoff  # noqa: E402


def run():
    res = []
    def chk(label, got, want):
        ok = got == want
        res.append((label, ok, got, want))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")

    # ── normalize_a_code ───────────────────────────────────────────
    chk("股票裸码保持", normalize_a_code("600036", "stock"), "600036")
    chk("股票 .SH 剥后缀", normalize_a_code("600036.SH", "stock"), "600036")
    chk("股票 .SZ 剥后缀", normalize_a_code("000001.SZ", "stock"), "000001")
    chk("股票 sh 前缀剥前缀", normalize_a_code("sh600036", "stock"), "600036")
    chk("股票 sz 前缀剥前缀", normalize_a_code("sz000001", "stock"), "000001")
    chk("指数裸码→sh000001", normalize_a_code("000001", "index"), "sh000001")
    chk("指数裸码399→sz399001", normalize_a_code("399001", "index"), "sz399001")
    chk("指数 .SH→sh000001", normalize_a_code("000001.SH", "index"), "sh000001")
    chk("指数 sh000001 保留", normalize_a_code("sh000001", "index"), "sh000001")
    chk("港股→hk00700", normalize_a_code("700", "hk"), "hk00700")
    chk("港股5位", normalize_a_code("00700", "hk"), "hk00700")
    # 000001 歧义: auto 不猜 → 裸码; 显式 index → sh000001
    chk("000001 auto→裸(不猜)", normalize_a_code("000001", "auto"), "000001")

    # ── ak_symbol ──────────────────────────────────────────────────
    chk("股票 symbol sh600036", ak_symbol("600036", "stock"), "sh600036")
    chk("股票 symbol sz000001", ak_symbol("000001", "stock"), "sz000001")
    chk("指数 symbol = 存储码", ak_symbol("000001", "index"), "sh000001")

    # ── retry_on_empty: 返回空→重试 → 第3次成功 ──────────────────────
    calls = {"n": 0}
    @retry_with_backoff(max_attempts=3, base_delay=0.01, max_delay=0.05, retry_on_empty=True)
    def flaky(v):
        calls["n"] += 1
        if calls["n"] < 3:
            return []          # 前两次空
        return [1, 2, 3]
    try:
        r = flaky("x")
        chk("空结果重试后成功", r, [1, 2, 3])
        chk("重试次数=3", calls["n"], 3)
    except Exception as e:
        chk("空结果重试后成功(异常)", str(e), "无")

    # ── retry: 总失败 → 抛最后一个异常 ─────────────────────────────
    err_calls = {"n": 0}
    @retry_with_backoff(max_attempts=2, base_delay=0.01, max_delay=0.05)
    def always_fail():
        err_calls["n"] += 1
        raise ValueError("boom")
    try:
        always_fail()
        chk("总失败抛异常", "no-exc", "ValueError")
    except ValueError:
        chk("总失败抛异常", True, True)
        chk("失败尝试次数=2", err_calls["n"], 2)

    # ── retry: 成功不重试 ────────────────────────────────────────────
    ok_calls = {"n": 0}
    @retry_with_backoff(max_attempts=3, retry_on_empty=True)
    def always_ok():
        ok_calls["n"] += 1
        return "ok"
    r = always_ok()
    chk("成功不重试", r, "ok")
    chk("成功只调1次", ok_calls["n"], 1)

    ok = all(x[1] for x in res)
    print(f"\ncodec/resilience 自检: {sum(1 for x in res if x[1])}/{len(res)} 通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
