# -*- coding: utf-8 -*-
"""编号决策协议 + 确定性闸门（借鉴 PA_Agent 的二元决策树 / DecisionNodeEngine）。

思路：把交易决策拆成**编号闸门**，能客观计算的（数据可用性、规则额度、持仓风险、
资金与仓位）**由代码判定并给出结论**，模型只需要回答定性闸门（选股依据、下单）。

这样做的三个好处（也是我们加它的原因）：
  1. 省 token：模型不必自己算浮亏/回撤/剩余额度（它算得慢还容易算错）；
  2. 少被拒单：额度与合规在**决策前**就摊开，而不是下单时才被系统打回；
  3. 可审计：每天落库一份闸门结论，前端能逐条回看"系统当时怎么判的"。

闸门清单（G* 为系统判定，M* 为模型回答）：
    G0 数据可用性   —— 行情是否新鲜、持仓是否有报价（不新鲜时禁止开新仓）
    G1 风险闸门     —— 生效规则：能否开仓 / 今日剩余新仓额度 / 单票上限 / 冷静期名单
    G2 持仓处置     —— 逐票浮亏、距峰值回撤、持有天数、是否已被兜底保护锁定
    G3 市场环境     —— regime + 主要指数近 5 日
    M4 选股依据     —— 模型：给候选与理由（自主选股模式下用 screen_stocks 检索）
    G5 标的合规     —— 下单时系统自动检查（冷静期/T+1/资金/ST/流动性）
    G6 资金与仓位   —— 可用资金 → 单票上限金额、最多可买几笔
    M7 下单执行     —— 模型：place_order（可多笔）
    G8 收盘兜底     —— 系统：止损/移动止损/挂单超时
"""
from __future__ import annotations

from typing import Callable, Optional

GATE_DEFS = [
    ("G0", "数据可用性", "code"),
    ("G1", "风险闸门", "code"),
    ("G2", "持仓处置", "code"),
    ("G3", "市场环境", "code"),
    ("M4", "选股依据", "model"),
    ("G5", "标的合规", "code"),
    ("G6", "资金与仓位", "code"),
    ("M7", "下单执行", "model"),
    ("G8", "收盘兜底", "code"),
]


