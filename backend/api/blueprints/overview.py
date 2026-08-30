# -*- coding: utf-8 -*-
"""Overview — one-shot aggregate for the landing page:
accounts summary + best paper strategy + market snapshot.
"""
import json
import os

from flask import Blueprint

from ..envelope import ok
from ..paths import PAPER_RUNS_PATH

bp = Blueprint("overview", __name__, url_prefix="/api/overview")


def _accounts():
    try:
        from backend.trade_engine.engine import TradeEngine
        eng = TradeEngine()
        summaries = eng.list_account_summaries()
        for s in summaries:
            try:
                s["nav"] = eng.get_nav_history(s["account_id"]).get("nav", [])
            except Exception:
                s["nav"] = []
        return summaries
    except Exception:
        return []


def _best_strategy():
    try:
        if not os.path.exists(PAPER_RUNS_PATH):
            return None, ""
        with open(PAPER_RUNS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        runs = d.get("runs") or {}
        asof = d.get("as_of", "")
        best, best_m = None, None
        for name, r in runs.items():
            if not isinstance(r, dict) or r.get("error"):
                continue
            m = r.get("metrics") or {}
            if best_m is None or (m.get("total_return") or 0) > (best_m.get("total_return") or 0):
                best, best_m = name, m
        if best is None:
            return None, asof
        best_m = best_m or {}
        r = runs[best]
        return {
            "name": best,
            "total_return": best_m.get("total_return"),
            "cagr": best_m.get("cagr"),
            "alpha": best_m.get("alpha"),
            "sharpe": best_m.get("sharpe"),
            "max_drawdown": best_m.get("max_drawdown"),
            "rebalances": r.get("rebalances", 0),
            "holdings": len(r.get("final_holdings", {}) or {}),
        }, asof
    except Exception:
        return None, ""


def _market():
    """大盘指数 — 优先本地快照(fetch_index_prices, 快速可靠), 避免 akshare 实时被反爬阻塞总览页."""
    out = []
    try:
        from data_manager import fetch_index_prices
        data = fetch_index_prices()
        main_ids = ["sh000001", "sz399001", "sz399006"]
        out = [d for d in data if d.get("code") in main_ids]
        if out:
            return out
    except Exception:
        pass
    # 兜底: akshare 实时(带超时, 失败勿阻塞)- 仅当本地空
    try:
        import socket
        socket.setdefaulttimeout(5)
        from akshare_source import ak_get_index_spot
        data = ak_get_index_spot()
        main_ids = ["sh000001", "sz399001", "sz399006"]
        out = [d for d in data if d.get("code") in main_ids]
    except Exception:
        pass
    return out


@bp.route("")
def overview():
    strategy, asof = _best_strategy()
    return ok({
        "accounts": _accounts(),
        "strategy": strategy,
        "as_of": asof,
        "market": _market(),
    })
