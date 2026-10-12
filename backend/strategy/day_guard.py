# -*- coding: utf-8 -*-
"""day_guard.py — 每日持仓守护循环: 对模拟账户持仓逐日判定卖出并执行.

补齐全自动闭环: portfolio_paper 只做"重平衡日按排名调出", 本模块每日用
PositionGuard+保护规约判定"硬风控卖出"(止损/止盈/时间止损), 触发即卖出.
**保护优先于排名** —— 买后暴跌→止损立即卖, 涨到位→止盈锁盈, 持有超期→时间止损.

数据流 (每日17:00 update_daily 调用, 或手动):
  ① 读模拟账户全部持仓(TradeEngine.get_positions, 取 active 账户)
  ② 对每只持仓: 读该股K线(load_klines), 用 last_buy_date 恢复持有期,
     重建 ProtectionState(cost_price=entry, highest/lowest=当前), 当日bar判定
  ③ 触发 → TradeEngine.place_order(sell, market) 执行卖出; 记入卖出日志
  ④ 落库 data/day_guard_log.json (每只票的判定结果/是否卖出/原因)

隔离: 只卖模拟账户持仓; 不新建仓位, 不改策略契约. 卖出后现金回账户, 供下轮重平衡.
"""
from __future__ import annotations

import os, json
from datetime import datetime

from backend.strategy.position_guard import PositionGuard
from backend.strategy.sell_rules import SellRuleSet, reason_cn
from backend.strategy.data import load_klines
from backend.api.paths import DATA_DIR

GUARD_LOG = os.path.join(DATA_DIR, "day_guard_log.json")


def _active_accounts(engine):
    return [a for a in engine.list_accounts() if a.get("is_active")]


def run_day_guard(account_id=None, rule_set=None, engine=None, progress=None,
                  dry_run=True) -> dict:
    """每日持仓守护. dry_run=True 只判定不真卖(预览); 生产调用传 dry_run=False.

    返回 {as_of, account_id, checked:[{code,name,cost,reason,reason_cn,exec_price,action}], sold:[...]}.
    """
    def _emit(m):
        if progress:
            try: progress(m)
            except Exception: pass
    from backend.trade_engine.engine import TradeEngine
    engine = engine or TradeEngine()
    rules = rule_set or SellRuleSet.build()
    guard = PositionGuard(rules)

    accounts = [engine.get_account(account_id)] if account_id else _active_accounts(engine)
    accounts = [a for a in accounts if a]
    checked, sold = [], []

    for acc in accounts:
        aid = acc["id"]
        positions = engine.get_positions(aid)
        if not positions:
            _emit(f"账户#{aid} 无持仓")
            continue
        _emit(f"账户#{aid} 检查 {len(positions)} 只持仓(保护优先) ...")
        for pos in positions:
            code = pos["code"]; name = pos.get("name", "")
            entry = float(pos.get("cost_price") or 0)
            if entry <= 0:
                continue
            try:
                kres = load_klines(code, limit=1200)
                k = kres[0] if isinstance(kres, tuple) else kres
            except Exception as e:
                _emit(f"  {code} 读K线失败: {str(e)[:40]}")
                checked.append({"code": code, "name": name, "cost": entry,
                                "reason": "", "action": "skip", "note": "读K线失败"})
                continue
            if not k:
                checked.append({"code": code, "name": name, "cost": entry,
                                "reason": "", "action": "skip", "note": "无K线"})
                continue
            # 恢复持有期: 从 last_buy_date 到最新一根K线的 bar 数
            last_buy = pos.get("last_buy_date", "")
            dates = [str(x.get("date", ""))[:10] for x in k]
            entry_idx = 0
            if last_buy:
                buy_compact = str(last_buy).replace("-", "")
                for i, d in enumerate(dates):
                    if str(d).replace("-", "") >= buy_compact:
                        entry_idx = i
                        break
            latest = k[-1]
            bar = {"open": float(latest.get("open", latest.get("close", entry))),
                   "high": float(latest.get("high", latest.get("close", entry))),
                   "low": float(latest.get("low", latest.get("close", entry))),
                   "close": float(latest.get("close", entry))}
            bar_index = max(0, len(k) - 1 - entry_idx)
            st = guard.new_state(code, entry_price=entry, entry_index=entry_idx)
            # 先回放该股从建仓到昨日的最高/最低(供移动止损), 再用当日bar判定
            for h in k[entry_idx:entry_idx + max(0, len(k) - 1 - entry_idx)]:
                st.highest_price = max(st.highest_price, float(h.get("high", entry)))
                st.lowest_price = min(st.lowest_price, float(h.get("low", entry)))
            sig = guard.evaluate(st, bar, bar_index)
            if sig is None:
                checked.append({"code": code, "name": name, "cost": entry,
                                "reason": "", "action": "hold",
                                "float": round((bar["close"] / entry - 1) * 100, 2)})
                continue
            # 触发卖出
            action = "sell" if not dry_run else "preview_sell"
            if not dry_run:
                try:
                    o = engine.place_order(aid, code, name, "sell", "market",
                                           sig.exec_price, pos["qty"],
                                           current_price=bar["close"])
                    if o and o[1]:
                        _emit(f"  🔴 卖出 {name}({code}) {pos['qty']}股 @{bar['close']:.2f} · {sig.reason_cn}")
                except Exception as e:
                    _emit(f"  {code} 卖出失败: {str(e)[:40]}")
            else:
                _emit(f"  ⚠(预览) {name}({code}) 触发{sig.reason_cn} 拟卖 @{sig.exec_price:.2f}")
            sold.append({"code": code, "name": name, "cost": entry,
                         "reason": sig.reason, "reason_cn": sig.reason_cn,
                         "exec_price": sig.exec_price, "action": action})
            checked.append({"code": code, "name": name, "cost": entry,
                            "reason": sig.reason, "reason_cn": sig.reason_cn,
                            "exec_price": sig.exec_price, "action": action})

    out = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "account_id": account_id, "dry_run": dry_run, "checked": checked, "sold": sold,
           "n_checked": len(checked), "n_sold": len(sold)}
    try:
        with open(GUARD_LOG, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return out


if __name__ == "__main__":
    import sys
    _dry = "--execute" not in sys.argv
    r = run_day_guard(dry_run=_dry)
    print(f"检查 {r['n_checked']} 只 · 触发卖出 {r['n_sold']} 只 · dry_run={r['dry_run']}")
    for c in r["checked"]:
        if c.get("reason_cn"):
            print(f"  🔴 {c['name']}({c['code']}) {c['reason_cn']} @{c.get('exec_price')}")
