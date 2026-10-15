# -*- coding: utf-8 -*-
"""实盘蓝图 —— 把 trade-automation 的操作工具变成软件功能。

## 分工
- 本文件只负责 **HTTP 编排**：参数校验、只读/写入分流、把工具产物包成信封。
- 真正的进程调用与产物解析在 `backend/trade_bridge.py`。

## 安全分级（核心设计，改动请勿放松）
| 级别 | 端点 | 说明 |
| --- | --- | --- |
| 只读 | `/api/live/status` `/snapshot-list` `/fills` `/snapshots/<name>` | 不碰客户端，纯读文件 |
| 读客户端 | `/api/live/query/<panel>` `/quote` | 会驱动客户端的只读面板，不产生委托 |
| 有副作用 | `/api/live/startup` | 会拉起/登录客户端（不改账户资金） |
| **写** | `/api/live/orderflow` | **会产生真实委托**——需 `confirm=true` |

**写操作的闸门**：必须带 `confirm=true`，且提交类（`--submit`）还要 `submit=true`。
两级都显式给出才会执行；少一个就返回 400 并说明缺什么。这样"误点一下"不会下单。
"""
import os
import re

from flask import Blueprint, request

from ..envelope import ok, err
from .. import trade_bridge as tb

bp = Blueprint("live", __name__, url_prefix="/api/live")

# 只读面板白名单（对应 `--query TdxW <panel>`）
PANELS = {
    "positions": ("positions", "query.log"),
    "deals": ("deals", "query.log"),
    "cancel": ("cancel", "query.log"),
    "funds": ("funds", "query.log"),
}

# 标的代码：6 位数字。用于 quote / orderflow，防止把任意字符串拼进命令行。
_RE_CODE = re.compile(r"^\d{6}$")
# 订单数量：数字 或 all/max
_RE_QTY = re.compile(r"^(\d{1,9}|all|max)$")
# 价格：数字 或 市价参考/auto
_RE_PRICE = re.compile(r"^(\d{1,7}(\.\d{1,3})?|市价参考|auto)$")


