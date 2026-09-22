# -*- coding: utf-8 -*-
"""决策自洽性校验（借鉴 PA_Agent 的 coherence_checks.py P0/P1 校验）。

格式校验（protocol.validate_decision）只能保证"填得对"，管不了"自相矛盾"。
本模块检查模型**自己的说法与自己的动作是否一致**，例如：

    · 预测"看涨"却净卖出（不留仓位如何吃到上涨）
    · 预测"看跌"却净买入
    · thinking 里说"买入/加仓"，但一笔买单都没有
    · thinking 里说"减仓/清仓"，但没有任何卖单
    · 下买单但 thinking 完全没提这只票（可能是凑数单）

结论是**提示而非拒绝**（模型可能有自己的理由，比如"看涨大盘但个股见顶"），
但会一并落库并在前端展示，方便事后回看"它当时是不是自相矛盾"。
"""
from __future__ import annotations

from typing import Optional

BUY_WORDS = ("买入", "加仓", "建仓", "低吸", "开仓")
SELL_WORDS = ("卖出", "减仓", "清仓", "止损", "卖出计划", "止盈")


def _net_sign(plan: list) -> int:
    sig = 0
    for o in plan or []:
        s = str(o.get("side") or "").lower()
        if s == "buy":
            sig += 1
        elif s == "sell":
            sig -= 1
    return (sig > 0) - (sig < 0) if sig else 0


def check(decision: Optional[dict], plan: list, account: Optional[dict] = None) -> list:
    """返回不一致项列表（空 = 自洽）。"""
    d = decision or {}
    plan = plan or []
    thinking = str(d.get("thinking") or "")
    outlook = d.get("outlook") if isinstance(d.get("outlook"), dict) else {}
    direction = str(outlook.get("direction") or "")
    sig = _net_sign(plan)
    out: list = []

    if direction == "up" and sig < 0:
        out.append({"level": "warn", "kind": "outlook_vs_orders",
                    "msg": "预测看涨，但委托是净卖出 —— 若真看涨，卖出后如何吃到上涨？（如有特殊理由请在 thinking 说明）"})
    if direction == "down" and sig > 0:
        out.append({"level": "warn", "kind": "outlook_vs_orders",
                    "msg": "预测看跌，但委托是净买入 —— 判断与动作相反，确认是有意的逆势/抄底？"})

    claims_buy = any(w in thinking for w in BUY_WORDS)
    claims_sell = any(w in thinking for w in SELL_WORDS)
    has_buy = any(str(o.get("side") or "").lower() == "buy" for o in plan)
    has_sell = any(str(o.get("side") or "").lower() == "sell" for o in plan)
    if claims_buy and not has_buy and not any(w in thinking for w in ("不买", "暂不", "等待", "放弃", "未买", "无买入")):
        out.append({"level": "info", "kind": "claim_vs_orders",
                    "msg": "thinking 提到买入，但没有买单 —— 如果只是计划/观察，写明「计划不执行」会更清楚"})
    if claims_sell and not has_sell and not any(w in thinking for w in ("不卖", "暂不", "继续持有", "未卖", "无卖出")):
        out.append({"level": "info", "kind": "claim_vs_orders",
                    "msg": "thinking 提到卖出/减仓，但没有卖单（T+1 或不想卖都请写明原因）"})

    # 买单的票是否在 thinking 里被提到（防"凑数单"）
    for o in plan:
        if str(o.get("side") or "").lower() != "buy":
            continue
        code = str(o.get("code") or "")
        name = str(o.get("name") or "")
        if code and code not in thinking and (not name or name not in thinking):
            out.append({"level": "info", "kind": "order_not_mentioned",
                        "msg": f"买入 {name or code}({code}) 但 thinking 里没提到它 —— 请说明买入依据"})
            break

    # 账户事实交叉：声称空仓却持仓很多、声称满仓却大量现金（粗判，只在明显矛盾时提示）
    acct = account or {}
    try:
        pos_n = int(acct.get("positions") or 0)
        cash = float(acct.get("balance") or 0)
        total = float(acct.get("total_assets") or 0)
        if pos_n == 0 and cash > 0 and total > 0 and cash / total < 0.5:
            out.append({"level": "info", "kind": "account_mismatch",
                        "msg": "账户显示空仓但现金占比不到一半 —— 请核对上下文里的账户数据"})
    except Exception:
        pass
    return out