def _fmt_money(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1e8:
        return f"{n / 1e8:.2f}亿"
    if abs(n) >= 1e4:
        return f"{n / 1e4:.2f}万"
    return f"{n:.0f}"


def build_gates(profile_id: int, account_id: int, as_of: str,
                positions: Optional[list] = None, account: Optional[dict] = None,
                regime: Optional[dict] = None, price_fn: Optional[Callable] = None,
                data_latest: str = "") -> dict:
    """计算全部闸门，返回 {"gates": [...], "text": <给模型看的编号协议文本>, "summary": {...}}。

    positions/account 来自上下文（实盘为实时价、回放为 as-of 收盘价），本模块不自己取价。
    """
    from . import discipline as disc

    gates: list = []
    positions = list(positions or [])
    account = account or {}

    # ── G0 数据可用性 ──
    stale_days = None
    try:
        if data_latest and as_of:
            stale_days = disc._trading_gap(str(data_latest)[:10], str(as_of)[:10])
    except Exception:
        stale_days = None
    no_price = [p.get("code") for p in positions if not p.get("price")]
    g0_status = "pass"
    g0_note = ""
    if no_price:
        g0_status, g0_note = "warn", f"有 {len(no_price)} 只持仓没有报价：{', '.join(no_price[:3])}"
    if stale_days is not None and stale_days > 0:
        g0_status = "warn"
        g0_note = (f"行情最新到 {str(data_latest)[:10]}，比决策日 {as_of} 落后 "
                   f"{stale_days} 个交易日（落后时不要依据'最新价'下结论）")
    gates.append({"id": "G0", "title": "数据可用性", "kind": "code", "status": g0_status,
                  "facts": {"行情最新": data_latest or "未知", "决策日": as_of,
                            "落后交易日": stale_days, "无报价持仓": no_price},
                  "note": g0_note})

    # ── G1 风险闸门 ──
    rules = []
    try:
        rules = disc.active_rules(int(profile_id), as_of)
    except Exception:
        rules = []
    prot = {}
    try:
        prot = disc.protection_rules(int(profile_id), as_of)
    except Exception:
        prot = {}
    block_rule = next((r for r in rules if r["kind"] == "block_new_buy"), None)
    cap_rule = next((r for r in rules if r["kind"] == "max_new_positions_day"), None)
    pos_cap = next((r for r in rules if r["kind"] == "position_cap_pct"), None)
    momentum_rule = next((r for r in rules if r["kind"] == "require_momentum_up"), None)
    can_buy = not block_rule
    quota = int(cap_rule.get("value") or 0) if cap_rule else None
    gates.append({"id": "G1", "title": "风险闸门", "kind": "code",
                  "status": "block" if block_rule else ("warn" if (cap_rule or momentum_rule) else "pass"),
                  "facts": {"可开新仓": can_buy,
                            "禁买原因": (block_rule.get("reason") if block_rule else ""),
                            "今日新仓额度": quota,
                            "单票仓位上限%": (float(pos_cap["value"]) if pos_cap else None),
                            "买入需动量为正": bool(momentum_rule),
                            "兜底止损%": prot.get("stop_loss_pct"),
                            "冷静期(交易日)": prot.get("sell_reentry_cooldown")},
                  "note": ("当前禁止开新仓：" + str(block_rule.get("reason") or "规则"))
                          if block_rule else ""})

    # ── G2 持仓处置 ──
    rows = []
    must_handle = []
    for p in positions:
        code = str(p.get("code") or "")
        if not code:
            continue
        cost = float(p.get("cost_price") or 0)
        px = float(p.get("price") or 0)
        pnl_pct = (px / cost - 1) * 100 if (cost > 0 and px > 0) else None
        closes = []
        try:
            buy_date = str(p.get("last_buy_date") or as_of)
            closes = disc._closes_since(code, buy_date, as_of)
        except Exception:
            closes = []
        peak = max([cost] + closes) if closes else cost
        from_peak = (px / peak - 1) * 100 if (peak > 0 and px > 0) else None
        stop = float(prot.get("stop_loss_pct") or 8)
        trail_act = float(prot.get("trailing_activation_pct") or 15)
        trail = float(prot.get("trailing_stop_pct") or 10)
        flags = []
        if pnl_pct is not None and pnl_pct <= -stop:
            flags.append(f"已触及兜底止损（{pnl_pct:.1f}% ≤ -{stop:g}%）")
        if from_peak is not None and (peak / cost - 1) * 100 >= trail_act and from_peak <= -trail:
            flags.append(f"已触发移动止损（自高点 {from_peak:.1f}%）")
        held = None
        try:
            held = disc._trading_gap(str(p.get("last_buy_date") or as_of), as_of)
        except Exception:
            held = None
        row = {"code": code, "name": p.get("name") or code, "qty": p.get("qty"),
               "浮亏%": round(pnl_pct, 2) if pnl_pct is not None else None,
               "距峰值%": round(from_peak, 2) if from_peak is not None else None,
               "持有交易日": held, "系统标记": flags,
               "你的逻辑": (p.get("thesis") or "")[:80]}
        rows.append(row)
        if flags:
            must_handle.append(f"{code} {row['name']}：" + "；".join(flags))
    gates.append({"id": "G2", "title": "持仓处置", "kind": "code",
                  "status": "warn" if must_handle else "info",
                  "facts": {"持仓数": len(rows), "明细": rows},
                  "note": ("以下持仓已触发系统保护条件，收盘会被强制卖出（你也可以现在自己卖）："
                           + " / ".join(must_handle)) if must_handle else ""})

    # ── G3 市场环境 ──
    gates.append({"id": "G3", "title": "市场环境", "kind": "code", "status": "info",
                  "facts": regime or {}, "note": ""})

    # ── M4 选股依据（模型） ──
    gates.append({"id": "M4", "title": "选股依据", "kind": "model",
                  "status": "todo", "facts": {},
                  "note": "你要回答的闸门：今天买什么？给出筛选条件与理由（自主选股模式下用 screen_stocks）。"})

    # ── G5 标的合规 ──
    gates.append({"id": "G5", "title": "标的合规", "kind": "code", "status": "info",
                  "facts": {"检查项": ["卖出冷静期", "T+1（今日买入不可卖）", "可用资金",
                                      "单票仓位上限", "ST/退市风险", "涨跌停可买性"]},
                  "note": "下单时系统自动检查；被拒会在返回里给你具体原因，按原因调整即可。"})

    # ── G6 资金与仓位 ──
    cash = float(account.get("balance") or account.get("可用资金") or 0)
    cap_pct = float(pos_cap["value"]) if pos_cap else None
    per_ticket = (cash * cap_pct / 100.0) if cap_pct else None
    gates.append({"id": "G6", "title": "资金与仓位", "kind": "code", "status": "info",
                  "facts": {"可用资金": round(cash, 2), "可用资金(简称)": _fmt_money(cash),
                            "单票上限%": cap_pct,
                            "单票最多可投": round(per_ticket, 2) if per_ticket else None,
                            "今日新仓额度": quota if quota is not None else "未限制",
                            "在途委托": len(account.get("pending_orders") or [])},
                  "note": "买入按 100 股整数倍；限价挂单会冻结资金。"})

    # ── M7 下单执行（模型） ──
    gates.append({"id": "M7", "title": "下单执行", "kind": "model", "status": "todo", "facts": {},
                  "note": "你要回答的闸门：下单几笔、什么价、多少股；不操作也要说明原因。"})

    # ── G8 收盘兜底 ──
    gates.append({"id": "G8", "title": "收盘兜底", "kind": "code", "status": "info",
                  "facts": {"兜底止损%": prot.get("stop_loss_pct"),
                            "移动止损": f"{prot.get('trailing_stop_pct')}%@{prot.get('trailing_activation_pct')}%",
                            "挂单超时(交易日)": prot.get("pending_expiry_days")},
                  "note": "收盘后系统会对触发的持仓强制卖出、撤销超时挂单；你不卖的它会卖。"})

    blocked = [g for g in gates if g["status"] == "block"]
    warns = [g for g in gates if g["status"] == "warn"]
    # ── 给模型的文本：只讲"你该知道的结论"和"你要回答什么"，系统项一句话带过 ──
    lines = ["【决策协议（编号闸门）】系统项已由程序判定，你只需回答标 [你] 的闸门。"]
    for g in gates:
        if g["kind"] == "code":
            facts = "；".join(f"{k}={v}" for k, v in (g["facts"] or {}).items() if k != "明细") if g["title"] != "持仓处置" \
                else f"持仓 {len(g['facts'].get('明细') or [])} 只"
            lines.append(f"· {g['id']} {g['title']}[系统·{g['status']}] {facts}"
                         + (f" —— {g['note']}" if g["note"] else ""))
            if g["title"] == "持仓处置" and g["facts"].get("明细"):
                for r in g["facts"]["明细"]:
                    lines.append(f"    - {r['code']} {r['name']} 浮亏{r['浮亏%']}% 距峰值{r['距峰值%']}% "
                                 f"持有{r['持有交易日']}日" + (f" ⚠{('；'.join(r['系统标记']))}" if r["系统标记"] else ""))
        else:
            lines.append(f"· {g['id']} {g['title']}[你] {g['note']}")
    if blocked:
        lines.append("⛔ 有闸门为 block：请勿尝试被禁止的动作（会被系统直接拒绝）。")
    if warns:
        lines.append("⚠ 有闸门为 warn：相关动作前先处理或说明。")
    return {"gates": gates, "text": "\n".join(lines),
            "summary": {"blocked": [g["id"] for g in blocked], "warned": [g["id"] for g in warns],
                        "can_buy": can_buy, "quota": quota, "positions": len(rows),
                        "must_handle": must_handle}}
