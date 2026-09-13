# -*- coding: utf-8 -*-
"""probe_fund_flow.py — 探测东财资金流接口反爬状态 + 测安全拉取速率.

用法: python scripts/probe_fund_flow.py [--interval 3] [--batch 30]
每 60s 探测 1 只; 恢复后按指定间隔连续拉 batch 只, 统计失败率 → 判断安全速率.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


def main():
    from akshare_source import ak_fetch_fund_flow
    import logging
    logging.basicConfig(
        filename=os.path.join(ROOT, "data", "logs", "probe_fund_flow.log"),
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    interval = 3.0
    batch = 30
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--interval" and i + 1 < len(args):
            interval = float(args[i + 1])
        if a == "--batch" and i + 1 < len(args):
            batch = int(args[i + 1])

    def log(msg):
        print(msg, flush=True)
        logging.info(msg)

    # 探测恢复
    probe = ["600036", "000858", "002594", "601318", "000333"]
    pi = 0
    log("探测中(每60s一只, 直到接口恢复)...")
    while True:
        c = probe[pi % len(probe)]
        rows = ak_fetch_fund_flow(c)
        if rows:
            log(f"恢复! {c} -> {len(rows)} 条 (最早 {rows[0][1]} ~ 最新 {rows[-1][1]})")
            break
        pi += 1
        time.sleep(60)

    # 测安全速率
    test = ["600036", "000001", "600519", "000858", "601318", "002594", "300750", "000333",
            "600900", "601899", "000725", "600030", "002415", "688981", "300059", "600276",
            "000651", "600887", "601012", "600009"]
    ok = fail = 0
    for c in test[:batch]:
        t0 = time.time()
        rows = ak_fetch_fund_flow(c)
        dt = time.time() - t0
        if rows:
            ok += 1
        else:
            fail += 1
            log(f"  FAIL {c}")
        time.sleep(max(0, interval - dt))
    log(f"速率测试: {ok}/{len(test[:batch])} 成功, 失败 {fail} @ 间隔 {interval}s")
    log("结论: " + ("可全量拉取" if fail == 0 else "需降速或分批"))


if __name__ == "__main__":
    main()