def _n(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ────────────────────────── 状态 / 只读文件 ──────────────────────────

@bp.route("/status")
def status():
    """工具可用性 + 最近一次结果 + 关键文件时间 + 最近快照。
    纯文件读取，不驱动客户端，可安全轮询。"""
    return ok(tb.status_summary())


@bp.route("/fills")
def fills():
    """当日成交回传（对账用）。默认今天。"""
    import time
    d = request.args.get("date") or time.strftime("%Y%m%d")
    if not (d.isdigit() and len(d) == 8):
        return err(400, "bad_date", "date 需为 yyyymmdd")
    rows = tb.read_fills(d)
    return ok({"date": d, "count": len(rows), "fills": rows})


@bp.route("/idempotency")
def idempotency():
    """幂等锁记录：每笔已提交委托及其状态（判断"是否已经下过这一单"）。"""
    return ok({"entries": tb.read_idempotency()})


@bp.route("/snapshots")
def snapshots():
    return ok({"snapshots": tb.list_snapshots(_n(request.args.get("limit"), 30) or 30)})


@bp.route("/snapshots/<name>")
def snapshot(name):
    j = tb.read_snapshot(name)
    if j is None:
        return err(404, "not_found", "快照不存在或文件名非法")
    return ok(j)


# ────────────────────────── 读客户端（只读） ──────────────────────────

@bp.route("/query/<panel>")
def query(panel):
    """读客户端面板。支持 ?bg=1 用后台模式（不抢前台焦点）。

    注意：这些命令会驱动券商客户端，**属于只读面板但仍需客户端已登录**。
    未登录时工具会明确失败，不会产生误导性的空结果。
    """
    if panel not in PANELS:
        return err(400, "bad_panel", f"面板必须是 {list(PANELS)} 之一")
    sub, log = PANELS[panel]
    args = ["--query", "TdxW", sub]
    if request.args.get("bg") in ("1", "true"):
        args.append("--bg")
    r = tb.run_readonly(args, timeout=_n(request.args.get("timeout"), 120) or 120, log_name=log)
    return ok(r)


@bp.route("/quote")
def quote():
    """实时行情（现价/涨停/昨收/跌停）。支持批量：?codes=600000,000001"""
    raw = (request.args.get("codes") or "").strip()
    codes = [c for c in re.split(r"[,\s]+", raw) if c]
    if not codes:
        return err(400, "no_codes", "需要 codes=600000,000001")
    bad = [c for c in codes if not _RE_CODE.match(c)]
    if bad:
        return err(400, "bad_code", f"代码需为 6 位数字，非法：{bad}")
    if len(codes) > 50:
        return err(400, "too_many", "单次最多 50 只")
    args = ["--query", "TdxW", "quote", ",".join(codes)]
    if request.args.get("bg") in ("1", "true"):
        args.append("--bg")
    r = tb.run_readonly(args, timeout=_n(request.args.get("timeout"), 180) or 180, log_name="query.log")
    return ok(r)


# ────────────────────────── 有副作用（不改资金） ──────────────────────────

@bp.route("/startup", methods=["POST"])
def startup():
    """一键启动流水线：拉起客户端 → 清弹窗 → 登录 → 进交易界面 → 回资金+持仓。

    会启动/登录客户端，但**不下单、不改资金**。属于"有副作用但不危险"，
    因此不加 confirm 闸门，但仍记录在 last-result.json 里可审计。
    """
    body = request.get_json(silent=True) or {}
    cred = body.get("cred_file") or os.environ.get("SC_TRADE_CRED", "E:/certs/k.txt")
    args = ["--startup", "TdxW", cred]
    if body.get("bg"):
        args.append("--bg")
    r = tb.run_readonly(args, timeout=_n(body.get("timeout"), 240) or 240, log_name="startup.log")
    return ok(r)


@bp.route("/snapshot", methods=["POST"])
def snapshot_take():
    """收盘快照：确保就绪 → 读 资金+持仓+成交+委托 → 存档。"""
    body = request.get_json(silent=True) or {}
    cred = body.get("cred_file") or os.environ.get("SC_TRADE_CRED", "E:/certs/k.txt")
    r = tb.run_readonly(["--snapshot", "TdxW", cred],
                        timeout=_n(body.get("timeout"), 240) or 240, log_name="startup.log")
    return ok(r)


# ────────────────────── 会话解锁（券商交易保护超时重锁） ──────────────────────
#
# 与首次登录是两条不同的路径：
#   首次登录 → 顶层弹窗（账号 + 密码两个输入框）
#   超时重锁 → **嵌在主窗口里的对话框**（无标题、只有 1 个密码框）
#   所以 `--logintest` 找不到它，必须走工具的 `--unlock`。
#
# 为什么这个端点比其它"读"端点更敏感：
#   它会**代替人输入交易密码**。券商普遍有"密码错误 N 次锁定"，
#   所以工具有**登录自锁**（login-guard.json：密码被判错后拒绝再试）与
#   **最多尝试 1 次**的硬约束。本端点不放松其中任何一条：
#   不提供"重试"参数、不做循环、失败只如实回报并让自锁生效。

@bp.route("/unlock", methods=["POST"])
def unlock():
    """解锁被（交易保护）锁定的交易界面。

    请求体（都可选）：
      { "cred_file": "E:/certs/k.txt", "timeout": 180 }

    安全约束（由工具侧强制，本层不改）：
      · 密码只从凭据文件读，**绝不经过 HTTP 请求体**，也不落日志
      · 键盘输入只进前台窗口，未到前台即中止
      · **最多尝试 1 次**；失败即写 login-guard.json 自锁，防止连续失败锁账户
    """
    body = request.get_json(silent=True) or {}
    cred = body.get("cred_file") or os.environ.get("SC_TRADE_CRED", "E:/certs/k.txt")
    r = tb.run_readonly(["--unlock", "TdxW", cred],
                        timeout=_n(body.get("timeout"), 200) or 200, log_name="unlock.log")
    return ok(r)


# ────────────────────────── 写：真实委托 ──────────────────────────

@bp.route("/orderflow", methods=["POST"])
def orderflow():
    """**会产生真实委托**的下单/撤单/预演。

    请求体：
      {
        "mode": "buy"|"sell"|"buy-multi"|"sell-multi"|"cancel",
        "code": "600000",        # 单笔时必填（multi 用 legs）
        "price": "市价参考" | 5.26,
        "qty": "max" | "all" | 100,
        "legs": "<c:p:q>;<c:p:q>",  # multi 模式
        "cancel_scope": "all-buy"|"all-sell",
        "submit": true,          # 是否真提交（false = 仅预演，不提交）
        "confirm": true,         # 必须为 true，否则拒绝
        "bg": true,
        "yes": true,             # 跳过人工确认框（agent 模式）
        "allow_st": false        # 允许 ST（默认拒绝）
      }

    闸门：`confirm=true` 是硬要求；`submit=true` 才会带 `--submit`。
    两者都给了才可能真正下单——少一个就 400，避免误点。
    """
    body = request.get_json(silent=True) or {}
    if body.get("confirm") is not True:
        return err(400, "need_confirm",
                   "下单会立即产生真实委托，需要 confirm=true 明确确认")

    mode = (body.get("mode") or "").strip()
    if mode not in ("buy", "sell", "buy-multi", "sell-multi", "cancel"):
        return err(400, "bad_mode",
                   "mode 必须是 buy / sell / buy-multi / sell-multi / cancel")

    submit = body.get("submit") is True
    args = ["--orderflow", "TdxW"]

    if mode in ("buy", "sell"):
        code = str(body.get("code") or "").strip()
        if not _RE_CODE.match(code):
            return err(400, "bad_code", "code 需为 6 位数字")
        price = body.get("price")
        price = "市价参考" if price in (None, "", "auto", "市价参考") else str(price)
        if not _RE_PRICE.match(price):
            return err(400, "bad_price", "price 需为数字，或 市价参考/auto")
        qty = str(body.get("qty") if body.get("qty") is not None else "max")
        if not _RE_QTY.match(qty):
            return err(400, "bad_qty", "qty 需为数字，或 all/max")
        args += [mode, code, price, qty]

    elif mode in ("buy-multi", "sell-multi"):
        legs = str(body.get("legs") or "").strip()
        if not legs:
            return err(400, "no_legs", "批量模式需要 legs，如 600000:市价参考:max;000001:5.0:100")
        for leg in legs.split(";"):
            parts = leg.split(":")
            if len(parts) != 3 or not _RE_CODE.match(parts[0]) \
               or not _RE_PRICE.match(parts[1]) or not _RE_QTY.match(parts[2]):
                return err(400, "bad_legs", f"腿格式非法：{leg}（应为 代码:价格:数量）")
        args += [mode, legs]

    else:  # cancel
        scope = str(body.get("cancel_scope") or "all-buy")
        if scope not in ("all-buy", "all-sell"):
            return err(400, "bad_scope", "cancel_scope 需为 all-buy / all-sell")
        args += ["cancel", scope]

    if submit:
        args.append("--submit")
        if body.get("yes") is True:
            args.append("--yes")
    if body.get("allow_st"):
        args.append("--allow-st")
    if body.get("bg"):
        args.append("--bg")

    # 提交类给更长的超时（要过三重闭环复核）
    timeout = _n(body.get("timeout"), 300 if submit else 180) or 180
    r = tb.run_readonly(args, timeout=timeout, log_name="orders.log")
    r["submitted"] = bool(submit)
    r["mode"] = mode
    return ok(r)
