# -*- coding: utf-8 -*-
"""从客户端侧消费 Agent Gateway(/api/agent/v1)的轻量 HTTP 客户端。

研究代理用它在"读宏观→选标的→建策略→异步回测→复盘修订→择优"闭环中调用网关。
所有响应按 {code, data} 信封解包；非 0 抛 GatewayError。
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

DEFAULT_BASE = "http://127.0.0.1:5000"


class GatewayError(Exception):
    def __init__(self, code, message, retriable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retriable = retriable


class GatewayClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE, timeout: int = 30):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}",
                                     "Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return self.base_url + path

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 params: Optional[dict] = None, idempotency_key: str = "") -> Any:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            r = self.session.request(method, self._url(path), json=body, params=params,
                                     headers=headers, timeout=self.timeout)
            payload = r.json()
        except Exception as e:
            raise GatewayError(-1, f"网关调用失败({method} {path}): {e}")
        if r.status_code != 200 or payload.get("code", 0) != 0:
            err = payload.get("error") or payload
            raise GatewayError(r.status_code, err.get("message", str(err)), bool(err.get("retriable")))
        return payload.get("data")

    # ── R: 宏观 ──────────────────────────────────────────────────
    def macro_regime(self) -> dict:
        return self._request("GET", "/api/agent/v1/macro/regime")

    def macro_indicators(self, category: Optional[str] = None) -> list:
        return self._request("GET", "/api/agent/v1/macro/indicators", params={"category": category})

    # ── R: 目录 / 因子 / K线 ──────────────────────────────────────
    def catalog_stats(self) -> dict:
        return self._request("GET", "/api/agent/v1/catalog/stats")

    def catalog_sectors(self) -> list:
        return self._request("GET", "/api/agent/v1/catalog/sectors")

    def catalog_select(self, **kw) -> dict:
        return self._request("GET", "/api/agent/v1/catalog/select", params={k: v for k, v in kw.items() if v})

    def factors(self, category: Optional[str] = None) -> list:
        return self._request("GET", "/api/agent/v1/factors", params={"category": category})

    def klines(self, code: str, days: int = 180) -> dict:
        return self._request("GET", "/api/agent/v1/klines", params={"code": code, "days": days})

    # ── W: 策略 ──────────────────────────────────────────────────
    def create_strategy(self, contract: dict, idempotency_key: str = "") -> dict:
        return self._request("POST", "/api/agent/v1/strategies", body=contract, idempotency_key=idempotency_key)

    def get_strategy(self, sid: int) -> dict:
        return self._request("GET", f"/api/agent/v1/strategies/{sid}")

    def update_strategy(self, sid: int, contract: dict) -> dict:
        return self._request("PATCH", f"/api/agent/v1/strategies/{sid}", body=contract)

    def list_strategies(self) -> list:
        return self._request("GET", "/api/agent/v1/strategies")

    # ── B: 异步回测 ──────────────────────────────────────────────
    def run_backtest(self, sid: int, params: Optional[dict] = None, idempotency_key: str = "") -> dict:
        return self._request("POST", "/api/agent/v1/backtest/run",
                             body={"strategy_id": sid, "params": params or {}}, idempotency_key=idempotency_key)

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/api/agent/v1/jobs/{job_id}")

    def wait_job(self, job_id: str, poll: float = 1.0, timeout: float = 180.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            j = self.get_job(job_id)
            if j and j.get("status") in ("succeeded", "failed", "cancelled"):
                return j
            time.sleep(poll)
        raise GatewayError(-1, f"job {job_id} 超时未完成")

    def backtest(self, sid: int, params: Optional[dict] = None, idempotency_key: str = "") -> dict:
        """提交异步回测并阻塞到完成，返回带 metrics 的 job。"""
        job = self.run_backtest(sid, params, idempotency_key)
        return self.wait_job(job["job_id"])

    # ── T: paper ─────────────────────────────────────────────────
    def paper_order(self, payload: dict) -> dict:
        return self._request("POST", "/api/agent/v1/paper/orders", body=payload)
