# -*- coding: utf-8 -*-
"""M1 Agent Gateway 冒烟测试 — 端到端验证 能力分级/异步job/paper-only安全/R接口。

运行(项目根，项目解释器)：
  python backend/agent/smoke_test.py
直接复用 Web API 的 Flask test_client（create_app），不依赖启动真实服务器。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.api.server import create_app  # noqa: E402
from backend.agent import gateway as gw  # noqa: E402


# ── 示例策略(与 run_vertical_slice 相同，确保可回测) ─────────────────
STRATEGY = {
    "name": "均线金叉 + 超卖反弹",
    "description": "MA5上穿MA10 且 收盘>MA20 且 RSI14在40~70 买入；RSI14>75 或 MACD死叉 卖出；止损5%止盈12%",
    "universe": {"code": "600036", "name": "招商银行"},
    "entry": {"type": "and", "args": [
        {"type": "eq", "args": ["MA5_CROSS_UP_MA10", 1]},
        {"type": "gt", "args": ["CLOSE", "MA20"]},
        {"type": "between", "args": ["RSI14", 40, 70]},
    ]},
    "exit": {"type": "or", "args": [
        {"type": "gt", "args": ["RSI14", 75]},
        {"type": "eq", "args": ["MACD_CROSS_DOWN", 1]},
    ]},
    "position_sizing": {"mode": "percent_of_equity", "value": 0.95},
    "risk": {"stop_loss_pct": 0.05, "take_profit_pct": 0.12, "allow_short": False},
    "params": {"initial_balance": 100000.0},
}


def main():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    results = []

    def check(label, cond, extra=""):
        results.append((label, bool(cond), extra))
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))

    # ── 签发 token(R,W,B,T, paper-only) ──────────────────────────────
    tok_rwbt = gw.issue_token("default", "R,W,B,T", paper_only=True, rate_limit_per_min=200)
    tok_r = gw.issue_token("default", "R", paper_only=True, rate_limit_per_min=200)
    full_rwbt = tok_rwbt["full_token"]
    full_r = tok_r["full_token"]
    h_ok = {"Authorization": f"Bearer {full_rwbt}"}
    h_r = {"Authorization": f"Bearer {full_r}"}
    check("签发 token(RWBT/R)", bool(full_rwbt and full_r))

    def get(path, headers=h_ok, **kw):
        return client.get(path, headers=headers, **kw)

    def post(path, headers=h_ok, **kw):
        return client.post(path, headers=headers, **kw)

    # ── 安全：无/错 token → 401 ─────────────────────────────────────
    r = get("/api/agent/v1/macro/regime", headers={})
    check("无token被拒(401)", r.status_code == 401, f"{r.status_code}")
    r = get("/api/agent/v1/macro/regime", headers={"Authorization": "Bearer bad"})
    check("错token被拒(401)", r.status_code == 401, f"{r.status_code}")

    # ── 能力分级：R token 不能 B/W/T ───────────────────────────────
    r = post("/api/agent/v1/backtest/run", headers=h_r, json={"strategy_id": 1})
    check("R token 不能回测(403)", r.status_code == 403, f"{r.status_code}")
    r = post("/api/agent/v1/strategies", headers=h_r, json=STRATEGY)
    check("R token 不能写策略(403)", r.status_code == 403, f"{r.status_code}")

    # ── R: 宏观 ───────────────────────────────────────────────────────
    r = get("/api/agent/v1/health")
    check("health(200)", r.status_code == 200)
    r = get("/api/agent/v1/macro/regime")
    d = r.get_json().get("data", {})
    check("macro/regime(整体标签非空)", bool(d.get("overall")), d.get("overall", "")[:40])
    check("macro/regime(含类别5)", len(d.get("categories", {})) >= 5,
          str(len(d.get("categories", {}))))
    check("macro/regime(as_of 新鲜度)", d.get("freshness_days") is not None,
          f"{d.get('freshness_days')}天前")

    r = get("/api/agent/v1/macro/indicators?category=fx")
    check("macro/indicators(fx)", r.status_code == 200 and len(r.get_json().get("data", [])) >= 1)

    # ── R: 目录 ───────────────────────────────────────────────────────
    r = get("/api/agent/v1/catalog/stats")
    d = r.get_json().get("data", {})
    check("catalog/stats(A股5211+)" , d.get("total_stocks", 0) >= 5000, str(d.get("total_stocks")))
    r = get("/api/agent/v1/catalog/sectors")
    check("catalog/sectors(板块枚举)", len(r.get_json().get("data", [])) >= 20)
    r = get("/api/agent/v1/catalog/select?sector=银行")
    d = r.get_json().get("data", {})
    check("catalog/select(银行)", len(d.get("items", [])) >= 10, f"{len(d.get('items', []))}只")
    r = get("/api/agent/v1/catalog/select?sector=不存在板块")
    check("catalog/select(非法板块→400)", r.status_code == 400, f"{r.status_code}")
    r = get("/api/agent/v1/catalog/describe/600036")
    d = r.get_json().get("data", {})
    check("catalog/describe(600036)", d.get("name") == "招商银行", d.get("name", ""))
    r = get("/api/agent/v1/catalog/search?q=银行")
    check("catalog/search(银行>0)", len(r.get_json().get("data", [])) > 0)
    r = get("/api/agent/v1/catalog/boards")
    check("catalog/boards(东财板块)", len(r.get_json().get("data", [])) > 0)
    r = get("/api/agent/v1/catalog/leader-of?name=银行")
    check("catalog/leader-of(银行)", r.status_code == 200)

    # ── R: 因子 / K线 ─────────────────────────────────────────────────
    r = get("/api/agent/v1/factors")
    check("factors(因子清单)", len(r.get_json().get("data", [])) >= 25,
          f"{len(r.get_json().get('data', []))}个")
    r = get("/api/agent/v1/klines?code=600036&days=30")
    d = r.get_json().get("data", {})
    check("klines(600036,30日)", d.get("bars", 0) == 30, f"{d.get('bars')}根")

    # ── W: 声明式策略 CRUD ───────────────────────────────────────────
    r = post("/api/agent/v1/strategies", json=STRATEGY)
    sresp = r.get_json()
    check("create strategy(200)", r.status_code == 200, f"{r.status_code}")
    sid = sresp.get("data", {}).get("id") if r.status_code == 200 else None
    check("create strategy(返回id)", sid is not None, f"id={sid}")
    r = get(f"/api/agent/v1/strategies/{sid}")
    check("get strategy", r.get_json().get("data", {}).get("id") == sid)
    r = get("/api/agent/v1/strategies")
    check("list strategies(>=1)", len(r.get_json().get("data", [])) >= 1)

    # ── B: 异步回测 → 轮询 ───────────────────────────────────────────
    r = post("/api/agent/v1/backtest/run", json={"strategy_id": sid, "params": {}})
    job_id = r.get_json().get("data", {}).get("job_id") if r.status_code == 200 else None
    check("backtest/run(返回job_id)", r.status_code == 200 and bool(job_id), f"job={job_id}")
    # 轮询直到完成
    terminal = None
    for _ in range(60):
        jr = get(f"/api/agent/v1/jobs/{job_id}")
        jd = jr.get_json().get("data", {})
        terminal = jd.get("status")
        if terminal in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.5)
    check("backtest job 完成(succeeded)", terminal == "succeeded", f"status={terminal}")
    if terminal == "succeeded":
        jd = get(f"/api/agent/v1/jobs/{job_id}").get_json().get("data", {})
        res = jd.get("decoded_result", {})
        m = res.get("metrics", {})
        check("backtest 指标(总收益率)", "total_return" in m, f"total_return={m.get('total_return')}%")
        check("backtest 指标(夏普)", "sharpe" in m, f"sharpe={m.get('sharpe')}")
        check("backtest 无致命错误", res.get("error") is None)
    r = post(f"/api/agent/v1/jobs/{job_id}/cancel")
    check("cancel job(已结束→409或200)", r.status_code in (200, 409), f"{r.status_code}")

    # ── W: watchlist ─────────────────────────────────────────────────
    r = post("/api/agent/v1/watchlist", json={"code": "600519", "name": "贵州茅台"})
    check("watchlist add", r.status_code == 200)
    r = get("/api/agent/v1/watchlist")
    check("watchlist list(含600519)", any(x["code"] == "600519" for x in r.get_json().get("data", [])))
    r = client.delete("/api/agent/v1/watchlist/600519", headers=h_ok)
    check("watchlist remove", r.get_json().get("data", {}).get("removed") is True)

    # ── T: paper 下单(paper-only) ────────────────────────────────────
    from backend.trade_engine.engine import TradeEngine as _TE
    _te = _TE()
    _test_acct = _te.create_account(f"agent-smoke-{int(time.time())}", 100000.0)
    _test_acct_id = _test_acct["id"] if isinstance(_test_acct, dict) else _test_acct
    r = post("/api/agent/v1/paper/orders", json={
        "code": "600036", "side": "buy", "qty": 100, "order_type": "market",
        "account_id": _test_acct_id})
    d = r.get_json().get("data", {}) if r.status_code == 200 else {}
    check("paper order(被接受)", r.status_code == 200 and d.get("note") == "paper", f"{r.status_code}")

    # ── 幂等: 用同一 Idempotency-Key 提交回测 → 重放 ──────────────────
    r1 = post("/api/agent/v1/backtest/run", json={"strategy_id": sid}, headers={
        **h_ok, "Idempotency-Key": "idem-test-1"})
    check("幂等(首次保留)", r1.status_code == 200, f"{r1.status_code}")

    # ── kill switch ──────────────────────────────────────────────────
    r = post("/api/agent/v1/paper/kill-switch")
    check("kill-switch(熔断)", r.status_code == 200, f"{r.status_code}")

    # ── 自清理: 撤销测试 token / 删测试策略 / 删测试账户 ─────────────
    from backend.agent import services as _svc
    gw.revoke_token_record(tok_rwbt["id"])
    gw.revoke_token_record(tok_r["id"])
    try:
        _svc.delete_strategy("default", sid) if sid else None
    except Exception:
        pass
    try:
        _te.delete_account(_test_acct_id)
    except Exception:
        pass

    # ── 汇总 ─────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'='*60}")
    print(f"M1 Agent Gateway 冒烟: {passed}/{total} 通过")
    fails = [l for l, ok, _ in results if not ok]
    if fails:
        print("未通过项:")
        for f in fails:
            print(f"  - {f}")
    print("[OK] Agent Gateway + MCP 骨架可用" if passed == total else "[FAIL] 存在失败")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
